from pathlib import Path

import duckdb
import matplotlib.dates as mdates
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FuncFormatter


SCRIPT_DIR = Path(__file__).resolve().parent
BASE = SCRIPT_DIR / "base" / "parquet" / "df_ronda.parquet"
OUT_DIR = SCRIPT_DIR / "Ocorrências"

TOP_N = 10
PERIOD_START = pd.Timestamp("2024-01-01")
PERIOD_END = pd.Timestamp("2026-04-01")
CATEGORY_FOLDERS = {
    "H": "Horistas",
    "M": "Mensalistas",
    "T": "Terceiros",
}
AREAS_FOLDER = "Áreas"
MIN_LINE_GAP_MIN = 30

# Termos que indicam home office/remoto — qualquer ocorrência nesses campos exclui o registro
# do conjunto suspeito (a pessoa pode legitimamente bater ponto fora da fábrica nesses casos).
HOME_OFFICE_TERMS = ("HOME", "OFFICE", "REMOT", "TELE")

# Valores do campo "tipo" que representam o registro de ponto manual relevante.
# Outros tipos (refeitório, acesso, etc.) não devem entrar na análise.
PONTO_TIPO_VALUES = ("1", "PONTO")

# Paleta — laranja é o ponto manual posterior à saída física;
# magenta é o ponto manual anterior à entrada física (novo).
COLOR_AFTER_EXIT = "#F28C28"
COLOR_AFTER_EXIT_EDGE = "#9A4F00"
COLOR_BEFORE_ENTRY = "#B23A8C"
COLOR_BEFORE_ENTRY_EDGE = "#5A1C45"
COLOR_PORTARIA = "#c83b32"
COLOR_LINE = "#111111"
REPORT_BG = "#f4f8fb"
REPORT_TEXT = "#142235"
REPORT_MUTED = "#5b7088"
REPORT_GRID = "#d5e5ee"
REPORT_BLUE = "#1764a5"
REPORT_GRAY = "#a8b4bf"
REPORT_AMBER = "#b36b00"
COLOR_MANUAL_POINT = REPORT_BLUE

# Tratamento de 3º turno/turno noturno:
# quando a pessoa entra em um dia e sai no dia seguinte, o ponto manual da
# madrugada/noite pode ser um ponto normal dentro da fábrica. O script só remove
# a suspeita quando existem marcações físicas reais dos dois lados do intervalo.
OVERNIGHT_SHIFT_LABEL = "turno noturno"


def hora_to_minutes(value):
    if pd.isna(value):
        return np.nan
    if isinstance(value, pd.Timedelta):
        parts = value.components
        return parts.hours * 60 + parts.minutes + parts.seconds / 60
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value.hour * 60 + value.minute + getattr(value, "second", 0) / 60
    try:
        parts = str(value).split(":")
        return int(parts[0]) * 60 + int(parts[1]) + (
            int(parts[2]) / 60 if len(parts) > 2 else 0
        )
    except Exception:
        return np.nan


def minutes_label(minutes):
    if pd.isna(minutes):
        return ""
    value = int(round(float(minutes)))
    return f"{value // 60:02d}:{value % 60:02d}"


def hours_label(hours):
    if pd.isna(hours):
        return "0min"
    sign = "-" if hours < 0 else ""
    minutes = int(round(abs(float(hours)) * 60))
    return duration_label(minutes, sign=sign)


def duration_label(minutes, sign=""):
    if pd.isna(minutes):
        return "-"
    value = abs(int(round(float(minutes))))
    hours, mins = divmod(value, 60)
    if hours and mins:
        return f"{sign}{hours}h {mins}min"
    if hours:
        return f"{sign}{hours}h"
    return f"{sign}{mins}min"


def safe_filename(value, fallback="sem_nome"):
    clean = "".join(
        ch if ch.isalnum() or ch in (" ", "-", "_", ".", "*") else "_"
        for ch in str(value)
    ).strip()
    clean = clean.replace("*", "x").replace(" ", "_")
    return clean or fallback


def contains_any_term(series, terms=HOME_OFFICE_TERMS):
    text = series.fillna("").astype(str).str.upper()
    mask = pd.Series(False, index=series.index)
    for term in terms:
        mask = mask | text.str.contains(term, na=False, regex=False)
    return mask


def yfmt(value, pos=None):
    return minutes_label(value)


def wrap_text(ax, text, x, y, width_chars=38, line_gap=0.045, **kwargs):
    words = text.split()
    line = ""
    for word in words:
        test = (line + " " + word).strip()
        if len(test) > width_chars and line:
            ax.text(x, y, line, transform=ax.transAxes, **kwargs)
            y -= line_gap
            line = word
        else:
            line = test
    if line:
        ax.text(x, y, line, transform=ax.transAxes, **kwargs)
        y -= line_gap
    return y


def gaussian_smooth_line(x_values, y_values, points=240, bandwidth_days=42):
    if len(x_values) < 2:
        return x_values, y_values
    x_grid = np.linspace(float(np.min(x_values)), float(np.max(x_values)), points)
    distances = (x_values[:, None] - x_grid[None, :]) / float(bandwidth_days)
    weights = np.exp(-0.5 * distances**2)
    smooth = (weights * y_values[:, None]).sum(axis=0) / weights.sum(axis=0)
    return x_grid, smooth


def get_top_manual_people():
    if not BASE.exists():
        raise FileNotFoundError(f"Base consolidada nao encontrada: {BASE}")

    con = duckdb.connect(database=":memory:")
    try:
        con.execute("PRAGMA threads=4")
        query = f"""
            SELECT
              cadastro,
              any_value(nome) AS nome,
              any_value(cargo) AS cargo,
              COUNT(*) AS registros_manuais_brutos,
              COUNT(DISTINCT (
                CAST(data AS VARCHAR) || '|' ||
                CAST(hora AS VARCHAR) || '|' ||
                coalesce(CAST(dir AS VARCHAR), '') || '|' ||
                coalesce(CAST(coletor AS VARCHAR), '') || '|' ||
                coalesce(CAST(planta AS VARCHAR), '') || '|' ||
                coalesce(CAST(descricao_coletor AS VARCHAR), '')
              )) AS registros_manuais_distintos,
              COUNT(DISTINCT CAST(data AS DATE)) AS dias_com_manual,
              MIN(CAST(data AS DATE)) AS primeira_data_manual,
              MAX(CAST(data AS DATE)) AS ultima_data_manual
            FROM read_parquet('{BASE.as_posix()}')
            WHERE "Manual" = 'Sim'
            GROUP BY cadastro
            ORDER BY registros_manuais_brutos DESC, registros_manuais_distintos DESC
            LIMIT {TOP_N}
        """
        return con.execute(query).fetchdf()
    finally:
        con.close()


def load_person(cadastro):
    cols = [
        "cadastro",
        "nome",
        "data",
        "hora",
        "dir",
        "tipo",
        "acesso",
        "descricao_coletor",
        "uso_acesso",
        "planta",
        "coletor",
        "cargo",
        "area",
        "departamento",
        "Manual",
    ]
    df = pq.read_table(str(BASE), columns=cols, filters=[("cadastro", "==", str(cadastro))]).to_pandas()
    if df.empty:
        raise RuntimeError(f"Nenhum registro encontrado para a chapa {cadastro}.")

    df["data_corrigida"] = pd.to_datetime(df["data"], errors="coerce").dt.normalize()
    df["hora_min"] = df["hora"].map(hora_to_minutes)
    df = df.dropna(subset=["data_corrigida", "hora_min"]).copy()
    df["data_hora"] = df["data_corrigida"] + pd.to_timedelta(df["hora_min"], unit="m")
    df = df[(df["data_corrigida"] >= PERIOD_START) & (df["data_corrigida"] <= PERIOD_END)].copy()
    if df.empty:
        raise RuntimeError(f"Sem registros no periodo para a chapa {cadastro}.")

    df["manual_norm"] = df["Manual"].astype(str).str.strip().str.upper()
    df["dir_norm"] = df["dir"].astype(str).str.strip().str.upper()
    df["tipo_norm"] = df["tipo"].fillna("").astype(str).str.strip().str.upper()
    df["planta_norm"] = df["planta"].astype(str).str.strip()
    df["desc_norm"] = df["descricao_coletor"].fillna("").astype(str).str.upper()
    df["uso_norm"] = df["uso_acesso"].fillna("").astype(str).str.upper()
    df["coletor_norm"] = df["coletor"].fillna("").astype(str).str.upper()
    df["acesso_norm"] = df["acesso"].fillna("").astype(str).str.upper()
    df["home_office_flag"] = (
        contains_any_term(df["desc_norm"])
        | contains_any_term(df["uso_norm"])
        | contains_any_term(df["coletor_norm"])
        | contains_any_term(df["acesso_norm"])
    )
    return df


def _daily_anchor(real_events, port_only_mask, pick="last"):
    """Calcula a âncora diária (entrada ou saída física) por pessoa.

    Regra: preferir o registro PORT do dia (porta da fábrica). Se não houver PORT,
    cai no melhor registro físico do dia (`dir`=S/E não manual e fora da planta 999).
    `pick="last"` retorna o último do dia (usado para saída);
    `pick="first"` retorna o primeiro do dia (usado para entrada).
    """
    if real_events.empty:
        return real_events.iloc[0:0].copy()

    take = "head" if pick == "first" else "tail"
    sort_order = ["data_corrigida", "hora_min"]

    port_events = real_events[port_only_mask].sort_values(sort_order)
    daily = getattr(port_events.groupby("data_corrigida", as_index=False), take)(1).copy()

    # Dias sem PORT caem para qualquer registro físico daquele dia (fallback).
    fallback_days = set(real_events["data_corrigida"]) - set(daily["data_corrigida"])
    if fallback_days:
        fallback = real_events[real_events["data_corrigida"].isin(fallback_days)].sort_values(sort_order)
        fallback_daily = getattr(fallback.groupby("data_corrigida", as_index=False), take)(1).copy()
        daily = pd.concat([daily, fallback_daily], ignore_index=True)

    return daily.sort_values("data_corrigida").reset_index(drop=True)


def _split_manual_outside_daily(manual_with_anchors):
    """Classifica ponto manual fora da fábrica preservando a lógica diária.

    Dia normal: entrada <= saída, então fora da fábrica é antes da primeira
    entrada ou depois da última saída.

    Dia de turno noturno/virado: entrada > saída. Nesse caso a pessoa ficou
    dentro da fábrica de `entrada -> 24:00` e de `00:00 -> saída`; por isso só
    o intervalo `saída -> entrada` é considerado fora da fábrica. Para não
    contar o mesmo ponto duas vezes, o registro é classificado pelo lado mais
    próximo: após saída ou antes da entrada.
    """
    if manual_with_anchors.empty:
        return manual_with_anchors.copy(), manual_with_anchors.copy()

    data = manual_with_anchors.copy()
    has_exit = data["saida_real_min"].notna()
    has_entry = data["entrada_real_min"].notna()
    has_both = has_exit & has_entry
    overnight = has_both & (data["entrada_real_min"] > data["saida_real_min"])
    regular_day = has_both & ~overnight

    # Dias com apenas uma âncora continuam sendo tratados de forma conservadora:
    # se só existe saída, mede pós-saída; se só existe entrada, mede pré-entrada.
    after_regular = (regular_day | (has_exit & ~has_entry)) & (
        data["hora_min"] > data["saida_real_min"]
    )
    before_regular = (regular_day | (has_entry & ~has_exit)) & (
        data["hora_min"] < data["entrada_real_min"]
    )

    # Em turno virado, o ponto só é suspeito no "miolo" fora da fábrica:
    # depois da saída da manhã e antes da próxima entrada da noite.
    overnight_gap = (
        overnight
        & (data["hora_min"] > data["saida_real_min"])
        & (data["hora_min"] < data["entrada_real_min"])
    )
    dist_after = data["hora_min"] - data["saida_real_min"]
    dist_before = data["entrada_real_min"] - data["hora_min"]
    overnight_after = overnight_gap & (dist_after <= dist_before)
    overnight_before = overnight_gap & (dist_before < dist_after)

    manual_after_exit = data[after_regular | overnight_after].copy()
    manual_after_exit["minutos_apos_saida"] = (
        manual_after_exit["hora_min"] - manual_after_exit["saida_real_min"]
    )

    manual_before_entry = data[before_regular | overnight_before].copy()
    manual_before_entry["minutos_antes_entrada"] = (
        manual_before_entry["entrada_real_min"] - manual_before_entry["hora_min"]
    )

    return manual_after_exit, manual_before_entry


def prepare_person_analysis(df, manual_cargo=None):
    """Prepara o conjunto analítico de uma pessoa.

    Retorna registros físicos (entrada/saída), pontos manuais brutos e dois conjuntos
    de "ponto fora da fábrica":
      - `manual_after_exit`: ponto manual depois da última saída física do dia
      - `manual_before_entry`: ponto manual antes da primeira entrada física do dia
    """
    period_all = df.copy()

    # Pontos manuais candidatos: Manual=Sim, tipo=Ponto e fora de home office.
    manual_raw = period_all[
        period_all["manual_norm"].eq("SIM")
        & period_all["tipo_norm"].isin(PONTO_TIPO_VALUES)
        & ~period_all["home_office_flag"]
    ].copy()
    if manual_cargo:
        manual_raw = manual_raw[
            manual_raw["cargo"].astype(str).str.strip().str.upper().eq(str(manual_cargo).upper())
        ].copy()
    manual_distinct = manual_raw.drop_duplicates(
        subset=[
            "data_corrigida",
            "hora_min",
            "dir_norm",
            "coletor",
            "planta_norm",
            "desc_norm",
            "tipo",
            "acesso",
        ]
    )

    # Eventos físicos reais (não manuais e fora da planta 999, que é digital).
    real = period_all[
        ~period_all["manual_norm"].eq("SIM") & ~period_all["planta_norm"].eq("999")
    ].copy()
    real_exits = real[real["dir_norm"].eq("S")]
    real_entries = real[real["dir_norm"].eq("E")]

    # Âncoras físicas diárias. PORT é a referência preferida (porta principal da fábrica).
    daily_exit = _daily_anchor(
        real_exits, real_exits["desc_norm"].str.contains("PORT", na=False), pick="last"
    )
    daily_entry = _daily_anchor(
        real_entries, real_entries["desc_norm"].str.contains("PORT", na=False), pick="first"
    )

    if daily_exit.empty and daily_entry.empty:
        raise RuntimeError("Sem entradas/saidas fisicas no periodo.")

    daily_exit = daily_exit.assign(saida_real_min=daily_exit["hora_min"]) if not daily_exit.empty else daily_exit
    daily_entry = daily_entry.assign(entrada_real_min=daily_entry["hora_min"]) if not daily_entry.empty else daily_entry

    # Junta cada ponto manual com a saída e a entrada física do mesmo dia.
    manual_with_anchors = manual_raw.copy()
    if not daily_exit.empty:
        manual_with_anchors = manual_with_anchors.merge(
            daily_exit[["data_corrigida", "saida_real_min"]], on="data_corrigida", how="left"
        )
    else:
        manual_with_anchors["saida_real_min"] = np.nan
    if not daily_entry.empty:
        manual_with_anchors = manual_with_anchors.merge(
            daily_entry[["data_corrigida", "entrada_real_min"]], on="data_corrigida", how="left"
        )
    else:
        manual_with_anchors["entrada_real_min"] = np.nan

    # Classifica o ponto fora da fábrica sem assumir que o manual é entrada/saída.
    # O ajuste de turno noturno evita marcar como suspeito um ponto feito durante
    # a jornada que atravessa a meia-noite.
    manual_after_exit, manual_before_entry = _split_manual_outside_daily(manual_with_anchors)

    # Agregação diária: para cada dia, qual a "inflação" máxima de serviço (lado entrada + lado saída).
    daily_suspicious = _build_daily_suspicious(manual_after_exit, manual_before_entry)

    horas_apos = float(manual_after_exit["minutos_apos_saida"].sum() / 60.0) if len(manual_after_exit) else 0.0
    horas_antes = float(manual_before_entry["minutos_antes_entrada"].sum() / 60.0) if len(manual_before_entry) else 0.0

    stats = {
        "registros_manuais_brutos": int(len(manual_raw)),
        "registros_manuais_distintos": int(len(manual_distinct)),
        "dias_com_manual": int(manual_raw["data_corrigida"].nunique()),
        "dias_com_saida_real": int(daily_exit["data_corrigida"].nunique()) if not daily_exit.empty else 0,
        "dias_com_entrada_real": int(daily_entry["data_corrigida"].nunique()) if not daily_entry.empty else 0,
        "ocorrencias_apos_saida": int(len(manual_after_exit)),
        "ocorrencias_antes_entrada": int(len(manual_before_entry)),
        "ocorrencias_fora_fabrica": int(len(manual_after_exit) + len(manual_before_entry)),
        "dias_com_manual_apos_saida": int(manual_after_exit["data_corrigida"].nunique()),
        "dias_com_manual_antes_entrada": int(manual_before_entry["data_corrigida"].nunique()),
        "horas_apos_saida": horas_apos,
        "horas_antes_entrada": horas_antes,
        "horas_totais_manipuladas": horas_apos + horas_antes,
        "diferenca_horas_servico_reais": float(daily_suspicious["diferenca_min"].sum() / 60.0)
        if not daily_suspicious.empty
        else 0.0,
    }
    return period_all, manual_distinct, daily_exit, daily_entry, manual_after_exit, manual_before_entry, daily_suspicious, stats


def _build_daily_suspicious(manual_after_exit, manual_before_entry):
    """Soma, por dia, o maior ponto manual fora da fábrica de cada lado.

    A "diferença de serviço real" representa quanto tempo a pessoa "inflou" no dia
    além do físico. Cada lado (antes/depois) contribui com seu maior desvio.
    """
    parts = []
    if not manual_after_exit.empty:
        parts.append(
            manual_after_exit.groupby("data_corrigida", as_index=False)["minutos_apos_saida"]
            .max()
            .rename(columns={"minutos_apos_saida": "net_apos"})
        )
    if not manual_before_entry.empty:
        parts.append(
            manual_before_entry.groupby("data_corrigida", as_index=False)["minutos_antes_entrada"]
            .max()
            .rename(columns={"minutos_antes_entrada": "net_antes"})
        )
    if not parts:
        return pd.DataFrame(columns=["data_corrigida", "net_apos", "net_antes", "diferenca_min"])
    merged = parts[0]
    for extra in parts[1:]:
        merged = merged.merge(extra, on="data_corrigida", how="outer")
    if "net_apos" not in merged:
        merged["net_apos"] = 0.0
    if "net_antes" not in merged:
        merged["net_antes"] = 0.0
    merged[["net_apos", "net_antes"]] = merged[["net_apos", "net_antes"]].fillna(0.0)
    merged["diferenca_min"] = merged["net_apos"] + merged["net_antes"]
    return merged


def build_manual_cases(manual_after_exit, manual_before_entry):
    """Une os pontos manuais suspeitos em uma tabela simples para PDF.

    Cada linha representa um ponto manual e a referência física usada para
    validar a suspeita. A linha preta pontilhada no gráfico é desenhada só
    quando a distância entre o ponto e a portaria for de pelo menos 30 minutos.
    """
    parts = []
    if not manual_after_exit.empty:
        after = manual_after_exit.copy()
        after["tipo_ocorrencia"] = "Após saída"
        after["referencia_min"] = after["saida_real_min"]
        after["referencia_label"] = "Saída física"
        after["minutos_fora"] = after["minutos_apos_saida"]
        parts.append(after)
    if not manual_before_entry.empty:
        before = manual_before_entry.copy()
        before["tipo_ocorrencia"] = "Antes entrada"
        before["referencia_min"] = before["entrada_real_min"]
        before["referencia_label"] = "Entrada física"
        before["minutos_fora"] = before["minutos_antes_entrada"]
        parts.append(before)
    if not parts:
        return pd.DataFrame(
            columns=[
                "data_corrigida",
                "hora_min",
                "referencia_min",
                "minutos_fora",
                "tipo_ocorrencia",
                "referencia_label",
                "manual_dt",
                "referencia_dt",
            ]
        )
    cases = pd.concat(parts, ignore_index=True, sort=False)
    cases = cases.dropna(subset=["data_corrigida", "hora_min", "referencia_min", "minutos_fora"]).copy()
    cases["manual_dt"] = cases["data_corrigida"] + pd.to_timedelta(cases["hora_min"], unit="m")
    cases["referencia_dt"] = cases["data_corrigida"] + pd.to_timedelta(cases["referencia_min"], unit="m")
    cases["linha_pdf"] = cases["minutos_fora"].ge(MIN_LINE_GAP_MIN)
    return cases.sort_values(["data_corrigida", "hora_min"]).reset_index(drop=True)


def add_card(ax, title, edge="#C8E7F7"):
    ax.axis("off")
    panel = patches.FancyBboxPatch(
        (0.02, 0.03),
        0.96,
        0.94,
        boxstyle="round,pad=0.014,rounding_size=0.018",
        transform=ax.transAxes,
        linewidth=0.9,
        edgecolor=edge,
        facecolor="#FFFFFF",
    )
    ax.add_patch(panel)
    ax.text(0.08, 0.91, title, transform=ax.transAxes, fontsize=12, fontweight="bold", color="#132235", va="top")


def write_pairs(ax, pairs, y=0.80, color="#155C87"):
    for label, value in pairs:
        ax.text(0.08, y, label, transform=ax.transAxes, fontsize=8.4, color="#5B7185", va="top")
        ax.text(0.92, y, str(value), transform=ax.transAxes, fontsize=8.8, fontweight="bold", color=color, ha="right", va="top")
        y -= 0.058
    return y


def report_page_base(name, cad, subtitle, color, description):
    """Base visual inspirada nos PDFs de investigação: grafico grande + card lateral."""
    fig = plt.figure(figsize=(13.6, 9.6), facecolor=REPORT_BG)
    fig.text(0.055, 0.93, f"{name} - Cadastro {cad}", fontsize=18, fontweight="bold", color=REPORT_TEXT)
    fig.text(0.055, 0.895, subtitle, fontsize=13, color=color)
    fig.text(0.055, 0.868, description, fontsize=10, color=REPORT_MUTED)
    ax = fig.add_axes([0.055, 0.13, 0.68, 0.68])
    axc = fig.add_axes([0.77, 0.13, 0.20, 0.68])
    return fig, ax, axc


def report_card(ax, title):
    ax.set_axis_off()
    ax.add_patch(
        patches.FancyBboxPatch(
            (0.02, 0.02),
            0.96,
            0.96,
            boxstyle="round,pad=0.012,rounding_size=0.015",
            linewidth=1,
            edgecolor="#bfd9e8",
            facecolor="#ffffff",
            transform=ax.transAxes,
        )
    )
    ax.text(0.08, 0.91, title, transform=ax.transAxes, fontsize=13, fontweight="bold", color=REPORT_TEXT, va="top")


def report_pairs(ax, items, y=0.83, color=REPORT_BLUE):
    for label, value in items:
        ax.text(0.08, y, label, transform=ax.transAxes, color=REPORT_MUTED, fontsize=9.3, va="top")
        ax.text(0.92, y, str(value), transform=ax.transAxes, color=color, fontsize=9.3, fontweight="bold", ha="right", va="top")
        y -= 0.058
    return y


def report_note(ax, text, y):
    return wrap_text(
        ax,
        text,
        0.08,
        y,
        width_chars=31,
        line_gap=0.044,
        fontsize=9.2,
        color=REPORT_MUTED,
        va="top",
    )


def setup_report_time_axis(ax, values):
    clean = pd.Series(values).dropna()
    if clean.empty:
        start, end = 5 * 60, 23 * 60 + 30
    else:
        start = max(0, min(5 * 60, int(np.floor(clean.min() / 60) * 60)))
        end = min(24 * 60 - 1, max(23 * 60, int(np.ceil(clean.max() / 60) * 60)))
    ticks = np.arange(start, end + 1, 60)
    ax.set_ylim(end, start)
    ax.set_yticks(ticks)
    ax.set_yticklabels([minutes_label(v) for v in ticks])
    ax.grid(True, color=REPORT_GRID, linewidth=0.8)


def setup_report_date_axis(ax, dates):
    dates = pd.to_datetime(dates).dropna()
    if dates.empty:
        return
    start = dates.min() - pd.Timedelta(days=15)
    end = dates.max() + pd.Timedelta(days=15)
    ax.set_xlim(start, end)
    months = max(1, (end.year - start.year) * 12 + end.month - start.month)
    interval = max(1, int(np.ceil(months / 8)))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=interval))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%Y"))


def report_legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="upper left", frameon=True, facecolor="white", edgecolor=REPORT_GRID, fontsize=8.7)


def build_heatmap(daily):
    weekday_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
    daily = daily.copy()
    daily["weekday"] = daily["data_corrigida"].dt.weekday
    daily["dia_semana"] = pd.Categorical(
        daily["weekday"].map(dict(enumerate(weekday_labels))),
        categories=weekday_labels,
        ordered=True,
    )
    min_bin = max(0, int(np.floor((daily["hora_min"].min() - 30) / 30) * 30))
    max_bin = min(24 * 60, int(np.ceil((daily["hora_min"].max() + 30) / 30) * 30))
    bins = np.arange(min_bin, max_bin + 30, 30)
    labels = [f"{b // 60:02d}:{b % 60:02d}" for b in bins[:-1]]
    daily["faixa_saida"] = pd.cut(
        daily["hora_min"],
        bins=bins,
        labels=labels,
        right=False,
        include_lowest=True,
    )
    heat = (
        daily.pivot_table(
            index="faixa_saida",
            columns="dia_semana",
            values="cadastro",
            aggfunc="count",
            fill_value=0,
            observed=False,
        )
        .reindex(index=labels, columns=weekday_labels, fill_value=0)
    )
    nonzero = heat.sum(axis=1).to_numpy().nonzero()[0]
    if len(nonzero):
        heat_display = heat.iloc[max(nonzero[0] - 1, 0) : min(nonzero[-1] + 2, len(heat))]
    else:
        heat_display = heat
    return heat, heat_display, weekday_labels


def _homeoffice_exclusion_sql(prefix="r."):
    """Fragmento SQL: exclui registros marcados como home office em qualquer campo."""
    fields = ("desc_norm", "uso_norm", "coletor_norm", "acesso_norm")
    clauses = [f"contains({prefix}{f}, '{t}')" for f in fields for t in HOME_OFFICE_TERMS]
    return "NOT (" + " OR ".join(clauses) + ")"


def compute_manual_rankings():
    """Calcula ranking por categoria (Horistas/Mensalistas/Terceiros) e por pessoa.

    Critério de "ponto manual fora da fábrica":
      - tipo de registro = Ponto (não refeitório/acesso)
      - Manual = Sim
      - Sem indicação de home office em qualquer campo
      - Horário do registro está ANTES da primeira entrada física do dia, OU
        DEPOIS da última saída física do dia
      - Em turno noturno/virado (entrada física > saída física no mesmo dia),
        o intervalo dentro da fábrica cruza a meia-noite; por isso só o miolo
        entre saída e próxima entrada é considerado fora da fábrica
      - "Entrada/saída física" = registro PORT real (dir=E/S, não manual,
        planta diferente de 999). Fallback: qualquer registro físico do dia.
    """
    if not BASE.exists():
        raise FileNotFoundError(f"Base consolidada nao encontrada: {BASE}")

    homeoffice_filter = _homeoffice_exclusion_sql(prefix="r.")

    con = duckdb.connect(database=":memory:")
    try:
        con.execute("PRAGMA threads=2")
        con.execute("SET preserve_insertion_order=false")
        # Deixa o DuckDB usar disco para operações grandes. Isso reduz risco de
        # estouro de memória quando a base está aberta em outros processos.
        spill_dir = Path("C:/tmp/duckdb_spill")
        spill_dir.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{spill_dir.as_posix()}'")
        con.execute(
            f"""
            CREATE TEMP TABLE manual_outside AS
            WITH raw AS (
                SELECT
                    CAST(cadastro AS VARCHAR) AS cadastro,
                    CAST(nome AS VARCHAR) AS nome,
                    upper(trim(CAST(cargo AS VARCHAR))) AS cargo,
                    CAST(data AS DATE) AS data_ref,
                    (
                        date_part('hour', CAST(hora AS TIME)) * 60.0
                        + date_part('minute', CAST(hora AS TIME))
                        + date_part('second', CAST(hora AS TIME)) / 60.0
                    ) AS minuto_dia,
                    upper(trim(CAST("Manual" AS VARCHAR))) AS manual_norm,
                    upper(trim(CAST(dir AS VARCHAR))) AS dir_norm,
                    upper(trim(CAST(tipo AS VARCHAR))) AS tipo_norm,
                    trim(CAST(planta AS VARCHAR)) AS planta_norm,
                    upper(coalesce(CAST(descricao_coletor AS VARCHAR), '')) AS desc_norm,
                    upper(coalesce(CAST(uso_acesso AS VARCHAR), '')) AS uso_norm,
                    upper(coalesce(CAST(coletor AS VARCHAR), '')) AS coletor_norm,
                    upper(coalesce(CAST(acesso AS VARCHAR), '')) AS acesso_norm,
                    nullif(trim(CAST(area AS VARCHAR)), '') AS area_clean,
                    nullif(trim(CAST(departamento AS VARCHAR)), '') AS dept_clean
                FROM read_parquet('{BASE.as_posix()}')
                WHERE CAST(data AS DATE)
                    BETWEEN DATE '{PERIOD_START:%Y-%m-%d}' AND DATE '{PERIOD_END:%Y-%m-%d}'
            ),
            -- Área/departamento dominante por pessoa (apoia o rótulo dos relatórios).
            area_counts AS (
                SELECT cadastro, area_clean, dept_clean, count(*) AS qtd
                FROM raw
                WHERE manual_norm <> 'SIM'
                  AND area_clean IS NOT NULL
                GROUP BY cadastro, area_clean, dept_clean
            ),
            person_area AS (
                SELECT
                    cadastro,
                    area_clean AS area,
                    coalesce(dept_clean, 'Sem departamento') AS departamento
                FROM (
                    SELECT
                        *,
                        row_number() OVER (
                            PARTITION BY cadastro
                            ORDER BY qtd DESC, area_clean, dept_clean
                        ) AS rn
                    FROM area_counts
                )
                WHERE rn = 1
            ),
            -- Reduz o volume antes de cruzar com as âncoras físicas. Sem esse filtro
            -- antecipado, o DuckDB precisa comparar todos os acessos da base com o
            -- calendário diário de entrada/saída.
            manual_points AS (
                SELECT *
                FROM raw r
                WHERE r.manual_norm = 'SIM'
                  AND r.tipo_norm IN ('1', 'PONTO')
                  AND {homeoffice_filter}
            ),
            -- Saída física diária: último S do dia, preferindo PORT; fallback para qualquer S físico.
            port_exit AS (
                SELECT cadastro, data_ref, max(minuto_dia) AS ref_min
                FROM raw
                WHERE manual_norm <> 'SIM' AND planta_norm <> '999'
                  AND dir_norm = 'S' AND contains(desc_norm, 'PORT')
                GROUP BY cadastro, data_ref
            ),
            any_exit AS (
                SELECT cadastro, data_ref, max(minuto_dia) AS ref_min
                FROM raw
                WHERE manual_norm <> 'SIM' AND planta_norm <> '999' AND dir_norm = 'S'
                GROUP BY cadastro, data_ref
            ),
            daily_exit AS (
                SELECT
                    coalesce(p.cadastro, a.cadastro) AS cadastro,
                    coalesce(p.data_ref, a.data_ref) AS data_ref,
                    coalesce(p.ref_min, a.ref_min) AS ref_min
                FROM any_exit a
                FULL OUTER JOIN port_exit p
                    ON p.cadastro = a.cadastro AND p.data_ref = a.data_ref
            ),
            -- Entrada física diária: primeiro E do dia, preferindo PORT; fallback para qualquer E físico.
            port_entry AS (
                SELECT cadastro, data_ref, min(minuto_dia) AS ref_min
                FROM raw
                WHERE manual_norm <> 'SIM' AND planta_norm <> '999'
                  AND dir_norm = 'E' AND contains(desc_norm, 'PORT')
                GROUP BY cadastro, data_ref
            ),
            any_entry AS (
                SELECT cadastro, data_ref, min(minuto_dia) AS ref_min
                FROM raw
                WHERE manual_norm <> 'SIM' AND planta_norm <> '999' AND dir_norm = 'E'
                GROUP BY cadastro, data_ref
            ),
            daily_entry AS (
                SELECT
                    coalesce(p.cadastro, a.cadastro) AS cadastro,
                    coalesce(p.data_ref, a.data_ref) AS data_ref,
                    coalesce(p.ref_min, a.ref_min) AS ref_min
                FROM any_entry a
                FULL OUTER JOIN port_entry p
                    ON p.cadastro = a.cadastro AND p.data_ref = a.data_ref
            ),
            daily_anchor AS (
                SELECT
                    coalesce(s.cadastro, e.cadastro) AS cadastro,
                    coalesce(s.data_ref, e.data_ref) AS data_ref,
                    s.ref_min AS saida_min,
                    e.ref_min AS entrada_min
                FROM daily_exit s
                FULL OUTER JOIN daily_entry e
                    ON e.cadastro = s.cadastro AND e.data_ref = s.data_ref
            ),
            -- O ponto manual é um "ponto normal", não entrada/saída. A classificação
            -- compara apenas o horário do ponto com as âncoras físicas do dia.
            manual_candidates AS (
                SELECT
                    r.cadastro,
                    r.nome,
                    r.cargo,
                    r.data_ref,
                    r.minuto_dia,
                    CASE
                        -- Turno virado: entrada à noite e saída pela manhã.
                        -- O registro só é suspeito no intervalo fora da fábrica
                        -- entre a saída da manhã e a próxima entrada da noite.
                        WHEN a.saida_min IS NOT NULL
                         AND a.entrada_min IS NOT NULL
                         AND a.entrada_min > a.saida_min
                         AND r.minuto_dia > a.saida_min
                         AND r.minuto_dia < a.entrada_min
                            THEN CASE
                                WHEN r.minuto_dia - a.saida_min <= a.entrada_min - r.minuto_dia
                                    THEN 'apos_saida'
                                ELSE 'antes_entrada'
                            END
                        -- Dia normal ou dia com apenas saída física disponível.
                        WHEN a.saida_min IS NOT NULL
                         AND (a.entrada_min IS NULL OR a.entrada_min <= a.saida_min)
                         AND r.minuto_dia > a.saida_min
                            THEN 'apos_saida'
                        -- Dia normal ou dia com apenas entrada física disponível.
                        WHEN a.entrada_min IS NOT NULL
                         AND (a.saida_min IS NULL OR a.entrada_min <= a.saida_min)
                         AND r.minuto_dia < a.entrada_min
                            THEN 'antes_entrada'
                    END AS tipo_ocorrencia,
                    CASE
                        WHEN a.saida_min IS NOT NULL
                         AND a.entrada_min IS NOT NULL
                         AND a.entrada_min > a.saida_min
                         AND r.minuto_dia > a.saida_min
                         AND r.minuto_dia < a.entrada_min
                            THEN CASE
                                WHEN r.minuto_dia - a.saida_min <= a.entrada_min - r.minuto_dia
                                    THEN a.saida_min
                                ELSE a.entrada_min
                            END
                        WHEN a.saida_min IS NOT NULL
                         AND (a.entrada_min IS NULL OR a.entrada_min <= a.saida_min)
                         AND r.minuto_dia > a.saida_min
                            THEN a.saida_min
                        WHEN a.entrada_min IS NOT NULL
                         AND (a.saida_min IS NULL OR a.entrada_min <= a.saida_min)
                         AND r.minuto_dia < a.entrada_min
                            THEN a.entrada_min
                    END AS referencia_min,
                    CASE
                        WHEN a.saida_min IS NOT NULL
                         AND a.entrada_min IS NOT NULL
                         AND a.entrada_min > a.saida_min
                         AND r.minuto_dia > a.saida_min
                         AND r.minuto_dia < a.entrada_min
                            THEN least(r.minuto_dia - a.saida_min, a.entrada_min - r.minuto_dia)
                        WHEN a.saida_min IS NOT NULL
                         AND (a.entrada_min IS NULL OR a.entrada_min <= a.saida_min)
                         AND r.minuto_dia > a.saida_min
                            THEN r.minuto_dia - a.saida_min
                        WHEN a.entrada_min IS NOT NULL
                         AND (a.saida_min IS NULL OR a.entrada_min <= a.saida_min)
                         AND r.minuto_dia < a.entrada_min
                            THEN a.entrada_min - r.minuto_dia
                    END AS minutos_fora
                FROM manual_points r
                INNER JOIN daily_anchor a
                    ON a.cadastro = r.cadastro AND a.data_ref = r.data_ref
            )
            SELECT
                mc.cadastro,
                mc.nome,
                mc.cargo,
                mc.data_ref,
                mc.minuto_dia,
                mc.tipo_ocorrencia,
                mc.referencia_min,
                mc.minutos_fora,
                coalesce(pa.area, 'Sem area') AS area,
                coalesce(pa.departamento, 'Sem departamento') AS departamento
            FROM manual_candidates mc
            LEFT JOIN person_area pa ON pa.cadastro = mc.cadastro
            WHERE mc.tipo_ocorrencia IS NOT NULL
            """
        )

        # Para a "diferença de serviço real": cada dia contribui com o maior desvio
        # de cada lado (entrada + saída). Evita inflar o número se a pessoa colocou
        # vários pontos manuais no mesmo dia.
        category_query = """
            WITH daily_max AS (
                SELECT
                    cadastro, cargo, data_ref,
                    max(CASE WHEN tipo_ocorrencia = 'apos_saida'    THEN minutos_fora END) AS net_apos,
                    max(CASE WHEN tipo_ocorrencia = 'antes_entrada' THEN minutos_fora END) AS net_antes
                FROM manual_outside
                GROUP BY cadastro, cargo, data_ref
            ),
            person_net AS (
                SELECT
                    cadastro, cargo,
                    sum(coalesce(net_apos, 0) + coalesce(net_antes, 0)) / 60.0 AS diferenca_horas_servico_reais
                FROM daily_max
                GROUP BY cadastro, cargo
            )
            SELECT
                ma.cadastro,
                min(ma.nome) AS nome,
                ma.cargo,
                any_value(ma.area) AS area,
                any_value(ma.departamento) AS departamento,
                sum(CASE WHEN ma.tipo_ocorrencia = 'apos_saida'    THEN 1 ELSE 0 END) AS ocorrencias_apos_saida,
                sum(CASE WHEN ma.tipo_ocorrencia = 'antes_entrada' THEN 1 ELSE 0 END) AS ocorrencias_antes_entrada,
                count(*) AS ocorrencias_fora_fabrica,
                count(DISTINCT CASE WHEN ma.tipo_ocorrencia = 'apos_saida'    THEN ma.data_ref END) AS dias_apos_saida,
                count(DISTINCT CASE WHEN ma.tipo_ocorrencia = 'antes_entrada' THEN ma.data_ref END) AS dias_antes_entrada,
                count(DISTINCT ma.data_ref) AS dias_com_manual_fora,
                sum(CASE WHEN ma.tipo_ocorrencia = 'apos_saida'    THEN ma.minutos_fora ELSE 0 END) / 60.0 AS horas_apos_saida,
                sum(CASE WHEN ma.tipo_ocorrencia = 'antes_entrada' THEN ma.minutos_fora ELSE 0 END) / 60.0 AS horas_antes_entrada,
                sum(ma.minutos_fora) / 60.0 AS horas_totais_manipuladas,
                coalesce(any_value(pn.diferenca_horas_servico_reais), 0) AS diferenca_horas_servico_reais
            FROM manual_outside ma
            LEFT JOIN person_net pn ON pn.cadastro = ma.cadastro AND pn.cargo = ma.cargo
            GROUP BY ma.cadastro, ma.cargo
        """

        person_query = """
            WITH daily_max AS (
                SELECT
                    cadastro, data_ref,
                    max(CASE WHEN tipo_ocorrencia = 'apos_saida'    THEN minutos_fora END) AS net_apos,
                    max(CASE WHEN tipo_ocorrencia = 'antes_entrada' THEN minutos_fora END) AS net_antes
                FROM manual_outside
                GROUP BY cadastro, data_ref
            ),
            person_net AS (
                SELECT
                    cadastro,
                    sum(coalesce(net_apos, 0) + coalesce(net_antes, 0)) / 60.0 AS diferenca_horas_servico_reais
                FROM daily_max
                GROUP BY cadastro
            ),
            cargos AS (
                SELECT cadastro, string_agg(DISTINCT cargo, '/') AS cargo
                FROM manual_outside
                GROUP BY cadastro
            )
            SELECT
                ma.cadastro,
                min(ma.nome) AS nome,
                any_value(c.cargo) AS cargo,
                any_value(ma.area) AS area,
                any_value(ma.departamento) AS departamento,
                sum(CASE WHEN ma.tipo_ocorrencia = 'apos_saida'    THEN 1 ELSE 0 END) AS ocorrencias_apos_saida,
                sum(CASE WHEN ma.tipo_ocorrencia = 'antes_entrada' THEN 1 ELSE 0 END) AS ocorrencias_antes_entrada,
                count(*) AS ocorrencias_fora_fabrica,
                count(DISTINCT CASE WHEN ma.tipo_ocorrencia = 'apos_saida'    THEN ma.data_ref END) AS dias_apos_saida,
                count(DISTINCT CASE WHEN ma.tipo_ocorrencia = 'antes_entrada' THEN ma.data_ref END) AS dias_antes_entrada,
                count(DISTINCT ma.data_ref) AS dias_com_manual_fora,
                sum(CASE WHEN ma.tipo_ocorrencia = 'apos_saida'    THEN ma.minutos_fora ELSE 0 END) / 60.0 AS horas_apos_saida,
                sum(CASE WHEN ma.tipo_ocorrencia = 'antes_entrada' THEN ma.minutos_fora ELSE 0 END) / 60.0 AS horas_antes_entrada,
                sum(ma.minutos_fora) / 60.0 AS horas_totais_manipuladas,
                coalesce(any_value(pn.diferenca_horas_servico_reais), 0) AS diferenca_horas_servico_reais
            FROM manual_outside ma
            LEFT JOIN person_net pn ON pn.cadastro = ma.cadastro
            LEFT JOIN cargos c ON c.cadastro = ma.cadastro
            GROUP BY ma.cadastro
        """

        category_stats = con.execute(category_query).fetchdf()
        person_stats = con.execute(person_query).fetchdf()
    finally:
        con.close()

    def normalize(stats):
        if stats.empty:
            return stats
        stats["cadastro"] = stats["cadastro"].astype(str)
        stats["cargo"] = stats["cargo"].fillna("").astype(str).str.strip().str.upper()
        stats["area"] = stats["area"].fillna("Sem area").astype(str).str.strip()
        stats["nome"] = stats["nome"].fillna("").astype(str)
        return stats.sort_values(
            ["ocorrencias_fora_fabrica", "horas_totais_manipuladas"],
            ascending=[False, False],
        ).reset_index(drop=True)

    return normalize(category_stats), normalize(person_stats)


def make_people_ranking_pdf(table, output_dir, title, filename, subtitle=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / filename
    view = table.copy()
    if view.empty:
        return None

    columns = [
        "cadastro",
        "nome",
        "cargo",
        "area",
        "ocorrencias_antes_entrada",
        "ocorrencias_apos_saida",
        "ocorrencias_fora_fabrica",
        "dias_com_manual_fora",
        "horas_totais_manipuladas",
        "diferenca_horas_servico_reais",
    ]
    view = view[columns].copy()
    view["nome"] = view["nome"].astype(str).str.slice(0, 34)
    view["area"] = view["area"].astype(str).str.slice(0, 18)
    view["horas_totais_manipuladas"] = view["horas_totais_manipuladas"].map(hours_label)
    view["diferenca_horas_servico_reais"] = view["diferenca_horas_servico_reais"].map(hours_label)
    view.columns = [
        "Chapa",
        "Nome",
        "Cargo",
        "Area",
        "Antes entrada",
        "Apos saida",
        "Total fora",
        "Dias",
        "Horas manipuladas",
        "Dif. servico real",
    ]

    rows_per_page = 24
    with PdfPages(pdf_path) as pdf:
        for page_idx, start in enumerate(range(0, len(view), rows_per_page), start=1):
            chunk = view.iloc[start : start + rows_per_page]
            fig, ax = plt.subplots(figsize=(11.69, 8.27), dpi=180)
            ax.axis("off")
            ax.text(0.02, 0.965, title, fontsize=15.5, fontweight="bold", transform=ax.transAxes)
            note = subtitle or f"Base: {BASE}"
            ax.text(0.02, 0.925, note, fontsize=8.2, color="#5B7185", transform=ax.transAxes)
            if len(view) > rows_per_page:
                ax.text(
                    0.98,
                    0.925,
                    f"Pagina {page_idx}",
                    fontsize=8.2,
                    color="#5B7185",
                    ha="right",
                    transform=ax.transAxes,
                )
            tbl = ax.table(
                cellText=chunk.values.tolist(),
                colLabels=view.columns,
                loc="center",
                cellLoc="left",
                colLoc="left",
            )
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(6.7)
            tbl.scale(1, 1.34)
            for (row_idx, _), cell in tbl.get_celld().items():
                if row_idx == 0:
                    cell.set_facecolor("#155C87")
                    cell.set_text_props(color="white", weight="bold")
                elif row_idx % 2 == 0:
                    cell.set_facecolor("#F1F8FC")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
    return pdf_path


def make_area_summary_pdf(area_stats):
    if area_stats.empty:
        return None
    output_dir = OUT_DIR / AREAS_FOLDER
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / "00_piores_areas.pdf"
    view = area_stats.copy()
    view["horas_totais_manipuladas"] = view["horas_totais_manipuladas"].map(hours_label)
    view["diferenca_horas_servico_reais"] = view["diferenca_horas_servico_reais"].map(hours_label)
    view.columns = [
        "Area",
        "Pessoas",
        "Antes entrada",
        "Apos saida",
        "Total fora",
        "Horas manipuladas",
        "Dif. servico real",
    ]
    with PdfPages(pdf_path) as pdf:
        fig, ax = plt.subplots(figsize=(11.69, 8.27), dpi=180)
        ax.axis("off")
        ax.text(0.02, 0.96, "3 piores areas por pontos manuais fora da fabrica", fontsize=16, fontweight="bold", transform=ax.transAxes)
        ax.text(0.02, 0.92, "Ranking por quantidade bruta de pontos manuais antes da entrada ou apos a ultima saida fisica da fabrica", fontsize=8.5, color="#5B7185", transform=ax.transAxes)
        tbl = ax.table(cellText=view.values.tolist(), colLabels=view.columns, loc="center", cellLoc="left", colLoc="left")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8.2)
        tbl.scale(1, 1.65)
        for (row_idx, _), cell in tbl.get_celld().items():
            if row_idx == 0:
                cell.set_facecolor("#155C87")
                cell.set_text_props(color="white", weight="bold")
            elif row_idx % 2 == 0:
                cell.set_facecolor("#F1F8FC")
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
    return pdf_path


def make_person_pdf_pretty(row, output_dir=None):
    """Gera PDF individual no estilo dos relatorios de investigacao."""
    cad = str(row["cadastro"])
    name = str(row["nome"])
    pdf_dir = Path(output_dir) if output_dir is not None else OUT_DIR
    pdf_dir.mkdir(parents=True, exist_ok=True)

    df = load_person(cad)
    # Para auditoria, o PDF é por pessoa. Mesmo que ela apareça em rankings por
    # categoria, aqui olhamos todos os pontos manuais dela no período.
    manual_cargo = None
    (
        period_all,
        manual,
        daily_exit,
        daily_entry,
        manual_after_exit,
        manual_before_entry,
        daily_suspicious,
        stats,
    ) = prepare_person_analysis(df, manual_cargo=manual_cargo)
    manual_cases = build_manual_cases(manual_after_exit, manual_before_entry)

    plt.rcParams.update(
        {
            "figure.facecolor": REPORT_BG,
            "axes.facecolor": "#fbfdff",
            "axes.edgecolor": REPORT_GRID,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    safe_name = safe_filename(name)
    pdf_path = pdf_dir / f"{cad}_{safe_name[:42]}_validacao_manuais.pdf"
    period_label = f"{PERIOD_START:%d/%m/%Y} a {PERIOD_END:%d/%m/%Y}"
    line_cases = manual_cases[manual_cases["linha_pdf"]].copy() if not manual_cases.empty else manual_cases
    line_count = int(len(line_cases)) if not manual_cases.empty else 0
    maior_dif = manual_cases["minutos_fora"].max() if not manual_cases.empty else np.nan

    physical_parts = []
    if not daily_entry.empty:
        physical_parts.append(daily_entry.assign(portaria_tipo="Entrada fisica"))
    if not daily_exit.empty:
        physical_parts.append(daily_exit.assign(portaria_tipo="Saida fisica"))
    physical = pd.concat(physical_parts, ignore_index=True, sort=False) if physical_parts else pd.DataFrame()

    with PdfPages(pdf_path) as pdf:
        # Pagina 1 - principal, espelhada no PDF de referencia.
        fig, ax, axc = report_page_base(
            name,
            cad,
            "Portaria x ponto manual | ponto sem presenca fisica",
            REPORT_BLUE,
            f"Vermelho = portaria E/S. Azul = ponto manual suspeito. Periodo: {period_label}.",
        )
        if not physical.empty:
            ax.scatter(
                physical["data_hora"],
                physical["hora_min"],
                s=18,
                c=COLOR_PORTARIA,
                alpha=0.24,
                edgecolors="none",
                linewidths=0,
                label="Portaria E/S",
                zorder=2,
            )
        if not line_cases.empty:
            refs = (
                line_cases[["referencia_dt", "referencia_min"]]
                .dropna()
                .drop_duplicates()
                .copy()
            )
            ax.scatter(
                refs["referencia_dt"],
                refs["referencia_min"],
                s=34,
                c=COLOR_PORTARIA,
                alpha=0.9,
                edgecolors="white",
                linewidths=0.35,
                label="Portaria ligada",
                zorder=5,
            )
        if not manual_after_exit.empty:
            ax.scatter(
                manual_after_exit["data_hora"],
                manual_after_exit["hora_min"],
                s=42,
                c=COLOR_MANUAL_POINT,
                alpha=0.86,
                edgecolors="white",
                linewidths=0.35,
                label="Manual apos saida",
                zorder=4,
            )
        if not manual_before_entry.empty:
            ax.scatter(
                manual_before_entry["data_hora"],
                manual_before_entry["hora_min"],
                s=44,
                c=COLOR_MANUAL_POINT,
                marker="D",
                alpha=0.86,
                edgecolors="white",
                linewidths=0.35,
                label="Manual antes entrada",
                zorder=5,
            )
        if not line_cases.empty:
            label_added = False
            for _, case in line_cases.iterrows():
                ax.plot(
                    [case["referencia_dt"], case["manual_dt"]],
                    [case["referencia_min"], case["hora_min"]],
                    color=COLOR_LINE,
                    linestyle=":",
                    linewidth=2.2,
                    alpha=0.95,
                    label=f"Ligacao >= {MIN_LINE_GAP_MIN}min" if not label_added else None,
                    zorder=3,
                )
                label_added = True

        time_values = []
        date_values = []
        for source in (physical, manual_after_exit, manual_before_entry):
            if not source.empty:
                time_values.append(source["hora_min"])
                date_values.append(source["data_hora"])
        setup_report_time_axis(ax, pd.concat(time_values, ignore_index=True) if time_values else pd.Series(dtype=float))
        setup_report_date_axis(ax, pd.concat(date_values, ignore_index=True) if date_values else period_all["data_hora"])
        ax.set_xlabel("Data")
        ax.set_ylabel("Horario")
        report_legend(ax)

        report_card(axc, "Resumo")
        y = report_pairs(
            axc,
            [
                ("Pontos fora", stats["ocorrencias_fora_fabrica"]),
                ("Antes entrada", stats["ocorrencias_antes_entrada"]),
                ("Apos saida", stats["ocorrencias_apos_saida"]),
                ("Linhas >=30min", line_count),
                ("Maior diferenca", duration_label(maior_dif)),
                ("Horas totais", hours_label(stats["horas_totais_manipuladas"])),
                ("Dif. servico real", hours_label(stats["diferenca_horas_servico_reais"])),
            ],
            color=REPORT_BLUE,
        )
        report_note(axc, "Linha preta liga o ponto manual ate a portaria quando a diferenca e de pelo menos 30min.", y - 0.02)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        # Pagina 2 - concentracao mensal, limpa e direta.
        fig, ax, axc = report_page_base(
            name,
            cad,
            "Concentracao mensal dos pontos sem presenca",
            REPORT_BLUE,
            "Barras mostram a quantidade de pontos manuais sem presenca fisica por mes.",
        )
        if manual_cases.empty:
            ax.set_axis_off()
            ax.text(0.02, 0.78, "Sem ponto manual fora da fabrica pelos criterios atuais.", transform=ax.transAxes, color=REPORT_MUTED, fontsize=12)
        else:
            monthly = manual_cases.copy()
            monthly["mes"] = monthly["data_corrigida"].dt.to_period("M").dt.to_timestamp()
            pivot = (
                monthly.pivot_table(index="mes", columns="tipo_ocorrencia", values="minutos_fora", aggfunc="size", fill_value=0)
                .sort_index()
            )
            for col in ["Antes entrada", "Após saída"]:
                if col not in pivot:
                    pivot[col] = 0
            x = np.arange(len(pivot))
            ax.bar(x, pivot["Após saída"], color=COLOR_AFTER_EXIT, label="Apos saida")
            ax.bar(x, pivot["Antes entrada"], bottom=pivot["Após saída"], color=COLOR_BEFORE_ENTRY, label="Antes entrada")
            ax.set_xticks(x)
            ax.set_xticklabels([d.strftime("%m/%Y") for d in pivot.index], rotation=35, ha="right", fontsize=8.8)
            ax.set_ylabel("Qtd. pontos")
            ax.set_title("Meses com maior concentracao", loc="left", fontsize=13, color=REPORT_TEXT, fontweight="bold")
            ax.grid(True, axis="y", color=REPORT_GRID, linewidth=0.8)
            for spine in ax.spines.values():
                spine.set_visible(False)
            report_legend(ax)

        report_card(axc, "Resumo")
        y = report_pairs(
            axc,
            [
                ("Meses", manual_cases["data_corrigida"].dt.to_period("M").nunique() if not manual_cases.empty else 0),
                ("Pontos fora", stats["ocorrencias_fora_fabrica"]),
                ("Dias antes", stats["dias_com_manual_antes_entrada"]),
                ("Dias apos", stats["dias_com_manual_apos_saida"]),
                ("Maior diferenca", duration_label(maior_dif)),
            ],
            color=REPORT_BLUE,
        )
        report_note(axc, "Esta pagina mostra onde o volume se concentrou. Use a pagina 1 para enxergar a ligacao com a portaria.", y - 0.02)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        # Pagina 3 - heatmap antigo, refeito no mesmo estilo visual.
        fig, ax, axc = report_page_base(
            name,
            cad,
            "Distribuicao das saidas fisicas",
            REPORT_BLUE,
            "Heatmap das ultimas saidas fisicas do dia. Serve como contexto do expediente real.",
        )
        if daily_exit.empty:
            ax.set_axis_off()
            ax.text(0.02, 0.78, "Sem saidas fisicas no periodo.", transform=ax.transAxes, color=REPORT_MUTED, fontsize=12)
            heat_display = pd.DataFrame()
        else:
            heat, heat_display, weekday_labels = build_heatmap(daily_exit)
            arr = heat_display.to_numpy(dtype=float)
            cmap = LinearSegmentedColormap.from_list("manual_heat", ["#FFFFFF", "#EAF5FB", "#BFDFF1", "#6EAED1", REPORT_BLUE])
            im = ax.imshow(arr, aspect="auto", cmap=cmap, vmin=0, vmax=max(1, float(arr.max()) if arr.size else 1), origin="upper")
            ax.set_xticks(np.arange(len(weekday_labels)))
            ax.set_xticklabels(weekday_labels, fontsize=9.5, fontweight="bold")
            ax.set_yticks(np.arange(len(heat_display.index)))
            ax.set_yticklabels(list(heat_display.index), fontsize=8.3)
            ax.set_xlabel("Dia da semana")
            ax.set_title("Quantidade de dias por faixa horaria", loc="left", fontsize=13, color=REPORT_TEXT, fontweight="bold")
            ax.set_xticks(np.arange(-0.5, len(weekday_labels), 1), minor=True)
            ax.set_yticks(np.arange(-0.5, len(heat_display.index), 1), minor=True)
            ax.grid(which="minor", color=REPORT_GRID, linestyle="-", linewidth=0.8)
            ax.tick_params(which="minor", bottom=False, left=False)
            for spine in ax.spines.values():
                spine.set_visible(False)
            threshold = arr.max() * 0.55 if arr.size and arr.max() else 999
            for yy in range(arr.shape[0]):
                for xx in range(arr.shape[1]):
                    val = int(arr[yy, xx])
                    if val:
                        ax.text(xx, yy, str(val), ha="center", va="center", fontsize=8.6, fontweight="bold", color="#FFFFFF" if val >= threshold else "#1D435A")
            cbar = fig.colorbar(im, ax=ax, fraction=0.030, pad=0.025)
            cbar.outline.set_visible(False)
            cbar.ax.tick_params(labelsize=7.8, colors=REPORT_MUTED)

        report_card(axc, "Resumo")
        median_min = daily_exit["hora_min"].median() if not daily_exit.empty else np.nan
        p10 = daily_exit["hora_min"].quantile(0.10) if not daily_exit.empty else np.nan
        p90 = daily_exit["hora_min"].quantile(0.90) if not daily_exit.empty else np.nan
        y = report_pairs(
            axc,
            [
                ("Saidas fisicas", stats["dias_com_saida_real"]),
                ("Entradas fisicas", stats["dias_com_entrada_real"]),
                ("Pontos manuais", stats["registros_manuais_brutos"]),
                ("Dias com manual", stats["dias_com_manual"]),
                ("Mediana saida", minutes_label(median_min)),
                ("P10-P90 saida", f"{minutes_label(p10)}-{minutes_label(p90)}"),
            ],
            color=REPORT_BLUE,
        )
        report_note(axc, "A comparacao usa PORT como preferencia e fallback fisico quando nao ha PORT no dia.", y - 0.02)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        # Pagina 4 - grafico final de coerencia, sem tabela.
        fig, ax, axc = report_page_base(
            name,
            cad,
            "Manipulados / coerencia dos pontos",
            REPORT_AMBER,
            "Cada bolinha mostra quanto o ponto manual ficou distante da portaria de referencia.",
        )
        plot_cases = manual_cases.dropna(subset=["manual_dt", "minutos_fora"]).copy()
        if plot_cases.empty:
            ax.set_axis_off()
            ax.text(0.02, 0.78, "Sem caso prioritario pelos criterios atuais.", transform=ax.transAxes, color=REPORT_MUTED, fontsize=12)
        else:
            plot_cases = plot_cases.sort_values("manual_dt")
            above = plot_cases["linha_pdf"]
            ax.scatter(
                plot_cases.loc[~above, "manual_dt"],
                plot_cases.loc[~above, "minutos_fora"],
                s=22,
                c="#8aa6bd",
                alpha=0.55,
                edgecolors="none",
                label=f"Abaixo de {MIN_LINE_GAP_MIN}min",
            )
            ax.scatter(
                plot_cases.loc[above, "manual_dt"],
                plot_cases.loc[above, "minutos_fora"],
                s=42,
                c=COLOR_PORTARIA,
                alpha=0.88,
                edgecolors="white",
                linewidths=0.35,
                label=f"{MIN_LINE_GAP_MIN}min ou mais",
            )
            top_labels = plot_cases[above].sort_values("minutos_fora", ascending=False).head(4)
            for _, case in top_labels.iterrows():
                ax.annotate(
                    duration_label(case["minutos_fora"]),
                    (case["manual_dt"], case["minutos_fora"]),
                    textcoords="offset points",
                    xytext=(4, 5),
                    fontsize=8,
                    color=REPORT_TEXT,
                )
            ax.axhline(0, color=REPORT_GRID, linewidth=1)
            ax.axhline(MIN_LINE_GAP_MIN, color=COLOR_PORTARIA, linestyle="--", linewidth=1.3, alpha=0.8)
            ax.text(0.995, MIN_LINE_GAP_MIN, "30min", transform=ax.get_yaxis_transform(), ha="right", va="bottom", color=COLOR_PORTARIA, fontsize=8.5, fontweight="bold")
            ax.grid(True, color=REPORT_GRID, linewidth=0.8)
            setup_report_date_axis(ax, plot_cases["manual_dt"])
            ax.set_ylim(0, max(90, float(plot_cases["minutos_fora"].max()) * 1.15))
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: duration_label(value)))
            ax.set_ylabel("Ponto manual x portaria")
            ax.set_xlabel("Data")
            ax.set_title("Quanto tempo o ponto ficou fora do lastro fisico", loc="left", fontsize=13, color=REPORT_TEXT, fontweight="bold")
            report_legend(ax)

        report_card(axc, "Resumo")
        dias_linha = line_cases["data_corrigida"].nunique() if not line_cases.empty else 0
        y = report_pairs(
            axc,
            [
                ("Corte visual", f"{MIN_LINE_GAP_MIN}min"),
                ("Casos >= corte", line_count),
                ("Dias >= corte", dias_linha),
                ("Maior diferenca", duration_label(maior_dif)),
                ("Total antes", stats["ocorrencias_antes_entrada"]),
                ("Total apos", stats["ocorrencias_apos_saida"]),
            ],
            color=REPORT_AMBER,
        )
        report_note(axc, "Vermelho destaca dias de 30min ou mais. Para concluir, validar escala, justificativa e aprovacao.", y - 0.02)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    return pdf_path, stats


def make_person_pdf(row, output_dir=None):
    """Gera o PDF de validação individual (2 páginas: heatmap de saída + evolução temporal)."""
    return make_person_pdf_pretty(row, output_dir=output_dir)

    cad = str(row["cadastro"])
    name = str(row["nome"])
    pdf_dir = Path(output_dir) if output_dir is not None else OUT_DIR
    pdf_dir.mkdir(parents=True, exist_ok=True)
    df = load_person(cad)
    manual_cargo = str(row.get("cargo", "")).strip().upper()
    if manual_cargo not in CATEGORY_FOLDERS:
        manual_cargo = None
    (
        period_all,
        manual,
        daily_exit,
        daily_entry,
        manual_after_exit,
        manual_before_entry,
        daily_suspicious,
        stats,
    ) = prepare_person_analysis(df, manual_cargo=manual_cargo)
    manual_cases = build_manual_cases(manual_after_exit, manual_before_entry)

    # Heatmap continua sendo das saídas físicas — referencia o expediente "real".
    heat, heat_display, weekday_labels = build_heatmap(daily_exit)
    x_dates = mdates.date2num(daily_exit["data_corrigida"].to_numpy(dtype="datetime64[ms]"))
    y = daily_exit["hora_min"].to_numpy(dtype=float)
    slope_day, _ = np.polyfit(x_dates, y, 1) if len(daily_exit) >= 2 else (0.0, y[0])
    slope_30d = slope_day * 30
    smooth_x, smooth_y = gaussian_smooth_line(x_dates, y)

    first_window = daily_exit.head(min(20, len(daily_exit)))["hora_min"].median()
    last_window = daily_exit.tail(min(20, len(daily_exit)))["hora_min"].median()
    delta_edge = last_window - first_window

    period_label = f"{PERIOD_START:%d/%m/%Y} a {PERIOD_END:%d/%m/%Y}"
    median_min = daily_exit["hora_min"].median()
    mean_min = daily_exit["hora_min"].mean()
    p10 = daily_exit["hora_min"].quantile(0.10)
    p90 = daily_exit["hora_min"].quantile(0.90)
    mode_bucket = heat.stack().idxmax() if heat.size and heat.to_numpy().max() > 0 else ("-", "-")
    mode_count = int(heat.to_numpy().max()) if heat.size else 0
    mode_txt = (
        f"{mode_bucket[1]} as {mode_bucket[0]} ({mode_count} dias)"
        if mode_bucket != ("-", "-")
        else "Sem saidas no periodo"
    )

    # Classificação textual para o cabeçalho da página 2.
    n_apos = stats["ocorrencias_apos_saida"]
    n_antes = stats["ocorrencias_antes_entrada"]
    if n_apos and n_antes:
        classification = "ponto manual fora da fabrica (antes da entrada e apos a saida)"
    elif n_apos:
        classification = "ponto manual apos saida fisica"
    elif n_antes:
        classification = "ponto manual antes da entrada fisica"
    else:
        classification = "sem ponto manual fora da fabrica"

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titleweight": "bold",
            "axes.labelcolor": "#203348",
            "xtick.color": "#203348",
            "ytick.color": "#203348",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    bg = "#F8FBFD"
    ink = "#132235"
    muted = "#5B7185"
    grid = "#DCEEF7"
    blue = "#89CFF0"
    blue_dark = "#155C87"
    orange = COLOR_AFTER_EXIT
    magenta = COLOR_BEFORE_ENTRY
    cmap = LinearSegmentedColormap.from_list(
        "babyblue_clean",
        ["#FFFFFF", "#EDF9FF", "#CDEFFF", "#89CFF0", "#3E99C9"],
    )

    safe_name = safe_filename(name)
    pdf_path = pdf_dir / f"{cad}_{safe_name[:42]}_validacao_manuais.pdf"

    with PdfPages(pdf_path) as pdf:
        # ----- Página 1: heatmap das últimas saídas físicas -----
        fig = plt.figure(figsize=(11.69, 8.27), dpi=180, facecolor=bg)
        gs = fig.add_gridspec(2, 4, height_ratios=[0.72, 5.2], width_ratios=[1, 1, 1, 1.02], hspace=0.16, wspace=0.18)
        ax_title = fig.add_subplot(gs[0, :])
        ax_title.axis("off")
        ax_title.text(0.01, 0.82, f"{name} - Chapa {cad}", fontsize=16, fontweight="bold", color=ink, va="top")
        ax_title.text(0.01, 0.42, "Heatmap das ultimas saidas fisicas do dia", fontsize=12.5, color=blue_dark, va="top")
        ax_title.text(0.01, 0.13, f"{period_label} | Criterio: ultima saida fisica PORT com dir=S; fallback S quando nao ha PORT", fontsize=8.8, color=muted, va="top")

        ax = fig.add_subplot(gs[1, :3])
        arr = heat_display.to_numpy(dtype=float)
        im = ax.imshow(arr, aspect="auto", cmap=cmap, vmin=0, vmax=max(1, float(arr.max()) if arr.size else 1), origin="upper")
        ax.set_xticks(np.arange(len(weekday_labels)))
        ax.set_xticklabels(weekday_labels, fontsize=9.5, fontweight="bold")
        ax.set_yticks(np.arange(len(heat_display.index)))
        ax.set_yticklabels(list(heat_display.index), fontsize=8.4)
        ax.set_xlabel("Dia da semana", fontsize=9.8, fontweight="bold", labelpad=8)
        ax.set_title("Distribuicao por faixa horaria", loc="left", fontsize=11.2, color=ink, pad=10)
        ax.set_xticks(np.arange(-0.5, len(weekday_labels), 1), minor=True)
        ax.set_yticks(np.arange(-0.5, len(heat_display.index), 1), minor=True)
        ax.grid(which="minor", color=grid, linestyle="-", linewidth=0.8)
        ax.tick_params(which="minor", bottom=False, left=False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        threshold = arr.max() * 0.55 if arr.size and arr.max() else 999
        for yy in range(arr.shape[0]):
            for xx in range(arr.shape[1]):
                val = int(arr[yy, xx])
                if val:
                    ax.text(xx, yy, str(val), ha="center", va="center", fontsize=8.8, fontweight="bold", color="#FFFFFF" if val >= threshold else "#1D435A")
        cbar = fig.colorbar(im, ax=ax, fraction=0.030, pad=0.025)
        cbar.outline.set_visible(False)
        cbar.ax.tick_params(labelsize=7.8, colors=muted)
        cbar.set_label("Qtd. de dias", fontsize=8.5, color=muted)

        axp = fig.add_subplot(gs[1, 3])
        axp.axis("off")
        panel = patches.FancyBboxPatch((0.02, 0.03), 0.96, 0.94, boxstyle="round,pad=0.014,rounding_size=0.018", transform=axp.transAxes, linewidth=0.9, edgecolor="#C8E7F7", facecolor="#FFFFFF")
        axp.add_patch(panel)
        y0 = 0.91
        axp.text(0.08, y0, "Resumo", transform=axp.transAxes, fontsize=12, fontweight="bold", color=ink, va="top")
        y0 -= 0.085
        for label, value in [
            ("Saidas fisicas", f"{stats['dias_com_saida_real']}"),
            ("Entradas fisicas", f"{stats['dias_com_entrada_real']}"),
            ("Pontos manuais", f"{stats['registros_manuais_brutos']}"),
            ("Manuais distintos", f"{stats['registros_manuais_distintos']}"),
            ("Dias com manual", f"{stats['dias_com_manual']}"),
            ("Mediana saida", minutes_label(median_min)),
            ("P10-P90 saida", f"{minutes_label(p10)}-{minutes_label(p90)}"),
        ]:
            axp.text(0.08, y0, label, transform=axp.transAxes, fontsize=8.8, color=muted, va="top")
            axp.text(0.92, y0, value, transform=axp.transAxes, fontsize=9.3, fontweight="bold", color=blue_dark, va="top", ha="right")
            y0 -= 0.064
        y0 -= 0.035
        axp.text(0.08, y0, "Maior concentracao", transform=axp.transAxes, fontsize=9.7, fontweight="bold", color=ink, va="top")
        y0 -= 0.052
        wrap_text(axp, mode_txt, 0.08, y0, width_chars=30, fontsize=9.0, color=blue_dark, va="top")
        fig.subplots_adjust(left=0.055, right=0.975, top=0.94, bottom=0.08)
        pdf.savefig(fig, facecolor=bg)
        plt.close(fig)

        # ----- Página 2: portaria x ponto manual suspeito -----
        # Vermelho = portaria/registro físico. Laranja/magenta = ponto manual.
        # Linha preta pontilhada liga o ponto manual à referência física quando >=30min.
        fig = plt.figure(figsize=(11.69, 8.27), dpi=180, facecolor=bg)
        gs = fig.add_gridspec(2, 4, height_ratios=[0.72, 5.2], width_ratios=[1, 1, 1, 1.02], hspace=0.16, wspace=0.18)
        ax_title = fig.add_subplot(gs[0, :])
        ax_title.axis("off")
        ax_title.text(0.01, 0.82, f"{name} - Chapa {cad}", fontsize=16, fontweight="bold", color=ink, va="top")
        ax_title.text(0.01, 0.42, "Portaria x ponto manual fora da fabrica", fontsize=12.5, color=blue_dark, va="top")
        ax_title.text(
            0.01,
            0.13,
            f"{period_label} | Vermelho: portaria | Laranja/Magenta: ponto manual | Linha preta: diferenca >= {MIN_LINE_GAP_MIN}min",
            fontsize=8.8,
            color=muted,
            va="top",
        )

        ax = fig.add_subplot(gs[1, :3])
        ax.set_facecolor("#FFFFFF")

        # Marcos físicos da portaria: entrada e saída reais ficam em vermelho.
        if not daily_exit.empty:
            ax.scatter(
                daily_exit["data_hora"],
                daily_exit["hora_min"],
                s=22,
                color=COLOR_PORTARIA,
                edgecolor="#FFFFFF",
                linewidth=0.35,
                alpha=0.78,
                label="Portaria / saida fisica",
            )
        if not daily_entry.empty:
            ax.scatter(
                daily_entry["data_hora"],
                daily_entry["hora_min"],
                s=18,
                color=COLOR_PORTARIA,
                edgecolor="#FFFFFF",
                linewidth=0.35,
                alpha=0.55,
                label="Portaria / entrada fisica",
            )

        # Pontos manuais suspeitos.
        if not manual_after_exit.empty:
            ax.scatter(
                manual_after_exit["data_hora"],
                manual_after_exit["hora_min"],
                s=36,
                color=orange,
                edgecolor=COLOR_AFTER_EXIT_EDGE,
                linewidth=0.45,
                alpha=0.92,
                label="Ponto manual APOS saida fisica",
                zorder=4,
            )
        if not manual_before_entry.empty:
            ax.scatter(
                manual_before_entry["data_hora"],
                manual_before_entry["hora_min"],
                s=36,
                color=magenta,
                edgecolor=COLOR_BEFORE_ENTRY_EDGE,
                linewidth=0.45,
                alpha=0.92,
                marker="D",
                label="Ponto manual ANTES da entrada fisica",
                zorder=5,
            )

        if not manual_cases.empty:
            line_cases = manual_cases[manual_cases["linha_pdf"]].copy()
            label_added = False
            for _, case in line_cases.iterrows():
                ax.plot(
                    [case["referencia_dt"], case["manual_dt"]],
                    [case["referencia_min"], case["hora_min"]],
                    color=COLOR_LINE,
                    linestyle=":",
                    linewidth=2.0,
                    alpha=0.92,
                    label=f"Ligacao >= {MIN_LINE_GAP_MIN}min" if not label_added else None,
                    zorder=3,
                )
                label_added = True

        ax.plot(smooth_x, smooth_y, color=blue_dark, linewidth=2.6, solid_capstyle="round", solid_joinstyle="round", alpha=0.85, label="Tendencia saida fisica")
        ax.set_title("Linha liga o ponto manual ate a portaria usada como referencia", loc="left", fontsize=11.2, color=ink, pad=10)
        ax.set_ylabel("Horario", fontsize=9.8, fontweight="bold", labelpad=8)
        ax.set_xlabel("Data", fontsize=9.8, fontweight="bold", labelpad=8)
        ax.yaxis.set_major_formatter(FuncFormatter(yfmt))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b/%y"))
        plt.setp(ax.get_xticklabels(), rotation=0, ha="center", fontsize=8.5)

        # Eixo Y precisa abranger todas as séries plotadas (entradas + saídas + manuais).
        y_pieces = []
        for source in (daily_exit, daily_entry, manual_after_exit, manual_before_entry):
            if not source.empty:
                y_pieces.append(source["hora_min"].to_numpy(dtype=float))
        y_all = np.concatenate(y_pieces) if y_pieces else np.array([0.0, 24 * 60])
        min_y = max(0, np.floor((np.nanmin(y_all) - 45) / 30) * 30)
        max_y = min(24 * 60, np.ceil((np.nanmax(y_all) + 45) / 30) * 30)
        ax.set_ylim(max_y, min_y)
        ax.set_yticks(np.arange(min_y, max_y + 1, 30))
        ax.grid(True, axis="both", color=grid, linewidth=0.8)
        for spine in ax.spines.values():
            spine.set_visible(False)
        legend = ax.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor=grid, fontsize=8.0)
        legend.get_frame().set_linewidth(0.7)

        # Painel direito: estatísticas separadas, com leitura curta.
        axp = fig.add_subplot(gs[1, 3])
        add_card(axp, "Validacao")
        y0 = 0.82
        axp.text(0.08, y0, "Conclusao", transform=axp.transAxes, fontsize=8.5, color=muted, va="top")
        y0 -= 0.045
        conclusion_color = magenta if (n_antes and not n_apos) else orange if n_apos else blue_dark
        wrap_text(axp, classification, 0.08, y0, width_chars=32, fontsize=8.8, fontweight="bold", color=conclusion_color, va="top")
        y0 -= 0.13
        linha_count = int(manual_cases["linha_pdf"].sum()) if not manual_cases.empty else 0
        maior_dif = manual_cases["minutos_fora"].max() if not manual_cases.empty else np.nan
        y0 = write_pairs(
            axp,
            [
                ("Pontos fora", stats["ocorrencias_fora_fabrica"]),
                ("Linhas >=30min", linha_count),
                ("Maior diferenca", duration_label(maior_dif)),
                ("Antes entrada", stats["ocorrencias_antes_entrada"]),
                ("Apos saida", stats["ocorrencias_apos_saida"]),
                ("Horas totais", hours_label(stats["horas_totais_manipuladas"])),
                ("Dif. servico real", hours_label(stats["diferenca_horas_servico_reais"])),
            ],
            y=y0,
            color=blue_dark,
        )
        wrap_text(
            axp,
            "Linha preta aparece apenas quando o ponto manual esta pelo menos 30min distante da portaria de referencia.",
            0.08,
            y0 - 0.02,
            width_chars=31,
            fontsize=8.4,
            color=muted,
            va="top",
        )

        fig.subplots_adjust(left=0.055, right=0.975, top=0.94, bottom=0.08)
        pdf.savefig(fig, facecolor=bg)
        plt.close(fig)

        # ----- Página 3: resumo mensal simples -----
        fig = plt.figure(figsize=(11.69, 8.27), dpi=180, facecolor=bg)
        gs = fig.add_gridspec(2, 4, height_ratios=[0.72, 5.2], width_ratios=[1, 1, 1, 1.02], hspace=0.16, wspace=0.18)
        ax_title = fig.add_subplot(gs[0, :])
        ax_title.axis("off")
        ax_title.text(0.01, 0.82, f"{name} - Chapa {cad}", fontsize=16, fontweight="bold", color=ink, va="top")
        ax_title.text(0.01, 0.42, "Evolucao mensal dos pontos manuais fora da fabrica", fontsize=12.5, color=blue_dark, va="top")
        ax_title.text(0.01, 0.13, "Visao enxuta: quantidade de pontos por mes, separando antes da entrada e apos a saida.", fontsize=8.8, color=muted, va="top")

        ax = fig.add_subplot(gs[1, :3])
        ax.set_facecolor("#FFFFFF")
        if manual_cases.empty:
            ax.text(0.02, 0.82, "Sem ponto manual fora da fabrica pelos criterios atuais.", transform=ax.transAxes, fontsize=12, color=muted)
            ax.axis("off")
        else:
            monthly = manual_cases.copy()
            monthly["mes"] = monthly["data_corrigida"].dt.to_period("M").dt.to_timestamp()
            pivot = (
                monthly.pivot_table(
                    index="mes",
                    columns="tipo_ocorrencia",
                    values="minutos_fora",
                    aggfunc="size",
                    fill_value=0,
                )
                .sort_index()
            )
            for col in ["Antes entrada", "Após saída"]:
                if col not in pivot:
                    pivot[col] = 0
            x = np.arange(len(pivot))
            ax.bar(x, pivot["Após saída"], color=orange, label="Apos saida")
            ax.bar(x, pivot["Antes entrada"], bottom=pivot["Após saída"], color=magenta, label="Antes entrada")
            ax.set_xticks(x)
            ax.set_xticklabels([d.strftime("%m/%Y") for d in pivot.index], rotation=45, ha="right", fontsize=8.2)
            ax.set_ylabel("Qtd. pontos")
            ax.set_title("Meses com maior concentracao", loc="left", fontsize=11.2, color=ink, pad=10)
            ax.grid(True, axis="y", color=grid, linewidth=0.8)
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor=grid, fontsize=8.5)

        axp = fig.add_subplot(gs[1, 3])
        add_card(axp, "Resumo")
        linha_count = int(manual_cases["linha_pdf"].sum()) if not manual_cases.empty else 0
        maior_dif = manual_cases["minutos_fora"].max() if not manual_cases.empty else np.nan
        write_pairs(
            axp,
            [
                ("Meses analisados", manual_cases["data_corrigida"].dt.to_period("M").nunique() if not manual_cases.empty else 0),
                ("Pontos fora", stats["ocorrencias_fora_fabrica"]),
                ("Linhas >=30min", linha_count),
                ("Maior diferenca", duration_label(maior_dif)),
                ("Horas totais", hours_label(stats["horas_totais_manipuladas"])),
            ],
            y=0.80,
            color=blue_dark,
        )
        fig.subplots_adjust(left=0.055, right=0.975, top=0.94, bottom=0.11)
        pdf.savefig(fig, facecolor=bg)
        plt.close(fig)

        # ----- Página 4: gráfico dos casos prioritários -----
        fig = plt.figure(figsize=(11.69, 8.27), dpi=180, facecolor=bg)
        gs = fig.add_gridspec(2, 4, height_ratios=[0.72, 5.2], width_ratios=[1, 1, 1, 1.02], hspace=0.16, wspace=0.18)
        ax_title = fig.add_subplot(gs[0, :])
        ax_title.axis("off")
        ax_title.text(0.01, 0.82, f"{name} - Chapa {cad}", fontsize=16, fontweight="bold", color=ink, va="top")
        ax_title.text(0.01, 0.42, "Casos para olhar primeiro", fontsize=12.5, color=blue_dark, va="top")
        ax_title.text(
            0.01,
            0.13,
            "Grafico da diferenca entre o ponto manual e a portaria de referencia. Vermelho = 30min ou mais.",
            fontsize=8.8,
            color=muted,
            va="top",
        )

        ax = fig.add_subplot(gs[1, :3])
        ax.set_facecolor("#FFFFFF")
        plot_cases = manual_cases.dropna(subset=["manual_dt", "minutos_fora"]).copy()
        if plot_cases.empty:
            ax.axis("off")
            ax.text(0.02, 0.82, "Sem ponto manual fora da fabrica pelos criterios atuais.", transform=ax.transAxes, fontsize=12, color=muted)
        else:
            plot_cases = plot_cases.sort_values("manual_dt")
            below = plot_cases[~plot_cases["linha_pdf"]]
            above = plot_cases[plot_cases["linha_pdf"]]

            if not below.empty:
                ax.scatter(
                    below["manual_dt"],
                    below["minutos_fora"],
                    s=24,
                    color="#B7C7D3",
                    alpha=0.55,
                    edgecolor="#FFFFFF",
                    linewidth=0.25,
                    label=f"Abaixo de {MIN_LINE_GAP_MIN}min",
                    zorder=2,
                )
            if not above.empty:
                ax.scatter(
                    above["manual_dt"],
                    above["minutos_fora"],
                    s=42,
                    color=COLOR_PORTARIA,
                    alpha=0.88,
                    edgecolor="#FFFFFF",
                    linewidth=0.35,
                    label=f"{MIN_LINE_GAP_MIN}min ou mais",
                    zorder=3,
                )

            # Linha de corte clara: acima dela o caso também recebe linha pontilhada na página 2.
            ax.axhline(
                MIN_LINE_GAP_MIN,
                color=COLOR_LINE,
                linestyle=":",
                linewidth=1.8,
                alpha=0.9,
                label=f"Corte {MIN_LINE_GAP_MIN}min",
            )

            top_labels = plot_cases.nlargest(5, "minutos_fora")
            for _, case in top_labels.iterrows():
                ax.annotate(
                    f"{case['data_corrigida']:%d/%m}\n{duration_label(case['minutos_fora'])}",
                    xy=(case["manual_dt"], case["minutos_fora"]),
                    xytext=(4, 8),
                    textcoords="offset points",
                    fontsize=7.4,
                    color=ink,
                    ha="left",
                    va="bottom",
                )

            y_max = max(MIN_LINE_GAP_MIN + 15, float(plot_cases["minutos_fora"].max()) + 20)
            ax.set_ylim(0, y_max)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, pos=None: duration_label(value)))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=max(1, int(np.ceil(plot_cases["manual_dt"].dt.to_period("M").nunique() / 8)))))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%Y"))
            plt.setp(ax.get_xticklabels(), rotation=0, ha="center", fontsize=8.2)
            ax.set_ylabel("Diferenca ponto x portaria")
            ax.set_xlabel("Data")
            ax.set_title("Quanto maior a bolinha vermelha no eixo Y, maior a diferenca", loc="left", fontsize=11.2, color=ink, pad=10)
            ax.grid(True, axis="y", color=grid, linewidth=0.8)
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor=grid, fontsize=8.3)

        axp = fig.add_subplot(gs[1, 3])
        add_card(axp, "Como ler")
        above_count = int(manual_cases["linha_pdf"].sum()) if not manual_cases.empty else 0
        maior_gap = manual_cases["minutos_fora"].max() if not manual_cases.empty else np.nan
        dias_com_linha = (
            manual_cases[manual_cases["linha_pdf"]]["data_corrigida"].nunique()
            if not manual_cases.empty
            else 0
        )
        y0 = write_pairs(
            axp,
            [
                ("Corte visual", f"{MIN_LINE_GAP_MIN}min"),
                ("Casos >= corte", above_count),
                ("Dias >= corte", dias_com_linha),
                ("Maior diferenca", duration_label(maior_gap)),
                ("Total antes", stats["ocorrencias_antes_entrada"]),
                ("Total apos", stats["ocorrencias_apos_saida"]),
                ("Total fora", stats["ocorrencias_fora_fabrica"]),
            ],
            y=0.80,
            color=blue_dark,
        )
        y0 = wrap_text(
            axp,
            "Vermelho mostra onde a diferenca chegou a 30min ou mais. Esses mesmos casos aparecem ligados por linha preta na pagina anterior.",
            0.08,
            y0 - 0.02,
            width_chars=31,
            fontsize=8.4,
            color=muted,
            va="top",
        )
        wrap_text(
            axp,
            "Rótulos aparecem só nos maiores casos para manter o gráfico legível.",
            0.08,
            y0 - 0.02,
            width_chars=31,
            fontsize=8.4,
            color=muted,
            va="top",
        )
        fig.subplots_adjust(left=0.055, right=0.975, top=0.94, bottom=0.08)
        pdf.savefig(fig, facecolor=bg)
        plt.close(fig)

    return pdf_path, stats


def make_ranking_pdf(top, stats_rows):
    pdf_path = OUT_DIR / "00_top10_ranking_pontos_manuais.pdf"
    table = top.merge(
        pd.DataFrame(stats_rows),
        on="cadastro",
        how="left",
        suffixes=("", "_validacao"),
    )
    with PdfPages(pdf_path) as pdf:
        fig, ax = plt.subplots(figsize=(11.69, 8.27), dpi=180)
        ax.axis("off")
        ax.text(0.02, 0.96, "Top 10 pessoas com mais registros de ponto manual", fontsize=16, fontweight="bold", transform=ax.transAxes)
        ax.text(0.02, 0.92, f"Base: {BASE}", fontsize=8.5, color="#5B7185", transform=ax.transAxes)
        display_cols = [
            "cadastro",
            "nome",
            "cargo",
            "registros_manuais_brutos",
            "registros_manuais_distintos",
            "dias_com_manual",
            "ocorrencias_antes_entrada",
            "ocorrencias_apos_saida",
            "ocorrencias_fora_fabrica",
            "horas_totais_manipuladas",
            "diferenca_horas_servico_reais",
        ]
        view = table[display_cols].copy()
        view["horas_totais_manipuladas"] = view["horas_totais_manipuladas"].map(hours_label)
        view["diferenca_horas_servico_reais"] = view["diferenca_horas_servico_reais"].map(hours_label)
        view.columns = [
            "Chapa",
            "Nome",
            "Cargo",
            "Pontos manuais",
            "Manuais distintos",
            "Dias",
            "Antes entrada",
            "Apos saida",
            "Total fora",
            "Horas manipuladas",
            "Dif. servico real",
        ]
        cell_text = view.values.tolist()
        tbl = ax.table(cellText=cell_text, colLabels=view.columns, loc="center", cellLoc="left", colLoc="left")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(7.2)
        tbl.scale(1, 1.55)
        for (row, col), cell in tbl.get_celld().items():
            if row == 0:
                cell.set_facecolor("#155C87")
                cell.set_text_props(color="white", weight="bold")
            elif row % 2 == 0:
                cell.set_facecolor("#F1F8FC")
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
    return pdf_path


def raw_record_type(df):
    """Classifica linhas cruas para facilitar validação no Excel."""
    desc = df["desc_norm"].fillna("").astype(str)
    uso = df["uso_norm"].fillna("").astype(str)
    tipo = df["tipo_norm"].fillna("").astype(str)
    manual = df["manual_norm"].fillna("").astype(str)
    planta = df["planta_norm"].fillna("").astype(str)

    labels = pd.Series("Outro", index=df.index, dtype="object")
    labels = labels.mask(desc.str.contains("PORT", na=False), "Portaria")
    labels = labels.mask(manual.eq("SIM") & tipo.isin(PONTO_TIPO_VALUES), "Ponto manual")
    labels = labels.mask(planta.eq("999") | df["home_office_flag"], "Home office")
    labels = labels.mask(desc.str.contains("REF", na=False) | uso.str.contains("REF", na=False), "Refeicao")
    return labels


def person_audit_tables(row, all_cargos=True):
    """Monta resumo, ocorrências e linhas cruas para uma pessoa."""
    cad = str(row["cadastro"])
    df = load_person(cad)
    manual_cargo = None
    if not all_cargos:
        manual_cargo = str(row.get("cargo", "")).strip().upper()
        if manual_cargo not in CATEGORY_FOLDERS:
            manual_cargo = None
    (
        period_all,
        manual,
        daily_exit,
        daily_entry,
        manual_after_exit,
        manual_before_entry,
        daily_suspicious,
        stats,
    ) = prepare_person_analysis(df, manual_cargo=manual_cargo)
    cases = build_manual_cases(manual_after_exit, manual_before_entry)

    name = str(period_all["nome"].dropna().iloc[0]) if "nome" in period_all and not period_all["nome"].dropna().empty else str(row.get("nome", ""))
    cargo = "/".join(sorted(period_all["cargo"].dropna().astype(str).str.upper().unique()))
    area = period_all["area"].dropna().astype(str).mode().iloc[0] if "area" in period_all and not period_all["area"].dropna().empty else ""
    departamento = (
        period_all["departamento"].dropna().astype(str).mode().iloc[0]
        if "departamento" in period_all and not period_all["departamento"].dropna().empty
        else ""
    )
    line_cases = cases[cases["linha_pdf"]].copy() if not cases.empty else cases
    maior_diferenca_min = float(cases["minutos_fora"].max()) if not cases.empty else np.nan
    summary = {
        "cadastro": cad,
        "nome": name,
        "cargo": cargo,
        "area": area,
        "departamento": departamento,
        "pontos_sem_presenca": int(len(cases)),
        "casos_30min_ou_mais": int(len(line_cases)),
        "dias_30min_ou_mais": int(line_cases["data_corrigida"].nunique()) if not line_cases.empty else 0,
        "antes_entrada": stats["ocorrencias_antes_entrada"],
        "apos_saida": stats["ocorrencias_apos_saida"],
        "horas_totais": hours_label(stats["horas_totais_manipuladas"]),
        "dif_servico_real": hours_label(stats["diferenca_horas_servico_reais"]),
        "maior_diferenca": duration_label(maior_diferenca_min) if not cases.empty else "-",
        "maior_diferenca_min": maior_diferenca_min,
        "primeira_ocorrencia": cases["data_corrigida"].min() if not cases.empty else pd.NaT,
        "ultima_ocorrencia": cases["data_corrigida"].max() if not cases.empty else pd.NaT,
    }

    if cases.empty:
        occurrences = pd.DataFrame()
        raw = pd.DataFrame()
        return summary, occurrences, raw

    occurrences = cases.copy().reset_index(drop=True)
    occurrences["case_id"] = [
        f"{cad}_{pd.Timestamp(row_case.data_corrigida):%Y%m%d}_{idx + 1:03d}"
        for idx, row_case in occurrences.iterrows()
    ]
    occurrences["cadastro"] = cad
    occurrences["nome"] = name
    occurrences["ponto_manual_hora"] = occurrences["hora_min"].map(minutes_label)
    occurrences["portaria_referencia_hora"] = occurrences["referencia_min"].map(minutes_label)
    occurrences["diferenca"] = occurrences["minutos_fora"].map(duration_label)
    occurrences["data"] = occurrences["data_corrigida"].dt.strftime("%d/%m/%Y")
    occurrences["manual_dt_txt"] = occurrences["manual_dt"].dt.strftime("%d/%m/%Y %H:%M")
    occurrences["referencia_dt_txt"] = occurrences["referencia_dt"].dt.strftime("%d/%m/%Y %H:%M")

    occurrence_cols = [
        "case_id",
        "cadastro",
        "nome",
        "data",
        "tipo_ocorrencia",
        "manual_dt_txt",
        "referencia_dt_txt",
        "ponto_manual_hora",
        "portaria_referencia_hora",
        "diferenca",
        "minutos_fora",
        "linha_pdf",
        "descricao_coletor",
        "coletor",
        "acesso",
        "uso_acesso",
        "dir",
        "tipo",
        "cargo",
        "area",
        "departamento",
    ]
    occurrences_export = occurrences[[c for c in occurrence_cols if c in occurrences.columns]].copy()

    raw_days = line_cases["data_corrigida"].dropna().unique()
    raw = period_all[period_all["data_corrigida"].isin(raw_days)].copy()
    if raw.empty:
        return summary, occurrences_export, raw

    raw["tipo_registro"] = raw_record_type(raw)
    raw["ponto_ligado"] = False
    raw["portaria_ligada"] = False
    raw["case_ids"] = ""
    raw["diferencas"] = ""
    raw["data_hora_txt"] = raw["data_hora"].dt.strftime("%d/%m/%Y %H:%M")
    raw["data_txt"] = raw["data_corrigida"].dt.strftime("%d/%m/%Y")
    raw["hora_txt"] = raw["hora_min"].map(minutes_label)

    for _, case in occurrences[occurrences["linha_pdf"]].iterrows():
        date_match = raw["data_corrigida"].eq(case["data_corrigida"])
        manual_match = date_match & np.isclose(raw["hora_min"].astype(float), float(case["hora_min"]), atol=0.01)
        ref_match = date_match & np.isclose(raw["hora_min"].astype(float), float(case["referencia_min"]), atol=0.01)
        raw.loc[manual_match, "ponto_ligado"] = True
        raw.loc[ref_match, "portaria_ligada"] = True
        raw.loc[manual_match | ref_match, "case_ids"] = raw.loc[manual_match | ref_match, "case_ids"].map(
            lambda value: f"{value};{case['case_id']}".strip(";")
        )
        raw.loc[manual_match | ref_match, "diferencas"] = raw.loc[manual_match | ref_match, "diferencas"].map(
            lambda value: f"{value};{duration_label(case['minutos_fora'])}".strip(";")
        )

    raw_cols = [
        "cadastro",
        "nome",
        "data_txt",
        "data_hora_txt",
        "hora_txt",
        "tipo_registro",
        "ponto_ligado",
        "portaria_ligada",
        "case_ids",
        "diferencas",
        "Manual",
        "dir",
        "tipo",
        "planta",
        "coletor",
        "acesso",
        "descricao_coletor",
        "uso_acesso",
        "cargo",
        "area",
        "departamento",
    ]
    raw_export = raw[[c for c in raw_cols if c in raw.columns]].sort_values(["data_txt", "hora_txt"]).copy()
    return summary, occurrences_export, raw_export


def export_audit_excel(rows, output_path=None):
    """Cria Excel para validar quem colocou ponto manual sem presença física."""
    output_path = Path(output_path) if output_path is not None else OUT_DIR / "00_auditoria_pontos_sem_presenca.xlsx"
    unique = {}
    for _, row in pd.DataFrame(rows).iterrows():
        cad = str(row["cadastro"])
        if cad not in unique:
            unique[cad] = row.to_dict()

    summaries = []
    occurrences = []
    raw_lines = []
    for row in unique.values():
        summary, occ, raw = person_audit_tables(row, all_cargos=True)
        summaries.append(summary)
        if not occ.empty:
            occurrences.append(occ)
        if not raw.empty:
            raw_lines.append(raw)

    resumo = pd.DataFrame(summaries)
    if not resumo.empty:
        resumo = resumo.sort_values(
            ["casos_30min_ou_mais", "pontos_sem_presenca", "maior_diferenca_min"],
            ascending=[False, False, False],
        )
    ocorrencias = pd.concat(occurrences, ignore_index=True) if occurrences else pd.DataFrame()
    linhas_cruas = pd.concat(raw_lines, ignore_index=True) if raw_lines else pd.DataFrame()

    descricao = pd.DataFrame(
        [
            {
                "aba": "Resumo Pessoas",
                "descricao": "Ranking de pessoas com ponto manual em horario sem presenca fisica.",
            },
            {
                "aba": "Ocorrencias",
                "descricao": "Cada ponto manual suspeito, com hora do ponto, portaria de referencia e diferenca.",
            },
            {
                "aba": "Linhas Cruas Ocorrencias",
                "descricao": "Linhas cruas dos dias com diferenca >=30min, marcando ponto_ligado e portaria_ligada.",
            },
        ]
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        descricao.to_excel(writer, sheet_name="Descricao", index=False)
        resumo.to_excel(writer, sheet_name="Resumo Pessoas", index=False)
        ocorrencias.to_excel(writer, sheet_name="Ocorrencias", index=False)
        linhas_cruas.to_excel(writer, sheet_name="Linhas Cruas Ocorrencias", index=False)
        for ws in writer.sheets.values():
            ws.freeze_panes = "A2"
            for col in ws.columns:
                max_len = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 10), 55)
    return output_path


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    category_rankings, person_rankings = compute_manual_rankings()
    if category_rankings.empty and person_rankings.empty:
        raise RuntimeError(
            "Nao encontrei pontos manuais fora da fabrica (antes da entrada ou apos a saida)."
        )

    # Ordenação consistente: prioriza quem tem mais ocorrências totais e maior volume de horas manipuladas.
    rank_keys = ["ocorrencias_fora_fabrica", "horas_totais_manipuladas"]

    generated = []
    audit_rows = []
    for cargo, folder in CATEGORY_FOLDERS.items():
        category_dir = OUT_DIR / folder
        top_category = (
            category_rankings[category_rankings["cargo"].eq(cargo)]
            .sort_values(rank_keys, ascending=[False, False])
            .head(TOP_N)
            .copy()
        )
        if top_category.empty:
            continue

        ranking_pdf = make_people_ranking_pdf(
            top_category,
            category_dir,
            f"Top {TOP_N} {folder}: ponto manual sem presenca fisica",
            f"00_top{TOP_N}_{folder.lower()}_manuais_fora_fabrica.pdf",
            "Criterio: Manual=Sim tipo Ponto antes da entrada fisica ou apos a saida fisica, com tratamento para turno virado e exclusao de home office.",
        )
        if ranking_pdf:
            generated.append(ranking_pdf)
            print(ranking_pdf)

        audit_rows.extend(top_category.to_dict("records"))
        for _, row in top_category.iterrows():
            pdf_path, _ = make_person_pdf(row, category_dir)
            generated.append(pdf_path)
            print(pdf_path)

    # Ranking por área usando o conjunto person_rankings (uma linha por pessoa).
    valid_area = person_rankings[
        person_rankings["area"].notna()
        & ~person_rankings["area"].str.upper().isin(["SEM AREA", "NAN", "NONE", ""])
    ].copy()
    area_stats = (
        valid_area.groupby("area", as_index=False)
        .agg(
            pessoas=("cadastro", "nunique"),
            ocorrencias_antes_entrada=("ocorrencias_antes_entrada", "sum"),
            ocorrencias_apos_saida=("ocorrencias_apos_saida", "sum"),
            ocorrencias_fora_fabrica=("ocorrencias_fora_fabrica", "sum"),
            horas_totais_manipuladas=("horas_totais_manipuladas", "sum"),
            diferenca_horas_servico_reais=("diferenca_horas_servico_reais", "sum"),
        )
        .sort_values(rank_keys, ascending=[False, False])
        .head(3)
        .reset_index(drop=True)
    )

    area_summary_pdf = make_area_summary_pdf(area_stats)
    if area_summary_pdf:
        generated.append(area_summary_pdf)
        print(area_summary_pdf)

    area_root = OUT_DIR / AREAS_FOLDER
    for rank, area in enumerate(area_stats["area"].tolist(), start=1):
        area_people = (
            person_rankings[person_rankings["area"].eq(area)]
            .sort_values(rank_keys, ascending=[False, False])
            .copy()
        )
        area_dir = area_root / f"{rank:02d}_{safe_filename(area)}"
        ranking_pdf = make_people_ranking_pdf(
            area_people,
            area_dir,
            f"Area {area}: pessoas com ponto manual sem presenca fisica",
            "00_funcionarios_area_manuais_fora_fabrica.pdf",
            "Inclui funcionarios da area com ponto manual antes da entrada fisica ou apos a saida fisica, ja ajustado para turno virado.",
        )
        if ranking_pdf:
            generated.append(ranking_pdf)
            print(ranking_pdf)

        audit_rows.extend(area_people.to_dict("records"))
        for _, row in area_people.iterrows():
            pdf_path, _ = make_person_pdf(row, area_dir)
            generated.append(pdf_path)
            print(pdf_path)

    if audit_rows:
        audit_excel = export_audit_excel(audit_rows)
        print(audit_excel)

    print(f"Total de PDFs gerados: {len(generated)}")


if __name__ == "__main__":
    main()
