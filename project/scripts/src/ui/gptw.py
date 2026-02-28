"""df_gptw.py

Tabelas/indicadores relacionados a GPTW (por área).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

import pandas as pd
from dash import html

from ..core import repo_global as repo
from ..domain.gptw import (
    ARROW_DOWN,
    ARROW_NONE,
    ARROW_UP,
    COLOR_DOWN,
    COLOR_NONE,
    COLOR_UP,
)



def _fmt(valor) -> str:
    if pd.isna(valor):
        return "-"
    try:
        numero = float(valor)
        return str(int(numero)) if numero.is_integer() else f"{numero:.1f}"
    except Exception:
        return str(valor)


def _arrow(curr, prox):
    if curr is None or prox is None or pd.isna(curr) or pd.isna(prox):
        return ARROW_NONE, COLOR_NONE
    try:
        atual = float(curr)
        proximo = float(prox)
    except Exception:
        return ARROW_NONE, COLOR_NONE
    if atual > proximo:
        return ARROW_UP, COLOR_UP
    if atual < proximo:
        return ARROW_DOWN, COLOR_DOWN
    return ARROW_NONE, COLOR_NONE


def _listar_subareas(
    area_label: str,
    anos_ord: list[int],
    her_df: pd.DataFrame | None = None,
    df_df_gptw: pd.DataFrame | None = None,
) -> list[str]:
    her_df = her_df if her_df is not None else getattr(repo, "her", None)
    df_df_gptw = df_df_gptw if df_df_gptw is not None else getattr(repo, "df_df_gptw", None)

    subareas: list[str] = []
    if isinstance(her_df, pd.DataFrame) and {"Área", "Heranca"}.issubset(her_df.columns):
        her_df = her_df.copy()
        her_df["Área"] = her_df["Área"].astype(str).str.strip()
        herancas = her_df.loc[her_df["Área"].eq(area_label), "Heranca"].dropna().unique()
        cand = her_df[
            her_df["Área"].str.startswith(area_label)
            & her_df["Área"].ne(area_label)
        ]
        if len(herancas) > 0:
            cand = cand[cand["Heranca"].isin(herancas)]
        subareas = cand["Área"].dropna().unique().tolist()

    if not subareas and isinstance(df_df_gptw, pd.DataFrame):
        all_areas = df_df_gptw["Área"].astype(str).str.strip().unique().tolist()
        subareas = [
            a
            for a in all_areas
            if a != area_label and a.startswith(area_label)
        ]
    return subareas


def _area_sort_key(area: str) -> tuple:
    tokens = [token.strip() for token in str(area).replace("/", "-").split("-") if token.strip()]
    return len(tokens), tuple(tokens)


def mini_tabela_df_gptw(
    area_label: str | None,
    anos: tuple[int, ...] = (2023, 2024, 2025),
    incluir_macro: bool = True,
    df_df_gptw: pd.DataFrame | None = None,
    her_df: pd.DataFrame | None = None,
):
    wrapper_style = {
        "marginLeft": "auto",
        "margin": "0 auto",
        "marginTop": "0",
    }
    th = {
        "padding": "4px 8px",
        "border": "1px solid #bbb",
        "backgroundColor": "#f5f5f5",
        "fontWeight": "bold",
        "textAlign": "center",
        "fontFamily": "VW Text",
        "fontSize": "30px",
    }
    td = {
        "padding": "4px 8px",
        "border": "1px solid #bbb",
        "textAlign": "center",
        "fontFamily": "VW Text",
    }
    td_first = {**td, "fontWeight": "bold", "fontSize": "20px"}
    arrow_style_base = {"marginLeft": "6px", "fontSize": "12px", "opacity": 0.9}

    anos_ord = list(anos)
    anos_str_ord = [str(ano) for ano in anos_ord]
    is_asc_time = anos_ord == sorted(anos_ord)

    if not area_label:
        tabela = html.Table(
            [
                html.Thead(
                    html.Tr(
                        [html.Th("Área", style=th)]
                        + [html.Th(str(a), style=th) for a in anos_ord]
                    )
                ),
                html.Tbody(
                    html.Tr(
                        [html.Td("-", style={**td, "textAlign": "left"})]
                        + [html.Td("-", style=td) for _ in anos_ord]
                    )
                ),
            ],
            style={
                "borderCollapse": "collapse",
                "fontSize": "14px",
                "boxShadow": "0 2px 6px rgba(0,0,0,0.10)",
            },
        )
        return html.Div(tabela, style=wrapper_style)

    df = df_df_gptw if df_df_gptw is not None else getattr(repo, "df_df_gptw", None)
    if df is None or getattr(df, "empty", True):
        tabela = html.Table(
            [
                html.Thead(
                    html.Tr(
                        [html.Th("Área", style=th)]
                        + [html.Th(str(a), style=th) for a in anos_ord]
                    )
                ),
                html.Tbody(
                    html.Tr(
                        [html.Td(area_label, style={**td, "textAlign": "left"})]
                        + [html.Td("-", style=td) for _ in anos_ord]
                    )
                ),
            ],
            style={
                "borderCollapse": "collapse",
                "fontSize": "14px",
                "boxShadow": "0 2px 6px rgba(0,0,0,0.10)",
            },
        )
        return html.Div(tabela, style=wrapper_style, title="df_df_gptw vazio/ausente")

    df = df.copy()
    area_col = "Área" if "Área" in df.columns else None
    if area_col is None:
        return html.Div(
            "df_df_gptw sem coluna Área/Área",
            style={**wrapper_style, "opacity": 0.7, "fontSize": "12px"},
        )

    anos_str_set = set(anos_str_ord)
    is_largo = anos_str_set.issubset(set(df.columns))

    if is_largo:
        cols = [area_col] + anos_str_ord
        tmp = df[cols].copy()
        for col in anos_str_ord:
            tmp[col] = pd.to_numeric(tmp[col], errors="coerce")
        piv = tmp.groupby(area_col)[anos_str_ord].mean()
        piv.columns = [int(c) for c in piv.columns]
        piv = piv.reindex(columns=anos_ord)
    else:
        cand_nota = [
            "Nota",
            "nota",
            "Score",
            "Pontuação",
            "Pontuacao",
            "Indice",
            "Indice",
            "Valor",
            "Value",
        ]
        nota_col = next((col for col in cand_nota if col in df.columns), None)
        if "Ano" not in df.columns or nota_col is None:
            return html.Div(
                "df_df_gptw precisa de colunas 'Ano' e 'Nota/Score/Pontuação'",
                style={**wrapper_style, "opacity": 0.7, "fontSize": "12px"},
            )
        df["Ano"] = pd.to_numeric(df["Ano"], errors="coerce")
        df[nota_col] = pd.to_numeric(df[nota_col], errors="coerce")
        piv = (
            df.groupby([area_col, "Ano"])[nota_col]
            .mean()
            .unstack("Ano")
            .reindex(columns=anos_ord)
        )

    piv.index = piv.index.astype(str).str.strip()
    alvo = str(area_label).strip()

    subareas = _listar_subareas(alvo, anos_ord, her_df=her_df, df_df_gptw=df)
    linhas: list[str] = []
    if incluir_macro:
        linhas.append(alvo)
    linhas.extend(sorted(subareas, key=_area_sort_key))
    if not linhas:
        linhas = [alvo]

    body_rows = []
    for idx, area_nome in enumerate(linhas):
        row = (
            piv.loc[area_nome]
            if area_nome in piv.index
            else pd.Series(index=anos_ord, dtype=float)
        )
        td_this = td_first if idx == 0 else td
        cells = [html.Td(area_nome, style={**td_this, "textAlign": "left"})]
        for j, ano in enumerate(anos_ord):
            valor = row.get(ano) if isinstance(row, pd.Series) else None
            ref_idx = (j - 1) if is_asc_time else (j + 1)
            prox_val = (
                row.get(anos_ord[ref_idx])
                if (0 <= ref_idx < len(anos_ord))
                else None
            )
            texto = _fmt(valor)
            simbolo, cor = _arrow(valor, prox_val)
            conteudo = [html.Span(texto)]
            if texto != "-":
                conteudo.append(html.Span(simbolo, style={**arrow_style_base, "color": cor}))
            cells.append(html.Td(conteudo, style=td_this))
        body_rows.append(html.Tr(cells))

    tabela = html.Table(
        [
            html.Thead(
                html.Tr(
                    [html.Th("Área", style=th)]
                    + [html.Th(str(a), style=th) for a in anos_ord]
                )
            ),
            html.Tbody(body_rows),
        ],
        style={
            "borderCollapse": "collapse",
            "fontSize": "13px",
            "boxShadow": "0px 2px 6px rgba(0,0,0,0.10)",
            "maxWidth": "560px",
        },
    )

    return html.Div(tabela, style=wrapper_style)


def _df_gptw_rows_apenas(
    area_label: str | None,
    anos=(2023, 2024, 2025),
    incluir_macro: bool = True,
):
    tabela = mini_tabela_df_gptw(area_label, anos=anos, incluir_macro=incluir_macro)
    return tabela


def df_gptw_tabela_empilhada(
    areas: list[str] | None,
    anos: tuple[int, ...] = (2023, 2024, 2025),
    df_df_gptw: pd.DataFrame | None = None,
    her_df: pd.DataFrame | None = None,
):
    if not areas:
        return html.Div("Nenhuma área selecionada.", style={"textAlign": "center"})
    blocos = [
        html.Div(
            mini_tabela_df_gptw(
                area,
                anos=anos,
                incluir_macro=True,
                df_df_gptw=df_df_gptw,
                her_df=her_df,
            ),
            style={"margin": "8px 0"},
        )
        for area in areas
    ]
    return html.Div(blocos, style={"display": "flex", "flexDirection": "column"})


def mini_tabelas_df_gptw_multi(
    areas: list[str] | None,
    df_df_gptw: pd.DataFrame | None = None,
    her_df: pd.DataFrame | None = None,
):
    return df_gptw_tabela_empilhada(
        areas,
        df_df_gptw=df_df_gptw,
        her_df=her_df,
    )
