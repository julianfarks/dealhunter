"""Conectores pendientes: la arquitectura está lista pero NO hay una fuente de precios permitida y verificada.

Mientras sigan así, los productos de estas tiendas se guardan en el carrito con el estado
"Requiere una fuente de datos compatible". No se inventan precios ni se simulan actualizaciones,
y no se hace scraping de estas tiendas (sus condiciones de uso y sus protecciones anti-bot lo impiden).
"""
from __future__ import annotations

from .base import Connector, ListingRef, ProductInfo, SourceUnavailable


class _Pending(Connector):
    reason = ""

    def configured(self) -> bool:
        return False

    def status(self) -> str:
        return "unavailable"

    def fetch(self, ref: ListingRef) -> ProductInfo:
        raise SourceUnavailable(self.reason)


class AmazonConnector(_Pending):
    key = "amazon"
    name = "Amazon"
    reason = (
        "Amazon no ofrece una fuente de precios pública. La Product Advertising API 5.0 fue retirada y su "
        "sucesora es la Creators API (requiere ser afiliado aprobado). Conector pendiente."
    )
    docs = reason


class AliExpressConnector(_Pending):
    key = "aliexpress"
    name = "AliExpress"
    reason = (
        "AliExpress sólo expone precios mediante su API de afiliados/Open Platform, que requiere cuenta aprobada "
        "y varía por región. Conector pendiente (sin verificar)."
    )
    docs = reason


class TemuConnector(_Pending):
    key = "temu"
    name = "Temu"
    reason = (
        "Temu no publica una API oficial de precios para terceros; sólo existen proveedores de datos comerciales. "
        "Conector pendiente de un proveedor autorizado."
    )
    docs = reason
