"""repo_global.py

Carrega DataFrames globais normalizados e construtores derivados.
"""
from __future__ import annotations

import pandas as pd

from .config import SETTINGS, configure_runtime
from ..data.datasets import load_all
from ..domain.builders import (
    build_df_count_por_semana,
    build_dropdown_options,
    build_her,
)

# Configura ambiente global (locale, pandas etc.)
configure_runtime(SETTINGS)
USING_DW_SQLITE: bool = bool(SETTINGS.dw_path and SETTINGS.dw_path.exists())

# Carregamento principal -------------------------------------------------------
_frames = load_all(SETTINGS)
df_df_ativos: pd.DataFrame = _frames["df_df_ativos"]
df_datas: pd.DataFrame = _frames["df_datas"]
df_semana_merged: pd.DataFrame = _frames["df_semana_merged"]
df_df_desligados: pd.DataFrame = _frames["df_df_desligados"]
df_df_gptw: pd.DataFrame = _frames["df_df_gptw"]
df_almoco: pd.DataFrame = _frames["df_almoco"]
df_headcount: pd.DataFrame = _frames["df_headcount"]

# Derivados globais -----------------------------------------------------------
df_count_por_semana: pd.DataFrame = build_df_count_por_semana(df_semana_merged)
her: pd.DataFrame = build_her(df_semana_merged)
dropdown_options: list[dict] = build_dropdown_options(her)

__all__ = [
    "df_df_ativos",
    "df_datas",
    "df_semana_merged",
    "df_df_desligados",
    "df_df_gptw",
    "df_almoco",
    "df_headcount",
    "df_count_por_semana",
    "her",
    "dropdown_options",
    "USING_DW_SQLITE",
]
