"""filters.py

Funções de filtragem de DataFrames e utilitários de seleção.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

from typing import Iterable, Sequence

import pandas as pd

from ..core.config import AREAS_FORA
from .periods import LT_MONTHS


def normaliza_str(value: object) -> str:
    text = str(value).strip()
    return text if text.lower() not in {"nan", "none"} else ""


def startswith_any(value: object, prefixes: Iterable[str]) -> bool:
    candidate = normaliza_str(value)
    if not candidate:
        return False
    for prefix in prefixes:
        prefix_norm = normaliza_str(prefix)
        if prefix_norm and (candidate == prefix_norm or candidate.startswith(prefix_norm)):
            return True
    return False


def aplicar_filtro_faixas(df: pd.DataFrame, coluna: str, faixas: Sequence[str]) -> pd.DataFrame:
    if not faixas or not all(" a " in faixa for faixa in faixas):
        return df
    return df[df[coluna].apply(lambda valor: esta_em_alguma_faixa(valor, faixas))]


def aplicar_filtro_por_area(
    df: pd.DataFrame,
    area: str | None,
    subarea: str | None,
    her_df: pd.DataFrame,
) -> pd.DataFrame:
    if area and area != "GERAL":
        if subarea:
            deps = her_df[her_df["Area"] == subarea]["Heranca"].unique()
            return df[(df["Area"] == subarea) & (df["Heranca"].isin(deps))]
        deps = her_df[her_df["Area"] == area]["Heranca"].unique()
        return df[df["Area"].str.startswith(area) & df["Heranca"].isin(deps)]
    return df


def resolver_areas_viajantes(
    her_df: pd.DataFrame,
    areas_base: Sequence[str] | None = None,
) -> tuple[set[str], set[str]]:
    if areas_base is None:
        areas_base = AREAS_FORA
    areas_base_norm = [normaliza_str(area) for area in areas_base if normaliza_str(area)]

    if her_df is None or her_df.empty or not {"Area", "Heranca"}.issubset(her_df.columns):
        return set(areas_base_norm), set()

    tmp = her_df[["Area", "Heranca"]].copy()
    tmp["Area"] = tmp["Area"].astype(str).str.strip()
    tmp["Heranca"] = tmp["Heranca"].astype(str).str.strip()

    herancas_base = (
        tmp.loc[tmp["Area"].apply(lambda area: startswith_any(area, areas_base_norm)), "Heranca"]
        .dropna()
        .unique()
        .tolist()
    )
    herancas_norm = [normaliza_str(heranca) for heranca in herancas_base if normaliza_str(heranca)]

    return set(areas_base_norm), set(herancas_norm)


def esta_em_alguma_faixa(valor: object, faixas: Sequence[str]) -> bool:
    for faixa in faixas:
        try:
            fmin, fmax = map(float, faixa.split(" a "))
            if fmin <= float(valor) < fmax:
                return True
        except Exception:
            continue
    return False


def filtrar_por_periodo(df: pd.DataFrame, dt_ini, dt_fim) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    dt_ini = pd.Timestamp(dt_ini).normalize()
    dt_fim = pd.Timestamp(dt_fim).normalize()
    if dt_ini > dt_fim:
        dt_ini, dt_fim = dt_fim, dt_ini

    dff = df.copy()

    if "Data" in dff.columns:
        dff["Data"] = pd.to_datetime(dff["Data"], errors="coerce")
        if pd.api.types.is_datetime64tz_dtype(dff["Data"]):
            dff["Data"] = dff["Data"].dt.tz_localize(None)
        return dff[dff["Data"].between(dt_ini, dt_fim, inclusive="both")]

    if "Início da Semana" in dff.columns:
        dff["_IniSem"] = pd.to_datetime(dff["Início da Semana"], errors="coerce")
        if pd.api.types.is_datetime64tz_dtype(dff["_IniSem"]):
            dff["_IniSem"] = dff["_IniSem"].dt.tz_localize(None)
        return dff[dff["_IniSem"].between(dt_ini, dt_fim, inclusive="both")].drop(columns=["_IniSem"])

    if {"Ano", "Semana por Ano"}.issubset(dff.columns):
        tmp = dff[["Ano", "Semana por Ano"]].copy()
        tmp["Ano"] = pd.to_numeric(tmp["Ano"], errors="coerce")
        tmp["Semana por Ano"] = pd.to_numeric(tmp["Semana por Ano"], errors="coerce")
        mask_valid = tmp["Ano"].notna() & tmp["Semana por Ano"].between(1, 53, inclusive="both")
        tmp = tmp[mask_valid]
        inicios = pd.to_datetime(
            tmp["Ano"].astype(int).astype(str)
            + tmp["Semana por Ano"].astype(int).astype(str).str.zfill(2)
            + "1",
            format="%G%V%u",
            errors="coerce",
        )
        dff = dff.loc[tmp.index].copy()
        dff["_IniSem"] = inicios
        return dff[dff["_IniSem"].between(dt_ini, dt_fim, inclusive="both")].drop(columns=["_IniSem"])

    return dff


def interpolar_cor_hex(cor1: str, cor2: str, t: float) -> str:
    c1 = [int(cor1[i : i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(cor2[i : i + 2], 16) for i in (1, 3, 5)]
    interp = [int(c1[idx] + (c2[idx] - c1[idx]) * t) for idx in range(3)]
    return f"#{interp[0]:02x}{interp[1]:02x}{interp[2]:02x}"


def normalizar_str(texto: str) -> str:
    return str(texto).strip().replace("_", " ")


def slug(texto: str) -> str:
    return str(texto).replace(" ", "_").replace("/", "-")
