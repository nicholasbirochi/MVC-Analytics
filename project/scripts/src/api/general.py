"""general.py

Página geral: KPIs, filtros e navegação entre páginas.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations
from dash import Input, Output, State, callback_context, dcc, html
import pandas as pd
import plotly.graph_objects as go
import time

from ..core.repo_global import (
    df_semana_merged,
    df_df_ativos,
    df_df_desligados,
    df_datas,
    df_df_gptw,
    df_almoco,
    df_count_por_semana,
    dropdown_options,
    her,
)
from ..domain.filters import (
    aplicar_filtro_faixas,
    aplicar_filtro_por_area,
    carregar_media_colaboradores,
    filtrar_base,
    interpolar_cor_hex,
    slug,
)
from ..domain.periods import (
    LT_MONTHS, LT_MARKS,
    LT_C1_MIN, LT_C1_MAX, LT_C2_MIN, LT_C2_MAX,
    periodo_limites,
)
from ..domain.builders import (
    build_dataframe_diario_area,
    build_dataframe_almoco_area,
    cache_key,
    is_valid,
)
from ..domain.tenure import carregar_adm_dem_cache, obter_periodo_admissao, sobrepoe_periodo
from ..domain.exports import (
    fig_to_base64,
    fig_to_bytes,
    gerar_relatorio_formatado,
    calcular_percentual_presenca,
)
from ..domain.copresenca import calcular_ordem_heatmap
from ..ui.figures import (
    grafico_heatmap_encontros_men,
    grafico_heatmap_encontros_exec,
    figura_vazia_linha,
)
from ..ui.theme import aplicar_tema_pb


def _normalizar_faixas(faixas) -> list[str]:
    if not faixas:
        return []
    if isinstance(faixas, str):
        return [faixas]
    return [str(f) for f in faixas]


def _media_colaboradores(
    df_desligados,
    viajam,
    area_selecionada,
    subarea_selecionada,
    periodo_idx,
) -> pd.DataFrame:
    return carregar_media_colaboradores(
        df_desligados=df_desligados,
        viajam=viajam,
        area_selecionada=area_selecionada,
        subarea_selecionada=subarea_selecionada,
        periodo_idx=periodo_idx,
    )


def _media_ponderada(df: pd.DataFrame, cargo: str | None = None) -> float:
    if df is None or df.empty:
        return 0.0
    dff = df.copy()
    if cargo is not None and "Cargo" in dff.columns:
        dff = dff[dff["Cargo"] == cargo]
    if dff.empty:
        return 0.0
    dias_presenca = pd.to_numeric(dff["Dias Presenca"], errors="coerce").fillna(0).sum()
    dias_monitorados = pd.to_numeric(dff["Dias Monitorados"], errors="coerce").fillna(0).sum()
    if dias_monitorados <= 0:
        return 0.0
    return round(float(dias_presenca / dias_monitorados), 2)


def register(app):
    @app.callback(
        Output('resumo-container', 'style'),
        Output('toggle-resumo-btn', 'children'),
        Input('toggle-resumo-btn', 'n_clicks')
    )
    def toggle_lista_areas(n):
        aberto = (n or 0) % 2 == 1
        return ({'display': 'block'}, "▼") if aberto else ({'display': 'none'}, "►")

    @app.callback(
        Output('lista-pessoas-container', 'style'),
        Output('toggle-lista-btn', 'children'),
        Input('toggle-lista-btn', 'n_clicks')
    )
    def toggle_lista_pessoas(n):
        aberto = (n or 0) % 2 == 1
        return ({'display': 'block'}, "▼") if aberto else ({'display': 'none'}, "►")

    @app.callback(
        [
            # Subárea
            Output('dropdown-subarea', 'options'),
            Output('dropdown-subarea', 'style'),
            Output('dropdown-subarea', 'value'),

            # Slider período
            Output('periodo-slider', 'min'),
            Output('periodo-slider', 'max'),
            Output('periodo-slider', 'value'),

            # Stores + texto
            Output('area-selecionada', 'data'),
            Output('subarea-selecionada', 'data'),
            Output('periodo-indices', 'data'),
            Output('periodo-texto', 'children'),
        ],
        [
            Input('dropdown-area', 'value'),
            Input('cenario-toggle', 'value'),
            Input('periodo-slider', 'value'),
        ],
        State('dropdown-subarea', 'value')
    )
    def orquestrador(area, cenario, slider_val, sub_val_atual):
        # ------ Área/Subárea ------
        if not area or area == 'GERAL':
            sub_opts, sub_style, sub_val = [], {'display': 'none'}, None
        else:
            try:
                heranca = her[her['Área'] == area]['Heranca'].unique()
                subareas_df = her[
                    (her['Área'].str.startswith(area)) &
                    (her['Área'] != area) &
                    (her['Heranca'].isin(heranca))
                ]
                if subareas_df.empty:
                    sub_opts, sub_style, sub_val = [], {'display': 'none'}, None
                else:
                    sub_opts = [
                        {'label': f"{row['Área']} {row.get('Departamento','')}", 'value': row['Área']}
                        for _, row in subareas_df.iterrows()
                    ]
                    # preserva a seleção anterior se ainda existir nas opções
                    valores = {o['value'] for o in sub_opts}
                    sub_val = sub_val_atual if sub_val_atual in valores else None
                    sub_style = {'width': '300px', 'marginTop': '10px', 'display': 'block'}
            except Exception:
                sub_opts, sub_style, sub_val = [], {'display': 'none'}, None

        # ------ Travar período pelo cenário ------
        if cenario == 'c1':
            min_i, max_i = LT_C1_MIN, LT_C1_MAX
        else:
            min_i, max_i = LT_C2_MIN, LT_C2_MAX

        v0, v1 = (slider_val if slider_val else [min_i, max_i])
        v0 = min(max(v0, min_i), max_i)
        v1 = min(max(v1, min_i), max_i)
        if v0 > v1:
            v0, v1 = min_i, max_i
        slider_min, slider_max, slider_out = min_i, max_i, [v0, v1]

        # ------ Texto do período (com fallback de locale) ------
        def fmt_mes_ano(dt: pd.Timestamp) -> str:
            try:
                return f"{dt.month_name(locale='pt_BR').capitalize()}/{dt.year}"
            except Exception:
                return dt.strftime("%b/%Y").capitalize()

        i0, i1 = slider_out
        d0 = pd.Timestamp(LT_MONTHS[i0])
        d1 = (pd.Timestamp(LT_MONTHS[i1]) + pd.offsets.MonthEnd(1))
        periodo_txt = f"Período selecionado: {fmt_mes_ano(d0)} a {fmt_mes_ano(d1)}"

        # ------ Stores ------
        area_store = area
        subarea_store = sub_val
        periodo_store = [i0, i1]

        return (
            sub_opts, sub_style, sub_val,
            slider_min, slider_max, slider_out,
            area_store, subarea_store, periodo_store, periodo_txt
        )

    @app.callback(
        Output('faixa-selecionada', 'data'),
        Output('ultimo-clique', 'data'),
        Input('grafico-heatmap', 'clickData'),
        Input('botao-resetar', 'n_clicks'),
        State('faixa-selecionada', 'data'),
        State('ultimo-clique', 'data'),
        prevent_initial_call=True
    )
    def atualizar_faixa(clickData, n_reset, faixa_atual, ultimo_clique):
        ctx = callback_context
        trigger = ctx.triggered_id

        faixa_atual = faixa_atual or []
        ultimo_clique = ultimo_clique or {'faixa': None, 'timestamp': 0}

        if trigger == 'grafico-heatmap' and clickData:
            faixa = clickData['points'][0]['x']
            nova_lista = [f for f in faixa_atual if f != faixa] if faixa in faixa_atual else faixa_atual + [faixa]
            return nova_lista, {'faixa': faixa, 'timestamp': time.time()}

        if trigger == 'botao-resetar':
            return [], {'faixa': None, 'timestamp': 0}

        return faixa_atual, ultimo_clique

    @app.callback(
        Output('tabela-detalhada-colaboradores', 'children'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('dropdown-chapa', 'value'),
        Input('faixa-selecionada', 'data'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data')
    )
    def atualizar_tabela(df_desligados, viajam, chapa_selecionada, faixas, area_selecionada, subarea_selecionada, periodo_idx):
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_colab = media_df[
            ["Área", "Departamento", "Cadastro", "Nome", "Cargo Especifico", "Média Presença"]
        ].copy()
        media_colab.columns = ["Área", "Departamento", "Chapa", "Nome", "Cargo", "Média Dia"]
        media_colab['Média Dia'] = media_colab['Média Dia'].round(2)

        if chapa_selecionada:
            media_colab = media_colab[media_colab['Chapa'].astype(str) == str(chapa_selecionada)]

        media_colab = aplicar_filtro_faixas(media_colab, 'Média Dia', faixas)
        media_colab['Média %'] = (((media_colab['Média Dia'] / 2) * 100) - 100).round(2)
        media_colab = media_colab.sort_values(by=['Área', 'Média %'], ascending=True)
        media_colab['Média %'] = media_colab['Média %'].astype(str) + ' %'

        tabela = html.Div([
            html.Table([
                html.Thead([
                    html.Tr([
                        html.Th(col, style={
                            'textAlign': 'left',
                            'backgroundColor': '#f0f0f0',
                            'padding': '10px',
                            'fontWeight': 'bold',
                            'borderBottom': '2px solid #ccc',
                            'borderRight': '1px solid #ccc'
                        }) for col in media_colab.columns
                    ])
                ]),
                html.Tbody([
                    html.Tr([
                        html.Td(
                            dcc.Link(str(valor), href=f"/pessoa/{linha[2]}", style={
                                'display': 'block',
                                'width': '100%',
                                'height': '100%',
                                'color': (
                                    'green' if (
                                        (isinstance(linha[5], (int, float)) and linha[5] >= 2) or
                                        (isinstance(linha[6], str) and '%' in linha[6] and float(linha[6].replace('%', '').strip()) >= 0)
                                    ) else 'red'
                                ),
                                'textDecoration': 'none',
                            }),
                            style={
                                'textAlign': 'left',
                                'padding': '8px',
                                'borderBottom': '1px solid #eee',
                                'borderRight': '1px solid #eee' if i < len(media_colab.columns) - 1 else 'none',
                                'backgroundColor': 'white'
                            }
                        ) for i, valor in enumerate(linha)
                    ]) for linha in media_colab.values
                ])
            ], style={
                'borderCollapse': 'separate',
                'borderSpacing': '0',
                'width': '100%',
                'fontSize': '15px',
                'boxShadow': '0 4px 12px rgba(0, 0, 0, 0.05)',
                'borderRadius': '12px',
                'overflow': 'hidden'
            })
        ])

        return tabela

    @app.callback(
        Output('dropdown-chapa', 'options'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('faixa-selecionada', 'data'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data')
    )
    def atualizar_opcoes_chapa(df_desligados, viajam, faixas, area_selecionada, subarea_selecionada, periodo_idx):
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_presenca = media_df[['Cadastro', 'Nome', 'Média Presença']].copy()
        media_presenca.columns = ['Chapa', 'Nome', 'Média']
        media_presenca = aplicar_filtro_faixas(media_presenca, 'Média', faixas)
        media_presenca = media_presenca.sort_values(by='Nome')
        opcoes = [{'label': f"{row['Chapa']} - {row['Nome']}", 'value': str(row['Chapa'])} for _, row in media_presenca.iterrows()]

        return opcoes

    @app.callback(
        Output('grafico-heatmap', 'figure'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('faixa-selecionada', 'data'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data')
    )
    def atualizar_heatmap(df_desligados, viajam, faixas, area_selecionada, subarea_selecionada, periodo_idx):
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_presenca_detalhada = media_df[['Cadastro', 'Média Presença']].copy()

        media_por_pessoa = media_presenca_detalhada[['Cadastro', 'Média Presença']].copy()
        media_por_pessoa['Média Presença'] = media_por_pessoa['Média Presença'].clip(lower=0, upper=7)

        bins = list(range(0, 8))
        labels_bins = [f"{i} a {i+1}" for i in range(7)]

        media_por_pessoa['Faixa'] = pd.cut(
            media_por_pessoa['Média Presença'],
            bins=bins,
            labels=labels_bins,
            right=False,
            include_lowest=True
        )

        if faixas:
            dados_faixa = media_por_pessoa[media_por_pessoa['Faixa'].isin(faixas)]
        else:
            dados_faixa = media_por_pessoa.copy()

        contagem_faixa = dados_faixa['Faixa'].value_counts().reindex(labels_bins, fill_value=0)
        x_faixas = contagem_faixa.index.tolist()
        y_faixas = contagem_faixa.values.tolist()

        num_faixas = max(1, len(x_faixas))
        colorscale = [None] * num_faixas

        quant_vermelho, indices_vermelho = [], []
        quant_amarelo, indices_amarelo = [], []
        quant_verde, indices_verde = [], []

        for i, faixa in enumerate(x_faixas):
            fmin = int(faixa.split(" ")[0])
            qtd = y_faixas[i]
            if fmin < 2:
                quant_vermelho.append(qtd)
                indices_vermelho.append(i)
            elif fmin > 4:
                quant_amarelo.append(qtd)
                indices_amarelo.append(i)
            else:
                quant_verde.append(qtd)
                indices_verde.append(i)

        min_verm, max_verm = (min(quant_vermelho), max(quant_vermelho)) if quant_vermelho else (0, 1)
        min_am, max_am = (min(quant_amarelo), max(quant_amarelo)) if quant_amarelo else (0, 1)
        min_vd, max_vd = (min(quant_verde), max(quant_verde)) if quant_verde else (0, 1)

        for idx in indices_vermelho:
            qtd = y_faixas[idx]
            t = (qtd - min_verm) / (max_verm - min_verm) if max_verm > min_verm else 0
            pos = idx / (num_faixas - 1) if num_faixas > 1 else 0
            colorscale[idx] = [pos, interpolar_cor_hex("#fc9898", "#ef6464", t)]

        for idx in indices_amarelo:
            qtd = y_faixas[idx]
            t = (qtd - min_am) / (max_am - min_am) if max_am > min_am else 0
            pos = idx / (num_faixas - 1) if num_faixas > 1 else 0
            colorscale[idx] = [pos, interpolar_cor_hex("#fff9a9", "#ffef09", t)]

        for idx in indices_verde:
            qtd = y_faixas[idx]
            t = (qtd - min_vd) / (max_vd - min_vd) if max_vd > min_vd else 0
            pos = idx / (num_faixas - 1) if num_faixas > 1 else 0
            colorscale[idx] = [pos, interpolar_cor_hex("#9effd0", "#3fbe81", t)]

        for i in range(num_faixas):
            if colorscale[i] is None:
                pos = i / (num_faixas - 1) if num_faixas > 1 else 0
                colorscale[i] = [pos, "#cccccc"]

        fig_heat = go.Figure(data=go.Heatmap(
            z=[list(range(num_faixas))],
            x=x_faixas,
            y=["Distribuição"],
            colorscale=colorscale,
            hovertemplate="Faixa: %{x}<br>Qtd Pessoas: %{customdata}<extra></extra>",
            customdata=[y_faixas] if y_faixas else [[]],
            showscale=False
        ))

        annotations = [
            dict(x=x_faixas[i], y="Distribuição", text=str(val), showarrow=False,
                 font=dict(color="black", size=15, family="VW Text"),
                 xanchor="center", yanchor="middle")
            for i, val in enumerate(y_faixas)
        ]

        fig_heat.update_layout(
            title={'text': "Distribuição de Colaboradores por Faixa", 'font': {'family': 'VW Text', 'color': '#000000', 'size': 24}},
            xaxis_title="Faixa de Média (dias/semana)",
            yaxis_title="",
            xaxis=dict(type='category'),
            yaxis=dict(showticklabels=False),
            height=250,
            showlegend=False,
            annotations=annotations
        )

        return fig_heat

    @app.callback(
        Output('grafico-dispersao', 'figure'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('faixa-selecionada', 'data'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data')
    )
    def atualizar_dispersao(df_desligados, viajam, faixas, area_selecionada, subarea_selecionada, periodo_idx):
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_presenca_detalhada = media_df[['Cadastro', 'Média Presença']].copy()

        media_presenca_detalhada = aplicar_filtro_faixas(media_presenca_detalhada, 'Média Presença', faixas)
        if media_presenca_detalhada.empty:
            return figura_vazia_linha("Sem dados para o período e filtros selecionados.")
        media_presenca_detalhada['Média Presença Arred'] = media_presenca_detalhada['Média Presença'].round(1)

        dados_disp = media_presenca_detalhada.groupby('Média Presença Arred')['Cadastro'].count().reset_index()
        dados_disp.columns = ['Média Presença', 'Qtd Pessoas']
        if dados_disp.empty:
            return figura_vazia_linha("Sem dados para montar a dispersão no período selecionado.")

        fig_dispersao = go.Figure()
        fig_dispersao.add_trace(go.Scatter(
            x=dados_disp['Média Presença'],
            y=dados_disp['Qtd Pessoas'],
            mode='markers+text',
            marker=dict(size=12, color="#0003b4"),
            hovertemplate="Qtd Pessoas: %{y}<br>Média Presença: %{x:.1f}<extra></extra>"
        ))

        fig_dispersao.update_layout(
            title={'text': f"Dispersão Geral ({', '.join(faixas) if faixas else 'Todos'})", 'font': {'family': 'VW Text', 'color': '#000000', 'size': 24}},
            xaxis_title="Média de Presença Semanal",
            yaxis_title="Qtd de Pessoas",
            height=500
        )

        fig_dispersao = aplicar_tema_pb(fig_dispersao)
        return fig_dispersao

    @app.callback(
        Output('grafico-presenca-cargo', 'figure'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('faixa-selecionada', 'data'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data')
    )
    def atualizar_presenca_cargo(df_desligados, viajam, faixas, area_selecionada, subarea_selecionada, periodo_idx):
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_presenca_detalhada = media_df[['Cadastro', 'Média Presença', 'Cargo']].copy()
        media_presenca_detalhada = aplicar_filtro_faixas(media_presenca_detalhada, 'Média Presença', faixas)
        if media_presenca_detalhada.empty:
            return figura_vazia_linha("Sem dados para o período e filtros selecionados.")

        fig_cargo = go.Figure()
        for cod, nome, cor in [('E', 'Executivos', "#1574b3"), ('M', 'Mensalistas', '#7cc3e9'), ('H', 'Horistas', '#3fbe81')]:
            df_aux = media_presenca_detalhada[media_presenca_detalhada['Cargo'] == cod].copy()
            if df_aux.empty:
                continue
            df_aux['Média Presença Arred'] = df_aux['Média Presença'].round(1)
            df_cargo = df_aux.groupby('Média Presença Arred')['Cadastro'].count().reset_index()
            df_cargo.columns = ['Média Presença', 'Qtd Pessoas']
            fig_cargo.add_trace(go.Scatter(
                x=df_cargo['Média Presença'],
                y=df_cargo['Qtd Pessoas'],
                mode='markers+text',
                name=nome,
                marker=dict(size=12, color=cor),
                hovertemplate=(f"{nome}<br>Qtd Pessoas: %{{y}}<br>Média Presença: %{{x:.1f}}<extra></extra>")
            ))
        if not fig_cargo.data:
            return figura_vazia_linha("Sem dados por cargo para o período e filtros selecionados.")

        fig_cargo.update_layout(
            title={'text': f"Presença por Cargo ({', '.join(faixas) if faixas else 'Todos'})", 'font': {'family': 'VW Text', 'color': '#000000', 'size': 24}},
            xaxis_title="Média de Presença Semanal",
            yaxis_title="Qtd de Pessoas",
            height=500,
            legend=dict(x=1, y=0.84, orientation='v', xanchor='right', yanchor='bottom',
                        font=dict(size=12), bgcolor='#ffffff')
        )

        fig_cargo = aplicar_tema_pb(fig_cargo)
        return fig_cargo

    @app.callback(
        Output('grafico-boxplot', 'figure'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('faixa-selecionada', 'data'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data')
    )
    def atualizar_boxplot(df_desligados, viajam, faixas, area_selecionada, subarea_selecionada, periodo_idx):
        # Se nenhuma área específica foi selecionada, não carrega o gráfico
        if not area_selecionada or area_selecionada == "GERAL":
            # pode retornar um gráfico vazio ou simplesmente não atualizar
            return figura_vazia_linha("Selecione uma área no dropdown para visualizar o Boxplot.")
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        medias_individuais = media_df[['Cadastro', 'Nome', 'Área', 'Média Presença']].copy()
        medias_individuais.columns = ['Chapa', 'Nome', 'Área', 'Média Presença']
        medias_individuais['Média Presença'] = medias_individuais['Média Presença'].round(2)

        if area_selecionada and area_selecionada != 'GERAL':
            if subarea_selecionada:
                medias_individuais = medias_individuais[medias_individuais['Área'] == subarea_selecionada]
            else:
                medias_individuais = medias_individuais[medias_individuais['Área'].str.startswith(area_selecionada)]

        medias_individuais = aplicar_filtro_faixas(medias_individuais, 'Média Presença', faixas)
        if medias_individuais.empty:
            return figura_vazia_linha("Sem dados para montar o boxplot no período e filtros selecionados.")

        fig_boxplot = go.Figure()
        AZUL_LINHA = "#3299dd"
        AZUL_FILL = 'rgba(21,116,179,0.30)'
        VERM_LINHA = "#FF0000"
        VERM_FILL = 'rgba(211,47,47,0.30)'

        for area_nome, dados_area in medias_individuais.groupby('Área'):
            s = dados_area['Média Presença'].dropna()
            tem_abaixo = (s.min() < 2)
            cor_linha = VERM_LINHA if tem_abaixo else AZUL_LINHA
            cor_fill = VERM_FILL if tem_abaixo else AZUL_FILL

            if not s.empty:
                fig_boxplot.add_trace(go.Box(
                    y=s,
                    name=area_nome,
                    boxpoints='outliers',
                    line=dict(color=cor_linha, width=2),
                    marker=dict(color=cor_linha, size=4),
                    fillcolor=cor_fill,
                    hovertemplate=area_nome + "<br>Média: %{y:.2f}<extra></extra>"
                ))
        if not fig_boxplot.data:
            return figura_vazia_linha("Sem dados para montar o boxplot no período e filtros selecionados.")

        titulo_bp = f"Boxplot de Presença por Área ({', '.join(faixas) if faixas else 'Todos'})"
        fig_boxplot.update_layout(
            title={'text': titulo_bp, 'font': {'family': 'VW Text', 'size': 24}},
            yaxis_title="Média de Presença Semanal",
            xaxis=dict(
                title="",
                showline=True,
                zeroline=True,
                rangeslider=dict(
                    visible=True,
                    bgcolor="white",
                    bordercolor="black",
                    borderwidth=1
                )
            ),
            boxmode='group',
            height=600,
            shapes=[dict(
                type="line", xref="paper", yref="y", x0=0, x1=1, y0=2, y1=2,
                line=dict(color="#A10000", width=3, dash="solid")
            )]
        )

        fig_boxplot = aplicar_tema_pb(fig_boxplot, so_y_boxplot=True)
        return fig_boxplot

    @app.callback(
        Output('tabela-informacoes-colaboradores', 'children'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data')
    )
    def atualizar_info(df_desligados, viajam, area_selecionada, subarea_selecionada, periodo_idx):
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )

        total_colaboradores = media_df['Cadastro'].nunique() if 'Cadastro' in media_df.columns else 0
        total_mensalistas = media_df[media_df['Cargo'] == 'M']['Cadastro'].nunique() if 'Cargo' in media_df.columns else 0
        total_executivos = media_df[media_df['Cargo'] == 'E']['Cadastro'].nunique() if 'Cargo' in media_df.columns else 0
        total_horistas = media_df[media_df['Cargo'] == 'H']['Cadastro'].nunique() if 'Cargo' in media_df.columns else 0
        media_presenca_geral = _media_ponderada(media_df)
        media_presenca_mensalistas = _media_ponderada(media_df, cargo='M')
        media_presenca_executivos = _media_ponderada(media_df, cargo='E')
        media_presenca_horistas = _media_ponderada(media_df, cargo='H')

        def _to_number(value):
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            s = str(value).strip()
            if not s:
                return None
            if "," in s and "." in s:
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", ".")
            try:
                return float(s)
            except ValueError:
                return None

        def _sorted_rows_desc(items, formatter=lambda x: x):
            def _sort_key(item):
                num = _to_number(item[1])
                return (num is None, num if num is not None else 0)

            items_sorted = sorted(items, key=_sort_key, reverse=True)
            numericos = [item for item in items_sorted if _to_number(item[1]) is not None]
            nao_numericos = [item for item in items_sorted if _to_number(item[1]) is None]
            return [html.Tr([html.Td(label), html.Td(formatter(value))]) for label, value in numericos + nao_numericos]

        colab_items = [
            ("Total de Colaboradores:", total_colaboradores),
            ("Horistas:", total_horistas),
            ("Mensalistas:", total_mensalistas),
            ("Executivos:", total_executivos),
        ]
        presenca_items = [
            ("Total:", media_presenca_geral),
            ("Horistas:", media_presenca_horistas),
            ("Mensalistas:", media_presenca_mensalistas),
            ("Executivos:", media_presenca_executivos),
        ]

        rows = (
            _sorted_rows_desc(colab_items)
            + [
                html.Tr([html.Td(html.Br()), html.Td()]),
                html.Tr([html.Th("Média de Presença por Semana", colSpan=2)], style={'fontSize': '20px'}),
            ]
            + _sorted_rows_desc(
                presenca_items,
                formatter=lambda v: "0"
                if (isinstance(v, str) and v.strip().lower() == "nan")
                else (
                    lambda x: "0" if (x is None or x != x) else f"{x}"
                )(_to_number(v)),
            )
        )

        tabela_info = html.Table(
            [
                html.Thead([html.Tr([html.Th("Informações de Colaboradores", colSpan=2)], style={'fontSize': '20px'})]),
                html.Tbody(rows),
            ],
            style={'fontSize': '16px', 'width': '100%'},
        )

        return tabela_info

    @app.callback(
        Output('resumo-container', 'children'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('faixa-selecionada', 'data'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data')
    )
    def atualizar_resumo(df_desligados, viajam, faixas, area_selecionada, subarea_selecionada, periodo_idx):
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_colab_resumo = media_df[
            ['Área', 'Departamento', 'Cadastro', 'Nome', 'Cargo', 'Média Presença']
        ].copy()
        media_colab_resumo.columns = ['Área', 'Departamento', 'Chapa', 'Nome', 'Cargo', 'Média Dia']
        media_colab_resumo['Média Dia'] = media_colab_resumo['Média Dia'].round(2)

        resumo_area = media_colab_resumo.groupby(['Área', 'Departamento']).agg(
            Qtd_Pessoas=('Chapa', 'count'),
            Qtd_Mensalistas=('Cargo', lambda x: (x == 'M').sum()),
            Qtd_Executivos=('Cargo', lambda x: (x == 'E').sum()),
            Qtd_Horistas=('Cargo', lambda x: (x == 'H').sum()),
            Media_Dia=('Média Dia', 'mean')
        ).reset_index()
        resumo_area['Média Dia'] = resumo_area['Media_Dia'].round(2)
        resumo_area['Média %'] = ((resumo_area['Média Dia'] / 2) * 100 - 100).round(2)
        resumo_area = aplicar_filtro_faixas(resumo_area, 'Média Dia', faixas)

        def _td_link_area(texto, area, extra_style=None):
            base_style = {
                'display': 'block', 'width': '100%', 'height': '100%',
                'color': 'inherit', 'textDecoration': 'none', 'padding': '8px'
            }
            if extra_style:
                base_style.update(extra_style)
            return dcc.Link(str(texto), href=f"/area/{slug(area)}", style=base_style)

        def td_style(align='left', width='auto'):
            return {
                'borderBottom': '1px solid #eee',
                'borderRight': '1px solid #eee',
                'cursor': 'pointer',
                'textAlign': align,
                'width': width,
                'padding': '5px 10px'
            }

        def th_style(align='left', width='auto'):
            return {
                'padding': '10px 10px',
                'backgroundColor': '#f0f0f0',
                'textAlign': align,
                'fontWeight': 'bold',
                'borderBottom': '2px solid #ccc',
                'borderRight': '1px solid #ccc',
                'width': width
            }

        tabela_resumo_area = html.Div([
            html.Div(children=[
                html.Table([
                    html.Thead([
                        html.Tr([
                            html.Th('Área', style=th_style('left', '0%')),
                            html.Th('Departamento', style=th_style('left', '0%')),
                            html.Th('Executivos', style=th_style('left', '0%')),
                            html.Th('Mensalistas', style=th_style('left', '0%')),
                            html.Th('Horistas', style=th_style('left', '0%')),
                            html.Th('Total', style=th_style('left', '0%')),
                            html.Th('Média Dia', style=th_style('left', '0%')),
                            html.Th('Média %', style=th_style('left', '0%')),
                        ])
                    ]),
                    html.Tbody([
                        html.Tr([
                            html.Td(_td_link_area(row['Área'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(row['Departamento'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(row['Qtd_Executivos'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(row['Qtd_Mensalistas'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(row['Qtd_Horistas'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(row['Qtd_Pessoas'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(row['Média Dia'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(f"{row['Média %']} %", row['Área']),
                                    style=td_style('left', '0%')),
                        ],
                        style={'color': 'red'} if row['Média Dia'] < 2 else {'color': 'green'})
                        for _, row in resumo_area.iterrows()
                    ])
                ], style={
                    'borderCollapse': 'collapse',
                    'width': '100%',
                    'fontSize': '15px',
                    'boxShadow': '0 4px 12px rgba(0, 0, 0, 0.05)',
                    'borderRadius': '12px',
                    'overflow': 'hidden'
                })
            ])
        ])

        return tabela_resumo_area
