"""area.py

Callbacks e visões por Área/Departamento/Subárea.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations
`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

from dash import Input, Output, State, callback_context, dcc, html, no_update
import pandas as pd

from ..core.repo_global import (
    df_datas,
    df_df_ativos,
    df_semana_merged,
    df_almoco,
    her,
)
from ..domain.builders import (
    build_dataframe_diario_area,
    build_dataframe_almoco_area,
    cache_key,
    get_area,
    is_valid,
)
from ..domain.periods import (
    LT_MONTHS, LT_MARKS,
    LT_C1_MIN, LT_C1_MAX, LT_C2_MIN, LT_C2_MAX,
    LT_FIM_ABS, lt_idx_of,
    periodo_limites,
)
from ..domain.filters import slug
from ..ui.figures import (
    grafico_heatmap_encontros_men,
    grafico_heatmap_encontros_exec,
    grafico_pentagonos_rel_exec_multiplos,
    grafico_pentagonos_exec_exec_multiplos,
    _sanitize_object_columns,
)
from ..ui.gptw import mini_tabela_df_gptw
from ..ui.theme import ESTILO_EXIBIR, ESTILO_OCULTO, aplicar_tema_pb

estilo_exibir = ESTILO_EXIBIR
estilo_oculto = ESTILO_OCULTO


def areas_toggle_ui():
    """Toggle simples para alternar Teia (radar) e Heatmap."""
    return html.Div(
        [
            dcc.Store(id="areas_vis_state", data="heatmap"),
            html.Button(
                "Modo: Heatmap (detalhe)",
                id="areas_vis_btn",
                n_clicks=0,
                style={
                    "fontFamily": "VW Text",
                    "fontWeight": "bold",
                    "padding": "10px 16px",
                    "borderRadius": "20px",
                    "border": "1px solid #b0b0b0",
                    "backgroundColor": "#f2f2f2",
                    "cursor": "pointer",
                    "boxShadow": "0 2px 4px rgba(0,0,0,0.10)",
                },
            ),
        ],
        style={"display": "flex", "alignItems": "center", "gap": "14px"},
    )


def register(app):
    @app.callback(
        [
            # Subárea
            Output('dropdown-subarea-area', 'options'),
            Output('dropdown-subarea-area', 'value'),

            # Slider período
            Output('periodo-slider-area', 'min'),
            Output('periodo-slider-area', 'max'),
            Output('periodo-slider-area', 'value'),

            # Store do período + texto
            Output('periodo-indices-area', 'data'),
            Output('periodo-texto-area', 'children'),

            # Gráficos
            Output('grafico-area-heatmap-men', 'figure'),
            Output('grafico-area-heatmap-exec', 'figure'),
        ],
        [
            # Inputs
            Input('area-atual-area', 'data'),
            Input('dropdown-subarea-area', 'value'),
            Input('cenario-toggle-area', 'value'),
            Input('df_desligados-toggle-area', 'value'),
            Input('viajam-toggle-area', 'value'),
            Input('periodo-slider-area', 'value'),
            Input('url','search'),
            Input('areas_vis_state','data')
        ]
    )
    def callback_unificado(area_base, subarea_sel, cenario, df_desligados_area, viajam_area, slider_val_state, search, areas_vis_state):
        from urllib.parse import parse_qs
        qs = parse_qs((search or '').lstrip('?'))
        modo = (qs.get('modo', ['geral'])[0] or 'geral').lower()
        is_almoco = (modo == 'almoco')

        ctx = callback_context
        trig = (ctx.triggered_id or 'initial') if ctx else 'initial'

        # --- 1) limites baseados no cenário ---
        if   cenario == 'c1':
            min_i, max_i = LT_C1_MIN, LT_C1_MAX
        elif cenario == 'c2':
            min_i, max_i = LT_C2_MIN, LT_C2_MAX
        else:  # 'all'
            min_i = 0
            try:
                max_i = lt_idx_of(LT_FIM_ABS.year, LT_FIM_ABS.month)
            except Exception:
                max_i = len(LT_MONTHS) - 1

        # valor atual do slider, também “clampado”
        if slider_val_state:
            v0, v1 = slider_val_state
        else:
            v0, v1 = min_i, max_i
        v0 = min(max(v0, min_i), max_i)
        v1 = min(max(v1, min_i), max_i)
        if v0 > v1:
            v0, v1 = min_i, max_i

        slider_min_out, slider_max_out, slider_val_out = min_i, max_i, [v0, v1]

        # --- 3) período calculado corretamente (AGORA com texto!) ---
        # inicializa variáveis para evitar erro de escopo
        i0 = i1 = None

        if is_almoco:
            # 🔹 Calcula período real com base no df_almoco
            if 'df_almoco' in globals() and isinstance(df_almoco, pd.DataFrame) and not df_almoco.empty:
                datas_validas = pd.to_datetime(df_almoco['Data'], errors='coerce').dropna()
                if not datas_validas.empty:
                    dt_ini = datas_validas.min()
                    dt_fim = datas_validas.max()
                else:
                    # fallback caso a base esteja vazia
                    dt_ini = pd.Timestamp.today()
                    dt_fim = pd.Timestamp.today()
            else:
                # fallback total (sem df_almoco)
                dt_ini = pd.Timestamp.today()
                dt_fim = pd.Timestamp.today()
        else:
            # 🔹 Mantém lógica normal (usando o slider)
            i0, i1 = slider_val_out
            dt_ini, dt_fim = periodo_limites([i0, i1])

        # --- Criação do texto do período ---
        m0, y0 = dt_ini.month_name('pt_BR').capitalize(), dt_ini.year
        m1, y1 = dt_fim.month_name('pt_BR').capitalize(), dt_fim.year
        periodo = f"{m0}/{y0} a {m1}/{y1}"
        periodo_txt_out = periodo
        periodo_data_out = [i0, i1] if not is_almoco else None

        # -------------------- 2) SUBÁREA (options + manter seleção) -------------
        sub_opts_out = []
        sub_val_out = subarea_sel  # default: manter
        if not area_base:
            sub_opts_out, sub_val_out = [], None
        else:
            try:
                heranca = her[her['Área'] == area_base]['Heranca'].unique()
                subareas_df = her[
                    (her['Área'].str.startswith(area_base)) &
                    (her['Área'] != area_base) &
                    (her['Heranca'].isin(heranca))
                ]
                if subareas_df.empty:
                    sub_opts_out = []
                else:
                    sub_opts_out = [
                        {'label': f"{row['Área']} {row.get('Departamento','')}", 'value': row['Área']}
                        for _, row in subareas_df.iterrows()
                    ]
            except Exception:
                sub_opts_out = []

            # manter seleção se ainda válida
            if sub_val_out and not is_valid(sub_val_out, sub_opts_out):
                sub_val_out = None
            # se a área mudou, pode limpar a subárea inválida
            if trig == 'area-atual-area' and (not is_valid(sub_val_out, sub_opts_out)):
                sub_val_out = None

        # --- 3) DF FULL (recalcular só quando precisa) ---
        mudou_area_ou_sub = trig in ('area-atual-area', 'dropdown-subarea-area')
        mudou_periodo     = trig in ('periodo-slider-area', 'cenario-toggle-area')
        mudou_filtros     = trig in ('df_desligados-toggle-area', 'viajam-toggle-area')

        df_key = cache_key(area_base, sub_val_out, df_desligados_area, viajam_area, i0, i1)

        if not hasattr(callback_unificado, "_df_cache"):
            callback_unificado._df_cache = {}
        cache_map = callback_unificado._df_cache

        precisa_df = bool(area_base) and (mudou_area_ou_sub or mudou_periodo or mudou_filtros or (trig in ('initial', 'areas_vis_state')) or (df_key not in cache_map))

        if precisa_df:
            if is_almoco:
                df_full = build_dataframe_almoco_area(
                    area_base, sub_val_out, her, df_almoco, df_df_ativos, dt_ini=dt_ini, dt_fim=dt_fim
                )
            else:
                df_full = build_dataframe_diario_area(
                    area_base, sub_val_out, her, df_datas, df_df_ativos, dt_ini=dt_ini, dt_fim=dt_fim
                )

            # filtros opcionais (df_desligados/viajam) – mantenha como já estava, se fizer sentido para almoço
            if (df_desligados_area == 'right' and not df_full.empty and
                'Cadastro' in df_full.columns and 'Desligado' in getattr(globals().get('df_semana_merged', pd.DataFrame()), 'columns', [])):
                afast = df_semana_merged[['Cadastro','Desligado']].drop_duplicates()
                afast['Cadastro'] = afast['Cadastro'].astype(str)
                df_full = df_full.merge(afast, on='Cadastro', how='left')
                df_full = df_full[df_full['Desligado'] != 'Sim'].drop(columns=['Desligado'])

            if (viajam_area == 'right' and not df_full.empty and 'Cadastro' in df_full.columns):
                df_sm = globals().get('df_semana_merged', pd.DataFrame())
                viaja_col = None
                for c in ['Viaja','Viajando','Em Viagem','Viajam']:
                    if c in getattr(df_sm, 'columns', []): viaja_col = c; break
                if viaja_col is not None:
                    vj = df_sm[['Cadastro', viaja_col]].drop_duplicates()
                    vj['Cadastro'] = vj['Cadastro'].astype(str)
                    df_full = df_full.merge(vj, on='Cadastro', how='left')
                    df_full = df_full[df_full[viaja_col] != 'Sim'].drop(columns=[viaja_col])

            cache_map[df_key] = df_full
        else:
            df_full = cache_map.get(df_key, pd.DataFrame())

        # --- TÍTULO amigável por modo ---
        periodo = f"{m0}/{y0} a {m1}/{y1}"
        titulo_men = (f"Almoços e Saídas — Mensalistas e Horistas × Executivos ({periodo})"
                      if is_almoco else
                      f"Presença Percentual de Mensalistas e Horistas com os seus Executivos ({periodo})")
        titulo_exec = (f"Almoços e Saídas — Executivos × Executivos ({periodo})"
                       if is_almoco else
                       f"Presença Percentual entre Executivos ({periodo})")

        # --- Evita piscar o gráfico sem design ---
        fig_men_out = no_update
        fig_exec_out = no_update

        vis_mode = (areas_vis_state or "heatmap")
        if isinstance(vis_mode, str):
            vis_mode = vis_mode.lower()
        else:
            vis_mode = "heatmap"

        if precisa_df:
            if vis_mode == "network":
                try:
                    df_net = _sanitize_object_columns(df_full)
                    fig_men_full = grafico_pentagonos_rel_exec_multiplos(df_net, titulo_men, max_exec=999)
                    fig_exec_full = grafico_pentagonos_exec_exec_multiplos(
                        df_net, titulo_exec, max_exec=999
                    )
                except Exception:
                    fig_men_full = aplicar_tema_pb(
                        grafico_heatmap_encontros_men(df_full, titulo_men, validar_mesma_planta=True),
                        so_y_boxplot=False,
                        grade=True,
                    )
                    fig_exec_full = aplicar_tema_pb(
                        grafico_heatmap_encontros_exec(df_full, titulo_exec, validar_mesma_planta=True),
                        so_y_boxplot=False,
                        grade=False,
                        clean=True,
                    )
            else:
                fig_men_full = aplicar_tema_pb(
                    grafico_heatmap_encontros_men(df_full, titulo_men, validar_mesma_planta=True),
                    so_y_boxplot=False,
                    grade=True,
                )
                fig_exec_full = aplicar_tema_pb(
                    grafico_heatmap_encontros_exec(df_full, titulo_exec, validar_mesma_planta=True),
                    so_y_boxplot=False,
                    grade=False,
                    clean=True,
                )

            fig_men_full.update_layout(uirevision="area-vis-men")
            fig_exec_full.update_layout(uirevision="area-vis-exec")

            fig_men_out = fig_men_full
            fig_exec_out = fig_exec_full

        # retorna tudo normalmente
        return (
            sub_opts_out, sub_val_out,
            slider_min_out, slider_max_out, slider_val_out,
            periodo_data_out, periodo_txt_out,
            fig_men_out, fig_exec_out
        )

    @app.callback(
        Output('conteudo-analitico-area','children'),
        Output('conteudo-analitico-area','style'),
        Output('pagina-geral','style', allow_duplicate=True),
        Output('url','pathname', allow_duplicate=True),
        Input('url','pathname'),
        Input('botao-voltar-area','n_clicks'),
        Input('url','search')
    )
    def exibir_conteudo_area(pathname, n_clicks, search):
        # Ação de voltar
        if n_clicks and n_clicks > 0:
            return None, estilo_oculto, estilo_exibir, "/"

        # Rota inválida
        if not pathname or "/area/" not in pathname:
            return no_update, estilo_oculto, no_update, no_update

        # Área/subárea a partir do path
        area, subarea = get_area(pathname)
        if not area:
            return None, estilo_oculto, estilo_exibir, no_update

        # --- detectar modo pelo querystring (?modo=geral|almoco) ---
        from urllib.parse import parse_qs
        qs = parse_qs((search or '').lstrip('?'))
        modo = (qs.get('modo', ['geral'])[0] or 'geral').lower()
        is_almoco = (modo == 'almoco')

        # ======= CONSTRÓI O RELATÓRIO (FIGURAS INICIAIS) =======
        if is_almoco:
            df_full = build_dataframe_almoco_area(area, subarea, her, df_almoco, df_df_ativos)
        else:
            df_full = build_dataframe_diario_area(area, subarea, her, df_datas, df_df_ativos)

        fig_heatmap_men = None
        fig_heatmap_exec = None

        # ======= BARRA DE FILTROS (mesmo conteúdo, mas pode ficar oculta no modo almoço) =======
        filter_block_style = {
            'flex':'1','padding':'16px','boxSizing':'border-box','backgroundColor':"#e0e0e0",
            'borderRadius':'16px','margin':'14px','boxShadow':'0px 3px 6px rgba(0,0,0,0.1)',
            'display':'flex','flexWrap':'wrap','alignItems':'flex-start','gap':'24px'
        }
        if is_almoco:
            # Esconder completamente no modo almoço (mantém IDs e callbacks)
            filter_block_style['display'] = 'none'

        filtros_div = html.Div([
            # Desligados / Viajam
            html.Div([
                html.Div([
                    html.Label("Mostrar as pessoas desligadas?"),
                    dcc.RadioItems(
                        id='df_desligados-toggle-area',
                        options=[{'label': 'Sim', 'value': 'left'}, {'label': 'Não', 'value': 'right'}],
                        value='left',
                        labelStyle={'display': 'inline-block', 'marginRight': '10px'}
                    ),
                ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center'}),

                html.Div([
                    html.Label("Mostrar as áreas que viajam?"),
                    dcc.RadioItems(
                        id='viajam-toggle-area',
                        options=[{'label': 'Sim', 'value': 'left'}, {'label': 'Não', 'value': 'right'}],
                        value='left',
                        labelStyle={'display': 'inline-block', 'marginRight': '10px'}
                    ),
                ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center'}),
            ], style={'display':'flex','gap':'30px','alignItems':'center'}),

            # Cenário + RangeSlider
            html.Div([
                html.Div([
                    dcc.RadioItems(
                        id='cenario-toggle-area',
                        options=[
                            {'label': 'Tudo',                 'value': 'all'},
                            {'label': 'Jan/2024 a Abr/2025',  'value': 'c1'},
                            {'label': 'Mai/2025 em diante',   'value': 'c2'}
                        ],
                        value='all',
                        labelStyle={'display': 'inline-block'}
                    )
                ], style={'textAlign': 'center', 'marginBottom': '6px'}),

                dcc.RangeSlider(
                    id='periodo-slider-area',
                    min=0, max=len(LT_MONTHS)-1,
                    value=[0, len(LT_MONTHS)-1],
                    marks=LT_MARKS, allowCross=False, step=1, pushable=1
                )
            ], style={'marginLeft': '50px','flex':'0 0 560px'}),

            # Subárea local (dentro da mesma herança)
            html.Div([
                dcc.Dropdown(
                    id='dropdown-subarea-area',
                    options=[],
                    value=subarea,  # já entra com a subárea atual, se houver
                    placeholder='Selecione uma subárea',
                    clearable=True,
                    style={'width': '300px', 'marginTop': '10px'}
                ),
            ], style={'marginLeft':'auto'})
        ], style=filter_block_style)

        # ======= CONTEÚDO DA PÁGINA (com botões centrais abaixo do título) =======
        conteudo = html.Div([
            # Sequenciador de loading da aba Áreas
            dcc.Store(id='area-load-step', data=0),
            dcc.Interval(id='area-load-interval', interval=500, n_intervals=0, disabled=False, max_intervals=2),

            # ===================== CABEÇALHO =====================
            html.Div([

                # ---- Coluna da esquerda: Definição + Botão Voltar ----
                html.Div([
                    # Definição (badge explicativa)
                    html.Div(
                        [html.Span(
                            "O que essa página mostra?\n"
                            "Entradas no refeitório e saídas da planta durante o horário de almoço, "
                            "considerando diferenças de até 1 minuto para o refeitório e 3 minutos "
                            "para as saídas da fábrica, além de estar sendo analisado apenas os últimos 3 meses.",
                            style={
                                'fontFamily': 'VW Text',
                                'fontSize': '14px',
                                'fontWeight': 'bold',
                                'padding': '6px 20px',
                                'border': '1px solid #000',
                                'borderRadius': '6px',
                                'backgroundColor': '#fff',
                                'display': 'block',
                                'textAlign': 'justify',
                                'whiteSpace': 'pre-line',
                                'width': '400px',
                                'lineHeight': '1.3',  
                                'boxSizing': 'border-box'
                            }
                        )] if is_almoco else [],
                        id='definicao-site',
                        style={
                            'display': 'flex',
                            'justifyContent': 'center',
                            'alignItems': 'flex-start',
                            'width': '100%',
                            'margin': '0 auto',
                            'marginBottom': '8px'
                        }
                    ),

                    # Botão "Voltar"
                    html.Button(
                        "Voltar",
                        id='botao-voltar-area',
                        n_clicks=0,
                        style={
                            'color': 'Black',
                            'fontFamily': 'VW Text',
                            'fontWeight': 'bold',
                            'padding': '10px 16px',
                            'fontSize': '14px',
                            'backgroundColor': '#e0e0e0',
                            'border': 'none',
                            'borderRadius': '5px',
                            'cursor': 'pointer',
                            'boxShadow': '0px 2px 6px rgba(0,0,0,0.25)',
                            'width': 'auto',            # largura só o suficiente para o texto
                            'textAlign': 'center',
                            'alignSelf': 'flex-start',  # força alinhamento à esquerda
                            'transition': '0.2s ease'
                        }
                    )
                ],
                style={
                    'display': 'flex',
                    'flexDirection': 'column',
                    'alignItems': 'flex-start',     # alinha tudo à esquerda
                    'justifyContent': 'flex-start',
                    'flex': '0 0 260px',
                    'maxWidth': '30%',
                    'marginLeft': '14px',           # margem igual à da direita
                }),

                # ---- Título centralizado ----
                html.H2(
                    f"Análise Específica — {subarea or area}",
                    style={
                        'flex': '1',
                        'textAlign': 'center',
                        'margin': '0',
                        'fontFamily': 'VW Text',
                        'fontWeight': 'bold',
                        'fontSize': '22px',
                        'whiteSpace': 'nowrap',
                        'overflow': 'hidden',
                        'textOverflow': 'ellipsis'
                    }
                ),

                # ---- Mini-tabela à direita ----
                html.Div(
                    mini_tabela_df_gptw(subarea or area),
                    style={
                        'marginRight': '14px',
                        'flex': '0 0 260px',
                        'maxWidth': '30%'
                    }
                )
            ],
            style={
                'display': 'flex',
                'alignItems': 'flex-end',
                'justifyContent': 'space-between',
                'flexWrap': 'wrap',
                'gap': '12px',
                'margin': '14px',
                'position': 'relative'
            }),

            # ===================== BOTÕES CENTRAIS =====================
            html.Div([
                dcc.Link(
                    "Relacionamento Geral da Área",
                    href=f"/area/{slug(subarea or area)}?modo=geral",
                    style={
                        'fontFamily': 'VW Text',
                        'fontSize': '16px',
                        'fontWeight': 'bold',
                        'color': '#000000',
                        'textDecoration': 'none',
                        'padding': '8px 16px',
                        'border': '1px solid #000000',
                        'borderRadius': '6px',
                        'backgroundColor': "#e0e0e0",
                        'cursor': 'pointer',
                        'transition': '0.2s ease',
                        'textAlign': 'center'
                    }
                ),
                dcc.Link(
                    "Relacionamento do Almoço da Área",
                    href=f"/area/{slug(subarea or area)}?modo=almoco",
                    style={
                        'fontFamily': 'VW Text',
                        'fontSize': '16px',
                        'fontWeight': 'bold',
                        'color': '#000000',
                        'textDecoration': 'none',
                        'padding': '8px 16px',
                        'border': '1px solid #000000',
                        'borderRadius': '6px',
                        'backgroundColor': "#e0e0e0",
                        'cursor': 'pointer',
                        'transition': '0.2s ease',
                        'textAlign': 'center'
                    }
                )
            ],
            style={
                'display': 'flex',
                'justifyContent': 'center',
                'alignItems': 'center',
                'gap': '12px',
                'margin': '8px 0 14px',
                'flexWrap': 'wrap'
            }),

            html.Div(
                areas_toggle_ui(),
                style={'display': 'flex', 'justifyContent': 'center', 'margin': '4px 0 12px'}
            ),
            # ===================== FILTROS E GRÁFICOS =====================
            filtros_div,

            html.Div(
                id='periodo-texto-area',
                style={
                    'textAlign': 'center',
                'marginTop': '4px',
                'marginBottom': '14px'
            }
        ),

            dcc.Loading(
                id='loading-area-men',
                type='default',
                children=dcc.Graph(figure=fig_heatmap_men, id='grafico-area-heatmap-men', style={'height':'auto'})
            ),
            dcc.Loading(
                id='loading-area-exec',
                type='default',
                children=dcc.Graph(figure=fig_heatmap_exec, id='grafico-area-heatmap-exec', style={'height':'auto'})
            ),

            # ===================== STORES =====================
            dcc.Store(id='periodo-indices-area', data=[LT_C1_MIN, LT_C1_MAX]),
            dcc.Store(id='area-atual-area', data=area)

        ],
        style={
            'padding': '14px',
            'backgroundColor': 'white'
        })

        return conteudo, {'display':'block'}, {'display':'none'}, no_update

    @app.callback(
        Output('areas_vis_state', 'data'),
        Output('areas_vis_btn', 'children'),
        Input('areas_vis_btn', 'n_clicks'),
        State('areas_vis_state', 'data'),
        prevent_initial_call=False
    )
    def _toggle_areas_vis(n_clicks, current):
        current = (current or "heatmap").lower()
        if current == "teia":
            current = "network"
        next_state = current if (n_clicks or 0) == 0 else ("network" if current == "heatmap" else "heatmap")
        label = (
            "Modo: Heatmap (detalhe)" if next_state == "heatmap"
            else "Modo: Teia (rede)"
        )
        return next_state, label
