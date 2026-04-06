"""figures.py

Composição de figuras/plotagens (Plotly/Matplotlib).

Projeto: Dashboard presencialidade — Empresa
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
from plotly.subplots import make_subplots

from ..core import repo_global as repo
from ..domain.cargo import normalize_cargo_series


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


FIRST_SEEN_CACHE: dict[str, pd.Timestamp] | None = None


def _carregar_primeira_data_cache() -> dict[str, pd.Timestamp]:
    global FIRST_SEEN_CACHE
    if FIRST_SEEN_CACHE is not None:
        return FIRST_SEEN_CACHE

    FIRST_SEEN_CACHE = {}
    fontes = [
        getattr(repo, "df_datas", None),
        getattr(repo, "df_semana_merged", None),
    ]
    for df_all in fontes:
        if (
            isinstance(df_all, pd.DataFrame)
            and not df_all.empty
            and {"Cadastro", "Data"}.issubset(df_all.columns)
        ):
            tmp = df_all[["Cadastro", "Data"]].copy()
            tmp["Cadastro"] = tmp["Cadastro"].astype(str).str.strip()
            tmp["Data"] = pd.to_datetime(tmp["Data"], errors="coerce")
            tmp = tmp.dropna(subset=["Cadastro", "Data"])
            FIRST_SEEN_CACHE = (
                tmp.groupby("Cadastro")["Data"]
                .min()
                .to_dict()
            )
            if FIRST_SEEN_CACHE:
                break
    return FIRST_SEEN_CACHE


def _finalizar_heatmap(fig: go.Figure, titulo: str, altura: int = 420) -> go.Figure:
    fig.update_layout(
        title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
        height=altura,
    )
    return fig


def _figure_info(fig: go.Figure, message: str) -> go.Figure:
    fig.add_annotation(
        text=message,
        showarrow=False,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        font=dict(size=13, color="#555"),
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
        if cadastro in meta.index:
            info = meta.loc[cadastro]
            nome = info.get("Nome", "")
            area = info.get("ÁreaNorm", "")
        else:
            nome = cadastro
            area = ""
        tenure_label = tenure.get(str(cadastro), "-")
        label = (
            f"{_abbr(nome)} <span style='font-size:10px;opacity:.85'><b>({tenure_label})</b></span>"
            f"<br>({str(area)})"
        )
        x_labels.append(label)
        y_labels.append(label.split("<br>")[0])

    x_full = []
    y_full = []
    for cadastro in cadastros:
        if cadastro in meta.index:
            nome = str(meta.loc[cadastro, "Nome"]).title()
        else:
            nome = str(cadastro)
        label = f"{nome} ({cadastro})"
        x_full.append(label)
        y_full.append(label)
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
    for dia, grupo in df.groupby("Data"):
        grupo = grupo.sort_values("Cadastro").drop_duplicates(subset=["Cadastro"], keep="last")
        if grupo.empty:
            continue
        execs = grupo.loc[grupo["Cargo"].eq("E"), ["Cadastro", "Planta"]]
        mens = grupo.loc[~grupo["Cargo"].eq("E"), ["Cadastro", "Planta"]]
        if execs.empty or mens.empty:
            continue
        for _, ex in execs.iterrows():
            pl_exec = _normalizar_planta_cell(ex.get("Planta"))
            if not pl_exec:
                continue
            for _, men in mens.iterrows():
                pl_men = _normalizar_planta_cell(men.get("Planta"))
                if not pl_men or pl_exec.isdisjoint(pl_men):
                    continue
                pares.append((dia, str(ex["Cadastro"]), str(men["Cadastro"])))

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
            title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
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
        title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
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


def _polar_key(i: int) -> str:
    """Chave do subplot polar no layout do Plotly."""
    i = int(i)
    return "polar" if i == 1 else f"polar{i}"

def _ajustar_domains_subplots_polares(
    fig: go.Figure,
    rows: int,
    cols: int,
    n: int,
    pad_x: float = 0.02,
    pad_y: float = 0.05
) -> go.Figure:
    """Ajuste leve de domains para subplots polares.

    Observação: o make_subplots já define domains. Este helper existe principalmente para:
    - evitar erro quando o código tenta ajustar domains e a chave ainda não existe
    - permitir um ajuste “soft” no futuro sem espalhar lógica pelo código
    """
    try:
        for i in range(1, int(n) + 1):
            key = _polar_key(i)
            if key not in fig.layout:
                continue
            # se não houver domain (raro), define algo padrão
            if getattr(fig.layout[key], "domain", None) is None:
                fig.layout[key].domain = dict(x=[0, 1], y=[0, 1])
    except Exception:
        pass
    return fig

def _hex_to_rgb(h):
    h = h.strip()
    if not h.startswith("#"): h = f"#{h}"
    h = h.lstrip("#")
    if len(h)==3:
        h = "".join([c*2 for c in h])
    return tuple(int(h[i:i+2], 16) for i in (0,2,4))

def interpolar_cor_hex(cor1, cor2, t):
    c1 = [int(cor1[i:i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(cor2[i:i + 2], 16) for i in (1, 3, 5)]
    interp = [int(c1[j] + (c2[j] - c1[j]) * t) for j in range(3)]
    return f"#{interp[0]:02x}{interp[1]:02x}{interp[2]:02x}"

def grafico_pentagonos_rel_exec_multiplos(
    df_full: pd.DataFrame,
    titulo: str,
    max_exec: int = 12,
    max_eixos: int | None = None,        # None = mostra todos (sem limite); senão limita N eixos
    range_mode: str | None = None,      # compatibilidade: ignorado (range fixo 0–100%)
    validar_mesma_planta: bool = True,  # respeita planta/cluster (se houver)
    df_hierarquia: pd.DataFrame | None = None,
    is_almoco: bool = False,            # se True: hover mostra somente o percentual
    strict: bool = True,                # se True: levanta erro claro; se False: devolve fig com mensagem
    n_cols: int = 3,                    # layout dos subplots
    include_exec_subordinados: bool = False,  # inclui "executivos menores" no radar do executivo "maior"
    max_exec_subordinados: int = 3,          # reserva até N eixos para executivos subordinados
):
    """Radares (polar) por executivo — eixos dinâmicos seguindo a MESMA regra do heatmap.
    Obs.: parâmetro range_mode é aceito por compatibilidade, mas o radar usa sempre range 0–100%.

    Regra base (igual ao heatmap Mensalistas×Executivos):
      - Eixo = mensalista comparável ao executivo pela Área
      - Comparável quando: area_m.startswith(area_e) após normalização (barra -> hífen, lower)

    Adicional solicitado:
      - No radar de um executivo "maior" (Área mais abrangente), incluir também os executivos "menores"
        cuja área começa com a área do "maior" (area_exec_sub.startswith(area_exec_maior)), área diferente.

    Métrica (no mesmo espírito do heatmap):
      pct(rel, exec) = dias_em_comum(rel, exec) / dias_presenca_rel(rel) * 100

      - Para mensalistas, o denominador é a presença do mensalista (igual heatmap M×E).
      - Para executivos subordinados (quando incluídos), o denominador é a presença do executivo subordinado.
    """
    # ------------------------- helpers locais -------------------------
    def _fig_erro(msg: str) -> go.Figure:
        fig = go.Figure()
        fig.update_layout(
            title={'text': f"{titulo} — ERRO", 'font': {'family': 'Segoe UI', 'size': 22}, 'x': 0.5, 'xanchor': 'center', 'pad': {'t': 28, 'b': 28}},
            height=420,
            margin=dict(l=60, r=40, t=80, b=40),
            font=dict(family="Segoe UI"),
            showlegend=False
        )
        fig.add_annotation(
            text=str(msg),
            x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False,
            font=dict(family="Segoe UI", size=14),
            align="center"
        )
        return fig

    def _raise_or_fig(msg: str) -> go.Figure:
        if strict:
            raise ValueError(msg)
        return _fig_erro(msg)

    # abreviação (se existir no projeto, usa)
    try:
        _abbr = _abbr_nome_vw  # noqa: F821
    except Exception:
        def _abbr(x: str) -> str:
            x = "" if x is None else str(x).strip()
            if not x:
                return ""
            parts = x.split()
            return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1]}"

    # ------------------------- cores (mesmas do heatmap) -------------------------
    colorscale = [
        [0.00, "#af3333"], [0.35, "#fc9898"],
        [0.35, "#ffef09"], [0.60, "#fff9a9"],
        [0.60, "#9effd0"], [1.00, "#267951"],
    ]

    def _hex_rgba(hex_color: str, alpha: float = 0.22) -> str:
        try:
            r_, g_, b_ = _hex_to_rgb(hex_color)  # noqa: F821 (função global no projeto)
        except Exception:
            h = hex_color.strip().lstrip("#")
            if len(h) == 3:
                h = "".join([c * 2 for c in h])
            r_, g_, b_ = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r_},{g_},{b_},{alpha})"

    def _cor_heatmap(pct: float) -> str:
        # mapeia 0–100 para a mesma escala do heatmap (com transições em 35% e 60%)
        try:
            v = float(pct)
        except Exception:
            v = 0.0
        if np.isnan(v):
            return "#cccccc"
        v = max(0.0, min(100.0, v))
        if v <= 35.0:
            t = v / 35.0 if 35.0 else 0.0
            return interpolar_cor_hex("#af3333", "#fc9898", t)
        elif v <= 60.0:
            t = (v - 35.0) / 25.0 if 25.0 else 0.0
            return interpolar_cor_hex("#ffef09", "#fff9a9", t)
        else:
            t = (v - 60.0) / 40.0 if 40.0 else 0.0
            return interpolar_cor_hex("#9effd0", "#267951", t)


    def _norm_area(x) -> str:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        return str(x).replace("/", "-").strip().lower()

    def _rel_por_area(area_a, area_b) -> bool:
        """True se area_a começa com area_b (após normalização)."""
        sa = _norm_area(area_a)
        sb = _norm_area(area_b)
        return bool(sb) and sa.startswith(sb)

    # compatibilidade planta/cluster (sempre retorna bool)
    def _planta_ok(a, b) -> bool:
        if a is None or b is None:
            return False

        if isinstance(a, (np.ndarray, pd.Series)):
            a = a.tolist()
        if isinstance(b, (np.ndarray, pd.Series)):
            b = b.tolist()

        if isinstance(a, (set, frozenset, list, tuple)) or isinstance(b, (set, frozenset, list, tuple)):
            try:
                sa = set(a) if not isinstance(a, (set, frozenset)) else set(a)
                sb = set(b) if not isinstance(b, (set, frozenset)) else set(b)
                return len(sa.intersection(sb)) > 0
            except Exception:
                return False

        try:
            return str(a) == str(b)
        except Exception:
            return False

    def _planta_nonempty(x) -> bool:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return False
        if isinstance(x, (np.ndarray, pd.Series)):
            try:
                x = x.tolist()
            except Exception:
                pass
        if isinstance(x, (set, frozenset, list, tuple)):
            return len(x) > 0
        s = str(x).strip()
        return bool(s) and s.lower() not in ("nan", "none")


    def _detect_area_col(df: pd.DataFrame) -> str | None:
        if df is None or df.empty:
            return None
        if "Área" in df.columns:
            return "Área"
        if "Área" in df.columns:
            return "Área"
        for c in df.columns:
            if "area" in str(c).lower():
                return c
        return None

    # ------------------------- validações base -------------------------
    if df_full is None or getattr(df_full, "empty", True):
        fig_empty = go.Figure()
        fig_empty.update_layout(
            title={'text': titulo, 'font': {'family': 'Segoe UI', 'size': 22}},
            height=420, showlegend=False, font=dict(family="Segoe UI")
        )
        return fig_empty

    # sanitiza (resolve np.ndarray/list/set em colunas object)
    df_rel = _sanitize_object_columns(df_full.copy())

    required = ["Data", "Cadastro", "Cargo"]
    missing = [c for c in required if c not in df_rel.columns]
    if missing:
        return _raise_or_fig(f"Colunas obrigatórias ausentes para o modo Teia: {missing}")

    df_rel["Data"] = pd.to_datetime(df_rel["Data"], errors="coerce")
    df_rel = df_rel.dropna(subset=["Data"])
    if df_rel.empty:
        fig_empty = go.Figure()
        fig_empty.update_layout(
            title={'text': titulo, 'font': {'family': 'Segoe UI', 'size': 22}},
            height=420, showlegend=False, font=dict(family="Segoe UI")
        )
        return fig_empty

    df_rel["Cadastro"] = df_rel["Cadastro"].map(_safe_hashable).astype(str)

    # normaliza Cargo para E/M/H/T (terceiros como tipo proprio: T)
    df_rel["Cargo"] = normalize_cargo_series(df_rel["Cargo"])

    if "Planta" not in df_rel.columns:
        df_rel["Planta"] = "X"

    # dedup para não inflar presença (mesma abordagem do heatmap)
    df_rel = df_rel.drop_duplicates(subset=["Data", "Cadastro"], keep="last")

    # ------------------------- adiciona Área (se necessário) -------------------------
    hier = df_hierarquia
    if hier is None:
        hier = globals().get("df_ativos", None)

    area_col = _detect_area_col(df_rel)
    if area_col is None and isinstance(hier, pd.DataFrame) and not hier.empty and "Cadastro" in hier.columns:
        area_col_h = _detect_area_col(hier)
        if area_col_h:
            h = hier[["Cadastro", area_col_h]].copy()
            h["Cadastro"] = h["Cadastro"].map(_safe_hashable).astype(str)
            df_rel = df_rel.merge(h, on="Cadastro", how="left")
            area_col = area_col_h

    if area_col:
        df_rel["ÁreaNorm"] = df_rel[area_col].astype(str).replace({"nan": "", "None": ""})
    else:
        df_rel["ÁreaNorm"] = ""

    # ------------------------- meta (nome/área/cargo) -------------------------
    meta_cols = ["Cadastro", "Cargo", "ÁreaNorm"]
    if "Nome" in df_rel.columns:
        meta_cols.insert(1, "Nome")

    meta_src = df_rel.sort_values("Data").drop_duplicates("Cadastro", keep="last")[meta_cols].copy()
    meta_src["Cadastro"] = meta_src["Cadastro"].astype(str)

    name_map = {r["Cadastro"]: ("" if ("Nome" not in r or pd.isna(r.get("Nome"))) else str(r.get("Nome")))
                for _, r in meta_src.iterrows()}
    area_map = {r["Cadastro"]: ("" if pd.isna(r.get("ÁreaNorm")) else str(r.get("ÁreaNorm")))
                for _, r in meta_src.iterrows()}

    exec_ids = sorted(meta_src.loc[meta_src["Cargo"].eq("E"), "Cadastro"].unique().tolist())
    men_ids = sorted(
        meta_src.loc[meta_src["Cargo"].isin(["M", "H", "T"]), "Cadastro"].unique().tolist()
    )  # Mensalistas, Horistas e Terceiros

    if not exec_ids:
        return _raise_or_fig("Nenhum executivo (Cargo=E) encontrado no filtro atual.")

    # ------------------------- relacionamento por Área (igual heatmap) -------------------------
    has_area_info = any(_norm_area(area_map.get(e, "")) for e in exec_ids) and any(_norm_area(area_map.get(m, "")) for m in men_ids)

    related_m_map: dict[str, set[str]] = {}
    related_e_map: dict[str, set[str]] = {}

    if has_area_info:
        for e in exec_ids:
            ae = area_map.get(e, "")
            # mensalistas comparáveis (igual ao heatmap)
            rel_m = {m for m in men_ids if _rel_por_area(area_map.get(m, ""), ae)}
            related_m_map[str(e)] = rel_m

            # executivos "menores" no relacionamento com o "maior"
            if include_exec_subordinados:
                rel_e = {e2 for e2 in exec_ids if (e2 != e and _rel_por_area(area_map.get(e2, ""), ae))}
            else:
                rel_e = set()
            related_e_map[str(e)] = rel_e
    else:
        # fallback: top relacionados (co-presença) — somente quando não há área
        pares = _construir_encontros_exec_men(df_rel)  # usa rotina existente
        if pares is None or pares.empty:
            return _raise_or_fig("Sem dados suficientes para construir a Teia (sem Área e sem co-presença).")
        pares["Exec"] = pares["Exec"].astype(str)
        pares["Men"] = pares["Men"].astype(str)
        for e, g in pares.groupby("Exec"):
            top = (g.groupby("Men")
                   .size()
                   .reset_index(name="encontros")
                   .sort_values("encontros", ascending=False))
            if max_eixos is not None:
                top = top.head(int(max_eixos))
            related_m_map[str(e)] = set(top["Men"].astype(str).tolist())
            related_e_map[str(e)] = set()

    # ------------------------- calcula percentuais (mesma lógica do heatmap) -------------------------
    # denom por "relacionado" (pode ser M ou E subordinado)
    denom_rel: dict[str, int] = {}
    numer_er: dict[tuple[str, str], int] = {}

    df_day = df_rel[["Data", "Cadastro", "Cargo", "Planta"]].copy()
    df_day["Cadastro"] = df_day["Cadastro"].astype(str)

    # conjunto de pessoas que podem aparecer como eixo em algum radar
    candidatos_rel = set()
    for e in exec_ids:
        candidatos_rel |= set(map(str, related_m_map.get(str(e), set())))
        candidatos_rel |= set(map(str, related_e_map.get(str(e), set())))

    for day, g in df_day.groupby("Data"):
        planta_by = dict(zip(g["Cadastro"].astype(str), g["Planta"].tolist()))
        cargo_by = dict(zip(g["Cadastro"].astype(str), g["Cargo"].astype(str)))
        present_set = set(planta_by.keys())

        # denominadores: presença por relacionado (somente para quem é candidato a eixo)
        for pid in present_set.intersection(candidatos_rel):
            if validar_mesma_planta and not _planta_nonempty(planta_by.get(pid, None)):
                continue
            denom_rel[pid] = denom_rel.get(pid, 0) + 1

        # executivos presentes no dia (somente os que têm mapa de relacionamento)
        execs_present = [cad for cad, cargo in zip(g["Cadastro"].astype(str), g["Cargo"].astype(str)) if cargo == "E"]
        execs_present = [e for e in execs_present if e in related_m_map]

        for e in execs_present:
            rels = set()
            rels |= set(map(str, related_m_map.get(e, set())))
            rels |= set(map(str, related_e_map.get(e, set())))
            if not rels:
                continue

            rels_present = present_set.intersection(rels)
            pe = planta_by.get(e, None)

            for pid in rels_present:
                if validar_mesma_planta:
                    pp = planta_by.get(pid, None)
                    if not _planta_ok(pe, pp):
                        continue
                numer_er[(e, pid)] = numer_er.get((e, pid), 0) + 1

    # métricas por par (Exec, Rel)
    if numer_er:
        rows = []
        for (e, pid), num in numer_er.items():
            den = int(denom_rel.get(pid, 0))
            pct = (float(num) / den * 100.0) if den > 0 else np.nan
            rows.append((e, pid, num, den, pct))
        rel_metrics = pd.DataFrame(rows, columns=["Exec", "Rel", "num", "den", "pct"])
    else:
        rel_metrics = pd.DataFrame(columns=["Exec", "Rel", "num", "den", "pct"])

    # score para escolher executivos exibidos
    if not rel_metrics.empty:
        score = (rel_metrics.groupby("Exec")["num"].sum()
                 .sort_values(ascending=False)
                 .reset_index(name="total_num"))
        exec_sel = score["Exec"].astype(str).tolist()
    else:
        pres = (df_rel.loc[df_rel["Cargo"].eq("E")]
                .groupby("Cadastro")["Data"].nunique()
                .sort_values(ascending=False))
        exec_sel = pres.index.astype(str).tolist()

    exec_sel = [e for e in exec_sel if e in exec_ids][:max_exec]
    if not exec_sel:
        return _raise_or_fig("Nenhum executivo elegível após cálculo (verifique filtros/período).")

    # ------------------------- subplots polares -------------------------
    n = len(exec_sel)
    cols = max(1, min(int(n_cols), n))
    rows = int(math.ceil(n / cols))

    subplot_titles = []
    for e in exec_sel:
        nm = name_map.get(str(e), str(e))
        subplot_titles.append(f"{_abbr(nm)} ({e})")
    while len(subplot_titles) < rows * cols:
        subplot_titles.append("")

    specs = [[{"type": "polar"} for _ in range(cols)] for _ in range(rows)]
    fig = make_subplots(rows=rows, cols=cols, specs=specs, subplot_titles=subplot_titles)

    # desloca títulos ~20px PARA CIMA (yshift positivo)
    try:
        for ann in (fig.layout.annotations or []):
            if getattr(ann, "text", "") and "(" in str(ann.text) and ")" in str(ann.text):
                ann.yshift = 30
    except Exception:
        pass

    # range visual: ticks até 100% sempre, mas com um "respiro" para afastar labels (~8 unidades)
    FIXED_TICK_MAX = 100.0
    PAD_VISUAL = 8.0  # 3 + 5 (pedido incremental)
    RANGE_MAX = FIXED_TICK_MAX + PAD_VISUAL

    # ------------------------- 1 radar por executivo -------------------------
    for i, e in enumerate(exec_sel):
        r = (i // cols) + 1
        c = (i % cols) + 1
        e = str(e)

        rel_execs = sorted(list(map(str, related_e_map.get(e, set()))))
        rel_mens  = sorted(list(map(str, related_m_map.get(e, set()))))

        # métricas do executivo
        if not rel_metrics.empty:
            g = rel_metrics.loc[rel_metrics["Exec"].eq(e)].copy()
        else:
            g = pd.DataFrame(columns=["Rel", "pct", "num", "den"])

        val_map = dict(zip(g["Rel"].astype(str), g["pct"].astype(float))) if not g.empty else {}
        num_map = dict(zip(g["Rel"].astype(str), g["num"].astype(int))) if not g.empty else {}
        den_map = dict(zip(g["Rel"].astype(str), g["den"].astype(int))) if not g.empty else {}

        def _mk(pid: str):
            pid = str(pid)
            pct = float(val_map.get(pid, 0.0))
            nnum = int(num_map.get(pid, 0))
            nden = int(den_map.get(pid, int(denom_rel.get(pid, 0))))
            return (pid, pct, nnum, nden)

        exec_vals = [_mk(pid) for pid in rel_execs]
        men_vals  = [_mk(pid) for pid in rel_mens]

        # ordena por pct desc, depois num desc
        exec_vals.sort(key=lambda x: (x[1], x[2]), reverse=True)
        men_vals.sort(key=lambda x: (x[1], x[2]), reverse=True)

        # eixos = exatamente as mesmas pessoas do heatmap (mensalistas comparáveis pela Área)
        rel_vals = men_vals
        if max_eixos is not None:
            rel_vals = rel_vals[:int(max_eixos)]

        if not rel_vals:
            rel_vals = [("Sem pessoas comparáveis (Área)", 0.0, 0, 0)]

        theta = []
        rvals = []
        custom = []

        for pid, pct, nnum, nden in rel_vals:
            if pid == "Sem pessoas comparáveis (Área)":
                p_nome = pid
                pid_show = ""
            else:
                p_nome = name_map.get(pid, pid)
                pid_show = pid

            # Nome em 1ª linha; 2ª linha: Cadastro — % (no estilo do heatmap)
            if pid_show:
                theta.append(f"{_abbr(p_nome)}<br>{pid_show} — {pct:.1f}%")
            else:
                theta.append(f"{_abbr(p_nome)}")
            rvals.append(float(pct))
            _c_hex = _cor_heatmap(pct)
            custom.append([p_nome, pid, nnum, nden, _c_hex, e])

        # fecha polígono
        theta_c = theta + [theta[0]]
        r_c = rvals + [rvals[0]]
        custom_c = custom + [custom[0]]
        # cores por ponto (mesma lógica do heatmap) — usadas nos marcadores e no hover
        _colors = [cd[4] if len(cd) > 4 else '#cccccc' for cd in custom]
        colors_c = _colors + [_colors[0]]

        exec_nome = name_map.get(e, e)


        # cor (igual ao heatmap): linha/preenchimento pelo pct médio; marcadores por pct individual
        _vals_color = [v for v in rvals if isinstance(v, (int, float)) and not np.isnan(v)]
        _pct_mean = float(np.nanmean(_vals_color)) if _vals_color else 0.0
        _line_color = _cor_heatmap(_pct_mean)
        _fill_color = _hex_rgba(_line_color, 0.22)
        # Hover (almoço e geral) no mesmo formato, com cor do ponto (igual ao heatmap)
        hover = (
            "<b>%{customdata[0]}</b> × <b>%{text}</b>"
            "<br><b>%{customdata[5]} x %{customdata[1]} — %{r:.1f}%</b>"
            "<extra></extra>"
        )

        fig.add_trace(
            go.Scatterpolar(
                r=r_c,
                theta=theta_c,
                fill="toself",
                fillcolor=_fill_color,
                mode="lines+markers",
                line=dict(width=2, color=_line_color),
                marker=dict(size=10, line=dict(width=1.5, color='#1a1a1a'), color=colors_c, showscale=False),
                showlegend=False,
                text=[exec_nome] * len(theta_c),
                customdata=custom_c,
                hovertemplate=hover,
            ),
            row=r, col=c
        )

        pol_key = _polar_key(i + 1)

        fig.layout[pol_key].radialaxis.range = [0, RANGE_MAX]
        fig.layout[pol_key].radialaxis.tick0 = 0
        fig.layout[pol_key].radialaxis.dtick = 20
        fig.layout[pol_key].radialaxis.showticklabels = True
        fig.layout[pol_key].radialaxis.tickfont = dict(family="Segoe UI", size=11)
        fig.layout[pol_key].angularaxis.tickfont = dict(family="Segoe UI", size=11)
        fig.layout[pol_key].radialaxis.ticksuffix = "%"

    # ------------------------- layout geral -------------------------
    fig.update_layout(
        title={
            'text': titulo,
            'font': {'family': 'Segoe UI', 'size': 22},
            'x': 0.5, 'xanchor': 'center',
            'pad': {'t': 28, 'b': 20}
        },
        font=dict(family="Segoe UI"),
        hoverlabel=dict(bgcolor="white", bordercolor="black", font=dict(family="Segoe UI", color="black")),
        margin=dict(l=70, r=40, t=125, b=60),
        height=max(520, rows * 420),
        showlegend=False,
    )

    # centralização/ajuste de domains
    if n != 1:
        fig = _ajustar_domains_subplots_polares(fig, rows, cols, n)
    else:
        # centraliza suavemente
        try:
            fig.layout["polar"].domain.x = [0.15, 0.85]
            fig.layout["polar"].domain.y = [0.12, 0.88]
        except Exception:
            pass

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
    max_exec: int = 12,
    max_eixos: int | None = None,        # None = mostra todos (sem limite); senão limita N eixos
    range_mode: str | None = None,      # compatibilidade: ignorado (range fixo 0–100%)
    validar_mesma_planta: bool = True,
    df_hierarquia: pd.DataFrame | None = None,
    is_almoco: bool = False,            # se True: hover mostra somente o percentual
    strict: bool = True,                # se True: levanta erro claro; se False: devolve fig com mensagem
    n_cols: int = 3,                    # layout dos subplots
):
    """Radares (polar) por executivo — relacionamento entre executivos (Exec × Exec).

    Eixos (por executivo):
      - Outros executivos comparáveis pela Área, seguindo a mesma ideia do heatmap:
        area_outro.startswith(area_exec) após normalização (barra -> hífen, lower).

    Valor radial (percentual):
      - pct(outro_exec, exec) = dias_em_comum(outro_exec, exec) / dias_presenca(outro_exec) * 100
      - Isso corresponde à célula do heatmap Exec×Exec na *linha* do "outro_exec" e *coluna* do "exec".

    Observações:
      - range_mode é aceito por compatibilidade, mas o radar usa sempre 0–100% (com ticks até 100%).
      - Se não houver Área disponível, faz fallback por top co-presença (somente entre executivos).
    """
    # ------------------------- helpers locais -------------------------
    def _fig_erro(msg: str) -> go.Figure:
        fig = go.Figure()
        fig.update_layout(
            title={'text': f"{titulo} — ERRO", 'font': {'family': 'Segoe UI', 'size': 22},
                   'x': 0.5, 'xanchor': 'center', 'pad': {'t': 28, 'b': 28}},
            height=420,
            margin=dict(l=60, r=40, t=125, b=40),
            font=dict(family="Segoe UI"),
            showlegend=False
        )
        fig.add_annotation(
            text=str(msg),
            x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False,
            font=dict(family="Segoe UI", size=14),
            align="center"
        )
        return fig

    def _raise_or_fig(msg: str) -> go.Figure:
        if strict:
            raise ValueError(msg)
        return _fig_erro(msg)

    try:
        _abbr = _abbr_nome_vw  # noqa: F821
    except Exception:
        def _abbr(x: str) -> str:
            x = "" if x is None else str(x).strip()
            if not x:
                return ""
            parts = x.split()
            return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1]}"

    # ------------------------- cores (mesmas do heatmap) -------------------------
    colorscale = [
        [0.00, "#af3333"], [0.35, "#fc9898"],
        [0.35, "#ffef09"], [0.60, "#fff9a9"],
        [0.60, "#9effd0"], [1.00, "#267951"],
    ]

    def _hex_rgba(hex_color: str, alpha: float = 0.22) -> str:
        try:
            r_, g_, b_ = _hex_to_rgb(hex_color)  # noqa: F821 (função global no projeto)
        except Exception:
            h = hex_color.strip().lstrip("#")
            if len(h) == 3:
                h = "".join([c * 2 for c in h])
            r_, g_, b_ = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r_},{g_},{b_},{alpha})"

    def _cor_heatmap(pct: float) -> str:
        # mapeia 0–100 para a mesma escala do heatmap (com transições em 35% e 60%)
        try:
            v = float(pct)
        except Exception:
            v = 0.0
        if np.isnan(v):
            return "#cccccc"
        v = max(0.0, min(100.0, v))
        if v <= 35.0:
            t = v / 35.0 if 35.0 else 0.0
            return interpolar_cor_hex("#af3333", "#fc9898", t)
        elif v <= 60.0:
            t = (v - 35.0) / 25.0 if 25.0 else 0.0
            return interpolar_cor_hex("#ffef09", "#fff9a9", t)
        else:
            t = (v - 60.0) / 40.0 if 40.0 else 0.0
            return interpolar_cor_hex("#9effd0", "#267951", t)


    def _norm_area(x) -> str:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return ""
        return str(x).replace("/", "-").strip().lower()

    def _rel_por_area(area_outro, area_exec) -> bool:
        so = _norm_area(area_outro)
        se = _norm_area(area_exec)
        return bool(se) and so.startswith(se)

    def _planta_ok(a, b) -> bool:
        if a is None or b is None:
            return False
        if isinstance(a, (np.ndarray, pd.Series)):
            a = a.tolist()
        if isinstance(b, (np.ndarray, pd.Series)):
            b = b.tolist()
        if isinstance(a, (set, frozenset, list, tuple)) or isinstance(b, (set, frozenset, list, tuple)):
            try:
                sa = set(a) if not isinstance(a, (set, frozenset)) else set(a)
                sb = set(b) if not isinstance(b, (set, frozenset)) else set(b)
                return len(sa.intersection(sb)) > 0
            except Exception:
                return False
        try:
            return str(a) == str(b)
        except Exception:
            return False

    def _planta_nonempty(x) -> bool:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return False
        if isinstance(x, (np.ndarray, pd.Series)):
            try:
                x = x.tolist()
            except Exception:
                pass
        if isinstance(x, (set, frozenset, list, tuple)):
            return len(x) > 0
        s = str(x).strip()
        return bool(s) and s.lower() not in ("nan", "none")

    def _detect_area_col(df: pd.DataFrame) -> str | None:
        if df is None or df.empty:
            return None
        if "Área" in df.columns:
            return "Área"
        if "Área" in df.columns:
            return "Área"
        for c in df.columns:
            if "area" in str(c).lower():
                return c
        return None

    # ------------------------- validações base -------------------------
    if df_full is None or getattr(df_full, "empty", True):
        fig_empty = go.Figure()
        fig_empty.update_layout(
            title={'text': titulo, 'font': {'family': 'Segoe UI', 'size': 22},
                   'x': 0.5, 'xanchor': 'center', 'pad': {'t': 28, 'b': 28}},
            height=420, showlegend=False, font=dict(family="Segoe UI")
        )
        return fig_empty

    df_rel = _sanitize_object_columns(df_full.copy())

    required = ["Data", "Cadastro", "Cargo"]
    missing = [c for c in required if c not in df_rel.columns]
    if missing:
        return _raise_or_fig(f"Colunas obrigatórias ausentes para o modo Teia (Exec×Exec): {missing}")

    df_rel["Data"] = pd.to_datetime(df_rel["Data"], errors="coerce")
    df_rel = df_rel.dropna(subset=["Data"])
    if df_rel.empty:
        fig_empty = go.Figure()
        fig_empty.update_layout(
            title={'text': titulo, 'font': {'family': 'Segoe UI', 'size': 22},
                   'x': 0.5, 'xanchor': 'center', 'pad': {'t': 28, 'b': 28}},
            height=420, showlegend=False, font=dict(family="Segoe UI")
        )
        return fig_empty

    df_rel["Cadastro"] = df_rel["Cadastro"].map(_safe_hashable).astype(str)

    # normaliza Cargo para E/M/H/T (terceiros como tipo proprio: T)
    df_rel["Cargo"] = normalize_cargo_series(df_rel["Cargo"])

    # apenas executivos
    df_rel = df_rel[df_rel["Cargo"].eq("E")].copy()
    if df_rel.empty:
        return _raise_or_fig("Nenhum executivo (Cargo=E) encontrado no filtro atual.")

    if "Planta" not in df_rel.columns:
        df_rel["Planta"] = "X"

    # dedup para não inflar presença
    df_rel = df_rel.drop_duplicates(subset=["Data", "Cadastro"], keep="last")

    # ------------------------- adiciona Área (se necessário) -------------------------
    hier = df_hierarquia
    if hier is None:
        hier = globals().get("df_ativos", None)

    area_col = _detect_area_col(df_rel)
    if area_col is None and isinstance(hier, pd.DataFrame) and not hier.empty and "Cadastro" in hier.columns:
        area_col_h = _detect_area_col(hier)
        if area_col_h:
            h = hier[["Cadastro", area_col_h]].copy()
            h["Cadastro"] = h["Cadastro"].map(_safe_hashable).astype(str)
            df_rel = df_rel.merge(h, on="Cadastro", how="left")
            area_col = area_col_h

    if area_col:
        df_rel["ÁreaNorm"] = df_rel[area_col].astype(str).replace({"nan": "", "None": ""})
    else:
        df_rel["ÁreaNorm"] = ""

    # ------------------------- meta (nome/área) -------------------------
    meta_cols = ["Cadastro", "ÁreaNorm"]
    if "Nome" in df_rel.columns:
        meta_cols.insert(1, "Nome")
    meta_src = df_rel.sort_values("Data").drop_duplicates("Cadastro", keep="last")[meta_cols].copy()
    meta_src["Cadastro"] = meta_src["Cadastro"].astype(str)

    name_map = {r["Cadastro"]: ("" if ("Nome" not in r or pd.isna(r.get("Nome"))) else str(r.get("Nome")))
                for _, r in meta_src.iterrows()}
    area_map = {r["Cadastro"]: ("" if pd.isna(r.get("ÁreaNorm")) else str(r.get("ÁreaNorm")))
                for _, r in meta_src.iterrows()}

    exec_ids = sorted(meta_src["Cadastro"].astype(str).unique().tolist())
    if not exec_ids:
        return _raise_or_fig("Nenhum executivo encontrado após consolidar metadados.")

    # ------------------------- mapa de relacionados (exec -> outros execs) -------------------------
    has_area_info = any(_norm_area(area_map.get(e, "")) for e in exec_ids)

    related_e_map: dict[str, list[str]] = {}

    if has_area_info:
        # Pedido: na 2ª seção (Exec×Exec), mostrar a relação de TODOS os executivos
        # com TODOS os demais (não apenas "subordinados" por prefixo de Área).
        # Mantemos Área apenas para ordenação estável.
        def _exec_sort_key(cad: str):
            return (
                _norm_area(area_map.get(cad, "")),
                str(name_map.get(cad, cad)).lower(),
                str(cad)
            )

        for e in exec_ids:
            rels = [e2 for e2 in exec_ids if e2 != e]
            rels.sort(key=_exec_sort_key)
            related_e_map[str(e)] = rels
    else:
        # fallback: top relacionados por co-presença bruta (encontros) — entre executivos
        # (usa a própria base filtrada e valida planta, se disponível)
        # estratégia: contar co-presença simples por dia (sem %), depois escolher top.
        df_day = df_rel[["Data", "Cadastro", "Planta"]].copy()
        df_day["Cadastro"] = df_day["Cadastro"].astype(str)

        from collections import defaultdict
        counts = defaultdict(int)
        for day, g in df_day.groupby("Data"):
            g = g.sort_values("Cadastro").drop_duplicates(subset=["Cadastro"], keep="last")
            ids = g["Cadastro"].astype(str).tolist()
            planta_by = dict(zip(g["Cadastro"].astype(str), g["Planta"].tolist()))

            for i in range(len(ids)):
                for j in range(len(ids)):
                    if i == j:
                        continue
                    a, b = ids[i], ids[j]
                    if validar_mesma_planta and not _planta_ok(planta_by.get(a, None), planta_by.get(b, None)):
                        continue
                    counts[(a, b)] += 1

        for e in exec_ids:
            rels = [(b, counts.get((e, b), 0)) for b in exec_ids if b != e]
            rels.sort(key=lambda x: x[1], reverse=True)
            # fallback: se max_eixos definido, respeita; senão, usa todos com contagem>0
            if max_eixos is None:
                rel_list = [b for b, v in rels if v > 0]
            else:
                rel_list = [b for b, v in rels[:int(max_eixos)]]
            related_e_map[str(e)] = rel_list

    # ------------------------- calcula matriz % (mesma lógica do heatmap Exec×Exec) -------------------------
    idx_map = {cad: i for i, cad in enumerate(exec_ids)}
    N = len(exec_ids)

    encontros_same = np.zeros((N, N), dtype=float)
    dias_pres = np.zeros((N,), dtype=float)

    df_day = df_rel[["Data", "Cadastro", "Planta"]].copy()
    df_day["Cadastro"] = df_day["Cadastro"].astype(str)

    for day, g in df_day.groupby("Data"):
        g = g.sort_values("Cadastro").drop_duplicates(subset=["Cadastro"], keep="last")
        planta_by = dict(zip(g["Cadastro"].astype(str), g["Planta"].tolist()))
        present = set(planta_by.keys())

        sets_list = []
        pres_mask = np.zeros((N,), dtype=bool)

        # prepara vetores por ordem exec_ids
        for i, cad in enumerate(exec_ids):
            pl = planta_by.get(cad, None)
            if validar_mesma_planta:
                ok = _planta_nonempty(pl)
            else:
                ok = cad in present
            pres_mask[i] = bool(ok)
            sets_list.append(pl)

        dias_pres += pres_mask.astype(float)

        if not np.any(pres_mask):
            continue

        # computa co-presença (mesma planta se validar)
        if validar_mesma_planta:
            # matriz booleana NxN: interseção de plantas e ambos presentes
            same = np.zeros((N, N), dtype=bool)
            for i in range(N):
                if not pres_mask[i]:
                    continue
                for j in range(N):
                    if not pres_mask[j]:
                        continue
                    if i == j:
                        continue
                    if _planta_ok(sets_list[i], sets_list[j]):
                        same[i, j] = True
            valid = same
        else:
            # sem planta: basta ambos presentes
            valid = pres_mask[:, None] & pres_mask[None, :]
            np.fill_diagonal(valid, False)

        encontros_same += valid.astype(float)

    denom = dias_pres[:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        percent = np.divide(
            encontros_same,
            denom,
            out=np.full_like(encontros_same, np.nan, dtype=float),
            where=(denom > 0)
        ) * 100.0

    np.fill_diagonal(percent, np.nan)

    # ------------------------- seleção de executivos exibidos -------------------------
    pres_exec = (df_rel.groupby("Cadastro")["Data"].nunique()
                 .sort_values(ascending=False))
    exec_sel = pres_exec.index.astype(str).tolist()[:max_exec]
    exec_sel = [e for e in exec_sel if e in exec_ids]

    if not exec_sel:
        return _raise_or_fig("Nenhum executivo elegível após cálculo (verifique filtros/período).")

    # ------------------------- subplots polares -------------------------
    n = len(exec_sel)
    cols = max(1, min(int(n_cols), n))
    rows = int(math.ceil(n / cols))

    subplot_titles = []
    for e in exec_sel:
        nm = name_map.get(str(e), str(e))
        subplot_titles.append(f"{_abbr(nm)} ({e})")
    while len(subplot_titles) < rows * cols:
        subplot_titles.append("")

    specs = [[{"type": "polar"} for _ in range(cols)] for _ in range(rows)]
    fig = make_subplots(rows=rows, cols=cols, specs=specs, subplot_titles=subplot_titles)

    # títulos dos subplots: deslocados para cima (yshift positivo)
    try:
        for ann in (fig.layout.annotations or []):
            if getattr(ann, "text", "") and "(" in str(ann.text) and ")" in str(ann.text):
                ann.yshift = 30
    except Exception:
        pass

    FIXED_TICK_MAX = 100.0
    PAD_VISUAL = 8.0
    RANGE_MAX = FIXED_TICK_MAX + PAD_VISUAL

    # ------------------------- 1 radar por executivo -------------------------
    for i, e in enumerate(exec_sel):
        r = (i // cols) + 1
        c = (i % cols) + 1
        e = str(e)

        # eixos = executivos comparáveis pela área (mesma ideia do heatmap)
        rels = list(map(str, related_e_map.get(e, [])))
        if max_eixos is not None:
            rels = rels[:int(max_eixos)]

        if not rels:
            rels = ["Sem executivos comparáveis (Área)"]

        e_idx = idx_map.get(e, None)

        theta = []
        rvals = []
        custom = []

        for pid in rels:
            if pid == "Sem executivos comparáveis (Área)" or e_idx is None or pid not in idx_map:
                p_nome = pid
                pid_show = ""
                pct = 0.0
            else:
                p_nome = name_map.get(pid, pid)
                pid_show = pid
                p_idx = idx_map[pid]
                # percent do HEATMAP: linha = pid (rel), coluna = e
                v = percent[p_idx, e_idx]
                pct = 0.0 if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)

            if pid_show:
                theta.append(f"{_abbr(p_nome)}<br>{pid_show} — {pct:.1f}%")
            else:
                theta.append(f"{_abbr(p_nome)}")
            rvals.append(float(pct))
            _c_hex = _cor_heatmap(pct)
            custom.append([p_nome, pid, _c_hex, e])

        theta_c = theta + [theta[0]]
        r_c = rvals + [rvals[0]]
        custom_c = custom + [custom[0]]
        _colors = [cd[2] if len(cd) > 2 else '#cccccc' for cd in custom]
        colors_c = _colors + [_colors[0]]

        exec_nome = name_map.get(e, e)


        # cor (igual ao heatmap): linha/preenchimento pelo pct médio; marcadores por pct individual
        _vals_color = [v for v in rvals if isinstance(v, (int, float)) and not np.isnan(v)]
        _pct_mean = float(np.nanmean(_vals_color)) if _vals_color else 0.0
        _line_color = _cor_heatmap(_pct_mean)
        _fill_color = _hex_rgba(_line_color, 0.22)
        # Hover (almoço e geral) no mesmo formato, com cor do ponto (igual ao heatmap)
        hover = (
            "<b>%{customdata[0]}</b> × <b>%{text}</b>"
            "<br><b>%{customdata[3]} x %{customdata[1]} — %{r:.1f}%</b>"
            "<extra></extra>"
        )

        fig.add_trace(
            go.Scatterpolar(
                r=r_c,
                theta=theta_c,
                fill="toself",
                fillcolor=_fill_color,
                mode="lines+markers",
                line=dict(width=2, color=_line_color),
                marker=dict(size=10, line=dict(width=1.5, color='#1a1a1a'), color=colors_c, showscale=False),
                showlegend=False,
                text=[exec_nome] * len(theta_c),
                customdata=custom_c,
                hovertemplate=hover,
            ),
            row=r, col=c
        )

        pol_key = _polar_key(i + 1)

        fig.layout[pol_key].radialaxis.range = [0, RANGE_MAX]
        fig.layout[pol_key].radialaxis.tick0 = 0
        fig.layout[pol_key].radialaxis.dtick = 20
        fig.layout[pol_key].radialaxis.showticklabels = True
        fig.layout[pol_key].radialaxis.tickfont = dict(family="Segoe UI", size=11)
        fig.layout[pol_key].angularaxis.tickfont = dict(family="Segoe UI", size=11)
        fig.layout[pol_key].radialaxis.ticksuffix = "%"

    # ------------------------- layout geral -------------------------
    fig.update_layout(
        title={
            'text': titulo,
            'font': {'family': 'Segoe UI', 'size': 22},
            'x': 0.5, 'xanchor': 'center',
            'pad': {'t': 28, 'b': 20}
        },
        font=dict(family="Segoe UI"),
        hoverlabel=dict(bgcolor="white", bordercolor="black", font=dict(family="Segoe UI", color="black")),
        margin=dict(l=70, r=40, t=125, b=60),
        height=max(520, rows * 420),
        showlegend=False,
    )

    if n != 1:
        fig = _ajustar_domains_subplots_polares(fig, rows, cols, n)
    else:
        try:
            fig.layout["polar"].domain.x = [0.15, 0.85]
            fig.layout["polar"].domain.y = [0.12, 0.88]
        except Exception:
            pass

    return fig

def grafico_heatmap_encontros_men(
    df_full: pd.DataFrame,
    titulo: str,
    validar_mesma_planta: bool = True,
) -> go.Figure:
    fig = go.Figure()

    def _final(_fig: go.Figure) -> go.Figure:
        _fig.update_layout(
            title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
            height=420,
        )
        return _fig

    if df_full is None or df_full.empty:
        return _final(fig)

    dfp = df_full.copy()
    if "Cadastro" in dfp.columns:
        dfp["Cadastro"] = dfp["Cadastro"].astype(str)
    dfp["Data"] = pd.to_datetime(dfp["Data"], errors="coerce")
    dfp = dfp.dropna(subset=["Data"])
    if dfp.empty:
        return _final(fig)

    area_col = "Área" if "Área" in dfp.columns else None

    days = pd.date_range(
        dfp["Data"].min().normalize(),
        dfp["Data"].max().normalize(),
        freq="D",
    )

    pres = (
        dfp.groupby(["Data", "Cadastro"])["Contagem Presença"]
        .max()
        .unstack("Cadastro")
        .reindex(days)
        .fillna(0)
    )

    meta_cols = ["Cadastro", "Nome", "Cargo"] + ([area_col] if area_col else [])
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
    first_seen_cache = _carregar_primeira_data_cache()
    ref_dt = pd.Timestamp.today().normalize()
    tenure: dict[str, str] = {}
    for cad in meta.index:
        cid = str(cad)
        adm_ts = adm_cache.get(cid, None)
        dem_ts = dem_cache.get(cid, None)
        if pd.isna(adm_ts) or adm_ts is None:
            adm_ts = first_seen_cache.get(cid, None)
        if pd.isna(adm_ts) or adm_ts is None:
            datas_cad = pd.to_datetime(
                dfp.loc[dfp["Cadastro"].astype(str) == cid, "Data"],
                errors="coerce",
            ).dropna()
            adm_ts = datas_cad.min() if not datas_cad.empty else None
        tenure[cid] = tempo_de_casa_str(adm_ts, ref=ref_dt, dem_ts=dem_ts)

    def _tok(texto: object) -> list[str]:
        return [t.strip() for t in str(texto).replace("/", "-").split("-") if t.strip()]

    def _akey(area: object) -> tuple[int, tuple[str, ...]]:
        tokens = _tok(area)
        return (len(tokens), tuple(tokens))

    def _rel(area_m: object, area_e: object) -> bool:
        if pd.isna(area_m) or pd.isna(area_e):
            return False
        sm = str(area_m).replace("/", "-").lower().strip()
        se = str(area_e).replace("/", "-").lower().strip()
        return bool(se) and sm.startswith(se)

    mask_m = meta["Cargo"].astype(str).isin(["M", "H", "T"])
    mask_e = meta["Cargo"].astype(str).eq("E")

    cad_m = sorted(
        meta.index[mask_m],
        key=lambda c: (
            _akey(meta.loc[c, "ÁreaNorm"]),
            str(meta.loc[c, "Nome"]).lower(),
            str(c),
        ),
    )
    cad_e = sorted(
        meta.index[mask_e],
        key=lambda c: (
            _akey(meta.loc[c, "ÁreaNorm"]),
            str(meta.loc[c, "Nome"]).lower(),
            str(c),
        ),
    )

    if not cad_m or not cad_e:
        return _final(fig)

    if validar_mesma_planta and ("Planta" in dfp.columns):
        df_day = dfp[["Data", "Cadastro", "Planta"]].copy()
        df_day["Data"] = pd.to_datetime(df_day["Data"], errors="coerce").dt.normalize()
        df_day = df_day.dropna(subset=["Data", "Cadastro"])

        encontros_same = np.zeros((len(cad_m), len(cad_e)), dtype=float)
        dias_pres_m = np.zeros((len(cad_m),), dtype=float)

        for _, g in df_day.groupby("Data"):
            g = g.sort_values("Cadastro").drop_duplicates(subset=["Cadastro"], keep="last")
            serie = g.set_index("Cadastro")["Planta"]
            plantas_m = serie.reindex(cad_m)
            plantas_e = serie.reindex(cad_e)

            m_sets = [_normalizar_planta_cell(val) for val in plantas_m.tolist()]
            e_sets = [_normalizar_planta_cell(val) for val in plantas_e.tolist()]

            pres_m = np.array([len(ms) > 0 for ms in m_sets], dtype=bool)
            pres_e = np.array([len(es) > 0 for es in e_sets], dtype=bool)
            same = np.array(
                [
                    [
                        len(ms) > 0
                        and len(es) > 0
                        and not ms.isdisjoint(es)
                        for es in e_sets
                    ]
                    for ms in m_sets
                ],
                dtype=bool,
            )

            valid = same & pres_m[:, None] & pres_e[None, :]
            encontros_same += valid.astype(float)
            dias_pres_m += pres_m.astype(float)

        denom = dias_pres_m[:, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            percent = np.divide(
                encontros_same,
                denom,
                out=np.full_like(encontros_same, np.nan, dtype=float),
                where=(denom > 0),
            ) * 100.0
    else:
        arr_m = pres.reindex(columns=cad_m).fillna(0).to_numpy(float)
        arr_e = pres.reindex(columns=cad_e).fillna(0).to_numpy(float)
        encontros = arr_m.T @ arr_e
        denom = arr_m.sum(axis=0)[:, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            percent = np.divide(
                encontros,
                denom,
                out=np.full_like(encontros, np.nan, dtype=float),
                where=(denom > 0),
            ) * 100.0

    allowed = np.array(
        [
            [_rel(meta.loc[m, "ÁreaNorm"], meta.loc[e, "ÁreaNorm"]) for e in cad_e]
            for m in cad_m
        ],
        dtype=bool,
    )
    percent = np.where(allowed, percent, np.nan)
    if np.isnan(percent).all():
        return _final(fig)

    areas_m = [meta.loc[c, "ÁreaNorm"] for c in cad_m]
    areas_e = [meta.loc[c, "ÁreaNorm"] for c in cad_e]

    m_scores: list[float] = []
    for i, area_m in enumerate(areas_m):
        mask_cols = [area_e == area_m for area_e in areas_e]
        vals = percent[i, mask_cols]
        with np.errstate(invalid="ignore"):
            score = np.nanmean(vals) if np.any(mask_cols) else np.nan
        m_scores.append(-1e9 if np.isnan(score) else float(score))

    e_scores: list[float] = []
    for j, area_e in enumerate(areas_e):
        mask_rows = [area_m == area_e for area_m in areas_m]
        vals = percent[mask_rows, j]
        with np.errstate(invalid="ignore"):
            score = np.nanmean(vals) if np.any(mask_rows) else np.nan
        e_scores.append(-1e9 if np.isnan(score) else float(score))

    order_m = sorted(
        range(len(cad_m)),
        key=lambda i: (
            _akey(areas_m[i]),
            -m_scores[i],
            str(meta.loc[cad_m[i], "Nome"]).lower(),
            str(cad_m[i]),
        ),
    )
    order_e = sorted(
        range(len(cad_e)),
        key=lambda j: (
            _akey(areas_e[j]),
            -e_scores[j],
            str(meta.loc[cad_e[j], "Nome"]).lower(),
            str(cad_e[j]),
        ),
    )

    cad_m = [cad_m[i] for i in order_m]
    cad_e = [cad_e[j] for j in order_e]
    percent = percent[np.ix_(order_m, order_e)]

    def _abbr(nome: object) -> str:
        partes = str(nome).split()
        if not partes:
            return ""
        return " ".join([partes[0].capitalize()] + [p[0].upper() + "." for p in partes[1:]])

    y_labels = [
        f"{_abbr(meta.loc[c, 'Nome'])} "
        f"<span style='font-size:10px;opacity:.85'><b>[{meta.loc[c, 'Cargo']}]</b></span> "
        f"<span style='font-size:10px;opacity:.85'><b>- {tenure.get(str(c), '—')}</b></span>"
        for c in cad_m
    ]

    x_labels = [
        f"{_abbr(meta.loc[c, 'Nome'])} "
        f"<span style='font-size:10px;opacity:.85'><b>[{meta.loc[c, 'Cargo']}]</b></span> "
        f"<span style='font-size:10px;opacity:.85'><b>- {tenure.get(str(c), '—')}</b></span>"
        f"<br>({str(meta.loc[c, 'ÁreaNorm'])})"
        for c in cad_e
    ]

    y_full = [f"{str(meta.loc[c, 'Nome']).title()} ({c})" for c in cad_m]
    x_full = [f"{str(meta.loc[c, 'Nome']).title()} ({c})" for c in cad_e]
    customdata = [[(xe, ye) for xe in x_full] for ye in y_full]

    colors = [
        [0.00, "#af3333"],
        [0.35, "#fc9898"],
        [0.35, "#ffef09"],
        [0.60, "#fff9a9"],
        [0.60, "#9effd0"],
        [1.00, "#267951"],
    ]
    text = np.vectorize(
        lambda v: "" if (v is None or (isinstance(v, float) and np.isnan(v))) else f"{v:.1f}%"
    )(percent)

    hover_title = (
        "Encontros"
        if validar_mesma_planta and ("Planta" in dfp.columns)
        else "Encontros (co-presença)"
    )

    fig = go.Figure(
        data=go.Heatmap(
            z=percent,
            x=x_labels,
            y=y_labels,
            customdata=customdata,
            colorscale=colors,
            zmin=0,
            zmax=100,
            text=text,
            texttemplate="%{text}",
            hovertemplate=(
                "<b>%{customdata[1]}</b> × <b>%{customdata[0]}</b><br>"
                f"{hover_title}: %{{z:.1f}}%<extra></extra>"
            ),
            showscale=False,
            hoverongaps=False,
            hoverlabel=dict(bgcolor="white", font=dict(color="black")),
        )
    )

    linhas = max(len(y_labels), 1)
    altura = max(460, 40 + 23 * max(linhas, 10))
    fig.update_layout(
        title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
        xaxis_title="",
        yaxis_title="",
        height=altura,
        margin=dict(l=200, r=40, t=70, b=150),
    )
    fig.update_xaxes(tickangle=-45, autorange="reversed", automargin=True)
    fig.update_yaxes(automargin=True)
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
            title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
            height=420,
            font={"family": "Segoe UI"},
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
        title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
        showlegend=False,
        height=max(460, 420),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=90, r=90, t=70, b=60),
        font=dict(family="Segoe UI"),
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

    def _final(_fig: go.Figure) -> go.Figure:
        _fig.update_layout(
            title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
            height=420,
        )
        return _fig

    if df_full is None or df_full.empty:
        return _final(fig)

    dfp = df_full.copy()

    for col in ["Cadastro", "Cargo", "Nome", "Planta", "Área", "Departamento", "Setor"]:
        if col in dfp.columns:
            dfp[col] = dfp[col].map(_safe_hashable)
    if "Cadastro" in dfp.columns:
        dfp["Cadastro"] = dfp["Cadastro"].astype(str)
    if "Cargo" in dfp.columns:
        dfp["Cargo"] = dfp["Cargo"].astype(str)

    dfp["Data"] = pd.to_datetime(dfp["Data"], errors="coerce")
    dfp = dfp.dropna(subset=["Data"])
    if dfp.empty:
        return _final(fig)

    area_col = "Área" if "Área" in dfp.columns else None

    df_exec = dfp[dfp["Cargo"].astype(str).eq("E")].copy()
    if df_exec.empty:
        return _final(fig)

    days = pd.date_range(
        dfp["Data"].min().normalize(),
        dfp["Data"].max().normalize(),
        freq="D",
    )

    pres = (
        df_exec.groupby(["Data", "Cadastro"])["Contagem Presença"]
        .max()
        .unstack("Cadastro")
        .reindex(days)
        .fillna(0)
    )

    meta_src = df_exec.sort_values("Data").drop_duplicates("Cadastro", keep="last")
    if area_col:
        meta = (
            meta_src[["Cadastro", "Nome", "Cargo", area_col]]
            .set_index("Cadastro")
            .rename(columns={area_col: "ÁreaNorm"})
        )
    else:
        meta = meta_src[["Cadastro", "Nome", "Cargo"]].set_index("Cadastro")
        meta["ÁreaNorm"] = ""

    adm_cache, dem_cache = carregar_adm_dem_cache()
    first_seen_cache = _carregar_primeira_data_cache()
    ref_dt = pd.Timestamp.today().normalize()
    tenure: dict[str, str] = {}
    for cad in meta.index:
        cid = str(cad)
        adm_ts = adm_cache.get(cid, None)
        dem_ts = dem_cache.get(cid, None)
        if pd.isna(adm_ts) or adm_ts is None:
            adm_ts = first_seen_cache.get(cid, None)
        if pd.isna(adm_ts) or adm_ts is None:
            datas_cad = pd.to_datetime(
                df_exec.loc[df_exec["Cadastro"].astype(str) == cid, "Data"],
                errors="coerce",
            ).dropna()
            adm_ts = datas_cad.min() if not datas_cad.empty else None
        tenure[cid] = tempo_de_casa_str(adm_ts, ref=ref_dt, dem_ts=dem_ts)

    def _tok(texto: object) -> list[str]:
        return [t.strip() for t in str(texto).replace("/", "-").split("-") if t.strip()]

    def _akey(area: object) -> tuple[int, tuple[str, ...]]:
        tokens = _tok(area)
        return (len(tokens), tuple(tokens))

    cads = sorted(
        meta.index,
        key=lambda c: (
            _akey(meta.loc[c, "ÁreaNorm"]),
            str(meta.loc[c, "Nome"]).lower(),
            str(c),
        ),
    )
    if not cads:
        return _final(fig)

    if validar_mesma_planta and ("Planta" in df_exec.columns):
        df_day = df_exec[["Data", "Cadastro", "Planta"]].copy()
        df_day["Data"] = pd.to_datetime(df_day["Data"], errors="coerce").dt.normalize()
        df_day = df_day.dropna(subset=["Data", "Cadastro"])

        n_exec = len(cads)
        encontros_same = np.zeros((n_exec, n_exec), dtype=float)
        dias_pres = np.zeros((n_exec,), dtype=float)

        for _, g in df_day.groupby("Data"):
            g = g.sort_values("Cadastro").drop_duplicates(subset=["Cadastro"], keep="last")
            serie = g.set_index("Cadastro")["Planta"]
            plantas = serie.reindex(cads)
            sets_list = [_normalizar_planta_cell(val) for val in plantas.tolist()]
            pres_mask = np.array([len(st) > 0 for st in sets_list], dtype=bool)
            same = np.array(
                [
                    [
                        len(sets_list[i]) > 0
                        and len(sets_list[j]) > 0
                        and not sets_list[i].isdisjoint(sets_list[j])
                        for j in range(n_exec)
                    ]
                    for i in range(n_exec)
                ],
                dtype=bool,
            )
            valid = same & pres_mask[:, None] & pres_mask[None, :]
            encontros_same += valid.astype(float)
            dias_pres += pres_mask.astype(float)

        denom = dias_pres[:, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            percent = np.divide(
                encontros_same,
                denom,
                out=np.full_like(encontros_same, np.nan, dtype=float),
                where=(denom > 0),
            ) * 100.0
    else:
        arr = pres.reindex(columns=cads).fillna(0).to_numpy(dtype=float)
        encontros = arr.T @ arr
        denom = arr.sum(axis=0)[:, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            percent = np.divide(
                encontros,
                denom,
                out=np.full_like(encontros, np.nan, dtype=float),
                where=(denom > 0),
            ) * 100.0

    np.fill_diagonal(percent, np.nan)

    areas = [meta.loc[c, "ÁreaNorm"] for c in cads]
    e_scores: list[float] = []
    for j in range(len(cads)):
        col = percent[:, j].astype(float).copy()
        col[j] = np.nan
        score = np.nanmean(col) if np.any(~np.isnan(col)) else np.nan
        e_scores.append(-1e9 if np.isnan(score) else float(score))

    order = sorted(
        range(len(cads)),
        key=lambda j: (
            _akey(areas[j]),
            -e_scores[j],
            str(meta.loc[cads[j], "Nome"]).lower(),
            str(cads[j]),
        ),
    )
    cads = [cads[j] for j in order]
    percent = percent[np.ix_(order, order)]

    def _abbr(nome: object) -> str:
        partes = str(nome).split()
        if not partes:
            return ""
        return " ".join([partes[0].capitalize()] + [p[0].upper() + "." for p in partes[1:]])

    x_labels = [
        f"{_abbr(meta.loc[c, 'Nome'])} "
        f"<span style='font-size:10px;opacity:.85'><b>[{meta.loc[c, 'Cargo']}]</b></span> "
        f"<span style='font-size:10px;opacity:.85'><b>- {tenure.get(str(c), '—')}</b></span>"
        f"<br>({str(meta.loc[c, 'ÁreaNorm'])})"
        for c in cads
    ]
    y_labels = [
        f"{_abbr(meta.loc[c, 'Nome'])} "
        f"<span style='font-size:10px;opacity:.85'><b>[{meta.loc[c, 'Cargo']}]</b></span> "
        f"<span style='font-size:10px;opacity:.85'><b>- {tenure.get(str(c), '—')}</b></span>"
        for c in cads
    ]

    x_full = [f"{str(meta.loc[c, 'Nome']).title()} ({c})" for c in cads]
    y_full = [f"{str(meta.loc[c, 'Nome']).title()} ({c})" for c in cads]
    custom = [[(x_full[x], y_full[y]) for x in range(len(cads))] for y in range(len(cads))]

    colors = [
        [0.00, "#af3333"],
        [0.35, "#fc9898"],
        [0.35, "#ffef09"],
        [0.60, "#fff9a9"],
        [0.60, "#9effd0"],
        [1.00, "#267951"],
    ]
    text = np.vectorize(
        lambda v: "" if (v is None or (isinstance(v, float) and np.isnan(v))) else f"{v:.1f}%"
    )(percent)

    hover_title = (
        "Encontros"
        if validar_mesma_planta and ("Planta" in df_exec.columns)
        else "Encontros (co-presença)"
    )

    fig = go.Figure(
        data=go.Heatmap(
            z=percent,
            x=x_labels,
            y=y_labels,
            customdata=custom,
            colorscale=colors,
            zmin=0,
            zmax=100,
            text=text,
            texttemplate="%{text}",
            hovertemplate=(
                "<b>%{customdata[1]}</b> × <b>%{customdata[0]}</b><br>"
                f"{hover_title}: %{{z:.1f}}%<extra></extra>"
            ),
            showscale=False,
            hoverongaps=False,
            hoverlabel=dict(bgcolor="white", font=dict(color="black")),
        )
    )

    linhas = max(len(y_labels), 1)
    altura = max(460, 40 + 22 * max(linhas, 10))
    fig.update_layout(
        title={"text": titulo, "font": {"family": "Segoe UI", "size": 22}},
        xaxis_title="",
        yaxis_title="",
        height=altura,
        margin=dict(l=200, r=40, t=70, b=150),
    )
    fig.update_xaxes(tickangle=-45, automargin=True, autorange="reversed")
    fig.update_yaxes(autorange="reversed", automargin=True)
    return fig




