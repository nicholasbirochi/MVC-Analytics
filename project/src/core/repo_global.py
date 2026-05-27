"""repo_global.py

Carrega DataFrames globais normalizados e construtores derivados.
"""
from __future__ import annotations

import pandas as pd

from .config import SETTINGS, configure_runtime
from ..data.datasets import load_all


def _build_df_count_por_semana(df_semana_merged: pd.DataFrame) -> pd.DataFrame:
    required = [
        "Cadastro",
        "Nome",
        "Área",
        "Departamento",
        "Heranca",
        "Cargo Especifico",
        "Desligado",
        "Dia Semana",
    ]
    if all(col in df_semana_merged.columns for col in required):
        out = (
            df_semana_merged.groupby(
                [
                    "Cadastro",
                    "Nome",
                    "Área",
                    "Departamento",
                    "Heranca",
                    "Cargo Especifico",
                    "Desligado",
                ]
            )["Dia Semana"]
            .value_counts()
            .reset_index()
        )
        out.columns = [
            "Cadastro",
            "Nome",
            "Área",
            "Departamento",
            "Heranca",
            "Cargo Especifico",
            "Desligado",
            "Dia Semana",
            "Contagem Presença",
        ]
        return out
    return pd.DataFrame(
        columns=[
            "Cadastro",
            "Nome",
            "Área",
            "Departamento",
            "Heranca",
            "Cargo Especifico",
            "Desligado",
            "Dia Semana",
            "Contagem Presença",
        ]
    )


def _build_her(
    df_semana_merged: pd.DataFrame,
    df_df_ativos: pd.DataFrame | None = None,
) -> pd.DataFrame:
    has_cols_semana = (
        df_semana_merged is not None
        and not df_semana_merged.empty
        and {"Área", "Departamento", "Heranca"}.issubset(df_semana_merged.columns)
    )
    if has_cols_semana:
        return (
            df_semana_merged[["Área", "Departamento", "Heranca"]]
            .drop_duplicates()
            .sort_values("Área")
        )

    if (
        df_df_ativos is not None
        and not df_df_ativos.empty
        and {"Área", "Departamento", "Heranca"}.issubset(df_df_ativos.columns)
    ):
        return (
            df_df_ativos[["Área", "Departamento", "Heranca"]]
            .drop_duplicates()
            .sort_values("Área")
        )
    return pd.DataFrame(columns=["Área", "Departamento", "Heranca"])


def _build_dropdown_options(her_df: pd.DataFrame) -> list[dict]:
    if her_df is None or her_df.empty:
        return [{"label": "Geral (todas as areas)", "value": "GERAL"}]
    base = [{"label": "Geral (todas as areas)", "value": "GERAL"}]
    options = [
        {"label": f"{row['Área']} {row['Departamento']}", "value": row["Área"]}
        for _, row in her_df.iterrows()
    ]
    return base + options

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
df_count_por_semana: pd.DataFrame = _build_df_count_por_semana(df_semana_merged)
her: pd.DataFrame = _build_her(df_semana_merged, df_df_ativos)
dropdown_options: list[dict] = _build_dropdown_options(her)

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
