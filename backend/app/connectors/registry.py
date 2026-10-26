from __future__ import annotations

from .base import Connector
from .ebay import EbayConnector
from .generic import GenericConnector
from .mercadolibre import MercadoLibreConnector
from .pending import AliExpressConnector, AmazonConnector, TemuConnector

_REGISTRY: dict[str, Connector] = {}


def _build() -> None:
    for c in (
        MercadoLibreConnector(), EbayConnector(), AmazonConnector(), AliExpressConnector(),
        TemuConnector(), GenericConnector(),
    ):
        _REGISTRY[c.key] = c


_build()


def get_connector(key: str) -> Connector:
    return _REGISTRY.get(key) or _REGISTRY["generic"]


def all_connectors() -> list[Connector]:
    return list(_REGISTRY.values())


def register_for_tests(connector: Connector) -> Connector | None:
    prev = _REGISTRY.get(connector.key)
    _REGISTRY[connector.key] = connector
    return prev


def unregister_for_tests(key: str, previous: Connector | None) -> None:
    if previous is None:
        _REGISTRY.pop(key, None)
    else:
        _REGISTRY[key] = previous
