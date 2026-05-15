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
from urllib.parse import quote

from dash import html, dcc

from ..domain.periods import LT_MARKS, LT_C1_MIN, LT_C1_MAX, LT_C2_MIN, LT_C2_MAX, LT_MONTHS
from ..core.repo_global import dropdown_options
from .theme import VW_PLOTLY_FONT


def _flag_uri(svg: str) -> str:
    """Retorna um SVG inline seguro para usar como imagem no Dash."""
    return f"data:image/svg+xml;charset=utf-8,{quote(svg, safe='')}"


LANGUAGES = (
    (
        "pt",
        "BR",
        "Brasil",
        """
        <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
          <rect width="64" height="64" fill="#009b3a"/>
          <polygon points="32,9 55,32 32,55 9,32" fill="#ffdf00"/>
          <circle cx="32" cy="32" r="12" fill="#002776"/>
          <path d="M19 31c8-5 18-5 26 0" fill="none" stroke="#ffffff"
                stroke-width="3.2" stroke-linecap="round"/>
        </svg>
        """,
    ),
    (
        "en",
        "US",
        "United States",
        """
        <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
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
            <circle cx="5" cy="5" r="1.2"/><circle cx="12" cy="5" r="1.2"/>
            <circle cx="19" cy="5" r="1.2"/><circle cx="26" cy="5" r="1.2"/>
            <circle cx="8.5" cy="10" r="1.2"/><circle cx="15.5" cy="10" r="1.2"/>
            <circle cx="22.5" cy="10" r="1.2"/>
            <circle cx="5" cy="15" r="1.2"/><circle cx="12" cy="15" r="1.2"/>
            <circle cx="19" cy="15" r="1.2"/><circle cx="26" cy="15" r="1.2"/>
            <circle cx="8.5" cy="20" r="1.2"/><circle cx="15.5" cy="20" r="1.2"/>
            <circle cx="22.5" cy="20" r="1.2"/>
            <circle cx="5" cy="25" r="1.2"/><circle cx="12" cy="25" r="1.2"/>
            <circle cx="19" cy="25" r="1.2"/><circle cx="26" cy="25" r="1.2"/>
          </g>
        </svg>
        """,
    ),
    (
        "de",
        "DE",
        "Germany",
        """
        <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
          <rect width="64" height="21.34" y="0" fill="#000000"/>
          <rect width="64" height="21.33" y="21.34" fill="#dd0000"/>
          <rect width="64" height="21.33" y="42.67" fill="#ffce00"/>
        </svg>
        """,
    ),
    (
        "es",
        "ES",
        "Spain",
        """
        <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
          <rect width="64" height="64" fill="#f1bf00"/>
          <rect width="64" height="16" y="0" fill="#aa151b"/>
          <rect width="64" height="16" y="48" fill="#aa151b"/>
        </svg>
        """,
    ),
    (
        "pl",
        "PL",
        "Poland",
        """
        <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
          <rect width="64" height="64" fill="#ffffff"/>
          <rect width="64" height="32" y="32" fill="#dc143c"/>
        </svg>
        """,
    ),
    (
        "sk",
        "SK",
        "Slovakia",
        """
        <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
          <rect width="64" height="64" fill="#ee1c25"/>
          <rect width="64" height="42.67" y="0" fill="#0b4ea2"/>
          <rect width="64" height="21.33" y="0" fill="#ffffff"/>
        </svg>
        """,
    ),
    (
        "zh",
        "CN",
        "China",
        """
        <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
          <rect width="64" height="64" fill="#de2910"/>
          <polygon points="14,10 16.8,18 25.2,18 18.4,22.8 21,31 14,25.9
                           7,31 9.6,22.8 2.8,18 11.2,18" fill="#ffde00"/>
          <circle cx="28" cy="12" r="2.3" fill="#ffde00"/>
          <circle cx="32" cy="19" r="2.3" fill="#ffde00"/>
          <circle cx="31" cy="28" r="2.3" fill="#ffde00"/>
          <circle cx="24" cy="33" r="2.3" fill="#ffde00"/>
        </svg>
        """,
    ),
    (
        "hi",
        "IN",
        "India",
        """
        <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
          <rect width="64" height="64" fill="#138808"/>
          <rect width="64" height="42.67" y="0" fill="#ffffff"/>
          <rect width="64" height="21.33" y="0" fill="#ff9933"/>
          <circle cx="32" cy="32" r="7.5" fill="none" stroke="#1a4ba0"
                  stroke-width="2.4"/>
        </svg>
        """,
    ),
)


LANGUAGES = LANGUAGES[:]


def language_selector() -> html.Div:
    """Componente visual de seleção de idioma no padrão do cabeçalho do MVC."""
    buttons = []
    for idx, (code, label, title, svg) in enumerate(LANGUAGES):
        active = code == "pt"
        buttons.append(
            html.Button(
                [
                    html.Span(
                        html.Img(src=_flag_uri(svg), alt=""),
                        className="flag-disc",
                        **{"aria-hidden": "true"},
                    ),
                    html.Span(label, className="flag-label"),
                ],
                id=f"idioma-{code}",
                type="button",
                title=title,
                disable_n_clicks=True,
                className=f"lang-flag{' active' if active else ''}",
                style={"--menu-y": f"{idx * 54}px"},
                **{
                    "aria-label": title,
                    "aria-pressed": "true" if active else "false",
                    "data-lang": code,
                },
            )
        )

    return html.Div(
        html.Div(
            buttons,
            id="idioma-picker",
            className="flag-switcher",
            role="group",
            **{
                "aria-label": "Selecionar idioma",
                "aria-expanded": "false",
            },
        ),
        className="lang-wrap",
        style={"fontFamily": VW_PLOTLY_FONT},
    )


def tela_inicial_filtros() -> html.Div:
    """Tela inicial do executável para pré-filtrar o dashboard geral."""
    field_style = {'width': '100%', 'fontFamily': VW_PLOTLY_FONT}

    return html.Div(
        id='tela-inicial-filtros',
        children=[
            html.Div([
                html.Div([
                    html.Div([
                        html.H1(
                            "Filtros iniciais",
                            style={
                                'margin': '0',
                                'fontFamily': VW_PLOTLY_FONT,
                                'fontSize': 'clamp(26px, 4vw, 32px)',
                                'lineHeight': '1.1',
                            },
                        ),
                    ], style={'minWidth': '0'}),
                    html.Div([
                        html.Button(
                            "→",
                            id='prefiltro-confirmar',
                            n_clicks=0,
                            title='Aplicar filtros e abrir o dashboard geral',
                            **{'aria-label': 'Aplicar filtros e abrir o dashboard geral'},
                            className='prefiltro-confirmar',
                            style={
                                'color': 'Black',
                                'fontFamily': VW_PLOTLY_FONT,
                                'fontWeight': 'bold',
                                'padding': '0',
                                'fontSize': '22px',
                                'lineHeight': '1',
                                'height': '44px',
                                'width': '64px',
                                'backgroundColor': '#e0e0e0',
                                'border': 'none',
                                'borderRadius': '8px',
                                'cursor': 'pointer',
                                'boxShadow': '0px 2px 6px rgba(0,0,0,0.25)',
                                'display': 'inline-flex',
                                'alignItems': 'center',
                                'justifyContent': 'center',
                            },
                        )
                    ])
                ], className='prefiltro-header'),

                html.Div([
                    html.Div([
                        html.Label("Período", className='prefiltro-field-title'),
                        dcc.RadioItems(
                            id='prefiltro-cenario',
                            className='prefiltro-cenario-lista',
                            options=[
                                {'label': 'Jan/2024 a Abr/2025', 'value': 'c1'},
                                {'label': 'Mai/2025 em diante', 'value': 'c2'},
                            ],
                            value='c1',
                        ),
                        dcc.RangeSlider(
                            id='prefiltro-periodo',
                            min=LT_C1_MIN,
                            max=LT_C1_MAX,
                            value=[LT_C1_MIN, LT_C1_MAX],
                            marks=LT_MARKS,
                            allowCross=False,
                            step=1,
                            pushable=1,
                        ),
                    ], className='prefiltro-field prefiltro-field-wide prefiltro-field-shell'),

                    html.Div([
                        html.Label("Incluir na análise", className='prefiltro-field-title'),
                        dcc.Checklist(
                            id='prefiltro-escopo',
                            className='prefiltro-opcoes-lista',
                            options=[
                                {'label': 'Pessoas desligadas', 'value': 'desligados'},
                                {'label': 'Áreas que viajam', 'value': 'viajam'},
                            ],
                            value=['desligados', 'viajam'],
                        ),
                    ], className='prefiltro-field prefiltro-field-wide prefiltro-field-shell'),

                    html.Div([
                        html.Label("Tipo de colaborador", className='prefiltro-field-title'),
                        dcc.Checklist(
                            id='prefiltro-cargo',
                            className='prefiltro-cargo-lista',
                            options=[
                                {
                                    'label': [
                                        html.Span("E", className='prefiltro-cargo-badge'),
                                        html.Span("Executivo"),
                                    ],
                                    'value': 'E',
                                },
                                {
                                    'label': [
                                        html.Span("H", className='prefiltro-cargo-badge'),
                                        html.Span("Horista"),
                                    ],
                                    'value': 'H',
                                },
                                {
                                    'label': [
                                        html.Span("M", className='prefiltro-cargo-badge'),
                                        html.Span("Mensalista"),
                                    ],
                                    'value': 'M',
                                },
                                {
                                    'label': [
                                        html.Span("T", className='prefiltro-cargo-badge'),
                                        html.Span("Terceiro"),
                                    ],
                                    'value': 'T',
                                },
                            ],
                            value=['E', 'H', 'M', 'T'],
                        ),
                    ], className='prefiltro-field prefiltro-field-shell'),

                    html.Div([
                        html.Label("Área", className='prefiltro-field-title'),
                        html.Div([
                            dcc.Dropdown(
                                id='prefiltro-areas',
                                options=dropdown_options,
                                value='GERAL',
                                clearable=False,
                                placeholder='Selecione uma área',
                                style={**field_style, 'flex': '1', 'minWidth': '0'},
                            ),
                            html.Button(
                                '🔍',
                                id='prefiltro-area-go',
                                n_clicks=0,
                                title='Abrir a página completa desta área',
                                className='prefiltro-go-btn',
                                style={
                                    'fontFamily': VW_PLOTLY_FONT,
                                    'fontSize': '14px',
                                    'lineHeight': '1',
                                    'height': '36px',
                                    'minWidth': '36px',
                                    'padding': '0 10px',
                                    'border': '1px solid #cccccc',
                                    'borderRadius': '4px',
                                    'background': '#ffffff',
                                    'cursor': 'pointer',
                                    'whiteSpace': 'nowrap',
                                    'flex': '0 0 auto',
                                    'display': 'inline-flex',
                                    'alignItems': 'center',
                                    'justifyContent': 'center',
                                    'boxSizing': 'border-box',
                                },
                            ),
                        ], style={
                            'display': 'flex',
                            'alignItems': 'center',
                            'gap': '6px',
                            'marginBottom': '12px',
                        }),

                        html.Label(
                            'Colaborador',
                            className='prefiltro-field-title',
                            style={'marginTop': '2px'},
                        ),
                        html.Div([
                            dcc.Dropdown(
                                id='prefiltro-pessoa',
                                options=[],
                                value=None,
                                placeholder='Buscar chapa ou nome...',
                                searchable=True,
                                clearable=True,
                                style={**field_style, 'flex': '1', 'minWidth': '0'},
                            ),
                            html.Button(
                                '🔍',
                                id='prefiltro-pessoa-go',
                                n_clicks=0,
                                title='Abrir a página individual deste colaborador',
                                className='prefiltro-go-btn',
                                style={
                                    'fontFamily': VW_PLOTLY_FONT,
                                    'fontSize': '14px',
                                    'lineHeight': '1',
                                    'height': '36px',
                                    'minWidth': '36px',
                                    'padding': '0 10px',
                                    'border': '1px solid #cccccc',
                                    'borderRadius': '4px',
                                    'background': '#ffffff',
                                    'cursor': 'pointer',
                                    'whiteSpace': 'nowrap',
                                    'flex': '0 0 auto',
                                    'display': 'inline-flex',
                                    'alignItems': 'center',
                                    'justifyContent': 'center',
                                    'boxSizing': 'border-box',
                                },
                            ),
                        ], style={
                            'display': 'flex',
                            'alignItems': 'center',
                            'gap': '6px',
                        }),
                    ], className='prefiltro-field prefiltro-field-shell'),
                ], className='prefiltro-form-grid'),
            ], className='prefiltro-panel')
        ],
        style={
            'minHeight': '100vh',
            'display': 'none',
            'alignItems': 'center',
            'justifyContent': 'center',
            'padding': '20px',
            'boxSizing': 'border-box',
            'backgroundColor': 'white',
            'fontFamily': VW_PLOTLY_FONT,
        },
    )


LAYOUT = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Store(id='prefiltro-aplicado', data=False),
    dcc.Store(id='cargo-selecionado', data=[]),
    dcc.Store(id='areas-prefiltro', data=[]),
    tela_inicial_filtros(),

    # '''~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Geral ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'''
    html.Div([
        html.Div(id='pagina-geral', children=[

            # ====== Título ======
            html.Div([
                html.Div(style={'flex': '0 0 132px', 'minWidth': '132px'}),
                html.H1([
                    html.Span(
                        "Monitoramento Comportamental Geral de toda a Volkswagen",
                        **{"data-i18n": "main_title"},
                    ),
                    html.Br(),
                    html.Span(id='periodo-texto')
                ], style={
                    'textAlign': 'center',
                    'flex': '1',
                    'minWidth': '0',
                    'margin': '0',
                    'fontFamily': VW_PLOTLY_FONT
                }),
                language_selector()
            ], style={
                'display': 'flex',
                'justifyContent': 'space-between',
                'alignItems': 'flex-start',
                'gap': '16px',
                'marginBottom': '20px',
                'fontFamily': VW_PLOTLY_FONT,
                'position': 'relative',
                'zIndex': '20',
            }),

            # ================== BLOCO DE FILTROS ==================
            html.Div([
                html.Div([
                    # --- Bloco A: 2 RadioItems ---
                    html.Div([
                        html.Label(
                            "Mostrar as pessoas desligadas?",
                            **{"data-i18n": "show_inactive"},
                        ),
                        dcc.RadioItems(
                            id='desligados-toggle',
                            options=[
                                {'label': html.Span('Sim', **{"data-i18n": "yes"}), 'value': 'left'},
                                {'label': html.Span('Não', **{"data-i18n": "no"}), 'value': 'right'}
                            ],
                            value='left',
                            labelStyle={'display': 'inline-block', 'marginRight': '10px', 'fontFamily': VW_PLOTLY_FONT}
                        ),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center', 'fontFamily': VW_PLOTLY_FONT}),

                    html.Div([
                        html.Label(
                            "Mostrar as áreas que viajam?",
                            **{"data-i18n": "show_travel"},
                        ),
                        dcc.RadioItems(
                            id='viajam-toggle',
                            options=[
                                {'label': html.Span('Sim', **{"data-i18n": "yes"}), 'value': 'left'},
                                {'label': html.Span('Não', **{"data-i18n": "no"}), 'value': 'right'}
                            ],
                            value='left',
                            labelStyle={'display': 'inline-block', 'marginRight': '10px', 'fontFamily': VW_PLOTLY_FONT}
                        ),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'alignItems': 'center', 'fontFamily': VW_PLOTLY_FONT}),
                ], style={'display': 'flex', 'gap': '30px', 'alignItems': 'center', 'fontFamily': VW_PLOTLY_FONT}),

                # --- Bloco B: Linha do tempo ---
                html.Div([
                    html.Div([
                        dcc.RadioItems(
                            id='cenario-toggle',
                            options=[
                                {
                                    'label': html.Span(
                                        'Jan/2024 a Abr/2025',
                                        **{"data-i18n": "scenario_1"},
                                    ),
                                    'value': 'c1'
                                },
                                {
                                    'label': html.Span(
                                        'Mai/2025 em diante',
                                        **{"data-i18n": "scenario_2"},
                                    ),
                                    'value': 'c2'
                                }
                            ],
                            value='c1',
                            labelStyle={'display': 'inline-block', 'fontFamily': VW_PLOTLY_FONT}
                        )
                    ], style={'textAlign': 'center', 'marginBottom': '6px', 'fontFamily': VW_PLOTLY_FONT}),

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
                ], style={'flex': '0 0 560px', 'fontFamily': VW_PLOTLY_FONT}),

                # --- Bloco C: Dropdown ---
                html.Div([
                    dcc.Dropdown(
                        id='dropdown-area',
                        options=dropdown_options,
                        value='GERAL',
                        clearable=False,
                        style={'width': '270px', 'fontFamily': VW_PLOTLY_FONT}
                    ),
                    html.Div([
                        dcc.Dropdown(
                            id='dropdown-subarea',
                            options=[],
                            value=None,
                            placeholder='Selecione uma subárea',
                            clearable=True,
                            style={'width': '270px', 'marginTop': '10px', 'display': 'none', 'fontFamily': VW_PLOTLY_FONT}
                        )
                    ], id='subarea-container')
                ], style={'marginLeft': 'auto', 'fontFamily': VW_PLOTLY_FONT})
            ], style={
                'flex': '1',
                'padding': '20px',
                'boxSizing': 'border-box',
                'backgroundColor': "#e0e0e0",
                'borderRadius': '20px',
                'height': 'fit-content',
                'marginTop': '30px',
                'marginRight': '10px',
                'boxShadow': '0px 3px 6px rgba(0,0,0,0.1)',
                'display': 'flex',
                'flexWrap': 'wrap',
                'alignItems': 'flex-start',
                'marginBottom': '30px',
                'fontFamily': VW_PLOTLY_FONT,
            }),
            # ======================================================

            # ====== Heatmap + Info ======
            html.Div([
                html.Div([
                    dcc.Loading(
                        dcc.Graph(id='grafico-heatmap', config={'displayModeBar': False},
                                    style={'height': '250px', 'width': '100%', 'fontFamily': VW_PLOTLY_FONT})
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
                            'padding': '5px 10px',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold',
                            'fontSize': '18px'
                        }
                    )
                ], style={
                    'position': 'relative',
                    'flex': '1',
                    'minWidth': '400px',
                    'maxWidth': '100%',
                    'fontFamily': VW_PLOTLY_FONT,
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
                    'boxShadow': '0px 3px 6px rgba(0,0,0,0.1)',
                    'fontFamily': VW_PLOTLY_FONT,
                })
            ], style={
                'display': 'flex',
                'flexWrap': 'wrap',
                'alignItems': 'flex-start',
                'marginBottom': '30px',
                'fontFamily': VW_PLOTLY_FONT,
            }),

            # ====== Dispersão + Cargo ======
            html.Div([
                html.Div([
                    dcc.Loading(dcc.Graph(id='grafico-dispersao',
                                            style={'height': '550px', 'width': '100%', 'fontFamily': VW_PLOTLY_FONT}))
                ], style={'flex': '1', 'marginRight': '20px'}),
                html.Div([
                    dcc.Loading(dcc.Graph(id='grafico-presenca-cargo',
                                            style={'height': '550px', 'width': '100%', 'fontFamily': VW_PLOTLY_FONT}))
                ], style={'flex': '1'})
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'fontFamily': VW_PLOTLY_FONT}),

            # ====== Boxplot ======
            html.Div([
                html.Div([
                    dcc.Loading(dcc.Graph(id='grafico-boxplot',
                                            style={'height': '600px', 'width': '100%', 'fontFamily': VW_PLOTLY_FONT}))
                ], style={'flex': '2'})
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'fontFamily': VW_PLOTLY_FONT}),

            # ====== Resumo ======
            html.Div([
                # Botão de toggle ►
                html.Button("►", id="toggle-resumo-btn", n_clicks=0, style={
                    'fontSize': '18px',
                    'background': 'none',
                    'border': 'none',
                    'cursor': 'pointer',
                    'verticalAlign': 'middle',
                    'fontFamily': VW_PLOTLY_FONT,
                }),

                # Título principal
                html.Span(
                    "Resumo Específico por Área",
                    style={
                        'fontWeight': 'bold',
                        'fontSize': '18px',
                        'color': '#000000',
                        'flex': '1',
                        'textAlign': 'left',
                        'fontFamily': VW_PLOTLY_FONT,
                    },
                    **{"data-i18n": "area_summary"},
                ),

                # Novo botão/link para a página de relacionamento
                dcc.Link(
                    html.Span(
                        "Relacionamento entre Colaboradores ⭢",
                        **{"data-i18n": "relationship_link"},
                    ),
                    href="/relacionamento",
                    style={
                        'fontFamily': VW_PLOTLY_FONT,
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
                'marginBottom': '8px',
                'fontFamily': VW_PLOTLY_FONT,
            }),

            html.Div(id='resumo-container', style={'marginBottom': '20px', 'display': 'none', 'fontFamily': VW_PLOTLY_FONT}),

            # ====== Lista Pessoas ======
            html.Div([
                html.Div([
                    html.Button(
                        "►", id="toggle-lista-btn", n_clicks=0,
                        style={
                            'fontSize': '18px',
                            'background': 'none',
                            'border': 'none',
                            'cursor': 'pointer',
                            'verticalAlign': 'middle',
                            'fontFamily': VW_PLOTLY_FONT,
                        }
                    ),
                    html.Span(
                        "Presença dos Colaboradores",
                        style={
                            'fontWeight': 'bold',
                            'fontSize': '18px',
                            'color': '#000000',
                            'flex': '1',
                            'textAlign': 'left',
                            'fontFamily': VW_PLOTLY_FONT,
                        },
                        **{"data-i18n": "people_presence"},
                    )
                ], style={'marginBottom': '8px', 'fontFamily': VW_PLOTLY_FONT}),

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
                            style={'width': '300px', 'marginTop': '10px', 'marginBottom': '10px', 'fontFamily': VW_PLOTLY_FONT}
                        ),
                        html.Div(id='tabela-detalhada-colaboradores')
                    ],
                    style={'display': 'none'}
                )
            ],
            style={'marginTop': '15px', 'fontFamily': VW_PLOTLY_FONT}),

            # ====== Stores ======
            dcc.Store(id='faixa-selecionada', data=None),
            dcc.Store(id='area-selecionada', data='GERAL'),
            dcc.Store(id='subarea-selecionada', data=None),
            dcc.Store(id='ultimo-clique', data={'faixa': None, 'timestamp': 0}),
            dcc.Store(id='periodo-indices', data=[LT_C1_MIN, LT_C1_MAX])
        ], style={
            'display': 'none',
            'padding': '20px',
            'backgroundColor': 'white',
            'fontFamily': VW_PLOTLY_FONT,
        })
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
                    "↩",
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
                "↩",
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
                "↩",
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
], style={'fontFamily': VW_PLOTLY_FONT})
