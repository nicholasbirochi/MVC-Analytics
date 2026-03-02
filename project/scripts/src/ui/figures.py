"""figures.py

Composição de figuras/plotagens (Plotly/Matplotlib).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

from typing import Iterable

import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import math
from plotly.colors import sample_colorscale


def _safe_hashable(value):
    """Converte objetos potencialmente não-hashable em strings/escalares seguros."""
    try:
        if isinstance(value, np.ndarray):
            try:
                if value.shape == () or value.size == 1:
                    return value.item()
            except Exception:
                pass
            return "|".join(map(str, np.ravel(value).tolist()))
    except Exception:
        pass

    if isinstance(value, (list, tuple, set, frozenset)):
        try:
            if len(value) == 1:
                return next(iter(value))
        except Exception:
            pass
        try:
            return "|".join(map(str, list(value)))
        except Exception:
            return str(value)

    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)

    return value


def _sanitize_object_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza colunas object para strings hashable (evita TypeError unhashable)."""
    if df is None or getattr(df, "empty", True):
        return df
    cleaned = df.copy()
    for col in cleaned.columns:
        if getattr(cleaned[col], "dtype", None) == "object":
            try:
                cleaned[col] = cleaned[col].map(_safe_hashable)
            except Exception:
                cleaned[col] = cleaned[col].astype(str)
    return cleaned

from ..domain.copresenca import calcular_ordem_heatmap
from ..domain.tenure import carregar_adm_dem_cache, tempo_de_casa_str


def _finalizar_heatmap(fig: go.Figure, titulo: str, altura: int = 420) -> go.Figure:
    fig.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        height=altura,
    )
    return fig


def _normalizar_planta_cell(valor) -> frozenset:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return frozenset()
    if isinstance(valor, (set, frozenset)):
        return frozenset(map(lambda item: str(item).strip().lower(), valor))
    if isinstance(valor, (list, tuple)):
        return frozenset(map(lambda item: str(item).strip().lower(), valor))
    texto = str(valor).strip()
    if not texto:
        return frozenset()
    for separador in ["|", ";", ",", "/", "\\"]:
        if separador in texto:
            return frozenset(map(lambda item: item.strip().lower(), texto.split(separador)))
    return frozenset([texto.lower()])


def _montar_labels(meta: pd.DataFrame, cadastros: Iterable[str], tenure: dict[str, str]) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    def _abbr(nome: str) -> str:
        partes = str(nome).split()
        if not partes:
            return ""
        return " ".join([partes[0].capitalize()] + [f"{p[0].upper()}." for p in partes[1:]])

    x_labels = []
    y_labels = []
    custom = []

    for cadastro in cadastros:
        info = meta.loc[cadastro]
        nome = info.get("Nome", "")
        area = info.get("ÁreaNorm", "")
        tenure_label = tenure.get(str(cadastro), "-")
        label = (
            f"{_abbr(nome)} <span style='font-size:10px;opacity:.85'><b>({tenure_label})</b></span>"
            f"<br>({str(area)})"
        )
        x_labels.append(label)
        y_labels.append(label.split("<br>")[0])

    x_full = [f"{str(meta.loc[c, 'Nome']).title()} ({c})" for c in cadastros]
    y_full = [f"{str(meta.loc[c, 'Nome']).title()} ({c})" for c in cadastros]
    custom = [[(x_full[x], y_full[y]) for x in range(len(cadastros))] for y in range(len(cadastros))]
    return x_labels, y_labels, custom


def _abbr_nome_vw(nome: str) -> str:
    """Abreviação simples: primeiro + último token (ex.: 'Ana M. Silva')."""
    try:
        tokens = [t for t in str(nome).split() if t.strip()]
        if not tokens:
            return str(nome)
        if len(tokens) == 1:
            return tokens[0]
        return f"{tokens[0]} {tokens[-1]}"
    except Exception:
        return str(nome)


def _heatmap_colorscale():
    return [
        [0.00, "#af3333"],
        [0.35, "#fc9898"],
        [0.35, "#ffef09"],
        [0.60, "#fff9a9"],
        [0.60, "#9effd0"],
        [1.00, "#267951"],
    ]


def _construir_encontros_exec_men(df_full: pd.DataFrame) -> pd.DataFrame:
    """Cria pares (Data, Exec, Men) com co-presença na mesma planta/dia."""
    if df_full is None or df_full.empty:
        return pd.DataFrame(columns=["Data", "Exec", "Men"])

    df = df_full.copy()
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Data"])
    if df.empty:
        return pd.DataFrame(columns=["Data", "Exec", "Men"])

    if "Planta" in df.columns:
        df["Planta"] = df["Planta"].apply(_normalizar_planta_cell)
    else:
        df["Planta"] = [frozenset()] * len(df)

    df["Cadastro"] = df["Cadastro"].astype(str)
    df["Cargo"] = df["Cargo"].astype(str).str.upper().str[:1]

    pares: list[tuple[pd.Timestamp, str, str]] = []
    for (dia, planta), grupo in df.groupby(["Data", "Planta"]):
        if not planta:
            continue
        execs = grupo.loc[grupo["Cargo"].eq("E"), "Cadastro"].unique().tolist()
        mens = grupo.loc[~grupo["Cargo"].eq("E"), "Cadastro"].unique().tolist()
        if not execs or not mens:
            continue
        for e in execs:
            for m in mens:
                pares.append((dia, e, m))

    return pd.DataFrame(pares, columns=["Data", "Exec", "Men"])


def _metricas_rel_exec_men(df_full: pd.DataFrame):
    """Calcula métricas para radar: encontros, pessoas únicas, dias, semanas, recência (28d)."""
    pares = _construir_encontros_exec_men(df_full)
    if pares.empty:
        vazio = pd.DataFrame(columns=["Exec", "encontros", "pessoas_unicas", "dias", "semanas", "recencia"])
        vazio_m = pd.DataFrame(columns=["Men", "encontros", "pessoas_unicas", "dias", "semanas", "recencia"])
        return vazio, vazio_m, pd.DataFrame(columns=["Data", "encontros_semana"])

    pares["Semana"] = pares["Data"].dt.to_period("W").apply(lambda p: p.start_time)

    e_grp = pares.groupby("Exec")
    exec_df = pd.DataFrame(
        {
            "Exec": e_grp.size().index,
            "encontros": e_grp.size().values,
            "pessoas_unicas": e_grp["Men"].nunique().values,
            "dias": e_grp["Data"].nunique().values,
            "semanas": e_grp["Semana"].nunique().values,
            "recencia": e_grp.apply(
                lambda g: g.loc[g["Data"] >= (pares["Data"].max() - pd.Timedelta(days=28))].shape[0]
            ).values,
        }
    )

    m_grp = pares.groupby("Men")
    men_df = pd.DataFrame(
        {
            "Men": m_grp.size().index,
            "encontros": m_grp.size().values,
            "pessoas_unicas": m_grp["Exec"].nunique().values,
            "dias": m_grp["Data"].nunique().values,
            "semanas": m_grp["Semana"].nunique().values,
            "recencia": m_grp.apply(
                lambda g: g.loc[g["Data"] >= (pares["Data"].max() - pd.Timedelta(days=28))].shape[0]
            ).values,
        }
    )

    serie_sem = pares.groupby("Semana").size().reset_index(name="encontros_semana")
    return exec_df, men_df, serie_sem


def _radar_from_metrics(df: pd.DataFrame, titulo: str, label_col: str, top_n: int = 5) -> go.Figure:
    """Cria um radar (pentágono) com 5 eixos para top_n entidades com cores graduais."""
    fig = go.Figure()

    if df is None or df.empty:
        fig.add_annotation(
            text="Sem dados suficientes para montar a teia.",
            showarrow=False,
            font={"size": 14},
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
        )
        fig.update_layout(
            title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
            height=440,
            margin=dict(l=50, r=40, t=70, b=40),
            polar=dict(
                radialaxis=dict(range=[0, 100], gridcolor="rgba(0,0,0,0.18)", tickfont=dict(size=11)),
                angularaxis=dict(gridcolor="rgba(0,0,0,0.18)", tickfont=dict(size=12)),
            ),
            showlegend=False,
        )
        return fig

    metrics = ["encontros", "pessoas_unicas", "dias", "semanas", "recencia"]
    categorias = ["Interações", "Pessoas únicas", "Dias df_ativos", "Semanas ativas", "Recência (28d)"]
    df = df.copy().sort_values("encontros", ascending=False).head(top_n)

    for m in metrics:
        vmax = df[m].max() or 1
        df[f"{m}_norm"] = (df[m] / vmax) * 100.0

    colorscale = _heatmap_colorscale()
    for _, row in df.iterrows():
        valores_norm = [row[f"{m}_norm"] for m in metrics]
        valores_raw = [row[m] for m in metrics]
        media_norm = float(np.nanmean(valores_norm)) if len(valores_norm) else 0.0
        color = sample_colorscale(colorscale, media_norm / 100 if media_norm else 0)[0]

        hover_text = (
            f"<b>{row[label_col]}</b><br>"
            f"Interações: {valores_raw[0]:.0f}<br>"
            f"Pessoas únicas: {valores_raw[1]:.0f}<br>"
            f"Dias df_ativos: {valores_raw[2]:.0f}<br>"
            f"Semanas ativas: {valores_raw[3]:.0f}<br>"
            f"Recência (28d): {valores_raw[4]:.0f}"
        )

        fig.add_trace(
            go.Scatterpolar(
                r=valores_norm + [valores_norm[0]],
                theta=categorias + [categorias[0]],
                name=str(row[label_col]),
                fill="toself",
                fillcolor=color,
                line=dict(color="rgba(16, 29, 61, 0.8)", width=1),
                marker=dict(color=color),
                hovertemplate=hover_text + "<extra></extra>",
            )
        )

    fig.add_trace(
        go.Scatterpolar(
            r=[0, 0],
            theta=[categorias[0], categorias[0]],
            mode="markers",
            marker=dict(
                size=0.1,
                color=[0, 100],
                colorscale=colorscale,
                cmin=0,
                cmax=100,
                showscale=True,
                colorbar=dict(
                    title="Intensidade",
                    ticksuffix="%",
                    len=0.6,
                    y=0.5,
                ),
            ),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    fig.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        height=480,
        margin=dict(l=60, r=60, t=80, b=40),
        polar=dict(
            radialaxis=dict(
                range=[0, 100],
                gridcolor="rgba(0,0,0,0.18)",
                showline=True,
                linewidth=1,
                tickfont=dict(size=11),
            ),
            angularaxis=dict(
                gridcolor="rgba(0,0,0,0.15)",
                tickfont=dict(size=12),
            ),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, x=0.5, xanchor="center"),
    )
    return fig


def grafico_pentagono_rel_exec(df_full: pd.DataFrame, titulo: str) -> go.Figure:
    exec_df, _, _ = _metricas_rel_exec_men(df_full)
    return _radar_from_metrics(exec_df.rename(columns={"Exec": "Label"}), titulo, "Label", top_n=5)


def grafico_pentagono_rel_men(df_full: pd.DataFrame, titulo: str) -> go.Figure:
    _, men_df, _ = _metricas_rel_exec_men(df_full)
    return _radar_from_metrics(men_df.rename(columns={"Men": "Label"}), titulo, "Label", top_n=5)


def grafico_pentagonos_rel_exec_multiplos(
    df_full: pd.DataFrame,
    titulo: str,
    max_exec: int = 999,
) -> go.Figure:
    """
    Radar dinâmico: 1 polar por executivo, eixos = pessoas relacionadas (mesma base do heatmap).
    """
    from plotly.subplots import make_subplots

    fig_empty = go.Figure()
    fig_empty.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        height=420,
        showlegend=False,
    )

    if df_full is None or getattr(df_full, "empty", True):
        return fig_empty

    df_rel = _sanitize_object_columns(df_full)
    df_rel["Data"] = pd.to_datetime(df_rel.get("Data"), errors="coerce")
    df_rel = df_rel.dropna(subset=["Data"])
    if df_rel.empty:
        return fig_empty

    if "Cadastro" in df_rel.columns:
        df_rel["Cadastro"] = df_rel["Cadastro"].map(_safe_hashable).astype(str)
    if "Cargo" in df_rel.columns:
        df_rel["Cargo"] = df_rel["Cargo"].map(_safe_hashable).astype(str).str.upper().str[:1]
    if "Planta" not in df_rel.columns:
        df_rel["Planta"] = "X"

    meta_src = df_rel.sort_values("Data").drop_duplicates("Cadastro", keep="last")
    name_map = {
        str(row["Cadastro"]): ("" if pd.isna(row.get("Nome")) else str(row.get("Nome")))
        for _, row in meta_src.iterrows()
    }

    rel_df = _construir_encontros_exec_men(df_rel)
    if rel_df is None or rel_df.empty:
        return fig_empty

    rel_df["Exec"] = rel_df["Exec"].astype(str)
    rel_df["Men"] = rel_df["Men"].astype(str)

    counts = rel_df.groupby(["Exec", "Men"]).size().reset_index(name="encontros")
    if counts.empty:
        return fig_empty

    totais_exec = counts.groupby("Exec")["encontros"].sum().sort_values(ascending=False)
    exec_ids = totais_exec.index.tolist()
    if len(exec_ids) > int(max_exec):
        exec_ids = exec_ids[: int(max_exec)]

    n = int(len(exec_ids))
    if n == 0:
        return fig_empty

    cols = 3 if n > 1 else 1
    rows = int(math.ceil(n / cols))
    specs = [[{"type": "polar"} for _ in range(cols)] for _ in range(rows)]

    titles = []
    for eid in exec_ids:
        base_nm = name_map.get(eid, eid) or str(eid)
        titles.append(base_nm)
    while len(titles) < rows * cols:
        titles.append("")

    fig = make_subplots(
        rows=rows,
        cols=cols,
        specs=specs,
        subplot_titles=titles,
        horizontal_spacing=0.08,
        vertical_spacing=0.12,
    )

    max_r = max(float(counts["encontros"].max()), 1.0)

    for i, eid in enumerate(exec_ids):
        rels = counts[counts["Exec"] == eid].sort_values("encontros", ascending=False)
        if rels.empty:
            continue

        cats: list[str] = []
        labels_full: list[str] = []
        rvals: list[float] = []
        for _, row in rels.iterrows():
            mid = str(row["Men"])
            full_nm = name_map.get(mid, mid)
            cats.append(_abbr_nome_vw(full_nm) if full_nm else mid)
            labels_full.append(full_nm or mid)
            rvals.append(float(row["encontros"]))

        if not rvals:
            continue

        theta = cats + cats[:1]
        r_plot = rvals + rvals[:1]
        hover_labels = labels_full + labels_full[:1]
        base_nm = name_map.get(eid, eid) or str(eid)

        fig.add_trace(
            go.Scatterpolar(
                r=r_plot,
                theta=theta,
                fill="toself",
                name=base_nm,
                legendgroup=str(eid),
                hovertemplate="<b>%{text}</b><br>%{customdata}: %{r}<extra></extra>",
                text=[base_nm] * len(theta),
                customdata=hover_labels,
                opacity=0.78,
                showlegend=True,
            ),
            row=(i // cols) + 1,
            col=(i % cols) + 1,
        )

    if not fig.data:
        return fig_empty

    fig.update_polars(
        radialaxis=dict(
            visible=True,
            range=[0, max_r * 1.05],
            gridcolor="rgba(0,0,0,0.06)",
            linecolor="rgba(0,0,0,0.2)",
        ),
        angularaxis=dict(showline=False),
    )
    fig.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        showlegend=True,
        legend_title_text="Executivo base",
        height=max(420, 320 * rows),
        margin=dict(l=60, r=60, t=90, b=50),
        font=dict(family="VW Text"),
    )
    return fig


def _construir_encontros_exec_exec(df_full: pd.DataFrame) -> pd.DataFrame:
    """Cria pares (Data, ExecA, ExecB) com co-presença na mesma planta/dia."""
    if df_full is None or df_full.empty:
        return pd.DataFrame(columns=["Data", "ExecA", "ExecB"])

    df = _sanitize_object_columns(df_full.copy())
    df["Data"] = pd.to_datetime(df.get("Data"), errors="coerce").dt.normalize()
    df = df.dropna(subset=["Data"])
    if df.empty:
        return pd.DataFrame(columns=["Data", "ExecA", "ExecB"])

    if "Cadastro" not in df.columns:
        return pd.DataFrame(columns=["Data", "ExecA", "ExecB"])
    if "Cargo" not in df.columns:
        return pd.DataFrame(columns=["Data", "ExecA", "ExecB"])

    df["Cadastro"] = df["Cadastro"].astype(str)
    df["Cargo"] = df["Cargo"].astype(str).str.upper().str[:1]
    df = df[df["Cargo"].eq("E")].copy()
    if df.empty:
        return pd.DataFrame(columns=["Data", "ExecA", "ExecB"])

    if "Planta" in df.columns:
        df["Planta"] = df["Planta"].apply(_normalizar_planta_cell)
    else:
        df["Planta"] = [frozenset(["x"])] * len(df)

    pares: list[tuple[pd.Timestamp, str, str]] = []
    for _, grupo in df.groupby("Data"):
        grupo = grupo.sort_values("Cadastro").drop_duplicates(subset=["Cadastro"], keep="last")
        if grupo.empty:
            continue
        registros = list(zip(grupo["Cadastro"].tolist(), grupo["Planta"].tolist()))
        for i in range(len(registros)):
            cid_a, pl_a = registros[i]
            for j in range(i + 1, len(registros)):
                cid_b, pl_b = registros[j]
                if not pl_a or not pl_b:
                    continue
                if pl_a.isdisjoint(pl_b):
                    continue
                pares.append((grupo["Data"].iloc[0], str(cid_a), str(cid_b)))

    return pd.DataFrame(pares, columns=["Data", "ExecA", "ExecB"])


def grafico_pentagonos_exec_exec_multiplos(
    df_full: pd.DataFrame,
    titulo: str,
    max_exec: int = 999,
) -> go.Figure:
    """Radar dinâmico: 1 polar por executivo, eixos = executivos relacionados."""
    from plotly.subplots import make_subplots

    fig_empty = go.Figure()
    fig_empty.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        height=420,
        showlegend=False,
    )

    if df_full is None or getattr(df_full, "empty", True):
        return fig_empty

    df_rel = _sanitize_object_columns(df_full.copy())
    df_rel["Data"] = pd.to_datetime(df_rel.get("Data"), errors="coerce")
    df_rel = df_rel.dropna(subset=["Data"])
    if df_rel.empty:
        return fig_empty

    if "Cadastro" in df_rel.columns:
        df_rel["Cadastro"] = df_rel["Cadastro"].map(_safe_hashable).astype(str)
    if "Cargo" in df_rel.columns:
        df_rel["Cargo"] = df_rel["Cargo"].map(_safe_hashable).astype(str).str.upper().str[:1]

    meta_src = df_rel.sort_values("Data").drop_duplicates("Cadastro", keep="last")
    name_map = {
        str(row["Cadastro"]): ("" if pd.isna(row.get("Nome")) else str(row.get("Nome")))
        for _, row in meta_src.iterrows()
    }

    rel_df = _construir_encontros_exec_exec(df_rel)
    if rel_df.empty:
        return fig_empty

    counts_base = rel_df.groupby(["ExecA", "ExecB"]).size().reset_index(name="encontros")
    counts_rev = counts_base.rename(columns={"ExecA": "ExecB", "ExecB": "ExecA"})
    counts = pd.concat([counts_base, counts_rev], ignore_index=True)
    if counts.empty:
        return fig_empty

    totais_exec = counts.groupby("ExecA")["encontros"].sum().sort_values(ascending=False)
    exec_ids = totais_exec.index.tolist()
    if len(exec_ids) > int(max_exec):
        exec_ids = exec_ids[: int(max_exec)]
    n = int(len(exec_ids))
    if n == 0:
        return fig_empty

    cols = 3 if n > 1 else 1
    rows = int(math.ceil(n / cols))
    specs = [[{"type": "polar"} for _ in range(cols)] for _ in range(rows)]

    titles = []
    for eid in exec_ids:
        base_nm = name_map.get(eid, eid) or str(eid)
        titles.append(base_nm)
    while len(titles) < rows * cols:
        titles.append("")

    fig = make_subplots(
        rows=rows,
        cols=cols,
        specs=specs,
        subplot_titles=titles,
        horizontal_spacing=0.08,
        vertical_spacing=0.12,
    )

    max_r = max(float(counts["encontros"].max()), 1.0)

    for i, eid in enumerate(exec_ids):
        rels = counts[counts["ExecA"] == eid].sort_values("encontros", ascending=False)
        if rels.empty:
            continue

        cats: list[str] = []
        labels_full: list[str] = []
        rvals: list[float] = []
        for _, row in rels.iterrows():
            outro = str(row["ExecB"])
            full_nm = name_map.get(outro, outro)
            cats.append(_abbr_nome_vw(full_nm) if full_nm else outro)
            labels_full.append(full_nm or outro)
            rvals.append(float(row["encontros"]))

        if not rvals:
            continue

        theta = cats + cats[:1]
        r_plot = rvals + rvals[:1]
        hover_labels = labels_full + labels_full[:1]
        base_nm = name_map.get(eid, eid) or str(eid)

        fig.add_trace(
            go.Scatterpolar(
                r=r_plot,
                theta=theta,
                fill="toself",
                name=base_nm,
                legendgroup=str(eid),
                hovertemplate="<b>%{text}</b><br>%{customdata}: %{r}<extra></extra>",
                text=[base_nm] * len(theta),
                customdata=hover_labels,
                opacity=0.78,
                showlegend=True,
            ),
            row=(i // cols) + 1,
            col=(i % cols) + 1,
        )

    if not fig.data:
        return fig_empty

    fig.update_polars(
        radialaxis=dict(
            visible=True,
            range=[0, max_r * 1.05],
            gridcolor="rgba(0,0,0,0.06)",
            linecolor="rgba(0,0,0,0.2)",
        ),
        angularaxis=dict(showline=False),
    )
    fig.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        showlegend=True,
        legend_title_text="Executivo base",
        height=max(420, 320 * rows),
        margin=dict(l=60, r=60, t=90, b=50),
        font=dict(family="VW Text"),
    )
    return fig


def grafico_heatmap_encontros_men(
    df_full: pd.DataFrame,
    titulo: str,
    validar_mesma_planta: bool = True,
) -> go.Figure:
    fig = go.Figure()
    if df_full is None or df_full.empty:
        return _finalizar_heatmap(fig, titulo)

    dfp = df_full.copy()
    dfp["Data"] = pd.to_datetime(dfp["Data"], errors="coerce")
    dfp = dfp.dropna(subset=["Data"])
    if dfp.empty:
        return _finalizar_heatmap(fig, titulo)

    days = pd.date_range(
        dfp["Data"].min().normalize(), dfp["Data"].max().normalize(), freq="D"
    )
    pres = (
        dfp.groupby(["Data", "Cadastro"])["Contagem Presença"]
        .max()
        .unstack("Cadastro")
        .reindex(days)
        .fillna(0)
    )

    area_col = "Área" if "Área" in dfp.columns else None
    meta_cols = ["Cadastro", "Nome", "Cargo"]
    if area_col:
        meta_cols.append(area_col)
    meta_src = (
        dfp.sort_values("Data")
        .drop_duplicates("Cadastro", keep="last")[meta_cols]
    )
    meta = meta_src.set_index("Cadastro").copy()
    if area_col:
        meta = meta.rename(columns={area_col: "ÁreaNorm"})
    else:
        meta["ÁreaNorm"] = ""

    adm_cache, dem_cache = carregar_adm_dem_cache()
    ref_dt = days.max() if len(days) else pd.Timestamp.today().normalize()
    tenure = {}
    for cadastro in meta.index:
        cid = str(cadastro)
        adm_ts = adm_cache.get(cid, None)
        dem_ts = dem_cache.get(cid, None)
        tenure[cid] = tempo_de_casa_str(adm_ts, ref=ref_dt, dem_ts=dem_ts)

    mask_M = meta["Cargo"].astype(str).eq("M")
    mask_E = meta["Cargo"].astype(str).eq("E")
    cad_M = meta.index[mask_M].tolist()
    cad_E = meta.index[mask_E].tolist()
    if not cad_M or not cad_E:
        return _finalizar_heatmap(fig, titulo)

    cad_M_ord, cad_E_ord = calcular_ordem_heatmap(dfp)
    cad_M = cad_M_ord or [str(c) for c in cad_M]
    cad_E = cad_E_ord or [str(c) for c in cad_E]

    if validar_mesma_planta and ("Planta" in dfp.columns):
        df_day = dfp[["Data", "Cadastro", "Planta"]].copy()
        df_day["Data"] = pd.to_datetime(df_day["Data"], errors="coerce").dt.normalize()
        df_day = df_day.dropna(subset=["Data", "Cadastro"])
        encontros_same = np.zeros((len(cad_M), len(cad_E)), dtype=float)
        dias_pres_m = np.zeros((len(cad_M),), dtype=float)

        for _, grupo in df_day.groupby("Data"):
            grupo = grupo.sort_values("Cadastro").drop_duplicates(
                subset=["Cadastro"], keep="last"
            )
            serie = grupo.set_index("Cadastro")["Planta"]
            plantas_M = serie.reindex(cad_M)
            plantas_E = serie.reindex(cad_E)

            conjuntos_M = [_normalizar_planta_cell(valor) for valor in plantas_M.tolist()]
            conjuntos_E = [_normalizar_planta_cell(valor) for valor in plantas_E.tolist()]

            presM = np.array([len(conjunto) > 0 for conjunto in conjuntos_M], dtype=bool)
            presE = np.array([len(conjunto) > 0 for conjunto in conjuntos_E], dtype=bool)
            matriz = np.array(
                [
                    [
                        len(conjunto_m) > 0
                        and len(conjunto_e) > 0
                        and not conjunto_m.isdisjoint(conjunto_e)
                        for conjunto_e in conjuntos_E
                    ]
                    for conjunto_m in conjuntos_M
                ],
                dtype=bool,
            )

            validos = matriz & presM[:, None] & presE[None, :]
            encontros_same += validos.astype(float)
            dias_pres_m += presM.astype(float)

        with np.errstate(invalid="ignore", divide="ignore"):
            percent = np.divide(
                encontros_same,
                dias_pres_m[:, None],
                out=np.full_like(encontros_same, np.nan),
                where=dias_pres_m[:, None] > 0,
            ) * 100
    else:
        pres_M = pres.reindex(columns=cad_M).fillna(0).to_numpy(float)
        pres_E = pres.reindex(columns=cad_E).fillna(0).to_numpy(float)
        encontros = pres_M.T @ pres_E
        denom = pres_M.sum(axis=0)[:, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            percent = np.divide(
                encontros,
                denom,
                out=np.full_like(encontros, np.nan),
                where=denom > 0,
            ) * 100

    x_labels, y_labels, custom = _montar_labels(meta, cad_E, tenure)

    text = np.vectorize(
        lambda v: "" if (v is None or (isinstance(v, float) and np.isnan(v))) else f"{v:.1f}%"
    )(percent)

    hover_title = (
        "Encontros"
        if validar_mesma_planta and ("Planta" in dfp.columns)
        else "Encontros (co-presença)"
    )

    fig.add_trace(
        go.Heatmap(
            z=percent,
            x=x_labels,
            y=y_labels,
            customdata=custom,
            colorscale=_heatmap_colorscale(),
            zmin=0,
            zmax=100,
            text=text,
            texttemplate="%{text}",
        hovertemplate=(
            "<b>%{customdata[1]}</b> x <b>%{customdata[0]}</b><br>"
            f"{hover_title}: %{{z:.1f}}%<extra></extra>"
        ),
        showscale=True,
        colorbar=dict(title="Presença (%)", ticksuffix="%", len=0.82, thickness=14),
        hoverongaps=False,
        hoverlabel=dict(bgcolor="white", font=dict(color="black")),
    )
)

    linhas = max(len(y_labels), 1)
    altura = max(460, 40 + 22 * max(linhas, 10))
    fig.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        xaxis_title="",
        yaxis_title="",
        height=altura,
        margin=dict(l=200, r=40, t=70, b=150),
    )
    fig.update_xaxes(tickangle=-45, automargin=True, autorange="reversed")
    fig.update_yaxes(autorange="reversed", automargin=True)
    return fig


def grafico_rede_encontros_exec(
    df_full: pd.DataFrame,
    titulo: str,
    validar_mesma_planta: bool = True,
) -> go.Figure:
    """Rede de proximidade entre executivos (layout spring com pesos)."""
    fig = go.Figure()

    def _final(_fig, msg=None):
        _fig.update_layout(
            title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
            height=420,
            font={"family": "VW Text"},
        )
        if msg:
            _fig.add_annotation(
                text=msg,
                showarrow=False,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                font=dict(color="#555", size=12),
            )
        return _fig

    if df_full is None or getattr(df_full, "empty", True):
        return _final(fig, "Sem dados para montar a rede")

    dfp = _sanitize_object_columns(df_full)
    dfp["Data"] = pd.to_datetime(dfp.get("Data"), errors="coerce")
    dfp = dfp.dropna(subset=["Data"])
    if dfp.empty:
        return _final(fig, "Sem datas válidas para a rede")

    for col in ["Cadastro", "Cargo"]:
        if col not in dfp.columns:
            return _final(fig, "Base incompleta para montar a teia")
    dfp["Cadastro"] = dfp["Cadastro"].astype(str)
    dfp["Cargo"] = dfp["Cargo"].astype(str).str.upper().str[:1]
    if "Contagem Presença" not in dfp.columns:
        dfp["Contagem Presença"] = 1
    if "Planta" not in dfp.columns:
        dfp["Planta"] = "X"

    dfE = dfp[dfp["Cargo"].eq("E")].copy()
    if dfE.empty:
        return _final(fig, "Sem executivos no período")

    meta_src = dfE.sort_values("Data").drop_duplicates("Cadastro", keep="last")
    meta = meta_src[["Cadastro", "Nome", "Cargo"]].set_index("Cadastro")
    name_map = {idx: ("" if pd.isna(row["Nome"]) else str(row["Nome"])) for idx, row in meta.iterrows()}

    days = pd.date_range(dfp["Data"].min().normalize(), dfp["Data"].max().normalize(), freq="D")
    pres = (
        dfE.groupby(["Data", "Cadastro"])["Contagem Presença"].max().unstack("Cadastro").reindex(days).fillna(0.0)
    )
    pres.columns = pres.columns.astype(str)

    cads = list(pres.columns)
    if not cads:
        return _final(fig, "Sem executivos no período")

    arr = pres.to_numpy(float)

    if validar_mesma_planta and ("Planta" in dfE.columns):
        def _to_set(x):
            if x is None or (isinstance(x, float) and pd.isna(x)):
                return frozenset()
            if isinstance(x, (set, frozenset)):
                return frozenset(str(t).strip().lower() for t in x)
            if isinstance(x, (list, tuple)):
                return frozenset(str(t).strip().lower() for t in x)
            s = str(x).strip()
            if not s:
                return frozenset()
            for sep in ("|", ";", ",", "/", "\\"):
                if sep in s:
                    return frozenset(t.strip().lower() for t in s.split(sep))
            return frozenset([s.lower()])

        encontros = np.zeros((len(cads), len(cads)), dtype=float)
        dias_pres = np.zeros((len(cads),), dtype=float)

        df_day = dfE[["Data", "Cadastro", "Planta"]].copy()
        df_day["Data"] = pd.to_datetime(df_day["Data"], errors="coerce").dt.normalize()
        df_day = df_day.dropna(subset=["Data", "Cadastro"])

        for _, grupo in df_day.groupby("Data"):
            grupo = grupo.sort_values("Cadastro").drop_duplicates(subset=["Cadastro"], keep="last")
            serie = grupo.set_index("Cadastro")["Planta"]
            plantas = [_to_set(serie.get(e, None)) for e in cads]
            presentes = np.array([len(pl) > 0 for pl in plantas], dtype=bool)
            same = np.array(
                [
                    [
                        len(plantas[i]) > 0 and len(plantas[j]) > 0 and not plantas[i].isdisjoint(plantas[j])
                        for j in range(len(cads))
                    ]
                    for i in range(len(cads))
                ],
                dtype=bool,
            )
            valid = same & presentes[:, None] & presentes[None, :]
            encontros += valid.astype(float)
            dias_pres += presentes.astype(float)
    else:
        encontros = arr.T @ arr
        dias_pres = arr.sum(axis=0)

    with np.errstate(invalid="ignore", divide="ignore"):
        perc_dir = np.divide(
            encontros,
            dias_pres[:, None],
            out=np.full_like(encontros, np.nan),
            where=(dias_pres[:, None] > 0),
        )
    percent = np.nanmean(np.stack([perc_dir, perc_dir.T], axis=0), axis=0) * 100.0

    n = len(cads)
    edges: list[tuple[float, str, str]] = []
    for i in range(n):
        for j in range(i + 1, n):
            p = percent[i, j]
            if np.isnan(p) or p <= 0:
                continue
            edges.append((float(p), cads[i], cads[j]))

    pos = {}
    try:
        import networkx as nx  # opcional

        G = nx.Graph()
        for cid in cads:
            G.add_node(cid)
        for p, a, b in edges:
            G.add_edge(a, b, weight=max(p, 0.1))
        if len(G) == 1:
            pos = {cads[0]: (0.0, 0.0)}
        elif G.number_of_edges() > 0:
            k_val = 1.15 / np.sqrt(max(len(cads), 1))
            pos_nx = nx.spring_layout(G, weight="weight", k=k_val, iterations=140, seed=42)
            pos = {node: (float(x), float(y)) for node, (x, y) in pos_nx.items()}
    except Exception:
        pos = {}

    if not pos:
        angs = np.linspace(0, 2 * np.pi, n, endpoint=False) if n > 1 else [0]
        pos = {cads[i]: (float(np.cos(angs[i])), float(np.sin(angs[i]))) for i in range(n)}

    def _edge_width(pct):
        if np.isnan(pct) or pct <= 0:
            return 0.0
        return min(6.0, 1.0 + (pct / 18.0))

    def _edge_alpha(pct):
        return max(0.25, min(0.95, 0.25 + (pct / 120.0)))

    def _edge_txt(a, b, pct):
        nome_a = name_map.get(a, a)
        nome_b = name_map.get(b, b)
        return f"{_abbr_nome_vw(nome_a)} × {_abbr_nome_vw(nome_b)} — {pct:.1f}%"

    edges_sorted = sorted(edges, key=lambda item: item[0], reverse=True)
    top_edges = edges_sorted[: min(8, len(edges_sorted))]
    remaining = edges_sorted[min(8, len(edges_sorted)) :]

    buckets: dict[tuple[float, float], dict[str, list]] = {}
    for pct, a, b in remaining:
        width = round(_edge_width(pct), 2)
        alpha = _edge_alpha(pct)
        bucket = buckets.setdefault((width, alpha), {"x": [], "y": [], "text": []})
        bucket["x"] += [pos[a][0], pos[b][0], None]
        bucket["y"] += [pos[a][1], pos[b][1], None]
        bucket["text"].append(_edge_txt(a, b, pct))

    for (width, alpha), data in buckets.items():
        fig.add_trace(
            go.Scatter(
                x=data["x"],
                y=data["y"],
                mode="lines",
                line=dict(width=width, color=f"rgba(70,70,70,{alpha})"),
                hoverinfo="text",
                hovertext=data["text"],
                showlegend=False,
            )
        )

    if top_edges:
        hi_x: list[float] = []
        hi_y: list[float] = []
        hi_text: list[str] = []
        hi_w: list[float] = []
        for pct, a, b in top_edges:
            hi_x += [pos[a][0], pos[b][0], None]
            hi_y += [pos[a][1], pos[b][1], None]
            hi_text.append(_edge_txt(a, b, pct))
            hi_w.append(_edge_width(pct) + 0.6)
        fig.add_trace(
            go.Scatter(
                x=hi_x,
                y=hi_y,
                mode="lines",
                line=dict(width=max(hi_w) if hi_w else 3.6, color="rgba(0,163,122,0.9)"),
                hoverinfo="text",
                hovertext=hi_text,
                showlegend=False,
            )
        )

    strengths: list[float] = []
    for i, cid in enumerate(cads):
        vals = percent[i, :]
        vals = vals[~np.isnan(vals)]
        strengths.append(float(np.nanmean(vals)) if len(vals) else 0.0)
    max_strength = max(strengths) if strengths else 0.0
    max_strength = max(max_strength, 1.0)
    sizes = [14.0 + (s / max_strength) * 12.0 for s in strengths]
    colors = [f"rgba(0,86,184,{0.5 + 0.4 * (s / max_strength)})" for s in strengths]
    nomes = [name_map.get(c, c) for c in cads]

    fig.add_trace(
        go.Scatter(
            x=[pos[c][0] for c in cads],
            y=[pos[c][1] for c in cads],
            mode="markers+text",
            text=[_abbr_nome_vw(n) for n in nomes],
            textposition="top center",
            marker=dict(size=sizes, color=colors, line=dict(width=1.2, color="rgba(255,255,255,0.9)")),
            hoverinfo="text",
            hovertext=[f"{n} ({c})" for n, c in zip(nomes, cads)],
            showlegend=False,
        )
    )

    fig.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        showlegend=False,
        height=max(460, 420),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=90, r=90, t=70, b=60),
        font=dict(family="VW Text"),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="closest",
    )
    return fig

def figura_vazia_linha(
    mensagem: str = "Selecione um Mensalista e um Executivo para carregar o gráfico.",
) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=mensagem,
        showarrow=False,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
    )
    fig.update_layout(height=520, margin=dict(l=60, r=40, t=40, b=40))
    return fig


def grafico_heatmap_encontros_exec(
    df_full: pd.DataFrame,
    titulo: str,
    validar_mesma_planta: bool = True,
) -> go.Figure:
    fig = go.Figure()
    if df_full is None or df_full.empty:
        return _finalizar_heatmap(fig, titulo, altura=520)

    dfp = df_full.copy()
    dfp["Data"] = pd.to_datetime(dfp["Data"], errors="coerce")
    dfp = dfp.dropna(subset=["Data"])
    if dfp.empty:
        return _finalizar_heatmap(fig, titulo, altura=520)

    days = pd.date_range(
        dfp["Data"].min().normalize(), dfp["Data"].max().normalize(), freq="D"
    )
    pres = (
        dfp.groupby(["Data", "Cadastro"])["Contagem Presença"]
        .max()
        .unstack("Cadastro")
        .reindex(days)
        .fillna(0)
    )

    meta_cols = ["Cadastro", "Nome", "Cargo", "Área"]
    meta = (
        dfp.sort_values("Data")
        .drop_duplicates("Cadastro", keep="last")[meta_cols]
        .set_index("Cadastro")
    )
    meta = meta.rename(columns={"Área": "ÁreaNorm"})

    adm_cache, dem_cache = carregar_adm_dem_cache()
    ref_dt = days.max() if len(days) else pd.Timestamp.today().normalize()
    tenure = {}
    for cadastro in meta.index:
        cid = str(cadastro)
        adm_ts = adm_cache.get(cid, None)
        dem_ts = dem_cache.get(cid, None)
        tenure[cid] = tempo_de_casa_str(adm_ts, ref=ref_dt, dem_ts=dem_ts)

    cadastros = meta.index.tolist()
    if len(cadastros) < 2:
        return _finalizar_heatmap(fig, titulo, altura=520)

    cad_ord, _ = calcular_ordem_heatmap(dfp)
    if cad_ord:
        cadastros = cad_ord

    if validar_mesma_planta and ("Planta" in dfp.columns):
        df_day = dfp[["Data", "Cadastro", "Planta"]].copy()
        df_day["Data"] = pd.to_datetime(df_day["Data"], errors="coerce").dt.normalize()
        df_day = df_day.dropna(subset=["Data", "Cadastro"])
        encontros = np.zeros((len(cadastros), len(cadastros)), dtype=float)
        dias_pres = np.zeros((len(cadastros),), dtype=float)

        for _, grupo in df_day.groupby("Data"):
            grupo = grupo.sort_values("Cadastro").drop_duplicates(
                subset=["Cadastro"], keep="last"
            )
            serie = grupo.set_index("Cadastro")["Planta"]
            plantas = serie.reindex(cadastros)
            conjuntos = [_normalizar_planta_cell(valor) for valor in plantas.tolist()]
            presentes = np.array(
                [len(conjunto) > 0 for conjunto in conjuntos], dtype=bool
            )
            matriz = np.array(
                [
                    [
                        len(conj_i) > 0
                        and len(conj_j) > 0
                        and not conj_i.isdisjoint(conj_j)
                        for conj_j in conjuntos
                    ]
                    for conj_i in conjuntos
                ],
                dtype=bool,
            )
            validos = matriz & presentes[:, None] & presentes[None, :]
            encontros += validos.astype(float)
            dias_pres += presentes.astype(float)

        denom = np.where(dias_pres > 0, dias_pres[:, None], np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            percent = np.divide(
                encontros,
                denom,
                out=np.full_like(encontros, np.nan),
                where=~np.isnan(denom),
            ) * 100
    else:
        pres_mat = pres.reindex(columns=cadastros).fillna(0).to_numpy(float)
        encontros = pres_mat.T @ pres_mat
        denom = pres_mat.sum(axis=0)[:, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            percent = np.divide(
                encontros,
                denom,
                out=np.full_like(encontros, np.nan),
                where=denom > 0,
            ) * 100

    x_labels, y_labels, custom = _montar_labels(meta, cadastros, tenure)

    text = np.vectorize(
        lambda v: "" if (v is None or (isinstance(v, float) and np.isnan(v))) else f"{v:.1f}%"
    )(percent)

    hover_title = (
        "Encontros"
        if validar_mesma_planta and ("Planta" in dfp.columns)
        else "Encontros (co-presença)"
    )

    fig.add_trace(
        go.Heatmap(
            z=percent,
            x=x_labels,
            y=y_labels,
            customdata=custom,
            colorscale=_heatmap_colorscale(),
            zmin=0,
            zmax=100,
            text=text,
            texttemplate="%{text}",
        hovertemplate=(
            "<b>%{customdata[1]}</b> x <b>%{customdata[0]}</b><br>"
            f"{hover_title}: %{{z:.1f}}%<extra></extra>"
        ),
        showscale=True,
        colorbar=dict(title="Presença (%)", ticksuffix="%", len=0.82, thickness=14),
        hoverongaps=False,
        hoverlabel=dict(bgcolor="white", font=dict(color="black")),
    )
)

    linhas = max(len(y_labels), 1)
    altura = max(520, 40 + 22 * max(linhas, 10))
    fig.update_layout(
        title={"text": titulo, "font": {"family": "VW Text", "size": 22}},
        xaxis_title="",
        yaxis_title="",
        height=altura,
        margin=dict(l=120, r=40, t=70, b=120),
    )
    fig.update_xaxes(tickangle=-45, automargin=True, autorange="reversed")
    fig.update_yaxes(autorange="reversed", automargin=True)
    return fig
