"""Equivalencia entre notebook canônico e pipeline MVC.

Este teste valida as consultas-chave de relacionamento (geral e almoço)
comparando o resultado do pipeline MVC com a mesma SQL de referência
presente no notebook `Códigos Extras/Projeto unificado.ipynb`.
"""
from __future__ import annotations

import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from project.scripts.src.core.config import get_settings
from project.scripts.src.domain import pipeline
from project.scripts.src.domain.builders import (
    build_dataframe_almoco_area,
    build_dataframe_diario_area,
)


def _sample_area() -> str:
    df = pipeline.query_dw(
        'SELECT "Área" AS area FROM vw_colaboradores '
        'WHERE "Área" IS NOT NULL AND TRIM("Área") <> "" '
        'ORDER BY "Área" LIMIT 1;'
    )
    if df.empty:
        raise AssertionError("DW sem áreas disponíveis para validação.")
    return str(df.loc[0, "area"])


def _sample_period() -> tuple[pd.Timestamp, pd.Timestamp]:
    mm = pipeline.query_dw(
        'SELECT MIN("Data") AS dmin, MAX("Data") AS dmax FROM vw_df_diarios_unico;'
    )
    if mm.empty or pd.isna(mm.loc[0, "dmax"]):
        raise AssertionError("DW sem dados em vw_df_diarios_unico para validação.")
    dmax = pd.Timestamp(mm.loc[0, "dmax"]).normalize()
    dmin = (dmax - pd.DateOffset(days=14)).normalize()
    return dmin, dmax


def _manual_diario(area: str, subarea: str | None, dt_ini, dt_fim) -> pd.DataFrame:
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
        pd.Timestamp(dt_ini).strftime("%Y-%m-%d"),
        pd.Timestamp(dt_fim).strftime("%Y-%m-%d"),
        pd.Timestamp(dt_ini).strftime("%Y-%m-%d"),
        pd.Timestamp(dt_fim).strftime("%Y-%m-%d"),
    )
    out = pipeline.query_dw(sql, params=params, parse_dates=["Data"])
    if not out.empty:
        out["Cadastro"] = out["Cadastro"].astype(str)
        out["Contagem Presença"] = (
            pd.to_numeric(out["Contagem Presença"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
    return out


def _manual_almoco(area: str, subarea: str | None, dt_ini, dt_fim) -> pd.DataFrame:
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
    ORDER BY "Cadastro","Data";
    """
    params = params_area + (
        pd.Timestamp(dt_ini).strftime("%Y-%m-%d"),
        pd.Timestamp(dt_fim).strftime("%Y-%m-%d"),
    )
    out = pipeline.query_dw(sql, params=params, parse_dates=["Data"])
    if not out.empty:
        out["Cadastro"] = out["Cadastro"].astype(str)
        out["Contagem Presença"] = (
            pd.to_numeric(out["Contagem Presença"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
        out["Planta"] = out["Planta"].astype(str).fillna("")
    return out


class TestEquivalenceNotebookVsMvc(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = get_settings()
        if cls.settings.dw_path is None or not cls.settings.dw_path.exists():
            raise unittest.SkipTest("DW SQLite não disponível para validação.")

        cls.area = _sample_area()
        cls.dt_ini, cls.dt_fim = _sample_period()

    def test_pipeline_contract_keys(self) -> None:
        artifacts = pipeline.run_pipeline(self.settings)
        required_keys = {
            "df_df_ativos",
            "df_df_desligados",
            "df_semana_merged",
            "df_datas",
            "df_almoco",
            "df_df_gptw",
            "df_headcount",
            "df_count_por_semana",
            "her",
            "dropdown_options",
        }
        self.assertTrue(required_keys.issubset(set(artifacts.keys())))
        self.assertIn("Cadastro", artifacts["df_semana_merged"].columns)

    def test_diario_sql_equivalence(self) -> None:
        expected = _manual_diario(self.area, None, self.dt_ini, self.dt_fim)
        actual = pipeline.build_dataframe_diario_area_sql(
            area=self.area,
            subarea=None,
            dt_ini=self.dt_ini,
            dt_fim=self.dt_fim,
        )
        assert_frame_equal(expected, actual, check_dtype=False)

    def test_almoco_sql_equivalence(self) -> None:
        expected = _manual_almoco(self.area, None, self.dt_ini, self.dt_fim)
        actual = pipeline.build_dataframe_almoco_area_sql(
            area=self.area,
            subarea=None,
            dt_ini=self.dt_ini,
            dt_fim=self.dt_fim,
        )
        assert_frame_equal(expected, actual, check_dtype=False)

    def test_builders_delegate_to_canonical_sql(self) -> None:
        expected_diario = pipeline.build_dataframe_diario_area_sql(
            area=self.area,
            subarea=None,
            dt_ini=self.dt_ini,
            dt_fim=self.dt_fim,
        )
        actual_diario = build_dataframe_diario_area(
            area=self.area,
            subarea=None,
            dt_ini=self.dt_ini,
            dt_fim=self.dt_fim,
        )
        assert_frame_equal(expected_diario, actual_diario, check_dtype=False)

        expected_almoco = pipeline.build_dataframe_almoco_area_sql(
            area=self.area,
            subarea=None,
            dt_ini=self.dt_ini,
            dt_fim=self.dt_fim,
        )
        actual_almoco = build_dataframe_almoco_area(
            area=self.area,
            subarea=None,
            dt_ini=self.dt_ini,
            dt_fim=self.dt_fim,
        )
        assert_frame_equal(expected_almoco, actual_almoco, check_dtype=False)


if __name__ == "__main__":
    unittest.main()
