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


def _month_start(data: dt.date) -> dt.date:
    return dt.date(data.year, data.month, 1)


def _add_months(data: dt.date, months: int) -> dt.date:
    month_zero = (data.year * 12) + (data.month - 1) + int(months)
    year, month_idx = divmod(month_zero, 12)
    return dt.date(year, month_idx + 1, 1)


def _ultimo_dia_mes_anterior(referencia: dt.date) -> dt.date:
    """Retorna o ultimo dia do mes anterior a referencia."""
    primeiro = dt.date(referencia.year, referencia.month, 1)
    return primeiro - dt.timedelta(days=1)


def _max_data_dw() -> dt.date | None:
    """Usa a última data presente no DW, limitada ao mes corrente.

    O DW pode conter dados futuros (carga de teste, eventos agendados). Para
    a analise faz sentido cortar no final do mes anterior ao mes corrente, ou
    no maximo no dia de hoje, evitando que o slider abra em meses futuros sem
    dados reais. Se o DW tiver MAX(data) menor que isso, mantemos o que veio
    do DW.
    """
    dw_path_config = getattr(SETTINGS, "dw_path", None)
    if not dw_path_config:
        return None

    dw_path = Path(dw_path_config)
    if not dw_path.exists():
        return None

    consultas_principais = (
        ("agg_diarios_unico", "data"),
        ('vw_df_diarios_unico', '"Data"'),
        ('vw_semana_enriquecida', '"Data"'),
    )
    consultas_fallback = (
        ('vw_df_diarios', '"Data"'),
        ('evento_acesso_flat', 'data'),
    )
    hoje = dt.date.today()
    teto = _ultimo_dia_mes_anterior(hoje)

    def executar(
        conn: sqlite3.Connection,
        consultas: Iterable[tuple[str, str]],
    ) -> dt.date | None:
        datas: list[dt.date] = []
        for tabela, coluna in consultas:
            try:
                row = conn.execute(
                    f"SELECT MAX({coluna}) FROM {tabela} WHERE {coluna} <= ?",
                    (teto.strftime("%Y-%m-%d"),),
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


def _ultimos_meses_presentes_dw(n: int = 3) -> tuple[dt.date, dt.date] | None:
    """Retorna o intervalo dos últimos N meses que existem na catraca."""
    dw_path_config = getattr(SETTINGS, "dw_path", None)
    if not dw_path_config:
        return None

    dw_path = Path(dw_path_config)
    if not dw_path.exists():
        return None

    consultas = (
        ('vw_df_diarios_unico', '"Data"'),
        ("agg_diarios_unico", "data"),
        ('evento_acesso_flat', 'data'),
        ('vw_df_diarios', '"Data"'),
    )
    n = max(1, int(n or 1))
    teto = _ultimo_dia_mes_anterior(dt.date.today())

    try:
        with sqlite3.connect(str(dw_path)) as conn:
            for tabela, coluna in consultas:
                try:
                    row = conn.execute(
                        f"SELECT MAX({coluna}) FROM {tabela} WHERE {coluna} <= ?",
                        (teto.strftime("%Y-%m-%d"),),
                    ).fetchone()
                except sqlite3.Error:
                    continue
                if not row or row[0] is None:
                    continue

                max_ts = pd.to_datetime(row[0], errors="coerce")
                if pd.isna(max_ts):
                    continue

                meses: list[tuple[dt.date, dt.date]] = []
                cursor = _month_start(pd.Timestamp(max_ts).date())
                for _ in range(120):
                    prox = _add_months(cursor, 1)
                    try:
                        mes_row = conn.execute(
                            f"""
                            SELECT MAX({coluna})
                            FROM {tabela}
                            WHERE {coluna} >= ? AND {coluna} < ?
                            """,
                            (cursor.strftime("%Y-%m-%d"), prox.strftime("%Y-%m-%d")),
                        ).fetchone()
                    except sqlite3.Error:
                        break

                    if mes_row and mes_row[0] is not None:
                        mes_max = pd.to_datetime(mes_row[0], errors="coerce")
                        if not pd.isna(mes_max):
                            meses.append((cursor, pd.Timestamp(mes_max).date()))
                            if len(meses) >= n:
                                break
                    cursor = _add_months(cursor, -1)

                if meses:
                    return meses[-1][0], meses[0][1]
    except sqlite3.Error:
        return None

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


def ultimos_meses_catraca_limites(n: int = 3) -> tuple[pd.Timestamp, pd.Timestamp]:
    limites = _ultimos_meses_presentes_dw(n=n)
    if limites is None:
        fim = pd.Timestamp(LT_FIM_ABS).normalize()
        ini = pd.Timestamp(_month_start(_add_months(fim.date(), -(max(1, n) - 1))))
        return ini, fim
    ini, fim = limites
    return pd.Timestamp(ini).normalize(), pd.Timestamp(fim).normalize()


def ultimos_meses_catraca_indices(n: int = 3) -> list[int]:
    ini, fim = ultimos_meses_catraca_limites(n=n)
    try:
        return [lt_idx_of(ini.year, ini.month), lt_idx_of(fim.year, fim.month)]
    except Exception:
        return [max(0, len(LT_MONTHS) - max(1, n)), len(LT_MONTHS) - 1]
