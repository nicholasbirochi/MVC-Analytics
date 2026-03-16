"""tenure.py

Cálculo de tempo de casa (tenure) para colaboradores.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from ..core import repo_global as repo


def _norm_df(df):
    return df if isinstance(df, pd.DataFrame) and not df.empty else None


def _norm_col_name(value: object) -> str:
    text = "" if value is None else str(value).strip().lower()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]+", "", text)


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    if df is None or df.empty:
        return None
    normalized = {_norm_col_name(col): col for col in df.columns}
    for cand in candidates:
        key = _norm_col_name(cand)
        if key in normalized:
            return normalized[key]
    return None


def _clean_cadastro(value: str | int | float | None) -> str:
    text = "" if value is None else str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def coletar_admissoes_e_demissoes(
    df_df_desligados: pd.DataFrame | None = None,
    df_df_ativos: pd.DataFrame | None = None,
    df_semana_merged: pd.DataFrame | None = None,
) -> tuple[dict[str, pd.Timestamp], dict[str, pd.Timestamp]]:
    if df_df_desligados is None:
        df_df_desligados = repo.df_df_desligados
    if df_df_ativos is None:
        df_df_ativos = repo.df_df_ativos
    if df_semana_merged is None:
        df_semana_merged = repo.df_semana_merged

    adm: dict[str, pd.Timestamp] = {}
    dem: dict[str, pd.Timestamp] = {}

    def _put_min(target: dict[str, pd.Timestamp], key: str, value: pd.Timestamp) -> None:
        if pd.isna(value):
            return
        if (key not in target) or (value < target[key]):
            target[key] = value

    def _put_max(target: dict[str, pd.Timestamp], key: str, value: pd.Timestamp) -> None:
        if pd.isna(value):
            return
        if (key not in target) or (value > target[key]):
            target[key] = value

    # Fonte canônica de RH no DW (mesma lógica do notebook): melhora acurácia do tempo de casa.
    try:
        from .pipeline import query_dw

        hr = query_dw(
            'SELECT "Cadastro","Data Adm","Data Dem" FROM vw_colaborador_hr;',
            (),
            parse_dates=["Data Adm", "Data Dem"],
        )
        if isinstance(hr, pd.DataFrame) and not hr.empty and "Cadastro" in hr.columns:
            hr = hr.copy()
            hr["Cadastro"] = hr["Cadastro"].map(_clean_cadastro)
            adm_col_hr = _find_col(hr, ["Data Adm", "Data_Adm", "Data Admissao", "Data Admissão"])
            dem_col_hr = _find_col(hr, ["Data Dem", "Data_Dem", "Data Demissao", "Data Demissão"])
            if adm_col_hr:
                datas_adm_hr = pd.to_datetime(hr[adm_col_hr], errors="coerce")
                for cad, data in zip(hr["Cadastro"], datas_adm_hr):
                    _put_min(adm, cad, data)
            if dem_col_hr:
                datas_dem_hr = pd.to_datetime(hr[dem_col_hr], errors="coerce")
                for cad, data in zip(hr["Cadastro"], datas_dem_hr):
                    _put_max(dem, cad, data)
    except Exception:
        pass

    dfa = _norm_df(df_df_desligados)
    if dfa is not None and "Cadastro" in dfa.columns:
        cad_series = dfa["Cadastro"].map(_clean_cadastro)
        adm_col = _find_col(dfa, ["Data_Adm", "Data Adm", "Data Admissao", "Data Admissão"])
        dem_col = _find_col(dfa, ["Data_Dem", "Data Dem", "Data Demissao", "Data Demissão"])
        if adm_col:
            datas_adm = pd.to_datetime(dfa[adm_col], errors="coerce")
            for cad, data in zip(cad_series, datas_adm):
                _put_min(adm, cad, data)
        if dem_col:
            datas_dem = pd.to_datetime(dfa[dem_col], errors="coerce")
            for cad, data in zip(cad_series, datas_dem):
                _put_max(dem, cad, data)

    dfd = _norm_df(df_df_ativos)
    adm_col_ativos = _find_col(
        dfd,
        ["Data Admissao", "Data Admissão", "Data_Adm", "Data Adm", "Admissao", "Admissão"],
    ) if dfd is not None else None
    if dfd is not None and "Cadastro" in dfd.columns and adm_col_ativos:
        tmp = dfd[["Cadastro", adm_col_ativos]].copy()
        tmp["Cadastro"] = tmp["Cadastro"].map(_clean_cadastro)
        tmp[adm_col_ativos] = pd.to_datetime(tmp[adm_col_ativos], errors="coerce")
        tmp = tmp.dropna(subset=[adm_col_ativos]).drop_duplicates("Cadastro", keep="first")
        for cad, data in zip(tmp["Cadastro"], tmp[adm_col_ativos]):
            _put_min(adm, cad, data)

    dfsm = _norm_df(df_semana_merged)
    if dfsm is not None and "Cadastro" in dfsm.columns:
        possiveis = [
            "Admissao",
            "Data Admissao",
            "DtAdmissao",
            "Dt_Admissao",
            "Hire Date",
            "Admission",
        ]
        coluna = next((col for col in possiveis if col in dfsm.columns), None)
        if coluna:
            tmp = dfsm[["Cadastro", coluna]].copy()
            tmp["Cadastro"] = tmp["Cadastro"].astype(str)
            tmp[coluna] = pd.to_datetime(tmp[coluna], errors="coerce")
            tmp = tmp.dropna(subset=[coluna]).drop_duplicates("Cadastro", keep="first")
            for cad, data in zip(tmp["Cadastro"], tmp[coluna]):
                _put_min(adm, cad, data)

    return adm, dem


ADM_CACHE: dict[str, pd.Timestamp] | None = None
DEM_CACHE: dict[str, pd.Timestamp] | None = None


def carregar_adm_dem_cache(
    df_df_desligados: pd.DataFrame | None = None,
    df_df_ativos: pd.DataFrame | None = None,
    df_semana: pd.DataFrame | None = None,
) -> tuple[dict[str, pd.Timestamp], dict[str, pd.Timestamp]]:
    global ADM_CACHE, DEM_CACHE
    if ADM_CACHE is None or DEM_CACHE is None:
        ADM_CACHE, DEM_CACHE = coletar_admissoes_e_demissoes(
            df_df_desligados, df_df_ativos, df_semana
        )
    return ADM_CACHE, DEM_CACHE


def sobrepoe_periodo(adm_ts, dem_ts, dt_ini, dt_fim) -> bool:
    if pd.isna(adm_ts) or adm_ts is None:
        adm_ts = pd.Timestamp.min
    if pd.isna(dem_ts) or dem_ts is None:
        dem_ts = pd.Timestamp.max
    return (adm_ts <= dt_fim) and (dem_ts >= dt_ini)


def tempo_de_casa_str(adm_ts, ref=None, dem_ts=None) -> str:
    if pd.isna(adm_ts) or adm_ts is None:
        return "-"
    if ref is None:
        ref = pd.Timestamp.today().normalize()
    if pd.notna(dem_ts):
        ref = min(ref, dem_ts)

    months = (ref.year - adm_ts.year) * 12 + (ref.month - adm_ts.month)
    if ref.day < getattr(adm_ts, "day", ref.day):
        months -= 1
    months = max(0, months)
    years, months = divmod(months, 12)
    return f"{years}a {months}m" if years else f"{months}m"


def obter_periodo_admissao(
    chapa: str | int,
    df_df_desligados: pd.DataFrame | None = None,
    df_df_ativos: pd.DataFrame | None = None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if df_df_desligados is None:
        df_df_desligados = repo.df_df_desligados
    if df_df_ativos is None:
        df_df_ativos = repo.df_df_ativos

    chapa_str = _clean_cadastro(chapa)

    dfd = _norm_df(df_df_desligados)
    if dfd is not None and "Cadastro" in dfd.columns:
        dfd = dfd.copy()
        dfd["Cadastro"] = dfd["Cadastro"].map(_clean_cadastro)
        pessoa_df_desligados = dfd[dfd["Cadastro"] == chapa_str]
        if not pessoa_df_desligados.empty:
            adm_col = _find_col(dfd, ["Data_Adm", "Data Adm", "Data Admissao", "Data Admissão"])
            dem_col = _find_col(dfd, ["Data_Dem", "Data Dem", "Data Demissao", "Data Demissão"])
            adm = pd.to_datetime(
                pessoa_df_desligados[adm_col].iloc[0], errors="coerce"
            ) if adm_col else pd.NaT
            dem = pd.to_datetime(
                pessoa_df_desligados[dem_col].iloc[0], errors="coerce"
            ) if dem_col else pd.NaT
            if pd.isna(dem):
                dem = pd.Timestamp.max
            return (None if pd.isna(adm) else adm), dem

    dfa = _norm_df(df_df_ativos)
    if dfa is not None and "Cadastro" in dfa.columns:
        dfa = dfa.copy()
        dfa["Cadastro"] = dfa["Cadastro"].map(_clean_cadastro)
        pessoa_df_ativos = dfa[dfa["Cadastro"] == chapa_str]
        if not pessoa_df_ativos.empty:
            adm_col = _find_col(
                dfa,
                ["Data Admissao", "Data Admissão", "Data_Adm", "Data Adm", "Admissao", "Admissão"],
            )
            if adm_col:
                adm = pd.to_datetime(
                    pessoa_df_ativos[adm_col].iloc[0],
                    dayfirst=True,
                    errors="coerce",
                )
                if pd.notna(adm):
                    return adm, pd.Timestamp.max

    adm_cache, dem_cache = carregar_adm_dem_cache(df_df_desligados, df_df_ativos, repo.df_semana_merged)
    adm = adm_cache.get(chapa_str)
    dem = dem_cache.get(chapa_str)
    if adm is None and dem is None:
        return None, None
    return adm, (pd.Timestamp.max if dem is None or pd.isna(dem) else dem)
