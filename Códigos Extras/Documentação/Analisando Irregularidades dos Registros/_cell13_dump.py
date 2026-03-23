# Limpa df pesado para liberar memória (se necessário)
BATCH_SIZE = 250_000  # usado em loops de chunk/leitura/escrita nesta célula

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text.lower()

IRREGULARIDADES_SEM_PLANTA_999 = {
    "irregularidade_ausencia_das_horas_presenciais_minimas",
    "irregularidade_pessoas_trabalhando_sem_ganhar",
    "irregularidade_ponto_sem_portaria",
    "irregularidade_registro_sem_portaria",
}

def _deve_excluir_planta_999(
    irregularidade_col: str | None = None,
    titulo: str | None = None,
    pdf_path: Path | None = None,
) -> bool:
    candidatos = []

    if irregularidade_col:
        candidatos.append(slugify(irregularidade_col))

    if titulo:
        candidatos.append(slugify(titulo))

    if pdf_path is not None:
        try:
            candidatos.append(slugify(Path(pdf_path).stem))
        except Exception:
            pass
        candidatos.append(slugify(str(pdf_path)))

    return any(
        alvo in cand
        for cand in candidatos
        for alvo in IRREGULARIDADES_SEM_PLANTA_999
    )

def _mask_planta_not_999(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    s_num = pd.to_numeric(s, errors="coerce")
    mask_999 = s_num.eq(999) | s.str.match(r"^999(\D|$)", na=False)
    return ~mask_999

def _filtrar_df_sem_planta_999(df_: pd.DataFrame | None) -> pd.DataFrame | None:
    if not isinstance(df_, pd.DataFrame):
        return df_
    if df_.empty:
        return df_
    if "planta" not in df_.columns:
        return df_
    return df_.loc[_mask_planta_not_999(df_["planta"])].copy()

def _filtrar_row_ids_sem_planta_999(row_ids: np.ndarray) -> np.ndarray:
    if row_ids is None:
        return np.array([], dtype=np.int64)

    row_ids = np.asarray(row_ids, dtype=np.int64)
    if row_ids.size == 0:
        return row_ids

    if "planta" not in df_min_raw.columns:
        return row_ids

    row_ids = row_ids[(row_ids >= 0) & (row_ids < len(df_min_raw))]
    if row_ids.size == 0:
        return row_ids

    cache_name = "_PLANTA_NUM_CACHE"
    cache = globals().get(cache_name)

    if not isinstance(cache, np.ndarray) or len(cache) != len(df_min_raw):
        cache = pd.to_numeric(df_min_raw["planta"], errors="coerce").to_numpy()
        globals()[cache_name] = cache

    plantas = cache[row_ids]
    keep = ~pd.Series(plantas).eq(999).to_numpy()
    return row_ids[keep]

def _pick_col(df_: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df_.columns:
            return c
    return None


def _render_capa_padrao_pdf(
    pdf,
    titulo: str,
    gen_date: str,
    metricas: list[tuple[str, str]],
    periodo: str | None = None,
    concentracoes: list[tuple[str, str]] | None = None,
    top3_piores: list[str] | None = None,
    top3_atuais: list[str] | None = None,
    janela_info: str | None = None,
    extras: list[str] | None = None,
) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.axis("off")

    bottom_margin = 0.035
    truncated = {"value": False}

    def _clean_text(txt: str, max_chars: int | None = None) -> str:
        s = "" if txt is None else str(txt)
        s = " ".join(s.replace("\r", " ").replace("\n", " ").split())
        if max_chars and len(s) > max_chars:
            s = s[: max_chars - 3].rstrip() + "..."
        return s

    def _wrap_lines(txt: str, width: int, max_lines: int | None = None) -> list[str]:
        txt = "" if txt is None else str(txt)
        out: list[str] = []
        for blk in txt.replace("\r", "").split("\n"):
            blk = blk.strip()
            if blk == "":
                out.append("")
                continue
            words = blk.split()
            line = ""
            for w in words:
                candidate = (line + " " + w).strip()
                if len(candidate) <= width:
                    line = candidate
                else:
                    if line:
                        out.append(line)
                    line = w
            if line:
                out.append(line)

        if not out:
            out = [""]

        if max_lines is not None and len(out) > max_lines:
            out = out[:max_lines]
            if not out[-1].endswith("..."):
                out[-1] = _clean_text(out[-1], max_chars=max(10, width - 2))
        return out

    def _draw_wrapped(
        x: float,
        y: float,
        text: str,
        fontsize: float,
        width: int,
        step: float,
        fontweight: str | None = None,
        prefix_first: str | None = None,
        max_lines: int | None = None,
    ) -> float:
        lines = _wrap_lines(text, width=width, max_lines=max_lines)
        for k, ln in enumerate(lines):
            if y < bottom_margin:
                if not truncated["value"]:
                    ax.text(
                        0.02,
                        bottom_margin,
                        "(Resumo da capa truncado para manter legibilidade nesta página)",
                        fontsize=8.8,
                        va="bottom",
                        color="#555",
                    )
                    truncated["value"] = True
                return y
            ln_txt = f"{prefix_first}{ln}" if (k == 0 and prefix_first) else ln
            ax.text(x, y, ln_txt, fontsize=fontsize, fontweight=fontweight, va="top")
            y -= step
        return y

    y = 0.965
    y = _draw_wrapped(0.02, y, _clean_text(titulo), fontsize=16.8, width=92, step=0.040, fontweight="bold", max_lines=3)
    y -= 0.003
    y = _draw_wrapped(0.02, y, f"Gerado em: {gen_date}", fontsize=11.0, width=100, step=0.030)

    y -= 0.006
    for rotulo, valor in metricas:
        y = _draw_wrapped(0.02, y, f"{rotulo}: {valor}", fontsize=11.6, width=104, step=0.031, prefix_first="- ", max_lines=2)

    if periodo:
        y = _draw_wrapped(0.02, y, f"Período: {periodo}", fontsize=10.9, width=104, step=0.030, prefix_first="- ", max_lines=2)

    if concentracoes:
        for rotulo, valor in concentracoes:
            y = _draw_wrapped(0.02, y, f"{rotulo}: {valor}", fontsize=10.7, width=104, step=0.029, prefix_first="- ", max_lines=2)

    y = _draw_wrapped(
        0.02,
        y,
        "Top 3 piores (quantidade e % do total):",
        fontsize=11.2,
        width=102,
        step=0.030,
        fontweight="bold",
        prefix_first="- ",
        max_lines=2,
    )

    if top3_piores:
        for i, linha in enumerate(top3_piores[:3], start=1):
            linha_limpa = _clean_text(linha, max_chars=220)
            y = _draw_wrapped(0.035, y, f"{i}. {linha_limpa}", fontsize=9.4, width=120, step=0.024, max_lines=3)
    else:
        y = _draw_wrapped(0.035, y, "Sem dados suficientes.", fontsize=9.7, width=120, step=0.026)

    janela_txt = janela_info if janela_info else "base indisponível"
    y = _draw_wrapped(
        0.02,
        y,
        f"Top 3 atuais (últimos 30 dias) - base da janela: {janela_txt}",
        fontsize=10.9,
        width=102,
        step=0.030,
        fontweight="bold",
        prefix_first="- ",
        max_lines=2,
    )

    if top3_atuais:
        for i, linha in enumerate(top3_atuais[:3], start=1):
            linha_limpa = _clean_text(linha, max_chars=220)
            y = _draw_wrapped(0.035, y, f"{i}. {linha_limpa}", fontsize=9.2, width=120, step=0.024, max_lines=3)
    else:
        y = _draw_wrapped(0.035, y, "Sem dados suficientes na janela.", fontsize=9.6, width=120, step=0.026)

    if extras:
        for extra in extras:
            y = _draw_wrapped(0.02, y, _clean_text(str(extra), max_chars=220), fontsize=9.2, width=106, step=0.024, prefix_first="- ", max_lines=2)

    pdf.savefig(fig)
    plt.close(fig)


def gerar_relatorio_pdf_semanal_feriado(df_semanal: pd.DataFrame, titulo: str, pdf_path: Path) -> None:
    import datetime as _dt
    import numpy as np
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    gen_date = _dt.date.today().strftime("%Y-%m-%d")

    if df_semanal is None or df_semanal.empty:
        with PdfPages(pdf_path) as pdf:
            _render_capa_padrao_pdf(
                pdf=pdf,
                titulo=titulo,
                gen_date=gen_date,
                metricas=[
                    ("Pessoa-semanas irregulares", "0"),
                    ("Pessoas únicas", "0"),
                    ("Semanas com ocorrência", "0"),
                ],
                periodo=None,
                concentracoes=[
                    ("Concentração Top 1", "0 (0.0%)"),
                    ("Concentração Top 3", "0 (0.0%)"),
                    ("Concentração Top 10", "0 (0.0%)"),
                ],
                top3_piores=[],
                top3_atuais=[],
                janela_info="0 (0.0% do total)",
                extras=["Sem linhas para gerar o relatório semanal."],
            )
        return

    dfw = df_semanal.copy()

    # -----------------------------
    # Normalização mínima
    # -----------------------------
    if "_semana_feriado_ini" in dfw.columns and "semana_inicio" not in dfw.columns:
        dfw = dfw.rename(columns={"_semana_feriado_ini": "semana_inicio"})

    if "área" in dfw.columns and "area" not in dfw.columns:
        dfw = dfw.rename(columns={"área": "area"})

    if "semana_inicio" not in dfw.columns:
        raise ValueError("df_semanal precisa ter a coluna 'semana_inicio'.")

    dfw["semana_inicio"] = pd.to_datetime(dfw["semana_inicio"], errors="coerce").dt.normalize()
    dfw = dfw[dfw["semana_inicio"].notna()].copy()

    if "semana_fim" not in dfw.columns:
        dfw["semana_fim"] = dfw["semana_inicio"] + pd.Timedelta(days=6)
    else:
        dfw["semana_fim"] = pd.to_datetime(dfw["semana_fim"], errors="coerce").dt.normalize()

    if "nome" not in dfw.columns:
        dfw["nome"] = "Sem Nome"
    dfw["nome"] = dfw["nome"].fillna("Sem Nome").astype(str).str.strip()

    if "area" not in dfw.columns:
        dfw["area"] = "Sem Área"
    dfw["area"] = dfw["area"].fillna("Sem Área").astype(str).str.strip()

    if "dias_com_registro" not in dfw.columns:
        dfw["dias_com_registro"] = np.nan

    if "dias_presenciais" not in dfw.columns:
        dfw["dias_presenciais"] = 0
    if "horas_presenciais" not in dfw.columns:
        dfw["horas_presenciais"] = 0.0

    dfw["dias_presenciais"] = pd.to_numeric(dfw["dias_presenciais"], errors="coerce").fillna(0).astype(int)
    dfw["horas_presenciais"] = pd.to_numeric(dfw["horas_presenciais"], errors="coerce").fillna(0.0)

    if "cadastro" in dfw.columns:
        dfw["cadastro"] = dfw["cadastro"].astype(str).str.strip()
    else:
        raise ValueError("df_semanal precisa ter a coluna 'cadastro'.")

    if "nao_cumpriu_3" not in dfw.columns:
        dfw["nao_cumpriu_3"] = (dfw["dias_presenciais"] < 3)
    else:
        dfw["nao_cumpriu_3"] = dfw["nao_cumpriu_3"].fillna(False).astype(bool)

    # -----------------------------
    # Base analítica (pessoa-semana)
    # -----------------------------
    pessoa_semanas_total = int(len(dfw))
    pessoas_unicas = int(dfw["cadastro"].nunique())
    areas_unicas = int(dfw["area"].nunique())
    semanas_unicas = int(dfw["semana_inicio"].nunique())

    dt_min = dfw["semana_inicio"].min()
    dt_max = dfw["semana_fim"].max()

    area_agg = (
        dfw.groupby("area", as_index=False)
           .agg(
               pessoa_semanas=("cadastro", "size"),
               pessoas_unicas=("cadastro", "nunique"),
               media_dias_presenciais=("dias_presenciais", "mean"),
               media_horas_presenciais=("horas_presenciais", "mean"),
           )
    )
    area_agg["score_risco"] = area_agg["pessoa_semanas"] * (3 - area_agg["media_dias_presenciais"].clip(lower=0, upper=3))

    semana_agg = (
        dfw.groupby("semana_inicio", as_index=False)
           .agg(
               pessoa_semanas=("cadastro", "size"),
               pessoas_unicas=("cadastro", "nunique"),
               media_dias_presenciais=("dias_presenciais", "mean"),
               media_horas_presenciais=("horas_presenciais", "mean"),
           )
           .sort_values("semana_inicio")
    )

    pessoa_stats = (
        dfw.groupby(["cadastro", "nome", "area"], as_index=False)
           .agg(
               semanas_irregulares=("semana_inicio", "nunique"),
               dias_presenciais_total=("dias_presenciais", "sum"),
               horas_presenciais_total=("horas_presenciais", "sum"),
               media_dias_presenciais=("dias_presenciais", "mean"),
               media_horas_presenciais=("horas_presenciais", "mean"),
           )
    )

    def make_first_name_labels(series_names: pd.Series) -> pd.Series:
        first = (
            series_names.astype(str)
            .str.strip()
            .str.split()
            .str[0]
            .replace({"": "Semnome"})
        )
        counts = {}
        labels = []
        for fn in first.tolist():
            counts[fn] = counts.get(fn, 0) + 1
            labels.append(fn if counts[fn] == 1 else f"{fn} ({counts[fn]})")
        return pd.Series(labels, index=series_names.index)

    # -----------------------------
    # Estilo
    # -----------------------------
    VW_NAVY   = "#001E50"
    VW_BLUE   = "#0B5FA5"
    VW_BLUE2  = "#7FB0D6"
    VW_GREY   = "#C9D1D9"
    VW_DARK   = "#1B2A41"
    ACCENT    = "#A8D8F0"
    BG_LIGHT  = "#F6F8FB"

    plt.rcParams.update({
        "figure.facecolor": BG_LIGHT,
        "axes.facecolor": "white",
        "axes.edgecolor": VW_GREY,
        "axes.labelcolor": VW_DARK,
        "xtick.color": VW_DARK,
        "ytick.color": VW_DARK,
        "text.color": VW_DARK,
        "font.size": 10,
    })

    VW_CMAP = LinearSegmentedColormap.from_list(
        "vw_blues",
        [BG_LIGHT, "#CFE2F3", VW_BLUE, VW_NAVY]
    )

    def style_card(ax):
        for s in ax.spines.values():
            s.set_visible(True)
            s.set_color(VW_GREY)
            s.set_linewidth(1.2)
        ax.set_facecolor("white")

    def add_desc(ax, text):
        ax.text(
            0.01, -0.34, text,
            transform=ax.transAxes,
            ha="left", va="top",
            fontsize=8.8, color="#334155",
            wrap=True,
            bbox=dict(
                boxstyle="round,pad=0.40",
                facecolor=BG_LIGHT,
                edgecolor=VW_GREY,
                linewidth=0.9
            )
        )

    DESC = {
        "A": "Combina volume de pessoa-semana com severidade média (menos dias presenciais = maior severidade).",
        "B": "Mostra onde está a maior massa de semanas irregulares. É o melhor corte para priorização rápida.",
        "C": "Ajuda a ver se o problema foi pontual ou se repetiu entre as semanas/áreas analisadas.",
        "D": "Compara o volume de semanas irregulares com a média de dias presenciais da semana.",
        "E": "Mostra quão perto do limite mínimo de 3 dias estão os casos. Quanto mais perto de 0 dia, mais severo.",
        "F": "Evidencia quem reaparece em mais de uma semana irregular.",
        "G": "Mostra as áreas com maior base afetada em pessoas únicas, não só em volume bruto.",
        "H": "Destaca os recorrentes com menor média de dias presenciais nas semanas irregulares.",
    }

    with PdfPages(pdf_path) as pdf:
        # =========================================
        # CAPA
        # =========================================
        cad_nome_map = (
            pessoa_stats.drop_duplicates(subset=["cadastro"], keep="first")
                       .set_index("cadastro")["nome"]
            if (not pessoa_stats.empty) and ("cadastro" in pessoa_stats.columns)
            else pd.Series(dtype=str)
        )
        labels_pessoa = dfw["cadastro"].astype(str).map(
            lambda c: f"{c} - {cad_nome_map.get(c, '')}".strip(" -")
        )
        top_pessoas_semana = labels_pessoa.value_counts()
        top1_n = int(top_pessoas_semana.head(1).sum()) if not top_pessoas_semana.empty else 0
        top3_n = int(top_pessoas_semana.head(3).sum()) if not top_pessoas_semana.empty else 0
        top10_n = int(top_pessoas_semana.head(10).sum()) if not top_pessoas_semana.empty else 0

        top1_pct = (top1_n / pessoa_semanas_total) if pessoa_semanas_total else 0.0
        top3_pct = (top3_n / pessoa_semanas_total) if pessoa_semanas_total else 0.0
        top10_pct = (top10_n / pessoa_semanas_total) if pessoa_semanas_total else 0.0

        top3_piores_capa = []
        for k, v in top_pessoas_semana.head(3).items():
            pct = (int(v) / pessoa_semanas_total) if pessoa_semanas_total else 0.0
            top3_piores_capa.append(f"{str(k)} — {int(v)} ({pct:.1%})")

        dt_ref = pd.to_datetime(dfw["semana_inicio"], errors="coerce").dropna()
        dt_ref_max = dt_ref.max().normalize() if not dt_ref.empty else pd.NaT
        if pd.notna(dt_ref_max):
            dt_cut = dt_ref_max - pd.Timedelta(days=29)
            recent = dfw.loc[pd.to_datetime(dfw["semana_inicio"], errors="coerce") >= dt_cut]
        else:
            recent = dfw.head(0)

        total_recent = int(len(recent))
        if total_recent > 0:
            labels_recent = recent["cadastro"].astype(str).map(
                lambda c: f"{c} - {cad_nome_map.get(c, '')}".strip(" -")
            )
            top_recent = labels_recent.value_counts().head(3)
        else:
            top_recent = pd.Series(dtype=int)

        top3_atuais_capa = []
        for k, v in top_recent.items():
            pct = (int(v) / total_recent) if total_recent else 0.0
            top3_atuais_capa.append(f"{str(k)} — {int(v)} ({pct:.1%} da janela)")

        janela_info = (
            f"{total_recent:,} ({(total_recent / pessoa_semanas_total):.1%} do total)".replace(",", ".")
            if pessoa_semanas_total > 0 else "0 (0.0% do total)"
        )

        metricas_capa = [
            ("Pessoa-semanas irregulares", f"{pessoa_semanas_total:,}".replace(",", ".")),
            ("Pessoas únicas", f"{pessoas_unicas:,}".replace(",", ".")),
            ("Semanas com ocorrência", f"{semanas_unicas:,}".replace(",", ".")),
        ]

        periodo_capa = None
        if pd.notna(dt_min) and pd.notna(dt_max):
            periodo_capa = f"{pd.to_datetime(dt_min).date()} → {pd.to_datetime(dt_max).date()}"

        concentracoes_capa = [
            ("Concentração Top 1", f"{top1_n:,} ({top1_pct:.1%})".replace(",", ".")),
            ("Concentração Top 3", f"{top3_n:,} ({top3_pct:.1%})".replace(",", ".")),
            ("Concentração Top 10", f"{top10_n:,} ({top10_pct:.1%})".replace(",", ".")),
        ]

        extras_capa = [
            f"Áreas com ocorrência: {areas_unicas:,}".replace(",", "."),
            "Critério: menos de 3 dias presenciais na semana de feriado prolongado",
        ]

        _render_capa_padrao_pdf(
            pdf=pdf,
            titulo=titulo,
            gen_date=gen_date,
            metricas=metricas_capa,
            periodo=periodo_capa,
            concentracoes=concentracoes_capa,
            top3_piores=top3_piores_capa,
            top3_atuais=top3_atuais_capa,
            janela_info=janela_info,
            extras=extras_capa,
        )

        # =========================================
        # DASHBOARD 4x2
        # =========================================
        fig = plt.figure(figsize=(18, 24))
        gs = fig.add_gridspec(4, 2, hspace=0.92, wspace=0.28)

        # (A) Prioridade — Volume x Severidade por área
        axA = fig.add_subplot(gs[0, 0]); style_card(axA)

        dfA = area_agg.copy()
        topA = dfA.sort_values("score_risco", ascending=False).head(8).copy()

        axA.scatter(
            dfA["pessoa_semanas"],
            dfA["media_dias_presenciais"],
            s=(dfA["pessoas_unicas"] * 20).clip(50, 1000),
            alpha=0.65, color=VW_BLUE2, edgecolors=VW_NAVY, linewidths=0.7
        )
        axA.scatter(
            topA["pessoa_semanas"],
            topA["media_dias_presenciais"],
            s=(topA["pessoas_unicas"] * 24).clip(70, 1100),
            alpha=0.95, color=ACCENT, edgecolors=VW_NAVY, linewidths=0.9
        )

        for _, r in topA.iterrows():
            axA.annotate(
                str(r["area"]),
                xy=(r["pessoa_semanas"], r["media_dias_presenciais"]),
                xytext=(12, 10),
                textcoords="offset points",
                ha="left", va="bottom", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor=VW_GREY, linewidth=0.6)
            )

        axA.set_title("A) Prioridade — Volume × severidade por Área", pad=10, color=VW_NAVY, fontweight="bold")
        axA.set_xlabel("Volume (pessoa-semanas)")
        axA.set_ylabel("Média de dias presenciais")
        axA.grid(True, linestyle="--", alpha=0.18)
        axA.legend(handles=[
            Line2D([0], [0], marker='o', color='w', label='Áreas (geral)',
                   markerfacecolor=VW_BLUE2, markeredgecolor=VW_NAVY, markersize=9),
            Line2D([0], [0], marker='o', color='w', label='Top 8 prioridade',
                   markerfacecolor=ACCENT, markeredgecolor=VW_NAVY, markersize=9),
        ], loc="upper right", frameon=True, facecolor="white", edgecolor=VW_GREY)
        add_desc(axA, DESC["A"])

        # (B) Pareto — pessoa-semanas por área
        axB = fig.add_subplot(gs[0, 1]); style_card(axB)
        dfB = area_agg.sort_values("pessoa_semanas", ascending=False).head(12).copy()

        axB.bar(dfB["area"].astype(str), dfB["pessoa_semanas"], color=VW_NAVY, alpha=0.92)
        axB.set_title("B) Pareto — Massa de semanas irregulares por Área", pad=10, color=VW_NAVY, fontweight="bold")
        axB.set_xlabel("Área")
        axB.set_ylabel("Qtd de pessoa-semanas")
        axB.grid(axis="y", linestyle="--", alpha=0.18)
        axB.tick_params(axis="x", rotation=35)

        max_bar = float(dfB["pessoa_semanas"].max()) if not dfB.empty else 1.0
        axB.set_ylim(0, max_bar * 1.30 if max_bar > 0 else 1)
        for i, r in enumerate(dfB.itertuples(index=False)):
            axB.text(
                i,
                r.pessoa_semanas + max_bar * 0.03,
                f"{int(r.pessoa_semanas)}\n({float(r.media_dias_presenciais):.2f} dias)",
                ha="center", va="bottom", fontsize=8
            )
        add_desc(axB, DESC["B"])

        # (C) Heatmap — área x semana
        axC = fig.add_subplot(gs[1, 0]); style_card(axC)
        top_areas_heat = area_agg.sort_values("pessoa_semanas", ascending=False).head(10)["area"].astype(str).tolist()

        aw = (
            dfw[dfw["area"].astype(str).isin(top_areas_heat)]
            .groupby(["area", "semana_inicio"], as_index=False)
            .size()
            .rename(columns={"size": "qtd"})
        )

        if aw.empty:
            axC.axis("off")
            axC.text(0.02, 0.95, "C) Estabilidade — Área × semana", fontsize=14, fontweight="bold", va="top")
            axC.text(0.02, 0.82, "Sem dados suficientes.", fontsize=11, va="top")
        else:
            pivot = aw.pivot_table(index="area", columns="semana_inicio", values="qtd", aggfunc="sum").fillna(0)
            pivot = pivot.reindex(top_areas_heat)
            pivot = pivot.reindex(sorted(pivot.columns), axis=1)
            mat = pivot.values

            im = axC.imshow(mat, aspect="auto", cmap=VW_CMAP)
            axC.set_title("C) Estabilidade — Pessoa-semanas por Área × semana", pad=10, color=VW_NAVY, fontweight="bold")
            axC.set_xlabel("Semana (início)")
            axC.set_ylabel("Área")

            xlabels = [pd.to_datetime(c).strftime("%Y-%m-%d") for c in pivot.columns]
            axC.set_xticks(np.arange(len(xlabels)))
            axC.set_xticklabels(xlabels, rotation=45, ha="right")
            axC.set_yticks(np.arange(pivot.shape[0]))
            axC.set_yticklabels(pivot.index.astype(str))

            for i in range(mat.shape[0]):
                for j in range(mat.shape[1]):
                    v = mat[i, j]
                    axC.text(j, i, f"{int(v)}", ha="center", va="center",
                             fontsize=8, color=("white" if v >= np.nanmax(mat) * 0.60 and np.nanmax(mat) > 0 else VW_DARK))

            cbar = fig.colorbar(im, ax=axC, fraction=0.046, pad=0.04)
            cbar.set_label("Qtd pessoa-semana")

        add_desc(axC, DESC["C"])

        # (D) Tendência semanal
        axD = fig.add_subplot(gs[1, 1]); style_card(axD)
        dfD = semana_agg.copy()
        dfD["semana"] = dfD["semana_inicio"].dt.strftime("%Y-%m-%d")

        axD.plot(dfD["semana"], dfD["pessoa_semanas"], marker="o", color=VW_NAVY, linewidth=2.4, label="Pessoa-semanas")
        axD.set_title("D) Evolução semanal — Volume vs média de dias", pad=10, color=VW_NAVY, fontweight="bold")
        axD.set_xlabel("Semana (início)")
        axD.set_ylabel("Qtd pessoa-semana")
        axD.grid(True, linestyle="--", alpha=0.18)
        axD.tick_params(axis="x", rotation=45)

        axD2 = axD.twinx()
        axD2.plot(dfD["semana"], dfD["media_dias_presenciais"], marker="o", color=VW_BLUE, linewidth=2.2, label="Média dias")
        axD2.set_ylabel("Média dias presenciais")

        lines1, labels1 = axD.get_legend_handles_labels()
        lines2, labels2 = axD2.get_legend_handles_labels()
        axD.legend(lines1 + lines2, labels1 + labels2, loc="upper right", frameon=True, facecolor="white", edgecolor=VW_GREY)

        for x, y in zip(dfD["semana"], dfD["pessoa_semanas"]):
            axD.text(x, y + max(dfD["pessoa_semanas"].max() * 0.03, 0.2), f"{int(y)}", ha="center", fontsize=8)

        add_desc(axD, DESC["D"])

        # (E) Severidade — faixas de horas
        axE = fig.add_subplot(gs[2, 0]); style_card(axE)

        bins = [-0.001, 1.0, 2.0, 3.0001]
        labels = ["0 dia", "1 dia", "2 dias"]
        dfw["faixa_dias"] = pd.cut(dfw["dias_presenciais"], bins=bins, labels=labels, include_lowest=True, right=False)

        dist = (
            dfw.groupby("faixa_dias", dropna=False)
               .size()
               .rename("qtd")
               .reset_index()
        )
        dist["faixa_dias"] = dist["faixa_dias"].astype(str)
        dist = dist[dist["faixa_dias"].isin(labels)].copy()
        dist = dist.set_index("faixa_dias").reindex(labels).fillna(0).reset_index()
        dist["pct"] = dist["qtd"] / dist["qtd"].sum() * 100 if dist["qtd"].sum() > 0 else 0.0

        axE.bar(dist["faixa_dias"], dist["pct"], color=VW_BLUE, alpha=0.92)
        axE.set_title("E) Severidade — Distribuição por faixa de dias", pad=10, color=VW_NAVY, fontweight="bold")
        axE.set_xlabel("Dias presenciais na semana")
        axE.set_ylabel("% de pessoa-semanas")
        axE.grid(axis="y", linestyle="--", alpha=0.18)

        ymaxE = float(dist["pct"].max()) * 1.25 if not dist.empty else 1.0
        axE.set_ylim(0, ymaxE if ymaxE > 0 else 1)
        for i, r in dist.iterrows():
            axE.text(i, float(r["pct"]) + ymaxE * 0.02 if ymaxE > 0 else 0.1, f"{float(r['pct']):.1f}%", ha="center", fontsize=8)

        add_desc(axE, DESC["E"])

        # (F) Recorrência por pessoa
        axF = fig.add_subplot(gs[2, 1]); style_card(axF)

        topF = (
            pessoa_stats.sort_values(["semanas_irregulares", "horas_presenciais_total"], ascending=[False, True])
                       .head(12)
                       .copy()
        )
        topF["primeiro_nome"] = make_first_name_labels(topF["nome"])

        valsF = topF["semanas_irregulares"].to_numpy()
        axF.bar(topF["primeiro_nome"], valsF, color=VW_NAVY, alpha=0.92)
        axF.set_title("F) Investigação — Recorrência por pessoa", pad=10, color=VW_NAVY, fontweight="bold")
        axF.set_xlabel("Primeiro nome")
        axF.set_ylabel("Qtd de semanas irregulares")
        axF.grid(axis="y", linestyle="--", alpha=0.18)
        axF.tick_params(axis="x", rotation=45)
        for lab in axF.get_xticklabels():
            lab.set_ha("right")

        if len(valsF) > 0:
            axF.set_ylim(0, max(valsF.max() * 1.30, valsF.max() + 1))
            for i, r in enumerate(topF.itertuples(index=False)):
                axF.text(i, r.semanas_irregulares + 0.05, f"{str(r.area)}\n{float(r.media_dias_presenciais):.2f} dias",
                         ha="center", va="bottom", fontsize=8)

        add_desc(axF, DESC["F"])

        # (G) Base afetada — pessoas únicas por área
        axG = fig.add_subplot(gs[3, 0]); style_card(axG)

        dfG = area_agg.sort_values(["pessoas_unicas", "pessoa_semanas"], ascending=[False, False]).head(12).copy()
        valsG = dfG["pessoas_unicas"].to_numpy()

        axG.bar(dfG["area"].astype(str), valsG, color=VW_BLUE, alpha=0.92)
        axG.set_title("G) Base afetada — Pessoas únicas por Área", pad=10, color=VW_NAVY, fontweight="bold")
        axG.set_xlabel("Área")
        axG.set_ylabel("Pessoas únicas")
        axG.grid(axis="y", linestyle="--", alpha=0.18)
        axG.tick_params(axis="x", rotation=35)

        if len(valsG) > 0:
            axG.set_ylim(0, max(valsG.max() * 1.25, valsG.max() + 1))
            for i, r in enumerate(dfG.itertuples(index=False)):
                axG.text(i, r.pessoas_unicas + 0.05, f"{int(r.pessoa_semanas)} sem.", ha="center", va="bottom", fontsize=8)

        add_desc(axG, DESC["G"])

        # (H) Menor média de horas — recorrentes
        axH = fig.add_subplot(gs[3, 1]); style_card(axH)

        baseH = pessoa_stats[pessoa_stats["semanas_irregulares"] >= 2].copy()
        topH = (
            baseH.sort_values(["media_dias_presenciais", "semanas_irregulares"], ascending=[True, False])
                 .head(12)
                 .copy()
        )
        topH["primeiro_nome"] = make_first_name_labels(topH["nome"])

        valsH = topH["media_dias_presenciais"].to_numpy()
        axH.bar(topH["primeiro_nome"], valsH, color=VW_NAVY, alpha=0.85)
        axH.set_title("H) Recorrentes — Menor média de dias presenciais", pad=10, color=VW_NAVY, fontweight="bold")
        axH.set_xlabel("Primeiro nome")
        axH.set_ylabel("Média de dias presenciais")
        axH.grid(axis="y", linestyle="--", alpha=0.18)
        axH.tick_params(axis="x", rotation=45)
        for lab in axH.get_xticklabels():
            lab.set_ha("right")

        if len(valsH) > 0:
            axH.set_ylim(0, max(valsH.max() * 1.35, 1))
            for i, r in enumerate(topH.itertuples(index=False)):
                axH.text(i, r.media_dias_presenciais + 0.03, f"{int(r.semanas_irregulares)} sem.\n{str(r.area)}",
                         ha="center", va="bottom", fontsize=8)

        add_desc(axH, DESC["H"])

        fig.suptitle(
            "Painel semanal — Semana de Feriado Prolongado (pessoa-semana)",
            fontsize=20, fontweight="bold", color=VW_NAVY, y=0.99
        )

        pdf.savefig(fig)
        plt.close(fig)

        # =========================================
        # LISTAS FINAIS
        # =========================================
        fig = plt.figure(figsize=(11.69, 8.27))
        ax = fig.add_subplot(111)
        ax.axis("off")

        top_pessoas = (
            pessoa_stats.sort_values(["semanas_irregulares", "media_dias_presenciais"], ascending=[False, True])
                       .head(15)
                       .loc[:, ["cadastro", "nome", "area", "semanas_irregulares", "media_dias_presenciais"]]
                       .copy()
        )
        top_pessoas["media_dias_presenciais"] = top_pessoas["media_dias_presenciais"].round(2)

        ax.text(0.02, 0.97, "Top 15 pessoas — semanas irregulares", fontsize=15, fontweight="bold", va="top")

        if top_pessoas.empty:
            ax.text(0.02, 0.90, "Sem dados suficientes.", fontsize=11, va="top")
        else:
            tabela = ax.table(
                cellText=top_pessoas.values,
                colLabels=["Cadastro", "Nome", "Área", "Semanas", "Média dias"],
                cellLoc="left",
                colLoc="left",
                bbox=[0.02, 0.08, 0.96, 0.82]
            )
            tabela.auto_set_font_size(False)
            tabela.set_fontsize(9)
            tabela.scale(1, 1.15)

        pdf.savefig(fig)
        plt.close(fig)

def gerar_relatorio_pdf(df_irregularidade: pd.DataFrame, titulo: str, pdf_path: Path) -> None:
    if (
        isinstance(df_irregularidade, pd.DataFrame)
        and not df_irregularidade.empty
        and {"cadastro", "semana_inicio", "dias_presenciais", "horas_presenciais"}.issubset(df_irregularidade.columns)
    ):
        gerar_relatorio_pdf_semanal_feriado(df_irregularidade, titulo=titulo, pdf_path=pdf_path)
        return

    import datetime as _dt
    import numpy as np

    plt.rcParams.update({
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "font.size": 11,
        "axes.titlesize": 16,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
    })

    def _wrap(s: str, width: int = 44) -> str:
        s = "" if s is None else str(s)
        s = s.strip()
        if len(s) <= width:
            return s
        words = s.split()
        out, line = [], ""
        for w in words:
            if len(line) + len(w) + 1 <= width:
                line = (line + " " + w).strip()
            else:
                if line:
                    out.append(line)
                line = w
        if line:
            out.append(line)
        if len(out) <= 4:
            return "\n".join(out)
        return "\n".join(out[:4]) + "…"

    def _as_series(df_: pd.DataFrame, col: str) -> pd.Series:
        x = df_.loc[:, col]
        if isinstance(x, pd.DataFrame):
            x = x.iloc[:, 0]
        return x

    def _pick_col_local(df_: pd.DataFrame, candidates: list[str]) -> str | None:
        for c in candidates:
            if c in df_.columns:
                return c
        return None

    def _norm_text(s: str) -> str:
        s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", s).strip().lower()

    def _match_any(text_norm: str, patterns_norm: list[str]) -> bool:
        return any(p in text_norm for p in patterns_norm)

    def _annotate_barh(ax, total_base: int | None = None, fs: int = 9):
        xmax = ax.get_xlim()[1] if ax.get_xlim()[1] > 0 else 1.0
        pad = xmax * 0.012
        for p in ax.patches:
            v = float(p.get_width())
            if v <= 0:
                continue
            y = p.get_y() + p.get_height() / 2
            label = f"{int(v)} ({(v / total_base):.1%})" if (total_base and total_base > 0) else f"{int(v)}"
            x = min(v + pad, xmax * 0.985)
            ha = "left" if x < xmax * 0.96 else "right"
            ax.text(x, y, label, va="center", ha=ha, fontsize=fs)

    def _annotate_bar(ax, total_base: int | None = None, fs: int = 9):
        ymax = ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1.0
        pad = ymax * 0.015
        for p in ax.patches:
            v = float(p.get_height())
            if v <= 0:
                continue
            x = p.get_x() + p.get_width() / 2
            label = f"{int(v)}\n({(v / total_base):.1%})" if (total_base and total_base > 0) else f"{int(v)}"
            ax.text(x, v + pad, label, ha="center", va="bottom", fontsize=fs)

    def _pie_with_legend(ax, values, legend_labels, title, base_text):
        values = [int(v) for v in values]
        total_vals = sum(values)
        ax.set_title(title, pad=16, fontsize=12)
        if total_vals <= 0:
            ax.axis("off")
            ax.text(0.02, 0.90, "Sem dados suficientes.", fontsize=10.5, va="top")
            return

        wedges, _, autotexts = ax.pie(
            values,
            labels=None,
            autopct=lambda p: f"{p:.0f}%" if p > 0 else "",
            startangle=90,
            pctdistance=0.72,
            radius=0.88,
            wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
            textprops={"fontsize": 9},
        )
        for t in autotexts:
            t.set_fontsize(9)

        ax.legend(
            wedges,
            legend_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.98),
            ncol=min(2, len(legend_labels)),
            fontsize=8.5,
            frameon=False,
            borderaxespad=0.0,
        )
        ax.text(0.5, 0.04, base_text, ha="center", va="bottom", transform=ax.transAxes, fontsize=8.8)
        ax.set_aspect("equal")

    def _find_dim_colab_source(required_cols: list[str]) -> pd.DataFrame | None:
        candidates = [
            "dim_colaborador", "df_dim_colaborador", "df_colaboradores", "df_colaborador",
            "vw_colaboradores", "df_colaborador_hr", "vw_colaborador_hr", "df_colaboradorRH"
        ]
        for name in candidates:
            obj = globals().get(name)
            if isinstance(obj, pd.DataFrame) and all(c in obj.columns for c in required_cols):
                return obj
        return None

    def _get_dim_map(area_col_use: str | None, col_heranca: str | None, col_cargo: str | None = None) -> pd.DataFrame | None:
        if (area_col_use is None) or (col_heranca is None):
            return None

        cache_key = ("_DIM_MAP_CACHE", area_col_use, col_heranca, col_cargo or "")
        if cache_key in globals():
            cached = globals().get(cache_key)
            if isinstance(cached, pd.DataFrame) and not cached.empty and "cadastro" in cached.columns:
                return cached

        required = ["cadastro", area_col_use, col_heranca]
        required_cargo = required + ([col_cargo] if col_cargo else [])

        src = _find_dim_colab_source(required_cargo)
        if src is not None:
            dim = src.loc[:, required_cargo].copy(deep=False).drop_duplicates(subset=["cadastro"], keep="last")
            dim["cadastro"] = dim["cadastro"].astype(str).str.strip()
            dim["_area_norm"] = dim[area_col_use].fillna("").astype(str).str.strip()
            dim["_her_norm"] = dim[col_heranca].fillna("").astype(str).str.strip()
            if col_cargo and (col_cargo in dim.columns):
                dim["_cargo_norm"] = dim[col_cargo].fillna("").astype(str).str.strip().str.upper()
            globals()[cache_key] = dim[["cadastro", "_area_norm", "_her_norm"] + (["_cargo_norm"] if "_cargo_norm" in dim.columns else [])]
            return globals()[cache_key]

        base_all = globals().get("df_min_raw")
        if not isinstance(base_all, pd.DataFrame):
            return None
        if not all(c in base_all.columns for c in required_cargo):
            return None

        seen: set[str] = set()
        parts = []
        n = len(base_all)
        cols = required_cargo

        for i in range(0, n, BATCH_SIZE):
            chunk = base_all.iloc[i:i + BATCH_SIZE][cols].copy(deep=False)
            if chunk.empty:
                continue
            chunk = chunk.drop_duplicates(subset=["cadastro"], keep="last")
            cad_str = chunk["cadastro"].astype(str).str.strip()
            new_mask = ~cad_str.isin(seen)
            if not new_mask.any():
                continue
            chunk = chunk.loc[new_mask]
            cad_new = cad_str.loc[new_mask]
            seen.update(cad_new.tolist())
            chunk = chunk.assign(cadastro=cad_new.to_numpy(copy=False))
            parts.append(chunk)
            if len(seen) >= 400_000:
                break

        if not parts:
            return None

        dim = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["cadastro"], keep="last")
        dim["_area_norm"] = dim[area_col_use].fillna("").astype(str).str.strip()
        dim["_her_norm"] = dim[col_heranca].fillna("").astype(str).str.strip()
        if col_cargo and (col_cargo in dim.columns):
            dim["_cargo_norm"] = dim[col_cargo].fillna("").astype(str).str.strip().str.upper()

        globals()[cache_key] = dim[["cadastro", "_area_norm", "_her_norm"] + (["_cargo_norm"] if "_cargo_norm" in dim.columns else [])]
        return globals()[cache_key]

    def _build_dt_from_data_hora(df_: pd.DataFrame) -> pd.Series:
        if "_dt_ronda" in df_.columns:
            return pd.to_datetime(df_["_dt_ronda"], errors="coerce")
        if ("data" in df_.columns) and ("hora" in df_.columns):
            data_dt = pd.to_datetime(df_["data"], dayfirst=True, errors="coerce")
            hora_s = df_["hora"].fillna("00:00").astype(str).str.strip()
            hora_s = hora_s.replace({"": "00:00", "nan": "00:00", "NaT": "00:00"})
            hhmm_mask = hora_s.str.match(r"^\d{1,2}:\d{2}$", na=False)
            hora_s = hora_s.where(~hhmm_mask, hora_s + ":00")
            hora_td = pd.to_timedelta(hora_s, errors="coerce")
            return data_dt.dt.normalize() + hora_td
        return pd.Series(pd.NaT, index=df_.index)

    def _montar_metodologia_relatorio(titulo_local: str, pdf_path_local: Path | str, janela_proxy_minutos: int) -> tuple[str, list[str], list[str]]:
        txt_norm = _norm_text(f"{titulo_local} {pdf_path_local}")

        eh_ponto = _match_any(
            txt_norm,
            ["irregularidade_ponto_sem_portaria", "ponto sem portaria"],
        )
        eh_grill = _match_any(
            txt_norm,
            [
                "irregularidade_nao_entrou_no_refeitorio_mas_passou_no_grill",
                "nao entrou no refeitorio mas passou no grill",
            ],
        )
        eh_999 = _match_any(
            txt_norm,
            ["irregularidade_999_como_trajeto", "999 como trajeto"],
        )

        if eh_ponto:
            titulo_met = "Metodologia - Ponto sem Portaria"
            passos = [
                "Unidade de contagem: ocorrencia em pessoa-dia (deduplica por RM e dia operacional).",
                "Base elegivel: dias com ponto presencial e filtros da irregularidade aplicados.",
                f"Regra principal: irregular quando falta ENTRADA ou falta SAIDA de portaria em ate {int(janela_proxy_minutos)} minuto(s) do 1o ponto presencial.",
                "Dias com ENTRADA+SAIDA em portaria no mesmo dia sao desconsiderados.",
                f"Analise de possivel terceiro: pareamento <= {int(janela_proxy_minutos)} minuto(s), mesma planta e mesmo numero de coletor.",
                "Na lista de terceiros, so aparecem pessoas com registro de portaria no dia.",
            ]
            observacoes = [
                "Leitura dos nomes no relatorio: RM | Nome abreviado | Area.",
                "Graficos de distribuicao priorizam representatividade percentual por pessoa-dia.",
            ]
            return titulo_met, passos, observacoes

        if eh_grill:
            titulo_met = "Metodologia - Refeitorio x Grill"
            passos = [
                "Unidade de contagem: ocorrencia em pessoa-dia (nao por volume de linhas brutas).",
                "Classificacao de local: REF em qualquer ponto da descricao e sem GRILL => refeitorio normal.",
                "Regra principal: houve passagem em GRILL no dia, mas sem passagem em refeitorio normal no mesmo dia.",
                "Consolidacao por pessoa-dia para evitar duplicidade de batidas no mesmo dia.",
                "Comparativos de concentracao em duas janelas: periodo total e ultimos 30 dias.",
                "Heatmaps destacam periodo, horario e dia da semana com maior concentracao.",
            ]
            observacoes = [
                "Top pessoas sempre exibido como RM | Nome abreviado | Area.",
                "Coletores destacados no contexto do caso (refeitorios mais presentes).",
            ]
            return titulo_met, passos, observacoes

        if eh_999:
            titulo_met = "Metodologia - 999 como Trajeto"
            passos = [
                "Unidade de contagem: ocorrencia em pessoa-dia (deduplicacao por RM e dia operacional).",
                "Base da irregularidade: eventos classificados como 999 como trajeto conforme regra da base tratada.",
                "Analise de concentracao por pessoa no periodo total e na janela dos ultimos 30 dias.",
                "Consolidacao de Top 3 e Top 10 por volume para ranking de maior recorrencia.",
                "Heatmaps mostram concentracao por periodo, horario e dia da semana.",
                "Contexto operacional destaca plantas e portarias (descricao de coletor) mais presentes.",
            ]
            observacoes = [
                "Top pessoas sempre exibido como RM | Nome abreviado | Area.",
                "Graficos de distribuicao mostram percentual para facilitar comparacao entre grupos.",
            ]
            return titulo_met, passos, observacoes

        return (
            "Metodologia da Analise",
            [
                "Unidade de contagem: ocorrencia em pessoa-dia.",
                "Padronizacao de data/hora, RM, area, planta e coletor antes das agregacoes.",
                "Concentracao analisada no periodo total e, quando aplicavel, nos ultimos 30 dias.",
                "Ranking e distribuicoes apresentados em percentual para leitura comparativa.",
            ],
            ["Top pessoas no formato RM | Nome abreviado | Area."],
        )

    def _render_metodologia_resumo_pdf(
        pdf,
        titulo_metodologia: str,
        passos: list[str],
        observacoes: list[str] | None = None,
    ) -> None:
        fig = plt.figure(figsize=(11.69, 8.27))
        ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
        ax.axis("off")

        bottom_margin = 0.04

        def _wrap_local(txt: str, width: int) -> list[str]:
            txt = "" if txt is None else str(txt)
            out: list[str] = []
            for blk in txt.replace("\r", "").split("\n"):
                blk = blk.strip()
                if blk == "":
                    out.append("")
                    continue
                words = blk.split()
                line = ""
                for w in words:
                    cand = (line + " " + w).strip()
                    if len(cand) <= width:
                        line = cand
                    else:
                        if line:
                            out.append(line)
                        line = w
                if line:
                    out.append(line)
            return out if out else [""]

        def _draw(x: float, y: float, text: str, fs: float, width: int, step: float, weight: str | None = None) -> float:
            for ln in _wrap_local(text, width):
                if y < bottom_margin:
                    return y
                ax.text(x, y, ln, fontsize=fs, fontweight=weight, va="top")
                y -= step
            return y

        y = 0.95
        y = _draw(0.03, y, titulo_metodologia, fs=18, width=90, step=0.045, weight="bold")
        y = _draw(0.03, y, "Resumo objetivo da logica aplicada neste relatorio.", fs=11.2, width=108, step=0.032)

        y -= 0.006
        y = _draw(0.03, y, "Etapas da analise", fs=13.0, width=90, step=0.034, weight="bold")
        for i, p in enumerate(passos, start=1):
            y = _draw(0.04, y, f"{i}. {p}", fs=10.6, width=116, step=0.028)

        if observacoes:
            y -= 0.004
            y = _draw(0.03, y, "Leitura do relatorio", fs=12.2, width=90, step=0.033, weight="bold")
            for obs in observacoes:
                y = _draw(0.04, y, f"- {obs}", fs=10.4, width=116, step=0.027)

        pdf.savefig(fig)
        plt.close(fig)

    gen_date = _dt.date.today().strftime("%Y-%m-%d")
    try:
        janela_proxy_minutos = int(globals().get("janela_proxy_minutos", 3))
    except Exception:
        janela_proxy_minutos = 3
    janela_proxy_minutos = max(int(janela_proxy_minutos), 1)

    metodologia_titulo, metodologia_passos, metodologia_observacoes = _montar_metodologia_relatorio(
        titulo_local=titulo,
        pdf_path_local=pdf_path,
        janela_proxy_minutos=janela_proxy_minutos,
    )

    if df_irregularidade is None or df_irregularidade.empty:
        with PdfPages(pdf_path) as pdf:
            _render_capa_padrao_pdf(
                pdf=pdf,
                titulo=titulo,
                gen_date=gen_date,
                metricas=[
                    ("Ocorrências (pessoa-dia)", "0"),
                    ("Pessoas (cadastro)", "0"),
                    ("Dias com ocorrência", "0"),
                ],
                periodo=None,
                concentracoes=[
                    ("Concentração Top 1", "0 (0.0%)"),
                    ("Concentração Top 3", "0 (0.0%)"),
                    ("Concentração Top 10", "0 (0.0%)"),
                ],
                top3_piores=[],
                top3_atuais=[],
                janela_info="0 (0.0% do total)",
                extras=["Sem linhas para gerar o relatório."],
            )
            _render_metodologia_resumo_pdf(
                pdf=pdf,
                titulo_metodologia=metodologia_titulo,
                passos=metodologia_passos,
                observacoes=metodologia_observacoes,
            )
        return

    if getattr(df_irregularidade, "columns", None) is not None:
        df_irregularidade = df_irregularidade.loc[:, ~df_irregularidade.columns.duplicated()]

    titulo_norm = _norm_text(titulo)
    path_norm = _norm_text(str(pdf_path))

    excluir_planta_999_nesta_irregularidade = _deve_excluir_planta_999(
        titulo=titulo,
        pdf_path=pdf_path,
    )

    sem_corte_30 = _match_any(
        titulo_norm + " " + path_norm,
        [
            "semana de feriado prolongado",
            "feriado prolongado",
            "3 dias presenciais na semana",
            "irregularidade_pessoas_sem_cumprir_os_3_dias_presenciais_em_semana_de_feriado_prolongado",
            "pessoas_sem_cumprir_os_3_dias_presenciais_em_semana_de_feriado_prolongado",
            "executivos com historico de 999 como trajeto",
            "irregularidade_ausencia_das_horas_presenciais_minimas",
            "ausencia das horas presenciais minimas",
            "irregularidade_nao_entrou_no_refeitorio_mas_passou_no_grill",
            "nao entrou no refeitorio mas passou no grill",
        ],
    )
    somente_executivos_atuais = ("executivos com historico de 999 como trajeto" in titulo_norm)

    excluir_exec_nessas = _match_any(
        titulo_norm + " " + path_norm,
        [
            "irregularidade_registro_sem_portaria",
            "registro sem portaria",
            "irregularidade_ponto_sem_portaria",
            "ponto sem portaria",
            "irregularidade_pessoas_trabalhando_sem_ganhar",
            "pessoas trabalhando sem ganhar",
            "irregularidade_pessoas_trabalhando_alem_da_jornada_de_trabalho",
            "pessoas trabalhando alem da jornada de trabalho",
        ],
    )
    analisar_proxy_ponto = _match_any(
        titulo_norm + " " + path_norm,
        ["irregularidade_ponto_sem_portaria", "ponto sem portaria"],
    )
    if analisar_proxy_ponto and len(df_irregularidade) > 1_500_000:
        print("[INFO] Proxy de terceiros desativado nesta execução por volume alto (proteção de memória).")
        analisar_proxy_ponto = False

    analisar_heatmap_grill = _match_any(
        titulo_norm + " " + path_norm,
        [
            "irregularidade_nao_entrou_no_refeitorio_mas_passou_no_grill",
            "nao entrou no refeitorio mas passou no grill",
        ],
    )
    analisar_999_trajeto = _match_any(
        titulo_norm + " " + path_norm,
        [
            "irregularidade_999_como_trajeto",
            "999 como trajeto",
        ],
    )
    mostrar_periodo_desligado = _match_any(
        titulo_norm + " " + path_norm,
        [
            "irregularidade_registros_de_pessoas_desligadas",
            "registros de pessoas desligadas",
        ],
    )

    col_cad = _pick_col_local(df_irregularidade, ["cadastro"])
    col_nome = _pick_col_local(df_irregularidade, ["nome"])
    col_areas = "área" if "área" in df_irregularidade.columns else None
    col_area_fallback = _pick_col_local(df_irregularidade, ["area"])
    col_planta = "planta" if "planta" in df_irregularidade.columns else None
    col_heranca = "herança" if "herança" in df_irregularidade.columns else ("heranca" if "heranca" in df_irregularidade.columns else None)
    col_cargo = _pick_col_local(df_irregularidade, ["cargo", "cargo_atual"])
    col_data_dem = _pick_col_local(df_irregularidade, ["Data_Dem", "data_desligado", "DataDemissao", "data_demissao"])

    if "_dia_operacional" in df_irregularidade.columns:
        dia_op = pd.to_datetime(_as_series(df_irregularidade, "_dia_operacional"), errors="coerce")
    elif "dia_operacional" in df_irregularidade.columns:
        dia_op = pd.to_datetime(_as_series(df_irregularidade, "dia_operacional"), errors="coerce")
    else:
        data_dt = (
            pd.to_datetime(_as_series(df_irregularidade, "data"), dayfirst=True, errors="coerce")
            if "data" in df_irregularidade.columns
            else pd.Series(pd.NaT, index=df_irregularidade.index)
        )
        if "hora" not in df_irregularidade.columns:
            dia_op = data_dt.dt.normalize()
        else:
            hora_s = _as_series(df_irregularidade, "hora").fillna("00:00").astype(str).str.strip()
            hhmm_mask = hora_s.str.match(r"^\d{1,2}:\d{2}$", na=False)
            hora_s = hora_s.where(~hhmm_mask, hora_s + ":00")
            hora_td = pd.to_timedelta(hora_s, errors="coerce")
            dia_op = (data_dt.dt.normalize() + hora_td - pd.Timedelta(hours=11)).dt.normalize()

    cols_keep = ["_dia_operacional"]
    if col_cad: cols_keep.append(col_cad)
    if col_nome: cols_keep.append(col_nome)
    if col_areas: cols_keep.append(col_areas)
    elif col_area_fallback: cols_keep.append(col_area_fallback)
    if col_planta: cols_keep.append(col_planta)
    if col_heranca: cols_keep.append(col_heranca)
    if col_cargo: cols_keep.append(col_cargo)
    if col_data_dem: cols_keep.append(col_data_dem)

    dfv = df_irregularidade.loc[:, [c for c in cols_keep if c != "_dia_operacional"]].copy(deep=False)
    dfv["_dia_operacional"] = pd.to_datetime(dia_op, errors="coerce")

    if excluir_planta_999_nesta_irregularidade and col_planta and (col_planta in dfv.columns):
        dfv = dfv.loc[_mask_planta_not_999(dfv[col_planta])].copy()

    if col_cad and (col_cad in dfv.columns):
        dfv[col_cad] = dfv[col_cad].astype(str).str.strip()
        dfv = dfv[dfv[col_cad].ne("")]

    if somente_executivos_atuais and col_cargo and (col_cargo in dfv.columns):
        cargo_norm = dfv[col_cargo].fillna("").astype(str).str.strip().str.upper()
        dfv = dfv.loc[cargo_norm.eq("E")]

    if excluir_exec_nessas and col_cargo and (col_cargo in dfv.columns):
        cargo_norm2 = dfv[col_cargo].fillna("").astype(str).str.strip().str.upper()
        dfv = dfv.loc[~cargo_norm2.eq("E")]

    key_cols = [col_cad, "_dia_operacional"] if (col_cad and col_cad in dfv.columns) else ["_dia_operacional"]
    df_occ = (
        dfv.dropna(subset=["_dia_operacional"])
           .drop_duplicates(subset=key_cols, keep="first")
    )

    if df_occ.empty:
        with PdfPages(pdf_path) as pdf:
            _render_capa_padrao_pdf(
                pdf=pdf,
                titulo=titulo,
                gen_date=gen_date,
                metricas=[
                    ("Ocorrências (pessoa-dia)", "0"),
                    ("Pessoas (cadastro)", "0"),
                    ("Dias com ocorrência", "0"),
                ],
                periodo=None,
                concentracoes=[
                    ("Concentração Top 1", "0 (0.0%)"),
                    ("Concentração Top 3", "0 (0.0%)"),
                    ("Concentração Top 10", "0 (0.0%)"),
                ],
                top3_piores=[],
                top3_atuais=[],
                janela_info="0 (0.0% do total)",
                extras=["Sem ocorrências após normalização de dia operacional."],
            )
            _render_metodologia_resumo_pdf(
                pdf=pdf,
                titulo_metodologia=metodologia_titulo,
                passos=metodologia_passos,
                observacoes=metodologia_observacoes,
            )
        return

    MIN_OCORRENCIAS_PESSOA_DIA = 30
    if (not sem_corte_30) and col_cad and (col_cad in df_occ.columns):
        _cnt_pd = df_occ[col_cad].astype(str).str.strip().value_counts()
        _elig = _cnt_pd[_cnt_pd >= MIN_OCORRENCIAS_PESSOA_DIA].index
        if _elig.empty:
            with PdfPages(pdf_path) as pdf:
                _render_capa_padrao_pdf(
                    pdf=pdf,
                    titulo=titulo,
                    gen_date=gen_date,
                    metricas=[
                        ("Ocorrências (pessoa-dia)", "0"),
                        ("Pessoas (cadastro)", "0"),
                        ("Dias com ocorrência", "0"),
                    ],
                    periodo=None,
                    concentracoes=[
                        ("Concentração Top 1", "0 (0.0%)"),
                        ("Concentração Top 3", "0 (0.0%)"),
                        ("Concentração Top 10", "0 (0.0%)"),
                    ],
                    top3_piores=[],
                    top3_atuais=[],
                    janela_info="0 (0.0% do total)",
                    extras=["Sem dados suficientes (mínimo 30 ocorrências por pessoa-dia)."],
                )
                _render_metodologia_resumo_pdf(
                    pdf=pdf,
                    titulo_metodologia=metodologia_titulo,
                    passos=metodologia_passos,
                    observacoes=metodologia_observacoes,
                )
            return
        df_occ = df_occ.loc[df_occ[col_cad].astype(str).str.strip().isin(_elig)]
        if (col_cad in dfv.columns) and (not dfv.empty):
            dfv = dfv.loc[dfv[col_cad].astype(str).str.strip().isin(_elig)]

    total = int(len(df_occ))
    n_pessoas = int(df_occ[col_cad].nunique()) if (col_cad and col_cad in df_occ.columns) else 0
    n_dias = int(df_occ["_dia_operacional"].nunique())
    dt_min = df_occ["_dia_operacional"].min()
    dt_max = df_occ["_dia_operacional"].max()

    nome_map = {}
    if col_cad and col_nome and (col_cad in dfv.columns) and (col_nome in dfv.columns):
        tmp = dfv[[col_cad, col_nome]].copy()
        tmp[col_nome] = tmp[col_nome].fillna("").astype(str).str.strip()
        tmp = tmp[tmp[col_nome].ne("")]
        if not tmp.empty:
            cnt = (
                tmp.groupby([col_cad, col_nome], sort=False)
                   .size()
                   .reset_index(name="n")
                   .sort_values([col_cad, "n"], ascending=[True, False], kind="mergesort")
            )
            nome_map = cnt.drop_duplicates(subset=[col_cad], keep="first").set_index(col_cad)[col_nome].to_dict()

    periodo_desligado_map: dict[str, str] = {}
    if mostrar_periodo_desligado and col_data_dem and col_cad and (col_data_dem in dfv.columns) and (col_cad in dfv.columns):
        dem_aux = dfv[[col_cad, "_dia_operacional", col_data_dem]].copy()
        dem_aux["_dia_operacional"] = pd.to_datetime(dem_aux["_dia_operacional"], errors="coerce").dt.normalize().astype("datetime64[ns]")
        dem_aux[col_data_dem] = pd.to_datetime(dem_aux[col_data_dem], dayfirst=True, errors="coerce").dt.normalize().astype("datetime64[ns]")
        dem_aux = dem_aux.dropna(subset=[col_data_dem, "_dia_operacional"])
        if not dem_aux.empty:
            dem_aux[col_cad] = dem_aux[col_cad].astype(str).str.strip()
            dem_aux = dem_aux.loc[dem_aux[col_cad].ne("")]
            dem_aux = dem_aux.loc[dem_aux["_dia_operacional"] >= dem_aux[col_data_dem]]
            if not dem_aux.empty:
                agg_dem = (
                    dem_aux.groupby(col_cad)
                           .agg(dt_ini=(col_data_dem, "min"), dt_fim=("_dia_operacional", "max"))
                           .reset_index()
                )
                for r in agg_dem.itertuples(index=False):
                    cadk = str(getattr(r, col_cad)).strip()
                    if cadk:
                        dt_ini = pd.to_datetime(r.dt_ini, errors="coerce")
                        dt_fim = pd.to_datetime(r.dt_fim, errors="coerce")
                        if pd.notna(dt_ini) and pd.notna(dt_fim):
                            periodo_desligado_map[cadk] = f"{dt_ini.date()} → {dt_fim.date()}"
    if col_cad and (col_cad in df_occ.columns):
        cad_series = df_occ[col_cad].astype(str).str.strip()
        cad_counts = cad_series.value_counts()
        eligible_cads = cad_counts.index if sem_corte_30 else cad_counts[cad_counts >= MIN_OCORRENCIAS_PESSOA_DIA].index

        if len(eligible_cads) == 0:
            top_pessoas = pd.Series(dtype=int)
            top_pessoas_cad_counts = pd.Series(dtype=int)
        else:
            cad_series_elig = cad_series[cad_series.isin(eligible_cads)]
            top_pessoas = cad_series_elig.value_counts()
            top_pessoas_cad_counts = cad_counts.loc[eligible_cads]
    else:
        top_pessoas = pd.Series(dtype=int)
        top_pessoas_cad_counts = pd.Series(dtype=int)

    top1_n = int(top_pessoas.head(1).sum()) if (not top_pessoas.empty) else 0
    top3_n = int(top_pessoas.head(3).sum()) if (not top_pessoas.empty) else 0
    top10_n = int(top_pessoas.head(10).sum()) if (not top_pessoas.empty) else 0
    top1_pct = (top1_n / total) if total else 0.0
    top3_pct = (top3_n / total) if total else 0.0
    top10_pct = (top10_n / total) if total else 0.0

    mes = df_occ["_dia_operacional"].dt.to_period("M").dt.to_timestamp()
    mensal = mes.value_counts().sort_index()

    dow_map = {0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui", 4: "Sex", 5: "Sáb", 6: "Dom"}
    dow = (
        df_occ["_dia_operacional"].dt.dayofweek.map(dow_map)
            .value_counts()
            .reindex(["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"])
            .fillna(0).astype(int)
    )

    dt_max_norm = pd.to_datetime(dt_max).normalize()
    window_days = 30
    if pd.notna(dt_min) and pd.notna(dt_max):
        span = (pd.to_datetime(dt_max) - pd.to_datetime(dt_min)).days
        if span < 45:
            window_days = 14
        if span < 21:
            window_days = 7

    dt_cut = dt_max_norm - pd.Timedelta(days=window_days)
    recent = df_occ.loc[df_occ["_dia_operacional"] >= dt_cut]
    total_recent = int(len(recent))
    if col_cad and (col_cad in df_occ.columns) and total_recent > 0:
        cad_recent = recent[col_cad].astype(str).str.strip()
        if not sem_corte_30 and (top_pessoas_cad_counts is not None) and (not top_pessoas_cad_counts.empty):
            cad_recent = cad_recent[cad_recent.isin(top_pessoas_cad_counts.index.astype(str))]
        top_recent = cad_recent.value_counts()
    else:
        top_recent = pd.Series(dtype=int)

    def _rep_value_per_occ(df_in: pd.DataFrame, key_cols2: list[str], val_col: str) -> pd.Series:
        if (val_col is None) or (val_col not in df_in.columns):
            return pd.Series(dtype=str)
        tmp2 = df_in[key_cols2 + [val_col]].copy()
        tmp2[val_col] = tmp2[val_col].fillna("").astype(str).str.strip()
        tmp2 = tmp2[tmp2[val_col].ne("")]
        if tmp2.empty:
            return pd.Series(dtype=str)
        cnt = (
            tmp2.groupby(key_cols2 + [val_col], sort=False)
                .size()
                .reset_index(name="n")
                .sort_values(key_cols2 + ["n"], ascending=[True] * len(key_cols2) + [False], kind="mergesort")
        )
        rep = cnt.drop_duplicates(subset=key_cols2, keep="first").set_index(key_cols2)[val_col]
        return rep

    area_col_use = col_areas if col_areas else col_area_fallback
    dim_map = _get_dim_map(area_col_use, col_heranca, col_cargo)

    area_map: dict[str, str] = {}
    if isinstance(dim_map, pd.DataFrame) and (not dim_map.empty) and ("cadastro" in dim_map.columns) and ("_area_norm" in dim_map.columns):
        _area_tmp = dim_map[["cadastro", "_area_norm"]].copy(deep=False)
        _area_tmp["cadastro"] = _area_tmp["cadastro"].astype(str).str.strip()
        _area_tmp["_area_norm"] = _area_tmp["_area_norm"].fillna("").astype(str).str.strip()
        _area_tmp = _area_tmp.loc[_area_tmp["cadastro"].ne("")]
        if not _area_tmp.empty:
            area_map = _area_tmp.drop_duplicates(subset=["cadastro"], keep="last").set_index("cadastro")["_area_norm"].to_dict()

    def _top_val_por_cadastro(df_src: pd.DataFrame, cad_col: str | None, val_col: str | None) -> dict[str, str]:
        if (cad_col is None) or (val_col is None):
            return {}
        if (cad_col not in df_src.columns) or (val_col not in df_src.columns):
            return {}

        tmp = df_src[[cad_col, val_col]].copy(deep=False)
        tmp[cad_col] = tmp[cad_col].astype(str).str.strip()
        tmp[val_col] = tmp[val_col].fillna("").astype(str).str.strip()
        tmp = tmp.loc[tmp[cad_col].ne("") & tmp[val_col].ne("")]
        if tmp.empty:
            return {}

        cnt = (
            tmp.groupby([cad_col, val_col], sort=False)
               .size()
               .reset_index(name="n")
               .sort_values([cad_col, "n", val_col], ascending=[True, False, True], kind="mergesort")
        )
        top = cnt.drop_duplicates(subset=[cad_col], keep="first")
        return top.set_index(cad_col)[val_col].astype(str).to_dict()

    col_desc_coletor = _pick_col_local(
        df_irregularidade,
        ["descricao coletor", "descricao_coletor", "desc_coletor", "coletor", "descricao"],
    )

    df_caso_top_local = df_irregularidade
    coletor_top_rotulo = "Coletor top"

    if (col_desc_coletor is not None) and (col_desc_coletor in df_irregularidade.columns):
        desc_case = df_irregularidade[col_desc_coletor].fillna("").astype(str)

        if analisar_999_trajeto:
            re_port = globals().get("regex_portaria", r"PORTARIA|PORT")
            mask_case = desc_case.str.contains(re_port, case=False, na=False, regex=True)
            coletor_top_rotulo = "Portaria top"
        elif analisar_proxy_ponto:
            re_ponto = globals().get("regex_ponto", r"PONTO")
            re_port = globals().get("regex_portaria", r"PORTARIA|PORT")
            mask_case = (
                desc_case.str.contains(re_ponto, case=False, na=False, regex=True)
                & (~desc_case.str.contains(re_port, case=False, na=False, regex=True))
            )
            coletor_top_rotulo = "Ponto top"
        elif analisar_heatmap_grill:
            re_ref = globals().get("regex_refeitorio", r"REF")
            re_grill = globals().get("regex_grill", r"GRILL")
            mask_case = (
                desc_case.str.contains(re_ref, case=False, na=False, regex=True)
                & (~desc_case.str.contains(re_grill, case=False, na=False, regex=True))
            )
            coletor_top_rotulo = "Refeitório top"
        else:
            mask_case = pd.Series(True, index=df_irregularidade.index)

        df_caso_top_local = df_irregularidade.loc[mask_case].copy(deep=False)
        if df_caso_top_local.empty:
            df_caso_top_local = df_irregularidade

    top_planta_cad_map = _top_val_por_cadastro(df_caso_top_local, col_cad, col_planta)
    top_coletor_cad_map = _top_val_por_cadastro(df_caso_top_local, col_cad, col_desc_coletor)

    area_rep = pd.Series(dtype=str)
    if area_col_use and col_cad and (col_cad in dfv.columns):
        area_rep = _rep_value_per_occ(dfv, [col_cad, "_dia_operacional"], area_col_use)

    planta_rep = pd.Series(dtype=str)
    if col_planta and col_cad and (col_cad in dfv.columns):
        planta_rep = _rep_value_per_occ(dfv, [col_cad, "_dia_operacional"], col_planta)
        if not planta_rep.empty:
            _pl_str = planta_rep.astype(str).str.strip()
            _pl_num = pd.to_numeric(_pl_str, errors="coerce")
            _mask_999 = _pl_num.eq(999) | _pl_str.str.match(r"^999(\D|$)", na=False)
            planta_rep = planta_rep.loc[~_mask_999]

    combo_rep = pd.Series(dtype=str)
    if (not area_rep.empty) and (not planta_rep.empty):
        idx = area_rep.index.intersection(planta_rep.index)
        if len(idx) > 0:
            combo_rep = (area_rep.loc[idx].astype(str) + " | " + planta_rep.loc[idx].astype(str))

    top_areas = area_rep.value_counts() if not area_rep.empty else pd.Series(dtype=int)
    top_plantas = planta_rep.value_counts() if not planta_rep.empty else pd.Series(dtype=int)
    top_combo = combo_rep.value_counts() if not combo_rep.empty else pd.Series(dtype=int)

    # =========================
    # PROXY (Ponto sem Portaria):
    # - mesmo dia operacional
    # - janela de até 1 minuto
    # - exige mesma planta e mesmo número do coletor
    # =========================
    proxy_map: dict[str, dict] = {}
    proxy_top3_cads: list[str] = []
    proxy_diag = {
        "candidatos_avaliados": 0,
        "candidatos_com_eventos_elegiveis": 0,
        "eventos_elegiveis_candidatos": 0,
        "pares_proximos_tempo": 0,
        "pares_com_reforco_planta_ou_familia": 0,
        "pares_aceitos_suspeitos": 0,
        "pessoas_com_indicio": 0,
        "pessoas_com_recorrencia": 0,
    }

    if analisar_proxy_ponto and col_cad and (col_cad in df_occ.columns):
        base_all = globals().get("df_valid")
        if not isinstance(base_all, pd.DataFrame):
            base_all = globals().get("df")
        if not isinstance(base_all, pd.DataFrame):
            base_all = df_irregularidade

        desc_col = None
        if "descricao coletor" in base_all.columns:
            desc_col = "descricao coletor"
        else:
            for c in ["descricao_coletor", "desc_coletor", "coletor", "descricao"]:
                if c in base_all.columns:
                    desc_col = c
                    break

        # Se df_valid não tiver descrição do coletor, tenta a base da própria irregularidade.
        if desc_col is None and isinstance(df_irregularidade, pd.DataFrame):
            base_alt = df_irregularidade
            if "descricao coletor" in base_alt.columns:
                desc_col = "descricao coletor"
            else:
                for c in ["descricao_coletor", "desc_coletor", "coletor", "descricao"]:
                    if c in base_alt.columns:
                        desc_col = c
                        break
            if desc_col is not None and ("cadastro" in base_alt.columns):
                base_all = base_alt

        if desc_col is not None and ("cadastro" in base_all.columns):
            MAX_PROXY_CANDIDATOS = 60
            JANELA_SEGUNDOS = int(janela_proxy_minutos) * 60
            MAX_EVENTOS_POR_CANDIDATO = 3000

            if (top_pessoas_cad_counts is not None) and (not top_pessoas_cad_counts.empty):
                proxy_candidate_cads = list(top_pessoas_cad_counts.head(MAX_PROXY_CANDIDATOS).index.astype(str))
            else:
                proxy_candidate_cads = list(df_occ[col_cad].astype(str).str.strip().dropna().unique()[:MAX_PROXY_CANDIDATOS])

            proxy_diag["candidatos_avaliados"] = int(len(proxy_candidate_cads))

            base = base_all.copy(deep=False)
            # Terceiros podem ser de qualquer cargo (H/M/E).
            cad_base = base["cadastro"].astype(str).str.strip()

            if "_dt_ronda" in base.columns:
                dt_base = pd.to_datetime(base["_dt_ronda"], errors="coerce")
            else:
                dt_base = pd.to_datetime(_build_dt_from_data_hora(base), errors="coerce")

            if "_dia_operacional" in base.columns:
                dia_op_base = pd.to_datetime(base["_dia_operacional"], errors="coerce").dt.normalize()
            else:
                dia_op_base = (dt_base - pd.Timedelta(hours=11)).dt.normalize()

            if "planta" in base.columns:
                pl_base = pd.to_numeric(base["planta"], errors="coerce")
            else:
                pl_base = pd.Series(np.nan, index=base.index)

            desc_base = base[desc_col].fillna("").astype(str).str.strip()

            def _proxy_num_coletor_series(s: pd.Series) -> pd.Series:
                txt = s.fillna("").astype(str).str.strip().str.upper()
                txt = txt.apply(lambda v: unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode("ascii"))
                num = txt.str.extract(r"(?:COLETOR|CATRACA|RELOGIO(?:\s*PONTO)?|PONTO|MARCA)\D*([0-9]{1,6})", expand=False)
                num_fallback = txt.str.extract(r"\b([0-9]{1,6})\b", expand=False)
                num = num.fillna(num_fallback)
                return num.fillna("").astype(str).str.strip()

            coletor_base = _proxy_num_coletor_series(desc_base)

            point_mask = pd.Series(False, index=base.index)
            for bc in ["Ponto", "PONTO", "_PONTO", "_PONTO_PRESENCIAL", "PONTO_PRES", "HAS_PONTO_PRES", "PontoPresencial"]:
                if bc in base.columns and pd.api.types.is_bool_dtype(base[bc]):
                    point_mask = point_mask | base[bc].fillna(False)
            if not point_mask.any():
                point_mask = desc_base.str.contains(r"\bponto\b|rel[oó]gio|marca", case=False, na=False, regex=True)

            port_mask = pd.Series(False, index=base.index)
            for bc in ["Portaria", "PORTARIA", "_PORTARIA", "HAS_PORTARIA_ANY"]:
                if bc in base.columns and pd.api.types.is_bool_dtype(base[bc]):
                    port_mask = port_mask | base[bc].fillna(False)
            if not port_mask.any():
                _re_port = globals().get("regex_portaria", r"PORTARIA|PORT")
                port_mask = desc_base.str.contains(_re_port, case=False, na=False, regex=True)

            port_day_mask = port_mask & dia_op_base.notna() & cad_base.ne("")
            if port_day_mask.any():
                port_cad_arr = cad_base.loc[port_day_mask].astype(str).str.strip().to_numpy(dtype=object)
                port_day_arr = pd.to_datetime(dia_op_base.loc[port_day_mask], errors="coerce").to_numpy(dtype="datetime64[D]").astype(np.int64)
                portaria_day_set = set(zip(port_cad_arr.tolist(), port_day_arr.tolist()))
            else:
                portaria_day_set = set()

            base_mask = point_mask & dt_base.notna() & dia_op_base.notna() & cad_base.ne("")

            if base_mask.any():
                ev = pd.DataFrame({
                    "cad": cad_base.loc[base_mask].astype(str).str.strip().to_numpy(),
                    "dt": pd.to_datetime(dt_base.loc[base_mask], errors="coerce").to_numpy(dtype="datetime64[ns]"),
                    "dia_op": pd.to_datetime(dia_op_base.loc[base_mask], errors="coerce").to_numpy(dtype="datetime64[ns]"),
                    "planta": pd.to_numeric(pl_base.loc[base_mask], errors="coerce").to_numpy(dtype=float),
                    "coletor_num": coletor_base.loc[base_mask].fillna("").astype(str).str.strip().to_numpy(dtype=object),
                })

                ev = ev.dropna(subset=["dt", "dia_op"]).copy()
                if not ev.empty:
                    ev["sec"] = (ev["dt"].astype("int64") // 1_000_000_000).astype(np.int64)
                    ev["dia_i"] = pd.to_datetime(ev["dia_op"], errors="coerce").to_numpy(dtype="datetime64[D]").astype(np.int64)
                    ev["planta_i"] = pd.to_numeric(ev["planta"], errors="coerce")
                    ev["coletor_num"] = ev["coletor_num"].fillna("").astype(str).str.strip()

                    day_groups: dict[int, dict[str, np.ndarray]] = {}
                    for day_i, g in ev.groupby("dia_i", sort=False):
                        g = g.sort_values("sec", kind="mergesort")
                        day_groups[int(day_i)] = {
                            "sec": g["sec"].to_numpy(dtype=np.int64, copy=False),
                            "cad": g["cad"].to_numpy(dtype=object, copy=False),
                            "planta": pd.to_numeric(g["planta_i"], errors="coerce").to_numpy(dtype=float, copy=False),
                            "coletor": g["coletor_num"].to_numpy(dtype=object, copy=False),
                        }

                    counts: dict[str, dict[str, int]] = {str(c): {} for c in proxy_candidate_cads}

                    for cad0 in proxy_candidate_cads:
                        ev0 = ev.loc[ev["cad"].eq(str(cad0)), ["dia_i", "sec", "planta_i", "coletor_num"]]
                        if ev0.empty:
                            continue

                        proxy_diag["candidatos_com_eventos_elegiveis"] += 1
                        proxy_diag["eventos_elegiveis_candidatos"] += int(len(ev0))

                        if len(ev0) > MAX_EVENTOS_POR_CANDIDATO:
                            ev0 = ev0.sort_values("sec", kind="mergesort").head(MAX_EVENTOS_POR_CANDIDATO)

                        dct = counts.setdefault(str(cad0), {})

                        for day_i, g0 in ev0.groupby("dia_i", sort=False):
                            day_data = day_groups.get(int(day_i))
                            if day_data is None:
                                continue

                            sec_day = day_data["sec"]
                            cad_day = day_data["cad"]
                            pl_day = day_data["planta"]
                            coletor_day = day_data["coletor"]

                            for row in g0.itertuples(index=False):
                                sec0 = int(row.sec)
                                l = int(np.searchsorted(sec_day, sec0 - JANELA_SEGUNDOS, side="left"))
                                r = int(np.searchsorted(sec_day, sec0 + JANELA_SEGUNDOS, side="right"))
                                if r <= l:
                                    continue

                                sec_sub = sec_day[l:r]
                                cad_sub = cad_day[l:r]
                                pl_sub = pl_day[l:r]
                                coletor_sub = coletor_day[l:r]

                                mask_other = np.array([str(c).strip() != str(cad0) for c in cad_sub], dtype=bool)
                                if not mask_other.any():
                                    continue

                                sec_other = sec_sub[mask_other]
                                cad_other = cad_sub[mask_other]
                                pl_other = pl_sub[mask_other]
                                coletor_other = coletor_sub[mask_other]

                                dif = np.abs(sec_other - sec0)
                                proxy_diag["pares_proximos_tempo"] += int(len(dif))

                                pl0 = pd.to_numeric(row.planta_i, errors="coerce")
                                coletor0 = str(row.coletor_num).strip()

                                same_planta = (~np.isnan(pl_other)) & (not pd.isna(pl0)) & (pl_other == float(pl0))
                                same_coletor = np.array(
                                    [(str(c).strip() != "") and (str(c).strip() == coletor0) and (coletor0 != "") for c in coletor_other],
                                    dtype=bool,
                                )

                                same_planta_coletor = same_planta & same_coletor
                                # Mantém chave legada por compatibilidade com o funil já existente.
                                proxy_diag["pares_com_reforco_planta_ou_familia"] += int(same_planta_coletor.sum())

                                # Aceita somente quando TODAS as condições forem verdadeiras:
                                # <= 3 minuto, mesma planta e mesmo número do coletor.
                                has_portaria_other = np.array(
                                    [((str(c).strip(), int(day_i)) in portaria_day_set) for c in cad_other],
                                    dtype=bool,
                                )
                                accepted = (dif <= JANELA_SEGUNDOS) & same_planta_coletor & has_portaria_other
                                if not accepted.any():
                                    continue

                                proxy_diag["pares_aceitos_suspeitos"] += int(accepted.sum())
                                for cad_other_i in cad_other[accepted]:
                                    cad_o = str(cad_other_i).strip()
                                    if cad_o == "" or cad_o == str(cad0):
                                        continue
                                    dct[cad_o] = dct.get(cad_o, 0) + 1

                    for cad0, dct in counts.items():
                        if not dct:
                            continue

                        top_other = sorted(dct.items(), key=lambda x: (-x[1], x[0]))[:10]
                        total_hits = int(sum(dct.values()))
                        max_hits_mesmo_terceiro = int(top_other[0][1]) if top_other else 0

                        proxy_map[str(cad0)] = {
                            "top_other": [(k, int(v)) for k, v in top_other],
                            "score_total_proxy": total_hits,
                            "qtd_terceiros": int(len(dct)),
                            "max_hits_mesmo_terceiro": max_hits_mesmo_terceiro,
                        }

                    proxy_diag["pessoas_com_indicio"] = int(len(proxy_map))
                    proxy_diag["pessoas_com_recorrencia"] = int(
                        sum(1 for _cad, info in proxy_map.items() if int(info.get("max_hits_mesmo_terceiro", 0)) >= 2)
                    )

                    if proxy_map:
                        def _cad_volume(cad: str) -> int:
                            if (top_pessoas_cad_counts is None) or top_pessoas_cad_counts.empty:
                                return 0
                            try:
                                return int(top_pessoas_cad_counts.get(cad, 0))
                            except Exception:
                                return 0

                        proxy_top3_cads = [
                            cad for cad, _info in sorted(
                                proxy_map.items(),
                                key=lambda kv: (
                                    -int(kv[1].get("score_total_proxy", 0)),        # 1) total de ocorrências suspeitas
                                    -int(kv[1].get("max_hits_mesmo_terceiro", 0)), # 2) repetição do mesmo terceiro
                                    -_cad_volume(kv[0]),                           # 3) volume total da pessoa
                                    str(kv[0]),
                                )
                            )[:3]
                        ]

    def _fmt_pessoa_rm_nome_area(cad: str) -> str:
        cad = str(cad).strip()
        nome_raw = str(nome_map.get(cad, "")).strip() if nome_map else ""
        if nome_raw:
            parts = [p for p in nome_raw.split() if p]
            if len(parts) == 1:
                nome_abv = parts[0]
            else:
                nome_abv = f"{parts[0]} {parts[-1][0]}."
        else:
            nome_abv = "-"

        area_txt = str(area_map.get(cad, "")).strip() if area_map else ""
        if area_txt == "":
            area_txt = "-"

        planta_top = str(top_planta_cad_map.get(cad, "")).strip() if top_planta_cad_map else ""
        if planta_top == "":
            planta_top = "-"

        coletor_top = str(top_coletor_cad_map.get(cad, "")).strip() if top_coletor_cad_map else ""
        if coletor_top == "":
            coletor_top = "-"

        return f"RM {cad} | {nome_abv} | {area_txt} | Planta top: {planta_top} | {coletor_top_rotulo}: {coletor_top}"

    # =========================
    # PDF
    # =========================
    with PdfPages(pdf_path) as pdf:
        # CAPA (padrão único em tópicos)
        top3_piores_capa = []
        for k, v in top_pessoas.head(3).items():
            pct = (int(v) / total) if total else 0.0
            top3_piores_capa.append(f"{_wrap(_fmt_pessoa_rm_nome_area(str(k)), 60)} — {int(v)} ({pct:.1%})")

        top3_atuais_capa = []
        for k, v in top_recent.head(3).items():
            pct = (int(v) / total_recent) if total_recent else 0.0
            top3_atuais_capa.append(f"{_wrap(_fmt_pessoa_rm_nome_area(str(k)), 60)} — {int(v)} ({pct:.1%} da janela)")

        metricas_capa = [
            ("Ocorrências (pessoa-dia)", f"{total:,}".replace(",", ".")),
            ("Pessoas (cadastro)", f"{n_pessoas:,}".replace(",", ".")),
            ("Dias com ocorrência", f"{n_dias:,}".replace(",", ".")),
        ]
        periodo_capa = (
            f"{pd.to_datetime(dt_min).date()} → {pd.to_datetime(dt_max).date()}"
            if pd.notna(dt_min) and pd.notna(dt_max) else None
        )
        concentracoes_capa = [
            ("Concentração Top 1", f"{top1_n:,} ({top1_pct:.1%})".replace(",", ".")),
            ("Concentração Top 3", f"{top3_n:,} ({top3_pct:.1%})".replace(",", ".")),
            ("Concentração Top 10", f"{top10_n:,} ({top10_pct:.1%})".replace(",", ".")),
        ]
        janela_info = (
            f"{total_recent:,} ({(total_recent / total):.1%} do total)".replace(",", ".")
            if total > 0 else "0 (0.0% do total)"
        )

        _render_capa_padrao_pdf(
            pdf=pdf,
            titulo=titulo,
            gen_date=gen_date,
            metricas=metricas_capa,
            periodo=periodo_capa,
            concentracoes=concentracoes_capa,
            top3_piores=top3_piores_capa,
            top3_atuais=top3_atuais_capa,
            janela_info=janela_info,
        )
        _render_metodologia_resumo_pdf(
            pdf=pdf,
            titulo_metodologia=metodologia_titulo,
            passos=metodologia_passos,
            observacoes=metodologia_observacoes,
        )

        # GERAIS
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.69, 8.27), gridspec_kw={"height_ratios": [2.1, 1.3]})
        if mensal.empty:
            ax1.axis("off")
            ax1.text(0.02, 0.95, "Tendência mensal", fontsize=16, fontweight="bold", va="top")
            ax1.text(0.02, 0.80, "Sem datas válidas para agregação mensal.", fontsize=12, va="top")
        else:
            ax1.plot(mensal.index, mensal.values, marker="o", linewidth=2.1)
            ax1.fill_between(mensal.index, mensal.values, alpha=0.15)
            ax1.set_title("Tendência mensal (ocorrências pessoa-dia)")
            ax1.set_ylabel("Ocorrências")
            ax1.grid(alpha=0.25)

        ax2.set_title("Distribuição por dia da semana (heatmap)")
        dow_total = float(dow.values.sum()) if dow.values.size else 0.0
        if dow_total > 0:
            dow_pct = (dow.astype(float) / dow_total * 100.0)
        else:
            dow_pct = dow.astype(float)

        dow_mat = np.expand_dims(dow_pct.values.astype(float), axis=0)
        im_dow = ax2.imshow(
            dow_mat,
            aspect="auto",
            cmap="Blues",
            vmin=0.0,
            vmax=max(float(dow_pct.max()), 1.0),
        )
        ax2.set_yticks([0])
        ax2.set_yticklabels(["%"])
        ax2.set_xticks(range(len(dow_pct.index)))
        ax2.set_xticklabels(list(dow_pct.index))
        ax2.set_xlabel("Dia da semana")

        for xi, vv in enumerate(dow_pct.values.astype(float)):
            if vv <= 0:
                continue
            ax2.text(xi, 0, f"{vv:.1f}%", ha="center", va="center", fontsize=9)

        cbar_dow = fig.colorbar(im_dow, ax=ax2, fraction=0.03, pad=0.03)
        cbar_dow.set_label("% de ocorrências")
        plt.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

        def _page_top_series(title: str, ser: pd.Series, max_items: int = 12):
            fig = plt.figure(figsize=(11.69, 8.27))
            ax = fig.add_subplot(111)
            if ser is None or ser.empty:
                ax.axis("off")
                ax.text(0.02, 0.95, title, fontsize=16, fontweight="bold", va="top")
                ax.text(0.02, 0.80, "Sem dados suficientes.", fontsize=12, va="top")
                pdf.savefig(fig)
                plt.close(fig)
                return

            s = ser.head(max_items)
            den = float(ser.sum())
            if den > 0:
                s_pct = (s.astype(float) / den * 100.0)
            else:
                s_pct = s.astype(float)

            y_pos = np.arange(len(s_pct))
            labels = [_wrap(x, 60) for x in s_pct.index.astype(str)]
            vals = s_pct.values.astype(float)

            ax.barh(y_pos, vals, height=0.8)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(labels)
            ax.invert_yaxis()
            ax.set_title(title)
            ax.set_xlabel("% do total (pessoa-dia)")
            ax.grid(axis="x", alpha=0.25)

            xmax = max(float(vals.max()) * 1.22, 1.0)
            ax.set_xlim(0, xmax)
            for i, v in enumerate(vals):
                vv = float(v)
                if vv <= 0:
                    continue
                x = min(vv + xmax * 0.012, xmax * 0.985)
                ha = "left" if x < xmax * 0.96 else "right"
                ax.text(x, i, f"{vv:.1f}%", va="center", ha=ha, fontsize=9)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

        def _nome_abreviado(nome: str) -> str:
            nome = " ".join(str(nome).strip().split())
            if not nome:
                return "-"
            parts = [p for p in nome.split(" ") if p]
            if len(parts) == 1:
                return parts[0]
            return f"{parts[0]} {parts[-1][0]}."

        def _cad_label_basico(cad: str) -> str:
            cad = str(cad).strip()
            nome_txt = _nome_abreviado(str(nome_map.get(cad, "")).strip() if nome_map else "")
            area_txt = str(area_map.get(cad, "")).strip() if area_map else ""
            if area_txt == "":
                area_txt = "-"
            return f"RM {cad} | {nome_txt} | {area_txt}"

        def _cad_label(cad: str) -> str:
            return _fmt_pessoa_rm_nome_area(cad)

        def _cad_proxy_label(cad: str) -> str:
            return _cad_label_basico(cad)

        def _page_top3_volume_pessoas():
            fig = plt.figure(figsize=(11.69, 8.27))
            ax = fig.add_subplot(111)

            if (top_pessoas_cad_counts is None) or top_pessoas_cad_counts.empty:
                ax.axis("off")
                ax.text(0.02, 0.95, "Top 3 pessoas — volume de ocorrências", fontsize=16, fontweight="bold", va="top")
                ax.text(0.02, 0.80, "Sem dados suficientes.", fontsize=12, va="top")
                pdf.savefig(fig)
                plt.close(fig)
                return

            s = top_pessoas_cad_counts.head(3).copy()
            s.index = [_cad_label(c) for c in s.index.astype(str)]

            y_pos = np.arange(len(s))
            vals = s.values.astype(float)

            ax.barh(y_pos, vals, height=0.7)
            ax.set_yticks(y_pos)
            ax.set_yticklabels([_wrap(x, 60) for x in s.index.astype(str)])
            ax.invert_yaxis()
            ax.set_title("Top 3 pessoas — volume de ocorrências")
            ax.set_xlabel("Ocorrências (pessoa-dia)")
            ax.grid(axis="x", alpha=0.25)

            xmax = max(float(vals.max()) * 1.20, 1.0)
            ax.set_xlim(0, xmax)

            for i, v in enumerate(vals):
                pct = (float(v) / total * 100.0) if total else 0.0
                ax.text(min(v + xmax * 0.015, xmax * 0.98), i, f"{int(v)} ({pct:.1f}%)", va="center", fontsize=9)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

        def _page_top3_percentual_pessoas():
            fig = plt.figure(figsize=(11.69, 8.27))
            ax = fig.add_subplot(111)

            if (top_pessoas_cad_counts is None) or top_pessoas_cad_counts.empty or total <= 0:
                ax.axis("off")
                ax.text(0.02, 0.95, "Top 3 pessoas — percentual sobre o total", fontsize=16, fontweight="bold", va="top")
                ax.text(0.02, 0.80, "Sem dados suficientes.", fontsize=12, va="top")
                pdf.savefig(fig)
                plt.close(fig)
                return

            s_counts = top_pessoas_cad_counts.head(3).copy()
            s_pct = (s_counts / total * 100.0).round(2)
            s_pct.index = [_cad_label(c) for c in s_pct.index.astype(str)]

            y_pos = np.arange(len(s_pct))
            vals = s_pct.values.astype(float)

            ax.barh(y_pos, vals, height=0.7)
            ax.set_yticks(y_pos)
            ax.set_yticklabels([_wrap(x, 60) for x in s_pct.index.astype(str)])
            ax.invert_yaxis()
            ax.set_title("Top 3 pessoas — percentual sobre o total")
            ax.set_xlabel("% do total de ocorrências")
            ax.grid(axis="x", alpha=0.25)

            xmax = max(float(vals.max()) * 1.20, 1.0)
            ax.set_xlim(0, xmax)

            for i, (pct_v, count_v) in enumerate(zip(vals, s_counts.values.astype(int))):
                ax.text(min(pct_v + xmax * 0.015, xmax * 0.98), i, f"{pct_v:.1f}% ({int(count_v)} ocorr.)", va="center", fontsize=9)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

        def _page_top3_proxy_pessoas():
            cor_principal = "#0B5FA5"
            cor_contorno = "#001E50"

            diag_lines = [
                f"Candidatos avaliados: {int(proxy_diag.get('candidatos_avaliados', 0))}",
                f"Candidatos com eventos elegíveis: {int(proxy_diag.get('candidatos_com_eventos_elegiveis', 0))}",
                f"Eventos elegíveis (candidatos): {int(proxy_diag.get('eventos_elegiveis_candidatos', 0))}",
                f"Pares próximos no tempo (<= {int(janela_proxy_minutos)} min): {int(proxy_diag.get('pares_proximos_tempo', 0))}",
                f"Pares com mesma planta + coletor: {int(proxy_diag.get('pares_com_reforco_planta_ou_familia', 0))}",
                f"Pares aceitos como suspeitos: {int(proxy_diag.get('pares_aceitos_suspeitos', 0))}",
                f"Pessoas com indício: {int(proxy_diag.get('pessoas_com_indicio', 0))}",
                f"Pessoas com recorrência (mesmo terceiro >=2): {int(proxy_diag.get('pessoas_com_recorrencia', 0))}",
            ]

            fig = plt.figure(figsize=(11.69, 8.27))
            gs = fig.add_gridspec(1, 2, width_ratios=[1.10, 1.35], wspace=0.28)
            ax_info = fig.add_subplot(gs[0, 0])
            ax_rank = fig.add_subplot(gs[0, 1])

            ax_info.axis("off")
            fig.suptitle(
                "Ponto sem Portaria - Ranking de indício de terceiros",
                fontsize=16,
                fontweight="bold",
                y=0.985,
            )

            y = 0.96
            ax_info.text(0.00, y, "Como ler este bloco", fontsize=12.5, fontweight="bold", va="top"); y -= 0.07
            ax_info.text(0.00, y, f"Regra aplicada: <= {int(janela_proxy_minutos)} min, mesma planta, mesmo coletor e terceiro com portaria no dia.", fontsize=10.2, va="top", wrap=True); y -= 0.12
            ax_info.text(0.00, y, "Funil da detecção", fontsize=12.0, fontweight="bold", va="top"); y -= 0.05
            ax_info.text(0.00, y, "\n".join([f"- {x}" for x in diag_lines]), fontsize=9.8, va="top")

            if (not analisar_proxy_ponto) or (not proxy_top3_cads):
                ax_rank.axis("off")
                ax_rank.text(0.02, 0.90, "Sem casos suficientes para formar o Top 3.", fontsize=12, va="top")
                pdf.savefig(fig)
                plt.close(fig)
                return

            data_proxy = []
            for cad in proxy_top3_cads[:3]:
                info = proxy_map.get(str(cad), {})
                data_proxy.append({
                    "cad": str(cad),
                    "label": _cad_label(str(cad)),
                    "score": int(info.get("score_total_proxy", 0)),
                    "qtd_terceiros": int(info.get("qtd_terceiros", 0)),
                    "max_mesmo_terceiro": int(info.get("max_hits_mesmo_terceiro", 0)),
                })

            df_proxy = pd.DataFrame(data_proxy)
            if df_proxy.empty:
                ax_rank.axis("off")
                ax_rank.text(0.02, 0.90, "Sem dados suficientes para ranking.", fontsize=12, va="top")
                pdf.savefig(fig)
                plt.close(fig)
                return

            y_pos = np.arange(len(df_proxy))
            vals = df_proxy["score"].to_numpy(dtype=float)

            ax_rank.barh(y_pos, vals, height=0.62, color=cor_principal, edgecolor=cor_contorno, linewidth=1.0)
            ax_rank.set_yticks(y_pos)
            ax_rank.set_yticklabels([_wrap(x, 52) for x in df_proxy["label"].astype(str)])
            ax_rank.invert_yaxis()
            ax_rank.set_title("Top 3 por volume suspeito")
            ax_rank.set_xlabel("Ocorrências suspeitas por terceiros")
            ax_rank.grid(axis="x", alpha=0.25)

            xmax = max(float(vals.max()) * 1.22, 1.0)
            ax_rank.set_xlim(0, xmax)

            for i, r in enumerate(df_proxy.itertuples(index=False)):
                txt = f"{int(r.score)} suspeitas | {int(r.qtd_terceiros)} terceiros | máx. repetição {int(r.max_mesmo_terceiro)}"
                ax_rank.text(min(float(r.score) + xmax * 0.015, xmax * 0.98), i, txt, va="center", fontsize=9.0)

            plt.tight_layout(rect=[0, 0, 1, 0.96])
            pdf.savefig(fig)
            plt.close(fig)

        def _page_proxy_individual_top3():
            if (not analisar_proxy_ponto) or (not proxy_top3_cads):
                return

            cor_principal = "#0B5FA5"
            cor_contorno = "#001E50"
            total_proxy_pairs = int(proxy_diag.get("pares_aceitos_suspeitos", 0))
            periodo_txt = (
                f"{pd.to_datetime(dt_min).date()} → {pd.to_datetime(dt_max).date()}"
                if pd.notna(dt_min) and pd.notna(dt_max) else "-"
            )

            cnt_pessoas = top_pessoas_cad_counts.copy() if isinstance(top_pessoas_cad_counts, pd.Series) else pd.Series(dtype=int)
            if not cnt_pessoas.empty:
                cnt_pessoas.index = cnt_pessoas.index.astype(str)

            for pos, cad in enumerate(proxy_top3_cads[:3], start=1):
                cad_s = str(cad).strip()
                info = proxy_map.get(cad_s, {})
                score_total = int(info.get("score_total_proxy", 0))
                qtd_terceiros = int(info.get("qtd_terceiros", 0))
                max_mesmo = int(info.get("max_hits_mesmo_terceiro", 0))
                total_occ_pessoa = int(cnt_pessoas.get(cad_s, 0)) if not cnt_pessoas.empty else 0
                pct_proxy = (score_total / total_proxy_pairs) if total_proxy_pairs else 0.0

                top_other = list(info.get("top_other", []))[:6]

                fig = plt.figure(figsize=(11.69, 8.27))
                gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.35], wspace=0.30)
                ax_info = fig.add_subplot(gs[0, 0])
                ax_bar = fig.add_subplot(gs[0, 1])
                ax_info.axis("off")

                fig.suptitle(
                    f"Ponto sem Portaria - Caso individual {pos}º | {_wrap(_cad_label(cad_s), 74)}",
                    fontsize=14.4,
                    fontweight="bold",
                    y=0.985,
                )

                y = 0.95
                ax_info.text(0.00, y, "Resumo rápido", fontsize=12.8, fontweight="bold", va="top"); y -= 0.07
                ax_info.text(0.00, y, f"Período analisado: {periodo_txt}", fontsize=10.4, va="top"); y -= 0.055
                ax_info.text(0.00, y, f"Volume suspeito de terceiros: {score_total}", fontsize=10.8, va="top"); y -= 0.055
                ax_info.text(0.00, y, f"Participação no funil: {pct_proxy:.1%}", fontsize=10.8, va="top"); y -= 0.055
                ax_info.text(0.00, y, f"Terceiros distintos: {qtd_terceiros}", fontsize=10.8, va="top"); y -= 0.055
                ax_info.text(0.00, y, f"Máx. repetições do mesmo terceiro: {max_mesmo}", fontsize=10.8, va="top"); y -= 0.055
                ax_info.text(0.00, y, f"Ocorrências totais da pessoa (pessoa-dia): {total_occ_pessoa}", fontsize=10.4, va="top"); y -= 0.08
                ax_info.text(0.00, y, "Critério de detecção", fontsize=11.6, fontweight="bold", va="top"); y -= 0.045
                ax_info.text(0.00, y, f"<= {int(janela_proxy_minutos)} min | mesma planta | mesmo coletor | terceiro com portaria no dia", fontsize=9.6, va="top", wrap=True)

                if not top_other:
                    ax_bar.axis("off")
                    ax_bar.text(0.02, 0.92, "Terceiros relacionados", fontsize=12.2, fontweight="bold", va="top")
                    ax_bar.text(0.02, 0.78, "Sem correspondências suficientes para detalhar.", fontsize=10.6, va="top")
                else:
                    labels = [_wrap(_cad_proxy_label(k), 50) for k, _v in top_other]
                    vals = np.array([int(v) for _k, v in top_other], dtype=float)
                    y_pos = np.arange(len(vals))

                    ax_bar.barh(y_pos, vals, color=cor_principal, edgecolor=cor_contorno, linewidth=1.0)
                    ax_bar.set_yticks(y_pos)
                    ax_bar.set_yticklabels(labels)
                    ax_bar.invert_yaxis()
                    ax_bar.set_title("Top terceiros relacionados (Top 6)")
                    ax_bar.set_xlabel("Qtd de pares suspeitos")
                    ax_bar.grid(axis="x", alpha=0.25)

                    xmax = max(float(vals.max()) * 1.22, 1.0)
                    ax_bar.set_xlim(0, xmax)
                    for i, v in enumerate(vals):
                        pct_v = (float(v) / score_total) if score_total else 0.0
                        ax_bar.text(min(float(v) + xmax * 0.015, xmax * 0.98), i, f"{int(v)} ({pct_v:.1%})", va="center", fontsize=9.0)

                plt.tight_layout(rect=[0, 0, 1, 0.96])
                pdf.savefig(fig)
                plt.close(fig)

        _page_top_series("Top áreas (representatividade por pessoa-dia)", top_areas)
        _page_top_series("Top plantas (representatividade por pessoa-dia) — exclui planta 999", top_plantas)
        _page_top_series("Top área | planta (representatividade por pessoa-dia) — exclui planta 999", top_combo)

        _page_top3_volume_pessoas()
        _page_top3_percentual_pessoas()
        if analisar_proxy_ponto:
            _page_top3_proxy_pessoas()
            _page_proxy_individual_top3()

        # TOP 3 por volume (analise individual)
        # - Demais irregularidades: período total + últimos 30 dias (até 6 páginas)
        # - 999 como trajeto: somente período total (3 casos individuais)
        if col_cad and (col_cad in df_occ.columns) and (top_pessoas_cad_counts is not None) and (not top_pessoas_cad_counts.empty):
            cad_irreg_set = set(df_occ[col_cad].astype(str).str.strip().unique())

            dt_end = pd.to_datetime(dt_max).normalize() if pd.notna(dt_max) else pd.Timestamp.today().normalize()
            dt_start_30 = dt_end - pd.Timedelta(days=29)
            idx_30 = pd.date_range(dt_start_30, dt_end, freq="D")

            df_occ_ctx_total = df_occ.loc[:, [col_cad, "_dia_operacional"]].copy()
            df_occ_ctx_total[col_cad] = df_occ_ctx_total[col_cad].astype(str).str.strip()
            df_occ_ctx_total = df_occ_ctx_total.loc[df_occ_ctx_total[col_cad].ne("")].copy()

            df_occ_ctx_30 = df_occ_ctx_total.loc[
                (df_occ_ctx_total["_dia_operacional"] >= dt_start_30) &
                (df_occ_ctx_total["_dia_operacional"] <= dt_end)
            ].copy()

            cad_counts_30 = df_occ_ctx_30[col_cad].value_counts()
            if (not sem_corte_30):
                eligible_idx = top_pessoas_cad_counts.index.astype(str)
                cad_counts_30 = cad_counts_30.loc[cad_counts_30.index.isin(eligible_idx)]

            top3_total_cads = list(top_pessoas_cad_counts.head(3).index.astype(str))
            top3_30_cads = list(cad_counts_30.head(3).index.astype(str))

            if analisar_999_trajeto:
                ctx_specs = [
                    ("Período total", top3_total_cads, df_occ_ctx_total, f"{pd.to_datetime(dt_min).date()} → {pd.to_datetime(dt_max).date()}"),
                ]
            else:
                ctx_specs = [
                    ("Período total", top3_total_cads, df_occ_ctx_total, f"{pd.to_datetime(dt_min).date()} → {pd.to_datetime(dt_max).date()}"),
                    ("Últimos 30 dias", top3_30_cads, df_occ_ctx_30, f"{pd.to_datetime(dt_start_30).date()} → {pd.to_datetime(dt_end).date()}"),
                ]

            for ctx_nome, cads_ctx, df_ctx, janela_ctx_txt in ctx_specs:
                if not cads_ctx:
                    continue

                cad_counts_ctx = df_ctx[col_cad].value_counts()
                top10_cads_ctx = list(cad_counts_ctx.head(10).index.astype(str))
                top10_total_ctx = int(cad_counts_ctx.loc[top10_cads_ctx].sum()) if top10_cads_ctx else 0
                total_ctx = int(len(df_ctx))

                for pos_ctx, cad in enumerate(cads_ctx, start=1):
                    occ_p = df_ctx.loc[df_ctx[col_cad].eq(str(cad)), ["_dia_operacional"]]
                    if occ_p.empty:
                        continue

                    total_p = int(len(occ_p))
                    pct_p_total = (total_p / total_ctx) if total_ctx else 0.0
                    label = _cad_label(str(cad))

                    days = occ_p["_dia_operacional"].dt.normalize()
                    week_start = (days - pd.to_timedelta(days.dt.dayofweek, unit="D")).dt.normalize()
                    weekly_days = week_start.value_counts().sort_index()
                    mensal_semana = (
                        weekly_days.groupby(weekly_days.index.to_period("M").to_timestamp(), sort=False)
                                   .mean()
                                   .sort_index()
                        if not weekly_days.empty else pd.Series(dtype=float)
                    )

                    # Contagem diária de ocorrência (pessoa-dia), nunca por número de linhas.
                    daily_30 = (
                        occ_p.groupby(occ_p["_dia_operacional"].dt.normalize(), sort=False)
                             .size()
                             .reindex(idx_30, fill_value=0)
                    )

                    pct_vs_top10 = (total_p / top10_total_ctx) if top10_total_ctx else 0.0

                    area_val = None
                    her_val = None
                    if isinstance(dim_map, pd.DataFrame) and (not dim_map.empty) and ("cadastro" in dim_map.columns):
                        row_dim = dim_map.loc[dim_map["cadastro"].eq(str(cad))]
                        if not row_dim.empty:
                            area_val = row_dim["_area_norm"].iloc[0] or None
                            her_val = row_dim["_her_norm"].iloc[0] or None

                    grp_total = grp_with = grp_without = None
                    if (area_val is not None) and (her_val is not None) and isinstance(dim_map, pd.DataFrame) and (not dim_map.empty):
                        grp_cads = dim_map.loc[
                            dim_map["_area_norm"].eq(str(area_val)) & dim_map["_her_norm"].eq(str(her_val)),
                            "cadastro"
                        ].to_numpy()
                        grp_total = int(len(grp_cads))
                        if grp_total > 0:
                            grp_with = int(np.isin(grp_cads, list(cad_irreg_set)).sum())
                            grp_without = int(grp_total - grp_with)

                    other_days = int(max(total_ctx - total_p, 0))

                    fig = plt.figure(figsize=(11.69, 8.27))
                    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.0], wspace=0.38, hspace=0.48)

                    ax1 = fig.add_subplot(gs[0, 0])
                    ax2 = fig.add_subplot(gs[0, 1])
                    ax3 = fig.add_subplot(gs[0, 2])
                    ax4 = fig.add_subplot(gs[1, 0])
                    ax5 = fig.add_subplot(gs[1, 1])
                    ax6 = fig.add_subplot(gs[1, 2])
                    ax6.axis("off")

                    if analisar_999_trajeto and (ctx_nome == "Período total"):
                        titulo_individual = (
                            f"999 como trajeto  Caso individual {pos_ctx}º (período total) | "
                            f"{_wrap(label, 70)} | Total (pessoa-dia): {total_p} ({pct_p_total:.1%} do contexto)"
                        )
                    else:
                        titulo_individual = (
                            f"{ctx_nome} | Top 3 ({pos_ctx}º) — {_wrap(label, 70)} | "
                            f"Total (pessoa-dia): {total_p} ({pct_p_total:.1%} do contexto)"
                        )

                    fig.suptitle(
                        titulo_individual,
                        fontsize=14.2,
                        fontweight="bold",
                        y=0.985,
                    )

                    if mensal_semana.empty:
                        ax1.axis("off")
                        ax1.text(0.02, 0.92, "Dias com ocorrência na semana (mensal)", fontsize=11.5, fontweight="bold", va="top")
                        ax1.text(0.02, 0.78, "Sem dados suficientes.", fontsize=10, va="top")
                    else:
                        ax1.plot(mensal_semana.index, mensal_semana.values, marker="o", linewidth=2.0)
                        ax1.fill_between(mensal_semana.index, mensal_semana.values, alpha=0.12)
                        ax1.set_title("Dias com ocorrência na semana\n(média semanal no mês)", fontsize=11.5)
                        ax1.set_xlabel("Mês")
                        ax1.set_ylabel("Dias/semana")
                        ax1.grid(alpha=0.25)
                        ax1.tick_params(axis="x", rotation=35)
                        ax1.set_ylim(0, 7)

                    if daily_30.empty:
                        ax2.axis("off")
                        ax2.text(0.02, 0.92, "Últimos 30 dias (ocorrências/dia)", fontsize=11.5, fontweight="bold", va="top")
                        ax2.text(0.02, 0.78, "Sem dados suficientes.", fontsize=10, va="top")
                    else:
                        ax2.plot(daily_30.index, daily_30.values, marker="o", linewidth=1.7)
                        ax2.fill_between(daily_30.index, daily_30.values, alpha=0.12)
                        ax2.set_title("Últimos 30 dias\n(ocorrências por dia)", fontsize=11.5)
                        ax2.set_xlabel("Dia")
                        ax2.set_ylabel("Ocorrências")
                        ax2.grid(alpha=0.25)
                        ax2.tick_params(axis="x", rotation=35)

                    ax3.set_title("% de ocorrências vs Top 10 do contexto", fontsize=11.5)
                    ax3.barh(["Pessoa"], [pct_vs_top10], height=0.55)
                    ax3.set_xlim(0, 1)
                    ax3.set_xlabel("% do Top 10 do contexto")
                    ax3.grid(axis="x", alpha=0.25)
                    ax3.text(
                        min(pct_vs_top10 + 0.02, 0.97), 0,
                        f"{pct_vs_top10:.1%}",
                        va="center",
                        ha="left" if pct_vs_top10 < 0.9 else "right",
                        fontsize=10,
                    )

                    _pie_with_legend(
                        ax4,
                        [grp_with if grp_with is not None else 0, grp_without if grp_without is not None else 0],
                        [
                            f"Com irregularidade ({0 if grp_with is None else grp_with})",
                            f"Sem irregularidade ({0 if grp_without is None else grp_without})",
                        ],
                        "Área + herança:\nmesmo grupo da pessoa",
                        f"Base: {0 if grp_total is None else grp_total} pessoas",
                    )

                    _pie_with_legend(
                        ax5,
                        [total_p, other_days],
                        [f"Pessoa ({total_p})", f"Demais ({other_days})"],
                        "Dias com ocorrência:\npessoa vs demais",
                        f"Base: {total_ctx} ocorrências pessoa-dia",
                    )

                    periodo_analisado_txt = janela_ctx_txt
                    periodo_desligado_txt = periodo_desligado_map.get(str(cad), "-") if mostrar_periodo_desligado else None

                    ax6.text(0.00, 0.95, "Resumo", fontsize=13, fontweight="bold", va="top")
                    ax6.text(0.00, 0.82, f"Pessoa (RM | Nome abreviado | Área): {_wrap(_cad_label(str(cad)), 34)}", fontsize=10.0, va="top")
                    ax6.text(0.00, 0.66, f"Participação no contexto: {pct_p_total:.1%}", fontsize=10.5, va="top")
                    ax6.text(0.00, 0.56, f"Participação no Top 10 (contexto): {pct_vs_top10:.1%}", fontsize=10.5, va="top")
                    ax6.text(0.00, 0.46, f"Herança: {_wrap(her_val if her_val else '-', 28)}", fontsize=10.5, va="top")
                    ax6.text(0.00, 0.36, f"Período do contexto: {periodo_analisado_txt}", fontsize=10.2, va="top")
                    if mostrar_periodo_desligado:
                        ax6.text(0.00, 0.28, f"Período já desligado: {periodo_desligado_txt}", fontsize=10.0, va="top")

                    if analisar_proxy_ponto:
                        info = proxy_map.get(str(cad))
                        ax6.text(0.00, 0.08, f"Possíveis terceiros com portaria no dia (<= {int(janela_proxy_minutos)} min; mesma planta; mesmo nº coletor; chapa | nome abreviado | área)", fontsize=9.4, fontweight="bold", va="top")
                        if (not info) or (not info.get("top_other")):
                            ax6.text(0.00, 0.02, "Sem correspondências suficientes.", fontsize=9.0, va="top")
                        else:
                            lines = [f"- {_cad_proxy_label(k)} ({v})" for k, v in info["top_other"]]
                            ax6.text(0.00, 0.02, "\n".join(lines[:5]), fontsize=8.8, va="top")

                    fig.tight_layout(rect=[0, 0, 1, 0.95])
                    pdf.savefig(fig)
                    plt.close(fig)
        # Ponto sem Portaria — heatmaps finais das análises individuais (ranking)
        if analisar_proxy_ponto and col_cad and (col_cad in df_occ.columns) and ("data" in df_irregularidade.columns) and ("hora" in df_irregularidade.columns):
            try:
                from matplotlib.colors import LinearSegmentedColormap as _LSC

                desc_col_hm = _pick_col_local(df_irregularidade, ["descricao coletor", "descricao_coletor", "desc_coletor", "coletor", "descricao"])
                cols_hm = [col_cad, "data", "hora"] + ([desc_col_hm] if desc_col_hm else [])
                dph = df_irregularidade.loc[:, [c for c in cols_hm if c in df_irregularidade.columns]].copy(deep=False)
                dph[col_cad] = dph[col_cad].astype(str).str.strip()
                dph = dph.loc[dph[col_cad].ne("")].copy()

                data_dt_hm = pd.to_datetime(dph["data"], dayfirst=True, errors="coerce")
                hora_s_hm = dph["hora"].fillna("00:00").astype(str).str.strip()
                hhmm_mask_hm = hora_s_hm.str.match(r"^\d{1,2}:\d{2}$", na=False)
                hora_s_hm = hora_s_hm.where(~hhmm_mask_hm, hora_s_hm + ":00")
                hora_td_hm = pd.to_timedelta(hora_s_hm.replace({"": "00:00", "nan": "00:00", "NaT": "00:00"}), errors="coerce")
                dph["_dt"] = data_dt_hm.dt.normalize() + hora_td_hm
                hora_corte_hm = int(globals().get("hora_corte_operacional", 11))
                dph["_dia_key"] = (dph["_dt"] - pd.Timedelta(hours=hora_corte_hm)).dt.normalize()

                if desc_col_hm:
                    desc_hm = dph[desc_col_hm].fillna("").astype(str)
                else:
                    desc_hm = pd.Series("", index=dph.index)

                re_ponto_hm = globals().get("regex_ponto", r"PONTO")
                re_port_hm = globals().get("regex_portaria", r"PORTARIA|PORT")
                mask_ponto_hm = (
                    desc_hm.str.contains(re_ponto_hm, case=False, na=False, regex=True)
                    & (~desc_hm.str.contains(re_port_hm, case=False, na=False, regex=True))
                )

                dph = dph.loc[mask_ponto_hm & dph["_dt"].notna()].copy()
                if not dph.empty:
                    dph = (
                        dph.sort_values("_dt", kind="mergesort")
                           .drop_duplicates(subset=[col_cad, "_dia_key"], keep="first")
                           .copy()
                    )
                    dph["_dow"] = dph["_dia_key"].dt.dayofweek.astype(int)
                    dph["_hour"] = dph["_dt"].dt.hour.astype(int)

                    rank_occ = df_occ.loc[:, [col_cad, "_dia_operacional"]].copy()
                    rank_occ[col_cad] = rank_occ[col_cad].astype(str).str.strip()
                    rank_occ = rank_occ.loc[rank_occ[col_cad].ne("")].copy()

                    dt_end_hm = pd.to_datetime(dt_max).normalize() if pd.notna(dt_max) else pd.Timestamp.today().normalize()
                    dt_start_hm = dt_end_hm - pd.Timedelta(days=29)

                    top3_total_hm = list(rank_occ[col_cad].value_counts().head(3).index.astype(str))
                    rank_occ_30 = rank_occ.loc[
                        (rank_occ["_dia_operacional"] >= dt_start_hm) &
                        (rank_occ["_dia_operacional"] <= dt_end_hm)
                    ].copy()
                    top3_30_hm = list(rank_occ_30[col_cad].value_counts().head(3).index.astype(str))

                    cmap_hm = _LSC.from_list("vw_blue_hm", ["#F6F8FB", "#CFE2F3", "#0B5FA5", "#001E50"])
                    dow_labels_hm = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

                    def _render_heatmap_ponto_individual(cad_id: str, pos_txt: str, scope_txt: str, dt_ini_scope: pd.Timestamp, dt_fim_scope: pd.Timestamp):
                        dpc = dph.loc[
                            dph[col_cad].eq(str(cad_id))
                            & (dph["_dia_key"] >= dt_ini_scope)
                            & (dph["_dia_key"] <= dt_fim_scope)
                        ].copy()

                        fig = plt.figure(figsize=(11.69, 8.27))
                        gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.35], wspace=0.30)
                        ax_info = fig.add_subplot(gs[0, 0])
                        ax_hm = fig.add_subplot(gs[0, 1])
                        ax_info.axis("off")

                        label_p = _cad_label_basico(str(cad_id))
                        fig.suptitle(
                            f"Ponto sem Portaria — Heatmap individual ({scope_txt} | {pos_txt}) | {_wrap(label_p, 74)}",
                            fontsize=13.8,
                            fontweight="bold",
                            y=0.985,
                        )

                        if dpc.empty:
                            ax_hm.axis("off")
                            ax_hm.text(0.02, 0.90, "Sem dados para o recorte deste ranking.", fontsize=11.2, va="top")
                            ax_info.text(0.00, 0.95, "Resumo", fontsize=12.5, fontweight="bold", va="top")
                            ax_info.text(0.00, 0.86, f"Período: {pd.to_datetime(dt_ini_scope).date()} → {pd.to_datetime(dt_fim_scope).date()}", fontsize=10.2, va="top")
                            ax_info.text(0.00, 0.78, f"Critério: ocorrência-dia por pessoa", fontsize=10.2, va="top")
                            pdf.savefig(fig)
                            plt.close(fig)
                            return

                        mat = (
                            dpc.pivot_table(index="_dow", columns="_hour", values="_dt", aggfunc="count")
                               .reindex(index=range(7), columns=range(24), fill_value=0)
                               .fillna(0)
                               .astype(int)
                        )

                        vmax = int(mat.to_numpy().max()) if mat.size else 0
                        im = ax_hm.imshow(mat.values, aspect="auto", cmap=cmap_hm, vmin=0, vmax=max(vmax, 1))
                        ax_hm.set_xticks(range(0, 24, 2))
                        ax_hm.set_xticklabels([f"{h:02d}h" for h in range(0, 24, 2)])
                        ax_hm.set_yticks(range(7))
                        ax_hm.set_yticklabels(dow_labels_hm)
                        ax_hm.set_xlabel("Hora")
                        ax_hm.set_ylabel("Dia da semana")
                        ax_hm.set_title("Distribuição por dia da semana x hora")

                        for yi in range(mat.shape[0]):
                            for xi in range(mat.shape[1]):
                                v = int(mat.iat[yi, xi])
                                if v > 0:
                                    ax_hm.text(xi, yi, str(v), ha="center", va="center", fontsize=7.6)

                        cbar = fig.colorbar(im, ax=ax_hm, fraction=0.046, pad=0.04)
                        cbar.set_label("Ocorrências (pessoa-dia)")

                        total_scope = int(
                            rank_occ.loc[
                                rank_occ[col_cad].eq(str(cad_id))
                                & (rank_occ["_dia_operacional"] >= dt_ini_scope)
                                & (rank_occ["_dia_operacional"] <= dt_fim_scope)
                            ].shape[0]
                        )

                        ax_info.text(0.00, 0.95, "Resumo", fontsize=12.5, fontweight="bold", va="top")
                        ax_info.text(0.00, 0.86, f"Período: {pd.to_datetime(dt_ini_scope).date()} → {pd.to_datetime(dt_fim_scope).date()}", fontsize=10.2, va="top")
                        ax_info.text(0.00, 0.78, f"Volume da pessoa no ranking: {total_scope}", fontsize=10.6, va="top")
                        ax_info.text(0.00, 0.70, f"Critério: ocorrência-dia por pessoa", fontsize=10.2, va="top")
                        ax_info.text(0.00, 0.60, f"Filtro proxy: <= {int(janela_proxy_minutos)} min, mesma planta, mesmo coletor e terceiro com portaria no dia.", fontsize=9.6, va="top", wrap=True)

                        plt.tight_layout(rect=[0, 0, 1, 0.96])
                        pdf.savefig(fig)
                        plt.close(fig)

                    dt_ini_total_hm = pd.to_datetime(rank_occ["_dia_operacional"].min()).normalize() if not rank_occ.empty else dt_start_hm
                    dt_fim_total_hm = pd.to_datetime(rank_occ["_dia_operacional"].max()).normalize() if not rank_occ.empty else dt_end_hm

                    for pos, cad_id in enumerate(top3_total_hm, start=1):
                        _render_heatmap_ponto_individual(str(cad_id), f"{pos}º do Top 3", "Período total", dt_ini_total_hm, dt_fim_total_hm)

                    for pos, cad_id in enumerate(top3_30_hm, start=1):
                        _render_heatmap_ponto_individual(str(cad_id), f"{pos}º do Top 3", "Últimos 30 dias", dt_start_hm, dt_end_hm)
            except Exception as _e_hm:
                fig = plt.figure(figsize=(11.69, 8.27))
                ax = fig.add_subplot(111)
                ax.axis("off")
                ax.text(0.02, 0.92, "Ponto sem Portaria — heatmaps individuais", fontsize=18, fontweight="bold", va="top")
                ax.text(0.02, 0.80, f"Falha ao gerar heatmaps finais: {_e_hm}", fontsize=11.5, va="top")
                pdf.savefig(fig)
                plt.close(fig)

        # 999 como trajeto — Top pessoas (volume ocorrência-dia) + casos individuais
        titulo_l = str(titulo).lower()
        if ("999" in titulo_l) and ("trajeto" in titulo_l or "999" in str(pdf_path).lower()):
            required_cols = ["cadastro", "data", "hora", "dir", "planta", "descricao coletor"]
            if all(c in df_irregularidade.columns for c in required_cols):
                from matplotlib.colors import LinearSegmentedColormap as _LSC

                cols_999 = required_cols + ([col_cargo] if (somente_executivos_atuais and col_cargo) else [])
                dfx = df_irregularidade.loc[:, [c for c in cols_999 if c in df_irregularidade.columns]].copy(deep=False)
                dfx["cadastro"] = dfx["cadastro"].astype(str).str.strip()
                dfx = dfx.loc[dfx["cadastro"].ne("")].copy()

                if somente_executivos_atuais and col_cargo and (col_cargo in dfx.columns):
                    cargo_norm_999 = dfx[col_cargo].fillna("").astype(str).str.strip().str.upper()
                    dfx = dfx.loc[cargo_norm_999.eq("E")]

                data_dt = pd.to_datetime(dfx["data"], dayfirst=True, errors="coerce")
                hora_s = dfx["hora"].fillna("00:00").astype(str).str.strip()
                hora_s = hora_s.replace({"": "00:00", "nan": "00:00", "NaT": "00:00"})
                hhmm_mask = hora_s.str.match(r"^\d{1,2}:\d{2}$", na=False)
                hora_s = hora_s.where(~hhmm_mask, hora_s + ":00")
                hora_td = pd.to_timedelta(hora_s, errors="coerce")
                dfx["_dt"] = data_dt.dt.normalize() + hora_td
                hora_corte = int(globals().get("hora_corte_operacional", 11))
                dfx["_dia_key"] = (dfx["_dt"] - pd.Timedelta(hours=hora_corte)).dt.normalize()

                re_port = globals().get("regex_portaria", r"PORTARIA|PORT")
                desc_999 = dfx["descricao coletor"].fillna("").astype(str)
                dfx["_is_port"] = desc_999.str.contains(re_port, case=False, na=False, regex=True)

                dirn = dfx["dir"].fillna("").astype(str).str.strip().str.upper()
                dirn = dirn.replace({"ENTRADA": "E", "SAIDA": "S", "SAÍDA": "S"})
                dfx["_is_E"] = dirn.str.startswith("E")
                dfx["_is_S"] = dirn.str.startswith("S")

                planta_num = pd.to_numeric(dfx["planta"], errors="coerce")
                dfx["_is_999"] = planta_num.eq(999)

                port = dfx.loc[dfx["_is_port"] & dfx["_dt"].notna(), ["cadastro", "_dia_key", "_dt", "_is_E", "_is_S"]]
                ev_999 = dfx.loc[dfx["_is_999"] & dfx["_dt"].notna(), ["cadastro", "_dia_key", "_dt", "planta", "descricao coletor"]]

                if port.empty or ev_999.empty:
                    fig = plt.figure(figsize=(11.69, 8.27))
                    ax = fig.add_subplot(111)
                    ax.axis("off")
                    ax.text(0.02, 0.92, "999 como trajeto — Top pessoas", fontsize=18, fontweight="bold", va="top")
                    ax.text(0.02, 0.80, "Sem eventos suficientes para classificar o cenário 999 como trajeto.", fontsize=13, va="top")
                    pdf.savefig(fig)
                    plt.close(fig)
                else:
                    ent = (
                        port.loc[port["_is_E"]]
                            .groupby(["cadastro", "_dia_key"], sort=False)["_dt"].min()
                            .rename("t_ent")
                            .reset_index()
                    )
                    sai = (
                        port.loc[port["_is_S"]]
                            .groupby(["cadastro", "_dia_key"], sort=False)["_dt"].max()
                            .rename("t_sai")
                            .reset_index()
                    )
                    pe = ent.merge(sai, on=["cadastro", "_dia_key"], how="inner")

                    ev = ev_999.merge(pe, on=["cadastro", "_dia_key"], how="inner")
                    if ev.empty:
                        fig = plt.figure(figsize=(11.69, 8.27))
                        ax = fig.add_subplot(111)
                        ax.axis("off")
                        ax.text(0.02, 0.92, "999 como trajeto — Top pessoas", fontsize=18, fontweight="bold", va="top")
                        ax.text(0.02, 0.80, "Sem interseção entre eventos 999 e pares válidos de portaria.", fontsize=13, va="top")
                        pdf.savefig(fig)
                        plt.close(fig)
                    else:
                        ev["_before"] = ev["_dt"] < ev["t_ent"]
                        ev["_after"] = ev["_dt"] > ev["t_sai"]

                        day_flags = (
                            ev.groupby(["cadastro", "_dia_key"], sort=False)[["_before", "_after"]]
                              .any()
                              .reset_index()
                        )
                        day_flags["cat"] = np.select(
                            [
                                day_flags["_before"] & day_flags["_after"],
                                day_flags["_before"] & (~day_flags["_after"]),
                                (~day_flags["_before"]) & day_flags["_after"],
                            ],
                            ["Ambos", "Antes", "Depois"],
                            default="(sem class.)",
                        )
                        day_flags = day_flags.loc[day_flags["cat"].isin(["Antes", "Depois", "Ambos"])].copy()

                        if day_flags.empty:
                            fig = plt.figure(figsize=(11.69, 8.27))
                            ax = fig.add_subplot(111)
                            ax.axis("off")
                            ax.text(0.02, 0.92, "999 como trajeto — Top pessoas", fontsize=18, fontweight="bold", va="top")
                            ax.text(0.02, 0.80, "Sem dias classificados em Antes/Depois/Ambos.", fontsize=13, va="top")
                            pdf.savefig(fig)
                            plt.close(fig)
                        else:
                            dt_min_999 = pd.to_datetime(day_flags["_dia_key"].min()).normalize()
                            dt_end_999 = pd.to_datetime(day_flags["_dia_key"].max()).normalize()
                            dt_start_999_30 = dt_end_999 - pd.Timedelta(days=29)

                            day_flags_30 = day_flags.loc[
                                (day_flags["_dia_key"] >= dt_start_999_30)
                                & (day_flags["_dia_key"] <= dt_end_999)
                            ].copy()

                            rank_total = day_flags.groupby("cadastro", sort=False).size().sort_values(ascending=False)
                            rank_30 = day_flags_30.groupby("cadastro", sort=False).size().sort_values(ascending=False)

                            cmap_blue = _LSC.from_list("vw_blue_rank", ["#F6F8FB", "#CFE2F3", "#0B5FA5", "#001E50"])

                            def _render_999_concentracao_top10(
                                df_flags_scope: pd.DataFrame,
                                scope_txt: str,
                                janela_txt: str,
                            ) -> None:
                                fig = plt.figure(figsize=(11.69, 8.27))
                                ax = fig.add_subplot(111)
                                titulo_top10 = (
                                    "999 como trajeto — Top 10 pessoas piores (últimos 30 dias)"
                                    if "30" in str(scope_txt)
                                    else "999 como trajeto — Top 10 pessoas piores (período total)"
                                )

                                if (df_flags_scope is None) or df_flags_scope.empty:
                                    ax.axis("off")
                                    ax.text(0.02, 0.92, titulo_top10, fontsize=18, fontweight="bold", va="top")
                                    ax.text(0.02, 0.85, f"Concentração por categoria ({scope_txt})", fontsize=11.8, va="top")
                                    ax.text(0.02, 0.80, "Sem dados suficientes para este recorte.", fontsize=13, va="top")
                                    ax.text(0.02, 0.72, f"Janela: {janela_txt}", fontsize=11.2, va="top")
                                    pdf.savefig(fig)
                                    plt.close(fig)
                                    return

                                agg = (
                                    df_flags_scope.groupby(["cadastro", "cat"], sort=False)
                                                 .size()
                                                 .rename("n_dias")
                                                 .reset_index()
                                )
                                tot2 = agg.groupby("cadastro", sort=False)["n_dias"].sum().rename("n_total").reset_index()
                                if tot2.empty:
                                    ax.axis("off")
                                    ax.text(0.02, 0.92, titulo_top10, fontsize=18, fontweight="bold", va="top")
                                    ax.text(0.02, 0.85, f"Concentração por categoria ({scope_txt})", fontsize=11.8, va="top")
                                    ax.text(0.02, 0.80, "Sem dados para consolidar Top 10.", fontsize=13, va="top")
                                    pdf.savefig(fig)
                                    plt.close(fig)
                                    return

                                agg = agg.merge(tot2, on="cadastro", how="left")
                                agg["pct"] = agg["n_dias"] / agg["n_total"].where(agg["n_total"] > 0, np.nan)

                                top_cads = (
                                    tot2.sort_values(["n_total", "cadastro"], ascending=[False, True])
                                        .head(10)["cadastro"].astype(str).tolist()
                                )

                                cats = ["Antes", "Depois", "Ambos"]
                                mat = (
                                    agg.loc[agg["cadastro"].isin(top_cads)]
                                       .pivot_table(index="cadastro", columns="cat", values="pct", aggfunc="first")
                                       .reindex(index=top_cads, columns=cats)
                                       .fillna(0.0)
                                )

                                tot_map = tot2.set_index("cadastro")["n_total"].to_dict()
                                y_labels = [f"{_cad_label_basico(str(c))} | Vol: {int(tot_map.get(str(c), 0))}" for c in mat.index]

                                ax.set_title(titulo_top10, fontsize=15.5)
                                ax.text(0.01, 1.08, f"Concentração por categoria ({scope_txt})", transform=ax.transAxes, fontsize=10.2, va="bottom", ha="left")
                                ax.text(0.01, 1.02, f"Janela: {janela_txt}", transform=ax.transAxes, fontsize=10.2, va="bottom", ha="left")
                                ax.set_xlabel("Categoria")
                                ax.set_xticks([0, 1, 2])
                                ax.set_xticklabels(["Antes de entrar", "Depois de sair", "Ambos"])
                                ax.set_yticks(range(len(y_labels)))
                                ax.set_yticklabels([_wrap(y, 74) for y in y_labels])

                                im = ax.imshow(mat.values, aspect="auto", cmap=cmap_blue, vmin=0.0, vmax=1.0)
                                for yi in range(mat.shape[0]):
                                    for xi in range(mat.shape[1]):
                                        p = float(mat.iloc[yi, xi])
                                        ax.text(xi, yi, f"{p * 100:.0f}%", ha="center", va="center", fontsize=9.2)

                                cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
                                cbar.set_label("% por pessoa (linha = 100%)")
                                ax.text(0.01, -0.12, "Critério de Top 10: maior volume de ocorrência-dia por pessoa.", transform=ax.transAxes, fontsize=9.2, va="top")

                                pdf.savefig(fig)
                                plt.close(fig)

                            _render_999_concentracao_top10(
                                day_flags,
                                scope_txt="Período total",
                                janela_txt=f"{pd.to_datetime(dt_min_999).date()} → {pd.to_datetime(dt_end_999).date()}",
                            )
                            _render_999_concentracao_top10(
                                day_flags_30,
                                scope_txt="Últimos 30 dias",
                                janela_txt=f"{pd.to_datetime(dt_start_999_30).date()} → {pd.to_datetime(dt_end_999).date()}",
                            )

                            # Casos individuais (Top 3 do período total): heatmap de concentração por hora x dia da semana.
                            top3_total_999 = rank_total.head(3)
                            ev_hm = ev.merge(
                                day_flags.loc[:, ["cadastro", "_dia_key", "cat"]],
                                on=["cadastro", "_dia_key"],
                                how="inner",
                            )
                            if not ev_hm.empty and (not top3_total_999.empty):
                                ev_hm = (
                                    ev_hm.sort_values("_dt", kind="mergesort")
                                         .drop_duplicates(subset=["cadastro", "_dia_key"], keep="first")
                                         .copy()
                                )
                                ev_hm["_dow"] = ev_hm["_dia_key"].dt.dayofweek.astype(int)
                                ev_hm["_hora"] = ev_hm["_dt"].dt.hour.astype(int)
                                dow_labels_999 = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
                                cmap_hm_999 = _LSC.from_list("vw_blue_999_ind", ["#F6F8FB", "#CFE2F3", "#0B5FA5", "#001E50"])

                                def _render_999_individual_heatmap(cad_id: str, pos_txt: str):
                                    dfi = ev_hm.loc[ev_hm["cadastro"].astype(str).eq(str(cad_id))].copy()
                                    if dfi.empty:
                                        return

                                    mat = (
                                        dfi.pivot_table(index="_dow", columns="_hora", values="_dt", aggfunc="count")
                                           .reindex(index=range(7), columns=range(24), fill_value=0)
                                           .fillna(0)
                                           .astype(int)
                                    )

                                    total_p = int(rank_total.get(str(cad_id), 0))
                                    total_all = int(rank_total.sum())
                                    pct_p = (total_p / total_all) if total_all else 0.0
                                    label_p = _cad_label_basico(str(cad_id))

                                    fig = plt.figure(figsize=(11.69, 8.27))
                                    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.28)
                                    ax = fig.add_subplot(gs[0, 0])
                                    ax_info = fig.add_subplot(gs[0, 1])
                                    ax_info.axis("off")

                                    im = ax.imshow(mat.values, aspect="auto", cmap=cmap_hm_999)
                                    xticks = list(range(0, 24, 2))
                                    ax.set_xticks(xticks)
                                    ax.set_xticklabels([f"{h:02d}h" for h in xticks], rotation=0)
                                    ax.set_yticks(range(7))
                                    ax.set_yticklabels(dow_labels_999)
                                    ax.set_xlabel("Hora do dia")
                                    ax.set_ylabel("Dia da semana")
                                    ax.set_title(f"999 como trajeto  Caso individual {pos_txt} (período total) | {_wrap(label_p, 72)}", fontsize=12.5)

                                    for yi in range(mat.shape[0]):
                                        for xi in range(mat.shape[1]):
                                            v = int(mat.iat[yi, xi])
                                            if v > 0:
                                                ax.text(xi, yi, str(v), ha="center", va="center", fontsize=7.3)

                                    vmax = int(mat.to_numpy().max())
                                    if vmax > 0:
                                        pos = np.argwhere(mat.to_numpy() == vmax)[0]
                                        yi, xi = int(pos[0]), int(pos[1])
                                        periodos = ["Madrugada (00h-05h)", "Manhã (06h-11h)", "Tarde (12h-17h)", "Noite (18h-23h)"]
                                        periodo_idx = int(np.digitize([xi], bins=[6, 12, 18], right=False)[0])
                                        periodo_idx = max(0, min(periodo_idx, 3))
                                        periodo_txt = periodos[periodo_idx]
                                        ax.text(
                                            0.01,
                                            -0.11,
                                            f"Pico: {dow_labels_999[yi]} | {xi:02d}:00–{(xi + 1) % 24:02d}:00 | {vmax} ocorrência(s) pessoa-dia | Período: {periodo_txt}",
                                            transform=ax.transAxes,
                                            fontsize=9.2,
                                            va="top",
                                        )

                                    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
                                    cbar.set_label("Qtd. de ocorrências (pessoa-dia)")

                                    cat_dist = (
                                        dfi["cat"].value_counts()
                                           .reindex(["Antes", "Depois", "Ambos"], fill_value=0)
                                    )
                                    total_cat = int(cat_dist.sum())

                                    ax_info.text(0.00, 0.95, "Resumo do caso", fontsize=13.0, fontweight="bold", va="top")
                                    ax_info.text(0.00, 0.86, f"Pessoa: {_wrap(label_p, 34)}", fontsize=10.6, va="top")
                                    ax_info.text(0.00, 0.77, f"Volume (pessoa-dia): {total_p}", fontsize=10.6, va="top")
                                    ax_info.text(0.00, 0.69, f"Participação no total: {pct_p:.1%}", fontsize=10.6, va="top")
                                    ax_info.text(0.00, 0.60, f"Janela total: {pd.to_datetime(dt_min_999).date()} → {pd.to_datetime(dt_end_999).date()}", fontsize=9.8, va="top")
                                    ax_info.text(0.00, 0.50, "Distribuição por categoria", fontsize=11.2, fontweight="bold", va="top")

                                    y0 = 0.42
                                    for cat_nome in ["Antes", "Depois", "Ambos"]:
                                        vcat = int(cat_dist.get(cat_nome, 0))
                                        pcat = (vcat / total_cat) if total_cat else 0.0
                                        ax_info.text(0.00, y0, f"{cat_nome}: {vcat} ({pcat:.1%})", fontsize=10.0, va="top")
                                        y0 -= 0.07

                                    plt.tight_layout(rect=[0, 0, 1, 0.96])
                                    pdf.savefig(fig)
                                    plt.close(fig)

                                for pos, cad_id in enumerate(top3_total_999.index.astype(str).tolist(), start=1):
                                    _render_999_individual_heatmap(str(cad_id), f"{pos}º")

                            # Fechamento: total geral de todos os registros classificados
                            fig = plt.figure(figsize=(11.69, 8.27))
                            gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.2], wspace=0.30)
                            ax_info = fig.add_subplot(gs[0, 0])
                            ax_bar = fig.add_subplot(gs[0, 1])
                            ax_info.axis("off")

                            cat_tot = day_flags["cat"].value_counts().reindex(["Antes", "Depois", "Ambos"], fill_value=0)
                            total_reg = int(cat_tot.sum())
                            pessoas_unicas = int(day_flags["cadastro"].astype(str).nunique())
                            dias_unicos = int(pd.to_datetime(day_flags["_dia_key"], errors="coerce").nunique())

                            ax_info.text(0.00, 0.95, "999 como trajeto — Total geral", fontsize=14.0, fontweight="bold", va="top")
                            ax_info.text(0.00, 0.86, f"Período total: {pd.to_datetime(dt_min_999).date()} → {pd.to_datetime(dt_end_999).date()}", fontsize=10.6, va="top")
                            ax_info.text(0.00, 0.78, f"Total de ocorrências-dia classificadas: {total_reg}", fontsize=10.8, va="top")
                            ax_info.text(0.00, 0.71, f"Pessoas únicas: {pessoas_unicas}", fontsize=10.6, va="top")
                            ax_info.text(0.00, 0.64, f"Dias operacionais com ocorrência: {dias_unicos}", fontsize=10.6, va="top")
                            ax_info.text(0.00, 0.54, "Distribuição por categoria", fontsize=12.0, fontweight="bold", va="top")

                            vals = cat_tot.values.astype(float)
                            y = np.arange(len(cat_tot))
                            ax_bar.barh(y, vals, color="#0B5FA5", edgecolor="#001E50", linewidth=1.0)
                            ax_bar.set_yticks(y)
                            ax_bar.set_yticklabels([str(x) for x in cat_tot.index])
                            ax_bar.invert_yaxis()
                            ax_bar.set_xlabel("Ocorrências (pessoa-dia)")
                            ax_bar.set_title("Total geral por categoria")
                            ax_bar.grid(axis="x", alpha=0.25)

                            xmax = max(float(vals.max()) * 1.22, 1.0)
                            ax_bar.set_xlim(0, xmax)
                            for i, v in enumerate(vals):
                                pct = (float(v) / total_reg) if total_reg else 0.0
                                ax_bar.text(min(float(v) + xmax * 0.015, xmax * 0.98), i, f"{int(v)} ({pct:.1%})", va="center", fontsize=9.0)

                            plt.tight_layout(rect=[0, 0, 1, 0.96])
                            pdf.savefig(fig)
                            plt.close(fig)


        # Grill (heatmap) — horário x dia da semana (Top 3 período total + Top 3 últimos 30 dias)
        if analisar_heatmap_grill:
            required_cols_grill = ["cadastro", "data", "hora", "descricao coletor"]
            if all(c in df_irregularidade.columns for c in required_cols_grill):
                cols_grill = ["cadastro", "nome", "data", "hora", "descricao coletor"]
                dfg = df_irregularidade.loc[:, [c for c in cols_grill if c in df_irregularidade.columns]].copy(deep=False)

                data_dt = pd.to_datetime(dfg["data"], dayfirst=True, errors="coerce")
                hora_s = dfg["hora"].fillna("00:00").astype(str).str.strip()
                hora_s = hora_s.replace({"": "00:00", "nan": "00:00", "NaT": "00:00"})
                hhmm_mask = hora_s.str.match(r"^\d{1,2}:\d{2}$", na=False)
                hora_s = hora_s.where(~hhmm_mask, hora_s + ":00")
                hora_td = pd.to_timedelta(hora_s, errors="coerce")
                dfg["_dt"] = data_dt.dt.normalize() + hora_td
                hora_corte = int(globals().get("hora_corte_operacional", 11))
                dfg["_dia_key"] = (dfg["_dt"] - pd.Timedelta(hours=hora_corte)).dt.normalize()

                _re_grill = globals().get("regex_grill", r"\bGRILL\b")
                descg = dfg["descricao coletor"].fillna("").astype(str)
                dfg = dfg.loc[dfg["_dt"].notna() & descg.str.contains(_re_grill, case=False, na=False, regex=True)].copy()

                if dfg.empty:
                    fig = plt.figure(figsize=(11.69, 8.27))
                    ax = fig.add_subplot(111)
                    ax.axis("off")
                    ax.text(0.02, 0.92, "Grill — heatmaps Top 3 por pessoa", fontsize=18, fontweight="bold", va="top")
                    ax.text(0.02, 0.80, "Sem eventos de grill válidos para classificar.", fontsize=13, va="top")
                    pdf.savefig(fig)
                    plt.close(fig)
                else:
                    dfg["cadastro"] = dfg["cadastro"].astype(str).str.strip()
                    dfg = dfg.loc[dfg["cadastro"].ne("")].copy()

                    if dfg.empty:
                        fig = plt.figure(figsize=(11.69, 8.27))
                        ax = fig.add_subplot(111)
                        ax.axis("off")
                        ax.text(0.02, 0.92, "Grill — heatmaps Top 3 por pessoa", fontsize=18, fontweight="bold", va="top")
                        ax.text(0.02, 0.80, "Sem cadastro válido para classificar.", fontsize=13, va="top")
                        pdf.savefig(fig)
                        plt.close(fig)
                    else:
                        # Ocorrência diária: conta no máximo 1 ocorrência grill por pessoa-dia
                        dfg_pd = (
                            dfg.sort_values("_dt", kind="mergesort")
                               .drop_duplicates(subset=["cadastro", "_dia_key"], keep="first")
                               .copy()
                        )
                        dfg_pd["_dow"] = dfg_pd["_dia_key"].dt.dayofweek.astype(int)
                        dfg_pd["_hora"] = dfg_pd["_dt"].dt.hour.astype(int)

                        cont_total = dfg_pd.groupby("cadastro").size().sort_values(ascending=False)

                        dt_end_grill = pd.to_datetime(dfg_pd["_dia_key"].max()).normalize()
                        dt_start_30_grill = dt_end_grill - pd.Timedelta(days=29)
                        mask_30 = (dfg_pd["_dia_key"] >= dt_start_30_grill) & (dfg_pd["_dia_key"] <= dt_end_grill)
                        cont_30 = dfg_pd.loc[mask_30].groupby("cadastro").size().sort_values(ascending=False)

                        top3_total = cont_total.head(3)
                        top3_30 = cont_30.head(3)

                        dow_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

                        def _render_grill_top3_heatmap(
                            cadastro_id: str,
                            total_pessoa_dia: int,
                            titulo_bloco: str,
                            ordem_txt: str,
                            janela_txt: str,
                            df_source: pd.DataFrame | None = None,
                        ) -> None:
                            base_src = dfg_pd if df_source is None else df_source
                            dfg_cad = base_src.loc[base_src["cadastro"].eq(str(cadastro_id))].copy()
                            if dfg_cad.empty:
                                return

                            mat = (
                                dfg_cad.pivot_table(index="_dow", columns="_hora", values="_dt", aggfunc="count")
                                       .reindex(index=range(7), columns=range(24), fill_value=0)
                                       .fillna(0)
                                       .astype(int)
                            )

                            fig = plt.figure(figsize=(11.69, 8.27))
                            ax = fig.add_subplot(111)

                            im = ax.imshow(mat.values, aspect="auto", cmap="Blues")
                            xticks = list(range(0, 24, 2))
                            ax.set_xticks(xticks)
                            ax.set_xticklabels([f"{h:02d}h" for h in xticks], rotation=0)
                            ax.set_yticks(range(7))
                            ax.set_yticklabels(dow_labels)

                            pessoa_txt = _cad_label(str(cadastro_id))
                            ax.set_title(
                                f"{titulo_bloco} | {ordem_txt}\n{_wrap(pessoa_txt, 80)} | Total pessoa-dia: {int(total_pessoa_dia)} | Janela: {janela_txt}",
                                fontsize=12.5,
                            )
                            ax.set_xlabel("Hora do dia")
                            ax.set_ylabel("Dia da semana")

                            vmax = int(mat.to_numpy().max())
                            if vmax > 0:
                                pos = np.argwhere(mat.to_numpy() == vmax)[0]
                                yi, xi = int(pos[0]), int(pos[1])

                                periodos = ["Madrugada (00h-05h)", "Manhã (06h-11h)", "Tarde (12h-17h)", "Noite (18h-23h)"]
                                periodo_idx = int(np.digitize([xi], bins=[6, 12, 18], right=False)[0])
                                periodo_idx = max(0, min(periodo_idx, 3))
                                periodo_txt = periodos[periodo_idx]

                                hora_ini = f"{xi:02d}:00"
                                hora_fim = f"{(xi + 1) % 24:02d}:00"
                                ax.text(
                                    0.01,
                                    -0.12,
                                    f"Pico: {dow_labels[yi]} | {hora_ini}–{hora_fim} | {vmax} ocorrência(s) pessoa-dia | Período: {periodo_txt}",
                                    transform=ax.transAxes,
                                    fontsize=10.0,
                                    va="top",
                                )

                            for yi in range(mat.shape[0]):
                                for xi in range(mat.shape[1]):
                                    v = int(mat.iat[yi, xi])
                                    if v > 0:
                                        ax.text(xi, yi, str(v), ha="center", va="center", fontsize=7.5)

                            cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
                            cbar.set_label("Qtd. de ocorrências (pessoa-dia)")

                            pdf.savefig(fig)
                            plt.close(fig)

                        if top3_total.empty and top3_30.empty:
                            fig = plt.figure(figsize=(11.69, 8.27))
                            ax = fig.add_subplot(111)
                            ax.axis("off")
                            ax.text(0.02, 0.92, "Grill — heatmaps Top 3 por pessoa", fontsize=18, fontweight="bold", va="top")
                            ax.text(0.02, 0.80, "Sem dados suficientes para gerar Top 3 no período total ou nos últimos 30 dias.", fontsize=13, va="top")
                            pdf.savefig(fig)
                            plt.close(fig)
                        else:
                            janela_total_txt = f"{pd.to_datetime(dfg_pd['_dia_key'].min()).date()} → {pd.to_datetime(dfg_pd['_dia_key'].max()).date()}"
                            janela_30_txt = f"{pd.to_datetime(dt_start_30_grill).date()} → {pd.to_datetime(dt_end_grill).date()}"

                            for pos, (cad, qtd) in enumerate(top3_total.items(), start=1):
                                _render_grill_top3_heatmap(
                                    cadastro_id=str(cad),
                                    total_pessoa_dia=int(qtd),
                                    titulo_bloco="Grill — Top 3 por volume (período total)",
                                    ordem_txt=f"{pos}º do Top 3",
                                    janela_txt=janela_total_txt,
                                )

                            for pos, (cad, qtd) in enumerate(top3_30.items(), start=1):
                                _render_grill_top3_heatmap(
                                    cadastro_id=str(cad),
                                    total_pessoa_dia=int(qtd),
                                    titulo_bloco="Grill — Top 3 por volume (últimos 30 dias)",
                                    ordem_txt=f"{pos}º do Top 3",
                                    janela_txt=janela_30_txt,
                                )

                            # Novo recorte: Top 3 com ocorrência no horário das 11h às 13h (inclusive)
                            mask_11_13 = dfg_pd["_hora"].between(11, 13, inclusive="both")
                            dfg_pd_11_13 = dfg_pd.loc[mask_11_13].copy()
                            top3_11_13 = dfg_pd_11_13.groupby("cadastro").size().sort_values(ascending=False).head(3)

                            if top3_11_13.empty:
                                fig = plt.figure(figsize=(11.69, 8.27))
                                ax = fig.add_subplot(111)
                                ax.axis("off")
                                ax.text(0.02, 0.92, "Grill — Top 3 (11h às 13h)", fontsize=18, fontweight="bold", va="top")
                                ax.text(0.02, 0.80, "Sem dados suficientes no recorte de 11h a 13h.", fontsize=13, va="top")
                                pdf.savefig(fig)
                                plt.close(fig)
                            else:
                                janela_11_13_txt = (
                                    f"{pd.to_datetime(dfg_pd_11_13['_dia_key'].min()).date()} → "
                                    f"{pd.to_datetime(dfg_pd_11_13['_dia_key'].max()).date()}"
                                )
                                for pos, (cad, qtd) in enumerate(top3_11_13.items(), start=1):
                                    _render_grill_top3_heatmap(
                                        cadastro_id=str(cad),
                                        total_pessoa_dia=int(qtd),
                                        titulo_bloco="Grill — Top 3 por volume (11h às 13h)",
                                        ordem_txt=f"{pos}º do Top 3",
                                        janela_txt=janela_11_13_txt,
                                        df_source=dfg_pd_11_13,
                                    )
def row_ids_from_keys(df_min: pd.DataFrame, keys: pd.DataFrame) -> np.ndarray:
    if keys is None or keys.empty:
        return np.array([], dtype=np.int64)

    keys2 = keys.loc[:, ["cadastro", "_dia_operacional"]].drop_duplicates().copy()
    keys2["_dia_operacional"] = pd.to_datetime(keys2["_dia_operacional"], errors="coerce")

    if ("_ROWID_CACHE_HASH" not in globals()) or (len(globals()["_ROWID_CACHE_HASH"]) != len(df_min)):
        globals()["_ROWID_CACHE_ROWID"] = df_min["_row_id"].to_numpy(dtype=np.int64, copy=False)
        globals()["_ROWID_CACHE_HASH"] = pd.util.hash_pandas_object(
            df_min[["cadastro", "_dia_operacional"]], index=False
        ).to_numpy(dtype=np.uint64, copy=False)
        globals()["_ROWID_CACHE_HASH_INDEX"] = pd.Index(globals()["_ROWID_CACHE_HASH"])

    key_hash = pd.util.hash_pandas_object(
        keys2[["cadastro", "_dia_operacional"]], index=False
    ).to_numpy(dtype=np.uint64, copy=False)

    if key_hash.size == 0:
        return np.array([], dtype=np.int64)

    mask = globals()["_ROWID_CACHE_HASH_INDEX"].isin(key_hash)
    return globals()["_ROWID_CACHE_ROWID"][mask].astype(np.int64, copy=True)

# Mapa dia_operacional por row_id (para colocar na saída)
n_total = len(df_min_raw)
dia_op_arr = np.full(n_total, np.datetime64("NaT"), dtype="datetime64[ns]")
valid_map = df.loc[df["_dt_ronda"].notna(), ["_row_id", "_dia_operacional"]]
dia_op_arr[valid_map["_row_id"].to_numpy()] = valid_map["_dia_operacional"].to_numpy()

def materializar_e_exportar_por_rowid(
    row_ids: np.ndarray,
    irregularidade_col: str,
    titulo: str,
    df_relatorio: pd.DataFrame | None = None,
) -> pd.DataFrame:
    slug = slugify(irregularidade_col)

    parquet_path = DFS_DIR / f"{slug}.parquet"
    pdf_path = PDF_DIR / f"{slug}.pdf"

    excluir_planta_999_nesta_irregularidade = _deve_excluir_planta_999(
        irregularidade_col=irregularidade_col,
        titulo=titulo,
        pdf_path=pdf_path,
    )

    params_export = {
        "param_janela_portaria_min": globals().get("janela_portaria_min"),
        "param_tolerancia_entrada_min": globals().get("tolerancia_entrada_min"),
        "param_tolerancia_saida_min": globals().get("tolerancia_saida_min"),
        "param_janela_999_horas": globals().get("janela_999_horas"),
        "param_hora_corte_operacional": globals().get("hora_corte_operacional"),
        "param_descanso_min_horas": globals().get("descanso_min_horas"),
        "param_jornada_min_horas": globals().get("jornada_min_horas"),
        "param_jornada_min_minutos": globals().get("jornada_min_minutos"),
        "param_usar_jornada_por_portaria": globals().get("usar_jornada_por_portaria"),
        "param_max_jornada_portaria_horas": globals().get("max_jornada_portaria_horas"),
    }

    base_relatorio = df_relatorio if isinstance(df_relatorio, pd.DataFrame) else None

    if excluir_planta_999_nesta_irregularidade:
        row_ids = _filtrar_row_ids_sem_planta_999(row_ids)
        base_relatorio = _filtrar_df_sem_planta_999(base_relatorio)

    if row_ids.size == 0:
        df_out = df_min_raw.head(0).copy()
        df_out["dia_operacional"] = pd.to_datetime([], errors="coerce")
        df_out[irregularidade_col] = False
        for _k, _v in params_export.items():
            df_out[_k] = _v

        df_out.to_parquet(parquet_path, index=False)
        gerar_relatorio_pdf(base_relatorio if base_relatorio is not None else df_out, titulo=titulo, pdf_path=pdf_path)
        gc.collect()
        print("Parquet:", parquet_path)
        print("PDF   :", pdf_path)
        return df_out

    row_ids = row_ids[(row_ids >= 0) & (row_ids < len(df_min_raw))]

    MAX_ROWS_IN_MEMORY = 2_000_000
    REPORT_SAMPLE_ROWS = 2_000

    if row_ids.size > MAX_ROWS_IN_MEMORY:
        import pyarrow as pa
        import pyarrow.parquet as pq

        row_ids = np.sort(row_ids.astype(np.int64, copy=False))
        chunk_size = BATCH_SIZE

        if parquet_path.exists():
            parquet_path.unlink()

        writer = None
        report_parts = []
        report_count = 0

        for i in range(0, row_ids.size, chunk_size):
            ids = row_ids[i:i + chunk_size]
            part = df_min_raw.iloc[ids].copy()
            part["dia_operacional"] = pd.to_datetime(dia_op_arr[ids], errors="coerce")
            part[irregularidade_col] = True
            for _k, _v in params_export.items():
                part[_k] = _v
            part.drop(columns=["_row_id"], inplace=True, errors="ignore")

            table = pa.Table.from_pandas(part, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(str(parquet_path), table.schema, compression="snappy")
            writer.write_table(table)

            if report_count < REPORT_SAMPLE_ROWS:
                take = min(REPORT_SAMPLE_ROWS - report_count, len(part))
                report_parts.append(part.head(take).copy())
                report_count += take

            del ids, part, table
            gc.collect()

        if writer is not None:
            writer.close()

        if report_parts:
            df_report_fallback = pd.concat(report_parts, ignore_index=True)
        else:
            df_report_fallback = df_min_raw.head(0).copy()
            df_report_fallback["dia_operacional"] = pd.to_datetime([], errors="coerce")
            df_report_fallback[irregularidade_col] = False
            for _k, _v in params_export.items():
                df_report_fallback[_k] = _v

        if excluir_planta_999_nesta_irregularidade:
            df_report_fallback = _filtrar_df_sem_planta_999(df_report_fallback)

        gerar_relatorio_pdf(base_relatorio if base_relatorio is not None else df_report_fallback, titulo=titulo, pdf_path=pdf_path)
        gc.collect()
        print("Parquet:", parquet_path)
        print("PDF   :", pdf_path)
        return df_report_fallback

    df_out = df_min_raw.iloc[row_ids].copy()
    df_out["dia_operacional"] = pd.to_datetime(dia_op_arr[row_ids], errors="coerce")
    df_out[irregularidade_col] = True
    for _k, _v in params_export.items():
        df_out[_k] = _v
    df_out.drop(columns=["_row_id"], inplace=True, errors="ignore")

    if excluir_planta_999_nesta_irregularidade:
        df_out = _filtrar_df_sem_planta_999(df_out)

    df_out.to_parquet(parquet_path, index=False)
    gerar_relatorio_pdf(base_relatorio if base_relatorio is not None else df_out, titulo=titulo, pdf_path=pdf_path)

    gc.collect()
    print("Parquet:", parquet_path)
    print("PDF   :", pdf_path)
    return df_out

# Mantém referência dos helpers modernos para evitar regressão por redefinições posteriores.
_gerar_relatorio_pdf_moderno = gerar_relatorio_pdf
_row_ids_from_keys_moderno = row_ids_from_keys
_materializar_e_exportar_por_rowid_moderno = materializar_e_exportar_por_rowid

