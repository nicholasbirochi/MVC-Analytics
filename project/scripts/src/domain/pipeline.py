"""pipeline.py

Pipeline canonico (MVC) alinhado ao notebook `Projeto unificado.ipynb`.

O foco e reproduzir a mesma semantica de carregamento/normalizacao do DW SQLite
em funcoes pequenas e testaveis.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from ..core.config import Settings, get_settings

_REQUIRED_VIEWS = {
    "vw_colaboradores",
    "vw_df_diarios",
    "vw_df_registros_semanais",
    "vw_df_almoco",
    "vw_almoco_cluster",
    "vw_dim_data",
    "vw_df_diarios_unico",
    "vw_semana_enriquecida",
    "vw_gptw",
    "vw_movimentacoes",
    "vw_headcount",
}

_THREAD_STATE = threading.local()
_QUERY_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_QUERY_CACHE_LOCK = threading.Lock()
_READY_CONTRACT: dict[Path, tuple[int, int]] = {}


def _dw_path(settings: Settings) -> Path:
    if settings.dw_path is None:
        raise FileNotFoundError(
            "RONDA_DW_PATH nao configurado e DW padrao nao encontrado."
        )
    path = Path(settings.dw_path)
    if not path.exists():
        raise FileNotFoundError(f"DW SQLite nao encontrado em: {path}")
    return path


def _db_version(path: Path) -> tuple[int, int]:
    st = path.stat()
    return (getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)), st.st_size)


def _dw_connect(sqlite_path: Path, readonly: bool = True) -> sqlite3.Connection:
    if readonly:
        uri_path = sqlite_path.resolve().as_posix()
        uri = f"file:{uri_path}?mode=ro&immutable=1&cache=shared"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only = ON;")
    else:
        conn = sqlite3.connect(str(sqlite_path), check_same_thread=False)

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -400000;")
    return conn


def _get_conn(settings: Settings) -> sqlite3.Connection:
    path = _dw_path(settings)
    version = _db_version(path)

    conn = getattr(_THREAD_STATE, "conn", None)
    state_version = getattr(_THREAD_STATE, "version", None)
    state_path = getattr(_THREAD_STATE, "path", None)
    if conn is None or state_version != version or state_path != path:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
        conn = _dw_connect(path, readonly=True)
        _THREAD_STATE.conn = conn
        _THREAD_STATE.version = version
        _THREAD_STATE.path = path
    return conn


def _view_exists(conn: sqlite3.Connection, name: str) -> bool:
    q = "SELECT 1 FROM sqlite_master WHERE type IN ('view','table') AND name = ? LIMIT 1;"
    cur = conn.execute(q, (name,))
    return cur.fetchone() is not None


def _resolve_first_existing(conn: sqlite3.Connection, names: Iterable[str]) -> str | None:
    for name in names:
        if name and _view_exists(conn, name):
            return name
    return None


def _load_view(conn: sqlite3.Connection, view_name: str) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM {view_name}", conn)


def _ensure_contract(conn: sqlite3.Connection, sqlite_path: Path) -> None:
    version = _db_version(sqlite_path)
    if _READY_CONTRACT.get(sqlite_path) == version:
        return

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('view', 'table')"
    ).fetchall()
    existing = {row[0] for row in rows if row and row[0]}
    missing = sorted(_REQUIRED_VIEWS - existing)
    if missing:
        raise sqlite3.OperationalError(
            "DW SQLite nao esta no contrato esperado para o app. "
            f"Faltando: {missing}"
        )
    _READY_CONTRACT[sqlite_path] = version


def query_dw(
    sql: str,
    params: tuple = (),
    parse_dates=None,
    cache_ttl: int = 900,
    cache_max_rows: int = 250_000,
    settings: Settings | None = None,
) -> pd.DataFrame:
    """Executa SQL no DW com cache em memoria (read-only)."""
    settings = settings or get_settings()
    sqlite_path = _dw_path(settings)
    conn = _get_conn(settings)
    _ensure_contract(conn, sqlite_path)

    parse_dates_key = tuple(parse_dates) if parse_dates is not None else None
    key_payload = repr(
        (sql, tuple(params), parse_dates_key, _db_version(sqlite_path))
    ).encode("utf-8")
    cache_key = hashlib.sha256(key_payload).hexdigest()

    now = time.time()
    with _QUERY_CACHE_LOCK:
        cached = _QUERY_CACHE.get(cache_key)
        if cached is not None and (now - cached[0]) <= cache_ttl:
            return cached[1].copy(deep=True)

    df = pd.read_sql_query(sql, conn, params=params, parse_dates=parse_dates)
    if len(df) <= cache_max_rows:
        with _QUERY_CACHE_LOCK:
            _QUERY_CACHE[cache_key] = (now, df.copy(deep=True))
    return df


def load_sources(config: Settings | None = None) -> dict[str, pd.DataFrame]:
    """Carrega fontes canônicas do DW SQLite."""
    settings = config or get_settings()
    sqlite_path = _dw_path(settings)
    conn = _dw_connect(sqlite_path, readonly=True)
    try:
        _ensure_contract(conn, sqlite_path)

        vw_colab = _resolve_first_existing(
            conn, ["vw_colaboradores", "vw_dim_colaboradores", "dim_colaborador"]
        )
        if vw_colab == "dim_colaborador":
            df_colaboradores = pd.read_sql_query(
                'SELECT cadastro AS "Cadastro", nome AS "Nome", cargo AS "Cargo", '
                'cargo_especifico AS "Cargo Especifico", area AS "Área", '
                'departamento AS "Departamento", heranca AS "Heranca", '
                'desligado AS "Desligado" FROM dim_colaborador',
                conn,
            )
        elif vw_colab:
            df_colaboradores = _load_view(conn, vw_colab)
        else:
            raise sqlite3.OperationalError("View de colaboradores nao encontrada no DW.")

        vw_sem = _resolve_first_existing(
            conn, ["vw_semana_enriquecida", "vw_df_registros_semanais"]
        )
        if vw_sem == "vw_semana_enriquecida":
            df_registros_semanais = _load_view(conn, "vw_df_registros_semanais")
            # Evita carregar uma view já denormalizada muito grande no bootstrap do app.
            # A versão enriquecida é buscada sob demanda em `dw_fetch_semana_enriquecida`.
            df_semana_enriquecida = pd.DataFrame()
        else:
            df_registros_semanais = _load_view(conn, "vw_df_registros_semanais")
            df_semana_enriquecida = pd.DataFrame()

        df_diarios = pd.DataFrame(columns=["Cadastro", "Planta", "Data"])
        df_almoco = pd.DataFrame(
            columns=[
                "Cadastro",
                "Data",
                "Hora",
                "Dir",
                "Planta",
                "Coletor",
                "Descricao Coletor",
            ]
        )

        df_headcount = pd.DataFrame()
        if _view_exists(conn, "vw_headcount"):
            df_headcount = _load_view(conn, "vw_headcount")
        elif _view_exists(conn, "headcount"):
            df_raw = pd.read_sql_query("SELECT * FROM headcount", conn)
            if isinstance(df_raw, pd.DataFrame) and not df_raw.empty:
                if ("Área" in df_raw.columns) or ("2023 hc" in df_raw.columns):
                    df_headcount = df_raw
                else:
                    cols_l = {str(c).lower(): c for c in df_raw.columns}
                    ren = {}
                    if "area" in cols_l:
                        ren[cols_l["area"]] = "Área"
                    if "heranca" in cols_l:
                        ren[cols_l["heranca"]] = "Heranca"
                    for year in (2023, 2024, 2025):
                        for key, out in [("hc", "hc"), ("e", "e"), ("s", "s")]:
                            k = f"y{year}_{key}"
                            if k in cols_l:
                                ren[cols_l[k]] = f"{year} {out}"
                    df_headcount = df_raw.rename(columns=ren)

        df_movimentacoes = (
            _load_view(conn, "vw_movimentacoes")
            if _view_exists(conn, "vw_movimentacoes")
            else pd.DataFrame()
        )
        df_gptw = (
            _load_view(conn, "vw_gptw")
            if _view_exists(conn, "vw_gptw")
            else pd.DataFrame()
        )
    finally:
        conn.close()

    for dff in (
        df_colaboradores,
        df_diarios,
        df_registros_semanais,
        df_almoco,
        df_headcount,
        df_movimentacoes,
        df_gptw,
        df_semana_enriquecida,
    ):
        if "Cadastro" in dff.columns:
            dff["Cadastro"] = dff["Cadastro"].astype(str)

    for dff in (df_diarios, df_registros_semanais, df_almoco, df_semana_enriquecida):
        if "Data" in dff.columns:
            dff["Data"] = pd.to_datetime(dff["Data"], errors="coerce")

    if "Data de alteração" in df_movimentacoes.columns:
        df_movimentacoes["Data de alteração"] = pd.to_datetime(
            df_movimentacoes["Data de alteração"], errors="coerce"
        )
        df_movimentacoes["Ano"] = df_movimentacoes["Data de alteração"].dt.year.astype(
            "Int64"
        )

    if "Desligado" in df_colaboradores.columns:
        desligado = df_colaboradores["Desligado"].astype("string").str.strip().str.lower()
        df_colaboradores["Desligado"] = np.where(
            desligado.isin(["1", "true", "sim", "yes", "y", "t"]),
            "Sim",
            "Não",
        )

    if "Área" not in df_colaboradores.columns and "Area" in df_colaboradores.columns:
        df_colaboradores = df_colaboradores.rename(columns={"Area": "Área"})

    return {
        "df_colaboradores": df_colaboradores,
        "df_registros_semanais": df_registros_semanais,
        "df_semana_enriquecida": df_semana_enriquecida,
        "df_diarios": df_diarios,
        "df_almoco": df_almoco,
        "df_headcount": df_headcount,
        "df_movimentacoes": df_movimentacoes,
        "df_gptw": df_gptw,
    }


def build_dimensions(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Constroi dimensoes (ativos/desligados/colaboradores)."""
    df_colaboradores = raw["df_colaboradores"].copy()
    if "Desligado" in df_colaboradores.columns:
        df_df_ativos = df_colaboradores[df_colaboradores["Desligado"] != "Sim"].copy()
        df_df_desligados = df_colaboradores[
            df_colaboradores["Desligado"] == "Sim"
        ].copy()
    else:
        df_df_ativos = df_colaboradores.copy()
        df_df_desligados = df_colaboradores.iloc[0:0].copy()

    for col in ("Data_Adm", "Data_Dem"):
        if col not in df_df_desligados.columns:
            df_df_desligados[col] = pd.NaT

    return {
        "df_colaboradores": df_colaboradores,
        "df_df_ativos": df_df_ativos,
        "df_df_desligados": df_df_desligados,
    }


def build_facts(
    raw: dict[str, pd.DataFrame],
    dims: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Constroi fatos principais para o MVC."""
    df_semana_enriquecida = raw["df_semana_enriquecida"].copy()
    df_registros_semanais = raw["df_registros_semanais"].copy()
    df_colaboradores = dims["df_colaboradores"].copy()

    if not df_semana_enriquecida.empty:
        df_semana_merged = df_semana_enriquecida
    else:
        # Mantem bootstrap leve: evita denormalizar 1+ milhao de linhas em memoria.
        df_semana_merged = df_registros_semanais.copy()

    for dff in (df_semana_merged, raw["df_diarios"], raw["df_almoco"]):
        if "Cadastro" in dff.columns:
            dff["Cadastro"] = dff["Cadastro"].astype(str)
        if "Data" in dff.columns:
            dff["Data"] = pd.to_datetime(dff["Data"], errors="coerce")

    if "Dia Semana" not in df_semana_merged.columns and "Data" in df_semana_merged.columns:
        dias_pt = {
            0: "Segunda",
            1: "Terça",
            2: "Quarta",
            3: "Quinta",
            4: "Sexta",
            5: "Sábado",
            6: "Domingo",
        }
        df_semana_merged["Dia Semana"] = df_semana_merged["Data"].dt.weekday.map(dias_pt)

    if "Cargo" not in df_semana_merged.columns and "Cargo Especifico" in df_semana_merged.columns:
        df_semana_merged = df_semana_merged.assign(
            Cargo=df_semana_merged["Cargo Especifico"]
        )

    return {
        "df_semana_merged": df_semana_merged,
        "df_datas": raw["df_diarios"].copy(),
        "df_almoco": raw["df_almoco"].copy(),
        "df_headcount": raw["df_headcount"].copy(),
        "df_df_gptw": raw["df_gptw"].copy(),
        "df_movimentacoes": raw["df_movimentacoes"].copy(),
    }


def _build_dropdown_options(her_df: pd.DataFrame) -> list[dict]:
    if her_df.empty:
        return [{"label": "Geral (todas as areas)", "value": "GERAL"}]
    options = [{"label": "Geral (todas as areas)", "value": "GERAL"}]
    for _, row in her_df.iterrows():
        area = row.get("Área", "")
        dept = row.get("Departamento", "")
        options.append({"label": f"{area} {dept}", "value": area})
    return options


def compute_metrics(
    facts: dict[str, pd.DataFrame],
    dims: dict[str, pd.DataFrame],
    params: dict | None = None,
) -> dict[str, pd.DataFrame | list[dict]]:
    """Calcula agregacoes canônicas usadas pelo MVC."""
    del dims, params
    df_semana_merged = facts["df_semana_merged"]
    count_cols = [
        "Cadastro",
        "Nome",
        "Área",
        "Departamento",
        "Heranca",
        "Cargo Especifico",
        "Desligado",
    ]

    if "Dia Semana" in df_semana_merged.columns and all(
        col in df_semana_merged.columns for col in count_cols
    ):
        df_count_por_semana = (
            df_semana_merged.groupby(
                count_cols
            )["Dia Semana"]
            .value_counts()
            .reset_index()
        )
        df_count_por_semana.columns = [
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
    else:
        df_count_por_semana = pd.DataFrame(
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

    if (
        df_semana_merged.empty
        or "Área" not in df_semana_merged.columns
        or "Departamento" not in df_semana_merged.columns
        or "Heranca" not in df_semana_merged.columns
    ):
        her = pd.DataFrame(columns=["Área", "Departamento", "Heranca"])
    else:
        her = (
            df_semana_merged[["Área", "Departamento", "Heranca"]]
            .drop_duplicates()
            .sort_values("Área")
        )

    return {
        "df_count_por_semana": df_count_por_semana,
        "her": her,
        "dropdown_options": _build_dropdown_options(her),
    }


def build_figures(metrics: dict[str, object]) -> dict[str, object]:
    """Hook de figuras (mantido para contrato do pipeline canônico)."""
    del metrics
    return {}


def run_pipeline(
    config: Settings | None = None,
    params: dict | None = None,
) -> dict[str, object]:
    """Executa o pipeline completo e retorna artefatos usados pelo MVC."""
    settings = config or get_settings()
    raw = load_sources(settings)
    dims = build_dimensions(raw)
    facts = build_facts(raw, dims)
    metrics = compute_metrics(facts, dims, params=params)
    figures = build_figures(metrics)
    return {**dims, **facts, **metrics, "figures": figures}


def _sql_in_clause(values: Iterable[object]) -> tuple[str, tuple[str, ...]]:
    vals = [str(v) for v in (values or []) if str(v).strip()]
    if not vals:
        return "1=0", ()
    placeholders = ",".join(["?"] * len(vals))
    return f"IN ({placeholders})", tuple(vals)


def dw_fetch_semana_enriquecida(
    cadastro: str | None = None,
    dt_ini=None,
    dt_fim=None,
    settings: Settings | None = None,
) -> pd.DataFrame:
    where = []
    params: list[str] = []
    if cadastro is not None:
        where.append('"Cadastro" = ?')
        params.append(str(cadastro))
    if dt_ini is not None and dt_fim is not None:
        where.append('"Data" BETWEEN ? AND ?')
        params.extend(
            [
                pd.Timestamp(dt_ini).strftime("%Y-%m-%d"),
                pd.Timestamp(dt_fim).strftime("%Y-%m-%d"),
            ]
        )
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = f'SELECT * FROM vw_semana_enriquecida{where_sql};'
    return query_dw(sql, tuple(params), parse_dates=["Data"], settings=settings)


def dw_fetch_diarios(
    cadastros: Iterable[object],
    dt_ini=None,
    dt_fim=None,
    settings: Settings | None = None,
) -> pd.DataFrame:
    where = []
    params: list[str] = []
    in_sql, in_params = _sql_in_clause(cadastros)
    where.append(f'"Cadastro" {in_sql}')
    params.extend(in_params)
    if dt_ini is not None and dt_fim is not None:
        where.append('"Data" BETWEEN ? AND ?')
        params.extend(
            [
                pd.Timestamp(dt_ini).strftime("%Y-%m-%d"),
                pd.Timestamp(dt_fim).strftime("%Y-%m-%d"),
            ]
        )
    sql = (
        'SELECT "Cadastro","Planta","Data" AS "Data" FROM vw_df_diarios_unico WHERE '
        + " AND ".join(where)
        + ";"
    )
    return query_dw(sql, tuple(params), parse_dates=["Data"], settings=settings)


def dw_fetch_almoco(
    cadastros: Iterable[object],
    dt_ini=None,
    dt_fim=None,
    settings: Settings | None = None,
) -> pd.DataFrame:
    where = []
    params: list[str] = []
    in_sql, in_params = _sql_in_clause(cadastros)
    where.append(f'"Cadastro" {in_sql}')
    params.extend(in_params)
    if dt_ini is not None and dt_fim is not None:
        where.append('"Data" BETWEEN ? AND ?')
        params.extend(
            [
                pd.Timestamp(dt_ini).strftime("%Y-%m-%d"),
                pd.Timestamp(dt_fim).strftime("%Y-%m-%d"),
            ]
        )
    sql = (
        'SELECT "Cadastro","Data" AS "Data","Hora","Dir","Planta","Coletor","Descricao Coletor" '
        "FROM vw_df_almoco WHERE "
        + " AND ".join(where)
        + ";"
    )
    return query_dw(sql, tuple(params), parse_dates=["Data"], settings=settings)


def dw_almoco_min_max(settings: Settings | None = None):
    df = query_dw(
        'SELECT MIN("Data") AS dmin, MAX("Data") AS dmax FROM vw_df_almoco;',
        (),
        settings=settings,
    )
    if df.empty or pd.isna(df.loc[0, "dmax"]):
        return None, None
    return pd.to_datetime(df.loc[0, "dmin"]), pd.to_datetime(df.loc[0, "dmax"])


def build_dataframe_diario_area_sql(
    area: str | None,
    subarea: str | None,
    dt_ini=None,
    dt_fim=None,
    settings: Settings | None = None,
) -> pd.DataFrame:
    """Replica a consulta canônica do notebook para relacionamento geral."""
    del settings
    empty_cols = [
        "Data",
        "Cadastro",
        "Nome",
        "Cargo",
        "Área",
        "Departamento",
        "Planta",
        "Contagem Presença",
    ]
    alvo = str((subarea or area or "")).strip()
    if not alvo:
        return pd.DataFrame(columns=empty_cols)

    if dt_ini is None or dt_fim is None:
        mm = query_dw('SELECT MIN("Data") AS dmin, MAX("Data") AS dmax FROM vw_df_diarios_unico;')
        if mm.empty or pd.isna(mm.loc[0, "dmax"]):
            return pd.DataFrame(columns=empty_cols)
        dmax = pd.to_datetime(mm.loc[0, "dmax"])
        dt_fim = dmax.normalize()
        dt_ini = (dt_fim - pd.DateOffset(months=3)).normalize()
    else:
        dt_ini = pd.Timestamp(dt_ini).normalize()
        dt_fim = pd.Timestamp(dt_fim).normalize()
        if dt_ini > dt_fim:
            dt_ini, dt_fim = dt_fim, dt_ini

    if subarea:
        where_area = 'c."Área" = ?'
        params_area = (str(subarea).strip(),)
    else:
        where_area = 'LOWER(c."Área") LIKE ?'
        params_area = (f"%{str(area).strip().lower()}%",)

    sql = f"""
    WITH cad AS (
      SELECT c."Cadastro", c."Nome", c."Cargo", c."Área", c."Departamento"
      FROM vw_colaboradores c
      WHERE {where_area}
    ),
    datas AS (
      SELECT d."Data"
      FROM vw_dim_data d
      WHERE d."Data" BETWEEN ? AND ?
    ),
    pres AS (
      SELECT p."Cadastro", p."Data", p."Planta"
      FROM vw_df_diarios_unico p
      JOIN cad ON cad."Cadastro" = p."Cadastro"
      WHERE p."Data" BETWEEN ? AND ?
    )
    SELECT
      datas."Data" AS "Data",
      cad."Cadastro" AS "Cadastro",
      cad."Nome" AS "Nome",
      cad."Cargo" AS "Cargo",
      cad."Área" AS "Área",
      cad."Departamento" AS "Departamento",
      pres."Planta" AS "Planta",
      CASE WHEN pres."Cadastro" IS NULL THEN 0 ELSE 1 END AS "Contagem Presença"
    FROM datas
    CROSS JOIN cad
    LEFT JOIN pres
      ON pres."Cadastro" = cad."Cadastro" AND pres."Data" = datas."Data"
    ORDER BY cad."Cadastro", datas."Data";
    """

    params = params_area + (
        dt_ini.strftime("%Y-%m-%d"),
        dt_fim.strftime("%Y-%m-%d"),
        dt_ini.strftime("%Y-%m-%d"),
        dt_fim.strftime("%Y-%m-%d"),
    )
    df = query_dw(sql, params=params, parse_dates=["Data"])
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    df["Cadastro"] = df["Cadastro"].astype(str)
    df["Contagem Presença"] = (
        pd.to_numeric(df["Contagem Presença"], errors="coerce").fillna(0).astype(int)
    )
    return df


def build_dataframe_almoco_area_sql(
    area: str | None,
    subarea: str | None,
    dt_ini=None,
    dt_fim=None,
    pessoas_alvo: tuple[str, str] | None = None,
) -> pd.DataFrame:
    """Replica a consulta canônica do notebook para relacionamento de almoço."""
    empty_cols = [
        "Data",
        "Cadastro",
        "Nome",
        "Cargo",
        "Área",
        "Departamento",
        "Planta",
        "Contagem Presença",
    ]
    alvo = str((subarea or area or "")).strip()
    if not alvo:
        return pd.DataFrame(columns=empty_cols)

    if dt_ini is None or dt_fim is None:
        dmin, dmax = dw_almoco_min_max()
        if dmax is None:
            return pd.DataFrame(columns=empty_cols)
        dt_fim = pd.Timestamp(dmax).normalize()
        dt_ini = (dt_fim - pd.DateOffset(months=3)).normalize()
    else:
        dt_ini = pd.Timestamp(dt_ini).normalize()
        dt_fim = pd.Timestamp(dt_fim).normalize()
        if dt_ini > dt_fim:
            dt_ini, dt_fim = dt_fim, dt_ini

    if subarea:
        where_area = 'c."Área" = ?'
        params_area = (str(subarea).strip(),)
    else:
        where_area = 'LOWER(c."Área") LIKE ?'
        params_area = (f"%{str(area).strip().lower()}%",)

    pair_clause = ""
    pair_params: tuple[str, str] | tuple[()] = ()
    if isinstance(pessoas_alvo, tuple) and len(pessoas_alvo) == 2:
        c1, c2 = map(str, pessoas_alvo)
        pair_clause = (
            'AND final."Data" IN (SELECT "Data" FROM clust WHERE "Cadastro" = ? '
            'INTERSECT SELECT "Data" FROM clust WHERE "Cadastro" = ?)'
        )
        pair_params = (c1, c2)

    sql = f"""
    WITH cad AS (
      SELECT c."Cadastro", c."Nome", c."Cargo", c."Área", c."Departamento"
      FROM vw_colaboradores c
      WHERE {where_area}
    ),
    clust AS (
      SELECT
        a."Data" AS "Data",
        a."Cadastro" AS "Cadastro",
        REPLACE(GROUP_CONCAT(DISTINCT a."Planta"), ',', '|') AS "Planta"
      FROM vw_almoco_cluster a
      JOIN cad ON cad."Cadastro" = a."Cadastro"
      WHERE a."Data" BETWEEN ? AND ?
      GROUP BY a."Data", a."Cadastro"
    ),
    pres_por_dia AS (
      SELECT "Data", COUNT(DISTINCT "Cadastro") AS qtde_pessoas
      FROM clust
      GROUP BY "Data"
    ),
    final AS (
      SELECT
        clust."Data" AS "Data",
        clust."Cadastro" AS "Cadastro",
        cad."Nome" AS "Nome",
        cad."Cargo" AS "Cargo",
        cad."Área" AS "Área",
        cad."Departamento" AS "Departamento",
        clust."Planta" AS "Planta",
        1 AS "Contagem Presença"
      FROM clust
      JOIN cad ON cad."Cadastro" = clust."Cadastro"
      JOIN pres_por_dia p ON p."Data" = clust."Data"
      WHERE p.qtde_pessoas > 1
    )
    SELECT * FROM final
    WHERE 1=1 {pair_clause}
    ORDER BY "Cadastro","Data";
    """

    params = params_area + (
        dt_ini.strftime("%Y-%m-%d"),
        dt_fim.strftime("%Y-%m-%d"),
    ) + pair_params
    df = query_dw(sql, params=params, parse_dates=["Data"])
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    df["Cadastro"] = df["Cadastro"].astype(str)
    df["Contagem Presença"] = (
        pd.to_numeric(df["Contagem Presença"], errors="coerce").fillna(0).astype(int)
    )
    df["Planta"] = df["Planta"].astype(str).fillna("")
    return df
