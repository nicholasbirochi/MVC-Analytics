"""Tabelas utilitárias para exibição."""
from __future__ import annotations

import pandas as pd
from dash import html


def simple_table(df: pd.DataFrame) -> html.Table:
    """Gera uma tabela HTML simples para dados tabulares."""
    if df is None or df.empty:
        return html.Div("Sem dados para exibir.")

    header = [html.Th(col) for col in df.columns]
    body = [
        html.Tr([html.Td(df.iloc[i][col]) for col in df.columns])
        for i in range(min(len(df), 20))
    ]
    return html.Table([html.Thead(html.Tr(header)), html.Tbody(body)])
