"""Normalizacao de cargo para regras de negocio do dashboard."""
from __future__ import annotations

import pandas as pd


HORISTA_GROUP_LABEL = "Horistas + Terceiros"


def normalize_cargo_series(series: pd.Series) -> pd.Series:
    """Normaliza codigos de cargo para E/M/H.

    Regra adicional: terceiros sao tratados como horistas (H).
    """
    src = series.astype("string").fillna("").str.strip()
    upper = src.str.upper()
    out = upper.str[:1]

    out = out.where(~(upper.str.startswith("E") | upper.str.contains("EXEC", na=False)), "E")
    out = out.where(~(upper.str.startswith("M") | upper.str.contains("MENS", na=False)), "M")

    horista_like = (
        upper.str.startswith("H")
        | upper.str.contains("HOR", na=False)
        | upper.str.startswith("T")
        | upper.str.contains("TERC", na=False)
        | upper.str.contains("THIRD", na=False)
        | upper.str.contains("OUTSOUR", na=False)
        | upper.str.contains("3R", na=False)
    )
    out = out.where(~horista_like, "H")
    return out.fillna("").astype(str)


def normalize_cargo_code(value: object) -> str:
    """Normaliza um unico valor de cargo para E/M/H."""
    return normalize_cargo_series(pd.Series([value], dtype="string")).iloc[0]


def normalize_cargo_columns(
    df: pd.DataFrame,
    cargo_col: str = "Cargo",
    fallback_col: str | None = "Cargo Especifico",
) -> pd.DataFrame:
    """Normaliza coluna de cargo com fallback opcional."""
    out = df.copy()
    if cargo_col not in out.columns:
        return out

    cargo_norm = normalize_cargo_series(out[cargo_col])
    if fallback_col and fallback_col in out.columns:
        fallback_norm = normalize_cargo_series(out[fallback_col])
        empty_mask = cargo_norm.astype(str).str.strip().eq("")
        cargo_norm = cargo_norm.where(~empty_mask, fallback_norm)
    out[cargo_col] = cargo_norm
    return out


def horista_like_mask(series: pd.Series) -> pd.Series:
    """Retorna mascara para cargos equivalentes a horista."""
    return normalize_cargo_series(series).eq("H")
