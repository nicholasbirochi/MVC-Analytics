"""Reduz terceiros para 25% no DW sem afetar E/M/H.

Estratégia:
- Seleção determinística de 1/4 dos cadastros com cargo `T`.
- Remove os demais `T` de `dim_colaborador`, `agg_registros_semanais` e `diarios_unico`.
- Mantém intactos os registros de `E`, `M` e `H`.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DW_PATH = Path("project/database/dw_ronda.sqlite")


def _counts_dim(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT cargo, COUNT(*) AS n FROM dim_colaborador GROUP BY cargo ORDER BY cargo",
        conn,
    )


def _counts_semana(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT d.cargo, COUNT(*) AS n
        FROM agg_registros_semanais s
        JOIN dim_colaborador d ON d.cadastro = s.cadastro
        GROUP BY d.cargo
        ORDER BY d.cargo
        """,
        conn,
    )


def apply_reduction(dw_path: Path) -> dict[str, object]:
    conn = sqlite3.connect(dw_path)
    try:
        before_dim = _counts_dim(conn)
        before_sem = _counts_semana(conn)

        conn.execute("BEGIN;")
        conn.execute("DROP TABLE IF EXISTS _tmp_keep_terceiros;")
        conn.execute(
            """
            CREATE TEMP TABLE _tmp_keep_terceiros AS
            SELECT cadastro
            FROM (
              SELECT
                cadastro,
                ROW_NUMBER() OVER (ORDER BY cadastro) AS rn
              FROM dim_colaborador
              WHERE cargo = 'T'
            ) t
            WHERE (rn % 4) = 1;
            """
        )

        conn.execute(
            """
            DELETE FROM agg_registros_semanais
            WHERE cadastro IN (
              SELECT cadastro
              FROM dim_colaborador
              WHERE cargo = 'T'
                AND cadastro NOT IN (SELECT cadastro FROM _tmp_keep_terceiros)
            );
            """
        )
        conn.execute(
            """
            DELETE FROM diarios_unico
            WHERE cadastro IN (
              SELECT cadastro
              FROM dim_colaborador
              WHERE cargo = 'T'
                AND cadastro NOT IN (SELECT cadastro FROM _tmp_keep_terceiros)
            );
            """
        )
        conn.execute(
            """
            DELETE FROM dim_colaborador
            WHERE cargo = 'T'
              AND cadastro NOT IN (SELECT cadastro FROM _tmp_keep_terceiros);
            """
        )
        conn.execute("DROP TABLE IF EXISTS _tmp_keep_terceiros;")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_dim_cadastro ON dim_colaborador(cadastro);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_dim_cargo ON dim_colaborador(cargo);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_dim_area ON dim_colaborador(area);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_dim_heranca ON dim_colaborador(heranca);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_sem_cadastro ON agg_registros_semanais(cadastro);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_sem_data ON agg_registros_semanais(data);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_sem_ano_sem ON agg_registros_semanais(ano, semana_por_ano, cadastro);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_diario_cad_data ON diarios_unico(cadastro, data);"
        )
        conn.execute("ANALYZE;")
        conn.commit()

        after_dim = _counts_dim(conn)
        after_sem = _counts_semana(conn)

        def _as_dict(df: pd.DataFrame) -> dict[str, int]:
            if df.empty:
                return {}
            return {str(r["cargo"]): int(r["n"]) for _, r in df.iterrows()}

        return {
            "before_dim": _as_dict(before_dim),
            "after_dim": _as_dict(after_dim),
            "before_semana": _as_dict(before_sem),
            "after_semana": _as_dict(after_sem),
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reduz terceiros para 25% no DW.")
    parser.add_argument("--dw-path", type=Path, default=DEFAULT_DW_PATH)
    args = parser.parse_args()

    result = apply_reduction(args.dw_path)
    print(result)


if __name__ == "__main__":
    main()
