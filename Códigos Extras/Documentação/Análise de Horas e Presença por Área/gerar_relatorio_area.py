# -*- coding: utf-8 -*-
"""
Relatorio de horas dentro da fabrica e semanas com mais dias presenciais,
para uma arvore de area configuravel.

Fonte: project/database/df_ronda.parquet (base bruta de eventos de catraca/ponto).
Escopo: definido em tempo de execucao via RONDA_RELATORIO_AREAS (ver `AREAS_ALVO`
abaixo) — nenhum codigo de area/departamento fica hardcoded neste arquivo de
proposito, pois esse recorte e sensivel e nao deve ficar versionado.

Metodologia (ver aba "Leia-me" no xlsx de saida para o texto completo):
- "Presencial" = qualquer evento com planta != 999 no dia (planta 999 =
  marcacao de home office via app "Captura Ponto 373", NAO conta como
  presenca fisica na fabrica).
- "Horas dentro da fabrica" no dia = ultima marcacao fisica do dia menos
  primeira marcacao fisica do dia (mesmo criterio ja usado no projeto em
  "Analise das horas dos colaboradores.ipynb": min/max de todas as marcacoes
  do dia, sem distinguir catraca de refeitorio).
- Janela de dados: ajustar DATA_INICIO/DATA_FIM abaixo conforme a cobertura
  real da base no momento de gerar o relatorio — a base pode ter cauda de
  datas futuras que sao cargas de teste/placeholder (ver checagem de
  continuidade diaria antes de rodar).
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.worksheet.worksheet import Worksheet

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SRC_PARQUET = Path("C:/tmp/df_area_alvo.parquet")  # ja filtrado por area em etapa anterior
OUT_DIR = Path(__file__).parent / "saida"
OUT_XLSX = OUT_DIR / "Relatorio_Horas_e_Presenca_na_Fabrica.xlsx"

# Codigos de area a analisar. NUNCA hardcode aqui — defina localmente via
# variavel de ambiente (ex.: no seu .env, nao versionado) como lista separada
# por virgula: RONDA_RELATORIO_AREAS=XX-Y,XX-YA,XX-YB
AREAS_ALVO = [
    a.strip() for a in os.environ.get("RONDA_RELATORIO_AREAS", "").split(",") if a.strip()
]
if not AREAS_ALVO:
    raise SystemExit(
        "Defina RONDA_RELATORIO_AREAS (codigos de area separados por virgula) "
        "antes de rodar este script — ex.: no seu .env local, nunca no codigo."
    )

DATA_INICIO = pd.Timestamp("2024-01-02")
DATA_FIM = pd.Timestamp("2026-04-03")

VW_BLUE = "001E50"
VW_BLUE_LIGHT = "F7FBFF"
VW_GRAY = "E0E0E0"
VW_GREEN = "C6E8C6"

DIAS_PT = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta", 5: "Sábado", 6: "Domingo"}

pd.set_option("mode.copy_on_write", True)


def _hora_to_timedelta(series: pd.Series) -> pd.Series:
    txt = series.astype(str)
    return pd.to_timedelta(txt, errors="coerce")


def _formatar_hhmm(td: pd.Timedelta) -> str:
    if pd.isna(td):
        return ""
    total_min = int(round(td.total_seconds() / 60))
    h, m = divmod(total_min, 60)
    return f"{h:02d}:{m:02d}"


def carregar_base() -> pd.DataFrame:
    df = pd.read_parquet(SRC_PARQUET)
    df["data"] = pd.to_datetime(df["data"])
    df = df[df["area"].isin(AREAS_ALVO)].copy()
    df = df[(df["data"] >= DATA_INICIO) & (df["data"] <= DATA_FIM)].copy()

    for col in ["desligado", "planta", "dir", "uso_acesso", "cargo"]:
        df[col] = df[col].astype(str).str.strip()

    df["hora_td"] = _hora_to_timedelta(df["hora"])
    df["fisico"] = df["planta"] != "999"
    return df


def montar_dimensao(df: pd.DataFrame) -> pd.DataFrame:
    dim = (
        df.sort_values("data")
        .groupby("cadastro")
        .agg(
            nome=("nome", "last"),
            area=("area", "last"),
            departamento=("departamento", "last"),
            heranca=("heranca", "last"),
            cargo=("cargo", "last"),
            cargo_especifico=("cargo_especifico", "last"),
            desligado=("desligado", "last"),
        )
        .reset_index()
    )
    return dim


def montar_presenca_diaria(df: pd.DataFrame, dim: pd.DataFrame) -> pd.DataFrame:
    fis = df[df["fisico"]].copy()

    diario = (
        fis.groupby(["cadastro", "data"])
        .agg(
            primeira_marcacao=("hora_td", "min"),
            ultima_marcacao=("hora_td", "max"),
            plantas_do_dia=("planta", lambda s: "|".join(sorted(set(s)))),
            qtd_marcacoes=("hora_td", "size"),
        )
        .reset_index()
    )
    diario["horas_na_fabrica"] = (
        (diario["ultima_marcacao"] - diario["primeira_marcacao"]).dt.total_seconds() / 3600.0
    ).clip(lower=0)

    home_office_dia = (
        df.loc[~df["fisico"], ["cadastro", "data"]]
        .drop_duplicates()
        .assign(home_office_no_dia=True)
    )
    diario = diario.merge(home_office_dia, on=["cadastro", "data"], how="left")
    diario["home_office_no_dia"] = diario["home_office_no_dia"].fillna(False)

    iso = diario["data"].dt.isocalendar()
    diario["ano_iso"] = iso["year"].astype(int)
    diario["semana_iso"] = iso["week"].astype(int)
    diario["dia_semana"] = diario["data"].dt.weekday.map(DIAS_PT)

    diario = diario.merge(dim, on="cadastro", how="left")
    diario["primeira_marcacao_hhmm"] = diario["primeira_marcacao"].map(_formatar_hhmm)
    diario["ultima_marcacao_hhmm"] = diario["ultima_marcacao"].map(_formatar_hhmm)

    cols = [
        "cadastro", "nome", "area", "departamento", "cargo", "cargo_especifico", "desligado",
        "data", "dia_semana", "ano_iso", "semana_iso",
        "primeira_marcacao_hhmm", "ultima_marcacao_hhmm", "horas_na_fabrica",
        "qtd_marcacoes", "plantas_do_dia", "home_office_no_dia",
    ]
    return diario[cols].sort_values(["area", "nome", "data"]).reset_index(drop=True)


def montar_home_office_dias(df: pd.DataFrame, dim: pd.DataFrame) -> pd.DataFrame:
    """Todos os dias (cadastro, data) com pelo menos 1 marcação de home office
    (Planta == 999), independente de esse mesmo dia também ter presença física.

    Separado de `montar_presenca_diaria` de propósito: aquela função só cobre
    dias com presença física (é a base da aba "Presença Diária"), então somar
    a flag "home_office_no_dia" dali sub-conta o home office real (só pegaria
    dias mistos física+remoto). Aqui contamos TODOS os dias de home office.
    """
    ho = df.loc[~df["fisico"], ["cadastro", "data"]].drop_duplicates().copy()
    iso = ho["data"].dt.isocalendar()
    ho["ano_iso"] = iso["year"].astype(int)
    ho["semana_iso"] = iso["week"].astype(int)
    return ho.merge(dim[["cadastro"]], on="cadastro", how="inner")


def montar_semana_inicio(ano_iso: pd.Series, semana_iso: pd.Series) -> pd.Series:
    chave = ano_iso.astype(str) + "-" + semana_iso.astype(str).str.zfill(2) + "-1"
    return pd.to_datetime(chave, format="%G-%V-%u")


def montar_resumo_semanal(diario: pd.DataFrame, home_office_dias: pd.DataFrame) -> pd.DataFrame:
    semanal = (
        diario.groupby(
            ["cadastro", "nome", "area", "departamento", "cargo", "desligado", "ano_iso", "semana_iso"]
        )
        .agg(
            dias_presenciais=("data", "nunique"),
            horas_totais_fabrica=("horas_na_fabrica", "sum"),
        )
        .reset_index()
    )

    ho_semana = (
        home_office_dias.groupby(["cadastro", "ano_iso", "semana_iso"])
        .size()
        .rename("dias_home_office_na_semana")
        .reset_index()
    )
    semanal = semanal.merge(ho_semana, on=["cadastro", "ano_iso", "semana_iso"], how="left")
    semanal["dias_home_office_na_semana"] = semanal["dias_home_office_na_semana"].fillna(0).astype(int)

    semanal["semana_inicio"] = montar_semana_inicio(semanal["ano_iso"], semanal["semana_iso"])
    semanal["horas_medias_por_dia"] = (
        semanal["horas_totais_fabrica"] / semanal["dias_presenciais"]
    ).round(2)
    semanal["horas_totais_fabrica"] = semanal["horas_totais_fabrica"].round(2)

    cols = [
        "cadastro", "nome", "area", "departamento", "cargo", "desligado",
        "ano_iso", "semana_iso", "semana_inicio",
        "dias_presenciais", "horas_totais_fabrica", "horas_medias_por_dia",
        "dias_home_office_na_semana",
    ]
    return semanal[cols].sort_values(["area", "nome", "ano_iso", "semana_iso"]).reset_index(drop=True)


def montar_melhores_semanas(semanal: pd.DataFrame) -> pd.DataFrame:
    maximo = semanal.groupby("cadastro")["dias_presenciais"].transform("max")
    melhores = semanal[(semanal["dias_presenciais"] == maximo) & (semanal["dias_presenciais"] > 0)].copy()
    melhores = melhores.sort_values(
        ["area", "nome", "dias_presenciais", "horas_totais_fabrica"],
        ascending=[True, True, False, False],
    ).reset_index(drop=True)
    return melhores


def montar_resumo_pessoa(
    diario: pd.DataFrame,
    melhores: pd.DataFrame,
    dim: pd.DataFrame,
    home_office_dias: pd.DataFrame,
) -> pd.DataFrame:
    resumo = (
        diario.groupby("cadastro")
        .agg(
            total_dias_presenciais=("data", "nunique"),
            total_horas_na_fabrica=("horas_na_fabrica", "sum"),
            primeiro_dia_com_registro=("data", "min"),
            ultimo_dia_com_registro=("data", "max"),
        )
        .reset_index()
    )

    # Left join assume que quem tem dia de home office também tem pelo menos
    # 1 dia de presença física no período (verificado nos dados atuais da
    # árvore alvo). Se isso deixar de valer, essa pessoa cairia de fora do
    # `resumo` aqui, mas ainda apareceria zerada no merge final com `dim`.
    ho_total = (
        home_office_dias.groupby("cadastro")
        .size()
        .rename("total_dias_home_office")
        .reset_index()
    )
    resumo = resumo.merge(ho_total, on="cadastro", how="left")
    resumo["total_dias_home_office"] = resumo["total_dias_home_office"].fillna(0).astype(int)

    resumo["total_horas_na_fabrica"] = resumo["total_horas_na_fabrica"].round(2)
    resumo["media_horas_por_dia_presencial"] = (
        resumo["total_horas_na_fabrica"] / resumo["total_dias_presenciais"]
    ).round(2)

    melhor_por_pessoa = (
        melhores.sort_values(["cadastro", "ano_iso", "semana_iso"])
        .groupby("cadastro")
        .first()
        .reset_index()[["cadastro", "ano_iso", "semana_iso", "semana_inicio", "dias_presenciais", "horas_totais_fabrica"]]
        .rename(
            columns={
                "ano_iso": "melhor_semana_ano",
                "semana_iso": "melhor_semana_num",
                "semana_inicio": "melhor_semana_inicio",
                "dias_presenciais": "melhor_semana_dias_presenciais",
                "horas_totais_fabrica": "melhor_semana_horas",
            }
        )
    )
    resumo = resumo.merge(melhor_por_pessoa, on="cadastro", how="left")

    resumo["dias_uteis_no_periodo"] = resumo["primeiro_dia_com_registro"].apply(
        lambda d: int(np.busday_count(d.date(), (DATA_FIM + pd.Timedelta(days=1)).date()))
    )
    resumo["pct_dias_presenciais"] = (
        resumo["total_dias_presenciais"] / resumo["dias_uteis_no_periodo"] * 100
    ).round(1)

    # Garante que todas as 20 pessoas da dimensao aparecam, mesmo sem nenhum
    # evento fisico no periodo (ficam com zeros/NaN nas metricas de presenca).
    resumo = dim.merge(resumo, on="cadastro", how="left")
    for col in [
        "total_dias_presenciais", "total_horas_na_fabrica", "total_dias_home_office",
        "media_horas_por_dia_presencial", "melhor_semana_dias_presenciais", "melhor_semana_horas",
        "dias_uteis_no_periodo", "pct_dias_presenciais",
    ]:
        if col in resumo.columns:
            resumo[col] = resumo[col].fillna(0)

    # Ordem pedida pelo usuário (as colunas de "melhor semana" ficam só na aba
    # "Semanas com Mais Presença" — aqui bastam os totais/médias por pessoa).
    cols = [
        "cadastro", "nome", "area", "departamento", "cargo", "cargo_especifico", "desligado",
        "pct_dias_presenciais", "total_horas_na_fabrica", "media_horas_por_dia_presencial",
        "total_dias_presenciais", "dias_uteis_no_periodo", "total_dias_home_office",
        "primeiro_dia_com_registro", "ultimo_dia_com_registro",
    ]
    return resumo[cols].sort_values(["area", "nome"]).reset_index(drop=True)


def montar_base_bruta(df: pd.DataFrame) -> pd.DataFrame:
    out = df[
        [
            "cadastro", "nome", "area", "departamento", "heranca", "cargo", "cargo_especifico",
            "desligado", "data", "hora", "dir", "planta", "coletor", "descricao_coletor",
            "uso_acesso", "tipo", "acesso", "registro_manual",
        ]
    ].copy()
    out = out.sort_values(["cadastro", "data", "hora"]).reset_index(drop=True)
    return out


# ----------------------------------------------------------------------------
# Excel writing / styling
# ----------------------------------------------------------------------------

RENOMEIA = {
    "cadastro": "Cadastro",
    "nome": "Nome",
    "area": "Área",
    "departamento": "Departamento",
    "heranca": "Herança",
    "cargo": "Cargo",
    "cargo_especifico": "Cargo Específico",
    "desligado": "Desligado",
    "data": "Data",
    "hora": "Hora",
    "dir": "Direção",
    "planta": "Planta",
    "coletor": "Coletor",
    "descricao_coletor": "Descrição Coletor",
    "uso_acesso": "Uso Acesso",
    "tipo": "Tipo",
    "acesso": "Acesso",
    "registro_manual": "Registro Manual",
    "dia_semana": "Dia da Semana",
    "ano_iso": "Ano (ISO)",
    "semana_iso": "Semana (ISO)",
    "primeira_marcacao_hhmm": "Primeira Marcação",
    "ultima_marcacao_hhmm": "Última Marcação",
    "horas_na_fabrica": "Horas na Fábrica",
    "qtd_marcacoes": "Qtd. Marcações no Dia",
    "plantas_do_dia": "Planta(s) do Dia",
    "home_office_no_dia": "Também c/ Home Office no Dia",
    "semana_inicio": "Semana (Início - Segunda)",
    "dias_presenciais": "Dias Presenciais",
    "horas_totais_fabrica": "Horas Totais na Fábrica",
    "horas_medias_por_dia": "Horas Médias por Dia",
    "dias_home_office_na_semana": "Dias c/ Home Office na Semana",
    "total_dias_presenciais": "Total Dias Presenciais",
    "dias_uteis_no_periodo": "Dias Úteis no Período",
    "pct_dias_presenciais": "% Dias Presenciais",
    "total_horas_na_fabrica": "Total Horas na Fábrica",
    "media_horas_por_dia_presencial": "Média Horas / Dia Presencial",
    "melhor_semana_ano": "Melhor Semana - Ano",
    "melhor_semana_num": "Melhor Semana - Nº (ISO)",
    "melhor_semana_inicio": "Melhor Semana - Início",
    "melhor_semana_dias_presenciais": "Melhor Semana - Dias Presenciais",
    "melhor_semana_horas": "Melhor Semana - Horas",
    "total_dias_home_office": "Total Dias Home Office",
    "primeiro_dia_com_registro": "Primeiro Dia c/ Registro",
    "ultimo_dia_com_registro": "Último Dia c/ Registro",
}

DATE_COLS = {
    "Data", "Semana (Início - Segunda)", "Melhor Semana - Início",
    "Primeiro Dia c/ Registro", "Último Dia c/ Registro",
}


def _traduzir(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns=RENOMEIA)


def _estilizar_planilha(ws: Worksheet, n_linhas: int, n_colunas: int, congelar_col: str = "A2") -> None:
    header_fill = PatternFill("solid", fgColor=VW_BLUE)
    header_font = Font(color="FFFFFF", bold=True, size=10)
    alt_fill = PatternFill("solid", fgColor=VW_BLUE_LIGHT)
    thin = Side(style="thin", color="D0D0D0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    ws.row_dimensions[1].height = 28

    headers = [c.value for c in ws[1]]
    for row_idx in range(2, n_linhas + 2):
        if row_idx % 2 == 0:
            for col_idx in range(1, n_colunas + 1):
                ws.cell(row=row_idx, column=col_idx).fill = alt_fill
        for col_idx in range(1, n_colunas + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = border
            header_name = headers[col_idx - 1]
            if header_name in DATE_COLS:
                cell.number_format = "dd/mm/yyyy"
            elif header_name and ("Horas" in str(header_name)):
                cell.number_format = "0.00"
            elif header_name == "% Dias Presenciais":
                cell.number_format = "0.0"

    for col_idx, header_name in enumerate(headers, start=1):
        largura = max(12, min(38, len(str(header_name)) + 4))
        ws.column_dimensions[get_column_letter(col_idx)].width = largura

    ws.freeze_panes = congelar_col
    ws.auto_filter.ref = ws.dimensions


def _destacar_coluna(ws: Worksheet, header_name: str, n_linhas: int) -> None:
    headers = [c.value for c in ws[1]]
    if header_name not in headers:
        return
    col_idx = headers.index(header_name) + 1
    col_letter = get_column_letter(col_idx)
    rule = ColorScaleRule(
        start_type="min", start_color="FFF7CC",
        mid_type="percentile", mid_value=50, mid_color="FFD98C",
        end_type="max", end_color="63BE7B",
    )
    ws.conditional_formatting.add(f"{col_letter}2:{col_letter}{n_linhas + 1}", rule)


def gerar_leia_me(wb, dim: pd.DataFrame | None = None) -> None:
    ws = wb.create_sheet("Leia-me", 0)
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 110

    titulo = Font(color="FFFFFF", bold=True, size=16)
    texto = Font(size=10.5)

    ws.merge_cells("A1:B2")
    ws["A1"] = "Relatório de Horas na Fábrica e Semanas com Mais Presença"
    ws["A1"].font = titulo
    ws["A1"].fill = PatternFill("solid", fgColor=VW_BLUE)
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 20
    ws.row_dimensions[2].height = 20
    for r in (1, 2):
        ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=VW_BLUE)

    n_pessoas = dim["cadastro"].nunique() if dim is not None and not dim.empty else 0
    cargos_presentes = (
        ", ".join(sorted(dim["cargo"].dropna().unique())) if dim is not None and not dim.empty else "-"
    )

    linhas = [
        ("", None),
        ("Escopo", "sub"),
        (f"Áreas analisadas (definidas em RONDA_RELATORIO_AREAS na hora de gerar este "
         f"arquivo — não versionado no script): {', '.join(AREAS_ALVO)}. "
         f"{n_pessoas} pessoas ao todo nessa seleção, cargos presentes: {cargos_presentes}.", "txt"),
        ("", None),
        ("Janela de dados", "sub"),
        (f"{DATA_INICIO:%d/%m/%Y} a {DATA_FIM:%d/%m/%Y}. Ajustar essas datas conforme a "
         "cobertura real da base no momento de gerar o relatório — a base pode ter cauda de "
         "datas futuras que são cargas de teste/placeholder (sem continuidade de negócio, "
         "mesmo padrão de nº de pessoas em datas fixas do mês); confirme isso antes de rodar "
         "e ajuste DATA_FIM se necessário para não distorcer horas e presença.", "txt"),
        ("", None),
        ("O que é \"presencial\" / \"dentro da fábrica\"", "sub"),
        ("Presencial = qualquer evento de catraca/refeitório/portaria com Planta ≠ 999 no dia. "
         "Planta 999 é o código reservado para marcação de home office feita pelo app "
         "\"Captura Ponto 373\" / Mobilidade — não é presença física e é tratada à parte "
         "(colunas de Home Office).", "txt"),
        ("", None),
        ("Como as horas são calculadas", "sub"),
        ("Para cada pessoa/dia, \"Horas na Fábrica\" = horário da última marcação física do dia "
         "menos horário da primeira marcação física do dia (mesmo critério já usado no projeto "
         "em \"Análise das horas dos colaboradores.ipynb\": primeira e última marcação do dia, "
         "sem diferenciar catraca de refeitório). Não há registro de intervalo/almoço separado "
         "nessa árvore, então o valor é o intervalo bruto entre entrada e saída observadas.", "txt"),
        ("", None),
        ("Como o Home Office é contado", "sub"),
        ("\"Total Dias Home Office\" (Resumo por Pessoa) e \"Dias c/ Home Office na Semana\" "
         "(Resumo Semanal) contam TODO dia com pelo menos 1 marcação Planta = 999 no período, "
         "esteja ou não presencial nesse mesmo dia. Já a coluna \"Também c/ Home Office no Dia\" "
         "na aba Presença Diária é mais estreita: só marca Sim quando aquele dia específico teve "
         "presença física E marcação de home office ao mesmo tempo (dia misto) — não use essa "
         "coluna para somar o total de home office da pessoa, ela vai subestimar.", "txt"),
        ("", None),
        ("Semanas com mais dias presenciais", "sub"),
        ("Semana = ISO (segunda a domingo). Para cada pessoa, a aba \"Semanas com Mais Presença\" "
         "traz a(s) semana(s) em que ela teve o maior número de dias presenciais no período "
         "(pode haver empate — todas aparecem). A aba \"Resumo por Pessoa\" traz a primeira "
         "dessas semanas-recorde como referência rápida.", "txt"),
        ("", None),
        ("Abas deste arquivo", "sub"),
        ("1. Resumo por Pessoa — uma linha por pessoa: total de dias presenciais, total de horas "
         "na fábrica, % de dias úteis presencial e a melhor semana.", "bullet"),
        ("2. Semanas com Mais Presença — ranking das semanas-recorde de cada pessoa (dias "
         "presenciais + horas), para leitura rápida de quem tem semanas mais cheias.", "bullet"),
        ("3. Resumo Semanal — todas as semanas de todas as pessoas, com dias presenciais, "
         "horas totais e horas médias por dia (base para gráficos/pivôs próprios).", "bullet"),
        ("4. Presença Diária — um registro por pessoa/dia com presença física: primeira e "
         "última marcação, horas na fábrica e se também houve marcação de home office no dia.", "bullet"),
        ("5. Base Bruta (Eventos) — todos os eventos de catraca/ponto originais das áreas "
         "selecionadas dentro da janela de dados, sem agregação (\"toda a base\", já filtrada "
         "por área).", "bullet"),
        ("", None),
        (f"Gerado em {dt.datetime.now():%d/%m/%Y %H:%M} — Fonte: project/database/df_ronda.parquet", "rodape"),
    ]

    row = 4
    for texto_linha, tipo in linhas:
        cell = ws.cell(row=row, column=2, value=texto_linha or None)
        if tipo == "sub":
            cell.font = Font(bold=True, size=12, color=VW_BLUE)
        elif tipo == "bullet":
            cell.font = texto
        elif tipo == "rodape":
            cell.font = Font(size=9, italic=True, color="666666")
        else:
            cell.font = texto
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = 14 if not texto_linha else max(14, 14 * (len(texto_linha) // 100 + 1))
        row += 1


def escrever_planilha(wb, nome_aba: str, df: pd.DataFrame, destacar: list[str] | None = None, congelar: str = "A2") -> None:
    ws = wb.create_sheet(nome_aba)
    df_fmt = _traduzir(df)

    for r in dataframe_to_rows(df_fmt, index=False, header=True):
        ws.append(r)

    _estilizar_planilha(ws, n_linhas=len(df_fmt), n_colunas=len(df_fmt.columns), congelar_col=congelar)
    for col in (destacar or []):
        _destacar_coluna(ws, col, len(df_fmt))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = carregar_base()
    dim = montar_dimensao(df)
    diario = montar_presenca_diaria(df, dim)
    home_office_dias = montar_home_office_dias(df, dim)
    semanal = montar_resumo_semanal(diario, home_office_dias)
    melhores = montar_melhores_semanas(semanal)
    resumo_pessoa = montar_resumo_pessoa(diario, melhores, dim, home_office_dias)
    base_bruta = montar_base_bruta(df)

    wb = Workbook()
    wb.remove(wb.active)

    gerar_leia_me(wb, dim)
    escrever_planilha(wb, "Resumo por Pessoa", resumo_pessoa, destacar=["Total Horas na Fábrica", "% Dias Presenciais"])
    escrever_planilha(wb, "Semanas com Mais Presença", melhores.drop(columns=["desligado"], errors="ignore"), destacar=["Dias Presenciais"])
    escrever_planilha(wb, "Resumo Semanal", semanal, destacar=["Dias Presenciais"])
    escrever_planilha(wb, "Presença Diária", diario, destacar=["Horas na Fábrica"])
    escrever_planilha(wb, "Base Bruta (Eventos)", base_bruta)

    wb.save(OUT_XLSX)
    print(f"OK -> {OUT_XLSX}")
    print(f"Pessoas: {len(resumo_pessoa)} | Dias presenciais: {len(diario)} | Semanas: {len(semanal)} | Eventos brutos: {len(base_bruta)}")


if __name__ == "__main__":
    main()
