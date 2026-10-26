"""Validación, identificación de tienda y normalización de URLs + protección SSRF.

Sólo usa la librería estándar para poder probarse sin dependencias.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048

# Acortadores conocidos: el ID del producto sólo se conoce tras seguir la redirección (con guardia SSRF).
SHORT_HOSTS = {
    "amzn.to", "a.co", "amzn.eu", "amzn.asia",
    "a.aliexpress.com", "s.click.aliexpress.com", "s.click.aliexpress.us",
    "meli.la", "ebay.to", "share.temu.com",
}

BLOCKED_TLDS = {"local", "localhost", "internal", "lan", "home", "corp", "intranet", "test", "invalid", "example"}

# Parámetros de seguimiento publicitario (seguros de eliminar).
_TRACKING_EXACT = {
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "mc_cid", "mc_eid", "igshid", "yclid",
    "_ga", "_gl", "_hsenc", "_hsmi", "ref_src", "srsltid", "cmpid", "ref", "ref_", "referrer",
    "spm", "scm", "pvid", "algo_pvid", "algo_exp_id", "aff_fcid", "aff_fsk", "aff_platform", "aff_trace_key",
    "sk", "tag", "linkcode", "linkid", "creative", "creativeasin", "camp", "psc_ref", "pd_rd_i",
    "pd_rd_r", "pd_rd_w", "pd_rd_wg", "pf_rd_p", "pf_rd_r", "content-id", "qid", "sr", "keywords", "crid",
    "sprefix", "dib", "dib_tag", "initiative_id", "sourcetype", "tracking_id", "matt_tool", "matt_word",
    "matt_source", "matt_campaign", "mkcid", "mkrid", "siteid", "campid", "customid", "toolid", "mkevt",
    "mkgroupid", "mktype", "ufes_redirect", "searchkeyword", "adminsite", "sourcetype", "browser_redirect",
    "tracking_source", "pdp_ext_f", "pdp_npi", "gps-id", "scm-url", "scm_id", "pvid", "algo_exp_id",
    "ws_ab_test", "btsid", "aff_request_id", "mp", "source", "matching_id", "from",
}
_TRACKING_PREFIXES = ("utm_", "aff_", "pf_rd_", "pd_rd_", "matt_", "mkt_", "_bta")


class InvalidUrl(ValueError):
    """La URL no es válida o no es segura de procesar."""


@dataclass(frozen=True)
class ParsedUrl:
    store_key: str  # amazon | aliexpress | mercadolibre | temu | ebay | generic
    external_id: str | None  # None si hace falta resolver un enlace corto
    variant_key: str
    canonical_url: str
    original_url: str
    needs_resolution: bool = False


_URL_RE = re.compile(r"https?://[^\s<>\"'«»]+", re.IGNORECASE)


def extract_url(text: str) -> str | None:
    """Obtiene la primera URL http(s) de un texto compartido ("Mira esto: https://…")."""
    if not text:
        return None
    m = _URL_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip(").,;:!?]}»")


def _is_tracking(name: str) -> bool:
    n = name.lower()
    return n in _TRACKING_EXACT or n.startswith(_TRACKING_PREFIXES)


# Para tiendas genéricas somos conservadores: sólo eliminamos parámetros inequívocamente publicitarios.
_GENERIC_STRIP_EXACT = {
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "mc_cid", "mc_eid", "igshid", "yclid",
    "_ga", "_gl", "_hsenc", "_hsmi", "ref_src", "srsltid", "cmpid",
}


def _is_generic_tracking(name: str) -> bool:
    n = name.lower()
    return n in _GENERIC_STRIP_EXACT or n.startswith(("utm_", "aff_", "_bta"))


def host_is_blocked_literal(host: str) -> bool:
    """True si el host es una IP literal no pública."""
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return not is_public_ip(ip)


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast


def assert_public_host(host: str, port: int | None = None, resolver=socket.getaddrinfo) -> None:
    """Resuelve el host y exige que TODAS sus direcciones sean públicas (protección SSRF)."""
    host = host.strip("[]").rstrip(".")
    if not host:
        raise InvalidUrl("Host vacío")
    try:
        ip = ipaddress.ip_address(host)
        if not is_public_ip(ip):
            raise InvalidUrl("Dirección IP no permitida")
        return
    except ValueError:
        pass
    try:
        infos = resolver(host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise InvalidUrl("No se pudo resolver el dominio") from e
    if not infos:
        raise InvalidUrl("No se pudo resolver el dominio")
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as e:  # pragma: no cover
            raise InvalidUrl("Dirección resuelta inválida") from e
        if not is_public_ip(ip):
            raise InvalidUrl("El dominio apunta a una dirección no permitida")


def validate_url(raw: str) -> tuple[str, str]:
    """Valida sintaxis/seguridad básica. Devuelve (url_limpia, host_en_minúsculas)."""
    if raw is None:
        raise InvalidUrl("URL vacía")
    raw = raw.strip()
    if not raw:
        raise InvalidUrl("URL vacía")
    if len(raw) > MAX_URL_LENGTH:
        raise InvalidUrl("URL demasiado larga")
    if any(c in raw for c in ("\x00", "\r", "\n", "\t", " ")):
        raise InvalidUrl("La URL contiene caracteres no permitidos")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as e:
        raise InvalidUrl("URL mal formada") from e
    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidUrl("Sólo se admiten enlaces http o https")
    if parts.username is not None or parts.password is not None:
        raise InvalidUrl("No se admiten credenciales dentro de la URL")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise InvalidUrl("La URL no tiene dominio")
    if port not in (None, 80, 443):
        raise InvalidUrl("Puerto no permitido")
    if host_is_blocked_literal(host):
        raise InvalidUrl("Dirección IP no permitida")
    try:
        ipaddress.ip_address(host)
        raise InvalidUrl("No se admiten direcciones IP; usa el enlace de la tienda")
    except ValueError:
        pass
    if "." not in host:
        raise InvalidUrl("Dominio no válido")
    if host.rsplit(".", 1)[-1] in BLOCKED_TLDS:
        raise InvalidUrl("Dominio no permitido")
    return raw, host


_TLD = r"(com|co\.[a-z]{2}|com\.[a-z]{2}|[a-z]{2,3})"


def detect_store(host: str) -> str:
    """Identifica la tienda por dominio exacto (con sus TLD legítimos), no por coincidencias parciales."""
    h = host.lower()
    if h in ("amzn.to", "a.co", "amzn.eu", "amzn.asia") or re.search(rf"(^|\.)amazon\.{_TLD}$", h):
        return "amazon"
    if h in ("a.aliexpress.com", "s.click.aliexpress.com", "s.click.aliexpress.us") or re.search(
            r"(^|\.)aliexpress\.(com|us|ru|[a-z]{2,3})$", h):
        return "aliexpress"
    if h == "meli.la" or re.search(rf"(^|\.)mercado(libre|livre)\.{_TLD}$", h):
        return "mercadolibre"
    if h == "share.temu.com" or re.search(r"(^|\.)temu\.com$", h):
        return "temu"
    if h == "ebay.to" or re.search(rf"(^|\.)ebay\.{_TLD}$", h):
        return "ebay"
    return "generic"


def _clean_query(query: str, keep: set[str] | None = None, generic: bool = False) -> list[tuple[str, str]]:
    out = []
    for k, v in parse_qsl(query, keep_blank_values=False):
        if keep is not None:
            if k.lower() in keep:
                out.append((k, v))
        elif not (_is_generic_tracking(k) if generic else _is_tracking(k)):
            out.append((k, v))
    return sorted(out)


def parse_product_url(raw: str) -> ParsedUrl:
    """Valida, identifica la tienda y normaliza la URL conservando lo que identifica el artículo."""
    url, host = validate_url(raw)
    parts = urlsplit(url)
    path = parts.path or "/"
    store = detect_store(host)

    if host in SHORT_HOSTS:
        return ParsedUrl(store, None, "", url, url, needs_resolution=True)

    if store == "amazon":
        m = re.search(r"/(?:dp|gp/product|gp/aw/d|product|d)/([A-Z0-9]{10})(?:[/?#]|$)", path, re.IGNORECASE)
        if not m:
            raise InvalidUrl("No se encontró el identificador (ASIN) del producto de Amazon en el enlace")
        asin = m.group(1).upper()
        h = host[2:] if host.startswith("m.") else host
        return ParsedUrl("amazon", asin, "", f"https://{h}/dp/{asin}", url)

    if store == "aliexpress":
        q = dict(parse_qsl(parts.query))
        m = re.search(r"/(?:item|i)/(\d{6,})(?:\.html)?", path)
        pid = m.group(1) if m else (q.get("productIds") or q.get("productId") or "")
        if not pid.isdigit():
            raise InvalidUrl("No se encontró el identificador del producto de AliExpress en el enlace")
        sku = q.get("sku_id") or q.get("skuId") or ""
        canon = f"https://www.aliexpress.com/item/{pid}.html" + (f"?sku_id={sku}" if sku else "")
        return ParsedUrl("aliexpress", pid, sku, canon, url)

    if store == "mercadolibre":
        cat = re.search(r"/p/(M[A-Z]{2}\d{5,})", path, re.IGNORECASE)
        item = re.search(r"\b(M[A-Z]{2})-?(\d{6,})", path, re.IGNORECASE)
        q = dict(parse_qsl(parts.query))
        if not item and q.get("wid"):
            item = re.match(r"(M[A-Z]{2})-?(\d{6,})", q["wid"], re.IGNORECASE)
        variation = q.get("variation", "")
        if item and not cat:
            ext = f"{item.group(1).upper()}{item.group(2)}"
        elif cat:
            ext = "P:" + cat.group(1).upper()
        else:
            raise InvalidUrl("No se encontró el identificador de la publicación de Mercado Libre en el enlace")
        canon = urlunsplit(("https", host, path, urlencode([("variation", variation)] if variation else []), ""))
        return ParsedUrl("mercadolibre", ext, variation, canon, url)

    if store == "temu":
        q = dict(parse_qsl(parts.query))
        m = re.search(r"-g-(\d{6,})\.html", path) or re.search(r"/g-(\d{6,})\.html", path)
        gid = m.group(1) if m else q.get("goods_id", "")
        if not gid.isdigit():
            raise InvalidUrl("No se encontró el identificador del producto de Temu en el enlace")
        sku = q.get("sku_id", "")
        canon = urlunsplit(("https", host, path, urlencode([("sku_id", sku)] if sku else []), "")) if m else \
            f"https://{host}/goods.html?goods_id={gid}" + (f"&sku_id={sku}" if sku else "")
        return ParsedUrl("temu", gid, sku, canon, url)

    if store == "ebay":
        m = re.search(r"/itm/(?:[^/]+/)?(\d{9,14})", path)
        if not m:
            raise InvalidUrl("No se encontró el número de artículo de eBay en el enlace")
        q = dict(parse_qsl(parts.query))
        var = q.get("var", "")
        canon = f"https://{host}/itm/{m.group(1)}" + (f"?var={var}" if var else "")
        return ParsedUrl("ebay", m.group(1), var, canon, url)

    # Tienda independiente
    query = urlencode(_clean_query(parts.query, generic=True))
    scheme = parts.scheme.lower()
    canon = urlunsplit((scheme, host, path, query, ""))
    ext = hashlib.sha1(canon.encode()).hexdigest()[:20]
    return ParsedUrl("generic", ext, "", canon, url)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def guess_title(original_url: str, store_key: str) -> str | None:
    """Nombre legible deducido del 'slug' de la URL (sólo mientras la tienda no nos dé el título real)."""
    try:
        path = urlsplit(original_url).path
    except ValueError:
        return None
    segs = [s for s in path.split("/") if s]
    slug = ""
    if store_key == "amazon":
        for i, s in enumerate(segs):
            if s.lower() in ("dp", "product", "d") and i > 0 and segs[i - 1].lower() not in ("gp", "dp"):
                slug = segs[i - 1]
                break
    elif store_key == "mercadolibre":
        for s in segs:
            m = re.match(r"M[A-Z]{2}-?\d{6,}-(.+?)(?:-?_JM)?$", s, re.IGNORECASE)
            if m:
                slug = m.group(1)
                break
    elif store_key == "temu":
        for s in segs:
            m = re.match(r"(.+)-g-\d{6,}\.html$", s)
            if m:
                slug = m.group(1)
                break
    elif store_key == "ebay":
        for i, s in enumerate(segs):
            if s == "itm" and i + 2 < len(segs) + 1 and i + 1 < len(segs) and not segs[i + 1].isdigit():
                slug = segs[i + 1]
                break
    elif store_key == "generic":
        for s in reversed(segs):
            slug = re.sub(r"\.(html?|php|aspx?)$", "", s, flags=re.IGNORECASE)
            if slug:
                break
    from urllib.parse import unquote

    text = re.sub(r"[-_+]+", " ", unquote(slug)).strip()
    if not text or text.isdigit() or len(text) < 3:
        return None
    return (text[0].upper() + text[1:])[:120]
