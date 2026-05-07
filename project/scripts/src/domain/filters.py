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

import threading
import time
from typing import Iterable, Sequence

import pandas as pd

from ..core.config import AREAS_FORA, get_settings
from ..core import repo_global as repo
from .cargo import normalize_cargo_columns
from .periods import LT_MONTHS, listar_segundas_periodo, periodo_limites
from .tenure import carregar_adm_dem_cache, sobrepoe_periodo

_FILTER_CACHE: dict[tuple, tuple[float, pd.DataFrame]] = {}
_FILTER_CACHE_LOCK = threading.Lock()
_MEDIA_CACHE: dict[tuple, tuple[float, pd.DataFrame]] = {}
_MEDIA_CACHE_LOCK = threading.Lock()


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
            deps = her_df[her_df["Área"] == subarea]["Heranca"].unique()
            return df[(df["Área"] == subarea) & (df["Heranca"].isin(deps))]
        deps = her_df[her_df["Área"] == area]["Heranca"].unique()
        return df[df["Área"].str.startswith(area) & df["Heranca"].isin(deps)]
    return df


def resolver_areas_viajantes(
    her_df: pd.DataFrame,
    areas_base: Sequence[str] | None = None,
) -> tuple[set[str], set[str]]:
    if areas_base is None:
        areas_base = AREAS_FORA
    areas_base_norm = [normaliza_str(area) for area in areas_base if normaliza_str(area)]

    if her_df is None or her_df.empty or not {"Área", "Heranca"}.issubset(her_df.columns):
        return set(areas_base_norm), set()

    tmp = her_df[["Área", "Heranca"]].copy()
    tmp["Área"] = tmp["Área"].astype(str).str.strip()
    tmp["Heranca"] = tmp["Heranca"].astype(str).str.strip()

    herancas_base = (
        tmp.loc[tmp["Área"].apply(lambda area: startswith_any(area, areas_base_norm)), "Heranca"]
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


def _cache_ttl() -> int:
    try:
        ttl = int(get_settings().cache_ttl)
    except Exception:
        ttl = 900
    return max(30, ttl)


def _periodo_key(periodo_idx) -> tuple[int, int]:
    if isinstance(periodo_idx, (list, tuple)) and len(periodo_idx) == 2:
        try:
            return int(periodo_idx[0]), int(periodo_idx[1])
        except Exception:
            pass
    return (0, len(LT_MONTHS) - 1)


def _frame_from_cache(cache: dict, lock: threading.Lock, key: tuple, ttl: int) -> pd.DataFrame | None:
    now = time.time()
    with lock:
        cached = cache.get(key)
        if cached is None:
            return None
        ts, df = cached
        if (now - ts) > ttl:
            cache.pop(key, None)
            return None
        return df.copy(deep=True)


def _store_frame_cache(cache: dict, lock: threading.Lock, key: tuple, df: pd.DataFrame) -> None:
    with lock:
        cache[key] = (time.time(), df.copy(deep=True))


def _cadastros_elegiveis(
    df_source: pd.DataFrame,
    dt_ini,
    dt_fim,
    df_semana_merged: pd.DataFrame,
) -> set[str]:
    if df_source.empty or "Cadastro" not in df_source.columns:
        return set()

    adm_cache, dem_cache = carregar_adm_dem_cache(
        repo.df_df_desligados if hasattr(repo, "df_df_desligados") else None,
        repo.df_df_ativos if hasattr(repo, "df_df_ativos") else None,
        df_semana_merged,
    )

    elegiveis: set[str] = set()
    for cad in df_source["Cadastro"].astype(str).dropna().unique():
        adm = adm_cache.get(str(cad), None)
        dem = dem_cache.get(str(cad), None)
        if sobrepoe_periodo(adm, dem, pd.Timestamp(dt_ini), pd.Timestamp(dt_fim)):
            elegiveis.add(str(cad))
    return elegiveis


def _agrupar_media_colaboradores(df_base: pd.DataFrame) -> pd.DataFrame:
    if df_base is None or df_base.empty:
        return pd.DataFrame(
            columns=[
                "Cadastro",
                "Nome",
                "Cargo",
                "Cargo Especifico",
                "Área",
                "Departamento",
                "Heranca",
                "Desligado",
                "Média Presença",
                "Dias Presenca",
                "Dias Monitorados",
            ]
        )

    defaults = {
        "Nome": "",
        "Cargo": "",
        "Cargo Especifico": "",
        "Área": "",
        "Departamento": "",
        "Heranca": "",
        "Desligado": "Não",
    }
    work = df_base.copy()
    for col, default in defaults.items():
        if col not in work.columns:
            work[col] = default
    if "Contagem Presença" not in work.columns:
        work["Contagem Presença"] = 0

    out = (
        work.groupby("Cadastro", as_index=False)
        .agg(
            {
                "Nome": "last",
                "Cargo": "last",
                "Cargo Especifico": "last",
                "Área": "last",
                "Departamento": "last",
                "Heranca": "last",
                "Desligado": "last",
                "Contagem Presença": ["mean", "sum", "size"],
            }
        )
        .reset_index(drop=True)
    )
    out.columns = [
        "Cadastro",
        "Nome",
        "Cargo",
        "Cargo Especifico",
        "Área",
        "Departamento",
        "Heranca",
        "Desligado",
        "Média Presença",
        "Dias Presenca",
        "Dias Monitorados",
    ]
    out["Cadastro"] = out["Cadastro"].astype(str)
    out["Média Presença"] = pd.to_numeric(out["Média Presença"], errors="coerce").fillna(0.0)
    out["Dias Presenca"] = pd.to_numeric(out["Dias Presenca"], errors="coerce").fillna(0.0)
    out["Dias Monitorados"] = (
        pd.to_numeric(out["Dias Monitorados"], errors="coerce").fillna(0.0).astype(int)
    )
    out = normalize_cargo_columns(out, cargo_col="Cargo", fallback_col="Cargo Especifico")
    return out


def _dias_monitorados_colaborador(
    cadastro: object,
    dt_ini,
    dt_fim,
    adm_cache: dict[str, pd.Timestamp],
    dem_cache: dict[str, pd.Timestamp],
) -> int:
    inicio = pd.Timestamp(dt_ini).normalize()
    fim = pd.Timestamp(dt_fim).normalize()
    cad = str(cadastro)
    adm = pd.to_datetime(adm_cache.get(cad), errors="coerce")
    dem = pd.to_datetime(dem_cache.get(cad), errors="coerce")
    if pd.notna(adm):
        inicio = max(inicio, adm.normalize())
    if pd.notna(dem):
        fim = min(fim, dem.normalize())
    if inicio > fim:
        return 0
    return len(listar_segundas_periodo(inicio, fim))


def _ajustar_media_para_periodo(
    df_media: pd.DataFrame,
    dt_ini,
    dt_fim,
    df_semana_merged: pd.DataFrame,
) -> pd.DataFrame:
    if df_media is None or df_media.empty or "Cadastro" not in df_media.columns:
        return df_media

    out = df_media.copy()
    adm_cache, dem_cache = carregar_adm_dem_cache(
        repo.df_df_desligados if hasattr(repo, "df_df_desligados") else None,
        repo.df_df_ativos if hasattr(repo, "df_df_ativos") else None,
        df_semana_merged,
    )
    if "Dias Presenca" not in out.columns:
        out["Dias Presenca"] = 0.0
    out["Dias Presenca"] = pd.to_numeric(out["Dias Presenca"], errors="coerce").fillna(0.0)
    out["Dias Monitorados"] = out["Cadastro"].apply(
        lambda cad: _dias_monitorados_colaborador(cad, dt_ini, dt_fim, adm_cache, dem_cache)
    )
    monitorados = pd.to_numeric(out["Dias Monitorados"], errors="coerce").fillna(0.0)
    out["Média Presença"] = (out["Dias Presenca"] / monitorados.where(monitorados > 0)).fillna(0.0)
    return out


def filtrar_base(
    df_desligados: str,
    viajam: str,
    area_selecionada: str | None,
    subarea_selecionada: str | None,
    periodo_idx,
    faixas,
    df_semana_merged: pd.DataFrame | None = None,
    her_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Filtra df_semana_merged aplicando periodo, elegibilidade, df_desligados/viajam e area."""
    df_semana_merged = df_semana_merged if df_semana_merged is not None else repo.df_semana_merged
    her_df = her_df if her_df is not None else getattr(repo, "her", pd.DataFrame())
    periodo_key = _periodo_key(periodo_idx)
    ttl = _cache_ttl()
    cache_key = (
        str(df_desligados),
        str(viajam),
        str(area_selecionada or ""),
        str(subarea_selecionada or ""),
        periodo_key,
        bool(getattr(repo, "USING_DW_SQLITE", False)),
    )
    cached = _frame_from_cache(_FILTER_CACHE, _FILTER_CACHE_LOCK, cache_key, ttl)
    if cached is not None:
        return cached

    dt_ini, dt_fim = periodo_limites(periodo_idx)
    if getattr(repo, "USING_DW_SQLITE", False):
        from .pipeline import dw_fetch_semana_enriquecida

        df_filtrado = dw_fetch_semana_enriquecida(dt_ini=dt_ini, dt_fim=dt_fim).copy()
    else:
        df_filtrado = filtrar_por_periodo(df_semana_merged, dt_ini, dt_fim).copy()

    if not df_filtrado.empty:
        elegiveis = _cadastros_elegiveis(df_filtrado, dt_ini, dt_fim, df_semana_merged)
        df_filtrado = df_filtrado[df_filtrado["Cadastro"].astype(str).isin(elegiveis)]

    if df_desligados == "right" and "Desligado" in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado["Desligado"] != "Sim"]

    if viajam == "right":
        areas_prefixos, herancas_prefixos = resolver_areas_viajantes(her_df)

        mask_area = False
        mask_her = False

        if "Área" in df_filtrado.columns:
            mask_area = df_filtrado["Área"].apply(lambda a: startswith_any(a, areas_prefixos))

        if "Heranca" in df_filtrado.columns and len(herancas_prefixos) > 0:
            mask_her = df_filtrado["Heranca"].apply(lambda h: startswith_any(h, herancas_prefixos))

        if isinstance(mask_area, pd.Series) and isinstance(mask_her, pd.Series):
            df_filtrado = df_filtrado[~(mask_area | mask_her)]
        elif isinstance(mask_area, pd.Series):
            df_filtrado = df_filtrado[~mask_area]
        elif isinstance(mask_her, pd.Series):
            df_filtrado = df_filtrado[~mask_her]

    df_filtrado = aplicar_filtro_por_area(df_filtrado, area_selecionada, subarea_selecionada, her_df)
    _store_frame_cache(_FILTER_CACHE, _FILTER_CACHE_LOCK, cache_key, df_filtrado)
    return df_filtrado.copy(deep=True)


def carregar_media_colaboradores(
    df_desligados: str,
    viajam: str,
    area_selecionada: str | None,
    subarea_selecionada: str | None,
    periodo_idx,
    df_semana_merged: pd.DataFrame | None = None,
    her_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Retorna média de presença por colaborador com priorização SQL + cache."""
    df_semana_merged = df_semana_merged if df_semana_merged is not None else repo.df_semana_merged
    her_df = her_df if her_df is not None else getattr(repo, "her", pd.DataFrame())
    periodo_key = _periodo_key(periodo_idx)
    cache_key = (
        str(df_desligados),
        str(viajam),
        str(area_selecionada or ""),
        str(subarea_selecionada or ""),
        periodo_key,
        bool(getattr(repo, "USING_DW_SQLITE", False)),
        "media_colab",
    )
    cached = _frame_from_cache(_MEDIA_CACHE, _MEDIA_CACHE_LOCK, cache_key, _cache_ttl())
    if cached is not None:
        return cached

    dt_ini, dt_fim = periodo_limites(periodo_idx)
    semanas_periodo = listar_segundas_periodo(dt_ini, dt_fim)
    if not semanas_periodo:
        return _agrupar_media_colaboradores(pd.DataFrame())

    if getattr(repo, "USING_DW_SQLITE", False):
        from .pipeline import query_dw

        semanas_sql = [pd.Timestamp(dia).strftime("%Y-%m-%d") for dia in semanas_periodo]
        placeholders = ",".join(["?"] * len(semanas_sql))
        sql = """
        SELECT
            "Cadastro",
            MAX("Nome") AS "Nome",
            MAX("Cargo") AS "Cargo",
            MAX("Cargo Especifico") AS "Cargo Especifico",
            MAX("Área") AS "Área",
            MAX("Departamento") AS "Departamento",
            MAX("Heranca") AS "Heranca",
            MAX("Desligado") AS "Desligado",
            AVG(COALESCE("Contagem Presença", 0.0)) AS "Média Presença",
            SUM(COALESCE("Contagem Presença", 0)) AS "Dias Presenca",
            COUNT(1) AS "Dias Monitorados"
        FROM vw_semana_enriquecida
        WHERE "Data" IN (__SEMANAS__)
        GROUP BY "Cadastro";
        """.replace("__SEMANAS__", placeholders)
        df_media = query_dw(
            sql,
            params=tuple(semanas_sql),
            cache_ttl=_cache_ttl(),
        )
        if "Cadastro" in df_media.columns:
            df_media["Cadastro"] = df_media["Cadastro"].astype(str)
        elegiveis = _cadastros_elegiveis(df_media, dt_ini, dt_fim, df_semana_merged)
        df_media = df_media[df_media["Cadastro"].isin(elegiveis)].copy()
    else:
        base = filtrar_por_periodo(df_semana_merged, dt_ini, dt_fim).copy()
        semanas_set = {pd.Timestamp(dia).normalize() for dia in semanas_periodo}
        if "Data" in base.columns:
            base["Data"] = pd.to_datetime(base["Data"], errors="coerce").dt.normalize()
            base = base[base["Data"].isin(semanas_set)].copy()
        elegiveis = _cadastros_elegiveis(base, dt_ini, dt_fim, df_semana_merged)
        base = base[base["Cadastro"].astype(str).isin(elegiveis)]
        df_media = _agrupar_media_colaboradores(base)

    df_media = _ajustar_media_para_periodo(df_media, dt_ini, dt_fim, df_semana_merged)

    if df_desligados == "right" and "Desligado" in df_media.columns:
        df_media = df_media[df_media["Desligado"] != "Sim"].copy()

    if viajam == "right":
        areas_prefixos, herancas_prefixos = resolver_areas_viajantes(her_df)
        if "Área" in df_media.columns:
            mask_area = df_media["Área"].apply(lambda a: startswith_any(a, areas_prefixos))
            df_media = df_media[~mask_area]
        if "Heranca" in df_media.columns and herancas_prefixos:
            mask_her = df_media["Heranca"].apply(lambda h: startswith_any(h, herancas_prefixos))
            df_media = df_media[~mask_her]

    df_media = aplicar_filtro_por_area(df_media, area_selecionada, subarea_selecionada, her_df)
    if "Cargo Especifico" not in df_media.columns and "Cargo" in df_media.columns:
        df_media["Cargo Especifico"] = df_media["Cargo"]
    if "Cargo" in df_media.columns:
        df_media = normalize_cargo_columns(
            df_media,
            cargo_col="Cargo",
            fallback_col="Cargo Especifico",
        )
    if "Nome" in df_media.columns:
        df_media = df_media.sort_values("Nome")

    _store_frame_cache(_MEDIA_CACHE, _MEDIA_CACHE_LOCK, cache_key, df_media)
    return df_media.copy(deep=True)
