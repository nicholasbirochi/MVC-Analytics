"""periods.py

Utilitários de datas/intervalos (ISO week, mês, bimestres, etc.).

Projeto: Dashboard presencialidade — Empresa
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable, Sequence

import pandas as pd

from ..core.config import FERIAS_COLETIVAS


# ----- Linha do tempo global --------------------------------------------------
LT_INICIO_ABS = dt.date(2024, 1, 1)
LT_FIM_ABS = dt.date.today()
LT_MONTHS: Sequence[dt.date] = pd.date_range(LT_INICIO_ABS, LT_FIM_ABS, freq="MS").date


def lt_idx_of(year: int, month: int) -> int:
    for idx, date_item in enumerate(LT_MONTHS):
        if date_item.year == year and date_item.month == month:
            return idx
    raise ValueError(f"Mês {month}/{year} não encontrado em LT_MONTHS")


LT_C1_MIN = lt_idx_of(2024, 1)
LT_C1_MAX = lt_idx_of(2025, 4)
LT_C2_MIN = lt_idx_of(2025, 5)
LT_C2_MAX = len(LT_MONTHS) - 1


def _lt_label(date_item: dt.date) -> str:
    return pd.Timestamp(date_item).strftime("%b/%Y").lower()


LT_MARKS = {
    idx: (_lt_label(date_item) if date_item.month in {1, 4, 7, 10} else "")
    for idx, date_item in enumerate(LT_MONTHS)
}


def esta_em_ferias(data: pd.Timestamp | dt.datetime | dt.date) -> bool:
    if data is None or pd.isna(data):
        return False
    data_ts = pd.Timestamp(data)
    for inicio, fim in FERIAS_COLETIVAS:
        if pd.Timestamp(inicio) <= data_ts <= pd.Timestamp(fim):
            return True
    return False


def listar_segundas_validas(df_semana: pd.DataFrame) -> list[pd.Timestamp]:
    if "Data" not in df_semana.columns:
        return []
    periodos = df_semana["Data"].dt.to_period("W").dropna().unique()
    segundas = [
        p.start_time for p in periodos if p.start_time.weekday() == 0
    ]
    segundas = sorted(segundas)
    return [
        dia
        for dia in segundas
        if not esta_em_ferias(dia)
        and getattr(dia.isocalendar(), "week", dia.isocalendar()[1]) != 1
    ]


def periodo_limites(indices: Iterable[int]) -> tuple[pd.Timestamp, pd.Timestamp]:
    i0, i1 = indices
    i0 = max(0, min(i0, len(LT_MONTHS) - 1))
    i1 = max(0, min(i1, len(LT_MONTHS) - 1))
    dt_ini = pd.to_datetime(LT_MONTHS[i0]).replace(day=1)
    dt_fim = pd.to_datetime(LT_MONTHS[i1]) + pd.offsets.MonthEnd(0)
    return dt_ini, dt_fim


