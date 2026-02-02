"""layout.py

Layout principal do app (Dash), containers e navegação.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations
from dash import html, dcc

from ..domain.periods import LT_MARKS, LT_C1_MIN, LT_C1_MAX, LT_C2_MIN, LT_C2_MAX, LT_MONTHS
from ..core.repo_global import dropdown_options


LAYOUT = html.Div([
    dcc.Location(id='url', refresh=False),

    # '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Geral ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''
    html.Div([
        html.Div(id='pagina-geral', children=[

            # ====== Título ======
            html.Div([
                html.H1([
                    "Relatório Presencial Geral de toda a Volkswagen (Mensalistas/Executivos)",
                    html.Br(),
                    html.Span(id='periodo-texto')
                ], style={'textAlign': 'center', 'flex': '1'})
            ], style={
                'display': 'flex',
                'justifyContent': 'flex-end',
                'alignItems': 'center',
                'marginBottom': '20px'
            }),

            # ================== BLOCO DE FILTROS ==================
            html.Div([
                html.Div([
                    # --- Bloco A: 2 RadioItems ---
                    html.Div([
                        html.Label("Mostrar as pessoas desligadas?"),
                        dcc.RadioItems(
                            id='df_desligados-toggle',
                            options=[
                                {'label': 'Sim', 'value': 'left'},
                                {'label': 'Não', 'value': 'right'}
                            ],
                            value='left',
                            labelStyle={'display': 'inline-block', 'marginRight': '10px'}
                        ),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center'}),

                    html.Div([
                        html.Label("Mostrar as áreas que viajam?"),
                        dcc.RadioItems(
                            id='viajam-toggle',
                            options=[
                                {'label': 'Sim', 'value': 'left'},
                                {'label': 'Não', 'value': 'right'}
                            ],
                            value='left',
                            labelStyle={'display': 'inline-block', 'marginRight': '10px'}
                        ),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center'}),
                ], style={'display': 'flex', 'gap': '30px', 'alignItems': 'center'}),

                # --- Bloco B: Linha do tempo ---
                html.Div([
                    html.Div([
                        dcc.RadioItems(
                            id='cenario-toggle',
                            options=[
                                {'label': 'Jan/2024 a Abr/2025', 'value': 'c1'},
                                {'label': 'Mai/2025 em diante', 'value': 'c2'}
                            ],
                            value='c1',
                            labelStyle={'display': 'inline-block'}
                        )
                    ], style={'textAlign': 'center', 'marginBottom': '6px'}),

                    dcc.RangeSlider(
                        id='periodo-slider',
                        min=0,
                        max=len(LT_MONTHS)-1,
                        value=[LT_C1_MIN, LT_C1_MAX],
                        marks=LT_MARKS,
                        allowCross=False,
                        step=1,
                        pushable=1
                    )
                ], style={'marginLeft': '50px', 'flex': '0 0 560px'}),

                # --- Bloco C: Dropdown ---
                html.Div([
                    dcc.Dropdown(
                        id='dropdown-area',
                        options=dropdown_options,
                        value='GERAL',
                        clearable=False,
                        style={'width': '300px'}
                    ),
                    html.Div([
                        dcc.Dropdown(
                            id='dropdown-subarea',
                            options=[],
                            value=None,
                            placeholder='Selecione uma subárea',
                            clearable=True,
                            style={'width': '300px', 'marginTop': '10px', 'display': 'none'}
                        )
                    ], id='subarea-container')
                ], style={'marginLeft': 'auto'})
            ], style={
                'flex': '1',
                'padding': '20px',
                'boxSizing': 'border-box',
                'backgroundColor': "#e0e0e0",
                'borderRadius': '20px',
                'height': 'fit-content',
                'marginTop': '30px',
                'marginLeft': '10px',
                'marginRight': '10px',
                'boxShadow': '0px 3px 6px rgba(0,0,0,0.1)',
                'display': 'flex',
                'flexWrap': 'wrap',
                'alignItems': 'flex-start',
                'marginBottom': '30px'
            }),
            # ======================================================

            # ====== Heatmap + Info ======
            html.Div([
                html.Div([
                    dcc.Loading(
                        dcc.Graph(id='grafico-heatmap', config={'displayModeBar': False},
                                    style={'height': '250px', 'width': '100%'})
                    ),
                    html.Button(
                        "↻",
                        id="botao-resetar",
                        style={
                            'fontFamily': 'VW Text',
                            'position': 'absolute',
                            'top': '30px',
                            'right': '20px',
                            'zIndex': '1',
                            'backgroundColor': '#e0e0e0',
                            'border': '1px solid #ccc',
                            'padding': '6px 12px',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold',
                            'size': '18px'
                        }
                    )
                ], style={
                    'position': 'relative',
                    'flex': '1',
                    'minWidth': '400px',
                    'maxWidth': '100%',
                }),

                html.Div(id='tabela-informacoes-colaboradores', style={
                    'flex': '1',
                    'minWidth': '280px',
                    'maxWidth': '400px',
                    'padding': '20px',
                    'boxSizing': 'border-box',
                    'backgroundColor': "#e0e0e0",
                    'borderRadius': '20px',
                    'height': 'fit-content',
                    'marginTop': '30px',
                    'marginLeft': '240px',
                    'marginRight': '130px',
                    'boxShadow': '0px 3px 6px rgba(0,0,0,0.1)'
                })
            ], style={
                'display': 'flex',
                'flexWrap': 'wrap',
                'alignItems': 'flex-start',
                'marginBottom': '30px'
            }),

            # ====== Dispersão + Cargo ======
            html.Div([
                html.Div([
                    dcc.Loading(dcc.Graph(id='grafico-dispersao',
                                            style={'height': '550px', 'width': '100%'}))
                ], style={'flex': '1', 'marginRight': '20px'}),
                html.Div([
                    dcc.Loading(dcc.Graph(id='grafico-presenca-cargo',
                                            style={'height': '550px', 'width': '100%'}))
                ], style={'flex': '1'})
            ], style={'display': 'flex', 'flexWrap': 'wrap'}),

            # ====== Boxplot ======
            html.Div([
                html.Div([
                    dcc.Loading(dcc.Graph(id='grafico-boxplot',
                                            style={'height': '600px', 'width': '100%'}))
                ], style={'flex': '2'})
            ], style={'display': 'flex', 'flexWrap': 'wrap'}),

            # ====== Resumo ======
            html.Div([
                # Botão de toggle ►
                html.Button("►", id="toggle-resumo-btn", n_clicks=0, style={
                    'fontSize': '18px',
                    'marginLeft': '10px',
                    'background': 'none',
                    'border': 'none',
                    'cursor': 'pointer',
                    'verticalAlign': 'middle'
                }),

                # Título principal
                html.Span("Resumo Específico por Área (Mensalistas/Executivos)", style={
                    'fontWeight': 'bold',
                    'fontSize': '18px',
                    'color': '#000000',
                    'flex': '1',
                    'textAlign': 'left'
                }),

                # Novo botão/link para a página de relacionamento
                dcc.Link(
                    "Relacionamento entre Colaboradores →",
                    href="/relacionamento",
                    style={
                        'fontFamily': 'VW Text',
                        'fontSize': '15px',
                        'fontWeight': 'bold',
                        'color': '#000000',
                        'textDecoration': 'none',
                        'marginLeft': 'auto',
                        'marginRight': '20px',
                        'padding': '6px 12px',
                        'border': '1px solid #000000',
                        'borderRadius': '6px',
                        'backgroundColor': "#e0e0e0",
                        'boxSizing': 'border-box',
                        'cursor': 'pointer'
                    }
                )
            ], style={
                'display': 'flex',
                'alignItems': 'center',
                'justifyContent': 'space-between',
                'marginBottom': '8px'
            }),

            html.Div(id='resumo-container', style={'marginBottom': '20px', 'display': 'none'}),

            # ====== Lista Pessoas ======
            html.Div([
                html.Div([
                    html.Button(
                        "►", id="toggle-lista-btn", n_clicks=0,
                        style={
                            'fontSize': '18px',
                            'marginLeft': '10px',
                            'background': 'none',
                            'border': 'none',
                            'cursor': 'pointer',
                            'verticalAlign': 'middle'
                        }
                    ),
                    html.Span("Presença dos Colaboradores", style={
                        'fontWeight': 'bold',
                        'fontSize': '18px',
                        'color': '#000000',
                        'flex': '1',
                        'textAlign': 'left'
                    })
                ], style={'marginBottom': '8px'}),

                html.Div(
                    id='lista-pessoas-container',
                    children=[
                        dcc.Dropdown(
                            id='dropdown-chapa',
                            options=[],
                            value=None,
                            placeholder='Buscar colaborador pela chapa...',
                            clearable=True,
                            searchable=True,
                            style={'width': '300px', 'marginTop': '10px', 'marginBottom': '10px'}
                        ),
                        html.Div(id='tabela-detalhada-colaboradores')
                    ],
                    style={'display': 'none'}
                )
            ],
            style={'marginTop': '15px'}),

            # ====== Stores ======
            dcc.Store(id='faixa-selecionada', data=None),
            dcc.Store(id='area-selecionada', data='GERAL'),
            dcc.Store(id='subarea-selecionada', data=None),
            dcc.Store(id='ultimo-clique', data={'faixa': None, 'timestamp': 0}),
            dcc.Store(id='periodo-indices', data=[LT_C1_MIN, LT_C1_MAX])
        ], style={'padding': '20px', 'backgroundColor': 'white'})
    ]),

    # '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Individual ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''
    dcc.Loading(
        id="loading-individual",
        type="circle",
        fullscreen=True,
        children=html.Div(
            id='conteudo-individual',
            children=[
                html.Button(
                    "Voltar",
                    id='botao-voltar',
                    n_clicks=0,
                    style={
                        'color': 'Black',
                        'fontFamily': 'VW Text',
                        'fontWeight': 'bold',
                        'marginTop': '20px',
                        'display': 'block',
                        'marginLeft': '10px',
                        'marginRight': 'auto',
                        'padding': '10px 20px',
                        'fontSize': '14px',
                        'backgroundColor': '#e0e0e0',
                        'border': 'none',
                        'borderRadius': '5px',
                        'cursor': 'pointer',
                        'boxShadow': '0px 2px 6px rgba(0, 0, 0, 0.25)'
                    }
                )
            ],
            style={'display': 'none', 'backgroundColor': 'white'}
        )
    ), 
    
    # '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Áreas ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''
    html.Div(
        id='conteudo-analitico-area',
        children=[
            html.Button(
                "Voltar",
                id='botao-voltar-area',
                n_clicks=0,
                style={
                    'color':'Black','fontFamily':'VW Text','fontWeight':'bold',
                    'marginTop':'20px','display':'block','marginLeft':'10px',
                    'marginRight':'auto','padding':'10px 20px','fontSize':'14px',
                    'backgroundColor':'#e0e0e0','border':'none','borderRadius':'5px',
                    'cursor':'pointer','boxShadow':'0px 2px 6px rgba(0,0,0,0.25)'
                }
            )
        ],
        style={'display':'none','backgroundColor':'white'}
    ),

    # '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Relacionamento ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''
    html.Div(
        id='conteudo-relacionamento',
        children=[
            html.Button(
                "Voltar",
                id='botao-voltar-relacionamento',
                n_clicks=0,
                style={
                    'color':'Black','fontFamily':'VW Text','fontWeight':'bold',
                    'marginTop':'20px','display':'block','marginLeft':'10px',
                    'marginRight':'auto','padding':'10px 20px','fontSize':'14px',
                    'backgroundColor':'#e0e0e0','border':'none','borderRadius':'5px',
                    'cursor':'pointer','boxShadow':'0px 2px 6px rgba(0,0,0,0.25)'
                }
            )
        ],
        style={'display':'none','backgroundColor':'white'}
    )
])