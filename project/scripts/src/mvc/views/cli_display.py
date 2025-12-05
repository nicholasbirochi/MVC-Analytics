"""Views simples para exibir DataFrames no CLI."""
from __future__ import annotations

import pandas as pd


def describe_frames(frames: dict[str, pd.DataFrame], max_rows: int = 5) -> None:
    """Imprime estatísticas e amostras dos DataFrames fornecidos."""
    for nome, df in frames.items():
        print(f"[{nome}] linhas={len(df)} colunas={list(df.columns)}")
        print(df.head(max_rows))


def describe_data_inventory(data: dict[str, pd.DataFrame]) -> None:
    """Exibe contagem de linhas/colunas para cada DataFrame carregado (equiv. ao notebook)."""
    for nome, df in data.items():
        print(f"- {nome}: {df.shape[0]} linhas | {df.shape[1]} colunas")
