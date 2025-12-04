import pandas as pd

from project.scripts.src.domain.periods import (
    LT_MONTHS,
    esta_em_ferias,
    listar_segundas_validas,
    periodo_limites,
)


def test_periodo_limites_normalizes_indices():
    dt_ini, dt_fim = periodo_limites((0, 0))

    assert dt_ini.day == 1
    assert dt_ini <= dt_fim
    assert dt_fim.month == LT_MONTHS[0].month


def test_listar_segundas_validas_returns_mondays():
    df = pd.DataFrame({"Data": pd.to_datetime(["2024-01-08", "2024-01-10"])})
    segundas = listar_segundas_validas(df)

    assert pd.Timestamp("2024-01-08") in segundas


def test_esta_em_ferias_matches_collective_period():
    assert esta_em_ferias(pd.Timestamp("2024-12-24"))
    assert not esta_em_ferias(pd.Timestamp("2024-02-10"))
