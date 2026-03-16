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

import re
import unicodedata

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


def _area_key(value: object) -> str:
    text = "" if value is None else str(value).strip().lower()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    text = text.replace("_", "-")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^0-9a-z\\/-]+", "", text)
    text = re.sub(r"-{2,}", "-", text)
    text = re.sub(r"/{2,}", "/", text)
    return text


def _normalize_col(col: object) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "", str(col)).lower()


def _turnover_col_for(norm_map: dict[str, str], ano: int, kind: str) -> str | None:
    year_str = str(ano)
    if kind == "hc":
        tokens = ("hc", "headcount", "colab", "colaboradores", "total")
    elif kind == "e":
        tokens = ("e", "entrada", "entradas", "admissao", "admissoes")
    else:
        tokens = ("s", "saida", "saidas", "demissao", "demissoes", "turnover")

    for token in tokens:
        key = f"{year_str}{token}"
        if key in norm_map:
            return norm_map[key]
    for token in tokens:
        key = f"{token}{year_str}"
        if key in norm_map:
            return norm_map[key]
    for norm_col, orig_col in norm_map.items():
        if year_str in norm_col and any(tok in norm_col for tok in tokens):
            return orig_col
    return None


def mini_tabela_df_turnover(
    area_label: str | None,
    anos: tuple[int, ...] = (2023, 2024, 2025),
    incluir_macro: bool = True,
    df_headcount: pd.DataFrame | None = None,
    df_df_gptw: pd.DataFrame | None = None,
    her_df: pd.DataFrame | None = None,
):
    wrapper_style = {
        "marginLeft": "auto",
        "margin": "0 auto",
        "marginTop": "0",
        "width": "fit-content",
        "maxWidth": "100%",
        "overflowX": "auto",
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
    td_sub = {**td, "fontWeight": "600", "fontSize": "14px"}
    td_es = {**td, "fontSize": "12px"}
    arrow_style = {"marginLeft": "6px", "fontSize": "12px", "opacity": 0.9}

    anos_ord = list(anos)
    is_asc_time = anos_ord == sorted(anos_ord)

    def _fmt_val(value) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "-"
        try:
            number = float(value)
            return str(int(number)) if number.is_integer() else f"{number:.1f}"
        except Exception:
            return str(value)

    def _to_float(value):
        try:
            if value is None:
                return None
            number = float(value)
            return None if pd.isna(number) else number
        except Exception:
            return None

    def _arrow(curr, prev):
        if curr is None or prev is None:
            return ARROW_NONE, COLOR_NONE
        if pd.isna(curr) or pd.isna(prev):
            return ARROW_NONE, COLOR_NONE
        try:
            c = float(curr)
            p = float(prev)
        except Exception:
            return ARROW_NONE, COLOR_NONE
        if c > p:
            return ARROW_UP, COLOR_UP
        if c < p:
            return ARROW_DOWN, COLOR_DOWN
        return ARROW_NONE, COLOR_NONE

    header_cells = [html.Th("Área", style=th)]
    for ano in anos_ord:
        header_cells.append(html.Th(str(ano), style={**th, "textAlign": "center"}))
        header_cells.append(html.Th("E", style={**th, "fontSize": "16px", "color": "#008000"}))
        header_cells.append(html.Th("S", style={**th, "fontSize": "16px", "color": "#cc0000"}))

    alvo = (area_label or "").strip()
    if not alvo:
        row_cells = [html.Td("—", style={**td, "textAlign": "left"})]
        for _ in anos_ord:
            row_cells.extend([html.Td("-", style=td), html.Td("-", style=td), html.Td("-", style=td)])
        table = html.Table(
            [html.Thead(html.Tr(header_cells)), html.Tbody([html.Tr(row_cells)])],
            style={"borderCollapse": "collapse", "fontSize": "13px", "boxShadow": "0px 2px 6px rgba(0,0,0,0.10)", "maxWidth": "560px"},
        )
        return html.Div(table, style=wrapper_style)

    df_head = df_headcount if df_headcount is not None else getattr(repo, "df_headcount", None)
    if df_head is None or getattr(df_head, "empty", True):
        row_cells = [html.Td(alvo, style={**td_first, "textAlign": "left"})]
        for _ in anos_ord:
            row_cells.extend([html.Td("-", style=td), html.Td("-", style=td), html.Td("-", style=td)])
        table = html.Table(
            [html.Thead(html.Tr(header_cells)), html.Tbody([html.Tr(row_cells)])],
            style={"borderCollapse": "collapse", "fontSize": "13px", "boxShadow": "0px 2px 6px rgba(0,0,0,0.10)", "maxWidth": "560px"},
        )
        return html.Div(table, style=wrapper_style)

    df_head = df_head.copy()
    area_col = None
    if "Área" in df_head.columns:
        area_col = "Área"
    else:
        for col in df_head.columns:
            if "area" in _normalize_col(col):
                area_col = col
                break
    if area_col is None:
        row_cells = [html.Td(alvo, style={**td_first, "textAlign": "left"})]
        for _ in anos_ord:
            row_cells.extend([html.Td("-", style=td), html.Td("-", style=td), html.Td("-", style=td)])
        table = html.Table(
            [html.Thead(html.Tr(header_cells)), html.Tbody([html.Tr(row_cells)])],
            style={"borderCollapse": "collapse", "fontSize": "13px", "boxShadow": "0px 2px 6px rgba(0,0,0,0.10)", "maxWidth": "560px"},
        )
        return html.Div(table, style=wrapper_style)

    df_head[area_col] = df_head[area_col].astype(str).str.strip()
    df_head["_area_key"] = df_head[area_col].map(_area_key)

    subareas_gptw = _listar_subareas(
        alvo,
        anos_ord,
        her_df=her_df,
        df_df_gptw=(df_df_gptw if df_df_gptw is not None else getattr(repo, "df_df_gptw", None)),
    )
    subareas_head = [
        a for a in df_head[area_col].dropna().astype(str).str.strip().unique().tolist()
        if a != alvo and a.startswith(alvo)
    ]
    subareas = []
    for area in sorted(subareas_gptw + subareas_head, key=_area_sort_key):
        if area not in subareas:
            subareas.append(area)

    linhas = [alvo] if incluir_macro else []
    linhas.extend(subareas)
    if not linhas:
        linhas = [alvo]

    norm_map = {_normalize_col(col): col for col in df_head.columns}
    df_idx = df_head.drop_duplicates(subset=["_area_key"], keep="first").set_index("_area_key", drop=False)
    body_rows = []

    def _serie_por_area(area_nome: str, permitir_agregado: bool = False) -> pd.Series:
        area_k = _area_key(area_nome)
        if area_k in df_idx.index:
            serie_loc = df_idx.loc[area_k]
            if isinstance(serie_loc, pd.DataFrame):
                serie_loc = serie_loc.iloc[0]
            return serie_loc

        if not permitir_agregado:
            return pd.Series(dtype=float)

        mask = df_head[area_col].astype(str).str.strip().str.startswith(str(area_nome).strip())
        if not mask.any():
            return pd.Series(dtype=float)

        agg: dict[str, float] = {}
        for ano in anos_ord:
            for kind in ("hc", "e", "s"):
                col = _turnover_col_for(norm_map, ano, kind)
                if col:
                    agg[col] = float(pd.to_numeric(df_head.loc[mask, col], errors="coerce").fillna(0).sum())
        return pd.Series(agg, dtype=float)

    for idx, area_nome in enumerate(linhas):
        row_td = td_first if idx == 0 else td_sub
        row_cells = [html.Td(area_nome, style={**row_td, "textAlign": "left"})]
        serie = _serie_por_area(area_nome, permitir_agregado=(idx == 0 and incluir_macro))

        prev_hc = None
        metric_values: list[float | None] = []
        for pos, ano in enumerate(anos_ord):
            hc_col = _turnover_col_for(norm_map, ano, "hc")
            e_col = _turnover_col_for(norm_map, ano, "e")
            s_col = _turnover_col_for(norm_map, ano, "s")

            hc_raw = serie.get(hc_col) if hc_col else None
            e_raw = serie.get(e_col) if e_col else None
            s_raw = serie.get(s_col) if s_col else None

            hc_num = _to_float(hc_raw)
            e_num = _to_float(e_raw)
            s_num = _to_float(s_raw)
            metric_values.extend([hc_num, e_num, s_num])

            hc_txt = _fmt_val(hc_raw) if hc_col else "-"
            e_txt = _fmt_val(e_raw) if e_col else "-"
            s_txt = _fmt_val(s_raw) if s_col else "-"

            if is_asc_time:
                curr_prev = prev_hc
            else:
                curr_prev = _to_float(serie.get(_turnover_col_for(norm_map, anos_ord[pos + 1], "hc"))) if pos + 1 < len(anos_ord) else None
            sym, col = _arrow(hc_num, curr_prev)
            hc_children = [html.Span(hc_txt)]
            if hc_txt != "-":
                hc_children.append(html.Span(sym, style={**arrow_style, "color": col}))

            row_cells.append(html.Td(hc_children, style=row_td))
            row_cells.append(html.Td(_fmt_val(e_num), style=td_es if idx > 0 else {**td_es, "fontWeight": "bold"}))
            row_cells.append(html.Td(_fmt_val(s_num), style=td_es if idx > 0 else {**td_es, "fontWeight": "bold"}))
            prev_hc = hc_num

        has_non_zero = any(
            (value is not None) and (not pd.isna(value)) and (abs(float(value)) > 0)
            for value in metric_values
        )
        if has_non_zero:
            body_rows.append(html.Tr(row_cells))

    if not body_rows:
        return html.Div(
            "Sem dados de headcount/turnover para o período selecionado.",
            style={
                **wrapper_style,
                "fontFamily": "VW Text",
                "fontSize": "13px",
                "opacity": 0.8,
                "textAlign": "center",
                "padding": "8px 12px",
            },
        )

    table = html.Table(
        [html.Thead(html.Tr(header_cells)), html.Tbody(body_rows)],
        style={
            "borderCollapse": "collapse",
            "fontSize": "13px",
            "boxShadow": "0px 2px 6px rgba(0,0,0,0.10)",
            "maxWidth": "560px",
        },
    )
    return html.Div(table, style=wrapper_style)


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
        "width": "fit-content",
        "maxWidth": "100%",
        "overflowX": "auto",
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
        td_this = td_first if idx == 0 else {**td_first, "fontSize": "14px", "fontWeight": "600"}
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
