"""Regras de negócio de presença/almoco."""
from __future__ import annotations

import pandas as pd

from ...core import repo_global as repo
from ...domain.builders import (
    build_dataframe_almoco_area,
    build_dataframe_diario_area,
)
from ...domain.periods import periodo_limites


def recorte_presenca(
    *,
    area: str | None = "GERAL",
    subarea: str | None = None,
    periodo_idx: tuple[int, int] | None = None,
    data: dict | None = None,
) -> dict[str, pd.DataFrame]:
    """Gera recortes de presença e almoço por área/subárea."""
    dt_ini = dt_fim = None
    if periodo_idx is not None:
        dt_ini, dt_fim = periodo_limites(periodo_idx)

    df_datas = (data or {}).get("df_datas", repo.df_datas)
    df_departamentos = (data or {}).get("df_departamentos", repo.df_departamentos)
    df_almoco = (data or {}).get("df_almoco", repo.df_almoco)

    diario = build_dataframe_diario_area(
        area=area,
        subarea=subarea,
        her_df=repo.her,
        df_datas_local=df_datas,
        df_dept=df_departamentos,
        dt_ini=dt_ini,
        dt_fim=dt_fim,
    )

    almoco_df = build_dataframe_almoco_area(
        area=area,
        subarea=subarea,
        her_df=repo.her,
        df_almoco_local=df_almoco,
        df_dept=df_departamentos,
        dt_ini=dt_ini,
        dt_fim=dt_fim,
    )

    return {"presenca": diario, "almoco": almoco_df}
