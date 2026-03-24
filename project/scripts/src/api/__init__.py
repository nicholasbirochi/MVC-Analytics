"""__init__.py

Módulo do dashboard de dados (Empresa).

Projeto: Dashboard presencialidade — Empresa
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations
from .general import register as register_general
from .individual import register as register_individual
from .area import register as register_area
from .relacionamento import register as register_relacionamento
import logging


def register_all(app):
    register_general(app)
    register_individual(app)
    register_area(app)
    register_relacionamento(app)

