"""repo_global.py

Módulo do dashboard de dados (Volkswagen do Brasil).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations


import pandas as pd

from .config import (
    configure_runtime,
    ALMOCO_PARQUET,
    AFASTADOS_PARQUET,
    DATAS_PARQUET,
    DEPARTAMENTOS_PARQUET,
    GPTW_PARQUET,
    SEMANA_PARQUET,
)

# Configura ambiente global (locale, pandas etc.)
configure_runtime()

# Carregamento principal -------------------------------------------------------
df_departamentos = pd.read_parquet(DEPARTAMENTOS_PARQUET)
df_datas = pd.read_parquet(DATAS_PARQUET)
df_semana_merged = pd.read_parquet(SEMANA_PARQUET)
df_afastados = pd.read_parquet(AFASTADOS_PARQUET)
df_gptw = pd.read_parquet(GPTW_PARQUET)
df_almoco = pd.read_parquet(ALMOCO_PARQUET)


def _normalize_cadastro(df: pd.DataFrame) -> pd.DataFrame:
    if "Cadastro" in df.columns:
        df["Cadastro"] = df["Cadastro"].astype(str)
    return df


for _df in (
    df_semana_merged,
    df_datas,
    df_afastados,
    df_departamentos,
    df_gptw,
    df_almoco,
):
    _normalize_cadastro(_df)


if "Data" in df_semana_merged.columns:
    df_semana_merged["Data"] = pd.to_datetime(df_semana_merged["Data"], errors="coerce")
if "Data" in df_datas.columns:
    df_datas["Data"] = pd.to_datetime(df_datas["Data"], errors="coerce")


if "Data" in df_semana_merged.columns and "Dia Semana" not in df_semana_merged.columns:
    dias = {
        0: "Segunda",
        1: "Terça",
        2: "Quarta",
        3: "Quinta",
        4: "Sexta",
        5: "Sábado",
        6: "Domingo",
    }
    df_semana_merged["Dia Semana"] = df_semana_merged["Data"].dt.weekday.map(dias)


if "Data" in df_datas.columns:
    df_datas["Data"] = pd.to_datetime(df_datas["Data"], errors="coerce")


if "Cargo" not in df_semana_merged.columns and "Cargo Especifico" in df_semana_merged.columns:
    df_semana_merged = df_semana_merged.assign(Cargo=df_semana_merged["Cargo Especifico"])


if "Dia Semana" in df_semana_merged.columns:
    df_count_por_semana = (
        df_semana_merged.groupby(
            [
                "Cadastro",
                "Nome",
                "Area",
                "Departamento",
                "Heranca",
                "Cargo Especifico",
                "Afastado",
            ]
        )["Dia Semana"]
        .value_counts()
        .reset_index()
    )
    df_count_por_semana.columns = [
        "Cadastro",
        "Nome",
        "Area",
        "Departamento",
        "Heranca",
        "Cargo Especifico",
        "Afastado",
        "Dia Semana",
        "Contagem Presença",
    ]
else:
    df_count_por_semana = pd.DataFrame(
        columns=[
            "Cadastro",
            "Nome",
            "Area",
            "Departamento",
            "Heranca",
            "Cargo Especifico",
            "Afastado",
            "Dia Semana",
            "Contagem Presença",
        ]
    )


her = (
    df_semana_merged[["Area", "Departamento", "Heranca"]]
    .drop_duplicates()
    .sort_values("Area")
)

dropdown_options = [{"label": "Geral (todas as áreas)", "value": "GERAL"}] + [
    {"label": f"{row['Area']} {row['Departamento']}", "value": row["Area"]}
    for _, row in her.iterrows()
]