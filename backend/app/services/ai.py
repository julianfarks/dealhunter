"""Asistente de IA opcional.

Diseño seguro: el modelo (si hay clave en el SERVIDOR) sólo clasifica la instrucción en una intención con
parámetros; la ejecución es determinista y usa únicamente datos reales del usuario. Sin clave, se usa el
intérprete por reglas (`aiparse`). Nunca se predicen precios futuros ni se califica una oferta sin datos.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..aiparse import classify_intent
from ..config import get_settings
from ..connectors.http import get_client
from ..models import AlertKind, Promotion, TrackedProduct, User
from ..util import D, fmt_money, pct_change
from . import compare as compare_svc
from . import history as history_svc
from .fx import load_rates
from .tracking import set_target, upsert_alert
from .views import latest_prices, potential_saving

log = logging.getLogger("dealhunter.ai")

ACTIONS = ["set_target", "set_pct", "set_any_drop", "set_historic_low", "find_promotions", "compare",
           "near_target", "top_savings", "review_first", "explain", "unknown"]

_SYSTEM = (
    "Clasificas instrucciones en español de un usuario de una app de seguimiento de precios. "
    "Llama SIEMPRE a la herramienta interpret_command. 'amount' es un importe en pesos/dólares/euros como número "
    "(sin símbolos). 'pct' es un porcentaje. 'n' es la cantidad de productos pedida. Si no encaja, action=unknown. "
    "No inventes datos ni respondas al usuario."
)


def _llm_intent(text: str) -> dict | None:
    s = get_settings()
    if not s.anthropic_api_key:
        return None
    tool = {
        "name": "interpret_command", "description": "Intención y parámetros de la instrucción del usuario",
        "input_schema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ACTIONS}, "amount": {"type": "number"},
            "pct": {"type": "number"}, "n": {"type": "integer"}}, "required": ["action"]},
    }
    try:
        resp = get_client().post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": s.ai_model, "max_tokens": 200, "system": _SYSTEM, "tools": [tool],
                  "tool_choice": {"type": "tool", "name": "interpret_command"},
                  "messages": [{"role": "user", "content": text[:500]}]},
            timeout=20,
        )
        if resp.status_code != 200:
            return None
        for block in resp.json().get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "interpret_command":
                data = block.get("input") or {}
                if data.get("action") not in ACTIONS:
                    return None
                out = {"action": data["action"]}
                if data.get("amount") is not None:
                    out["amount"] = str(Decimal(str(data["amount"])))
                if data.get("pct") is not None:
                    out["pct"] = str(Decimal(str(data["pct"])))
                if data.get("n") is not None:
                    out["n"] = max(1, min(20, int(data["n"])))
                return out
    except (InvalidOperation, ValueError, TypeError, Exception):  # noqa: B014 - la IA es opcional
        log.warning("La IA no pudo interpretar la instrucción; se usa el intérprete por reglas")
    return None


def interpret(text: str) -> dict:
    intent = _llm_intent(text)
    rules = classify_intent(text)
    if intent is None:
        return {**rules, "engine": "rules"}
    # Si ambos entienden algo distinto, se prioriza la regla cuando hay importe explícito (más fiable).
    if rules["action"] != "unknown" and "amount" in rules and intent.get("action") == "set_target":
        intent["amount"] = rules["amount"]
    return {**intent, "engine": "llm"}


def _items(db: Session, user_id: int) -> list[TrackedProduct]:
    return list(db.scalars(select(TrackedProduct).where(
        TrackedProduct.user_id == user_id, TrackedProduct.deleted.is_(False),
        TrackedProduct.archived.is_(False), TrackedProduct.purchased.is_(False))))


def execute(db: Session, user: User, intent: dict, tracked: TrackedProduct | None) -> dict:
    action = intent["action"]
    rates = load_rates(db)

    def need_product() -> dict | None:
        if tracked is None:
            return {"ok": False, "message": "Abre un producto de tu carrito y vuelve a pedírmelo para saber a cuál te refieres."}
        return None

    if action in ("set_target", "set_pct", "set_any_drop", "set_historic_low"):
        if (err := need_product()) is not None:
            return err
        li = tracked.listing
        cur = li.currency
        if action == "set_target":
            amount = D(intent["amount"])
            prefs_cur = user.preferences.currency if user.preferences else "COP"
            set_target(db, tracked, amount, prefs_cur)
            db.commit()
            return {"ok": True, "action": action, "message":
                    f"Listo: te avisaré cuando «{li.title or 'este producto'}» llegue a {fmt_money(amount, prefs_cur)} o menos."
                    " Es un aviso: no puedo garantizar que baje a ese precio.",
                    "changes": {"tracked_id": tracked.id, "target_price": str(amount), "currency": prefs_cur}}
        if action == "set_pct":
            pct = D(intent["pct"])
            upsert_alert(db, tracked, AlertKind.PCT_DROP.value, pct)
            db.commit()
            return {"ok": True, "action": action, "message":
                    f"Listo: te avisaré cuando baje al menos un {pct}% respecto al precio registrado al añadirlo.",
                    "changes": {"tracked_id": tracked.id, "alert": "pct_drop", "threshold": str(pct)}}
        if action == "set_any_drop":
            upsert_alert(db, tracked, AlertKind.ANY_DROP.value)
            db.commit()
            return {"ok": True, "action": action, "message": "Listo: te avisaré cuando baje cualquier cantidad.",
                    "changes": {"tracked_id": tracked.id, "alert": "any_drop"}}
        upsert_alert(db, tracked, AlertKind.HISTORIC_LOW.value)
        db.commit()
        return {"ok": True, "action": action, "message":
                "Listo: te avisaré cuando alcance un mínimo histórico registrado (necesita al menos 3 observaciones).",
                "changes": {"tracked_id": tracked.id, "alert": "historic_low"}}

    if action == "find_promotions":
        if (err := need_product()) is not None:
            return err
        promos = db.scalars(select(Promotion).where(
            Promotion.listing_id == tracked.listing_id, Promotion.active.is_(True))).all()
        if not promos:
            return {"ok": True, "action": action, "message":
                    "No hay promociones ni cupones verificables registrados para este producto en este momento. "
                    "No puedo confirmar que existan otras.", "data": []}
        lines = [f"• {p.description}" for p in promos]
        return {"ok": True, "action": action, "message": "Promociones registradas:\n" + "\n".join(lines),
                "data": [{"id": p.id, "origin": p.origin, "description": p.description} for p in promos]}

    if action == "compare":
        if (err := need_product()) is not None:
            return err
        offers = compare_svc.related_offers(db, tracked.listing, rates)
        cands, errs = compare_svc.external_candidates(tracked.listing)
        if not offers and not cands:
            return {"ok": True, "action": action, "message":
                    "No encontré el mismo artículo en otras tiendas con los datos disponibles"
                    + (f" ({'; '.join(errs)})" if errs else "") + ".", "data": []}
        lines = [f"• {o.store_name}: {fmt_money(o.price, o.currency)} — {'coincidencia exacta' if o.match == 'exact' else 'aproximada'}"
                 for o in offers]
        lines += [f"• {c['store']}: {c['price']} {c['currency']} — aproximada" for c in cands]
        return {"ok": True, "action": action, "message": "Ofertas encontradas:\n" + "\n".join(lines),
                "data": {"related": len(offers), "candidates": len(cands)}}

    if action == "explain":
        if (err := need_product()) is not None:
            return err
        h = history_svc.build_history(db, tracked.listing, "30d")
        pts = h["points"]
        if len(pts) < 2:
            return {"ok": True, "action": action, "message":
                    "Todavía tengo muy pocas observaciones de este producto para explicar cambios. "
                    + " ".join(h["warnings"])}
        last, prev = pts[-1], pts[-2]
        st = h["stats"]
        msg = (f"El último cambio registrado fue de {fmt_money(D(prev['price']), prev['currency'])} a "
               f"{fmt_money(D(last['price']), last['currency'])} ({last['change_pct']}%). "
               f"En el periodo mostrado el mínimo fue {fmt_money(D(st['min']), h['currency'])} y el máximo "
               f"{fmt_money(D(st['max']), h['currency'])}. ")
        msg += " ".join(h["warnings"]) + " No puedo predecir si volverá a bajar."
        return {"ok": True, "action": action, "message": msg.strip(), "data": {"stats": st}}

    items = _items(db, user.id)
    prices = latest_prices(db, [t.listing_id for t in items])

    if action == "near_target":
        thr = D(str(get_settings().near_target_threshold_pct))
        rows = []
        for t in items:
            o = prices.get(t.listing_id)
            if o is None or t.target_price is None or (t.target_currency or o.currency) != o.currency:
                continue
            cur, tgt = D(o.price), D(t.target_price)
            gap = (cur - tgt) / tgt * 100
            if gap <= thr:
                rows.append((gap, t, cur, tgt, o.currency))
        rows.sort(key=lambda r: r[0])
        if not rows:
            return {"ok": True, "action": action, "message":
                    "Ningún producto con precio objetivo está cerca de alcanzarlo con los datos actuales.", "data": []}
        lines = [f"• {t.listing.title or 'Producto'}: {fmt_money(cur, c)} (objetivo {fmt_money(tgt, c)})"
                 + (" — ¡ya lo alcanzó!" if cur <= tgt else f" — a {abs(round(gap, 1))}% del objetivo")
                 for gap, t, cur, tgt, c in rows]
        return {"ok": True, "action": action, "message": "Cerca de tu precio objetivo:\n" + "\n".join(lines),
                "data": [{"tracked_id": r[1].id} for r in rows]}

    if action in ("top_savings", "review_first"):
        n = int(intent.get("n", 5))
        scored = []
        for t in items:
            o = prices.get(t.listing_id)
            if o is None:
                continue
            cur = D(o.price)
            saving = potential_saving(t, cur, o.currency)
            pct = pct_change(D(t.initial_price), cur) if (t.initial_price is not None and t.initial_currency == o.currency) else None
            scored.append((t, cur, o.currency, saving, pct))
        if action == "top_savings":
            ranked = sorted([r for r in scored if r[3] is not None], key=lambda r: r[4])[:n]
            if not ranked:
                return {"ok": True, "action": action, "message":
                        "Todavía ningún producto tiene un precio por debajo del que registramos al añadirlo. "
                        "El ahorro potencial se calcula sólo con precios observados.", "data": []}
            lines = [f"• {t.listing.title or 'Producto'}: ahorro potencial {fmt_money(sv, c)} ({pct}%)"
                     for t, cur, c, sv, pct in ranked]
            return {"ok": True, "action": action, "message":
                    "Mayor ahorro potencial (frente al precio registrado al añadirlos; no es dinero ahorrado):\n"
                    + "\n".join(lines), "data": [{"tracked_id": r[0].id} for r in ranked]}
        scored2 = []
        for t, cur, c, sv, pct in scored:
            score, reasons = 0.0, []
            if t.target_price is not None and (t.target_currency or c) == c and cur <= D(t.target_price):
                score += 100
                reasons.append("alcanzó tu precio objetivo")
            if pct is not None and pct < 0:
                score += min(50, abs(float(pct)))
                reasons.append(f"bajó {abs(pct)}% desde que lo añadiste")
            if t.priority:
                score += 10 * t.priority
                reasons.append("tiene prioridad alta")
            if reasons:
                scored2.append((score, t, reasons))
        scored2.sort(key=lambda r: -r[0])
        scored2 = scored2[:n]
        if not scored2:
            return {"ok": True, "action": action, "message":
                    "Ahora mismo ningún producto destaca para revisar primero con los datos disponibles.", "data": []}
        lines = [f"• {t.listing.title or 'Producto'}: {', '.join(r)}" for _, t, r in scored2]
        return {"ok": True, "action": action, "message": "Conviene revisar primero:\n" + "\n".join(lines),
                "data": [{"tracked_id": r[1].id} for r in scored2]}

    return {"ok": False, "action": "unknown", "message":
            "No entendí la instrucción. Prueba con «Avísame cuando baje de 150.000 pesos», «¿Cuáles están cerca "
            "del precio objetivo?» o «Busca si hay una promoción para este producto»."}
