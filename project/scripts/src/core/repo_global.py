"""repo_global.py

Carrega DataFrames globais normalizados e construtores derivados.
"""
from __future__ import annotations

import pandas as pd

from .config import SETTINGS, configure_runtime
from ..data.datasets import (
    load_df_desligados,
    load_df_almoco,
    load_df_datas,
    load_df_ativos,
    load_df_gptw,
    load_df_headcount,
    load_df_semana,
)
from ..domain.builders import (
    build_df_count_por_semana,
    build_dropdown_options,
    build_her,
)

# Configura ambiente global (locale, pandas etc.)
configure_runtime(SETTINGS)

# Carregamento principal -------------------------------------------------------
df_ativos: pd.DataFrame = load_df_ativos(SETTINGS)
df_datas: pd.DataFrame = load_df_datas(SETTINGS)
df_semana_merged: pd.DataFrame = load_df_semana(SETTINGS)
df_desligados: pd.DataFrame = load_df_desligados(SETTINGS)
df_gptw: pd.DataFrame = load_df_gptw(SETTINGS)
df_almoco: pd.DataFrame = load_df_almoco(SETTINGS)
df_headcount: pd.DataFrame = load_df_headcount(SETTINGS)

# Derivados globais -----------------------------------------------------------
df_count_por_semana: pd.DataFrame = build_df_count_por_semana(df_semana_merged)
her: pd.DataFrame = build_her(df_semana_merged)
dropdown_options: list[dict] = build_dropdown_options(her)

__all__ = [
    "df_ativos",
    "df_datas",
    "df_semana_merged",
    "df_desligados",
    "df_gptw",
    "df_almoco",
    "df_headcount",
    "df_count_por_semana",
    "her",
    "dropdown_options",
]
