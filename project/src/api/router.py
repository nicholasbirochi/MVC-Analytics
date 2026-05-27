"""Router agregador para callbacks Dash.

Mantém a ideia do notebook/unificado: expõe um único ponto de registro
que chama todos os módulos de API existentes.
"""
from __future__ import annotations

from .general import register as register_general
from .individual import register as register_individual
from .area import register as register_area
from .relacionamento import register as register_relacionamento


def register_all(app) -> None:
    """Registra todos os callbacks/rotas no app Dash."""
    register_general(app)
    register_individual(app)
    register_area(app)
    register_relacionamento(app)
