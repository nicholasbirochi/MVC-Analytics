"""Reconstrói um DW SQLite funcional a partir dos parquets brutos.

Objetivo:
- restaurar contrato mínimo esperado pelo MVC;
- preservar análise semanal de presença;
- classificar terceiros como `T`.
"""
from __future__ import annotations

import argparse
import sqlite3
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

from ..domain.cargo import normalize_cargo_series


DEFAULT_RAW_BASE = Path("Base de Dados Original/parquet")
DEFAULT_OUT_DW = Path("project/database/dw_ronda_rebuilt.sqlite")
REGISTRO_MANUAL_COL = "registro_manual"


def _norm_col_name(name: object) -> str:
    text = "" if name is None else str(name).strip()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = (
        text.replace(" ", "_")
        .replace(".", "_")
        .replace("/", "_")
        .replace("-", "_")
    )
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _pick_col(columns: list[str], options: tuple[str, ...]) -> str | None:
    mapping = {_norm_col_name(c): c for c in columns}
    for opt in options:
        if opt in mapping:
            return mapping[opt]
    return None


def _normalize_cadastro(series: pd.Series) -> pd.Series:
    out = series.astype("string").str.strip()
    out = out.str.replace(r"\.0$", "", regex=True)
    return out.where(~out.fillna("").isin({"", "nan", "none", "null"}), pd.NA)


def _load_hr_dimension(raw_base: Path) -> pd.DataFrame:
    ativos_path = raw_base / "Ativos" / "Ativos.parquet"
    deslig_path = raw_base / "Desligados" / "Desligados.parquet"

    frames: list[pd.DataFrame] = []
    for path, desligado in ((ativos_path, "Não"), (deslig_path, "Sim")):
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        cols = list(df.columns)
        c_cad = _pick_col(cols, ("cadastro", "chapa"))
        if c_cad is None:
            continue
        c_nome = _pick_col(cols, ("nome_completo", "nome", "nome_colaborador"))
        c_cargo = _pick_col(cols, ("cargo", "tipo_colaborador"))
        c_cargo_esp = _pick_col(cols, ("cargo_especifico", "desc_cargo"))
        c_area = _pick_col(cols, ("area",))
        c_dept = _pick_col(cols, ("departamento", "desc_uo"))
        c_her = _pick_col(cols, ("heranca",))

        aux = pd.DataFrame(
            {
                "cadastro": _normalize_cadastro(df[c_cad]),
                "nome": df[c_nome].astype("string").str.strip() if c_nome else "",
                "cargo": df[c_cargo].astype("string").str.strip() if c_cargo else "",
                "cargo_especifico": (
                    df[c_cargo_esp].astype("string").str.strip() if c_cargo_esp else ""
                ),
                "area": df[c_area].astype("string").str.strip() if c_area else "",
                "departamento": df[c_dept].astype("string").str.strip() if c_dept else "",
                "heranca": df[c_her].astype("string").str.strip() if c_her else "",
                "desligado": desligado,
            }
        )
        frames.append(aux)

    if not frames:
        return pd.DataFrame(
            columns=[
                "cadastro",
                "nome",
                "cargo",
                "cargo_especifico",
                "area",
                "departamento",
                "heranca",
                "desligado",
            ]
        )

    hr = pd.concat(frames, ignore_index=True)
    hr = hr.dropna(subset=["cadastro"])
    hr = hr[hr["cadastro"].astype(str).str.strip() != ""]
    # mapeamento legado em algumas bases: 1=Horista, 2=Terceiro
    hr["cargo"] = hr["cargo"].replace({"1": "H", "2": "T"})
    hr["cargo"] = normalize_cargo_series(hr["cargo"])
    empty_cargo = hr["cargo"].astype(str).str.strip().eq("")
    if "cargo_especifico" in hr.columns:
        hr.loc[empty_cargo, "cargo"] = normalize_cargo_series(hr.loc[empty_cargo, "cargo_especifico"])

    hr = (
        hr.sort_values(["cadastro", "desligado"])
        .groupby("cadastro", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    return hr


def _category_dir(raw_base: Path, source_group: str, folder: str) -> Path:
    grouped = raw_base / source_group / folder
    if grouped.exists():
        return grouped
    return raw_base / folder


def _sql_union_logs(raw_base: Path) -> str:
    folders = [
        ("Executivos", "E"),
        ("Mensalistas", "M"),
        ("Horistas", "H"),
        ("Terceiros", "T"),
    ]
    parts: list[str] = []
    for folder, cargo in folders:
        registros_dir = _category_dir(raw_base, "Registros", folder)
        if registros_dir.exists() and any(registros_dir.glob("*.parquet")):
            glob = (registros_dir / "*.parquet").resolve().as_posix()
            parts.append(
                f"""
                SELECT
                  CAST(CHAPA AS VARCHAR) AS cadastro,
                  CAST(NOME_COLABORADOR AS VARCHAR) AS nome,
                  CAST(DATA_ACESSO AS VARCHAR) AS data_raw,
                  CAST(TIPO_ACESSO AS VARCHAR) AS tipo_raw,
                  CAST(CODIGO_PLANTA AS VARCHAR) AS planta_raw,
                  '{cargo}' AS cargo_src,
                  'Não' AS {REGISTRO_MANUAL_COL}
                FROM read_parquet('{glob}', union_by_name=true)
                """
            )

        ajustes_dir = _category_dir(raw_base, "Ajustes Manuais", folder)
        if ajustes_dir.exists() and any(ajustes_dir.glob("*.parquet")):
            glob = (ajustes_dir / "*.parquet").resolve().as_posix()
            parts.append(
                f"""
                SELECT
                  CAST(CHAPA AS VARCHAR) AS cadastro,
                  CAST(NOME_COLABORADOR AS VARCHAR) AS nome,
                  CAST(DATA_ACESSO AS VARCHAR) AS data_raw,
                  CAST(TIPO_ACESSO AS VARCHAR) AS tipo_raw,
                  CAST(CODIGO_PLANTA AS VARCHAR) AS planta_raw,
                  '{cargo}' AS cargo_src,
                  'Sim' AS {REGISTRO_MANUAL_COL}
                FROM read_parquet('{glob}', union_by_name=true)
                """
            )
    if not parts:
        raise FileNotFoundError(f"Nenhum parquet de registros encontrado em: {raw_base}")
    return "\nUNION ALL\n".join(parts)


def _create_sqlite_contract_views(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_colaboradores AS
        SELECT
          cadastro AS "Cadastro",
          nome AS "Nome",
          cargo AS "Cargo",
          cargo_especifico AS "Cargo Especifico",
          area AS "Área",
          departamento AS "Departamento",
          heranca AS "Heranca",
          desligado AS "Desligado"
        FROM dim_colaborador;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_df_registros_semanais AS
        SELECT
          cadastro AS "Cadastro",
          ano AS "Ano",
          semana_por_ano AS "Semana por Ano",
          data AS "Data",
          contagem_presenca AS "Contagem Presença"
        FROM agg_registros_semanais;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_semana_enriquecida AS
        SELECT
          a.cadastro AS "Cadastro",
          c.nome AS "Nome",
          c.cargo AS "Cargo",
          c.cargo_especifico AS "Cargo Especifico",
          c.area AS "Área",
          c.departamento AS "Departamento",
          c.heranca AS "Heranca",
          c.desligado AS "Desligado",
          a.ano AS "Ano",
          a.semana_por_ano AS "Semana por Ano",
          a.data AS "Data",
          a.contagem_presenca AS "Contagem Presença"
        FROM agg_registros_semanais a
        LEFT JOIN dim_colaborador c
          ON c.cadastro = a.cadastro;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_df_diarios_unico AS
        SELECT
          cadastro AS "Cadastro",
          planta AS "Planta",
          data AS "Data",
          registro_manual AS "registro_manual"
        FROM diarios_unico;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_df_diarios AS
        SELECT
          cadastro AS "Cadastro",
          planta AS "Planta",
          data AS "Data",
          registro_manual AS "registro_manual"
        FROM diarios_unico;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_dim_data AS
        SELECT DISTINCT
          data AS "Data"
        FROM diarios_unico;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_df_almoco AS
        SELECT
          CAST(NULL AS TEXT) AS "Cadastro",
          CAST(NULL AS DATE) AS "Data",
          CAST(NULL AS TEXT) AS "Hora",
          CAST(NULL AS TEXT) AS "Dir",
          CAST(NULL AS TEXT) AS "Planta",
          CAST(NULL AS TEXT) AS "Coletor",
          CAST(NULL AS TEXT) AS "Descricao Coletor"
        WHERE 1=0;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_almoco_cluster AS
        SELECT
          CAST(NULL AS DATE) AS "Data",
          CAST(NULL AS TEXT) AS "Cadastro",
          CAST(NULL AS TEXT) AS "Planta"
        WHERE 1=0;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_gptw AS
        SELECT * FROM gptw;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_movimentacoes AS
        SELECT * FROM movimentacoes;
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW out_db.vw_headcount AS
        SELECT * FROM headcount;
        """
    )


def rebuild_dw(raw_base: Path, out_dw: Path) -> dict[str, int]:
    out_dw.parent.mkdir(parents=True, exist_ok=True)
    if out_dw.exists():
        out_dw.unlink()

    con = duckdb.connect()
    con.execute("LOAD sqlite")
    con.execute("PRAGMA threads=4")

    logs_union = _sql_union_logs(raw_base)
    con.execute(
        f"""
        CREATE TEMP TABLE valid_logs AS
        WITH logs AS (
          {logs_union}
        ),
        norm AS (
          SELECT
            REGEXP_REPLACE(TRIM(cadastro), '\\\\.0$', '') AS cadastro,
            NULLIF(TRIM(nome), '') AS nome,
            COALESCE(
              TRY_STRPTIME(TRIM(data_raw), '%d/%m/%Y')::DATE,
              TRY_STRPTIME(TRIM(data_raw), '%m/%d/%Y')::DATE,
              TRY_CAST(TRIM(data_raw) AS DATE)
            ) AS data,
            TRIM(planta_raw) AS planta,
            TRIM(tipo_raw) AS tipo,
            cargo_src,
            COALESCE(NULLIF(TRIM({REGISTRO_MANUAL_COL}), ''), 'Não') AS registro_manual
          FROM logs
        )
        SELECT * FROM norm
        WHERE cadastro IS NOT NULL
          AND cadastro <> ''
          AND data IS NOT NULL
          AND planta IS NOT NULL
          AND planta <> ''
          AND planta <> '999'
          AND tipo IS NOT NULL
          AND tipo <> ''
          AND tipo <> '0';
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE presenca_dia AS
        SELECT DISTINCT cadastro, data
        FROM valid_logs;
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE agg_registros_semanais_tmp AS
        SELECT
          cadastro,
          CAST(STRFTIME(data, '%G') AS INTEGER) AS ano,
          CAST(STRFTIME(data, '%V') AS INTEGER) AS semana_por_ano,
          CAST(DATE_TRUNC('week', data) AS DATE) AS data,
          COUNT(*)::INTEGER AS contagem_presenca
        FROM presenca_dia
        GROUP BY cadastro, ano, semana_por_ano, data;
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE diarios_unico_tmp AS
        SELECT
          cadastro,
          MIN(planta) AS planta,
          data,
          MAX(CASE WHEN registro_manual = 'Sim' THEN 'Sim' ELSE 'Não' END) AS registro_manual
        FROM valid_logs
        GROUP BY cadastro, data;
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE dim_logs_tmp AS
        SELECT
          cadastro,
          COALESCE(ARG_MAX(nome, data), '') AS nome,
          COALESCE(ARG_MAX(cargo_src, data), '') AS cargo
        FROM valid_logs
        GROUP BY cadastro;
        """
    )

    hr_dim = _load_hr_dimension(raw_base)
    con.register("hr_dim_df", hr_dim)
    con.execute(
        """
        CREATE TEMP TABLE hr_dim_tmp AS
        SELECT
          CAST(cadastro AS VARCHAR) AS cadastro,
          COALESCE(CAST(nome AS VARCHAR), '') AS nome,
          COALESCE(CAST(cargo AS VARCHAR), '') AS cargo,
          COALESCE(CAST(cargo_especifico AS VARCHAR), '') AS cargo_especifico,
          COALESCE(CAST(area AS VARCHAR), '') AS area,
          COALESCE(CAST(departamento AS VARCHAR), '') AS departamento,
          COALESCE(CAST(heranca AS VARCHAR), '') AS heranca,
          COALESCE(CAST(desligado AS VARCHAR), 'Não') AS desligado
        FROM hr_dim_df;
        """
    )

    dim_logs = con.execute(
        """
        SELECT cadastro, nome, cargo
        FROM dim_logs_tmp
        """
    ).fetchdf()
    dim_logs["cargo_especifico"] = dim_logs["cargo"]
    dim_logs["area"] = ""
    dim_logs["departamento"] = ""
    dim_logs["heranca"] = ""
    dim_logs["desligado"] = "Não"

    if hr_dim.empty:
        dim_final = dim_logs.copy()
    else:
        base = dim_logs.set_index("cadastro")
        hr = hr_dim.rename(
            columns={
                "nome": "nome",
                "cargo": "cargo",
                "cargo_especifico": "cargo_especifico",
                "area": "area",
                "departamento": "departamento",
                "heranca": "heranca",
                "desligado": "desligado",
            }
        ).set_index("cadastro")
        dim_final = hr.combine_first(base).reset_index()

    dim_final["cargo"] = dim_final["cargo"].astype("string").fillna("")
    dim_final["cargo_especifico"] = dim_final["cargo_especifico"].astype("string").fillna("")
    dim_final["cargo"] = normalize_cargo_series(dim_final["cargo"])
    empty_mask = dim_final["cargo"].astype(str).str.strip().eq("")
    dim_final.loc[empty_mask, "cargo"] = normalize_cargo_series(
        dim_final.loc[empty_mask, "cargo_especifico"]
    )
    dim_final["cargo"] = dim_final["cargo"].astype(str)
    dim_final["desligado"] = (
        dim_final["desligado"]
        .astype("string")
        .str.strip()
        .str.lower()
        .map(lambda x: "Sim" if x in {"1", "true", "sim", "yes", "y", "t"} else "Não")
    )
    dim_final = dim_final[
        [
            "cadastro",
            "nome",
            "cargo",
            "cargo_especifico",
            "area",
            "departamento",
            "heranca",
            "desligado",
        ]
    ].drop_duplicates(subset=["cadastro"], keep="first")

    con.register("dim_final_df", dim_final)
    con.execute(
        """
        CREATE TEMP TABLE dim_colaborador_tmp AS
        SELECT
          CAST(cadastro AS VARCHAR) AS cadastro,
          COALESCE(CAST(nome AS VARCHAR), '') AS nome,
          COALESCE(CAST(cargo AS VARCHAR), '') AS cargo,
          COALESCE(CAST(cargo_especifico AS VARCHAR), '') AS cargo_especifico,
          COALESCE(CAST(area AS VARCHAR), '') AS area,
          COALESCE(CAST(departamento AS VARCHAR), '') AS departamento,
          COALESCE(CAST(heranca AS VARCHAR), '') AS heranca,
          COALESCE(CAST(desligado AS VARCHAR), 'Não') AS desligado
        FROM dim_final_df
        WHERE cadastro IS NOT NULL AND TRIM(cadastro) <> '';
        """
    )

    gptw_path = raw_base / "GPTW" / "GPTW.parquet"
    mov_path = raw_base / "Movimentacoes" / "Movimentacoes.parquet"
    if gptw_path.exists():
        gptw_df = pd.read_parquet(gptw_path)
    else:
        gptw_df = pd.DataFrame(columns=["Área", "GPTW"])
    if mov_path.exists():
        mov_df = pd.read_parquet(mov_path)
    else:
        mov_df = pd.DataFrame(
            columns=[
                "Cadastro",
                "Nome",
                "Abreviação UO antiga",
                "Desc. UO antiga",
                "Abreviação UO",
                "Desc. UO",
                "Data de alteração",
            ]
        )
    head_df = pd.DataFrame(columns=["Área", "Heranca", "2023 hc", "2024 hc", "2025 hc"])

    con.register("gptw_df", gptw_df)
    con.register("mov_df", mov_df)
    con.register("head_df", head_df)

    out_sqlite = out_dw.resolve().as_posix()
    con.execute(f"ATTACH '{out_sqlite}' AS out_db (TYPE SQLITE)")
    con.execute(
        """
        CREATE TABLE out_db.dim_colaborador AS
        SELECT * FROM dim_colaborador_tmp;
        """
    )
    con.execute(
        """
        CREATE TABLE out_db.agg_registros_semanais AS
        SELECT * FROM agg_registros_semanais_tmp;
        """
    )
    con.execute(
        """
        CREATE TABLE out_db.diarios_unico AS
        SELECT * FROM diarios_unico_tmp;
        """
    )
    con.execute(
        """
        CREATE TABLE out_db.evento_acesso_flat AS
        SELECT
          CAST(NULL AS TEXT) AS cadastro,
          CAST(NULL AS DATE) AS data,
          CAST(NULL AS TEXT) AS hora,
          CAST(NULL AS TEXT) AS ts,
          CAST(NULL AS TEXT) AS filial,
          CAST(NULL AS TEXT) AS planta,
          CAST(NULL AS TEXT) AS coletor,
          CAST(NULL AS TEXT) AS descricao_coletor,
          CAST(NULL AS TEXT) AS dir,
          CAST(NULL AS TEXT) AS tipo,
          CAST(NULL AS TEXT) AS acesso,
          CAST(NULL AS TEXT) AS uso_acesso,
          CAST(NULL AS TEXT) AS registro_manual
        WHERE 1=0;
        """
    )
    con.execute("CREATE TABLE out_db.gptw AS SELECT * FROM gptw_df;")
    con.execute("CREATE TABLE out_db.movimentacoes AS SELECT * FROM mov_df;")
    con.execute("CREATE TABLE out_db.headcount AS SELECT * FROM head_df;")

    _create_sqlite_contract_views(con)
    con.execute("DETACH out_db")
    con.close()

    with sqlite3.connect(out_dw) as conn:
        stats = {
            "dim_total": int(
                pd.read_sql_query("SELECT COUNT(*) n FROM dim_colaborador", conn).iloc[0, 0]
            ),
            "dim_terceiros": int(
                pd.read_sql_query(
                    "SELECT COUNT(*) n FROM dim_colaborador WHERE cargo='T'", conn
                ).iloc[0, 0]
            ),
            "semana_total": int(
                pd.read_sql_query("SELECT COUNT(*) n FROM agg_registros_semanais", conn).iloc[0, 0]
            ),
            "semana_terceiros": int(
                pd.read_sql_query(
                    "SELECT COUNT(*) n FROM vw_semana_enriquecida WHERE \"Cargo\"='T'",
                    conn,
                ).iloc[0, 0]
            ),
        }
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstrói DW SQLite a partir dos parquets.")
    parser.add_argument("--raw-base", type=Path, default=DEFAULT_RAW_BASE)
    parser.add_argument("--out-dw", type=Path, default=DEFAULT_OUT_DW)
    args = parser.parse_args()

    stats = rebuild_dw(args.raw_base, args.out_dw)
    for k, v in stats.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
