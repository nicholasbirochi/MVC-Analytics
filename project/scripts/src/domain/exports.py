"""exports.py

Funções de exportação (imagens, texto, HTML, etc.).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

import base64
import io

import matplotlib.pyplot as plt
import pandas as pd


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


def calcular_percentual_presenca(dias_presenca_por_semana: pd.Series) -> float:
    pontuacao = dias_presenca_por_semana.apply(
        lambda valor: 1 if valor >= 2 else (0.5 if valor == 1 else 0)
    )
    return round(pontuacao.mean() * 100, 1)


def gerar_relatorio_formatado(
    nome_input: str,
    chapa_input: str,
    media_presenca_semana,
    percentuais_presenca,
    periodo_label_completo: str,
) -> str:
    return (
        "   Relatório Corporativo - Sistema Integrado de Gestão de Frequência da Volkswagen\n\n"
        "   Este relatório tem como finalidade fornecer uma base de dados consolidada, com visualizações estratégicas e indicadores de performance "
        f"relacionados à presença e ao regime de trabalho dos colaboradores entre {periodo_label_completo}.\n\n"
        rf"  O colaborador {nome_input} ({chapa_input}) apresentou uma média semanal de presença de "
        rf"$\bf{{{media_presenca_semana}}}$ dia(s) no formato presencial. Para fins de cálculo, foi adotada uma metodologia de pontuação semanal baseada na quantidade de dias presenciais registrados:"
        "\n- 0 dias presenciais na semana = 0% de presença;\n"
        "- 1 dia presencial = 50%;\n"
        "- 2 ou mais dias presenciais = 100%.\n"
        "Ao longo do período analisado, a presença semanal média do colaborador no formato presencial foi de "
        rf"$\bf{{{percentuais_presenca}\%}}$."
        "\n\n   Importante destacar que, para este relatório, não foram consideradas como justificativas válidas de ausência: feriados, férias individuais, "
        "viagens a trabalho ou ausências previamente acordadas. A única exceção aplicada foi para períodos de férias coletivas, devidamente identificadas "
        "e excluídas do cálculo para evitar distorções. "
        'Foram identificadas as seguintes semanas com presença muito baixa, ou seja, entre "0" e "1" dia durante a semana (Ano-Semana):'
    )
