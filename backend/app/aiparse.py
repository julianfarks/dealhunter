"""Intérprete determinista de instrucciones en español (sin IA externa).

Sirve como alternativa cuando no hay clave de IA configurada y como validación del resultado cuando sí la hay.
Sólo clasifica la intención y extrae parámetros: la ejecución siempre usa datos reales del usuario.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


_UNITS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21,
    "veintiuno": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_TENS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90}
_HUND = {
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300, "cuatrocientos": 400, "quinientos": 500,
    "seiscientos": 600, "setecientos": 700, "ochocientos": 800, "novecientos": 900,
}
_WORD_RE = "|".join(sorted([*_UNITS, *_TENS, *_HUND, "mil", "millon", "millones"], key=len, reverse=True))


def _words_to_number(tokens: list[str]) -> int | None:
    total = 0
    current = 0
    seen = False
    for tok in tokens:
        if tok == "y":
            continue
        if tok in _UNITS:
            current += _UNITS[tok]
        elif tok in _TENS:
            current += _TENS[tok]
        elif tok in _HUND:
            current += _HUND[tok]
        elif tok == "mil":
            total += (current or 1) * 1000
            current = 0
        elif tok in ("millon", "millones"):
            total += (current or 1) * 1_000_000
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def _digits_to_decimal(raw: str) -> Decimal | None:
    s = raw.strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):  # separadores de miles
        return Decimal(re.sub(r"[.,]", "", s))
    if re.fullmatch(r"\d+[.,]\d{1,2}", s):  # decimales
        return Decimal(s.replace(",", "."))
    if re.fullmatch(r"\d+", s):
        return Decimal(s)
    return None


def parse_amount(text: str) -> Decimal | None:
    """Extrae un importe de textos como 'tres millones', '150 mil', '$1.200.000', '2,5 millones'."""
    t = _norm(text)
    # 1) cifra + multiplicador (mil / millones / k)
    m = re.search(r"(\d[\d.,]*)\s*(millones|millon|mil|k)\b", t)
    if m:
        base = _digits_to_decimal(m.group(1)) if re.fullmatch(r"\d{1,3}([.,]\d{3})+", m.group(1)) else None
        if base is None:
            try:
                base = Decimal(m.group(1).replace(",", "."))
            except Exception:
                base = None
        if base is not None:
            mult = Decimal(1_000_000) if m.group(2).startswith("millon") else Decimal(1000)
            return base * mult
    # 2) palabras
    toks = re.findall(rf"\b(?:{_WORD_RE}|y)\b", t)
    if toks:
        # recortar 'y' sobrantes en los extremos y quedarse con la primera secuencia contigua
        seq_match = re.search(rf"\b(?:(?:{_WORD_RE})(?:\s+y)?\s*)+", t)
        if seq_match:
            seq = re.findall(rf"\b(?:{_WORD_RE}|y)\b", seq_match.group(0))
            while seq and seq[-1] == "y":
                seq.pop()
            n = _words_to_number(seq)
            if n is not None and n > 0:
                return Decimal(n)
    # 3) cifra suelta (con o sin separadores / símbolo $)
    for m in re.finditer(r"\$?\s*(\d[\d.,]*)", t):
        val = _digits_to_decimal(m.group(1).rstrip(".,"))
        if val is not None and val > 0:
            return val
    return None


def parse_percent(text: str) -> Decimal | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(%|por\s*ciento)", _norm(text))
    return Decimal(m.group(1).replace(",", ".")) if m else None


def _top_n(t: str) -> int:
    m = re.search(r"\b(\d{1,2})\b", t)
    if m:
        return max(1, min(20, int(m.group(1))))
    for w, n in (("diez", 10), ("cinco", 5), ("tres", 3), ("cuatro", 4), ("dos", 2)):
        if re.search(rf"\b{w}\b", t):
            return n
    return 5


def classify_intent(text: str) -> dict:
    """Devuelve {'action': ..., ...parámetros}. 'unknown' si no se entiende."""
    t = _norm(text)
    amount = parse_amount(text)
    pct = parse_percent(text)

    if re.search(r"\b(pausa|pausar|pausame|deten|detener|deja de vigilar|deja de seguir)", t):
        return {"action": "pause"}
    if re.search(r"\b(reanuda|reanudar|reactiva|reactivar|retoma|retomar|vuelve a vigilar)", t):
        return {"action": "resume"}
    if re.search(r"minimo historico", t) and re.search(r"avis|alert|notific", t):
        return {"action": "set_historic_low"}
    if re.search(r"cerca (del|de mi|de su) (precio )?objetivo|cerca de (mi )?meta|casi (llegan|alcanzan)", t):
        return {"action": "near_target"}
    if re.search(r"(mayor|mas) ahorro|mejor(es)? (ahorro|oferta)|mas barat", t) and re.search(r"producto|carrito|mostrar|muestra|dime", t):
        return {"action": "top_savings", "n": _top_n(t)}
    if re.search(r"(que|cual(es)?) (producto|articulo)s?.*(revis|ver|mirar).*primero|prioriz|revisar primero", t):
        return {"action": "review_first", "n": _top_n(t)}
    if re.search(r"otras? tiendas?|mismo modelo|comparar|compara|en que otra", t):
        return {"action": "compare"}
    if re.search(r"promoci|cupon|descuento|oferta", t) and re.search(r"busca|hay|existe|tiene|encuentra|resum", t):
        return {"action": "find_promotions"}
    if re.search(r"por que|explica|que (paso|cambio)|cambio de precio|historial|subio|bajo (de )?precio", t) and not amount:
        return {"action": "explain"}
    if re.search(r"avis|alert|notific|quiero|baje|bajar|llegue|alcance|menos de|por menos|por debajo", t):
        if pct is not None and not re.search(r"pesos|cop|\$|mil|millon", t):
            return {"action": "set_pct", "pct": str(pct)}
        if amount is not None:
            return {"action": "set_target", "amount": str(amount)}
        if pct is not None:
            return {"action": "set_pct", "pct": str(pct)}
        if re.search(r"cualquier|cuando baje|baje (algo|un poco)", t):
            return {"action": "set_any_drop"}
    return {"action": "unknown"}
