"""datasets.py

Carregamento de DataFrames a partir de arquivos Parquet com cache interno.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Callable

import pandas as pd

from ..core.config import (
    AFASTADOS_PARQUET,
    ALMOCO_PARQUET,
    DATAS_PARQUET,
    DEPARTAMENTOS_PARQUET,
    GPTW_PARQUET,
    HEADCOUNT_PARQUET,
    SEMANA_PARQUET,
    Settings,
    get_settings,
)
from ..domain.cargo import normalize_cargo_columns
from ..domain.pipeline import run_pipeline

ParquetLoader = Callable[[str | bytes | Path], pd.DataFrame]


def _read_parquet(path: str | bytes | Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def _normalize_cadastro(df: pd.DataFrame) -> pd.DataFrame:
    if "Cadastro" in df.columns:
        df["Cadastro"] = df["Cadastro"].astype(str)
    return df


def _normalize_data(df: pd.DataFrame, column: str = "Data") -> pd.DataFrame:
    if column in df.columns:
        df[column] = pd.to_datetime(df[column], errors="coerce")
    return df


def _normalize_semana(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    _normalize_cadastro(df)
    _normalize_data(df, "Data")

    if "Dia Semana" not in df.columns and "Data" in df.columns:
        dias = {
            0: "Segunda",
            1: "Terca",
            2: "Quarta",
            3: "Quinta",
            4: "Sexta",
            5: "Sabado",
            6: "Domingo",
        }
        df["Dia Semana"] = df["Data"].dt.weekday.map(dias)

    if "Cargo" not in df.columns and "Cargo Especifico" in df.columns:
        df = df.assign(Cargo=df["Cargo Especifico"])
    if "Cargo" in df.columns:
        df = normalize_cargo_columns(df, cargo_col="Cargo", fallback_col="Cargo Especifico")

    return df


def _normalize_datas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    _normalize_cadastro(df)
    _normalize_data(df, "Data")
    return df


def _normalize_df_ativos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    _normalize_cadastro(df)
    if "Cargo" in df.columns:
        df = normalize_cargo_columns(df, cargo_col="Cargo", fallback_col="Cargo Especifico")
    return df


def _normalize_df_desligados(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    _normalize_cadastro(df)
    if "Cargo" in df.columns:
        df = normalize_cargo_columns(df, cargo_col="Cargo", fallback_col="Cargo Especifico")
    return df


def _normalize_df_gptw(df: pd.DataFrame) -> pd.DataFrame:
    return df.copy()


def _normalize_almoco(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    _normalize_cadastro(df)
    _normalize_data(df, "Data")
    return df


def _load(
    path: str | bytes | Path,
    reader: ParquetLoader = _read_parquet,
) -> pd.DataFrame:
    df = reader(path)
    return df.copy() if isinstance(df, pd.DataFrame) else df


@lru_cache(maxsize=4)
def _pipeline_artifacts(settings: Settings) -> dict[str, object] | None:
    if settings.dw_path and settings.dw_path.exists():
        return run_pipeline(settings)
    return None


@lru_cache(maxsize=None)
def load_df_df_ativos(
    settings: Settings | None = None,
    reader: ParquetLoader = _read_parquet,
) -> pd.DataFrame:
    settings = settings or get_settings()
    pipeline = _pipeline_artifacts(settings)
    if pipeline is not None:
        return pipeline["df_df_ativos"].copy()
    return _normalize_df_ativos(_load(settings.pasta_df_ativos, reader))


@lru_cache(maxsize=None)
def load_df_datas(
    settings: Settings | None = None,
    reader: ParquetLoader = _read_parquet,
) -> pd.DataFrame:
    settings = settings or get_settings()
    pipeline = _pipeline_artifacts(settings)
    if pipeline is not None:
        return pipeline["df_datas"].copy()
    return _normalize_datas(_load(settings.caminho_datas, reader))


@lru_cache(maxsize=None)
def load_df_semana(
    settings: Settings | None = None,
    reader: ParquetLoader = _read_parquet,
) -> pd.DataFrame:
    settings = settings or get_settings()
    pipeline = _pipeline_artifacts(settings)
    if pipeline is not None:
        return pipeline["df_semana_merged"].copy()
    return _normalize_semana(_load(settings.caminho_semana, reader))


@lru_cache(maxsize=None)
def load_df_df_desligados(
    settings: Settings | None = None,
    reader: ParquetLoader = _read_parquet,
) -> pd.DataFrame:
    settings = settings or get_settings()
    pipeline = _pipeline_artifacts(settings)
    if pipeline is not None:
        return pipeline["df_df_desligados"].copy()
    return _normalize_df_desligados(_load(settings.pasta_df_desligados, reader))


@lru_cache(maxsize=None)
def load_df_df_gptw(
    settings: Settings | None = None,
    reader: ParquetLoader = _read_parquet,
) -> pd.DataFrame:
    settings = settings or get_settings()
    pipeline = _pipeline_artifacts(settings)
    if pipeline is not None:
        return pipeline["df_df_gptw"].copy()
    return _normalize_df_gptw(_load(settings.caminho_df_gptw, reader))


@lru_cache(maxsize=None)
def load_df_almoco(
    settings: Settings | None = None,
    reader: ParquetLoader = _read_parquet,
) -> pd.DataFrame:
    settings = settings or get_settings()
    pipeline = _pipeline_artifacts(settings)
    if pipeline is not None:
        return pipeline["df_almoco"].copy()
    return _normalize_almoco(_load(settings.caminho_almoco, reader))


@lru_cache(maxsize=None)
def load_df_headcount(
    settings: Settings | None = None,
    reader: ParquetLoader = _read_parquet,
) -> pd.DataFrame:
    settings = settings or get_settings()
    pipeline = _pipeline_artifacts(settings)
    if pipeline is not None:
        return pipeline["df_headcount"].copy()
    if HEADCOUNT_PARQUET is None:
        return pd.DataFrame()
    path = settings.caminho_headcount or HEADCOUNT_PARQUET
    if not path:
        return pd.DataFrame()
    return _load(path, reader)


def load_all(settings: Settings | None = None) -> dict[str, pd.DataFrame]:
    """Carrega todos os DataFrames necessarios para o app."""
    settings = settings or get_settings()
    pipeline = _pipeline_artifacts(settings)
    if pipeline is not None:
        return {
            "df_df_ativos": pipeline["df_df_ativos"].copy(),
            "df_datas": pipeline["df_datas"].copy(),
            "df_semana_merged": pipeline["df_semana_merged"].copy(),
            "df_df_desligados": pipeline["df_df_desligados"].copy(),
            "df_df_gptw": pipeline["df_df_gptw"].copy(),
            "df_almoco": pipeline["df_almoco"].copy(),
            "df_headcount": pipeline["df_headcount"].copy(),
        }
    return {
        "df_df_ativos": load_df_df_ativos(settings),
        "df_datas": load_df_datas(settings),
        "df_semana_merged": load_df_semana(settings),
        "df_df_desligados": load_df_df_desligados(settings),
        "df_df_gptw": load_df_df_gptw(settings),
        "df_almoco": load_df_almoco(settings),
        "df_headcount": load_df_headcount(settings),
    }
