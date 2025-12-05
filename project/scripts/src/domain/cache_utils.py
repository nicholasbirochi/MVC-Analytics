"""Utilidades de cache para harmonizar configurações no app."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.config import DEFAULT_CACHE_TIMEOUT


@dataclass
class CacheOptions:
    """Opções de cache simples (mantém compatibilidade com Flask-Caching)."""
    cache_type: str = "SimpleCache"
    default_timeout: int = DEFAULT_CACHE_TIMEOUT


def as_dict(opts: CacheOptions) -> dict:
    """Converte opções em dict pronto para uso no init_app."""
    return {"CACHE_TYPE": opts.cache_type, "CACHE_DEFAULT_TIMEOUT": opts.default_timeout}
