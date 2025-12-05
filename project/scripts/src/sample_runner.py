"""sample_runner.py

Interface de linha de comando para reproduzir o resultado do notebook
"Projeto unificado" usando a arquitetura MVC já existente.

Objetivo: gerar o mesmo recorte de presença/almoco (área/subárea/período)
sem depender do notebook, reaproveitando os módulos de domínio/serviço.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from .core.config import configure_runtime, validate_data_files
from .core import repo_global as repo
from .domain.builders import (
    build_dataframe_almoco_area,
    build_dataframe_diario_area,
)
from .domain.periods import periodo_limites


# Aplica runtime e valida arquivos antes de qualquer operação.
configure_runtime()
validate_data_files()


def describe_frame(df: pd.DataFrame, titulo: str, max_rows: int = 5) -> None:
    """Exibe estatísticas rápidas de um DataFrame (head limitado).

    Args:
        df: DataFrame a ser inspecionado.
        titulo: rótulo exibido no print.
        max_rows: número de linhas a exibir na amostra.
    """
    print(f"[{titulo}] linhas={len(df)} colunas={list(df.columns)}")
    print(df.head(max_rows))


def recorte_presenca(
    *,
    area: str | None = "GERAL",
    subarea: str | None = None,
    periodo_idx: tuple[int, int] | None = None,
    df_datas: pd.DataFrame | None = None,
    df_departamentos: pd.DataFrame | None = None,
    df_almoco: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Gera recortes de presença e almoço por área/subárea.

    Args:
        area: slug de área (ou "GERAL" para todas).
        subarea: subárea específica opcional.
        periodo_idx: tupla de índices do slider (ex.: (0, 5)) para limitar datas.
        df_datas/df_departamentos/df_almoco: dataframes opcionais para injeção.
    Returns:
        dict com DataFrames 'presenca' e 'almoco'.
    """
    dt_ini = dt_fim = None
    if periodo_idx is not None:
        dt_ini, dt_fim = periodo_limites(periodo_idx)

    diario = build_dataframe_diario_area(
        area=area,
        subarea=subarea,
        her_df=repo.her,
        df_datas_local=df_datas if df_datas is not None else repo.df_datas,
        df_dept=df_departamentos if df_departamentos is not None else repo.df_departamentos,
        dt_ini=dt_ini,
        dt_fim=dt_fim,
    )

    almoco_df = build_dataframe_almoco_area(
        area=area,
        subarea=subarea,
        her_df=repo.her,
        df_almoco_local=df_almoco if df_almoco is not None else repo.df_almoco,
        df_dept=df_departamentos if df_departamentos is not None else repo.df_departamentos,
        dt_ini=dt_ini,
        dt_fim=dt_fim,
    )

    return {"presenca": diario, "almoco": almoco_df}


def run_sample(
    area: str | None = "GERAL",
    subarea: str | None = None,
    periodo_idx: tuple[int, int] | None = None,
    max_rows: int = 5,
) -> None:
    """Executa o fluxo de exemplo do notebook e imprime amostras.

    Args:
        area: slug de área (ou "GERAL" para todas).
        subarea: subárea específica opcional.
        periodo_idx: tupla de índices do slider (ex.: (0, 5)) para limitar datas.
        max_rows: linhas a exibir por recorte.
    """
    recortes = recorte_presenca(
        area=area,
        subarea=subarea,
        periodo_idx=periodo_idx,
    )
    describe_frame(recortes["presenca"], "Presença (diário)", max_rows=max_rows)
    describe_frame(recortes["almoco"], "Almoço (janela 11h-14h)", max_rows=max_rows)


if __name__ == "__main__":
    # Execução simples espelhando o exemplo do notebook unificado.
    run_sample(area="GERAL", subarea=None, periodo_idx=None, max_rows=5)
