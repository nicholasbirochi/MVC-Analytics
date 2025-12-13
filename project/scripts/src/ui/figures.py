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

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

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
        area = info.get("AreaNorm", "")
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
    categorias = ["Interações", "Pessoas únicas", "Dias ativos", "Semanas ativas", "Recência (28d)"]
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
            f"Dias ativos: {valores_raw[2]:.0f}<br>"
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

    area_col = "Area" if "Area" in dfp.columns else None
    meta_cols = ["Cadastro", "Nome", "Cargo"]
    if area_col:
        meta_cols.append(area_col)
    meta_src = (
        dfp.sort_values("Data")
        .drop_duplicates("Cadastro", keep="last")[meta_cols]
    )
    meta = meta_src.set_index("Cadastro").copy()
    if area_col:
        meta = meta.rename(columns={area_col: "AreaNorm"})
    else:
        meta["AreaNorm"] = ""

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

    meta_cols = ["Cadastro", "Nome", "Cargo", "Area"]
    meta = (
        dfp.sort_values("Data")
        .drop_duplicates("Cadastro", keep="last")[meta_cols]
        .set_index("Cadastro")
    )
    meta = meta.rename(columns={"Area": "AreaNorm"})

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
