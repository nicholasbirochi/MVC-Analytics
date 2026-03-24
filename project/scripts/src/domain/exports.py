"""exports.py

Funções de exportação (imagens, texto, HTML, etc.).

Projeto: Dashboard presencialidade — Empresa
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DATA_MUDANCA_REGRA_PRESENCIAL = pd.Timestamp("2025-05-01")
MIN_PRESENCIAL_ANTES_MUDANCA = 2
MIN_PRESENCIAL_APOS_MUDANCA = 3


def fig_to_base64(fig) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    buffer.seek(0)
    encoded = base64.b64encode(buffer.read()).decode("utf-8")
    plt.close(fig)
    return f"data:image/png;base64,{encoded}"


def fig_to_bytes(fig, fmt: str = "png") -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format=fmt, bbox_inches="tight")
    buffer.seek(0)
    return buffer.read()


def min_presencial_exigido(semana_ano: str) -> int:
    """Retorna o minimo de dias presenciais exigido para a semana ISO "AAAA-SS"."""
    try:
        ano_str, sem_str = str(semana_ano).split("-")
        ano, sem = int(ano_str), int(sem_str)
        dt_ini_semana = datetime.fromisocalendar(ano, sem, 1)
        dt_fim_semana = dt_ini_semana + timedelta(days=6)
        return (
            MIN_PRESENCIAL_APOS_MUDANCA
            if pd.Timestamp(dt_fim_semana) >= DATA_MUDANCA_REGRA_PRESENCIAL
            else MIN_PRESENCIAL_ANTES_MUDANCA
        )
    except Exception:
        return MIN_PRESENCIAL_APOS_MUDANCA


def calcular_percentual_presenca(dias_presenca_por_semana: pd.Series) -> float:
    """Calcula percentual medio considerando a regra vigente por semana."""
    if dias_presenca_por_semana is None or len(dias_presenca_por_semana) == 0:
        return 0.0

    scores = []
    for semana_ano, qtd in dias_presenca_por_semana.items():
        req = float(min_presencial_exigido(semana_ano))
        qtd = 0.0 if pd.isna(qtd) else float(qtd)
        score = 0.0 if req <= 0 else min(qtd / req, 1.0)
        scores.append(score)

    return round(float(np.mean(scores)) * 100, 1)


def gerar_relatorio_formatado(
    nome_input: str,
    chapa_input: str,
    media_presenca_semana,
    percentuais_presenca,
    periodo_label_completo: str,
) -> str:
    return (
        "   Relatório Corporativo - Sistema Integrado de Gestão de Frequência da Empresa\n\n"
        "   Este relatório tem como finalidade fornecer uma base de dados consolidada, com visualizações estratégicas e indicadores de performance "
        f"relacionados à presença e ao regime de trabalho dos colaboradores entre {periodo_label_completo}.\n\n"
        rf"  O colaborador {nome_input} ({chapa_input}) apresentou uma média semanal de presença de "
        rf"$\bf{{{media_presenca_semana}}}$ dia(s) no formato presencial. Para fins de cálculo, foi considerada a regra vigente por semana:"
        "\n- até Abril/2025: mínimo 2 dias presenciais/semana;\n"
        "- a partir de Maio/2025: mínimo 3 dias presenciais/semana.\n"
        "A pontuação semanal é calculada como: min(dias_presenciais / mínimo_exigido_na_semana, 1).\n"
        "Ao longo do período analisado, a presença semanal média do colaborador no formato presencial foi de "
        rf"$\bf{{{percentuais_presenca}\%}}$."
        "\n\n   Importante destacar que, para este relatório, não foram consideradas como justificativas válidas de ausência: feriados, férias individuais, "
        "viagens a trabalho ou ausências previamente acordadas. A única exceção aplicada foi para períodos de férias coletivas, devidamente identificadas "
        "e excluídas do cálculo para evitar distorções. "
        'Foram identificadas as seguintes semanas com presença muito baixa, ou seja, entre "0" e "1" dia durante a semana (Ano-Semana):'
    )


