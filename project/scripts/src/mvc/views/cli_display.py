"""Views simples para exibir DataFrames no CLI."""
from __future__ import annotations

import pandas as pd


def describe_frames(frames: dict[str, pd.DataFrame], max_rows: int = 5) -> None:
    """Imprime estatísticas e amostras dos DataFrames fornecidos."""
    for nome, df in frames.items():
        print(f"[{nome}] linhas={len(df)} colunas={list(df.columns)}")
        print(df.head(max_rows))
