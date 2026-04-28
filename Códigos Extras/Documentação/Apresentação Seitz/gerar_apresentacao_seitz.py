from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape
from pathlib import Path
from shutil import copy2

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dateutil.easter import easter


REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "saida"
DW_DEFAULT = REPO_ROOT / "project" / "database" / "dw_ronda.sqlite"
VW_LOGO_SOURCE = REPO_ROOT / "project" / "website" / "images" / "logo_white.png"

RULE_CHANGE_DATE = pd.Timestamp("2025-05-01")
REQ_PRESENTIAL_DAYS = 3.0
REQ_PRESENTIAL_DAYS_HOLIDAY_WEEK = 2.0
ADHERENCE_THRESHOLD_PCT = 90.0
AREA_EXCLUDE_PREFIXES = ("B-V", "B-SNP")
MANAGEMENT_FOCUS_EXCLUDE_TERMS = ("POS VENDAS", "EXTERIOR")
COLLECTIVE_VACATION_PERIODS = (
    (pd.Timestamp("2023-12-18"), pd.Timestamp("2024-01-07")),
    (pd.Timestamp("2024-12-23"), pd.Timestamp("2025-01-12")),
    (pd.Timestamp("2025-12-22"), pd.Timestamp("2026-01-11")),
)
BRAZIL_FIXED_HOLIDAYS = (
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (12, 25, "Natal"),
)
REQUEST_SPECIFICATIONS = (
    "Responder primeiro a quantidade de pessoas abaixo de 90% e as faixas pedidas.",
    "Usar o dw_ronda.sqlite como base oficial.",
    "Tirar pessoas ja desligadas do calculo.",
    "Incluir a logo da Volkswagen na apresentacao.",
    "Deixar o texto maior para leitura em tela e projetor.",
    "Remover semanas com ferias coletivas do calculo.",
    "Em semana com feriado, considerar critica apenas presenca de 0 ou 1 dia.",
)
PRESENTATION_AUTHOR_NAME = "Nicholas Birochi"
PRESENTATION_AUTHOR_ROLE = "Estagiário"
PRESENTATION_AUTHOR_TEAM = "Volkswagen do Brasil"


@dataclass(frozen=True)
class AnalysisConfig:
    dw_path: Path
    reference_date: pd.Timestamp
    rule_change_date: pd.Timestamp
    required_days: float
    adherence_threshold_pct: float
    output_dir: Path


def parse_args() -> AnalysisConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Gera a estatistica de presencialidade fraca para a apresentacao Seitz "
            "a partir do DW SQLite do projeto."
        )
    )
    parser.add_argument(
        "--dw-path",
        default=str(DW_DEFAULT),
        help="Caminho do dw_ronda.sqlite.",
    )
    parser.add_argument(
        "--reference-date",
        default="2026-04-23",
        help="Data de referencia do corte (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--rule-change-date",
        default=str(RULE_CHANGE_DATE.date()),
        help="Data em que a regra de 3 dias passou a valer (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--required-days",
        type=float,
        default=REQ_PRESENTIAL_DAYS,
        help="Quantidade esperada de dias presenciais por semana.",
    )
    parser.add_argument(
        "--adherence-threshold-pct",
        type=float,
        default=ADHERENCE_THRESHOLD_PCT,
        help="Limite percentual para considerar nao aderente.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="Pasta de saida dos artefatos.",
    )
    args = parser.parse_args()

    return AnalysisConfig(
        dw_path=Path(args.dw_path).resolve(),
        reference_date=pd.Timestamp(args.reference_date).normalize(),
        rule_change_date=pd.Timestamp(args.rule_change_date).normalize(),
        required_days=float(args.required_days),
        adherence_threshold_pct=float(args.adherence_threshold_pct),
        output_dir=Path(args.output_dir).resolve(),
    )


def ensure_output_dirs(output_dir: Path) -> tuple[Path, Path, Path]:
    charts_dir = output_dir / "charts"
    assets_dir = output_dir / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    return output_dir, charts_dir, assets_dir


def query_scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> object | None:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0]


def fetch_weekly_data(conn: sqlite3.Connection, config: AnalysisConfig) -> tuple[pd.DataFrame, pd.Timestamp]:
    last_week_raw = query_scalar(
        conn,
        """
        SELECT MAX(Data)
        FROM vw_semana_enriquecida
        WHERE Data <= ?
        """,
        (config.reference_date.strftime("%Y-%m-%d"),),
    )
    if last_week_raw is None:
        raise RuntimeError("Nao foi possivel identificar a ultima semana disponivel no DW.")

    last_week = pd.Timestamp(last_week_raw).normalize()
    week_start = (config.rule_change_date - pd.Timedelta(days=config.rule_change_date.weekday())).normalize()

    sql = """
    SELECT
        Cadastro,
        Nome,
        Cargo,
        [Cargo Especifico] AS [Cargo Especifico],
        [Área] AS [Area],
        Departamento,
        Heranca,
        Desligado,
        Ano,
        [Semana por Ano] AS [Semana por Ano],
        Data,
        [Contagem Presença] AS [Contagem Presenca]
    FROM vw_semana_enriquecida
    WHERE Data BETWEEN ? AND ?
      AND Desligado = 'Não'
      AND Cargo IN ('M', 'E')
    ORDER BY Cadastro, Data
    """
    df = pd.read_sql_query(
        sql,
        conn,
        params=(
            week_start.strftime("%Y-%m-%d"),
            last_week.strftime("%Y-%m-%d"),
        ),
        parse_dates=["Data"],
    )
    return df, last_week


def normalize_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def build_brazil_holidays_df(years: range) -> pd.DataFrame:
    rows: list[tuple[pd.Timestamp, str]] = []
    for year in years:
        for month, day, name in BRAZIL_FIXED_HOLIDAYS:
            rows.append((pd.Timestamp(year=year, month=month, day=day), name))
        if year >= 2024:
            rows.append((pd.Timestamp(year=year, month=11, day=20), "Consciência Negra"))
        easter_day = pd.Timestamp(easter(year))
        rows.append((easter_day - pd.Timedelta(days=2), "Sexta-feira Santa"))
        rows.append((easter_day + pd.Timedelta(days=60), "Corpus Christi"))
        rows.append((easter_day - pd.Timedelta(days=47), "Carnaval (terça)"))

    holidays = pd.DataFrame(rows, columns=["data", "nome"])
    holidays["data"] = pd.to_datetime(holidays["data"], errors="coerce").dt.normalize()
    holidays = (
        holidays.dropna(subset=["data"])
        .drop_duplicates(subset=["data"])
        .sort_values("data", kind="mergesort")
        .reset_index(drop=True)
    )
    holidays["semana_inicio"] = holidays["data"] - pd.to_timedelta(holidays["data"].dt.weekday, unit="D")
    return holidays


def build_week_rules(raw_df: pd.DataFrame, config: AnalysisConfig) -> pd.DataFrame:
    week_rules = (
        raw_df[["Data"]]
        .drop_duplicates()
        .rename(columns={"Data": "semana_inicio"})
        .sort_values("semana_inicio", kind="mergesort")
        .reset_index(drop=True)
    )
    week_rules["semana_inicio"] = pd.to_datetime(week_rules["semana_inicio"], errors="coerce").dt.normalize()
    week_rules["semana_fim"] = week_rules["semana_inicio"] + pd.Timedelta(days=6)
    week_rules["semana_ferias_coletivas"] = False
    week_rules["ferias_periodo"] = ""

    for inicio, fim in COLLECTIVE_VACATION_PERIODS:
        overlap = (week_rules["semana_inicio"] <= fim) & (week_rules["semana_fim"] >= inicio)
        week_rules.loc[overlap, "semana_ferias_coletivas"] = True
        week_rules.loc[overlap, "ferias_periodo"] = (
            inicio.strftime("%Y-%m-%d") + " a " + fim.strftime("%Y-%m-%d")
        )

    if week_rules.empty:
        week_rules["semana_feriado"] = False
        week_rules["feriados_nomes"] = ""
        week_rules["feriados_datas"] = ""
        week_rules["meta_dias_semana"] = float(config.required_days)
        week_rules["criterio_semana"] = "Semana normal"
        return week_rules

    years = range(
        int(week_rules["semana_inicio"].min().year),
        int(week_rules["semana_fim"].max().year) + 1,
    )
    holidays = build_brazil_holidays_df(years)
    holidays_grouped = (
        holidays.groupby("semana_inicio", as_index=False)
        .agg(
            feriados_nomes=("nome", lambda values: " | ".join(sorted(dict.fromkeys(str(v) for v in values if str(v).strip())))),
            feriados_datas=("data", lambda values: " | ".join(pd.to_datetime(values).dt.strftime("%Y-%m-%d").tolist())),
        )
    )
    week_rules = week_rules.merge(holidays_grouped, on="semana_inicio", how="left")
    week_rules["feriados_nomes"] = week_rules["feriados_nomes"].fillna("")
    week_rules["feriados_datas"] = week_rules["feriados_datas"].fillna("")
    week_rules["semana_feriado"] = week_rules["feriados_nomes"].ne("")
    week_rules["meta_dias_semana"] = np.where(
        week_rules["semana_feriado"],
        REQ_PRESENTIAL_DAYS_HOLIDAY_WEEK,
        float(config.required_days),
    ).astype(float)
    week_rules["criterio_semana"] = np.where(
        week_rules["semana_ferias_coletivas"],
        "Semana removida por ferias coletivas",
        np.where(
            week_rules["semana_feriado"],
            "Semana com feriado: critica apenas se houver 0 ou 1 dia presencial",
            f"Semana normal: meta de {float(config.required_days):.1f} dias presenciais",
        ),
    )
    return week_rules.sort_values("semana_inicio", kind="mergesort").reset_index(drop=True)


def apply_week_rules(df: pd.DataFrame, week_rules: pd.DataFrame) -> pd.DataFrame:
    work = df.merge(
        week_rules,
        left_on="Data",
        right_on="semana_inicio",
        how="left",
        validate="many_to_one",
    )
    work = work[~work["semana_ferias_coletivas"].fillna(False)].copy()
    return work


def copy_logo_asset(assets_dir: Path) -> Path | None:
    if not VW_LOGO_SOURCE.exists():
        return None
    dest = assets_dir / VW_LOGO_SOURCE.name
    copy2(VW_LOGO_SOURCE, dest)
    return dest


def apply_factory_filters(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["Area"] = normalize_text(work["Area"])
    work["Heranca"] = normalize_text(work["Heranca"])
    work = work[work["Area"].str.startswith("B-")].copy()
    exclude_mask = work["Area"].str.startswith(AREA_EXCLUDE_PREFIXES) | work["Heranca"].str.startswith(
        AREA_EXCLUDE_PREFIXES
    )
    work = work[~exclude_mask].copy()
    return work


def classify_media_bucket(avg_days: float, required_days: float) -> str:
    if pd.isna(avg_days):
        return "Sem média"
    if avg_days <= 1.0:
        return "Até 1,0 dia"
    if avg_days <= 1.5:
        return "De 1,0 a 1,5"
    if avg_days <= 2.0:
        return "De 1,5 a 2,0"
    if avg_days <= 2.5:
        return "De 2,0 a 2,5"
    if avg_days < (required_days * 0.9):
        return "Acima de 2,5 e abaixo de 90%"
    return "Aderente"


def build_people_summary(df: pd.DataFrame, config: AnalysisConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    grouped = (
        df.groupby("Cadastro", as_index=False)
        .agg(
            Nome=("Nome", "last"),
            Cargo=("Cargo", "last"),
            Cargo_Especifico=("Cargo Especifico", "last"),
            Area=("Area", "last"),
            Departamento=("Departamento", "last"),
            Heranca=("Heranca", "last"),
            semanas_monitoradas=("Data", "nunique"),
            semanas_com_feriado=("semana_feriado", "sum"),
            primeira_semana=("Data", "min"),
            ultima_semana=("Data", "max"),
            media_meta_semana=("meta_dias_semana", "mean"),
            media_dias_presenciais_semana=("Contagem Presenca", "mean"),
            total_dias_presenciais=("Contagem Presenca", "sum"),
        )
        .sort_values(["media_dias_presenciais_semana", "Nome", "Cadastro"], kind="mergesort")
        .reset_index(drop=True)
    )

    grouped["media_meta_semana"] = pd.to_numeric(grouped["media_meta_semana"], errors="coerce").fillna(
        float(config.required_days)
    )
    grouped["aderencia_pct"] = (
        grouped["media_dias_presenciais_semana"] / grouped["media_meta_semana"] * 100.0
    )
    grouped["gap_dias_para_meta"] = grouped["media_meta_semana"] - grouped["media_dias_presenciais_semana"]
    grouped["faixa_media_dias"] = grouped.apply(
        lambda row: classify_media_bucket(
            float(row["media_dias_presenciais_semana"]),
            float(row["media_meta_semana"]),
        ),
        axis=1,
    )
    grouped["nao_aderente"] = grouped["aderencia_pct"] < float(config.adherence_threshold_pct)
    grouped["aderencia_pct"] = grouped["aderencia_pct"].round(1)
    grouped["media_meta_semana"] = grouped["media_meta_semana"].round(2)
    grouped["media_dias_presenciais_semana"] = grouped["media_dias_presenciais_semana"].round(2)
    grouped["gap_dias_para_meta"] = grouped["gap_dias_para_meta"].round(2)
    grouped["semanas_com_feriado"] = (
        pd.to_numeric(grouped["semanas_com_feriado"], errors="coerce").fillna(0).astype(int)
    )

    bad = grouped[grouped["nao_aderente"]].copy()
    return grouped, bad


def build_bucket_tables(bad: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    total_bad = max(int(len(bad)), 1)
    cutoffs = [
        ("Até 1,0 dia", 1.0),
        ("Até 1,5 dia", 1.5),
        ("Até 2,0 dias", 2.0),
        ("Até 2,5 dias", 2.5),
    ]

    cumulative_rows: list[dict[str, object]] = []
    for label, cutoff in cutoffs:
        count = int((bad["media_dias_presenciais_semana"] <= cutoff).sum())
        cumulative_rows.append(
            {
                "Faixa": label,
                "Cutoff": cutoff,
                "Pessoas": count,
                "Percentual": round((count / total_bad) * 100.0, 1),
            }
        )
    cumulative_df = pd.DataFrame(cumulative_rows)

    bucket_order = [
        "Até 1,0 dia",
        "De 1,0 a 1,5",
        "De 1,5 a 2,0",
        "De 2,0 a 2,5",
        "Acima de 2,5 e abaixo de 90%",
    ]
    distribution = (
        bad.assign(Faixa=bad["faixa_media_dias"])
        .groupby("Faixa")
        .size()
        .rename("Pessoas")
        .reindex(bucket_order, fill_value=0)
        .reset_index()
    )
    distribution["Percentual"] = (distribution["Pessoas"] / total_bad * 100.0).round(1)
    return cumulative_df, distribution


def build_cargo_summary(all_people: pd.DataFrame, bad: pd.DataFrame) -> pd.DataFrame:
    total_by_cargo = (
        all_people.groupby("Cargo")
        .size()
        .rename("Total Pessoas")
        .reset_index()
    )
    bad_by_cargo = (
        bad.groupby("Cargo")
        .size()
        .rename("Nao Aderentes")
        .reset_index()
    )
    out = total_by_cargo.merge(bad_by_cargo, on="Cargo", how="left").fillna({"Nao Aderentes": 0})
    out["Nao Aderentes"] = out["Nao Aderentes"].astype(int)
    out["Percentual Nao Aderentes"] = (
        out["Nao Aderentes"] / out["Total Pessoas"] * 100.0
    ).round(1)
    return out.sort_values("Nao Aderentes", ascending=False, kind="mergesort").reset_index(drop=True)


def build_area_summary(all_people: pd.DataFrame, bad: pd.DataFrame) -> pd.DataFrame:
    total = (
        all_people.groupby(["Area", "Departamento", "Heranca"])
        .size()
        .rename("Total Pessoas")
        .reset_index()
    )
    bad_count = (
        bad.groupby(["Area", "Departamento", "Heranca"])
        .agg(
            **{
                "Nao Aderentes": ("Cadastro", "size"),
                "Media Dias Nao Aderentes": ("media_dias_presenciais_semana", "mean"),
            }
        )
        .reset_index()
    )
    out = total.merge(bad_count, on=["Area", "Departamento", "Heranca"], how="left").fillna(
        {"Nao Aderentes": 0}
    )
    out["Nao Aderentes"] = out["Nao Aderentes"].astype(int)
    out["Percentual Nao Aderentes"] = (
        out["Nao Aderentes"] / out["Total Pessoas"] * 100.0
    ).round(1)
    out["Media Dias Nao Aderentes"] = pd.to_numeric(
        out["Media Dias Nao Aderentes"], errors="coerce"
    ).round(2)
    out = out.sort_values(
        ["Nao Aderentes", "Percentual Nao Aderentes", "Area"],
        ascending=[False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return out


def build_management_focus_tables(area_df: pd.DataFrame, top_n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "Area",
        "Departamento",
        "Total Pessoas",
        "Nao Aderentes",
        "Percentual Nao Aderentes",
        "Media Dias Nao Aderentes",
    ]
    work = area_df.copy()
    text_scope = (
        work[["Area", "Departamento", "Heranca"]]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.upper()
    )
    for term in MANAGEMENT_FOCUS_EXCLUDE_TERMS:
        work = work[~text_scope.str.contains(term, regex=False)].copy()
        text_scope = text_scope.loc[work.index]
    volume_df = (
        work[columns]
        .sort_values(
            ["Nao Aderentes", "Percentual Nao Aderentes", "Area"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        .head(top_n)
        .reset_index(drop=True)
    )
    min_people = 10
    rate_base = work[work["Total Pessoas"].ge(min_people)].copy()
    if rate_base.empty:
        rate_base = work.copy()
    rate_df = (
        rate_base[columns]
        .sort_values(
            ["Percentual Nao Aderentes", "Nao Aderentes", "Area"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        .head(top_n)
        .reset_index(drop=True)
    )
    return volume_df, rate_df


def build_weekly_manager_summary(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["Contagem Presenca"] = pd.to_numeric(work["Contagem Presenca"], errors="coerce").fillna(0.0)
    work["meta_dias_semana"] = pd.to_numeric(work["meta_dias_semana"], errors="coerce").fillna(
        REQ_PRESENTIAL_DAYS
    )
    work["semana_feriado"] = work["semana_feriado"].fillna(False).astype(bool)
    work["critico_semana"] = np.where(
        work["semana_feriado"],
        work["Contagem Presenca"] <= 1.0,
        work["Contagem Presenca"] < (work["meta_dias_semana"] * 0.9),
    )
    weekly = (
        work.groupby("Data", as_index=False)
        .agg(
            total_pessoas=("Cadastro", "nunique"),
            pessoas_criticas=("critico_semana", "sum"),
            media_presenca=("Contagem Presenca", "mean"),
            media_meta=("meta_dias_semana", "mean"),
            semana_feriado=("semana_feriado", "max"),
        )
        .sort_values("Data", kind="mergesort")
        .reset_index(drop=True)
    )
    weekly["percentual_criticas"] = (
        weekly["pessoas_criticas"] / weekly["total_pessoas"] * 100.0
    ).round(1)
    weekly["media_movel_4s"] = weekly["percentual_criticas"].rolling(4, min_periods=1).mean().round(1)
    weekly["media_presenca"] = weekly["media_presenca"].round(2)
    weekly["media_meta"] = weekly["media_meta"].round(2)
    weekly["aderencia_media_pct"] = (weekly["media_presenca"] / weekly["media_meta"] * 100.0).round(1)
    weekly["media_presenca_movel_4s"] = weekly["media_presenca"].rolling(4, min_periods=1).mean().round(2)
    weekly["rotulo_semana"] = pd.to_datetime(weekly["Data"]).dt.strftime("%d/%m")
    weekly["tipo_semana"] = np.where(weekly["semana_feriado"], "Feriado", "Normal")
    return weekly


def build_department_management_summary(
    df: pd.DataFrame,
    recent_weeks: int = 8,
    top_areas: int = 6,
    departments_per_area: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = df.copy()
    work["Contagem Presenca"] = pd.to_numeric(work["Contagem Presenca"], errors="coerce").fillna(0.0)
    work["meta_dias_semana"] = pd.to_numeric(work["meta_dias_semana"], errors="coerce").fillna(
        REQ_PRESENTIAL_DAYS
    )
    work["semana_feriado"] = work["semana_feriado"].fillna(False).astype(bool)
    work["critico_semana"] = np.where(
        work["semana_feriado"],
        work["Contagem Presenca"] <= 1.0,
        work["Contagem Presenca"] < (work["meta_dias_semana"] * 0.9),
    )
    dept_weekly = (
        work.groupby(["Area", "Departamento", "Data"], as_index=False)
        .agg(
            total_pessoas=("Cadastro", "nunique"),
            pessoas_criticas=("critico_semana", "sum"),
            media_presenca=("Contagem Presenca", "mean"),
            media_meta=("meta_dias_semana", "mean"),
        )
        .sort_values(["Data", "Area", "Departamento"], kind="mergesort")
        .reset_index(drop=True)
    )
    dept_weekly["percentual_criticas"] = (
        dept_weekly["pessoas_criticas"] / dept_weekly["total_pessoas"] * 100.0
    ).round(1)
    dept_weekly["rotulo_departamento"] = (
        dept_weekly["Area"].astype(str).str.strip()
        + " | "
        + dept_weekly["Departamento"].astype(str).str.strip()
    )

    recent_dates = sorted(pd.to_datetime(dept_weekly["Data"].drop_duplicates()).tolist())
    if recent_dates:
        recent_dates = recent_dates[-recent_weeks:]
    dept_recent = dept_weekly[dept_weekly["Data"].isin(recent_dates)].copy()

    dept_recent_summary = (
        dept_recent.groupby(["Area", "Departamento", "rotulo_departamento"], as_index=False)
        .agg(
            semanas_monitoradas=("Data", "nunique"),
            total_pessoas_medio=("total_pessoas", "mean"),
            casos_criticos_recentes=("pessoas_criticas", "sum"),
            criticidade_media_recente=("percentual_criticas", "mean"),
            pior_semana_recente=("percentual_criticas", "max"),
            presenca_media_recente=("media_presenca", "mean"),
        )
        .sort_values(
            ["casos_criticos_recentes", "criticidade_media_recente", "rotulo_departamento"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )
    dept_recent_summary["total_pessoas_medio"] = dept_recent_summary["total_pessoas_medio"].round(1)
    dept_recent_summary["criticidade_media_recente"] = dept_recent_summary["criticidade_media_recente"].round(1)
    dept_recent_summary["pior_semana_recente"] = dept_recent_summary["pior_semana_recente"].round(1)
    dept_recent_summary["presenca_media_recente"] = dept_recent_summary["presenca_media_recente"].round(2)

    area_priority = (
        dept_recent_summary.groupby("Area", as_index=False)
        .agg(
            casos_criticos_recentes=("casos_criticos_recentes", "sum"),
            criticidade_media_recente=("criticidade_media_recente", "mean"),
        )
        .sort_values(
            ["casos_criticos_recentes", "criticidade_media_recente", "Area"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )
    selected_rows: list[pd.DataFrame] = []
    for area in area_priority.head(top_areas)["Area"].tolist():
        area_rows = (
            dept_recent_summary[dept_recent_summary["Area"].eq(area)]
            .sort_values(
                ["casos_criticos_recentes", "criticidade_media_recente", "Departamento"],
                ascending=[False, False, True],
                kind="mergesort",
            )
            .head(departments_per_area)
        )
        if not area_rows.empty:
            selected_rows.append(area_rows)

    if selected_rows:
        heatmap_priority = pd.concat(selected_rows, ignore_index=True)
    else:
        heatmap_priority = dept_recent_summary.head(top_areas * departments_per_area).copy()

    heatmap_priority = heatmap_priority.drop_duplicates(subset=["rotulo_departamento"]).reset_index(drop=True)
    top_labels = heatmap_priority["rotulo_departamento"].tolist()
    heatmap_df = dept_recent[dept_recent["rotulo_departamento"].isin(top_labels)].copy()
    heatmap_df["semana_inicio"] = pd.to_datetime(heatmap_df["Data"])
    heatmap_df["rotulo_heatmap"] = (
        heatmap_df["Area"].astype(str).str.strip()
        + "\n"
        + heatmap_df["Departamento"].astype(str).str.strip()
    )
    ordered_recent_dates = pd.Index(pd.to_datetime(recent_dates))
    row_order = (
        heatmap_priority["Area"].astype(str).str.strip()
        + "\n"
        + heatmap_priority["Departamento"].astype(str).str.strip()
    )
    heatmap_pivot = (
        heatmap_df.pivot_table(
            index="rotulo_heatmap",
            columns="semana_inicio",
            values="percentual_criticas",
            aggfunc="mean",
        )
        .reindex(row_order)
        .reindex(columns=ordered_recent_dates)
    )
    presence_pivot = (
        heatmap_df.pivot_table(
            index="rotulo_heatmap",
            columns="semana_inicio",
            values="media_presenca",
            aggfunc="mean",
        )
        .reindex(row_order)
        .reindex(columns=ordered_recent_dates)
    )
    heatmap_pivot = heatmap_pivot.rename(
        columns={
            ts: f"{int(ts.isocalendar().week):02d}\n({ts.strftime('%d/%m')})"
            for ts in ordered_recent_dates
        }
    )
    presence_pivot = presence_pivot.rename(
        columns={
            ts: f"{int(ts.isocalendar().week):02d}\n({ts.strftime('%d/%m')})"
            for ts in ordered_recent_dates
        }
    )
    heatmap_pivot["Media"] = (
        heatmap_priority.set_index(row_order)["criticidade_media_recente"]
        .round(1)
    )
    presence_pivot["Media"] = (
        heatmap_priority.set_index(row_order)["presenca_media_recente"]
        .round(1)
    )
    heatmap_pivot.attrs["avg_presence"] = presence_pivot
    return dept_recent_summary, heatmap_pivot


def build_exec_summary(
    all_people: pd.DataFrame,
    bad: pd.DataFrame,
    cumulative_df: pd.DataFrame,
    distribution_df: pd.DataFrame,
    week_rules: pd.DataFrame,
    last_week: pd.Timestamp,
    config: AnalysisConfig,
) -> pd.DataFrame:
    total_people = int(len(all_people))
    bad_people = int(len(bad))
    pct_bad = round((bad_people / total_people) * 100.0, 1) if total_people else 0.0
    avg_bad = round(float(bad["media_dias_presenciais_semana"].mean()), 2) if bad_people else 0.0
    median_bad = (
        round(float(bad["media_dias_presenciais_semana"].median()), 2) if bad_people else 0.0
    )
    avg_required = (
        round(float(all_people["media_meta_semana"].mean()), 2) if not all_people.empty else float(config.required_days)
    )
    holiday_weeks = week_rules[
        week_rules["semana_feriado"] & ~week_rules["semana_ferias_coletivas"]
    ].copy()
    removed_vacation_weeks = week_rules[week_rules["semana_ferias_coletivas"]].copy()
    holiday_weeks_str = ", ".join(holiday_weeks["semana_inicio"].dt.strftime("%Y-%m-%d").tolist()) or "Nenhuma"
    removed_vacation_weeks_str = (
        ", ".join(removed_vacation_weeks["semana_inicio"].dt.strftime("%Y-%m-%d").tolist()) or "Nenhuma"
    )

    rows = [
        ("Data de referencia", config.reference_date.strftime("%Y-%m-%d")),
        ("Ultima semana completa usada", last_week.strftime("%Y-%m-%d")),
        (
            "Periodo analisado",
            f"{week_rules.loc[~week_rules['semana_ferias_coletivas'], 'semana_inicio'].min().strftime('%Y-%m-%d')} a {week_rules.loc[~week_rules['semana_ferias_coletivas'], 'semana_inicio'].max().strftime('%Y-%m-%d')}",
        ),
        ("Meta presencial por semana", f"{config.required_days:.1f} dias"),
        ("Meta em semana com feriado", f"{REQ_PRESENTIAL_DAYS_HOLIDAY_WEEK:.1f} dias"),
        ("Regra especial em semana de feriado", "Critica apenas se houver 0 ou 1 dia presencial"),
        ("Limite de nao aderencia", f"< {config.adherence_threshold_pct:.0f}%"),
        ("Universo considerado", str(total_people)),
        ("Status dos desligados", "Fora do calculo"),
        ("Semanas de feriado consideradas", str(int(len(holiday_weeks)))),
        ("Semanas de ferias coletivas removidas", str(int(len(removed_vacation_weeks)))),
        ("Nao aderentes", str(bad_people)),
        ("Percentual nao aderente", f"{pct_bad:.1f}%"),
        (
            "Resposta curta",
            f"{bad_people} pessoas abaixo de {config.adherence_threshold_pct:.0f}% ({pct_bad:.1f}% das pessoas consideradas).",
        ),
        ("Media da meta semanal no periodo", f"{avg_required:.2f} dias"),
        ("Media semanal dos nao aderentes", f"{avg_bad:.2f} dias"),
        ("Mediana semanal dos nao aderentes", f"{median_bad:.2f} dias"),
        ("Até 1,0 dia", f"{cumulative_df.loc[cumulative_df['Faixa'].eq('Até 1,0 dia'), 'Percentual'].iloc[0]:.1f}%"),
        ("Até 1,5 dia", f"{cumulative_df.loc[cumulative_df['Faixa'].eq('Até 1,5 dia'), 'Percentual'].iloc[0]:.1f}%"),
        ("Até 2,0 dias", f"{cumulative_df.loc[cumulative_df['Faixa'].eq('Até 2,0 dias'), 'Percentual'].iloc[0]:.1f}%"),
        ("Até 2,5 dias", f"{cumulative_df.loc[cumulative_df['Faixa'].eq('Até 2,5 dias'), 'Percentual'].iloc[0]:.1f}%"),
        (
            "Acima de 2,5 e abaixo de 90%",
            f"{distribution_df.loc[distribution_df['Faixa'].eq('Acima de 2,5 e abaixo de 90%'), 'Percentual'].iloc[0]:.1f}%",
        ),
        ("Datas das semanas com feriado", holiday_weeks_str),
        ("Datas das semanas removidas por ferias", removed_vacation_weeks_str),
        (
            "Regras aplicadas",
            "Desligados removidos, cargos M/E, area iniciando em B-, excluidas areas B-V e B-SNP, com regra especial para semanas de feriado.",
        ),
    ]
    return pd.DataFrame(rows, columns=["Indicador", "Valor"])


def save_excel(
    output_path: Path,
    exec_summary: pd.DataFrame,
    cumulative_df: pd.DataFrame,
    distribution_df: pd.DataFrame,
    cargo_df: pd.DataFrame,
    area_df: pd.DataFrame,
    weekly_manager_df: pd.DataFrame,
    department_recent_df: pd.DataFrame,
    department_heatmap_df: pd.DataFrame,
    specs_df: pd.DataFrame,
    week_rules_df: pd.DataFrame,
    all_people: pd.DataFrame,
    bad: pd.DataFrame,
) -> None:
    summary_map = dict(exec_summary.values.tolist())
    indicator_labels = {
        "Universo considerado": "Pessoas consideradas",
        "Status dos desligados": "Desligados",
        "Limite de nao aderencia": "Entra na lista",
        "Nao aderentes": "Abaixo de 90%",
        "Percentual nao aderente": "% das pessoas consideradas",
        "Media semanal dos nao aderentes": "Media semanal abaixo de 90%",
        "Mediana semanal dos nao aderentes": "Mediana semanal abaixo de 90%",
        "Media da meta semanal no periodo": "Meta media no periodo",
    }
    exec_summary_display = exec_summary.copy()
    exec_summary_display["Indicador"] = exec_summary_display["Indicador"].replace(indicator_labels)
    exec_summary_display = exec_summary_display.rename(columns={"Indicador": "Item"})
    faixa_txt = "; ".join(
        f"{row.Faixa}: {float(row.Percentual):.1f}%"
        for row in cumulative_df.itertuples(index=False)
    )
    quick_read_df = pd.DataFrame(
        [
            {
                "Pergunta": "Quem esta abaixo de 90%?",
                "Resposta": f"{summary_map['Nao aderentes']} pessoas ({summary_map['Percentual nao aderente']} das pessoas consideradas).",
            },
            {
                "Pergunta": "Como ler as faixas?",
                "Resposta": faixa_txt,
            },
            {
                "Pergunta": "Qual e a regra?",
                "Resposta": "Semana normal: 3 dias. Semana com feriado: critica apenas com 0 ou 1 dia.",
            },
            {
                "Pergunta": "Quem entrou no calculo?",
                "Resposta": "Pessoas ativas M/E, areas B-, sem B-V e B-SNP.",
            },
        ]
    )
    top_volume_df, top_rate_df = build_management_focus_tables(area_df)
    deep_dive_note_df = pd.DataFrame(
        [
            {
                "Leitura": "Volume",
                "Como usar": "Onde ha mais pessoas abaixo de 90%. Melhor para priorizar impacto.",
            },
            {
                "Leitura": "Percentual",
                "Como usar": "Onde o problema pesa mais dentro da propria area. Base minima: 10 pessoas.",
            },
            {
                "Leitura": "Heatmap",
                "Como usar": "Apoio para ver semana a semana. Nao usar como primeira leitura.",
            },
        ]
    )
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        quick_read_df.to_excel(writer, sheet_name="Leia Primeiro", index=False)
        deep_dive_note_df.to_excel(writer, sheet_name="Aprofundamento Gestor", index=False)
        top_volume_df.to_excel(
            writer,
            sheet_name="Aprofundamento Gestor",
            startrow=len(deep_dive_note_df) + 3,
            index=False,
        )
        top_rate_df.to_excel(
            writer,
            sheet_name="Aprofundamento Gestor",
            startrow=len(deep_dive_note_df) + len(top_volume_df) + 7,
            index=False,
        )
        ws_focus = writer.sheets["Aprofundamento Gestor"]
        ws_focus.cell(row=len(deep_dive_note_df) + 3, column=1, value="Top 10 por volume")
        ws_focus.cell(
            row=len(deep_dive_note_df) + len(top_volume_df) + 7,
            column=1,
            value="Top 10 por percentual da area",
        )
        specs_df.to_excel(writer, sheet_name="Especificacoes", index=False)
        exec_summary_display.to_excel(writer, sheet_name="Resumo Executivo", index=False)
        cumulative_df.to_excel(writer, sheet_name="Faixas Cumulativas", index=False)
        distribution_df.to_excel(writer, sheet_name="Distribuicao Faixas", index=False)
        cargo_df.to_excel(writer, sheet_name="Resumo Cargo", index=False)
        area_df.to_excel(writer, sheet_name="Resumo Areas", index=False)
        weekly_manager_df.to_excel(writer, sheet_name="Resumo Semanal Gestao", index=False)
        department_recent_df.to_excel(writer, sheet_name="Resumo Departamentos", index=False)
        department_heatmap_df.to_excel(writer, sheet_name="Heatmap Departamentos")
        week_rules_df.to_excel(writer, sheet_name="Regras Semanais", index=False)
        bad.to_excel(writer, sheet_name="Abaixo de 90", index=False)
        all_people.to_excel(writer, sheet_name="Pessoas Consideradas", index=False)


def _apply_chart_style(ax: plt.Axes, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_title(title, fontsize=24, fontweight="bold", color="#0f2f59", pad=20)
    ax.set_xlabel(xlabel, fontsize=16, color="#5c7086")
    ax.set_ylabel(ylabel, fontsize=16, color="#5c7086")
    ax.set_facecolor("#fbfdff")
    ax.grid(axis="y", linestyle="--", alpha=0.42, color="#d8e3ee")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c8d7e6")
    ax.spines["bottom"].set_color("#c8d7e6")
    ax.tick_params(axis="both", labelsize=14.5, colors="#55677d")


def plot_distribution(distribution_df: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13.5, 7.4), constrained_layout=True)
    colors = ["#f2b7c3", "#f6cd9f", "#bfe7cc", "#aed6f1", "#b9c7ea"]
    ax.bar(distribution_df["Faixa"], distribution_df["Pessoas"], color=colors, width=0.65)
    for idx, row in distribution_df.iterrows():
        ax.text(
            idx,
            row["Pessoas"] + max(distribution_df["Pessoas"].max() * 0.015, 1),
            f"{int(row['Pessoas'])}\n{row['Percentual']:.1f}%",
            ha="center",
            va="bottom",
            fontsize=14,
            color="#1f2937",
        )
    _apply_chart_style(
        ax,
        "Pessoas abaixo de 90% por média semanal presencial",
        ylabel="Quantidade de pessoas",
    )
    ax.tick_params(axis="x", labelrotation=15)
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_top_areas(area_df: pd.DataFrame, out_path: Path, top_n: int = 10) -> None:
    top = area_df.head(top_n).copy()
    labels = top["Area"].astype(str) + " | " + top["Departamento"].astype(str)
    fig, ax = plt.subplots(figsize=(14.0, 8.2), constrained_layout=True)
    ax.barh(labels.iloc[::-1], top["Nao Aderentes"].iloc[::-1], color="#13315c")
    for y, (_, row) in enumerate(top.iloc[::-1].iterrows()):
        ax.text(
            row["Nao Aderentes"] + max(top["Nao Aderentes"].max() * 0.02, 0.4),
            y,
            f"{int(row['Nao Aderentes'])} | {row['Percentual Nao Aderentes']:.1f}%",
            va="center",
            fontsize=11,
            color="#1f2937",
        )
    _apply_chart_style(
        ax,
        "Areas com mais pessoas abaixo de 90% de aderencia",
        xlabel="Pessoas abaixo de 90%",
    )
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_cargo_summary(cargo_df: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 6.6), constrained_layout=True)
    ax.bar(cargo_df["Cargo"], cargo_df["Nao Aderentes"], color=["#2b6cb0", "#d1495b"])
    for idx, row in cargo_df.iterrows():
        ax.text(
            idx,
            row["Nao Aderentes"] + max(cargo_df["Nao Aderentes"].max() * 0.03, 0.4),
            f"{int(row['Nao Aderentes'])}\n{row['Percentual Nao Aderentes']:.1f}%",
            ha="center",
            va="bottom",
            fontsize=12,
            color="#1f2937",
        )
    _apply_chart_style(
        ax,
        "Pessoas abaixo de 90% por cargo",
        ylabel="Pessoas abaixo de 90%",
    )
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_cumulative_thresholds(cumulative_df: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12.2, 6.8), constrained_layout=True)
    colors = ["#efb8c5", "#f6c7a7", "#f2df9d", "#acd3ef"]
    ax.bar(cumulative_df["Faixa"], cumulative_df["Percentual"], color=colors, width=0.62)
    ymax = max(float(cumulative_df["Percentual"].max()), 1.0)
    for idx, row in cumulative_df.iterrows():
        ax.text(
            idx,
            row["Percentual"] + max(ymax * 0.025, 1.0),
            f"{row['Percentual']:.1f}%\n{int(row['Pessoas'])} pessoas",
            ha="center",
            va="bottom",
            fontsize=14,
            color="#1f2937",
        )
    ax.set_ylim(0, min(max(ymax * 1.18, ymax + 8.0), 110.0))
    _apply_chart_style(
        ax,
        "Faixas acumuladas pedidas no briefing",
        ylabel="% das pessoas abaixo de 90%",
    )
    ax.tick_params(axis="x", labelrotation=10)
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_weekly_criticality(weekly_df: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(15.4, 8.2), constrained_layout=True)
    x = np.arange(len(weekly_df))
    media_presenca = weekly_df["media_presenca"].to_numpy(dtype=float)
    rolling = weekly_df["media_presenca_movel_4s"].to_numpy(dtype=float)
    media_meta = weekly_df["media_meta"].to_numpy(dtype=float)
    holiday_mask = weekly_df["semana_feriado"].to_numpy(dtype=bool)
    ax.fill_between(x, media_presenca, color="#dcecf8", alpha=0.95, zorder=1)
    ax.fill_between(x, media_presenca, media_meta, where=media_presenca < media_meta, color="#f7d7df", alpha=0.65, interpolate=True, zorder=1)
    ax.plot(x, media_presenca, color="#0f4c81", linewidth=4.0, marker="o", markersize=6.1, label="Presença média", zorder=3)
    ax.plot(
        x,
        rolling,
        color="#88aecd",
        linewidth=3.0,
        linestyle="--",
        label="Média móvel 4 semanas",
        zorder=4,
    )
    ax.plot(x, media_meta, color="#7cb59b", linewidth=3.0, linestyle="-.", label="Meta da semana", zorder=2)
    if holiday_mask.any():
        ax.scatter(
            x[holiday_mask],
            media_presenca[holiday_mask],
            color="#d790a5",
            edgecolor="#ffffff",
            linewidth=1.4,
            s=98,
            zorder=5,
            label="Semana com feriado",
        )
    low_pos = int(np.nanargmin(media_presenca))
    last_pos = len(weekly_df) - 1
    ax.annotate(
        f"Pior semana {media_presenca[low_pos]:.2f} dia(s)\n{weekly_df.iloc[low_pos]['Data'].strftime('%d/%m/%Y')}",
        xy=(low_pos, media_presenca[low_pos]),
        xytext=(10, 16),
        textcoords="offset points",
        fontsize=13,
        color="#1f2937",
        bbox={"boxstyle": "round,pad=0.35", "fc": "#fff8fb", "ec": "#e7c7d2", "alpha": 0.98},
    )
    ax.annotate(
        f"Última {media_presenca[last_pos]:.2f} dia(s)",
        xy=(last_pos, media_presenca[last_pos]),
        xytext=(-40, -24),
        textcoords="offset points",
        fontsize=13,
        color="#1f2937",
        bbox={"boxstyle": "round,pad=0.35", "fc": "#f4fbff", "ec": "#cde4f6", "alpha": 0.98},
    )
    tick_positions = sorted(set(list(range(0, len(weekly_df), 4)) + [last_pos]))
    tick_labels = weekly_df.iloc[tick_positions]["Data"].dt.strftime("%d/%m").tolist()
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels)
    ymax = max(float(np.nanmax(media_presenca)), float(np.nanmax(rolling)), float(np.nanmax(media_meta)), 1.0)
    ax.set_ylim(0, max(ymax * 1.16, ymax + 0.5))
    _apply_chart_style(
        ax,
        "Tendência semanal da presença média versus meta",
        xlabel="Semanas monitoradas",
        ylabel="Dias presenciais médios por pessoa",
    )
    ax.legend(frameon=False, fontsize=13, loc="upper right", ncol=2)
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_department_heatmap(heatmap_df: pd.DataFrame, out_path: Path) -> None:
    avg_presence = heatmap_df.attrs.get("avg_presence")
    work = heatmap_df.copy()
    if work.empty:
        fig, ax = plt.subplots(figsize=(12.0, 6.0), constrained_layout=True)
        ax.text(0.5, 0.5, "Sem dados para heatmap", ha="center", va="center", fontsize=18, color="#5c677d")
        ax.axis("off")
        fig.savefig(out_path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return

    values = work.to_numpy(dtype=float)
    if np.isnan(values).all():
        fig, ax = plt.subplots(figsize=(12.0, 6.0), constrained_layout=True)
        ax.text(0.5, 0.5, "Sem dados para heatmap", ha="center", va="center", fontsize=18, color="#5c677d")
        ax.axis("off")
        fig.savefig(out_path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return

    fig_height = max(8.2, 0.82 * len(work.index) + 3.2)
    fig, ax = plt.subplots(figsize=(17.2, fig_height), constrained_layout=True)
    vmax = max(float(np.nanmax(values)), 1.0)
    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad("#edf1f5")
    masked_values = np.ma.masked_invalid(values)
    im = ax.imshow(masked_values, cmap=cmap, aspect="auto", vmin=0.0, vmax=vmax)
    presence_values = None
    if isinstance(avg_presence, pd.DataFrame) and not avg_presence.empty:
        presence_values = avg_presence.reindex(index=work.index, columns=work.columns).to_numpy(dtype=float)

    row_labels: list[str] = []
    area_boundaries: list[float] = []
    previous_area = None
    for idx, label in enumerate(work.index.astype(str).tolist()):
        if "\n" in label:
            area, department = label.split("\n", 1)
        else:
            area, department = label, ""
        department = department.strip()
        if len(department) > 44:
            department = department[:41] + "..."
        row_labels.append(f"{area.strip()}\n{department}" if department else area.strip())
        if previous_area is not None and area != previous_area:
            area_boundaries.append(idx - 0.5)
        previous_area = area

    ax.set_xticks(np.arange(len(work.columns)))
    ax.set_xticklabels(work.columns.astype(str).tolist(), fontsize=14, fontweight="semibold")
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=13.5)
    ax.tick_params(top=False, bottom=True, labeltop=False, labelbottom=True)
    ax.set_xticks(np.arange(values.shape[1] + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(values.shape[0] + 1) - 0.5, minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=1.3)
    ax.tick_params(which="minor", bottom=False, left=False)
    for boundary in area_boundaries:
        ax.axhline(boundary, color="#7c8aa5", linewidth=2.0, alpha=0.55)
    if values.shape[1] >= 2:
        ax.axvline(values.shape[1] - 1.5, color="#7c8aa5", linewidth=2.0, alpha=0.55)

    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            value = values[i, j]
            if np.isnan(value):
                ax.text(j, i, "-", ha="center", va="center", fontsize=13, fontweight="semibold", color="#6b7280")
                continue
            text_color = "white" if value >= max(vmax * 0.55, 42) else "#1f2937"
            label = f"{value:.0f}%"
            if presence_values is not None and not np.isnan(presence_values[i, j]):
                label = f"{label}\n{presence_values[i, j]:.1f}d"
            ax.text(j, i, label, ha="center", va="center", fontsize=10.8, fontweight="semibold", color=text_color)

    _apply_chart_style(
        ax,
        "Heatmap: % abaixo da regra semanal + dias médios\n100% não significa ausência total; cinza/- = sem registro no DW",
        xlabel="Semanas recentes; Média = período com dados",
        ylabel="Departamento priorizado",
    )
    cbar = fig.colorbar(im, ax=ax, pad=0.02)
    cbar.set_label("% abaixo da regra, não ausência total", fontsize=15)
    cbar.ax.tick_params(labelsize=13)
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def build_html_report(
    html_path: Path,
    metadata: dict[str, object],
    exec_summary: pd.DataFrame,
    cumulative_df: pd.DataFrame,
    distribution_df: pd.DataFrame,
    area_df: pd.DataFrame,
    weekly_manager_df: pd.DataFrame,
    department_recent_df: pd.DataFrame,
    chart_cumulative: Path,
    chart_weekly: Path,
    chart_department_heatmap: Path,
    chart_distribution: Path,
    logo_path: Path | None,
) -> None:
    summary_map = dict(exec_summary.values.tolist())
    chart_cumulative_rel = chart_cumulative.relative_to(html_path.parent).as_posix()
    chart_weekly_rel = chart_weekly.relative_to(html_path.parent).as_posix()
    chart_distribution_rel = chart_distribution.relative_to(html_path.parent).as_posix()
    logo_rel = logo_path.relative_to(html_path.parent).as_posix() if logo_path is not None else ""
    favicon_html = (
        f'  <link rel="icon" type="image/png" href="{logo_rel}">\n'
        f'  <link rel="shortcut icon" type="image/png" href="{logo_rel}">\n'
        f'  <link rel="apple-touch-icon" href="{logo_rel}">\n'
        if logo_rel
        else ""
    )
    cumulative_records = cumulative_df.to_dict(orient="records")
    cumulative_html = "\n".join(
        f"<tr><td>{escape(str(row['Faixa']))}</td><td>{int(row['Pessoas'])}</td><td>{float(row['Percentual']):.1f}%</td></tr>"
        for row in cumulative_records
    )
    top_volume_df, top_rate_df = build_management_focus_tables(area_df)

    def format_optional_days(value: object) -> str:
        if pd.isna(value):
            return "-"
        return f"{float(value):.2f}"

    def build_focus_rows(df: pd.DataFrame) -> str:
        return "\n".join(
            (
                "<tr>"
                f"<td>{escape(str(row['Area']))}</td>"
                f"<td>{escape(str(row['Departamento']))}</td>"
                f"<td>{int(row['Nao Aderentes'])}</td>"
                f"<td>{float(row['Percentual Nao Aderentes']):.1f}%</td>"
                f"<td>{format_optional_days(row['Media Dias Nao Aderentes'])}</td>"
                "</tr>"
            )
            for row in df.to_dict(orient="records")
        )

    top_volume_html = build_focus_rows(top_volume_df)
    top_rate_html = build_focus_rows(top_rate_df)
    faixa_principal_pct = float(
        distribution_df.loc[distribution_df["Faixa"].eq("De 2,0 a 2,5"), "Percentual"].iloc[0]
    )
    weekly_low = weekly_manager_df.loc[weekly_manager_df["media_presenca"].idxmin()]
    weekly_last = weekly_manager_df.iloc[-1]
    weekly_recent = float(weekly_manager_df["media_presenca"].tail(4).mean())
    def format_locale_date(value: object, locale: str) -> str:
        ts = pd.Timestamp(value)
        date_formats = {
            "pt": "%d/%m/%Y",
            "en": "%m/%d/%Y",
            "de": "%d.%m.%Y",
            "es": "%d/%m/%Y",
            "fr": "%d/%m/%Y",
            "it": "%d/%m/%Y",
            "pl": "%d.%m.%Y",
            "sk": "%d.%m.%Y",
            "zh": "%Y/%m/%d",
            "hi": "%d/%m/%Y",
        }
        return ts.strftime(date_formats.get(locale, date_formats["en"]))

    def format_locale_datetime(value: object, locale: str) -> str:
        ts = pd.Timestamp(value)
        datetime_formats = {
            "pt": "%d/%m/%Y %H:%M",
            "en": "%m/%d/%Y %H:%M",
            "de": "%d.%m.%Y %H:%M",
            "es": "%d/%m/%Y %H:%M",
            "fr": "%d/%m/%Y %H:%M",
            "it": "%d/%m/%Y %H:%M",
            "pl": "%d.%m.%Y %H:%M",
            "sk": "%d.%m.%Y %H:%M",
            "zh": "%Y/%m/%d %H:%M",
            "hi": "%d/%m/%Y %H:%M",
        }
        return ts.strftime(datetime_formats.get(locale, datetime_formats["en"]))

    def format_locale_period(start_value: object, end_value: object, locale: str) -> str:
        joins = {
            "pt": " a ",
            "en": " to ",
            "de": " bis ",
            "es": " a ",
            "fr": " au ",
            "it": " al ",
            "pl": " do ",
            "sk": " do ",
            "zh": " 至 ",
            "hi": " से ",
        }
        return f"{format_locale_date(start_value, locale)}{joins.get(locale, ' to ')}{format_locale_date(end_value, locale)}"

    def format_locale_ranges(periods: list[dict[str, str]], locale: str) -> str:
        joins = {
            "pt": " a ",
            "en": " to ",
            "de": " bis ",
            "es": " a ",
            "fr": " au ",
            "it": " al ",
            "pl": " do ",
            "sk": " do ",
            "zh": " 至 ",
            "hi": " से ",
        }
        return ", ".join(
            f"{format_locale_date(period['inicio'], locale)}{joins.get(locale, ' to ')}{format_locale_date(period['fim'], locale)}"
            for period in periods
        )

    def format_locale_date_list(values: list[object], locale: str) -> str:
        return ", ".join(format_locale_date(value, locale) for value in values)

    period_start_raw, period_end_raw = [part.strip() for part in summary_map["Periodo analisado"].split(" a ", 1)]
    reference_date_pt = format_locale_date(metadata["reference_date"], "pt")
    reference_date_en = format_locale_date(metadata["reference_date"], "en")
    reference_date_de = format_locale_date(metadata["reference_date"], "de")
    reference_date_es = format_locale_date(metadata["reference_date"], "es")
    reference_date_fr = format_locale_date(metadata["reference_date"], "fr")
    reference_date_it = format_locale_date(metadata["reference_date"], "it")
    reference_date_pl = format_locale_date(metadata["reference_date"], "pl")
    reference_date_sk = format_locale_date(metadata["reference_date"], "sk")
    reference_date_zh = format_locale_date(metadata["reference_date"], "zh")
    reference_date_hi = format_locale_date(metadata["reference_date"], "hi")
    last_week_pt = format_locale_date(metadata["last_complete_week"], "pt")
    last_week_en = format_locale_date(metadata["last_complete_week"], "en")
    last_week_de = format_locale_date(metadata["last_complete_week"], "de")
    last_week_es = format_locale_date(metadata["last_complete_week"], "es")
    last_week_fr = format_locale_date(metadata["last_complete_week"], "fr")
    last_week_it = format_locale_date(metadata["last_complete_week"], "it")
    last_week_pl = format_locale_date(metadata["last_complete_week"], "pl")
    last_week_sk = format_locale_date(metadata["last_complete_week"], "sk")
    last_week_zh = format_locale_date(metadata["last_complete_week"], "zh")
    last_week_hi = format_locale_date(metadata["last_complete_week"], "hi")
    generated_at_ts = pd.Timestamp(metadata["generated_at"])
    generated_at_pt = format_locale_datetime(generated_at_ts, "pt")
    generated_at_en = format_locale_datetime(generated_at_ts, "en")
    generated_at_de = format_locale_datetime(generated_at_ts, "de")
    generated_at_es = format_locale_datetime(generated_at_ts, "es")
    generated_at_fr = format_locale_datetime(generated_at_ts, "fr")
    generated_at_it = format_locale_datetime(generated_at_ts, "it")
    generated_at_pl = format_locale_datetime(generated_at_ts, "pl")
    generated_at_sk = format_locale_datetime(generated_at_ts, "sk")
    generated_at_zh = format_locale_datetime(generated_at_ts, "zh")
    generated_at_hi = format_locale_datetime(generated_at_ts, "hi")
    analysis_period_pt = format_locale_period(period_start_raw, period_end_raw, "pt")
    analysis_period_en = format_locale_period(period_start_raw, period_end_raw, "en")
    analysis_period_de = format_locale_period(period_start_raw, period_end_raw, "de")
    analysis_period_es = format_locale_period(period_start_raw, period_end_raw, "es")
    analysis_period_fr = format_locale_period(period_start_raw, period_end_raw, "fr")
    analysis_period_it = format_locale_period(period_start_raw, period_end_raw, "it")
    analysis_period_pl = format_locale_period(period_start_raw, period_end_raw, "pl")
    analysis_period_sk = format_locale_period(period_start_raw, period_end_raw, "sk")
    analysis_period_zh = format_locale_period(period_start_raw, period_end_raw, "zh")
    analysis_period_hi = format_locale_period(period_start_raw, period_end_raw, "hi")
    weekly_low_pt = format_locale_date(weekly_low["Data"], "pt")
    weekly_low_en = format_locale_date(weekly_low["Data"], "en")
    weekly_low_de = format_locale_date(weekly_low["Data"], "de")
    weekly_low_es = format_locale_date(weekly_low["Data"], "es")
    weekly_low_fr = format_locale_date(weekly_low["Data"], "fr")
    weekly_low_it = format_locale_date(weekly_low["Data"], "it")
    weekly_low_pl = format_locale_date(weekly_low["Data"], "pl")
    weekly_low_sk = format_locale_date(weekly_low["Data"], "sk")
    weekly_low_zh = format_locale_date(weekly_low["Data"], "zh")
    weekly_low_hi = format_locale_date(weekly_low["Data"], "hi")
    regular_week_pt = summary_map["Meta presencial por semana"]
    regular_week_en = regular_week_pt.replace(" dias", " days")
    regular_week_de = regular_week_pt.replace(" dias", " Tagen")
    regular_week_es = regular_week_pt.replace(" dias", " días")
    regular_week_fr = regular_week_pt.replace(" dias", " jours")
    regular_week_it = regular_week_pt.replace(" dias", " giorni")
    holiday_week_pt = summary_map["Meta em semana com feriado"]
    holiday_week_en = holiday_week_pt.replace(" dias", " days")
    holiday_week_de = holiday_week_pt.replace(" dias", " Tagen")
    holiday_week_es = holiday_week_pt.replace(" dias", " días")
    holiday_week_fr = holiday_week_pt.replace(" dias", " jours")
    holiday_week_it = holiday_week_pt.replace(" dias", " giorni")
    median_bad_pt = summary_map["Mediana semanal dos nao aderentes"]
    median_bad_en = median_bad_pt.replace(" dias", " days")
    median_bad_de = median_bad_pt.replace(" dias", " Tagen")
    median_bad_es = median_bad_pt.replace(" dias", " días")
    median_bad_fr = median_bad_pt.replace(" dias", " jours")
    median_bad_it = median_bad_pt.replace(" dias", " giorni")
    vacation_periods_validated = format_locale_ranges(metadata["collective_vacation_periods"], "pt")
    vacation_periods_validated_en = format_locale_ranges(metadata["collective_vacation_periods"], "en")
    vacation_periods_validated_de = format_locale_ranges(metadata["collective_vacation_periods"], "de")
    vacation_periods_validated_es = format_locale_ranges(metadata["collective_vacation_periods"], "es")
    vacation_periods_validated_fr = format_locale_ranges(metadata["collective_vacation_periods"], "fr")
    vacation_periods_validated_it = format_locale_ranges(metadata["collective_vacation_periods"], "it")
    vacation_periods_validated_pl = format_locale_ranges(metadata["collective_vacation_periods"], "pl")
    vacation_periods_validated_sk = format_locale_ranges(metadata["collective_vacation_periods"], "sk")
    vacation_periods_validated_zh = format_locale_ranges(metadata["collective_vacation_periods"], "zh")
    vacation_periods_validated_hi = format_locale_ranges(metadata["collective_vacation_periods"], "hi")
    vacation_weeks_removed = format_locale_date_list(metadata["vacation_weeks_removed"], "pt")
    vacation_weeks_removed_en = format_locale_date_list(metadata["vacation_weeks_removed"], "en")
    vacation_weeks_removed_de = format_locale_date_list(metadata["vacation_weeks_removed"], "de")
    vacation_weeks_removed_es = format_locale_date_list(metadata["vacation_weeks_removed"], "es")
    vacation_weeks_removed_fr = format_locale_date_list(metadata["vacation_weeks_removed"], "fr")
    vacation_weeks_removed_it = format_locale_date_list(metadata["vacation_weeks_removed"], "it")
    vacation_weeks_removed_pl = format_locale_date_list(metadata["vacation_weeks_removed"], "pl")
    vacation_weeks_removed_sk = format_locale_date_list(metadata["vacation_weeks_removed"], "sk")
    vacation_weeks_removed_zh = format_locale_date_list(metadata["vacation_weeks_removed"], "zh")
    vacation_weeks_removed_hi = format_locale_date_list(metadata["vacation_weeks_removed"], "hi")
    focus_text_pt = ", ".join(
        f"{row['Area']} | {row['Departamento']} ({float(row['criticidade_media_recente']):.1f}%)"
        for row in department_recent_df.head(3).to_dict(orient="records")
    )

    rules_table_html = f"""
        <table class="rule-table">
          <thead>
            <tr><th id="rules-h-item">Item</th><th id="rules-h-rule">Regra usada</th></tr>
          </thead>
          <tbody>
            <tr><td id="rules-base-label">Base</td><td><code>{escape(str(metadata['dw_path']))}</code></td></tr>
            <tr><td id="rules-off-label">Desligados</td><td id="rules-off-value">Pessoas desligadas não entram no cálculo</td></tr>
            <tr><td id="rules-normal-label">Semana normal</td><td id="rules-normal-value">Meta de {summary_map['Meta presencial por semana']}</td></tr>
            <tr><td id="rules-holiday-label">Semana com feriado</td><td id="rules-holiday-value">Crítica apenas se houver 0 ou 1 dia presencial, equivalente à meta de {summary_map['Meta em semana com feriado']}</td></tr>
            <tr><td id="rules-vac-label">Férias coletivas</td><td id="rules-vac-value">{summary_map['Semanas de ferias coletivas removidas']} semanas removidas do cálculo</td></tr>
            <tr><td id="rules-scope-label">Pessoas consideradas</td><td id="rules-scope-value">Pessoas ativas, cargos M/E, áreas B-, sem B-V e B-SNP</td></tr>
            <tr><td id="rules-limit-label">Entra na lista</td><td id="rules-limit-value">Menos de {metadata['adherence_threshold_pct']:.0f}% da meta</td></tr>
          </tbody>
        </table>
    """.strip()

    translations = {
        "pt": {
            "lang_label": "Idioma",
            "hero_title": "Home office: presença na fábrica",
            "hero_subtitle": "Resposta direta ao pedido: pessoas abaixo de 90% da meta e abertura por média de dias presenciais.",
            "meta_ref": f"Data de referência: {reference_date_pt}",
            "meta_last": f"Última semana usada: {last_week_pt}",
            "meta_period": f"Período: {analysis_period_pt}",
            "meta_holiday": "Semana com feriado: crítica apenas com 0 ou 1 dia presencial",
            "meta_vac": "Férias coletivas fora da conta",
            "kpi1_label": "Pessoas consideradas",
            "kpi1_note": "Pessoas que entraram no cálculo.",
            "kpi2_label": "Abaixo de 90%",
            "kpi2_note": f"{summary_map['Percentual nao aderente']} das pessoas consideradas ficou abaixo de 90%.",
            "kpi3_label": "Média semanal abaixo de 90%",
            "kpi3_note": f"A mediana foi de {median_bad_pt} por semana.",
            "kpi4_label": "Faixa crítica principal",
            "kpi4_note": "Maior concentração do desvio, ainda perto da meta.",
            "brief_title": "Resposta ao pedido",
            "brief_note": "Percentuais dentro do grupo abaixo de 90%.",
            "brief_h_faixa": "Faixa",
            "brief_h_people": "Pessoas",
            "brief_h_pct": "% das pessoas abaixo de 90%",
            "trend_title": "Tendência semanal da presença média",
            "trend_note": "Mostra a presença média semanal frente à meta esperada. Os pontos vermelhos indicam semanas com feriado.",
            "trend_callout": f"Pior semana do período em <strong>{weekly_low_pt}</strong> com <strong>{float(weekly_low['media_presenca']):.2f}</strong> dia(s) de presença média para meta de <strong>{float(weekly_low['media_meta']):.2f}</strong> dia(s). Na última semana o indicador ficou em <strong>{float(weekly_last['media_presenca']):.2f}</strong> dia(s) para meta de <strong>{float(weekly_last['media_meta']):.2f}</strong> dia(s), com média recente de <strong>{weekly_recent:.2f}</strong> dia(s) nas últimas 4 semanas.",
            "heat_title": "Heatmap de departamentos/subáreas",
            "heat_note": "Cada célula mostra o % abaixo da regra e, abaixo, os dias médios presenciais. 100% significa todos abaixo da regra, não ausência total; cinza indica semana sem registro no DW.",
            "heat_callout": f"Destaques recentes: {escape(focus_text_pt)}.",
            "focus_volume_title": "Onde agir primeiro",
            "focus_volume_note": "Top áreas por quantidade de pessoas abaixo de 90%.",
            "focus_rate_title": "Onde o problema pesa mais",
            "focus_rate_note": "Top áreas por % abaixo de 90%. Só áreas com 10 pessoas ou mais.",
            "focus_h_area": "Área",
            "focus_h_dept": "Departamento",
            "focus_h_people": "Pessoas",
            "focus_h_pct": "% da área",
            "focus_h_avg": "Média dias",
            "dist_title": "Distribuição por dias presenciais",
            "dist_note": "A maior parte dos casos está perto da meta.",
            "dist_callout": f"A faixa de 2,0 a 2,5 dias concentra <strong>{faixa_principal_pct:.1f}%</strong> dos casos.",
            "prepared_title": "Preparado por",
            "prepared_note": "Material estruturado para alinhamento interno antes da apresentação conjunta da estatística.",
            "sig_name": "Nome",
            "sig_role": "Função",
            "sig_company": "Empresa",
            "sig_generated": "Gerado em",
            "sig_generated_value": generated_at_pt,
            "rules_title": "Regras usadas",
            "rules_note": f"Férias coletivas conferidas no histórico: {vacation_periods_validated}. Neste período, saíram da conta as semanas {vacation_weeks_removed}.",
            "rules_h_item": "Item",
            "rules_h_rule": "Regra usada",
            "rules_base_label": "Base",
            "rules_off_label": "Desligados",
            "rules_off_value": "Pessoas desligadas não entram no cálculo",
            "rules_normal_label": "Semana normal",
            "rules_normal_value": f"Meta de {regular_week_pt}",
            "rules_holiday_label": "Semana com feriado",
            "rules_holiday_value": f"Crítica apenas se houver 0 ou 1 dia presencial, equivalente à meta de {holiday_week_pt}",
            "rules_vac_label": "Férias coletivas",
            "rules_vac_value": f"{summary_map['Semanas de ferias coletivas removidas']} semanas removidas do cálculo",
            "rules_scope_label": "Pessoas consideradas",
            "rules_scope_value": "Pessoas ativas, cargos M/E, áreas B-, sem B-V e B-SNP",
            "rules_limit_label": "Entra na lista",
            "rules_limit_value": f"Menos de {metadata['adherence_threshold_pct']:.0f}% da meta",
        },
        "en": {
            "lang_label": "Language",
            "hero_title": "Weak on-site attendance at the plant",
            "hero_subtitle": "Analysis prepared for the Seitz presentation on people below 90% on-site adherence. This version focuses on plant-management reading: trend, indicator behavior and department heatmap.",
            "meta_ref": f"Reference date: {reference_date_en}",
            "meta_last": f"Last week used: {last_week_en}",
            "meta_period": f"Period: {analysis_period_en}",
            "meta_holiday": "Holiday week: critical only with 0 or 1 on-site day",
            "meta_vac": "Collective vacation validated and removed",
            "kpi1_label": "Analyzed population",
            "kpi1_note": "Eligible base after the calculation filters.",
            "kpi2_label": "Non-adherent",
            "kpi2_note": f"{summary_map['Percentual nao aderente']} of the population stayed below 90%.",
            "kpi3_label": "Weekly average of the non-adherent group",
            "kpi3_note": f"The median was {median_bad_en} per week.",
            "kpi4_label": "Main critical band",
            "kpi4_note": "Largest concentration of deviation, still close to the target.",
            "brief_title": "Requested reading",
            "brief_note": "",
            "brief_h_faixa": "Band",
            "brief_h_people": "People",
            "brief_h_pct": "% of the non-adherent group",
            "trend_title": "Weekly average attendance trend",
            "trend_note": "Shows the weekly average attendance against the expected target. Red points mark holiday weeks.",
            "trend_callout": f"Worst week in the period: <strong>{weekly_low_en}</strong> with <strong>{float(weekly_low['media_presenca']):.2f}</strong> attendance day(s) on average for a target of <strong>{float(weekly_low['media_meta']):.2f}</strong> day(s). In the last week, the indicator reached <strong>{float(weekly_last['media_presenca']):.2f}</strong> day(s) for a target of <strong>{float(weekly_last['media_meta']):.2f}</strong> day(s), with a recent 4-week average of <strong>{weekly_recent:.2f}</strong> day(s).",
            "heat_title": "Department/subarea heatmap",
            "heat_note": "Each cell shows the % below the rule and, below it, the average on-site days. 100% means everyone was below the rule, not total absence; gray marks weeks without DW records.",
            "heat_callout": f"Recent highlights: {escape(focus_text_pt)}.",
            "dist_title": "Severity distribution",
            "dist_note": "Most cases are close to the target, indicating room for quick managerial adjustment.",
            "dist_callout": f"The 2.0 to 2.5 days band concentrates <strong>{faixa_principal_pct:.1f}%</strong> of the cases.",
            "prepared_title": "Prepared by",
            "prepared_note": "Material structured for internal alignment before the joint presentation of the statistics.",
            "sig_name": "Name",
            "sig_role": "Role",
            "sig_company": "Company",
            "sig_generated": "Generated on",
            "sig_generated_value": generated_at_en,
            "rules_title": "Rules applied in the calculation",
            "rules_note": f"Collective vacation periods were validated against the project's historical base: {vacation_periods_validated_en}. In the current scope, the removed weeks were {vacation_weeks_removed_en}.",
            "rules_h_item": "Item",
            "rules_h_rule": "Applied rule",
            "rules_base_label": "Source",
            "rules_off_label": "Terminated employees",
            "rules_off_value": "Already removed from the analyzed population",
            "rules_normal_label": "Regular week",
            "rules_normal_value": f"Target of {regular_week_en}",
            "rules_holiday_label": "Holiday week",
            "rules_holiday_value": f"Critical only with 0 or 1 on-site day, equivalent to a target of {holiday_week_en}",
            "rules_vac_label": "Collective vacation",
            "rules_vac_value": f"{summary_map['Semanas de ferias coletivas removidas']} weeks removed from the calculation",
            "rules_scope_label": "People scope",
            "rules_scope_value": "Active employees, M/E roles, B- areas, excluding B-V and B-SNP",
            "rules_limit_label": "Alert threshold",
            "rules_limit_value": f"Below {metadata['adherence_threshold_pct']:.0f}% adherence",
        },
        "es": {
            "lang_label": "Idioma",
            "hero_title": "Presencial débil en la planta",
            "hero_subtitle": "Análisis preparado para la presentación a Seitz sobre personas por debajo del 90% de adherencia presencial. Esta versión prioriza una lectura gerencial: tendencia del indicador, comportamiento y heatmap de departamentos.",
            "meta_ref": f"Fecha de referencia: {reference_date_es}",
            "meta_last": f"Última semana usada: {last_week_es}",
            "meta_period": f"Período: {analysis_period_es}",
            "meta_holiday": "Semana con festivo: crítica solo con 0 o 1 día presencial",
            "meta_vac": "Vacaciones colectivas validadas y retiradas del cálculo",
            "kpi1_label": "Universo analizado",
            "kpi1_note": "Base elegible después de los filtros del cálculo.",
            "kpi2_label": "No adherentes",
            "kpi2_note": f"{summary_map['Percentual nao aderente']} del universo quedó por debajo del 90%.",
            "kpi3_label": "Promedio semanal de los no adherentes",
            "kpi3_note": f"La mediana fue de {median_bad_es} por semana.",
            "kpi4_label": "Franja crítica principal",
            "kpi4_note": "Mayor concentración del desvío, todavía cerca de la meta.",
            "brief_title": "Lectura solicitada",
            "brief_note": "",
            "brief_h_faixa": "Franja",
            "brief_h_people": "Personas",
            "brief_h_pct": "% de los no adherentes",
            "trend_title": "Tendencia semanal de la presencia media",
            "trend_note": "Muestra la presencia media semanal frente a la meta esperada. Los puntos rojos indican semanas con festivo.",
            "trend_callout": f"Peor semana del período: <strong>{weekly_low_es}</strong> con <strong>{float(weekly_low['media_presenca']):.2f}</strong> día(s) de presencia media para una meta de <strong>{float(weekly_low['media_meta']):.2f}</strong> día(s). En la última semana, el indicador quedó en <strong>{float(weekly_last['media_presenca']):.2f}</strong> día(s) para una meta de <strong>{float(weekly_last['media_meta']):.2f}</strong> día(s), con media reciente de <strong>{weekly_recent:.2f}</strong> día(s) en las últimas 4 semanas.",
            "heat_title": "Heatmap de departamentos/subáreas",
            "heat_note": "Cada celda muestra el % por debajo de la regla y, debajo, los días medios presenciales. 100% significa todos por debajo de la regla, no ausencia total; gris indica semanas sin registro en el DW.",
            "heat_callout": f"Destacados recientes: {escape(focus_text_pt)}.",
            "dist_title": "Distribución de la severidad",
            "dist_note": "La mayor parte de los casos está cerca de la meta, lo que indica oportunidad de ajuste gerencial rápido.",
            "dist_callout": f"La franja de 2,0 a 2,5 días concentra <strong>{faixa_principal_pct:.1f}%</strong> de los casos.",
            "prepared_title": "Preparado por",
            "prepared_note": "Material estructurado para alineación interna antes de la presentación conjunta de la estadística.",
            "sig_name": "Nombre",
            "sig_role": "Función",
            "sig_company": "Empresa",
            "sig_generated": "Generado el",
            "sig_generated_value": generated_at_es,
            "rules_title": "Reglas aplicadas en el cálculo",
            "rules_note": f"Las vacaciones colectivas fueron validadas con la base histórica del proyecto: {vacation_periods_validated_es}. En el recorte actual, las semanas removidas fueron {vacation_weeks_removed_es}.",
            "rules_h_item": "Ítem",
            "rules_h_rule": "Regla usada",
            "rules_base_label": "Base",
            "rules_off_label": "Desvinculados",
            "rules_off_value": "Ya removidos del universo analizado",
            "rules_normal_label": "Semana normal",
            "rules_normal_value": f"Meta de {regular_week_es}",
            "rules_holiday_label": "Semana con festivo",
            "rules_holiday_value": f"Crítica solo si hubo 0 o 1 día presencial, equivalente a una meta de {holiday_week_es}",
            "rules_vac_label": "Vacaciones colectivas",
            "rules_vac_value": f"{summary_map['Semanas de ferias coletivas removidas']} semanas removidas del cálculo",
            "rules_scope_label": "Recorte de personas",
            "rules_scope_value": "Colaboradores activos, cargos M/E, áreas B-, excluyendo B-V y B-SNP",
            "rules_limit_label": "Límite de alerta",
            "rules_limit_value": f"Por debajo de {metadata['adherence_threshold_pct']:.0f}% de adherencia",
        },
        "fr": {
            "lang_label": "Langue",
            "hero_title": "Présence faible à l'usine",
            "hero_subtitle": "Analyse préparée pour la présentation à Seitz sur les personnes en dessous de 90% d'adhérence au présentiel. Cette version privilégie une lecture managériale: tendance de l'indicateur, comportement et heatmap des départements.",
            "meta_ref": f"Date de référence: {reference_date_fr}",
            "meta_last": f"Dernière semaine utilisée: {last_week_fr}",
            "meta_period": f"Période: {analysis_period_fr}",
            "meta_holiday": "Semaine avec jour férié: critique seulement avec 0 ou 1 jour sur site",
            "meta_vac": "Vacances collectives validées et retirées du calcul",
            "kpi1_label": "Population analysée",
            "kpi1_note": "Base éligible après les filtres du calcul.",
            "kpi2_label": "Non adhérents",
            "kpi2_note": f"{summary_map['Percentual nao aderente']} de la population est restée sous 90%.",
            "kpi3_label": "Moyenne hebdomadaire des non-adhérents",
            "kpi3_note": f"La médiane a été de {median_bad_fr} par semaine.",
            "kpi4_label": "Bande critique principale",
            "kpi4_note": "Plus forte concentration d'écart, encore proche de la cible.",
            "brief_title": "Lecture demandée",
            "brief_note": "",
            "brief_h_faixa": "Bande",
            "brief_h_people": "Personnes",
            "brief_h_pct": "% des non-adhérents",
            "trend_title": "Tendance hebdomadaire de la présence moyenne",
            "trend_note": "Montre la présence moyenne hebdomadaire par rapport à la cible attendue. Les points rouges signalent les semaines avec jour férié.",
            "trend_callout": f"Pire semaine de la période: <strong>{weekly_low_fr}</strong> avec <strong>{float(weekly_low['media_presenca']):.2f}</strong> jour(s) de présence moyenne pour une cible de <strong>{float(weekly_low['media_meta']):.2f}</strong> jour(s). Lors de la dernière semaine, l'indicateur a atteint <strong>{float(weekly_last['media_presenca']):.2f}</strong> jour(s) pour une cible de <strong>{float(weekly_last['media_meta']):.2f}</strong> jour(s), avec une moyenne récente de <strong>{weekly_recent:.2f}</strong> jour(s) sur les 4 dernières semaines.",
            "heat_title": "Heatmap des départements/sous-zones",
            "heat_note": "Affiche la part du département sous la règle hebdomadaire. 100% signifie que tous sont sous la règle, pas une absence totale; le gris marque les semaines sans enregistrement DW.",
            "heat_callout": f"Points récents: {escape(focus_text_pt)}.",
            "dist_title": "Répartition de la sévérité",
            "dist_note": "La majorité des cas reste proche de la cible, ce qui indique une possibilité d'ajustement managérial rapide.",
            "dist_callout": f"La bande de 2,0 à 2,5 jours concentre <strong>{faixa_principal_pct:.1f}%</strong> des cas.",
            "prepared_title": "Préparé par",
            "prepared_note": "Matériel structuré pour un alignement interne avant la présentation conjointe de la statistique.",
            "sig_name": "Nom",
            "sig_role": "Fonction",
            "sig_company": "Entreprise",
            "sig_generated": "Généré le",
            "sig_generated_value": generated_at_fr,
            "rules_title": "Règles appliquées au calcul",
            "rules_note": f"Les vacances collectives ont été validées à partir de l'historique du projet: {vacation_periods_validated_fr}. Dans le périmètre actuel, les semaines retirées ont été {vacation_weeks_removed_fr}.",
            "rules_h_item": "Élément",
            "rules_h_rule": "Règle appliquée",
            "rules_base_label": "Source",
            "rules_off_label": "Sortants",
            "rules_off_value": "Déjà retirés de la population analysée",
            "rules_normal_label": "Semaine normale",
            "rules_normal_value": f"Cible de {regular_week_fr}",
            "rules_holiday_label": "Semaine avec jour férié",
            "rules_holiday_value": f"Critique seulement avec 0 ou 1 jour sur site, équivalent à une cible de {holiday_week_fr}",
            "rules_vac_label": "Vacances collectives",
            "rules_vac_value": f"{summary_map['Semanas de ferias coletivas removidas']} semaines retirées du calcul",
            "rules_scope_label": "Périmètre des personnes",
            "rules_scope_value": "Collaborateurs actifs, rôles M/E, zones B-, hors B-V et B-SNP",
            "rules_limit_label": "Seuil d'alerte",
            "rules_limit_value": f"En dessous de {metadata['adherence_threshold_pct']:.0f}% d'adhérence",
        },
        "it": {
            "lang_label": "Lingua",
            "hero_title": "Presenza debole in stabilimento",
            "hero_subtitle": "Analisi preparata per la presentazione a Seitz sulle persone sotto il 90% di aderenza alla presenza. Questa versione privilegia una lettura manageriale: trend dell'indicatore, comportamento e heatmap dei dipartimenti.",
            "meta_ref": f"Data di riferimento: {reference_date_it}",
            "meta_last": f"Ultima settimana usata: {last_week_it}",
            "meta_period": f"Periodo: {analysis_period_it}",
            "meta_holiday": "Settimana con festività: critica solo con 0 o 1 giorno in presenza",
            "meta_vac": "Ferie collettive validate e rimosse dal calcolo",
            "kpi1_label": "Universo analizzato",
            "kpi1_note": "Base eleggibile dopo i filtri di calcolo.",
            "kpi2_label": "Non aderenti",
            "kpi2_note": f"{summary_map['Percentual nao aderente']} dell'universo è rimasto sotto il 90%.",
            "kpi3_label": "Media settimanale dei non aderenti",
            "kpi3_note": f"La mediana è stata di {median_bad_it} per settimana.",
            "kpi4_label": "Fascia critica principale",
            "kpi4_note": "Maggiore concentrazione dello scostamento, ancora vicina al target.",
            "brief_title": "Lettura richiesta",
            "brief_note": "",
            "brief_h_faixa": "Fascia",
            "brief_h_people": "Persone",
            "brief_h_pct": "% dei non aderenti",
            "trend_title": "Trend settimanale della presenza media",
            "trend_note": "Mostra la presenza media settimanale rispetto al target atteso. I punti rossi indicano settimane con festività.",
            "trend_callout": f"Settimana peggiore del periodo: <strong>{weekly_low_it}</strong> con <strong>{float(weekly_low['media_presenca']):.2f}</strong> giorno(i) di presenza media per un target di <strong>{float(weekly_low['media_meta']):.2f}</strong> giorno(i). Nell'ultima settimana, l'indicatore è rimasto a <strong>{float(weekly_last['media_presenca']):.2f}</strong> giorno(i) per un target di <strong>{float(weekly_last['media_meta']):.2f}</strong> giorno(i), con media recente di <strong>{weekly_recent:.2f}</strong> giorno(i) nelle ultime 4 settimane.",
            "heat_title": "Heatmap di dipartimenti/subaree",
            "heat_note": "Mostra la quota del dipartimento sotto la regola settimanale. 100% significa tutti sotto la regola, non assenza totale; il grigio indica settimane senza record DW.",
            "heat_callout": f"Elementi recenti: {escape(focus_text_pt)}.",
            "dist_title": "Distribuzione della severità",
            "dist_note": "La maggior parte dei casi è vicina al target, indicando spazio per un rapido aggiustamento manageriale.",
            "dist_callout": f"La fascia da 2,0 a 2,5 giorni concentra <strong>{faixa_principal_pct:.1f}%</strong> dei casi.",
            "prepared_title": "Preparato da",
            "prepared_note": "Materiale strutturato per l'allineamento interno prima della presentazione congiunta della statistica.",
            "sig_name": "Nome",
            "sig_role": "Ruolo",
            "sig_company": "Azienda",
            "sig_generated": "Generato il",
            "sig_generated_value": generated_at_it,
            "rules_title": "Regole applicate al calcolo",
            "rules_note": f"Le ferie collettive sono state validate sulla base storica del progetto: {vacation_periods_validated_it}. Nel perimetro attuale, le settimane rimosse sono state {vacation_weeks_removed_it}.",
            "rules_h_item": "Voce",
            "rules_h_rule": "Regola usata",
            "rules_base_label": "Base",
            "rules_off_label": "Dimessi",
            "rules_off_value": "Già rimossi dall'universo analizzato",
            "rules_normal_label": "Settimana normale",
            "rules_normal_value": f"Target di {regular_week_it}",
            "rules_holiday_label": "Settimana con festività",
            "rules_holiday_value": f"Critica solo se ci sono 0 o 1 giorno in presenza, equivalente a un target di {holiday_week_it}",
            "rules_vac_label": "Ferie collettive",
            "rules_vac_value": f"{summary_map['Semanas de ferias coletivas removidas']} settimane rimosse dal calcolo",
            "rules_scope_label": "Perimetro delle persone",
            "rules_scope_value": "Collaboratori attivi, ruoli M/E, aree B-, escluse B-V e B-SNP",
            "rules_limit_label": "Soglia di allerta",
            "rules_limit_value": f"Sotto il {metadata['adherence_threshold_pct']:.0f}% di aderenza",
        },
        "de": {
            "lang_label": "Sprache",
            "hero_title": "Schwache Anwesenheit im Werk",
            "hero_subtitle": "Analyse für die Seitz-Präsentation zu Personen unter 90% Anwesenheitsquote. Diese Version fokussiert sich auf die Sicht des Werkmanagements: Trend, Indikatorverlauf und Heatmap der Abteilungen.",
            "meta_ref": f"Stichtag: {reference_date_de}",
            "meta_last": f"Letzte berücksichtigte Woche: {last_week_de}",
            "meta_period": f"Zeitraum: {analysis_period_de}",
            "meta_holiday": "Feiertagswoche: kritisch nur bei 0 oder 1 Anwesenheitstag",
            "meta_vac": "Betriebsferien validiert und entfernt",
            "kpi1_label": "Analysierte Belegschaft",
            "kpi1_note": "Geeignete Basis nach den Berechnungsfiltern.",
            "kpi2_label": "Nicht adherent",
            "kpi2_note": f"{summary_map['Percentual nao aderente']} der Belegschaft lagen unter 90%.",
            "kpi3_label": "Wochendurchschnitt der nicht adherenten Gruppe",
            "kpi3_note": f"Der Median lag bei {median_bad_de} pro Woche.",
            "kpi4_label": "Wichtigste kritische Bandbreite",
            "kpi4_note": "Größte Abweichungskonzentration, noch nahe am Zielwert.",
            "brief_title": "Angeforderte Auswertung",
            "brief_note": "",
            "brief_h_faixa": "Band",
            "brief_h_people": "Personen",
            "brief_h_pct": "% der nicht adherenten Gruppe",
            "trend_title": "Wochentrend des Anwesenheitsdurchschnitts",
            "trend_note": "Zeigt den wochentlichen Anwesenheitsdurchschnitt gegen das Soll. Rote Punkte markieren Feiertagswochen.",
            "trend_callout": f"Schlechteste Woche im Zeitraum: <strong>{weekly_low_de}</strong> mit <strong>{float(weekly_low['media_presenca']):.2f}</strong> durchschnittlichen Anwesenheitstagen bei einem Soll von <strong>{float(weekly_low['media_meta']):.2f}</strong> Tagen. In der letzten Woche lag der Wert bei <strong>{float(weekly_last['media_presenca']):.2f}</strong> Tagen bei einem Soll von <strong>{float(weekly_last['media_meta']):.2f}</strong> Tagen, der 4-Wochen-Durchschnitt liegt bei <strong>{weekly_recent:.2f}</strong> Tagen.",
            "heat_title": "Heatmap der Abteilungen/Subbereiche",
            "heat_note": "Zeigt den Anteil der Abteilung unter der Wochenregel. 100% bedeutet alle unter der Regel, nicht vollständige Abwesenheit; Grau markiert Wochen ohne DW-Datensatz.",
            "heat_callout": f"Aktuelle Schwerpunkte: {escape(focus_text_pt)}.",
            "dist_title": "Verteilung der Schweregrade",
            "dist_note": "Die meisten Fälle liegen nahe am Zielwert, was auf eine schnelle managerielle Korrektur hinweist.",
            "dist_callout": f"Die Bandbreite von 2,0 bis 2,5 Tagen umfasst <strong>{faixa_principal_pct:.1f}%</strong> der Falle.",
            "prepared_title": "Erstellt von",
            "prepared_note": "Material zur internen Abstimmung vor der gemeinsamen Vorstellung der Statistik.",
            "sig_name": "Name",
            "sig_role": "Funktion",
            "sig_company": "Unternehmen",
            "sig_generated": "Erstellt am",
            "sig_generated_value": generated_at_de,
            "rules_title": "Angewandte Berechnungsregeln",
            "rules_note": f"Die Betriebsferien wurden anhand der Projekthistorie validiert: {vacation_periods_validated_de}. Im aktuellen Zeitraum wurden die Wochen {vacation_weeks_removed_de} entfernt.",
            "rules_h_item": "Punkt",
            "rules_h_rule": "Angewandte Regel",
            "rules_base_label": "Quelle",
            "rules_off_label": "Ausgeschiedene",
            "rules_off_value": "Bereits aus der analysierten Belegschaft entfernt",
            "rules_normal_label": "Normale Woche",
            "rules_normal_value": f"Soll von {regular_week_de}",
            "rules_holiday_label": "Feiertagswoche",
            "rules_holiday_value": f"Nur bei 0 oder 1 Anwesenheitstag kritisch, entsprechend einem Soll von {holiday_week_de}",
            "rules_vac_label": "Betriebsferien",
            "rules_vac_value": f"{summary_map['Semanas de ferias coletivas removidas']} Wochen aus der Berechnung entfernt",
            "rules_scope_label": "Personenumfang",
            "rules_scope_value": "Aktive Mitarbeitende, M/E-Funktionen, B-Bereiche, ohne B-V und B-SNP",
            "rules_limit_label": "Warnschwelle",
            "rules_limit_value": f"Unter {metadata['adherence_threshold_pct']:.0f}% Anwesenheitsquote",
        },
    }

    def translation_clone(base_key: str, **overrides: str) -> dict[str, str]:
        derived = translations[base_key].copy()
        derived.update(overrides)
        return derived

    translations["pl"] = translation_clone(
        "en",
        lang_label="Język",
        hero_title="Niska obecność w zakładzie",
        hero_subtitle="Analiza przygotowana do prezentacji dla Seitza dotyczącej osób poniżej 90% zgodności z pracą stacjonarną. Ta wersja koncentruje się na perspektywie zarządzania zakładem: trendzie wskaźnika i mapie cieplnej działów/podobszarów.",
        meta_ref=f"Data odniesienia: {reference_date_pl}",
        meta_last=f"Ostatni użyty tydzień: {last_week_pl}",
        meta_period=f"Okres: {analysis_period_pl}",
        meta_holiday="Tydzień ze świętem: krytyczny tylko przy 0 lub 1 dniu pracy na miejscu",
        meta_vac="Urlop zbiorowy zweryfikowany i wyłączony z obliczeń",
        kpi1_label="Analizowana populacja",
        kpi1_note="Kwalifikująca się baza po filtrach obliczeń.",
        kpi2_label="Niezgodni",
        kpi2_note=f"{summary_map['Percentual nao aderente']} populacji spadło poniżej 90%.",
        kpi3_label="Tygodniowa średnia grupy niezgodnej",
        kpi3_note="Mediana tygodniowa została zachowana zgodnie z obliczeniami raportu.",
        kpi4_label="Główna strefa krytyczna",
        kpi4_note="Największe skupienie odchylenia, nadal blisko celu.",
        brief_title="Wymagany odczyt",
        brief_note="",
        brief_h_faixa="Przedział",
        brief_h_people="Osoby",
        brief_h_pct="% grupy niezgodnej",
        trend_title="Tygodniowy trend średniej obecności",
        trend_note="Pokazuje tygodniową średnią obecność względem oczekiwanego celu. Czerwone punkty oznaczają tygodnie ze świętem.",
        trend_callout=f"Najgorszy tydzień w okresie: <strong>{weekly_low_pl}</strong> ze średnią <strong>{float(weekly_low['media_presenca']):.2f}</strong> dnia obecności przy celu <strong>{float(weekly_low['media_meta']):.2f}</strong> dnia. W ostatnim tygodniu wskaźnik osiągnął <strong>{float(weekly_last['media_presenca']):.2f}</strong> dnia przy celu <strong>{float(weekly_last['media_meta']):.2f}</strong> dnia, a średnia z ostatnich 4 tygodni wyniosła <strong>{weekly_recent:.2f}</strong> dnia.",
        heat_title="Mapa cieplna działów/podobszarów",
        heat_note="Pokazuje udział działu poniżej reguły tygodniowej. 100% oznacza wszystkich poniżej reguły, a nie całkowitą nieobecność; szary oznacza tygodnie bez rekordów DW.",
        heat_callout=f"Ostatnie wyróżnienia: {escape(focus_text_pt)}.",
        dist_title="Rozkład nasilenia",
        dist_note="Większość przypadków jest nadal blisko celu, co wskazuje na możliwość szybkiej korekty menedżerskiej.",
        dist_callout=f"Przedział od 2.0 do 2.5 dnia obejmuje <strong>{faixa_principal_pct:.1f}%</strong> przypadków.",
        prepared_title="Przygotował",
        prepared_note="Materiał uporządkowany do wewnętrznego uzgodnienia przed wspólną prezentacją statystyki.",
        sig_name="Imię i nazwisko",
        sig_role="Rola",
        sig_company="Firma",
        sig_generated="Wygenerowano",
        sig_generated_value=generated_at_pl,
        rules_title="Zasady zastosowane w obliczeniu",
        rules_note=f"Okresy urlopu zbiorowego zweryfikowano na podstawie historii projektu: {vacation_periods_validated_pl}. W bieżącym zakresie usunięto tygodnie {vacation_weeks_removed_pl}.",
        rules_h_item="Pozycja",
        rules_h_rule="Zastosowana zasada",
        rules_base_label="Źródło",
        rules_off_label="Zwolnieni pracownicy",
        rules_off_value="Już usunięci z analizowanej populacji",
        rules_normal_label="Zwykły tydzień",
        rules_normal_value="Cel: 3.0 dni",
        rules_holiday_label="Tydzień świąteczny",
        rules_holiday_value="Krytyczny tylko przy 0 lub 1 dniu na miejscu, co odpowiada celowi 2.0 dni",
        rules_vac_label="Urlop zbiorowy",
        rules_vac_value=f"{summary_map['Semanas de ferias coletivas removidas']} tygodnie wyłączone z obliczeń",
        rules_scope_label="Zakres osób",
        rules_scope_value="Aktywni pracownicy, role M/E, obszary B-, z wyłączeniem B-V i B-SNP",
        rules_limit_label="Próg alertu",
        rules_limit_value=f"Poniżej {metadata['adherence_threshold_pct']:.0f}% zgodności",
    )

    translations["sk"] = translation_clone(
        "en",
        lang_label="Jazyk",
        hero_title="Slabšia prítomnosť v závode",
        hero_subtitle="Analýza pripravená na prezentáciu pre Seitz o osobách pod 90% dochádzkovej adherencie. Táto verzia sa zameriava na pohľad riadenia závodu: trend ukazovateľa a tepelnú mapu oddelení/podoblastí.",
        meta_ref=f"Referenčný dátum: {reference_date_sk}",
        meta_last=f"Posledný použitý týždeň: {last_week_sk}",
        meta_period=f"Obdobie: {analysis_period_sk}",
        meta_holiday="Sviatočný týždeň: kritický iba pri 0 alebo 1 dni na pracovisku",
        meta_vac="Celozávodná dovolenka overená a vyradená z výpočtu",
        kpi1_label="Analyzovaná populácia",
        kpi1_note="Oprávnená báza po filtroch výpočtu.",
        kpi2_label="Nevyhovujúci",
        kpi2_note=f"{summary_map['Percentual nao aderente']} populácie zostalo pod 90%.",
        kpi3_label="Týždenný priemer nevyhovujúcej skupiny",
        kpi3_note="Týždený medián bol zachovaný podľa výpočtu reportu.",
        kpi4_label="Hlavné kritické pásmo",
        kpi4_note="Najväčšia koncentrácia odchýlky, stále blízko cieľa.",
        brief_title="Požadovaný pohľad",
        brief_note="",
        brief_h_faixa="Pásmo",
        brief_h_people="Ľudia",
        brief_h_pct="% nevyhovujúcej skupiny",
        trend_title="Týždenný trend priemernej prítomnosti",
        trend_note="Ukazuje týždennú priemernú prítomnosť oproti očakávanému cieľu. Červené body označujú sviatočné týždne.",
        trend_callout=f"Najslabší týždeň obdobia: <strong>{weekly_low_sk}</strong> s priemerom <strong>{float(weekly_low['media_presenca']):.2f}</strong> dňa prítomnosti pri cieli <strong>{float(weekly_low['media_meta']):.2f}</strong> dňa. V poslednom týždni ukazovateľ dosiahol <strong>{float(weekly_last['media_presenca']):.2f}</strong> dňa pri cieli <strong>{float(weekly_last['media_meta']):.2f}</strong> dňa a 4-týždňový priemer bol <strong>{weekly_recent:.2f}</strong> dňa.",
        heat_title="Tepelná mapa oddelení/podoblastí",
        heat_note="Zobrazuje podiel oddelenia pod týždenným pravidlom. 100% znamená všetkých pod pravidlom, nie úplnú neprítomnosť; sivá označuje týždne bez záznamov v DW.",
        heat_callout=f"Nedávne priority: {escape(focus_text_pt)}.",
        dist_title="Rozdelenie závažnosti",
        dist_note="Väčšina prípadov je stále blízko cieľa, čo naznačuje priestor na rýchlu manažérsku korekciu.",
        dist_callout=f"Pásmo od 2.0 do 2.5 dňa zahŕňa <strong>{faixa_principal_pct:.1f}%</strong> prípadov.",
        prepared_title="Pripravil",
        prepared_note="Materiál štruktúrovaný pre interné zosúladenie pred spoločnou prezentáciou štatistiky.",
        sig_name="Meno",
        sig_role="Funkcia",
        sig_company="Spoločnosť",
        sig_generated="Vygenerované",
        sig_generated_value=generated_at_sk,
        rules_title="Pravidlá použité vo výpočte",
        rules_note=f"Obdobia celozávodnej dovolenky boli overené podľa historickej bázy projektu: {vacation_periods_validated_sk}. V aktuálnom rozsahu boli odstránené týždne {vacation_weeks_removed_sk}.",
        rules_h_item="Položka",
        rules_h_rule="Použité pravidlo",
        rules_base_label="Zdroj",
        rules_off_label="Ukončení zamestnanci",
        rules_off_value="Už vyradení z analyzovanej populácie",
        rules_normal_label="Bežný týždeň",
        rules_normal_value="Cieľ: 3.0 dňa",
        rules_holiday_label="Sviatočný týždeň",
        rules_holiday_value="Kritický iba pri 0 alebo 1 dni na pracovisku, čo zodpovedá cieľu 2.0 dňa",
        rules_vac_label="Celozávodná dovolenka",
        rules_vac_value=f"{summary_map['Semanas de ferias coletivas removidas']} týždne vyradené z výpočtu",
        rules_scope_label="Rozsah osôb",
        rules_scope_value="Aktívni zamestnanci, roly M/E, oblasti B-, s výnimkou B-V a B-SNP",
        rules_limit_label="Prahová hodnota",
        rules_limit_value=f"Pod {metadata['adherence_threshold_pct']:.0f}% adherencie",
    )

    translations["zh"] = translation_clone(
        "en",
        lang_label="语言",
        hero_title="工厂到岗偏弱",
        hero_subtitle="本分析为向 Seitz 汇报而准备，聚焦现场出勤遵守率低于 90% 的人员。本版本侧重工厂管理视角：指标趋势以及部门/子区域热力图。",
        meta_ref=f"参考日期：{reference_date_zh}",
        meta_last=f"使用的最后一周：{last_week_zh}",
        meta_period=f"期间：{analysis_period_zh}",
        meta_holiday="节假日周：只有现场 0 天或 1 天时才视为关键",
        meta_vac="集体休假已核实并从计算中剔除",
        kpi1_label="分析范围",
        kpi1_note="应用计算筛选后的有效基础人群。",
        kpi2_label="未达标人员",
        kpi2_note=f"有 {summary_map['Percentual nao aderente']} 低于 90%。",
        kpi3_label="未达标人群周均到岗",
        kpi3_note="周度中位数已按报告计算保留。",
        kpi4_label="主要关键区间",
        kpi4_note="偏差最集中的区间，但仍接近目标。",
        brief_title="需求读取",
        brief_note="",
        brief_h_faixa="区间",
        brief_h_people="人数",
        brief_h_pct="未达标人群占比",
        trend_title="周均到岗趋势",
        trend_note="展示每周平均到岗与目标的对比。红点表示节假日周。",
        trend_callout=f"期间最差一周为 <strong>{weekly_low_zh}</strong>，平均到岗 <strong>{float(weekly_low['media_presenca']):.2f}</strong> 天，目标为 <strong>{float(weekly_low['media_meta']):.2f}</strong> 天。最近一周指标为 <strong>{float(weekly_last['media_presenca']):.2f}</strong> 天，目标为 <strong>{float(weekly_last['media_meta']):.2f}</strong> 天，最近 4 周平均为 <strong>{weekly_recent:.2f}</strong> 天。",
        heat_title="部门/子区域热力图",
        heat_note="显示该部门低于周规则的比例。100% 表示所有人低于规则，不代表全部缺勤；灰色表示 DW 中没有该周记录。",
        heat_callout=f"近期重点：{escape(focus_text_pt)}。",
        dist_title="严重度分布",
        dist_note="大多数案例仍然接近目标，说明管理层可以较快推动纠偏。",
        dist_callout=f"2.0 到 2.5 天区间占 <strong>{faixa_principal_pct:.1f}%</strong>。",
        prepared_title="编制人",
        prepared_note="该材料已整理完成，用于正式联合汇报前的内部对齐。",
        sig_name="姓名",
        sig_role="职务",
        sig_company="公司",
        sig_generated="生成时间",
        sig_generated_value=generated_at_zh,
        rules_title="计算采用规则",
        rules_note=f"集体休假区间已根据项目历史基线完成核实：{vacation_periods_validated_zh}。在当前范围内，被移除的周为 {vacation_weeks_removed_zh}。",
        rules_h_item="项目",
        rules_h_rule="采用规则",
        rules_base_label="数据源",
        rules_off_label="离职人员",
        rules_off_value="已从分析范围中移除",
        rules_normal_label="常规周",
        rules_normal_value="目标：3.0 天",
        rules_holiday_label="节假日周",
        rules_holiday_value="只有现场 0 天或 1 天时视为关键，对应目标 2.0 天",
        rules_vac_label="集体休假",
        rules_vac_value=f"已从计算中移除 {summary_map['Semanas de ferias coletivas removidas']} 周",
        rules_scope_label="人员范围",
        rules_scope_value="在职员工，M/E 岗位，B- 区域，排除 B-V 和 B-SNP",
        rules_limit_label="预警阈值",
        rules_limit_value=f"低于 {metadata['adherence_threshold_pct']:.0f}%",
    )

    translations["hi"] = translation_clone(
        "en",
        lang_label="भाषा",
        hero_title="प्लांट में कम ऑन-साइट उपस्थिति",
        hero_subtitle="यह विश्लेषण Seitz को प्रस्तुति देने के लिए तैयार किया गया है और 90% से कम ऑन-साइट अनुपालन वाले लोगों पर केंद्रित है। यह संस्करण प्लांट प्रबंधन के दृष्टिकोण पर आधारित है: ट्रेंड, संकेतक का व्यवहार और विभाग/उप-क्षेत्र हीटमैप।",
        meta_ref=f"संदर्भ तिथि: {reference_date_hi}",
        meta_last=f"उपयोग किया गया अंतिम सप्ताह: {last_week_hi}",
        meta_period=f"अवधि: {analysis_period_hi}",
        meta_holiday="छुट्टी वाला सप्ताह: केवल 0 या 1 ऑन-साइट दिन होने पर ही गंभीर",
        meta_vac="सामूहिक अवकाश सत्यापित कर गणना से हटाया गया",
        kpi1_label="विश्लेषित जनसंख्या",
        kpi1_note="गणना फ़िल्टर के बाद पात्र आधार।",
        kpi2_label="अधूरा अनुपालन",
        kpi2_note=f"{summary_map['Percentual nao aderente']} जनसंख्या 90% से नीचे रही।",
        kpi3_label="अधूरे अनुपालन समूह का साप्ताहिक औसत",
        kpi3_note="साप्ताहिक माध्यिका रिपोर्ट गणना के अनुसार रखी गई है।",
        kpi4_label="मुख्य गंभीर श्रेणी",
        kpi4_note="विचलन की सबसे बड़ी एकाग्रता, फिर भी लक्ष्य के करीब।",
        brief_title="मांगी गई रीडिंग",
        brief_note="",
        brief_h_faixa="श्रेणी",
        brief_h_people="लोग",
        brief_h_pct="अधूरे अनुपालन समूह का %",
        trend_title="साप्ताहिक औसत उपस्थिति प्रवृत्ति",
        trend_note="यह अपेक्षित लक्ष्य के मुकाबले साप्ताहिक औसत उपस्थिति दिखाता है। लाल बिंदु छुट्टी वाले सप्ताह दर्शाते हैं।",
        trend_callout=f"अवधि का सबसे कमजोर सप्ताह <strong>{weekly_low_hi}</strong> रहा, जिसमें औसत उपस्थिति <strong>{float(weekly_low['media_presenca']):.2f}</strong> दिन थी और लक्ष्य <strong>{float(weekly_low['media_meta']):.2f}</strong> दिन था। अंतिम सप्ताह में संकेतक <strong>{float(weekly_last['media_presenca']):.2f}</strong> दिन रहा, लक्ष्य <strong>{float(weekly_last['media_meta']):.2f}</strong> दिन था, और पिछले 4 सप्ताह का औसत <strong>{weekly_recent:.2f}</strong> दिन रहा।",
        heat_title="विभाग/उप-क्षेत्र हीटमैप",
        heat_note="यह विभाग में साप्ताहिक नियम से नीचे रहे लोगों का हिस्सा दिखाता है। 100% का अर्थ है सभी नियम से नीचे थे, पूरी अनुपस्थिति नहीं; धूसर रंग DW में रिकॉर्ड न होने वाले सप्ताह दिखाता है।",
        heat_callout=f"हाल के मुख्य बिंदु: {escape(focus_text_pt)}.",
        dist_title="गंभीरता का वितरण",
        dist_note="अधिकांश मामले अभी भी लक्ष्य के करीब हैं, जिससे तेज़ प्रबंधकीय समायोजन की संभावना दिखती है।",
        dist_callout=f"2.0 से 2.5 दिन वाली श्रेणी में <strong>{faixa_principal_pct:.1f}%</strong> मामले हैं।",
        prepared_title="तैयार किया गया द्वारा",
        prepared_note="यह सामग्री संयुक्त प्रस्तुति से पहले आंतरिक संरेखण के लिए व्यवस्थित की गई है।",
        sig_name="नाम",
        sig_role="भूमिका",
        sig_company="कंपनी",
        sig_generated="जनरेट किया गया",
        sig_generated_value=generated_at_hi,
        rules_title="गणना में लागू नियम",
        rules_note=f"सामूहिक अवकाश अवधियों को परियोजना के ऐतिहासिक आधार के अनुसार सत्यापित किया गया: {vacation_periods_validated_hi}। वर्तमान दायरे में हटाए गए सप्ताह {vacation_weeks_removed_hi} थे।",
        rules_h_item="आइटम",
        rules_h_rule="लागू नियम",
        rules_base_label="स्रोत",
        rules_off_label="सेवा समाप्त कर्मचारी",
        rules_off_value="विश्लेषित जनसंख्या से पहले ही हटाए जा चुके हैं",
        rules_normal_label="सामान्य सप्ताह",
        rules_normal_value="लक्ष्य: 3.0 दिन",
        rules_holiday_label="छुट्टी वाला सप्ताह",
        rules_holiday_value="केवल 0 या 1 ऑन-साइट दिन होने पर गंभीर, जो 2.0 दिन के लक्ष्य के बराबर है",
        rules_vac_label="सामूहिक अवकाश",
        rules_vac_value=f"{summary_map['Semanas de ferias coletivas removidas']} सप्ताह गणना से हटाए गए",
        rules_scope_label="लोगों का दायरा",
        rules_scope_value="सक्रिय कर्मचारी, M/E भूमिकाएँ, B- क्षेत्र, B-V और B-SNP को छोड़कर",
        rules_limit_label="अलर्ट सीमा",
        rules_limit_value=f"{metadata['adherence_threshold_pct']:.0f}% से नीचे",
    )

    for values in translations.values():
        values.setdefault("focus_volume_title", "Where to act first")
        values.setdefault("focus_volume_note", "Top areas by number of people below 90%.")
        values.setdefault("focus_rate_title", "Where the issue weighs more")
        values.setdefault("focus_rate_note", "Top areas by % below 90% within the area. Minimum base: 10 people.")
        values.setdefault("focus_h_area", "Area")
        values.setdefault("focus_h_dept", "Department")
        values.setdefault("focus_h_people", "People")
        values.setdefault("focus_h_pct", "% of area")
        values.setdefault("focus_h_avg", "Avg days")

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Apresentação Seitz - Presencial Fraco</title>
{favicon_html.rstrip()}
  <style>
    :root {{
      --bg: #ecf3f9;
      --ink: #102743;
      --muted: #5d7188;
      --card: rgba(255, 255, 255, 0.94);
      --line: #d4e0ec;
      --accent: #0b2f59;
      --accent-2: #7eabc9;
      --accent-soft: #dcebfa;
      --shadow: 0 24px 54px rgba(11, 34, 61, 0.09);
      --radius: 28px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Aptos, "Segoe UI Variable", "Segoe UI", sans-serif;
      font-size: 22px;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(133, 176, 212, 0.18), transparent 26%),
        radial-gradient(circle at 86% 12%, rgba(198, 223, 243, 0.28), transparent 18%),
        linear-gradient(180deg, #f8fbfd 0%, var(--bg) 100%);
    }}
    .page {{
      width: min(1780px, calc(100vw - 24px));
      margin: 18px auto 42px;
      display: grid;
      gap: 24px;
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: 44px 46px 34px;
      background:
        radial-gradient(circle at 18% 18%, rgba(255, 255, 255, 0.10), transparent 20%),
        radial-gradient(circle at 86% 20%, rgba(154, 193, 224, 0.22), transparent 22%),
        linear-gradient(135deg, #08284c 0%, #0d3b66 62%, #1b5787 100%);
      border-radius: calc(var(--radius) + 6px);
      color: white;
      box-shadow: var(--shadow);
    }}
    .hero::before {{
      content: "";
      position: absolute;
      inset: auto -120px -120px auto;
      width: 360px;
      height: 360px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255,255,255,0.15), rgba(255,255,255,0.02) 62%, transparent 70%);
      pointer-events: none;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(115deg, transparent 0 56%, rgba(255,255,255,0.06) 56%, rgba(255,255,255,0.03) 63%, transparent 63%);
      pointer-events: none;
    }}
    .hero-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 34px;
      position: relative;
      z-index: 1;
    }}
    .hero-copy {{
      flex: 1 1 auto;
      min-width: 0;
    }}
    .hero-side {{
      display: grid;
      gap: 18px;
      justify-items: end;
      flex: 0 0 auto;
      position: relative;
      z-index: 2;
    }}
    .lang-wrap {{
      display: grid;
      gap: 0;
      text-align: right;
      justify-items: end;
      position: relative;
      z-index: 6;
    }}
    .flag-switcher {{
      position: relative;
      width: 132px;
      min-width: 132px;
      height: 56px;
      min-height: 56px;
      overflow: visible;
      isolation: isolate;
    }}
    .flag-switcher::before {{
      content: "";
      position: absolute;
      top: -10px;
      right: -10px;
      width: calc(100% + 20px);
      height: calc(var(--menu-height, 56px) + 20px);
      border-radius: 24px;
      background: rgba(23, 55, 96, 0.46);
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: 0 18px 40px rgba(9, 23, 43, 0.24);
      backdrop-filter: blur(14px);
      opacity: 0;
      transform: translateY(-4px);
      transition: opacity 160ms ease, transform 160ms ease;
      pointer-events: none;
      z-index: -1;
    }}
    .flag-switcher.open {{
      z-index: 30;
    }}
    .flag-switcher.open::before {{
      opacity: 1;
      transform: translateY(0);
    }}
    .lang-flag {{
      position: absolute;
      top: 0;
      right: 0;
      display: flex;
      width: 132px;
      min-width: 112px;
      height: 56px;
      padding: 7px 16px 7px 7px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.10);
      color: white;
      align-items: center;
      justify-content: flex-start;
      gap: 12px;
      font-size: 18px;
      font-weight: 800;
      letter-spacing: 0.05em;
      cursor: pointer;
      opacity: 0;
      pointer-events: none;
      transform: translateY(var(--menu-y, 0px));
      transition: transform 160ms ease, background 160ms ease, border-color 160ms ease, box-shadow 160ms ease, opacity 120ms ease;
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.10);
      backdrop-filter: blur(8px);
    }}
    .lang-flag.active {{
      opacity: 1;
      pointer-events: auto;
    }}
    .flag-switcher.open .lang-flag {{
      opacity: 1;
      pointer-events: auto;
    }}
    .lang-flag.active::after {{
      content: "▾";
      margin-left: auto;
      font-size: 15px;
      line-height: 1;
      color: rgba(255,255,255,0.92);
      letter-spacing: 0;
    }}
    .flag-switcher.open .lang-flag.active::after {{
      content: "▴";
    }}
    .lang-flag:hover {{
      transform: translateY(calc(var(--menu-y, 0px) - 1px));
      background: rgba(255,255,255,0.16);
    }}
    .lang-flag.active {{
      background: rgba(255,255,255,0.24);
      border-color: rgba(255,255,255,0.48);
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.16);
    }}
    .lang-flag[data-lang="pt"] {{ background: rgba(179, 229, 196, 0.24); }}
    .lang-flag[data-lang="de"] {{ background: rgba(223, 227, 234, 0.22); }}
    .lang-flag[data-lang="en"] {{ background: rgba(194, 220, 245, 0.24); }}
    .lang-flag[data-lang="es"] {{ background: rgba(248, 228, 170, 0.25); }}
    .lang-flag[data-lang="pl"] {{ background: rgba(247, 214, 221, 0.24); }}
    .lang-flag[data-lang="sk"] {{ background: rgba(210, 225, 247, 0.24); }}
    .lang-flag[data-lang="zh"] {{ background: rgba(248, 210, 198, 0.24); }}
    .lang-flag[data-lang="hi"] {{ background: rgba(232, 232, 232, 0.24); }}
    .lang-flag[data-lang="fr"] {{ background: rgba(201, 229, 249, 0.24); }}
    .lang-flag[data-lang="it"] {{ background: rgba(203, 238, 215, 0.24); }}
    .lang-flag:focus-visible {{
      outline: 3px solid rgba(255,255,255,0.48);
      outline-offset: 2px;
    }}
    .flag-disc {{
      width: 40px;
      height: 40px;
      border-radius: 999px;
      overflow: hidden;
      flex: 0 0 40px;
      box-shadow: 0 3px 10px rgba(0, 0, 0, 0.16);
      border: 2px solid rgba(255,255,255,0.78);
      background: white;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .flag-disc svg {{
      display: block;
      width: 100%;
      height: 100%;
    }}
    .flag-label {{
      display: inline-block;
      min-width: 34px;
      text-align: left;
    }}
    .hero-logo {{
      width: 220px;
      max-width: 30vw;
      height: auto;
      opacity: 0.98;
      display: block;
    }}
    .hero-copy h1 {{
      margin: 0 0 12px;
      font-size: clamp(48px, 6.2vw, 76px);
      line-height: 1.05;
      letter-spacing: -0.03em;
    }}
    .hero-copy p {{
      margin: 0;
      max-width: 980px;
      color: rgba(255, 255, 255, 0.88);
      font-size: 24px;
      line-height: 1.5;
    }}
    .hero-statement {{
      margin-top: 20px;
      max-width: 980px;
      padding: 18px 20px 18px 22px;
      border-radius: 22px;
      border: 1px solid rgba(255,255,255,0.16);
      border-left: 5px solid rgba(255,255,255,0.88);
      background: rgba(255,255,255,0.10);
      backdrop-filter: blur(10px);
      color: rgba(255,255,255,0.98);
      font-size: 21px;
      line-height: 1.52;
      box-shadow: 0 18px 34px rgba(7, 20, 37, 0.12);
    }}
    .hero-statement strong {{
      color: #ffffff;
    }}
    .meta {{
      margin-top: 24px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      position: relative;
      z-index: 1;
    }}
    .meta span {{
      padding: 12px 16px;
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.10);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
      font-size: 18px;
      letter-spacing: 0.02em;
    }}
    .grid-4 {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 18px;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 22px;
    }}
    .card {{
      position: relative;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.97) 0%, rgba(248, 251, 254, 0.97) 100%);
      border: 1px solid rgba(255, 255, 255, 0.8);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 26px;
    }}
    .kpi-card {{
      padding: 26px 24px 22px;
    }}
    .kpi-card::before {{
      content: "";
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 5px;
      background: linear-gradient(90deg, var(--accent) 0%, #5c88b4 100%);
    }}
    .kpi-card::after {{
      content: "";
      position: absolute;
      top: -28px;
      right: -18px;
      width: 128px;
      height: 128px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(220, 235, 250, 0.70), transparent 70%);
      pointer-events: none;
    }}
    .feature-card {{
      padding: 28px;
    }}
    .site-footer {{
      padding: 24px 28px;
      border-radius: 24px;
      background: linear-gradient(180deg, #f3f6f8 0%, #eaf0f4 100%);
      border: 1px solid #d5e0e8;
      color: var(--ink);
      box-shadow: 0 12px 28px rgba(11, 34, 61, 0.06);
    }}
    .kpi-label {{
      color: var(--muted);
      font-size: 20px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 10px;
      font-weight: 800;
    }}
    .kpi-value {{
      font-size: clamp(44px, 5vw, 64px);
      font-weight: 800;
      letter-spacing: -0.03em;
      margin-bottom: 6px;
    }}
    .kpi-note {{
      color: var(--muted);
      font-size: 16px;
      line-height: 1.5;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 38px;
      letter-spacing: -0.03em;
    }}
    p.section-note {{
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 19px;
      line-height: 1.55;
    }}
    img.chart {{
      width: 100%;
      border-radius: 20px;
      border: 1px solid #dce7f1;
      background: white;
      display: block;
      box-shadow: 0 14px 28px rgba(12, 39, 67, 0.08);
    }}
    .chart-scroll {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    .table-scroll {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 20px;
    }}
    th, td {{
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 15px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .callout {{
      margin-top: 16px;
      padding: 18px 20px;
      border-radius: 22px;
      background: linear-gradient(180deg, #f7fbff 0%, #ffffff 100%);
      border: 1px solid rgba(198, 215, 231, 0.9);
      border-left: 6px solid var(--accent);
      color: #2d3a4b;
      font-size: 20px;
      line-height: 1.58;
      box-shadow: 0 12px 28px rgba(13, 40, 68, 0.05);
    }}
    .footer-panels {{
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.75fr);
      gap: 28px;
    }}
    .footer-panel {{
      min-width: 0;
    }}
    .site-footer h2 {{
      color: var(--ink);
      font-size: 24px;
      letter-spacing: 0;
      margin-bottom: 8px;
    }}
    .site-footer p.section-note {{
      color: var(--muted);
      font-size: 15.5px;
      line-height: 1.5;
      margin-bottom: 12px;
    }}
    .site-footer table {{
      color: #2d3a4b;
      font-size: 14.5px;
    }}
    .site-footer th,
    .site-footer td {{
      border-bottom: 1px solid #d5e0e8;
      padding: 9px 10px 9px 0;
    }}
    .site-footer th {{
      color: var(--muted);
    }}
    .site-footer code {{
      color: var(--ink);
      background: #e1e8ee;
      border-radius: 6px;
      padding: 2px 5px;
      overflow-wrap: anywhere;
    }}
    .rule-table td:first-child,
    .rule-table th:first-child {{
      width: 28%;
    }}
    .signature-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}
    .signature-item {{
      padding: 10px 12px;
      border-radius: 10px;
      background: rgba(255,255,255,0.66);
      border: 1px solid #d5e0e8;
      color: #2d3a4b;
    }}
    .signature-item strong {{
      display: block;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    @media (max-width: 1020px) {{
      .grid-4, .grid-2, .signature-grid, .footer-panels {{
        grid-template-columns: 1fr;
      }}
      .page {{
        width: min(100vw - 14px, 1200px);
        margin: 10px auto 30px;
      }}
      .hero {{
        padding: 30px 24px 24px;
      }}
      .hero-top {{
        align-items: flex-start;
      }}
      .hero-side {{
        justify-items: start;
      }}
      .lang-wrap {{
        text-align: left;
        justify-items: start;
      }}
      .flag-switcher {{
        justify-self: start;
      }}
      .hero-logo {{
        width: 170px;
        max-width: 42vw;
      }}
    }}
    @media (max-width: 760px) {{
      body {{
        font-size: 18px;
      }}
      .page {{
        width: calc(100vw - 12px);
        margin: 6px auto 22px;
        gap: 14px;
      }}
      .hero {{
        padding: 18px 16px;
        border-radius: 24px;
      }}
      .hero-top {{
        flex-direction: column;
        align-items: stretch;
        gap: 16px;
      }}
      .hero-side {{
        width: 100%;
        gap: 12px;
        justify-items: stretch;
      }}
      .flag-switcher {{
        width: 124px;
        min-width: 124px;
        height: 48px;
        min-height: 48px;
        justify-self: end;
      }}
      .lang-flag {{
        width: 124px;
        max-width: 100%;
        height: 48px;
        padding: 5px 8px 5px 5px;
        gap: 8px;
        font-size: 14px;
        justify-content: flex-start;
      }}
      .flag-disc {{
        width: 32px;
        height: 32px;
        flex-basis: 32px;
      }}
      .flag-label {{
        min-width: 20px;
        text-align: center;
      }}
      .hero-logo {{
        width: 144px;
        max-width: 44vw;
        margin-left: auto;
      }}
      .hero-copy h1 {{
        font-size: clamp(32px, 10vw, 46px);
        line-height: 1.04;
      }}
      .hero-copy p {{
        font-size: 18px;
        line-height: 1.45;
      }}
      .hero-statement {{
        margin-top: 16px;
        padding: 14px 16px 14px 18px;
        font-size: 16px;
        line-height: 1.46;
        border-radius: 18px;
      }}
      .meta {{
        gap: 8px;
        margin-top: 16px;
      }}
      .meta span {{
        width: 100%;
        font-size: 14px;
        padding: 10px 12px;
        border-radius: 16px;
      }}
      .card {{
        padding: 18px 16px;
        border-radius: 20px;
      }}
      .feature-card {{
        padding: 20px 16px;
      }}
      .kpi-label {{
        font-size: 15px;
        margin-bottom: 8px;
      }}
      .kpi-value {{
        font-size: clamp(32px, 11vw, 42px);
      }}
      .kpi-note {{
        font-size: 13px;
        line-height: 1.4;
      }}
      h2 {{
        font-size: 28px;
        margin-bottom: 10px;
      }}
      p.section-note {{
        font-size: 16px;
        line-height: 1.45;
        margin-bottom: 12px;
      }}
      .chart-scroll {{
        margin: 0 -4px;
        padding: 0 4px 6px;
      }}
      .chart-scroll .chart {{
        width: 760px;
        min-width: 760px;
      }}
      .chart-scroll.heatmap .chart {{
        width: 920px;
        min-width: 920px;
      }}
      .table-scroll {{
        margin: 0 -4px;
        padding: 0 4px 2px;
      }}
      .table-scroll table {{
        min-width: 520px;
      }}
      table {{
        font-size: 15px;
      }}
      th, td {{
        padding: 10px 10px;
      }}
      .callout {{
        font-size: 15px;
        padding: 14px;
        line-height: 1.45;
      }}
      .site-footer {{
        padding: 18px 16px;
        border-radius: 20px;
      }}
      .site-footer table {{
        font-size: 13.5px;
      }}
      .site-footer th,
      .site-footer td {{
        padding: 8px 8px 8px 0;
      }}
      .signature-item strong {{
        font-size: 12px;
      }}
    }}
    @media (max-width: 460px) {{
      .hero-copy h1 {{
        font-size: clamp(29px, 10.4vw, 40px);
      }}
      .hero-copy p {{
        font-size: 16px;
      }}
      .chart-scroll .chart {{
        width: 700px;
        min-width: 700px;
      }}
      .chart-scroll.heatmap .chart {{
        width: 860px;
        min-width: 860px;
      }}
      .table-scroll table {{
        min-width: 480px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="hero-top">
        <div class="hero-copy">
          <h1 id="hero-title">{translations['pt']['hero_title']}</h1>
          <p id="hero-subtitle">{translations['pt']['hero_subtitle']}</p>
          <div class="hero-statement" id="hero-statement">{translations['pt']['kpi2_note']} {translations['pt']['dist_callout']}</div>
        </div>
        <div class="hero-side">
          <div class="lang-wrap">
            <div class="flag-switcher" id="lang-picker" role="group" aria-label="Selecionar idioma" aria-expanded="false">
              <button class="lang-flag active" type="button" data-lang="pt" aria-label="Brazil" aria-pressed="true" title="Brazil">
                <span class="flag-disc" aria-hidden="true">
                  <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <defs><clipPath id="flag-br"><circle cx="32" cy="32" r="32"/></clipPath></defs>
                    <g clip-path="url(#flag-br)">
                      <rect width="64" height="64" fill="#009b3a"/>
                      <polygon points="32,9 55,32 32,55 9,32" fill="#ffdf00"/>
                      <circle cx="32" cy="32" r="12" fill="#002776"/>
                      <path d="M19 31c8-5 18-5 26 0" fill="none" stroke="#ffffff" stroke-width="3.2" stroke-linecap="round"/>
                    </g>
                  </svg>
                </span>
                <span class="flag-label">BR</span>
              </button>
              <button class="lang-flag" type="button" data-lang="en" aria-label="United States" aria-pressed="false" title="United States">
                <span class="flag-disc" aria-hidden="true">
                  <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <defs><clipPath id="flag-us"><circle cx="32" cy="32" r="32"/></clipPath></defs>
                    <g clip-path="url(#flag-us)">
                      <rect width="64" height="64" fill="#ffffff"/>
                      <rect width="64" height="5" y="0" fill="#b22234"/>
                      <rect width="64" height="5" y="10" fill="#b22234"/>
                      <rect width="64" height="5" y="20" fill="#b22234"/>
                      <rect width="64" height="5" y="30" fill="#b22234"/>
                      <rect width="64" height="5" y="40" fill="#b22234"/>
                      <rect width="64" height="5" y="50" fill="#b22234"/>
                      <rect width="64" height="4" y="60" fill="#b22234"/>
                      <rect width="30" height="28" x="0" y="0" fill="#3c3b6e"/>
                      <g fill="#ffffff">
                        <circle cx="5" cy="5" r="1.2"/><circle cx="12" cy="5" r="1.2"/><circle cx="19" cy="5" r="1.2"/><circle cx="26" cy="5" r="1.2"/>
                        <circle cx="8.5" cy="10" r="1.2"/><circle cx="15.5" cy="10" r="1.2"/><circle cx="22.5" cy="10" r="1.2"/>
                        <circle cx="5" cy="15" r="1.2"/><circle cx="12" cy="15" r="1.2"/><circle cx="19" cy="15" r="1.2"/><circle cx="26" cy="15" r="1.2"/>
                        <circle cx="8.5" cy="20" r="1.2"/><circle cx="15.5" cy="20" r="1.2"/><circle cx="22.5" cy="20" r="1.2"/>
                        <circle cx="5" cy="25" r="1.2"/><circle cx="12" cy="25" r="1.2"/><circle cx="19" cy="25" r="1.2"/><circle cx="26" cy="25" r="1.2"/>
                      </g>
                    </g>
                  </svg>
                </span>
                <span class="flag-label">US</span>
              </button>
              <button class="lang-flag" type="button" data-lang="de" aria-label="Germany" aria-pressed="false" title="Germany">
                <span class="flag-disc" aria-hidden="true">
                  <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <defs><clipPath id="flag-de"><circle cx="32" cy="32" r="32"/></clipPath></defs>
                    <g clip-path="url(#flag-de)">
                      <rect width="64" height="21.34" y="0" fill="#000000"/>
                      <rect width="64" height="21.33" y="21.34" fill="#dd0000"/>
                      <rect width="64" height="21.33" y="42.67" fill="#ffce00"/>
                    </g>
                  </svg>
                </span>
                <span class="flag-label">DE</span>
              </button>
              <button class="lang-flag" type="button" data-lang="es" aria-label="Spain" aria-pressed="false" title="Spain">
                <span class="flag-disc" aria-hidden="true">
                  <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <defs><clipPath id="flag-es"><circle cx="32" cy="32" r="32"/></clipPath></defs>
                    <g clip-path="url(#flag-es)">
                      <rect width="64" height="64" fill="#f1bf00"/>
                      <rect width="64" height="16" y="0" fill="#aa151b"/>
                      <rect width="64" height="16" y="48" fill="#aa151b"/>
                    </g>
                  </svg>
                </span>
                <span class="flag-label">ES</span>
              </button>
              <button class="lang-flag" type="button" data-lang="pl" aria-label="Poland" aria-pressed="false" title="Poland">
                <span class="flag-disc" aria-hidden="true">
                  <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <defs><clipPath id="flag-pl"><circle cx="32" cy="32" r="32"/></clipPath></defs>
                    <g clip-path="url(#flag-pl)">
                      <rect width="64" height="64" fill="#ffffff"/>
                      <rect width="64" height="32" y="32" fill="#dc143c"/>
                    </g>
                  </svg>
                </span>
                <span class="flag-label">PL</span>
              </button>
              <button class="lang-flag" type="button" data-lang="sk" aria-label="Slovakia" aria-pressed="false" title="Slovakia">
                <span class="flag-disc" aria-hidden="true">
                  <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <defs><clipPath id="flag-sk"><circle cx="32" cy="32" r="32"/></clipPath></defs>
                    <g clip-path="url(#flag-sk)">
                      <rect width="64" height="64" fill="#ee1c25"/>
                      <rect width="64" height="42.67" y="0" fill="#0b4ea2"/>
                      <rect width="64" height="21.33" y="0" fill="#ffffff"/>
                    </g>
                  </svg>
                </span>
                <span class="flag-label">SK</span>
              </button>
              <button class="lang-flag" type="button" data-lang="zh" aria-label="China" aria-pressed="false" title="China">
                <span class="flag-disc" aria-hidden="true">
                  <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <defs><clipPath id="flag-zh"><circle cx="32" cy="32" r="32"/></clipPath></defs>
                    <g clip-path="url(#flag-zh)">
                      <rect width="64" height="64" fill="#de2910"/>
                      <polygon points="14,10 16.8,18 25.2,18 18.4,22.8 21,31 14,25.9 7,31 9.6,22.8 2.8,18 11.2,18" fill="#ffde00"/>
                      <circle cx="28" cy="12" r="2.3" fill="#ffde00"/>
                      <circle cx="32" cy="19" r="2.3" fill="#ffde00"/>
                      <circle cx="31" cy="28" r="2.3" fill="#ffde00"/>
                      <circle cx="24" cy="33" r="2.3" fill="#ffde00"/>
                    </g>
                  </svg>
                </span>
                <span class="flag-label">CN</span>
              </button>
              <button class="lang-flag" type="button" data-lang="hi" aria-label="India" aria-pressed="false" title="India">
                <span class="flag-disc" aria-hidden="true">
                  <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <defs><clipPath id="flag-hi"><circle cx="32" cy="32" r="32"/></clipPath></defs>
                    <g clip-path="url(#flag-hi)">
                      <rect width="64" height="64" fill="#138808"/>
                      <rect width="64" height="42.67" y="0" fill="#ffffff"/>
                      <rect width="64" height="21.33" y="0" fill="#ff9933"/>
                      <circle cx="32" cy="32" r="7.5" fill="none" stroke="#1a4ba0" stroke-width="2.4"/>
                    </g>
                  </svg>
                </span>
                <span class="flag-label">IN</span>
              </button>
            </div>
          </div>
          {f'<img class="hero-logo" src="{logo_rel}" alt="Logo Volkswagen">' if logo_rel else ''}
        </div>
      </div>
      <div class="meta">
        <span id="meta-ref">{translations['pt']['meta_ref']}</span>
        <span id="meta-last">{translations['pt']['meta_last']}</span>
        <span id="meta-period">{translations['pt']['meta_period']}</span>
        <span id="meta-holiday">{translations['pt']['meta_holiday']}</span>
        <span id="meta-vac">{translations['pt']['meta_vac']}</span>
      </div>
    </section>

    <section class="grid-4">
      <article class="card kpi-card">
        <div class="kpi-label" id="kpi1-label">{translations['pt']['kpi1_label']}</div>
        <div class="kpi-value">{summary_map['Universo considerado']}</div>
        <div class="kpi-note" id="kpi1-note">{translations['pt']['kpi1_note']}</div>
      </article>
      <article class="card kpi-card">
        <div class="kpi-label" id="kpi2-label">{translations['pt']['kpi2_label']}</div>
        <div class="kpi-value">{summary_map['Nao aderentes']}</div>
        <div class="kpi-note" id="kpi2-note">{translations['pt']['kpi2_note']}</div>
      </article>
      <article class="card kpi-card">
        <div class="kpi-label" id="kpi3-label">{translations['pt']['kpi3_label']}</div>
        <div class="kpi-value">{summary_map['Media semanal dos nao aderentes']}</div>
        <div class="kpi-note" id="kpi3-note">{translations['pt']['kpi3_note']}</div>
      </article>
      <article class="card kpi-card">
        <div class="kpi-label" id="kpi4-label">{translations['pt']['kpi4_label']}</div>
        <div class="kpi-value">{faixa_principal_pct:.1f}%</div>
        <div class="kpi-note" id="kpi4-note">{translations['pt']['kpi4_note']}</div>
      </article>
    </section>

    <section class="grid-2">
      <article class="card feature-card">
        <h2 id="brief-title">{translations['pt']['brief_title']}</h2>
        <p class="section-note" id="brief-note">{translations['pt']['brief_note']}</p>
        <div class="chart-scroll">
          <img class="chart" src="{chart_cumulative_rel}" alt="Gráfico de faixas acumuladas do briefing">
        </div>
        <div class="table-scroll">
          <table style="margin-top: 18px;">
            <thead>
              <tr><th id="brief-h-faixa">{translations['pt']['brief_h_faixa']}</th><th id="brief-h-people">{translations['pt']['brief_h_people']}</th><th id="brief-h-pct">{translations['pt']['brief_h_pct']}</th></tr>
            </thead>
            <tbody>
              {cumulative_html}
            </tbody>
          </table>
        </div>
      </article>
      <article class="card feature-card">
        <h2 id="trend-title">{translations['pt']['trend_title']}</h2>
        <p class="section-note" id="trend-note">{translations['pt']['trend_note']}</p>
        <div class="chart-scroll">
          <img class="chart" src="{chart_weekly_rel}" alt="Gráfico de tendência semanal da presença média">
        </div>
        <div class="callout" id="trend-callout">{translations['pt']['trend_callout']}</div>
      </article>
    </section>

    <section class="card feature-card">
      <h2 id="dist-title">{translations['pt']['dist_title']}</h2>
      <p class="section-note" id="dist-note">{translations['pt']['dist_note']}</p>
      <div class="chart-scroll">
        <img class="chart" src="{chart_distribution_rel}" alt="Gráfico de pessoas abaixo de 90% por média semanal">
      </div>
      <div class="callout" id="dist-callout">{translations['pt']['dist_callout']}</div>
    </section>

    <section class="grid-2">
      <article class="card feature-card">
        <h2 id="focus-volume-title">{translations['pt']['focus_volume_title']}</h2>
        <p class="section-note" id="focus-volume-note">{translations['pt']['focus_volume_note']}</p>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th id="focus-volume-h-area">{translations['pt']['focus_h_area']}</th>
                <th id="focus-volume-h-dept">{translations['pt']['focus_h_dept']}</th>
                <th id="focus-volume-h-people">{translations['pt']['focus_h_people']}</th>
                <th id="focus-volume-h-pct">{translations['pt']['focus_h_pct']}</th>
                <th id="focus-volume-h-avg">{translations['pt']['focus_h_avg']}</th>
              </tr>
            </thead>
            <tbody>
              {top_volume_html}
            </tbody>
          </table>
        </div>
      </article>
      <article class="card feature-card">
        <h2 id="focus-rate-title">{translations['pt']['focus_rate_title']}</h2>
        <p class="section-note" id="focus-rate-note">{translations['pt']['focus_rate_note']}</p>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th id="focus-rate-h-area">{translations['pt']['focus_h_area']}</th>
                <th id="focus-rate-h-dept">{translations['pt']['focus_h_dept']}</th>
                <th id="focus-rate-h-people">{translations['pt']['focus_h_people']}</th>
                <th id="focus-rate-h-pct">{translations['pt']['focus_h_pct']}</th>
                <th id="focus-rate-h-avg">{translations['pt']['focus_h_avg']}</th>
              </tr>
            </thead>
            <tbody>
              {top_rate_html}
            </tbody>
          </table>
        </div>
      </article>
    </section>

    <footer class="site-footer">
      <div class="footer-panels">
        <div class="footer-panel">
          <h2 id="rules-title">{translations['pt']['rules_title']}</h2>
          <p class="section-note" id="rules-note">{translations['pt']['rules_note']}</p>
          {rules_table_html}
        </div>
        <div class="footer-panel">
          <h2 id="prepared-title">{translations['pt']['prepared_title']}</h2>
          <p class="section-note" id="prepared-note">{translations['pt']['prepared_note']}</p>
          <div class="signature-grid">
            <div class="signature-item">
              <strong id="sig-name">{translations['pt']['sig_name']}</strong>
              <div>{PRESENTATION_AUTHOR_NAME}</div>
            </div>
            <div class="signature-item">
              <strong id="sig-role">{translations['pt']['sig_role']}</strong>
              <div>{PRESENTATION_AUTHOR_ROLE}</div>
            </div>
            <div class="signature-item">
              <strong id="sig-company">{translations['pt']['sig_company']}</strong>
              <div>{PRESENTATION_AUTHOR_TEAM}</div>
            </div>
            <div class="signature-item">
              <strong id="sig-generated">{translations['pt']['sig_generated']}</strong>
              <div id="sig-generated-value">{generated_at_pt}</div>
            </div>
          </div>
        </div>
      </div>
    </footer>
  </main>
  <script>
    const translations = {json.dumps(translations, ensure_ascii=False)};
    const preferredLangOrder = ['pt', 'en', 'de', 'es', 'pl', 'sk', 'zh', 'hi'];
    function setText(id, value, html=false) {{
      const el = document.getElementById(id);
      if (!el) return;
      if (html) el.innerHTML = value;
      else el.textContent = value;
    }}
    function applyLanguage(lang) {{
      const t = translations[lang] || translations.pt;
      const langMap = {{
        pt: 'pt-BR',
        de: 'de',
        en: 'en',
        es: 'es',
        pl: 'pl',
        sk: 'sk',
        zh: 'zh-CN',
        hi: 'hi-IN',
        fr: 'fr',
        it: 'it',
      }};
      const titleMap = {{
        pt: 'Apresentação Seitz - Presencial Fraco',
        de: 'Seitz-Präsentation - Schwache Anwesenheit',
        en: 'Seitz Presentation - Weak On-Site Attendance',
        es: 'Presentación Seitz - Presencial Débil',
        pl: 'Prezentacja Seitz - Słaba Obecność Stacjonarna',
        sk: 'Prezentácia Seitz - Slabšia Prítomnosť Na Mieste',
        zh: 'Seitz 汇报 - 现场出勤偏弱',
        hi: 'Seitz प्रस्तुति - कम ऑन-साइट उपस्थिति',
        fr: 'Présentation Seitz - Présence Faible',
        it: 'Presentazione Seitz - Presenza Debole',
      }};
      document.documentElement.lang = langMap[lang] || 'pt-BR';
      document.title = titleMap[lang] || titleMap.pt;
      langButtons.forEach((button) => {{
        const active = button.dataset.lang === lang;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
      }});
      syncLanguageMenu(lang);
      setText('lang-label', t.lang_label);
      setText('hero-title', t.hero_title);
      setText('hero-subtitle', t.hero_subtitle);
      setText('hero-statement', `${{t.kpi2_note}} ${{t.dist_callout}}`, true);
      setText('meta-ref', t.meta_ref);
      setText('meta-last', t.meta_last);
      setText('meta-period', t.meta_period);
      setText('meta-holiday', t.meta_holiday);
      setText('meta-vac', t.meta_vac);
      setText('kpi1-label', t.kpi1_label);
      setText('kpi1-note', t.kpi1_note);
      setText('kpi2-label', t.kpi2_label);
      setText('kpi2-note', t.kpi2_note);
      setText('kpi3-label', t.kpi3_label);
      setText('kpi3-note', t.kpi3_note);
      setText('kpi4-label', t.kpi4_label);
      setText('kpi4-note', t.kpi4_note);
      setText('brief-title', t.brief_title);
      setText('brief-note', t.brief_note);
      setText('brief-h-faixa', t.brief_h_faixa);
      setText('brief-h-people', t.brief_h_people);
      setText('brief-h-pct', t.brief_h_pct);
      setText('trend-title', t.trend_title);
      setText('trend-note', t.trend_note);
      setText('trend-callout', t.trend_callout, true);
      setText('heat-title', t.heat_title);
      setText('heat-note', t.heat_note);
      setText('heat-callout', t.heat_callout, true);
      setText('focus-volume-title', t.focus_volume_title);
      setText('focus-volume-note', t.focus_volume_note);
      setText('focus-rate-title', t.focus_rate_title);
      setText('focus-rate-note', t.focus_rate_note);
      ['volume', 'rate'].forEach((kind) => {{
        setText(`focus-${{kind}}-h-area`, t.focus_h_area);
        setText(`focus-${{kind}}-h-dept`, t.focus_h_dept);
        setText(`focus-${{kind}}-h-people`, t.focus_h_people);
        setText(`focus-${{kind}}-h-pct`, t.focus_h_pct);
        setText(`focus-${{kind}}-h-avg`, t.focus_h_avg);
      }});
      setText('dist-title', t.dist_title);
      setText('dist-note', t.dist_note);
      setText('dist-callout', t.dist_callout, true);
      setText('prepared-title', t.prepared_title);
      setText('prepared-note', t.prepared_note);
      setText('sig-name', t.sig_name);
      setText('sig-role', t.sig_role);
      setText('sig-company', t.sig_company);
      setText('sig-generated', t.sig_generated);
      setText('sig-generated-value', t.sig_generated_value);
      setText('rules-title', t.rules_title);
      setText('rules-note', t.rules_note);
      setText('rules-h-item', t.rules_h_item);
      setText('rules-h-rule', t.rules_h_rule);
      setText('rules-base-label', t.rules_base_label);
      setText('rules-off-label', t.rules_off_label);
      setText('rules-off-value', t.rules_off_value);
      setText('rules-normal-label', t.rules_normal_label);
      setText('rules-normal-value', t.rules_normal_value);
      setText('rules-holiday-label', t.rules_holiday_label);
      setText('rules-holiday-value', t.rules_holiday_value);
      setText('rules-vac-label', t.rules_vac_label);
      setText('rules-vac-value', t.rules_vac_value);
      setText('rules-scope-label', t.rules_scope_label);
      setText('rules-scope-value', t.rules_scope_value);
      setText('rules-limit-label', t.rules_limit_label);
      setText('rules-limit-value', t.rules_limit_value);
    }}
    const langPicker = document.getElementById('lang-picker');
    const langButtons = Array.from(document.querySelectorAll('.lang-flag'));
    function syncLanguageMenu(activeLang) {{
      if (!langPicker) return;
      const menuStep = window.matchMedia('(max-width: 760px)').matches ? 56 : 64;
      const menuBaseHeight = window.matchMedia('(max-width: 760px)').matches ? 48 : 56;
      const available = langButtons.map((button) => button.dataset.lang);
      const ordered = [activeLang, ...preferredLangOrder.filter((lang) => lang !== activeLang && available.includes(lang))];
      langButtons.forEach((button) => {{
        const slot = Math.max(0, ordered.indexOf(button.dataset.lang));
        button.style.setProperty('--menu-y', `${{slot * menuStep}}px`);
      }});
      const menuHeight = Math.max(menuBaseHeight, menuBaseHeight + (ordered.length - 1) * menuStep);
      langPicker.style.setProperty('--menu-height', `${{menuHeight}}px`);
    }}
    function closeLanguageMenu() {{
      if (!langPicker) return;
      langPicker.classList.remove('open');
      langPicker.setAttribute('aria-expanded', 'false');
    }}
    function toggleLanguageMenu() {{
      if (!langPicker) return;
      const shouldOpen = !langPicker.classList.contains('open');
      langPicker.classList.toggle('open', shouldOpen);
      langPicker.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    }}
    langButtons.forEach((button) => {{
      button.addEventListener('click', (event) => {{
        event.stopPropagation();
        if (button.classList.contains('active')) {{
          toggleLanguageMenu();
          return;
        }}
        applyLanguage(button.dataset.lang);
        closeLanguageMenu();
      }});
    }});
    document.addEventListener('click', (event) => {{
      if (langPicker && !langPicker.contains(event.target)) closeLanguageMenu();
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape') closeLanguageMenu();
    }});
    applyLanguage('pt');
    closeLanguageMenu();
  </script>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")


def write_text_summary(
    output_dir: Path,
    exec_summary: pd.DataFrame,
    cumulative_df: pd.DataFrame,
    distribution_df: pd.DataFrame,
    cargo_df: pd.DataFrame,
    area_df: pd.DataFrame,
    specs_df: pd.DataFrame,
    week_rules_df: pd.DataFrame,
    weekly_manager_df: pd.DataFrame,
    department_recent_df: pd.DataFrame,
) -> None:
    summary_map = dict(exec_summary.values.tolist())
    weekly_low = weekly_manager_df.loc[weekly_manager_df["media_presenca"].idxmin()]
    weekly_last = weekly_manager_df.iloc[-1]
    focus_departments = ", ".join(
        f"{row['Area']} | {row['Departamento']} ({float(row['criticidade_media_recente']):.1f}%)"
        for row in department_recent_df.head(5).to_dict(orient="records")
    )
    top_volume_df, top_rate_df = build_management_focus_tables(area_df, top_n=5)
    top_volume_text = ", ".join(
        f"{row['Area']} ({int(row['Nao Aderentes'])})"
        for row in top_volume_df.to_dict(orient="records")
    )
    top_rate_text = ", ".join(
        f"{row['Area']} ({float(row['Percentual Nao Aderentes']):.1f}%)"
        for row in top_rate_df.to_dict(orient="records")
    )
    faixa_curta = " | ".join(
        f"{row.Faixa}: {float(row.Percentual):.1f}%"
        for row in cumulative_df.itertuples(index=False)
    )
    lines = [
        "# Apresentação Seitz - Resumo Executivo",
        "",
        "## Resposta curta",
        f"- {summary_map['Resposta curta']}",
        f"- Faixas acumuladas: {faixa_curta}",
        "",
        "## Quem entrou no cálculo",
        f"- Referência: {summary_map['Data de referencia']} | Última semana: {summary_map['Ultima semana completa usada']}",
        f"- Período analisado: {summary_map['Periodo analisado']}",
        f"- Pessoas consideradas: {summary_map['Universo considerado']} | Desligados: {summary_map['Status dos desligados']}",
        f"- Média de quem ficou abaixo de 90%: {summary_map['Media semanal dos nao aderentes']} | Mediana: {summary_map['Mediana semanal dos nao aderentes']}",
        f"- Feriados: {summary_map['Semanas de feriado consideradas']} semanas | Férias removidas: {summary_map['Semanas de ferias coletivas removidas']} semanas",
        "",
        "## Especificações do pedido",
    ]
    for row in specs_df.to_dict(orient="records"):
        lines.append(f"- {row['Especificacao']}")
    lines.extend(
        [
            "",
            "## Regras especiais de semana",
            f"- Semana normal: meta de {summary_map['Meta presencial por semana']}.",
            f"- Semana com feriado: meta de {summary_map['Meta em semana com feriado']} e critério crítico apenas para 0 ou 1 dia presencial.",
            f"- Datas das semanas com feriado: {summary_map['Datas das semanas com feriado']}",
            f"- Datas das semanas removidas por férias: {summary_map['Datas das semanas removidas por ferias']}",
            "- Períodos validados de férias coletivas: "
            + ", ".join(
                f"{inicio.strftime('%Y-%m-%d')} a {fim.strftime('%Y-%m-%d')}"
                for inicio, fim in COLLECTIVE_VACATION_PERIODS
            ),
            "",
            "## Leituras para gestor de planta",
            f"- Menor presença média semanal: {float(weekly_low['media_presenca']):.2f} dia(s) na semana de {pd.Timestamp(weekly_low['Data']).strftime('%Y-%m-%d')}, contra meta média de {float(weekly_low['media_meta']):.2f} dia(s).",
            f"- Última semana monitorada: {float(weekly_last['media_presenca']):.2f} dia(s) de presença média para meta de {float(weekly_last['media_meta']):.2f} dia(s).",
            f"- Onde agir primeiro, por volume: {top_volume_text}.",
            f"- Onde o problema pesa mais, por percentual: {top_rate_text}.",
            "",
            "## Faixas dentro do grupo abaixo de 90%",
        ]
    )
    for row in cumulative_df.itertuples(index=False):
        lines.append(f"- {row.Faixa}: {int(row.Pessoas)} pessoas ({float(row.Percentual):.1f}%)")
    lines.extend(
        [
            "",
            "## Distribuição completa das faixas",
        ]
    )
    for row in distribution_df.itertuples(index=False):
        lines.append(f"- {row.Faixa}: {int(row.Pessoas)} pessoas ({float(row.Percentual):.1f}%)")
    lines.extend(
        [
            "",
            "## Resumo por cargo",
        ]
    )
    for row in cargo_df.to_dict(orient="records"):
        lines.append(
            f"- Cargo {row['Cargo']}: {int(row['Nao Aderentes'])} pessoas abaixo de 90% "
            f"de {int(row['Total Pessoas'])} pessoas ({float(row['Percentual Nao Aderentes']):.1f}%)"
        )
    lines.extend(
        [
            "",
            "## Aprofundamento - tendência recente",
            f"- Departamentos/subáreas que mais pedem atenção recente: {focus_departments}.",
        ]
    )
    for row in department_recent_df.head(10).to_dict(orient="records"):
        lines.append(
            f"- {row['Area']} | {row['Departamento']}: {int(row['casos_criticos_recentes'])} casos críticos recentes "
            f"({float(row['criticidade_media_recente']):.1f}% médio, pior semana {float(row['pior_semana_recente']):.1f}%)"
        )
    holiday_rows = week_rules_df[
        week_rules_df["semana_feriado"] & ~week_rules_df["semana_ferias_coletivas"]
    ].copy()
    vacation_rows = week_rules_df[week_rules_df["semana_ferias_coletivas"]].copy()
    lines.extend(
        [
            "",
            "## Semanas com feriado",
        ]
    )
    for row in holiday_rows.to_dict(orient="records"):
        lines.append(
            f"- {pd.Timestamp(row['semana_inicio']).strftime('%Y-%m-%d')}: {row['feriados_nomes']}"
        )
    lines.extend(
        [
            "",
            "## Semanas removidas por férias coletivas",
        ]
    )
    for row in vacation_rows.to_dict(orient="records"):
        lines.append(
            f"- {pd.Timestamp(row['semana_inicio']).strftime('%Y-%m-%d')} a {pd.Timestamp(row['semana_fim']).strftime('%Y-%m-%d')}: {row['ferias_periodo']}"
        )
    lines.extend(
        [
            "",
            "## Regras aplicadas",
            "- Considerados apenas colaboradores ativos.",
            "- Pessoas desligadas não entram no cálculo.",
            "- Considerados apenas cargos M e E.",
            "- Consideradas apenas áreas iniciando em B-.",
            "- Excluídas áreas B-V e B-SNP.",
            "- Em semanas com feriado, a meta considerada foi de 2 dias.",
            "- Em semanas normais, a meta considerada foi de 3 dias.",
            "- Semanas de férias coletivas foram removidas do cálculo.",
            "- Aderência calculada como media_dias_presenciais_semana / media_meta_semana.",
        ]
    )
    (output_dir / "resumo_execucao.md").write_text("\n".join(lines), encoding="utf-8")


def build_metadata(config: AnalysisConfig, last_week: pd.Timestamp, week_rules_df: pd.DataFrame) -> dict[str, object]:
    return {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dw_path": str(config.dw_path),
        "reference_date": config.reference_date.strftime("%Y-%m-%d"),
        "last_complete_week": last_week.strftime("%Y-%m-%d"),
        "rule_change_date": config.rule_change_date.strftime("%Y-%m-%d"),
        "required_days": config.required_days,
        "holiday_required_days": REQ_PRESENTIAL_DAYS_HOLIDAY_WEEK,
        "adherence_threshold_pct": config.adherence_threshold_pct,
        "factory_area_rule": "Area com prefixo B-, excluindo B-V e B-SNP.",
        "collective_vacation_periods": [
            {"inicio": inicio.strftime("%Y-%m-%d"), "fim": fim.strftime("%Y-%m-%d")}
            for inicio, fim in COLLECTIVE_VACATION_PERIODS
        ],
        "holiday_weeks_considered": week_rules_df.loc[
            week_rules_df["semana_feriado"] & ~week_rules_df["semana_ferias_coletivas"],
            "semana_inicio",
        ].dt.strftime("%Y-%m-%d").tolist(),
        "vacation_weeks_removed": week_rules_df.loc[
            week_rules_df["semana_ferias_coletivas"],
            "semana_inicio",
        ].dt.strftime("%Y-%m-%d").tolist(),
    }


def main() -> None:
    config = parse_args()
    if not config.dw_path.exists():
        raise FileNotFoundError(f"DW nao encontrado: {config.dw_path}")

    output_dir, charts_dir, assets_dir = ensure_output_dirs(config.output_dir)
    logo_path = copy_logo_asset(assets_dir)
    specs_df = pd.DataFrame({"Especificacao": list(REQUEST_SPECIFICATIONS)})

    with sqlite3.connect(config.dw_path) as conn:
        raw_df, last_week = fetch_weekly_data(conn, config)

    week_rules_df = build_week_rules(raw_df, config)
    filtered_df = apply_factory_filters(raw_df)
    filtered_df = apply_week_rules(filtered_df, week_rules_df)
    all_people, bad = build_people_summary(filtered_df, config)
    cumulative_df, distribution_df = build_bucket_tables(bad)
    cargo_df = build_cargo_summary(all_people, bad)
    area_df = build_area_summary(all_people, bad)
    focus_volume_df, focus_rate_df = build_management_focus_tables(area_df)
    weekly_manager_df = build_weekly_manager_summary(filtered_df)
    department_recent_df, department_heatmap_df = build_department_management_summary(filtered_df)
    exec_summary = build_exec_summary(
        all_people=all_people,
        bad=bad,
        cumulative_df=cumulative_df,
        distribution_df=distribution_df,
        week_rules=week_rules_df,
        last_week=last_week,
        config=config,
    )
    metadata = build_metadata(config, last_week, week_rules_df)

    excel_path = output_dir / "apresentacao_seitz_presencial_fraco.xlsx"
    chart_cumulative = charts_dir / "faixas_cumulativas.png"
    chart_weekly = charts_dir / "tendencia_semanal_criticidade.png"
    chart_department_heatmap = charts_dir / "heatmap_departamentos.png"
    chart_distribution = charts_dir / "distribuicao_faixas.png"
    html_path = output_dir / "apresentacao_seitz_presencial_fraco.html"
    json_path = output_dir / "resumo_execucao.json"
    csv_bad_path = output_dir / "pessoas_abaixo_90.csv"
    csv_universe_path = output_dir / "pessoas_consideradas.csv"

    save_excel(
        excel_path,
        exec_summary=exec_summary,
        cumulative_df=cumulative_df,
        distribution_df=distribution_df,
        cargo_df=cargo_df,
        area_df=area_df,
        weekly_manager_df=weekly_manager_df,
        department_recent_df=department_recent_df,
        department_heatmap_df=department_heatmap_df,
        specs_df=specs_df,
        week_rules_df=week_rules_df,
        all_people=all_people,
        bad=bad,
    )
    bad.to_csv(csv_bad_path, index=False, encoding="utf-8-sig")
    all_people.to_csv(csv_universe_path, index=False, encoding="utf-8-sig")
    plot_cumulative_thresholds(cumulative_df, chart_cumulative)
    plot_weekly_criticality(weekly_manager_df, chart_weekly)
    plot_department_heatmap(department_heatmap_df, chart_department_heatmap)
    plot_distribution(distribution_df, chart_distribution)
    build_html_report(
        html_path=html_path,
        metadata=metadata,
        exec_summary=exec_summary,
        cumulative_df=cumulative_df,
        distribution_df=distribution_df,
        area_df=area_df,
        weekly_manager_df=weekly_manager_df,
        department_recent_df=department_recent_df,
        chart_cumulative=chart_cumulative,
        chart_weekly=chart_weekly,
        chart_department_heatmap=chart_department_heatmap,
        chart_distribution=chart_distribution,
        logo_path=logo_path,
    )
    write_text_summary(
        output_dir=output_dir,
        exec_summary=exec_summary,
        cumulative_df=cumulative_df,
        distribution_df=distribution_df,
        cargo_df=cargo_df,
        area_df=area_df,
        specs_df=specs_df,
        week_rules_df=week_rules_df,
        weekly_manager_df=weekly_manager_df,
        department_recent_df=department_recent_df,
    )
    week_rules_json = week_rules_df.copy()
    for col in ("semana_inicio", "semana_fim"):
        if col in week_rules_json.columns:
            week_rules_json[col] = pd.to_datetime(week_rules_json[col], errors="coerce").dt.strftime("%Y-%m-%d")
    json_path.write_text(
        json.dumps(
            {
                **metadata,
                "specifications": specs_df.to_dict(orient="records"),
                "summary": exec_summary.to_dict(orient="records"),
                "cumulative_buckets": cumulative_df.to_dict(orient="records"),
                "distribution_buckets": distribution_df.to_dict(orient="records"),
                "focus_volume": focus_volume_df.to_dict(orient="records"),
                "focus_rate": focus_rate_df.to_dict(orient="records"),
                "weekly_manager_summary": weekly_manager_df.assign(
                    Data=weekly_manager_df["Data"].dt.strftime("%Y-%m-%d")
                ).to_dict(orient="records"),
                "department_recent_summary": department_recent_df.to_dict(orient="records"),
                "weekly_rules": week_rules_json.to_dict(orient="records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Arquivos gerados em: {output_dir}")
    print(f"- HTML: {html_path.name}")
    print(f"- Excel: {excel_path.name}")
    print(f"- CSV pessoas abaixo de 90%: {csv_bad_path.name}")
    print(f"- CSV pessoas consideradas: {csv_universe_path.name}")


if __name__ == "__main__":
    main()
