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

import pandas as pd

from ..core import repo_global as repo


def _norm_df(df):
    return df if isinstance(df, pd.DataFrame) and not df.empty else None


def coletar_admissoes_e_demissoes(
    df_desligados: pd.DataFrame | None = None,
    df_ativos: pd.DataFrame | None = None,
    df_semana_merged: pd.DataFrame | None = None,
) -> tuple[dict[str, pd.Timestamp], dict[str, pd.Timestamp]]:
    if df_desligados is None:
        df_desligados = repo.df_desligados
    if df_ativos is None:
        df_ativos = repo.df_ativos
    if df_semana_merged is None:
        df_semana_merged = repo.df_semana_merged

    adm: dict[str, pd.Timestamp] = {}
    dem: dict[str, pd.Timestamp] = {}

    def _put(target: dict[str, pd.Timestamp], key: str, value: pd.Timestamp) -> None:
        if pd.isna(value):
            return
        if (key not in target) or (value < target[key]):
            target[key] = value

    dfa = _norm_df(df_desligados)
    if dfa is not None and "Cadastro" in dfa.columns:
        cad_series = dfa["Cadastro"].astype(str)
        if "Data_Adm" in dfa.columns:
            datas_adm = pd.to_datetime(dfa["Data_Adm"], errors="coerce")
            for cad, data in zip(cad_series, datas_adm):
                _put(adm, cad, data)
        if "Data_Dem" in dfa.columns:
            datas_dem = pd.to_datetime(dfa["Data_Dem"], errors="coerce")
            for cad, data in zip(cad_series, datas_dem):
                _put(dem, cad, data)

    dfd = _norm_df(df_ativos)
    if dfd is not None and {"Cadastro", "Data Admissao"}.issubset(dfd.columns):
        tmp = dfd[["Cadastro", "Data Admissao"]].copy()
        tmp["Cadastro"] = tmp["Cadastro"].astype(str)
        tmp["Data Admissao"] = pd.to_datetime(tmp["Data Admissao"], errors="coerce")
        tmp = tmp.dropna(subset=["Data Admissao"]).drop_duplicates("Cadastro", keep="first")
        for cad, data in zip(tmp["Cadastro"], tmp["Data Admissao"]):
            _put(adm, cad, data)

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
                _put(adm, cad, data)

    return adm, dem


ADM_CACHE: dict[str, pd.Timestamp] | None = None
DEM_CACHE: dict[str, pd.Timestamp] | None = None


def carregar_adm_dem_cache(
    df_desligados: pd.DataFrame | None = None,
    df_ativos: pd.DataFrame | None = None,
    df_semana: pd.DataFrame | None = None,
) -> tuple[dict[str, pd.Timestamp], dict[str, pd.Timestamp]]:
    global ADM_CACHE, DEM_CACHE
    if ADM_CACHE is None or DEM_CACHE is None:
        ADM_CACHE, DEM_CACHE = coletar_admissoes_e_demissoes(
            df_desligados, df_ativos, df_semana
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
    df_desligados: pd.DataFrame | None = None,
    df_ativos: pd.DataFrame | None = None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if df_desligados is None:
        df_desligados = repo.df_desligados
    if df_ativos is None:
        df_ativos = repo.df_ativos

    chapa_str = str(chapa)

    pessoa_desligados = df_desligados[df_desligados["Cadastro"] == chapa_str]
    if not pessoa_desligados.empty:
        adm = pd.to_datetime(pessoa_desligados["Data_Adm"].iloc[0], errors="coerce")
        dem = pd.to_datetime(pessoa_desligados["Data_Dem"].iloc[0], errors="coerce")
        if pd.isna(dem):
            dem = pd.Timestamp.max
        return adm, dem

    pessoa_ativos = df_ativos[df_ativos["Cadastro"] == chapa_str]
    if not pessoa_ativos.empty:
        adm = pd.to_datetime(
            pessoa_ativos["Data Admissao"].iloc[0],
            dayfirst=True,
            errors="coerce",
        )
        return adm, pd.Timestamp.max

    return None, None