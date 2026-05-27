"""Corrige terceiros no DW SQLite sem rebuild completo.

Este utilitario lê os parquets de terceiros, calcula presença semanal e aplica
upsert nas tabelas `dim_colaborador` e `agg_registros_semanais`.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

DEFAULT_DW_PATH = Path("project/database/dw_ronda.sqlite")
DEFAULT_TERCEIROS_DIR = Path("Base de Dados Original/parquet/Terceiros")
INSERT_BATCH = 50_000


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
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _resolve_col(columns: list[str], field: str) -> str:
    pairs = [(col, _norm_col_name(col)) for col in columns]
    if field == "cadastro":
        for col, key in pairs:
            if key in {"cadastro", "chapa"}:
                return col
    elif field == "nome":
        for col, key in pairs:
            if key in {"nome", "nome_colaborador"}:
                return col
    elif field == "data":
        for col, key in pairs:
            if key in {"data", "data_acesso"}:
                return col
    elif field == "hora":
        for col, key in pairs:
            if key in {"hora", "hora_acesso"}:
                return col
    elif field == "tipo":
        for col, key in pairs:
            if key in {"tipo", "tipo_acesso"}:
                return col
    elif field == "planta":
        for col, key in pairs:
            if key in {"planta", "codigo_planta"}:
                return col
    raise KeyError(f"Coluna obrigatoria nao encontrada para '{field}'.")


def _normalizar_cadastro(series: pd.Series) -> pd.Series:
    out = series.astype("string").str.strip()
    out = out.str.replace(r"\.0$", "", regex=True)
    return out.where(~out.fillna("").isin({"", "nan", "none", "null"}), pd.NA)


def _parse_data(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    slash_mask = text.str.match(r"^\d{1,2}/\d{1,2}/\d{4}$", na=False)
    data_br = pd.to_datetime(text.where(slash_mask), format="%d/%m/%Y", errors="coerce")
    data_us = pd.to_datetime(text.where(slash_mask), format="%m/%d/%Y", errors="coerce")
    data_other = pd.to_datetime(text.where(~slash_mask), errors="coerce")
    return data_other.fillna(data_br.fillna(data_us)).dt.normalize()


def _parse_hora_iso(series: pd.Series) -> pd.Series:
    hora_str = series.astype("string").str.strip()

    hora_extr = hora_str.str.extract(r"(\d{1,2}:\d{2}(?::\d{2})?)", expand=False)
    hora_clean = hora_extr.where(
        hora_extr.str.contains(r":\d{2}:\d{2}$", regex=True, na=False),
        hora_extr + ":00",
    )
    hora_clean = hora_clean.str.replace(r"^(\d):", r"0\1:", regex=True)
    hora_dt = pd.to_datetime(hora_clean, format="%H:%M:%S", errors="coerce")
    hora_iso = pd.Series(hora_dt.dt.strftime("%H:%M:%S"), dtype="string")

    hora_num = pd.to_numeric(hora_str.str.replace(",", ".", regex=False), errors="coerce")
    hora_num_td = pd.to_timedelta(hora_num, unit="m")
    hora_num_dt = pd.Timestamp("1900-01-01") + hora_num_td
    hora_num_iso = pd.Series(hora_num_dt.dt.strftime("%H:%M:%S"), dtype="string")

    return hora_iso.where(~hora_iso.fillna("").eq(""), hora_num_iso)


def _prepare_file(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_parquet(path)
    cols = list(raw.columns)
    col_cad = _resolve_col(cols, "cadastro")
    col_nome = _resolve_col(cols, "nome")
    col_data = _resolve_col(cols, "data")
    col_hora = _resolve_col(cols, "hora")
    col_tipo = _resolve_col(cols, "tipo")
    col_planta = _resolve_col(cols, "planta")

    work = pd.DataFrame(
        {
            "cadastro": _normalizar_cadastro(raw[col_cad]),
            "nome": raw[col_nome].astype("string").str.strip(),
            "data": _parse_data(raw[col_data]),
            "hora_iso": _parse_hora_iso(raw[col_hora]),
            "tipo": raw[col_tipo].astype("string").str.strip(),
            "planta": raw[col_planta].astype("string").str.strip(),
        }
    )
    work["hora_td"] = pd.to_timedelta(work["hora_iso"], errors="coerce")
    work["ts"] = work["data"] + work["hora_td"]

    valid = (
        work["cadastro"].notna()
        & work["data"].notna()
        & work["planta"].notna()
        & ~work["planta"].eq("")
        & ~work["planta"].eq("999")
        & work["tipo"].notna()
        & ~work["tipo"].eq("")
        & ~work["tipo"].eq("0")
    )
    valid_work = work.loc[valid].copy()
    if valid_work.empty:
        return (
            pd.DataFrame(columns=["cadastro", "nome", "ts"]),
            pd.DataFrame(
                columns=["cadastro", "ano", "semana_por_ano", "data", "contagem_presenca"]
            ),
        )

    dim_part = (
        valid_work.assign(ts_ord=valid_work["ts"].fillna(valid_work["data"]))
        .sort_values(["cadastro", "ts_ord"])
        .groupby("cadastro", as_index=False)
        .tail(1)[["cadastro", "nome", "ts_ord"]]
        .rename(columns={"ts_ord": "ts"})
    )

    unique_days = valid_work[["cadastro", "data"]].drop_duplicates().copy()
    iso = unique_days["data"].dt.isocalendar()
    unique_days["ano"] = iso["year"].astype(int)
    unique_days["semana_por_ano"] = iso["week"].astype(int)
    week_start = unique_days["data"] - pd.to_timedelta(unique_days["data"].dt.weekday, unit="D")
    unique_days["data_semana"] = week_start.dt.strftime("%Y-%m-%d")

    weekly_part = (
        unique_days.groupby(["cadastro", "ano", "semana_por_ano", "data_semana"], as_index=False)
        .size()
        .rename(columns={"size": "contagem_presenca", "data_semana": "data"})
    )
    weekly_part["contagem_presenca"] = weekly_part["contagem_presenca"].astype(int)
    return dim_part, weekly_part


def _consolidar_dim(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame(columns=["cadastro", "nome", "ts"])
    dim = pd.concat(parts, ignore_index=True)
    dim = (
        dim.sort_values(["cadastro", "ts"])
        .groupby("cadastro", as_index=False)
        .tail(1)[["cadastro", "nome", "ts"]]
    )
    dim["nome"] = dim["nome"].astype("string").fillna("").astype(str)
    return dim.reset_index(drop=True)


def _consolidar_weekly(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame(
            columns=["cadastro", "ano", "semana_por_ano", "data", "contagem_presenca"]
        )
    weekly = pd.concat(parts, ignore_index=True)
    weekly = (
        weekly.groupby(["cadastro", "ano", "semana_por_ano"], as_index=False)
        .agg({"data": "min", "contagem_presenca": "sum"})
        .reset_index(drop=True)
    )
    weekly["contagem_presenca"] = weekly["contagem_presenca"].astype(int)
    return weekly


def _executemany_batched(
    conn: sqlite3.Connection,
    sql: str,
    rows: list[tuple],
    batch_size: int = INSERT_BATCH,
) -> None:
    for start in range(0, len(rows), batch_size):
        end = min(start + batch_size, len(rows))
        conn.executemany(sql, rows[start:end])


def aplicar_fix(dw_path: Path, terceiros_dir: Path) -> dict[str, int]:
    files = sorted(terceiros_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"Nenhum parquet encontrado em: {terceiros_dir}")

    dim_parts: list[pd.DataFrame] = []
    weekly_parts: list[pd.DataFrame] = []
    for file in files:
        dim_part, weekly_part = _prepare_file(file)
        if not dim_part.empty:
            dim_parts.append(dim_part)
        if not weekly_part.empty:
            weekly_parts.append(weekly_part)

    dim = _consolidar_dim(dim_parts)
    weekly = _consolidar_weekly(weekly_parts)
    if dim.empty or weekly.empty:
        raise RuntimeError("Nao foi possivel gerar dados validos de terceiros.")

    conn = sqlite3.connect(dw_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("BEGIN;")

        dim_sql = """
        INSERT INTO dim_colaborador(
            cadastro,nome,cargo,cargo_especifico,area,departamento,heranca,desligado
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(cadastro) DO UPDATE SET
            nome = excluded.nome,
            cargo = 'T',
            cargo_especifico = CASE
                WHEN dim_colaborador.cargo_especifico IS NULL
                     OR trim(dim_colaborador.cargo_especifico) = ''
                THEN excluded.cargo_especifico
                ELSE dim_colaborador.cargo_especifico
            END;
        """
        dim_rows = [
            (row.cadastro, row.nome, "T", "TERCEIRO", "", "", "", "Não")
            for row in dim.itertuples(index=False)
        ]
        _executemany_batched(conn, dim_sql, dim_rows)

        weekly_sql = """
        INSERT INTO agg_registros_semanais(
            cadastro,ano,semana_por_ano,data,contagem_presenca
        ) VALUES (?,?,?,?,?)
        ON CONFLICT(cadastro,ano,semana_por_ano) DO UPDATE SET
            data = excluded.data,
            contagem_presenca = excluded.contagem_presenca;
        """
        weekly_rows = [
            (
                row.cadastro,
                int(row.ano),
                int(row.semana_por_ano),
                row.data,
                int(row.contagem_presenca),
            )
            for row in weekly.itertuples(index=False)
        ]
        _executemany_batched(conn, weekly_sql, weekly_rows)
        conn.commit()

        stats = {
            "dim_terceiros": int(
                pd.read_sql_query(
                    "SELECT COUNT(*) n FROM dim_colaborador WHERE cargo='T'", conn
                ).iloc[0, 0]
            ),
            "semana_terceiros": int(
                pd.read_sql_query(
                    "SELECT COUNT(*) n FROM agg_registros_semanais WHERE cadastro IN "
                    "(SELECT cadastro FROM dim_colaborador WHERE cargo='T')",
                    conn,
                ).iloc[0, 0]
            ),
            "vw_semana_terceiros": int(
                pd.read_sql_query(
                    "SELECT COUNT(*) n FROM vw_semana_enriquecida WHERE \"Cargo\"='T'",
                    conn,
                ).iloc[0, 0]
            ),
            "vw_colab_terceiros": int(
                pd.read_sql_query(
                    "SELECT COUNT(*) n FROM vw_colaboradores WHERE \"Cargo\"='T'", conn
                ).iloc[0, 0]
            ),
        }
        return stats
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill de terceiros no DW SQLite.")
    parser.add_argument(
        "--dw-path",
        type=Path,
        default=DEFAULT_DW_PATH,
        help="Caminho do DW SQLite (default: project/database/dw_ronda.sqlite).",
    )
    parser.add_argument(
        "--terceiros-dir",
        type=Path,
        default=DEFAULT_TERCEIROS_DIR,
        help="Diretorio dos parquets de terceiros.",
    )
    args = parser.parse_args()

    stats = aplicar_fix(args.dw_path, args.terceiros_dir)
    for key, value in stats.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
