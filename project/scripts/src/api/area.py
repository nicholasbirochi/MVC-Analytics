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
import plotly.graph_objects as go

from ..core.repo_global import (
    df_datas,
    df_df_ativos,
    df_semana_merged,
    df_almoco,
    df_headcount,
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
    figura_vazia_linha,
    _sanitize_object_columns,
)
from ..ui.gptw import mini_tabela_df_gptw, mini_tabela_df_turnover
from ..ui.theme import ESTILO_EXIBIR, ESTILO_OCULTO, aplicar_tema_pb

estilo_exibir = ESTILO_EXIBIR
estilo_oculto = ESTILO_OCULTO


def _headcount_card(area: str | None, subarea: str | None):
    th = {
        "padding": "4px 8px",
        "border": "1px solid #bbb",
        "backgroundColor": "#f5f5f5",
        "fontWeight": "bold",
        "textAlign": "center",
        "fontFamily": "VW Text",
    }
    td = {
        "padding": "4px 8px",
        "border": "1px solid #bbb",
        "textAlign": "center",
        "fontFamily": "VW Text",
    }
    td_first = {**td, "fontWeight": "bold", "textAlign": "left"}

    anos = [2023, 2024, 2025]
    if isinstance(df_headcount, pd.DataFrame) and not df_headcount.empty and "Área" in df_headcount.columns:
        dff = df_headcount.copy()
        dff["Área"] = dff["Área"].astype(str)
        if area:
            if subarea:
                dff = dff[dff["Área"].eq(str(subarea))]
            else:
                dff = dff[dff["Área"].str.startswith(str(area))]
    else:
        dff = pd.DataFrame()

    nome_area = subarea or area or "—"
    vals = []
    for ano in anos:
        c_hc = f"{ano} hc"
        c_e = f"{ano} e"
        c_s = f"{ano} s"
        if dff.empty:
            vals.extend(["—", "—", "—"])
            continue
        hc = int(pd.to_numeric(dff[c_hc], errors="coerce").fillna(0).sum()) if c_hc in dff.columns else 0
        ent = int(pd.to_numeric(dff[c_e], errors="coerce").fillna(0).sum()) if c_e in dff.columns else 0
        sai = int(pd.to_numeric(dff[c_s], errors="coerce").fillna(0).sum()) if c_s in dff.columns else 0
        vals.extend([hc, ent, sai])

    header = [html.Th("Área", style=th)]
    for ano in anos:
        header.extend(
            [
                html.Th(str(ano), style=th),
                html.Th("E", style=th),
                html.Th("S", style=th),
            ]
        )

    tabela = html.Table(
        [
            html.Thead(html.Tr(header)),
            html.Tbody(
                [
                    html.Tr(
                        [html.Td(nome_area, style=td_first)]
                        + [html.Td(v, style=td) for v in vals]
                    )
                ]
            ),
        ],
        style={
            "borderCollapse": "collapse",
            "fontSize": "13px",
            "boxShadow": "0px 2px 6px rgba(0,0,0,0.10)",
            "maxWidth": "560px",
        },
    )
    return html.Div(tabela, style={"margin": "0 auto", "width": "fit-content", "maxWidth": "100%"})


def areas_toggle_ui():
    """Toggle visual (heatmap <-> teia) alinhado ao notebook."""
    return html.Div(
        [
            dcc.Store(id="areas_vis_state", data="heatmap"),
            html.Button(
                id="areas_vis_btn",
                n_clicks=0,
                title="Alternar visualização: Heatmap ⇄ Diagrama",
                style={
                    "position": "relative",
                    "width": "92px",
                    "height": "42px",
                    "borderRadius": "999px",
                    "border": "1px solid rgba(0,0,0,.14)",
                    "background": "linear-gradient(#f7f7f7,#e7e7e7)",
                    "boxShadow": "0 1px 2px rgba(0,0,0,.12) inset, 0 1px 2px rgba(0,0,0,.05)",
                    "cursor": "pointer",
                    "transition": "all .18s ease-in-out",
                    "padding": "0",
                    "fontFamily": "VW Text",
                },
                children=html.Div(
                    [
                        html.Span(
                            "▦",
                            id="ico_heat",
                            style={
                                "position": "absolute",
                                "left": "14px",
                                "top": "50%",
                                "transform": "translateY(-50%)",
                                "fontSize": "18px",
                                "lineHeight": "1",
                                "color": "#0057b8",
                                "transition": "opacity .18s ease, color .18s ease",
                            },
                        ),
                        html.Span(
                            "🕸️",
                            id="ico_net",
                            style={
                                "position": "absolute",
                                "right": "14px",
                                "top": "50%",
                                "transform": "translateY(-50%)",
                                "fontSize": "18px",
                                "lineHeight": "1",
                                "color": "#00a37a",
                                "opacity": 0.28,
                                "transition": "opacity .18s ease, color .18s ease",
                            },
                        ),
                        html.Span(
                            id="knob",
                            style={
                                "position": "absolute",
                                "top": "3px",
                                "left": "3px",
                                "width": "36px",
                                "height": "36px",
                                "borderRadius": "50%",
                                "background": "#ffffff",
                                "boxShadow": "0 1px 2px rgba(0,0,0,.28), 0 0 0 1px rgba(0,0,0,.06) inset",
                                "transform": "translateX(0)",
                                "transition": "transform .18s ease-in-out, background .18s ease",
                            },
                        ),
                        html.Span(
                            "▦",
                            id="knob_ico",
                            style={
                                "position": "absolute",
                                "inset": "0",
                                "display": "flex",
                                "alignItems": "center",
                                "justifyContent": "center",
                                "fontSize": "20px",
                                "fontFamily": "VW Text",
                                "transform": "translateX(-25px)",
                                "transition": "transform .18s ease-in-out, color .18s ease-in-out",
                                "color": "#0057b8",
                            },
                        ),
                    ],
                    style={
                        "position": "absolute",
                        "inset": "0",
                        "display": "flex",
                        "alignItems": "center",
                        "justifyContent": "space-between",
                        "padding": "0 12px",
                        "userSelect": "none",
                        "fontFamily": "VW Text",
                    },
                ),
            ),
        ],
        style={"display": "flex", "alignItems": "center", "gap": "12px", "flexWrap": "nowrap"},
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
            Input('desligados-toggle-area', 'value'),
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
        periodo_txt_out = ""
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
        mudou_filtros     = trig in ('desligados-toggle-area', 'viajam-toggle-area')

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

        # --- Decide modo de visualização (Heatmap ou Teia/Network) ---
        vis_mode = areas_vis_state or "heatmap"
        if isinstance(vis_mode, str):
            vis_mode = vis_mode.lower()
        else:
            vis_mode = "heatmap"

        if not df_full.empty:
            if not hasattr(callback_unificado, "_fig_cache"):
                callback_unificado._fig_cache = {}
            fig_cache = callback_unificado._fig_cache

            if vis_mode == "network":
                fig_key = (df_key, "network_radar_v3")
            else:
                fig_key = (df_key, "heatmap")

            if fig_key in fig_cache:
                fig_men_full, fig_exec_full = fig_cache[fig_key]
            else:
                if vis_mode == "network":
                    df_net = df_full.copy()
                    try:
                        df_net = _sanitize_object_columns(df_net)
                    except Exception:
                        pass

                    if "Cargo" in df_net.columns:
                        try:
                            c = df_net["Cargo"].astype(str).str.strip()
                            cu = c.str.upper()
                            df_net["Cargo"] = (
                                pd.Series(pd.NA, index=df_net.index, dtype="object")
                                .where(False, other=cu.str[:1])
                            )
                            df_net["Cargo"] = df_net["Cargo"].where(
                                ~(cu.str.startswith("E") | cu.str.contains("EXEC")), "E"
                            )
                            df_net["Cargo"] = df_net["Cargo"].where(
                                ~(cu.str.startswith("M") | cu.str.contains("MENS")), "M"
                            )
                            df_net["Cargo"] = df_net["Cargo"].where(
                                ~(cu.str.startswith("H") | cu.str.contains("HOR")), "H"
                            )
                            df_net["Cargo"] = df_net["Cargo"].astype(str)
                        except Exception:
                            df_net["Cargo"] = df_net["Cargo"].astype(str)

                    if "Cadastro" in df_net.columns:
                        df_net["Cadastro"] = df_net["Cadastro"].astype(str)
                    if "Nome" not in df_net.columns and "Cadastro" in df_net.columns:
                        df_net["Nome"] = df_net["Cadastro"]
                    if "Data" in df_net.columns:
                        df_net["Data"] = pd.to_datetime(df_net["Data"], errors="coerce")
                    elif "Semana" in df_net.columns:
                        df_net["Data"] = pd.to_datetime(df_net["Semana"], errors="coerce")
                    if "Contagem Presença" in df_net.columns:
                        df_net["Contagem Presença"] = pd.to_numeric(
                            df_net["Contagem Presença"], errors="coerce"
                        ).fillna(0.0)
                    else:
                        df_net["Contagem Presença"] = 1.0

                    try:
                        titulo_men_teia = (
                            f"Pentágonos de relacionamento (Executivos × Mensalistas e Horistas) ({periodo})"
                        )
                        fig_men_full = grafico_pentagonos_rel_exec_multiplos(
                            df_net,
                            titulo=titulo_men_teia,
                            max_exec=12,
                            max_eixos=None,
                            range_mode="global",
                            validar_mesma_planta=True,
                            df_hierarquia=df_df_ativos,
                            is_almoco=is_almoco,
                            strict=True,
                        )
                    except Exception as exc:
                        fig_men_full = go.Figure()
                        fig_men_full.update_layout(
                            title={
                                'text': f"{titulo_men} — erro ao gerar TEIA",
                                'font': {'family': 'VW Text', 'size': 22}
                            },
                            height=420,
                            font={'family': 'VW Text'}
                        )
                        fig_men_full.add_annotation(
                            text=str(exc)[:200],
                            x=0.5,
                            y=0.5,
                            xref='paper',
                            yref='paper',
                            showarrow=False
                        )

                    try:
                        titulo_exec_teia = (
                            f"Pentágonos de relacionamento (Executivos × Executivos) ({periodo})"
                        )
                        fig_exec_full = grafico_pentagonos_exec_exec_multiplos(
                            df_net,
                            titulo=titulo_exec_teia,
                            max_exec=12,
                            max_eixos=None,
                            range_mode="global",
                            validar_mesma_planta=True,
                            df_hierarquia=df_df_ativos,
                            is_almoco=is_almoco,
                            strict=True,
                        )
                    except Exception as exc:
                        fig_exec_full = go.Figure()
                        fig_exec_full.update_layout(
                            title={
                                'text': f"{titulo_exec} — erro ao gerar TEIA",
                                'font': {'family': 'VW Text', 'size': 22}
                            },
                            height=420,
                            font={'family': 'VW Text'}
                        )
                        fig_exec_full.add_annotation(
                            text=str(exc)[:200],
                            x=0.5,
                            y=0.5,
                            xref='paper',
                            yref='paper',
                            showarrow=False
                        )
                else:
                    fig_men_full = aplicar_tema_pb(
                        grafico_heatmap_encontros_men(
                            df_full, titulo_men, validar_mesma_planta=True
                        ),
                        so_y_boxplot=False,
                        grade=True,
                    )
                    fig_exec_full = aplicar_tema_pb(
                        grafico_heatmap_encontros_exec(
                            df_full, titulo_exec, validar_mesma_planta=True
                        ),
                        so_y_boxplot=False,
                        grade=False,
                        clean=True,
                    )
                fig_cache[fig_key] = (fig_men_full, fig_exec_full)

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
        if is_almoco:
            texto_toggle = "Relacionamento Geral da Área ⭢"
            href_toggle = f"/area/{slug(subarea or area)}?modo=geral"
        else:
            texto_toggle = "Relacionamento do Almoço da Área ⭢"
            href_toggle = f"/area/{slug(subarea or area)}?modo=almoco"

        # ======= CONSTRÓI O RELATÓRIO (FIGURAS INICIAIS) =======
        if is_almoco:
            df_full = build_dataframe_almoco_area(area, subarea, her, df_almoco, df_df_ativos)
        else:
            df_full = build_dataframe_diario_area(area, subarea, her, df_datas, df_df_ativos)

        fig_heatmap_men = figura_vazia_linha("Carregando informações de relacionamento da área...")
        fig_heatmap_exec = figura_vazia_linha("Carregando informações de relacionamento da área...")

        # ======= BARRA DE FILTROS (mesmo conteúdo, mas pode ficar oculta no modo almoço) =======
        filter_block_style = {
            'flex':'1','padding':'16px','boxSizing':'border-box','backgroundColor':"#e0e0e0",
            'borderRadius':'16px','margin':'10px','boxShadow':'0px 3px 6px rgba(0,0,0,0.1)',
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
                        id='desligados-toggle-area',
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
            ], style={'flex':'0 0 540px'}),

            # Subárea local (dentro da mesma herança)
            html.Div([
                dcc.Dropdown(
                    id='dropdown-subarea-area',
                    options=[],
                    value=subarea,  # já entra com a subárea atual, se houver
                    placeholder='Selecione uma subárea',
                    clearable=True,
                    style={'width': '270px', 'marginTop': '6px'}
                ),
            ], style={'marginLeft':'auto'})
        ], style=filter_block_style)

        bloco_duplo = html.Div(
            [
                html.Div(
                    [
                        html.H4(
                            "Headcount & Turnover",
                            style={"textAlign": "center", "margin": "0 0 24px", "fontFamily": "VW Text"},
                        ),
                        mini_tabela_df_turnover(subarea or area, anos=(2023, 2024, 2025), incluir_macro=True),
                    ],
                    style={
                        "backgroundColor": "#fff",
                        "border": "1px solid #dcdcdc",
                        "borderRadius": "6px",
                        "padding": "6px",
                        "boxShadow": "0 2px 2px rgba(0,0,0,0.08)",
                        "flex": "0 1 270px",
                        "maxWidth": "560px",
                        "fontFamily": "VW Text",
                    },
                ),
                html.Div(
                    [
                        html.H4(
                            "GPTW",
                            style={"textAlign": "center", "margin": "0 0 24px", "fontFamily": "VW Text"},
                        ),
                        html.Div(
                            mini_tabela_df_gptw(subarea or area),
                            style={"margin": "0 auto", "width": "fit-content", "maxWidth": "100%"},
                        ),
                    ],
                    style={
                        "backgroundColor": "#fff",
                        "border": "1px solid #dcdcdc",
                        "borderRadius": "6px",
                        "padding": "6px",
                        "boxShadow": "0 2px 2px rgba(0,0,0,0.08)",
                        "flex": "0 1 270px",
                        "maxWidth": "560px",
                        "fontFamily": "VW Text",
                    },
                ),
                html.Div(
                    html.Div(areas_toggle_ui(), style={"pointerEvents": "auto"}),
                    style={
                        "position": "absolute",
                        "right": "10px",
                        "top": "10px",
                        "zIndex": 20,
                        "pointerEvents": "auto",
                    },
                ),
            ],
            style={
                "position": "relative",
                "display": "flex",
                "justifyContent": "center",
                "alignItems": "flex-start",
                "gap": "24px",
                "flexWrap": "wrap",
                "width": "100%",
                "maxWidth": "100%",
                "margin": "8px 0 16px",
                "padding": "10px",
                "boxSizing": "border-box",
                "fontFamily": "VW Text",
            },
        )

        conteudo = html.Div([
            # Sequenciador de loading da aba Áreas
            dcc.Store(id='area-load-step', data=0),
            dcc.Interval(id='area-load-interval', interval=500, n_intervals=0, disabled=False, max_intervals=2),

            html.Div([
                html.Div(
                    html.Span(
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
                            'width': '100%',
                            'margin': '20px 10px 0 10px',
                            'lineHeight': '1.3',
                            'boxSizing': 'border-box',
                        },
                    ),
                    id='definicao-site',
                    style={'display': 'flex', 'justifyContent': 'center', 'marginBottom': '8px'},
                ) if is_almoco else html.Div(),
                html.Div([
                    html.Div(
                        [
                            html.Button(
                                " ↩ ",
                                id='botao-voltar-area',
                                n_clicks=0,
                                style={
                                    'display': 'inline-flex',
                                    'alignItems': 'center',
                                    'color': 'Black',
                                    'fontFamily': 'VW Text',
                                    'fontWeight': 'bold',
                                    'padding': '5px 20px',
                                    'fontSize': '20px',
                                    'backgroundColor': '#e0e0e0',
                                    'border': 'none',
                                    'borderRadius': '5px',
                                    'cursor': 'pointer',
                                    'boxShadow': '0px 2px 6px rgba(0,0,0,0.25)',
                                    'textAlign': 'center',
                                    'textDecoration': 'none',
                                    'transition': '0.2s ease',
                                },
                            )
                        ],
                        style={
                            'display': 'flex',
                            'flexDirection': 'row',
                            'alignItems': 'center',
                            'justifyContent': 'flex-start',
                            'gap': '12px',
                            'flexWrap': 'nowrap',
                        },
                    ),
                    html.Div(
                        [
                            html.Button(
                                "🖨️ Imprimir",
                                id='btn-print-area',
                                n_clicks=0,
                                style={
                                    'backgroundColor': 'transparent',
                                    'border': 'none',
                                    'color': 'Black',
                                    'fontFamily': 'VW Text',
                                    'fontWeight': 'bold',
                                    'fontSize': '16px',
                                    'cursor': 'pointer',
                                    'padding': '10px 6px',
                                    'display': 'inline-flex',
                                    'alignItems': 'center',
                                    'justifyContent': 'center',
                                },
                            ),
                            dcc.Link(
                                texto_toggle,
                                href=href_toggle,
                                style={
                                    'display': 'inline-block',
                                    'color': 'Black',
                                    'fontFamily': 'VW Text',
                                    'fontWeight': 'bold',
                                    'padding': '10px',
                                    'fontSize': '14px',
                                    'backgroundColor': '#e0e0e0',
                                    'border': 'none',
                                    'borderRadius': '5px',
                                    'cursor': 'pointer',
                                    'boxShadow': '0px 2px 6px rgba(0, 0, 0, 0.25)',
                                    'width': 'auto',
                                    'textAlign': 'center',
                                    'textDecoration': 'none',
                                    'transition': '0.2s ease',
                                },
                            ),
                        ],
                        style={
                            'marginLeft': 'auto',
                            'display': 'flex',
                            'alignItems': 'center',
                            'justifyContent': 'flex-end',
                            'gap': '16px',
                            'flexWrap': 'nowrap',
                        },
                    ),
                    html.H2(
                        f"Análise Específica — {subarea or area}",
                        style={
                            'position': 'absolute',
                            'left': '50%',
                            'transform': 'translateX(-50%)',
                            'margin': '0',
                            'fontFamily': 'VW Text',
                            'fontWeight': 'bold',
                            'fontSize': '22px',
                            'whiteSpace': 'nowrap',
                            'overflow': 'hidden',
                            'textOverflow': 'ellipsis',
                            'textAlign': 'center',
                            'zIndex': 1,
                        },
                    ),
                ], style={
                    'display': 'flex',
                    'alignItems': 'center',
                    'justifyContent': 'space-between',
                    'flexWrap': 'wrap',
                    'gap': '16px',
                    'margin': '4px 0 0',
                    'padding': '0 10px',
                    'width': '100%',
                    'boxSizing': 'border-box',
                    'position': 'relative',
                }),
            ]),

            html.Div(id='dummy-print-area', style={'display': 'none'}),

            # ===================== FILTROS E GRÁFICOS =====================
            filtros_div,

            html.Div(
                id='periodo-texto-area',
                style={
                    'textAlign': 'center',
                    'marginTop': '4px',
                    'marginBottom': '10px'
                }
            ),

            bloco_duplo,

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
        style={'padding': '0px', 'backgroundColor': 'white'})

        return conteudo, {'display':'block'}, {'display':'none'}, no_update

    app.clientside_callback(
        """
        function(n_clicks, current) {
            current = current || "heatmap";
            var next_state = current;
            if (n_clicks && n_clicks > 0) {
                next_state = (current === "heatmap") ? "network" : "heatmap";
            }
            var btn_base = {
                position: "relative",
                width: "92px",
                height: "42px",
                borderRadius: "999px",
                border: "1px solid rgba(0,0,0,.14)",
                background: "linear-gradient(#f7f7f7,#e7e7e7)",
                boxShadow: "0 1px 2px rgba(0,0,0,.12) inset, 0 1px 2px rgba(0,0,0,.05)",
                cursor: "pointer",
                transition: "all .18s ease-in-out",
                padding: "0",
                fontFamily: "VW Text"
            };
            var btn_on = {
                background: "linear-gradient(#181818,#2a2a2a)",
                border: "1px solid rgba(255,255,255,.12)"
            };
            var knob_base = {
                position: "absolute",
                top: "3px",
                left: "3px",
                width: "36px",
                height: "36px",
                borderRadius: "50%",
                background: "#ffffff",
                boxShadow: "0 1px 2px rgba(0,0,0,.28), 0 0 0 1px rgba(0,0,0,.06) inset",
                transform: "translateX(0)",
                transition: "transform .18s ease-in-out, background .18s ease"
            };
            var knob_on = {
                transform: "translateX(50px)",
                background: "#1e1e1e",
                boxShadow: "0 1px 2px rgba(0,0,0,.28), 0 0 0 1px rgba(255,255,255,.08) inset"
            };
            var ico_base = {
                position: "absolute",
                top: "50%",
                transform: "translateY(-50%)",
                fontSize: "18px",
                lineHeight: "18px",
                fontFamily: "VW Text",
                userSelect: "none"
            };
            var ico_heat_color = { color: "#0057b8", left: "14px" };
            var ico_net_color  = { color: "#00a37a", right: "14px" };
            var ico_dim = { opacity: 0.28 };
            var ico_on_color = { color: "#f3f3f3" };
            var knob_ico_base = {
                position: "absolute",
                inset: "0",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "20px",
                fontFamily: "VW Text",
                transform: "translateX(-25px)"
            };
            var btn_style = Object.assign({}, btn_base);
            var knob_style = Object.assign({}, knob_base);
            var heat_style = Object.assign({}, ico_base, ico_heat_color);
            var net_style  = Object.assign({}, ico_base, ico_net_color);
            var knob_ico_style = Object.assign({}, knob_ico_base);
            var knob_ico_txt = "▦";
            if (next_state === "network") {
                Object.assign(btn_style, btn_on);
                Object.assign(knob_style, knob_on);
                Object.assign(heat_style, ico_dim);
                Object.assign(net_style, ico_on_color);
                knob_ico_txt = "🕸️";
                Object.assign(knob_ico_style, { color: "#f3f3f3", transform: "translateX(25px)" });
            } else {
                Object.assign(net_style, ico_dim);
                Object.assign(knob_ico_style, { color: "#0057b8", transform: "translateX(-25px)" });
            }
            return [next_state, btn_style, knob_style, heat_style, net_style, knob_ico_txt, knob_ico_style];
        }
        """,
        Output('areas_vis_state', 'data'),
        Output('areas_vis_btn', 'style'),
        Output('knob', 'style'),
        Output('ico_heat', 'style'),
        Output('ico_net', 'style'),
        Output('knob_ico', 'children'),
        Output('knob_ico', 'style'),
        Input('areas_vis_btn', 'n_clicks'),
        State('areas_vis_state', 'data'),
    )

    app.clientside_callback(
        """
        function(n_clicks) {
            if (!n_clicks) {
                return "";
            }
            try {
                window.print();
            } catch (e) {
                if (console && console.error) {
                    console.error("Erro ao chamar window.print()", e);
                }
            }
            return "";
        }
        """,
        Output('dummy-print-area', 'children'),
        Input('btn-print-area', 'n_clicks'),
    )
