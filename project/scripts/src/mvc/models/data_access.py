"""Acesso a dados e inicialização de ambiente."""
from __future__ import annotations

from ...core.config import configure_runtime, validate_data_files
from ...data.datasets import load_all


def load_data() -> dict:
    """Carrega todos os DataFrames necessários para o app."""
    configure_runtime()
    validate_data_files()
    return load_all()
