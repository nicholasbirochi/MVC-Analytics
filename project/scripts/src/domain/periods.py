"""periods.py

Utilitários de datas/intervalos (ISO week, mês, bimestres, etc.).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from ..core.config import FERIAS_COLETIVAS, SETTINGS


# ----- Linha do tempo global --------------------------------------------------
LT_INICIO_ABS = dt.date(2024, 1, 1)


def _max_data_dw() -> dt.date | None:
    """Usa a última presença real em mês fechado para evitar dados parciais/futuros."""
    dw_path_config = getattr(SETTINGS, "dw_path", None)
    if not dw_path_config:
        return None

    dw_path = Path(dw_path_config)
    if not dw_path.exists():
        return None

    hoje = pd.Timestamp(dt.date.today()).normalize()
    primeiro_dia_mes_atual = hoje.replace(day=1)
    limite_mes_fechado = (primeiro_dia_mes_atual - pd.Timedelta(days=1)).date()

    consultas_principais = (
        ("agg_diarios_unico", "data"),
        ('vw_df_diarios_unico', '"Data"'),
    )
    consultas_fallback = (
        ('vw_df_diarios', '"Data"'),
        ('evento_acesso_flat', 'data'),
    )

    def executar(
        conn: sqlite3.Connection,
        consultas: Iterable[tuple[str, str]],
    ) -> dt.date | None:
        datas: list[dt.date] = []
        for tabela, coluna in consultas:
            try:
                row = conn.execute(
                    f"SELECT MAX({coluna}) FROM {tabela} WHERE {coluna} <= ?",
                    (limite_mes_fechado.strftime("%Y-%m-%d"),),
                ).fetchone()
            except sqlite3.Error:
                continue
            if not row or row[0] is None:
                continue
            valor = pd.to_datetime(row[0], errors="coerce")
            if not pd.isna(valor):
                datas.append(pd.Timestamp(valor).date())
        return max(datas) if datas else None

    try:
        with sqlite3.connect(str(dw_path)) as conn:
            return executar(conn, consultas_principais) or executar(conn, consultas_fallback)
    except sqlite3.Error:
        return None


LT_FIM_ABS = _max_data_dw() or dt.date.today()
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


def listar_segundas_periodo(dt_ini, dt_fim) -> list[pd.Timestamp]:
    if dt_ini is None or dt_fim is None:
        return []
    try:
        inicio = pd.Timestamp(dt_ini).normalize()
        fim = pd.Timestamp(dt_fim).normalize()
    except Exception:
        return []
    if pd.isna(inicio) or pd.isna(fim):
        return []
    if inicio > fim:
        inicio, fim = fim, inicio

    dias_ate_segunda = (7 - inicio.weekday()) % 7
    primeira_segunda = inicio + pd.Timedelta(days=dias_ate_segunda)
    if primeira_segunda > fim:
        return []

    segundas = pd.date_range(primeira_segunda, fim, freq="7D")
    return [
        pd.Timestamp(dia)
        for dia in segundas
        if not esta_em_ferias(dia)
        and getattr(dia.isocalendar(), "week", dia.isocalendar()[1]) != 1
    ]


def periodo_limites(indices: Iterable[int]) -> tuple[pd.Timestamp, pd.Timestamp]:
    i0, i1 = indices
    i0 = max(0, min(i0, len(LT_MONTHS) - 1))
    i1 = max(0, min(i1, len(LT_MONTHS) - 1))
    dt_ini = pd.to_datetime(LT_MONTHS[i0]).replace(day=1)
    dt_fim = min(pd.to_datetime(LT_MONTHS[i1]) + pd.offsets.MonthEnd(0), pd.Timestamp(LT_FIM_ABS))
    return dt_ini, dt_fim
