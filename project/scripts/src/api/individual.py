"""individual.py

Callbacks e geração do relatório individual (colaborador).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations
from dash import Input, Output, State, dcc, html, no_update

import base64
from collections import defaultdict
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import matplotlib.patheffects as patheffects

from ..core.repo_global import (
    df_semana_merged,
    df_datas,
)
from ..domain.exports import (
    fig_to_base64,
    fig_to_bytes,
    gerar_relatorio_formatado,
    calcular_percentual_presenca,
    min_presencial_exigido,
    MIN_PRESENCIAL_APOS_MUDANCA,
)
from ..domain.pipeline import dw_fetch_diarios, dw_fetch_semana_enriquecida
from ..domain.tenure import obter_periodo_admissao
from ..ui.theme import (
    ESTILO_EXIBIR,
    ESTILO_OCULTO,
    ORDENACAO_DIAS,
    DIAS_PORTUGUES,
)

estilo_exibir = ESTILO_EXIBIR
estilo_oculto = ESTILO_OCULTO
ordenacao_dias = ORDENACAO_DIAS
dias_portugues = DIAS_PORTUGUES


def register(app):
    @app.callback(
        Output('conteudo-individual', 'children'),
        Output('conteudo-individual', 'style'),
        Output('pagina-geral', 'style', allow_duplicate=True),
        Output('url', 'pathname', allow_duplicate=True),
        Input('url', 'pathname'),
        Input('botao-voltar', 'n_clicks'),
        prevent_initial_call=True
    )
    def exibir_conteudo_individual(pathname, n_clicks):
        # Voltar
        if n_clicks is not None and n_clicks > 0:
            return None, estilo_oculto, estilo_exibir, "/"

        # Roteamento
        if not pathname or '/pessoa/' not in pathname:
            return None, estilo_oculto, no_update, no_update

        chapa_input = pathname.split('/pessoa/')[1]
        if not chapa_input:
            return None, estilo_oculto, estilo_exibir, no_update

        # Filtra dados da pessoa
        df_chapa_semana = dw_fetch_semana_enriquecida(cadastro=str(chapa_input))
        if df_chapa_semana.empty:
            return None, estilo_oculto, estilo_exibir, no_update

        nome_input = df_chapa_semana['Nome'].iloc[0].title()

        # Semana-Ano
        df_chapa_semana['Semana_Ano'] = (
            df_chapa_semana['Ano'].astype(str) + "-" + df_chapa_semana['Semana por Ano'].astype(str).str.zfill(2)
        )

        # Presenças por semana
        dias_presenca_por_semana = df_chapa_semana.groupby('Semana_Ano')['Contagem Presença'].mean()
        media_presenca_semana = round(dias_presenca_por_semana.mean(), 2)
        min_req_por_semana = dias_presenca_por_semana.index.to_series().apply(min_presencial_exigido)
        media_min_req = (
            round(min_req_por_semana.mean(), 2)
            if len(min_req_por_semana)
            else MIN_PRESENCIAL_APOS_MUDANCA
        )
        if pd.isna(media_min_req) or media_min_req <= 0:
            media_min_req = MIN_PRESENCIAL_APOS_MUDANCA

        percentual_da_media = round(((media_presenca_semana / media_min_req) * 100) - 100, 2)
        percentuais_presenca = calcular_percentual_presenca(dias_presenca_por_semana)

        # Distribuição de presenças (0..7) baseada na fonte canônica SQL do colaborador.
        distribuicao_presencas = df_chapa_semana['Contagem Presença'].value_counts().sort_index()
        x = sorted(set(distribuicao_presencas.index))
        y_presencas = distribuicao_presencas.reindex(x, fill_value=0)

        # Série temporal (ordenada)
        dias_presenca_por_semana_ordenado = dias_presenca_por_semana.sort_index()
        x_semanas = list(range(1, len(dias_presenca_por_semana_ordenado) + 1))
        y_presenca_por_semana = dias_presenca_por_semana_ordenado.values

        # Datas do heatmap geral
        df_chapa_data = dw_fetch_diarios([str(chapa_input)])[['Data', 'Cadastro']].copy()
        df_chapa_data['Data'] = pd.to_datetime(df_chapa_data['Data'])

        # Datas reais da chapa em df_datas
        df_chapa_data = dw_fetch_diarios([str(chapa_input)])[['Data', 'Cadastro']].copy()
        df_chapa_data['Data'] = pd.to_datetime(df_chapa_data['Data'], errors='coerce')

        # Se quiser limitar por admissão/demissão, usa o range dentro desse intervalo:
        # garanta que são Timestamps
        min_real = pd.Timestamp(df_chapa_data['Data'].min())
        max_real = pd.Timestamp(df_chapa_data['Data'].max())

        if pd.isna(min_real) or pd.isna(max_real):
            # Sem datas -> não há como montar o heatmap
            return None, estilo_oculto, estilo_exibir, no_update

        def _fmt_mes_ano(dt_ref: pd.Timestamp) -> str:
            try:
                return f"{dt_ref.month_name(locale='pt_BR').capitalize()} de {dt_ref.year}"
            except Exception:
                return dt_ref.strftime("%b de %Y").capitalize()

        m0 = _fmt_mes_ano(min_real)
        m1 = _fmt_mes_ano(max_real)

        mes_ano_inicio = m0
        mes_ano_fim    = m1

        # cria rótulos dinâmicos
        periodo_label_completo = f"{mes_ano_inicio} a {mes_ano_fim}"

        mes_ano_inicio = min_real.strftime("%b %Y").capitalize()
        mes_ano_fim    = max_real.strftime("%b %Y").capitalize()
        periodo_label_curto = f"{mes_ano_inicio} a {mes_ano_fim}"

        # Se quiser cruzar com adm/dem, aplique aqui:
        data_adm, data_dem = obter_periodo_admissao(chapa_input)
        adm_ts = pd.to_datetime(data_adm, errors="coerce")
        dem_ts = pd.to_datetime(data_dem, errors="coerce")
        if pd.notna(adm_ts):
            min_real = max(min_real.normalize(), adm_ts.normalize())
        if pd.notna(dem_ts):
            max_real = min(max_real.normalize(), dem_ts.normalize())

        # Gera TODAS as datas no período [min_real .. max_real]
        todas_datas = pd.date_range(min_real.normalize(), max_real.normalize(), freq='D')

        # Monta dataframe de referência (com rótulos ISO semanais e dias em PT)
        _dias_pt = {0:'Segunda',1:'Terça',2:'Quarta',3:'Quinta',4:'Sexta',5:'Sábado',6:'Domingo'}
        inicio_sem = todas_datas - pd.to_timedelta(todas_datas.weekday, unit='D')
        fim_sem = inicio_sem + pd.to_timedelta(6, unit='D')

        df_todas_datas = pd.DataFrame({
            "Data": todas_datas,
            "Ano": todas_datas.isocalendar().year.astype(int),
            "Semana_Num": todas_datas.isocalendar().week.astype(int),
            "Início da Semana": inicio_sem,
            "Fim da Semana": fim_sem,
        })
        df_todas_datas["Semana_Label"] = (
            df_todas_datas["Ano"].astype(str) + "-" + df_todas_datas["Semana_Num"].astype(str).str.zfill(2)
            + " | " + df_todas_datas["Início da Semana"].dt.strftime('%d/%m/%Y')
            + "-" + df_todas_datas["Fim da Semana"].dt.strftime('%d/%m/%Y')
        )
        df_todas_datas["Dia da Semana"] = df_todas_datas["Data"].dt.weekday.map(_dias_pt)

        # Merge de presença (1 se existe linha para a Data daquela chapa)
        df_merged = df_todas_datas.merge(df_chapa_data[["Data", "Cadastro"]], on="Data", how="left")
        df_merged["Presente"] = df_merged["Cadastro"].notna().astype(int)

        tabela_heatmap = (
            df_merged
            .pivot_table(index="Semana_Label", columns="Dia da Semana", values="Presente", aggfunc="sum", fill_value=0)
            .reindex(columns=ordenacao_dias)
            .sort_index()
        )

        df_todas_datas["Semana_Num"] = df_todas_datas["Data"].dt.isocalendar().week
        df_todas_datas["Início da Semana"] = df_todas_datas["Data"] - pd.to_timedelta(df_todas_datas["Data"].dt.weekday, unit="d")
        df_todas_datas["Fim da Semana"] = df_todas_datas["Início da Semana"] + pd.to_timedelta(6, unit="d")
        df_todas_datas["Semana_Label"] = (
            df_todas_datas["Ano"].astype(str) + "-" + df_todas_datas["Semana_Num"].astype(str).str.zfill(2)
            + " | " + df_todas_datas["Início da Semana"].dt.strftime('%d/%m/%Y')
            + "-" + df_todas_datas["Fim da Semana"].dt.strftime('%d/%m/%Y')
        )
        df_todas_datas["Dia da Semana"] = df_todas_datas["Data"].dt.day_name().map(dias_portugues).fillna(
            df_todas_datas["Data"].dt.day_name()
        )

        df_merged = df_todas_datas.merge(df_chapa_data[["Data", "Cadastro"]], how="left", on="Data")
        tabela_heatmap = df_merged.pivot_table(
            index="Semana_Label",
            columns="Dia da Semana",
            values="Cadastro",
            aggfunc="count",
            fill_value=0
        ).reindex(columns=ordenacao_dias)

        # ======= Figura (Matplotlib) =======
        fig = plt.figure(figsize=(28, 45))
        gs = gridspec.GridSpec(3, 2, height_ratios=[0.7, 0.5, 3.0], width_ratios=[1.9, 1.9])
        gs_heatmaps = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=gs[2, 0],
                                                       height_ratios=[max(1, tabela_heatmap.shape[0]), 1], hspace=0.02)

        # Título e linha de topo
        fig.suptitle(
            f"{nome_input} — Chapa {chapa_input}",
            x=0.01, y=1.012, fontsize=30, fontweight='bold', ha='left'
        )
        fig.lines.append(
            Line2D([0.01, 0.99], [0.992, 0.992], color='gray', linestyle='dashed', linewidth=1.5,
                alpha=0.6, transform=fig.transFigure, figure=fig)
        )
        fig.text(0.5, 0.953, f"Relatório de Frequência e Regime de Trabalho no Período de {periodo_label_completo}\n\n\n",
                 fontsize=28, ha='center')

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 1 - Gauge ~~~~~~~~~~~~~~~~~~~~~
        ax_clock = fig.add_subplot(gs[0, 0], polar=True)
        ax_clock.set_theta_offset(np.pi)
        ax_clock.set_theta_direction(-1)
        current_val = float(media_presenca_semana)
        colors = ['#ffb3b3', '#f4cccc', '#d9ead3', '#b6e6c5', '#96ddb1', '#6ccf9a', '#3fbe81']
        bounds = [0, 1, 2, 3, 4, 5, 6, 7]
        ax_clock.set_yticklabels([]); ax_clock.set_xticklabels([]); ax_clock.set_axis_off()
        for i in range(len(colors)):
            start = np.pi * (bounds[i] / 7)
            end = np.pi * (bounds[i + 1] / 7)
            ax_clock.barh(1, end - start, left=start, height=0.4, color=colors[i], edgecolor='black')
        tick_vals = [0, 1, 2, 3, 4, 5, 6, 7]
        tick_angles = [np.pi * (val / 7) for val in tick_vals]
        for ang, label in zip(tick_angles, [f"{val:.1f}" for val in tick_vals]):
            ax_clock.text(ang, 1.3, label, ha='center', va='center', fontsize=17, color='gray')
        angle = np.pi * (min(current_val, 7) / 7)
        ax_clock.arrow(angle, 0, 0, 0.95, width=0.03, head_width=0.08, head_length=0.15, fc='black', ec='black', zorder=5)
        ax_clock.text(0, 0, f"\n\n\n{current_val:.2f} dias/semana", fontsize=20, ha='center', va='center', color='#444')
        rect = Rectangle((0.264, 0.385), 0.48, 0.07, linewidth=2, edgecolor='black', facecolor='none',
                         transform=ax_clock.transAxes, zorder=10)
        ax_clock.add_patch(rect)
        ax_clock.set_title(f"\n\nFrequência da Contagem de Presencial\npor Semana ({periodo_label_curto})\n", va='bottom', fontsize=20, pad=35)
        if current_val > media_min_req:
            ax_clock.text(0.01, 0, f"\n\n\n\n\n Acima do necessário! \n+{percentual_da_media}%",
                          ha='center', va='center', fontsize=34, color='green', fontweight='bold',
                          path_effects=[patheffects.withStroke(linewidth=3, foreground='white')])
        elif current_val < media_min_req:
            ax_clock.text(0.01, 0, f"\n\n\n\n\n Abaixo do esperado! \n{percentual_da_media}%",
                          ha='center', va='center', fontsize=34, color='red', fontweight='bold',
                          path_effects=[patheffects.withStroke(linewidth=3, foreground='white')])
        ax_clock.patch.set_facecolor('white'); ax_clock.patch.set_alpha(0)
        ax_clock.text(-0.15, -0.16,
                      'Indicador de frequência presencial semanal de "0" a "7" dias úteis por semana.\n'
                      'Esse gráfico ajuda a saber a média que o colaborador está presente na planta.',
                      ha='left', va='center', fontsize=14, wrap=True, transform=ax_clock.transAxes)

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 2 - Distribuição por contagem semanal ~~~~~~~~~~~~~~~~~~~~~
        ax_line = fig.add_axes([0.618, 0.8195, 0.35, 0.120])
        ax_line.plot(x, y_presencas, color='#3fbe81', linewidth=4, label='Presencial')
        ax_line.fill_between(x, y_presencas, color='#96ddb1', alpha=0.5)
        for xi, yi in zip(x, y_presencas):
            ax_line.text(xi, yi + 0.14, f"{yi}", ha='center', fontsize=17)
        ax_line.set_xticks(x)
        ax_line.set_xlabel('Qtd. de Presencial na Semana', fontsize=20)
        ax_line.set_ylabel('Número de Ocorrências', fontsize=20)
        ax_line.set_title(f'Distribuição da Contagem de Presencial\npor Semana ({periodo_label_curto})', fontsize=20, pad=25)
        ax_line.grid(True, linestyle='--')
        ax_line.tick_params(axis='x', labelsize=17)
        ax_line.tick_params(axis='y', labelsize=17)
        ax_line.text(0, -0.28,
                     "Quantidade de semanas para uma certa quantidade de presença.\n"
                     "Esse gráfico ajuda a visualizar picos de frequência, transições de regime.",
                     ha='left', va='center', fontsize=14, wrap=True, transform=ax_line.transAxes)

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 3 - Série temporal + tendência ~~~~~~~~~~~~~~~~~~~~~
        x_np = np.array(sorted(x_semanas))
        y_np = np.array([y for _, y in sorted(zip(x_semanas, y_presenca_por_semana))])
        ax_line2 = fig.add_axes([0.204, 0.626, 0.680, 0.119])
        ax_line2.plot(x_np, y_np, color='#3fbe81', linewidth=4, label='Presencial')
        if len(x_np) >= 2:
            deg = 1 if len(x_np) == 2 else 2
            coef_poly = np.polyfit(x_np, y_np, deg=deg)
            poly_fn = np.poly1d(coef_poly)
            x_pred = np.linspace(x_np[0], x_np[-1], 500)
            fim = poly_fn(x_pred[-1])
            cor_tendencia = 'red' if fim < media_min_req else '#256b2b'
            ax_line2.plot(x_pred, poly_fn(x_pred), color=cor_tendencia, linestyle='--', linewidth=2, label='Tendência')
        ax_line2.set_xlim(x_np[0], x_np[-1] if len(x_np) else 1)
        anos = [label.split("-")[0] for label in dias_presenca_por_semana_ordenado.index]
        semanas = [int(label.split("-")[1]) for label in dias_presenca_por_semana_ordenado.index]
        ax_line2.set_xticks(x_semanas)
        ax_line2.set_xticklabels(semanas, fontsize=16)
        semanas_por_ano = defaultdict(list)
        for xv, ano in zip(x_semanas, anos):
            semanas_por_ano[ano].append(xv)
        for ano, semanas_ano in semanas_por_ano.items():
            centro = np.mean(semanas_ano)
            ax_line2.text(centro, -0.8, ano, transform=ax_line2.transData, ha='center', va='center', fontsize=18, color='gray')
        for i in range(1, len(anos)):
            if anos[i] != anos[i - 1]:
                x_val = x_semanas[i] - 0.5
                x_fig, _ = ax_line2.transData.transform((x_val, 0))
                x_fig_norm = fig.transFigure.inverted().transform((x_fig, 0))[0]
                bbox = ax_line2.get_position()
                y_fig = bbox.y0 - 0.015
                fig.lines.append(Line2D([x_fig_norm, x_fig_norm], [y_fig, y_fig + 0.015],
                                        transform=fig.transFigure, linestyle='--', color='gray', linewidth=2, alpha=0.7))
        ax_line2.set_xlabel('', fontsize=20)
        ax_line2.set_ylabel('Quantidade de Presença', fontsize=20)
        ax_line2.set_title(f'Distribuição da Contagem de Presencial em cada Semana ({periodo_label_curto})', fontsize=20, pad=25)
        ax_line2.grid(True, linestyle='--')
        ax_line2.legend(fontsize=16, loc='upper right')
        ax_line2.tick_params(axis='x', labelsize=17)
        ax_line2.tick_params(axis='y', labelsize=17)
        ax_line2.text(0, -0.31,
                      "Número de presença em cada semana de todo esse período, esse gráfico ajuda a visualizar picos de frequência, "
                      "transições de regime e a tendência do colaborador.\n\n\n\n\n\n",
                      ha='left', va='center', fontsize=14, wrap=True, transform=ax_line2.transAxes)

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 4 - Heatmap (semanas x dias) ~~~~~~~~~~~~~~~~~~~~~
        ax_heatmap = fig.add_subplot(gs_heatmaps[0])
        if tabela_heatmap.empty:
            ax_heatmap.axis('off')
        else:
            sns.heatmap(
                tabela_heatmap,
                cmap=ListedColormap(['#d9ead3']),
                linewidths=1, linecolor='gray',
                annot=True, annot_kws={"size": 17},
                cbar=False, ax=ax_heatmap
            )

        # Coloração por presença baixa
        for y_idx, semana_label in enumerate(tabela_heatmap.index):
            semana_codigo = semana_label.split(" |")[0].replace(" ", "-")
            if semana_codigo in dias_presenca_por_semana.index:
                qtd_presenca = dias_presenca_por_semana.loc[semana_codigo]
                cor_destaque = "#ffb3b3" if qtd_presenca == 0 else ("#f4cccc" if qtd_presenca == 1 else "#d9ead3")
                for col_idx in range(tabela_heatmap.shape[1]):
                    ax_heatmap.add_patch(
                        plt.Rectangle((col_idx, y_idx), 1, 1, facecolor=cor_destaque,
                                      edgecolor='gray', linewidth=2, zorder=1)
                    )
        ax_heatmap.set_title(f'\n\n\n\n\n\n\nDistribuição da Contagem de Presencial por\nAno e Semana para cada Dia da Semana ({periodo_label_curto})\n',
                             fontsize=20, pad=40)
        ax_heatmap.xaxis.set_label_position('top')
        ax_heatmap.xaxis.tick_top()
        ax_heatmap.tick_params(axis='x', bottom=False, labelbottom=False)
        ax_heatmap.set_ylabel(''); ax_heatmap.set_xlabel('')
        ax_heatmap.set_xticklabels(ax_heatmap.get_xticklabels(), fontsize=20)
        ax_heatmap.set_yticklabels(ax_heatmap.get_yticklabels(), fontsize=20)

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 5 - Texto + mini heatmap de semanas baixas ~~~~~~~~~~~~~~~~~~~~~
        ax_report = fig.add_subplot(gs[2, 1])
        relatorio_formatado = gerar_relatorio_formatado(nome_input, chapa_input, media_presenca_semana, percentuais_presenca, periodo_label_completo)
        ax_report.text(0, 1.058, relatorio_formatado, fontsize=20, ha='left', va='top', wrap=True, usetex=False)
        ax_report.axis('off')

        semanas_baixa = [
            sem
            for sem, qtd in dias_presenca_por_semana.items()
            if (0.0 if pd.isna(qtd) else float(qtd)) < float(min_presencial_exigido(sem))
        ]
        tabela_heatmap_baixa = tabela_heatmap[
            tabela_heatmap.index.str.split(r" \|").str[0].isin(semanas_baixa)
        ]

        if not tabela_heatmap_baixa.empty:
            left = 0.69; width = 0.30
            num_linhas = tabela_heatmap_baixa.shape[0]
            altura_base = 0.28; linhas_base = 36
            height = (num_linhas / linhas_base) * altura_base
            top = 0.410; bottom = top - height
            ax_heatmap3 = fig.add_axes([left, bottom, width, height])
            sns.heatmap(tabela_heatmap_baixa, cmap=ListedColormap(['#ffb3b3', '#f4cccc']),
                        linewidths=1, linecolor='gray', annot=True, annot_kws={'size': 14},
                        cbar=False, ax=ax_heatmap3)
            for y_idx, semana_label in enumerate(tabela_heatmap_baixa.index):
                semana_codigo = semana_label.split(" |")[0].replace(" ", "-")
                if semana_codigo in dias_presenca_por_semana.index:
                    qtd_presenca = dias_presenca_por_semana.loc[semana_codigo]
                    cor_destaque = "#ffb3b3" if qtd_presenca == 0 else "#f4cccc"
                    for col_idx in range(tabela_heatmap_baixa.shape[1]):
                        ax_heatmap3.add_patch(
                            plt.Rectangle((col_idx, y_idx), 1, 1, facecolor=cor_destaque,
                                          edgecolor='gray', linewidth=2, zorder=1)
                        )
            ax_heatmap3.set_ylabel(''); ax_heatmap3.set_xlabel('')
            ax_heatmap3.set_xticklabels(ax_heatmap3.get_xticklabels(), fontsize=14)
            ax_heatmap3.set_yticklabels(ax_heatmap3.get_yticklabels(), fontsize=14, rotation=0)
        else:
            pass

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 6 - Heatmap TOTAL do colaborador (dias) ~~~~~~~~~~~~~~~~~~~~~
        ax_heatmap2 = fig.add_subplot(gs_heatmaps[1])

        # Fonte diária de presença
        df_chapa_data = dw_fetch_diarios([str(chapa_input)])[['Data']].copy()
        df_chapa_data['Data'] = pd.to_datetime(df_chapa_data['Data'], errors='coerce')
        df_chapa_data = df_chapa_data.dropna(subset=['Data'])

        if df_chapa_data.empty:
            ax_heatmap2.axis('off')
        else:
            # Dia da semana em PT (mantém PT se já estiver)
            _dias_pt = {
                'Monday':'Segunda','Tuesday':'Terça','Wednesday':'Quarta',
                'Thursday':'Quinta','Friday':'Sexta','Saturday':'Sábado','Sunday':'Domingo'
            }
            nomes_en = df_chapa_data['Data'].dt.day_name()
            df_chapa_data['Dia Semana'] = nomes_en.map(_dias_pt).fillna(nomes_en)

            # Contagem por dia da semana, na ordem desejada
            counts = (df_chapa_data['Dia Semana']
                    .value_counts()
                    .reindex(ordenacao_dias, fill_value=0)
                    .astype(int))

            # 1 linha (Total) x 7 colunas (dias)
            heatmap_data = pd.DataFrame(
                [counts.values.tolist()],
                columns=ordenacao_dias,
                index=['Total']
            )

            cmap_personalizado = ListedColormap(["#ffb3b3", "#f4cccc", "#e3dacd", "#dae5d1", "#d9ead3"])
            sns.heatmap(
                heatmap_data,
                annot=True, fmt='g',
                cmap=cmap_personalizado,
                linewidths=1, linecolor='gray',
                annot_kws={'color': 'black', 'size': 17},
                cbar=False, ax=ax_heatmap2
            )

            # Ticks centralizados nas células
            ax_heatmap2.set_xticks(np.arange(heatmap_data.shape[1]) + 0.5)
            ax_heatmap2.set_xticklabels(list(heatmap_data.columns), fontsize=20, rotation=0)

            ax_heatmap2.set_yticks(np.arange(heatmap_data.shape[0]) + 0.5)
            ax_heatmap2.set_yticklabels(list(heatmap_data.index), fontsize=20, rotation=0)

            ax_heatmap2.set_xlabel('')
            ax_heatmap2.set_ylabel('')
            ax_heatmap2.tick_params(axis='y', left=True)

        # Layout final
        plt.subplots_adjust(wspace=1.4)
        fig.tight_layout()
        images_base64 = fig_to_base64(fig)

        # Gera binário
        png_bytes = fig_to_bytes(fig, fmt="png")
        pdf_bytes = fig_to_bytes(fig, fmt="pdf")

        # Converte em strings base64 (isso o Dash aceita)
        png_b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        pdf_b64 = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode()

        conteudo = html.Div([
            html.Button("Voltar", id='botao-voltar', n_clicks=0, style={
                'color': 'Black', 'fontFamily': 'VW Text', 'fontWeight': 'bold', 'marginTop': '20px',
                'display': 'block', 'marginTop': '10px', 'marginLeft': '10px', 'marginRight': 'auto',
                'padding': '10px 20px', 'fontSize': '14px', 'backgroundColor': '#e0e0e0', 'border': 'none',
                'borderRadius': '5px', 'cursor': 'pointer', 'boxShadow': '0px 2px 6px rgba(0, 0, 0, 0.25)'}),

            # Botões de download
            html.Div([
                html.A("Baixar PNG", href=png_b64, download=f"relatorio_{chapa_input}.png",
                    style={"marginRight": "20px", "fontSize": "16px",
                            "padding": "8px 14px", "backgroundColor": "#e0e0e0",
                            "color": "Black", "fontFamily": "VW Text", "borderRadius": "6px",
                            "textDecoration": "none",}),
                html.A("Baixar PDF", href=pdf_b64, download=f"relatorio_{chapa_input}.pdf",
                    style={"fontSize": "16px", "padding": "8px 14px",
                            "backgroundColor": "#ff0000", "color": "white",
                            "fontFamily": "VW Text", "borderRadius": "6px",
                            "textDecoration": "none",}),
            ], style={"textAlign": "center", "marginTop": "10px"}),

            # Imagem inline
            html.Img(src=images_base64, style={
                'width': '100%', 'maxWidth': '1400px', 'marginTop': '20px', 'background': 'white',
                'display': 'block', 'marginLeft': 'auto', 'marginRight': 'auto'
            })
        ])

        # >>> devolvemos o conteúdo individual e escondemos a página geral
        return conteudo, {'display': 'block'}, {'display': 'none'}, no_update
