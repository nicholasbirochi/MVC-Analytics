from pathlib import Path

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
PROJECT_DIR = SCRIPT_DIR.parent
BASE = PROJECT_DIR / "database" / "df_ronda.parquet"
OUT_DIR = SCRIPT_DIR
PDF = OUT_DIR / "ultimas_saidas_sem_planta_999.pdf"
EMAIL = OUT_DIR / "email_folli_gabriela_reverdini_ultimas_saidas_sem_planta_999.txt"

CAD = ""
NOME = ""
TODAY = pd.Timestamp("2026-04-30")


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


def prepare_daily_last_exits():
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
        "area",
        "departamento",
    ]
    df = pq.read_table(str(BASE), columns=cols, filters=[("cadastro", "==", CAD)]).to_pandas()
    if df.empty:
        raise RuntimeError("Nenhum registro encontrado para a chapa 4008223.")

    data = pd.to_datetime(df["data"], errors="coerce")
    dt = data.dt
    ambiguous = data.notna() & (dt.day <= 12) & (dt.month <= 12)
    swapped = pd.to_datetime(
        {"year": dt.year, "month": dt.day, "day": dt.month},
        errors="coerce",
    )
    df["data_corrigida"] = data.where(~ambiguous, swapped)
    df["hora_min"] = df["hora"].map(hora_to_minutes)
    df = df.dropna(subset=["data_corrigida", "hora_min"]).copy()
    df["data_corrigida"] = pd.to_datetime(df["data_corrigida"]).dt.normalize()

    end = min(df["data_corrigida"].max(), TODAY).normalize()
    start = (end - pd.DateOffset(months=12) + pd.DateOffset(days=1)).normalize()
    period_all = df[(df["data_corrigida"] >= start) & (df["data_corrigida"] <= end)].copy()
    period_all["planta_norm"] = period_all["planta"].astype(str).str.strip()
    period = period_all[~period_all["planta_norm"].eq("999")].copy()
    period["dir_norm"] = period["dir"].astype(str).str.strip().str.upper()

    saidas = period[period["dir_norm"].eq("S")].copy()
    daily = (
        saidas.sort_values(["data_corrigida", "hora_min"])
        .groupby("data_corrigida", as_index=False)
        .tail(1)
        .copy()
    )
    daily = daily.sort_values("data_corrigida").reset_index(drop=True)
    if daily.empty:
        raise RuntimeError("Sem saidas S no periodo apos excluir planta 999.")

    removed_999_rows = len(period_all) - len(period)
    removed_999_exit_rows = int(
        (
            period_all["planta_norm"].eq("999")
            & period_all["dir"].astype(str).str.strip().str.upper().eq("S")
        ).sum()
    )
    return daily, period, start, end, removed_999_rows, removed_999_exit_rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    daily, period, start, end, removed_999_rows, removed_999_exit_rows = (
        prepare_daily_last_exits()
    )

    weekday_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
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

    x_dates = mdates.date2num(daily["data_corrigida"].to_numpy(dtype="datetime64[ms]"))
    y = daily["hora_min"].to_numpy(dtype=float)
    slope_day, intercept = np.polyfit(x_dates, y, 1) if len(daily) >= 2 else (0.0, y[0])
    slope_30d = slope_day * 30
    slope_period = slope_day * (x_dates.max() - x_dates.min()) if len(daily) >= 2 else 0.0
    smooth_x, smooth_y = gaussian_smooth_line(x_dates, y)

    first_window = daily.head(min(20, len(daily)))["hora_min"].median()
    last_window = daily.tail(min(20, len(daily)))["hora_min"].median()
    delta_edge = last_window - first_window
    classification = (
        "tendencia de sair mais cedo"
        if slope_30d < -5
        else ("tendencia de sair mais tarde" if slope_30d > 5 else "sem tendencia relevante")
    )

    period_label = f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"
    last_exit_days = daily["data_corrigida"].nunique()
    days_without_exit = period["data_corrigida"].nunique() - last_exit_days
    median_min = daily["hora_min"].median()
    mean_min = daily["hora_min"].mean()
    p10 = daily["hora_min"].quantile(0.10)
    p90 = daily["hora_min"].quantile(0.90)
    early_1500 = int((daily["hora_min"] < 15 * 60).sum())
    late_1830 = int((daily["hora_min"] >= 18 * 60 + 30).sum())
    mode_bucket = heat.stack().idxmax() if heat.size and heat.to_numpy().max() > 0 else ("-", "-")
    mode_count = int(heat.to_numpy().max()) if heat.size else 0
    mode_txt = (
        f"{mode_bucket[1]} as {mode_bucket[0]} ({mode_count} dias)"
        if mode_bucket != ("-", "-")
        else "Sem saidas no periodo"
    )
    if slope_30d < -5:
        interp = "A linha linear aponta antecipacao do horario de saida ao longo do periodo."
    elif slope_30d > 5:
        interp = "A linha linear aponta postergacao do horario de saida ao longo do periodo."
    else:
        interp = (
            "A inclinacao e pequena; o padrao permanece concentrado perto de 17h, "
            "sem evidencia forte de antecipacao."
        )

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
    cmap = LinearSegmentedColormap.from_list(
        "babyblue_clean",
        ["#FFFFFF", "#EDF9FF", "#CDEFFF", "#89CFF0", "#3E99C9"],
    )

    with PdfPages(PDF) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27), dpi=180, facecolor=bg)
        gs = fig.add_gridspec(
            2,
            4,
            height_ratios=[0.72, 5.2],
            width_ratios=[1, 1, 1, 1.02],
            hspace=0.16,
            wspace=0.18,
        )
        ax_title = fig.add_subplot(gs[0, :])
        ax_title.axis("off")
        ax_title.text(
            0.01,
            0.82,
            f"{NOME} - Chapa {CAD}",
            fontsize=16,
            fontweight="bold",
            color=ink,
            va="top",
        )
        ax_title.text(
            0.01,
            0.42,
            "Heatmap das ultimas saidas do dia",
            fontsize=12.5,
            color=blue_dark,
            va="top",
        )
        ax_title.text(
            0.01,
            0.13,
            f"{period_label} | Criterio: ultima marcacao S diaria | Planta 999 excluida",
            fontsize=8.8,
            color=muted,
            va="top",
        )

        ax = fig.add_subplot(gs[1, :3])
        arr = heat_display.to_numpy(dtype=float)
        im = ax.imshow(
            arr,
            aspect="auto",
            cmap=cmap,
            vmin=0,
            vmax=max(1, float(arr.max()) if arr.size else 1),
            origin="upper",
        )
        ax.set_xticks(np.arange(len(weekday_labels)))
        ax.set_xticklabels(weekday_labels, fontsize=9.5, fontweight="bold")
        ax.set_yticks(np.arange(len(heat_display.index)))
        ax.set_yticklabels(list(heat_display.index), fontsize=8.4)
        ax.set_xlabel("Dia da semana", fontsize=9.8, fontweight="bold", labelpad=8)
        ax.set_ylabel("", fontsize=9.8, fontweight="bold", labelpad=8)
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
                    ax.text(
                        xx,
                        yy,
                        str(val),
                        ha="center",
                        va="center",
                        fontsize=8.8,
                        fontweight="bold",
                        color="#FFFFFF" if val >= threshold else "#1D435A",
                    )
        cbar = fig.colorbar(im, ax=ax, fraction=0.030, pad=0.025)
        cbar.outline.set_visible(False)
        cbar.ax.tick_params(labelsize=7.8, colors=muted)
        cbar.set_label("Qtd. de dias", fontsize=8.5, color=muted)

        axp = fig.add_subplot(gs[1, 3])
        axp.axis("off")
        panel = patches.FancyBboxPatch(
            (0.02, 0.03),
            0.96,
            0.94,
            boxstyle="round,pad=0.014,rounding_size=0.018",
            transform=axp.transAxes,
            linewidth=0.9,
            edgecolor="#C8E7F7",
            facecolor="#FFFFFF",
        )
        axp.add_patch(panel)
        y0 = 0.91
        axp.text(0.08, y0, "Resumo", transform=axp.transAxes, fontsize=12, fontweight="bold", color=ink, va="top")
        y0 -= 0.085
        for label, value in [
            ("Ultimas saidas", f"{last_exit_days}"),
            ("Dias sem saida S", f"{days_without_exit}"),
            ("Mediana", minutes_label(median_min)),
            ("Media", minutes_label(mean_min)),
            ("P10-P90", f"{minutes_label(p10)}-{minutes_label(p90)}"),
            ("Antes de 15h", f"{early_1500}"),
            ("Apos 18h30", f"{late_1830}"),
        ]:
            axp.text(0.08, y0, label, transform=axp.transAxes, fontsize=8.8, color=muted, va="top")
            axp.text(
                0.92,
                y0,
                value,
                transform=axp.transAxes,
                fontsize=9.4,
                fontweight="bold",
                color=blue_dark,
                va="top",
                ha="right",
            )
            y0 -= 0.064
        y0 -= 0.035
        axp.text(0.08, y0, "Maior concentracao", transform=axp.transAxes, fontsize=9.7, fontweight="bold", color=ink, va="top")
        y0 -= 0.052
        axp.text(0.08, y0, mode_txt, transform=axp.transAxes, fontsize=9.3, color=blue_dark, va="top")
        y0 -= 0.105
        axp.text(0.08, y0, "Filtro aplicado", transform=axp.transAxes, fontsize=9.7, fontweight="bold", color=ink, va="top")
        y0 -= 0.052
        wrap_text(
            axp,
            f"Foram removidas {removed_999_rows} linhas da planta 999 no periodo, incluindo {removed_999_exit_rows} marcacoes S.",
            0.08,
            y0,
            width_chars=32,
            fontsize=8.5,
            color=muted,
            va="top",
        )
        fig.subplots_adjust(left=0.055, right=0.975, top=0.94, bottom=0.08)
        pdf.savefig(fig, facecolor=bg)
        plt.close(fig)

        fig = plt.figure(figsize=(11.69, 8.27), dpi=180, facecolor=bg)
        gs = fig.add_gridspec(
            2,
            4,
            height_ratios=[0.72, 5.2],
            width_ratios=[1, 1, 1, 1.02],
            hspace=0.16,
            wspace=0.18,
        )
        ax_title = fig.add_subplot(gs[0, :])
        ax_title.axis("off")
        ax_title.text(
            0.01,
            0.82,
            f"{NOME} - Chapa {CAD}",
            fontsize=16,
            fontweight="bold",
            color=ink,
            va="top",
        )
        ax_title.text(
            0.01,
            0.42,
            "Tendencia das ultimas saidas do dia",
            fontsize=12.5,
            color=blue_dark,
            va="top",
        )
        ax_title.text(
            0.01,
            0.13,
            f"{period_label} | Criterio: ultima marcacao S diaria | Planta 999 excluida",
            fontsize=8.8,
            color=muted,
            va="top",
        )

        ax = fig.add_subplot(gs[1, :3])
        ax.set_facecolor("#FFFFFF")
        ax.scatter(
            daily["data_corrigida"],
            daily["hora_min"],
            s=22,
            color=blue,
            edgecolor=blue_dark,
            linewidth=0.35,
            alpha=0.76,
            label="Ultima saida diaria",
        )
        ax.plot(
            smooth_x,
            smooth_y,
            color=blue_dark,
            linewidth=3.0,
            solid_capstyle="round",
            solid_joinstyle="round",
            label="Tendencia",
        )
        ax.set_title("Evolucao temporal", loc="left", fontsize=11.2, color=ink, pad=10)
        ax.set_ylabel("Horario da ultima saida", fontsize=9.8, fontweight="bold", labelpad=8)
        ax.set_xlabel("Data", fontsize=9.8, fontweight="bold", labelpad=8)
        ax.yaxis.set_major_formatter(FuncFormatter(yfmt))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b/%y"))
        plt.setp(ax.get_xticklabels(), rotation=0, ha="center", fontsize=8.5)
        min_y = max(8 * 60, np.floor((np.nanmin(y) - 45) / 30) * 30)
        max_y = min(22 * 60, np.ceil((np.nanmax(y) + 45) / 30) * 30)
        ax.set_ylim(max_y, min_y)
        ax.set_yticks(np.arange(min_y, max_y + 1, 30))
        ax.grid(True, axis="both", color=grid, linewidth=0.8)
        for spine in ax.spines.values():
            spine.set_visible(False)
        legend = ax.legend(
            loc="upper left",
            frameon=True,
            facecolor="#FFFFFF",
            edgecolor=grid,
            fontsize=8.4,
        )
        legend.get_frame().set_linewidth(0.7)

        axp = fig.add_subplot(gs[1, 3])
        axp.axis("off")
        panel = patches.FancyBboxPatch(
            (0.02, 0.03),
            0.96,
            0.94,
            boxstyle="round,pad=0.014,rounding_size=0.018",
            transform=axp.transAxes,
            linewidth=0.9,
            edgecolor="#C8E7F7",
            facecolor="#FFFFFF",
        )
        axp.add_patch(panel)
        y0 = 0.91
        axp.text(0.08, y0, "Tendencia", transform=axp.transAxes, fontsize=12, fontweight="bold", color=ink, va="top")
        y0 -= 0.088
        axp.text(0.08, y0, "Conclusao", transform=axp.transAxes, fontsize=8.8, color=muted, va="top")
        y0 -= 0.043
        axp.text(
            0.08,
            y0,
            classification,
            transform=axp.transAxes,
            fontsize=9.2,
            fontweight="bold",
            color=blue_dark,
            va="top",
        )
        y0 -= 0.078
        for label, value in [
            ("Inclinacao", f"{slope_30d:+.1f} min / 30 dias"),
            ("Variacao estimada", f"{slope_period:+.1f} min"),
            ("Mediana inicial", minutes_label(first_window)),
            ("Mediana final", minutes_label(last_window)),
            ("Diferenca", f"{delta_edge:+.0f} min"),
            ("Dias considerados", f"{len(daily)}"),
        ]:
            axp.text(0.08, y0, label, transform=axp.transAxes, fontsize=8.8, color=muted, va="top")
            axp.text(
                0.92,
                y0,
                value,
                transform=axp.transAxes,
                fontsize=8.9,
                fontweight="bold",
                color=blue_dark,
                va="top",
                ha="right",
            )
            y0 -= 0.066
        y0 -= 0.045
        axp.text(0.08, y0, "Interpretacao", transform=axp.transAxes, fontsize=9.7, fontweight="bold", color=ink, va="top")
        y0 -= 0.055
        wrap_text(axp, interp, 0.08, y0, width_chars=32, fontsize=8.6, color=muted, va="top")
        fig.subplots_adjust(left=0.055, right=0.975, top=0.94, bottom=0.08)
        pdf.savefig(fig, facecolor=bg)
        plt.close(fig)

    EMAIL.write_text(
        f"""Assunto: Ultimas saidas sem planta 999 - Gabriela Reverdini (4008223)

Folli, bom dia.

Refiz a analise da GABRIELA REVERDINI DADIAN MASCHERETTI, chapa 4008223, considerando somente a ultima marcacao S de cada dia e excluindo todos os registros da planta 999 antes da consolidacao.

Periodo validado: {period_label}.

Resumo:
- {last_exit_days} ultimas saidas diarias consideradas;
- mediana: {minutes_label(median_min)};
- faixa P10-P90: {minutes_label(p10)} a {minutes_label(p90)};
- maior concentracao: {mode_txt};
- tendencia: {classification};
- inclinacao linear: {slope_30d:+.1f} minutos a cada 30 dias.

Foram removidas {removed_999_rows} linhas da planta 999 no periodo antes do calculo.

Segue o PDF em anexo com dois graficos: heatmap na primeira pagina e tendencia na segunda.

Atenciosamente,
""",
        encoding="utf-8",
    )
    print(PDF)
    print(EMAIL)


if __name__ == "__main__":
    main()
