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
from dash import Input, Output, State, callback_context, dcc, html, no_update
from dash.exceptions import PreventUpdate
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
    DATA_MUDANCA_REGRA_PRESENCIAL,
    MIN_PRESENCIAL_ANTES_MUDANCA,
    MIN_PRESENCIAL_APOS_MUDANCA,
)
from ..domain.copresenca import calcular_ordem_heatmap
from ..domain.cargo import HORISTA_LABEL, TERCEIRO_LABEL, normalize_cargo_columns
from ..ui.figures import (
    grafico_heatmap_encontros_men,
    grafico_heatmap_encontros_exec,
    figura_vazia_linha,
)
from ..ui.theme import ESTILO_EXIBIR, ESTILO_OCULTO, aplicar_tema_pb


def _normalizar_faixas(faixas) -> list[str]:
    if not faixas:
        return []
    if isinstance(faixas, str):
        return [faixas]
    return [str(f) for f in faixas]


def _normalizar_cadastro(valor: object) -> str:
    texto = "" if valor is None else str(valor).strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        return texto[:-2]
    return texto


def _normalizar_cargo_prefiltro(cargo) -> list[str]:
    if not cargo:
        return []
    valores = [cargo] if isinstance(cargo, str) else list(cargo)
    normalizados: list[str] = []
    for valor in valores:
        texto = str(valor or "").strip().upper()
        cod = ""
        if texto in {"E", "H", "M", "T"}:
            cod = texto
        elif texto.startswith("EXEC"):
            cod = "E"
        elif texto.startswith("HOR"):
            cod = "H"
        elif texto.startswith("MENS"):
            cod = "M"
        elif texto.startswith("TERC"):
            cod = "T"

        if cod and cod not in normalizados:
            normalizados.append(cod)
    return normalizados


def _normalizar_areas_prefiltro(areas) -> list[str]:
    if not areas:
        return []
    if isinstance(areas, str):
        areas = [areas]
    normalizadas: list[str] = []
    for area in areas:
        texto = str(area or "").strip()
        if not texto or texto == "GERAL":
            continue
        if texto not in normalizadas:
            normalizadas.append(texto)
    return normalizadas


def _normalizar_periodo_prefiltro(cenario: object, periodo) -> tuple[str, list[int]]:
    cenario_norm = "c2" if str(cenario or "").strip().lower() == "c2" else "c1"
    min_i, max_i = (LT_C2_MIN, LT_C2_MAX) if cenario_norm == "c2" else (LT_C1_MIN, LT_C1_MAX)

    try:
        v0, v1 = periodo if periodo and len(periodo) == 2 else [min_i, max_i]
        v0, v1 = int(v0), int(v1)
    except Exception:
        v0, v1 = min_i, max_i

    if v1 < min_i or v0 > max_i:
        return cenario_norm, [min_i, max_i]

    v0 = min(max(v0, min_i), max_i)
    v1 = min(max(v1, min_i), max_i)
    if v0 > v1:
        v0, v1 = min_i, max_i
    return cenario_norm, [v0, v1]


def _aplicar_prefiltros_inicio(
    media_df: pd.DataFrame,
    cargo_prefiltro: object = None,
    areas_prefiltro=None,
) -> pd.DataFrame:
    if media_df is None or media_df.empty:
        return media_df

    out = media_df.copy()
    cargos = _normalizar_cargo_prefiltro(cargo_prefiltro)
    if cargos and "Cargo" in out.columns:
        out = out[out["Cargo"].astype(str).str.upper().str.strip().isin(cargos)].copy()

    areas = _normalizar_areas_prefiltro(areas_prefiltro)
    if areas and "Área" in out.columns:
        area_series = out["Área"].astype(str).str.strip()
        mask = pd.Series(False, index=out.index)
        for area in areas:
            mask = mask | area_series.eq(area) | area_series.str.startswith(area)
        out = out[mask].copy()

    return out


def _media_colaboradores(
    df_desligados,
    viajam,
    area_selecionada,
    subarea_selecionada,
    periodo_idx,
) -> pd.DataFrame:
    media_df = carregar_media_colaboradores(
        df_desligados=df_desligados,
        viajam=viajam,
        area_selecionada=area_selecionada,
        subarea_selecionada=subarea_selecionada,
        periodo_idx=periodo_idx,
    )
    if "Cargo" in media_df.columns:
        media_df = normalize_cargo_columns(
            media_df,
            cargo_col="Cargo",
            fallback_col="Cargo Especifico",
        )
    return media_df


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


def _meta_presencial_periodo(periodo_idx) -> float:
    try:
        dt_ini, dt_fim = periodo_limites(periodo_idx)
    except Exception:
        return float(MIN_PRESENCIAL_APOS_MUDANCA)

    dt_ini = pd.Timestamp(dt_ini).normalize()
    dt_fim = pd.Timestamp(dt_fim).normalize()
    if dt_ini > dt_fim:
        dt_ini, dt_fim = dt_fim, dt_ini

    if dt_ini >= DATA_MUDANCA_REGRA_PRESENCIAL:
        return float(MIN_PRESENCIAL_APOS_MUDANCA)
    if dt_fim < DATA_MUDANCA_REGRA_PRESENCIAL:
        return float(MIN_PRESENCIAL_ANTES_MUDANCA)

    semanas = pd.period_range(dt_ini, dt_fim, freq="W")
    metas = [
        MIN_PRESENCIAL_APOS_MUDANCA
        if pd.Timestamp(semana.end_time).normalize() >= DATA_MUDANCA_REGRA_PRESENCIAL
        else MIN_PRESENCIAL_ANTES_MUDANCA
        for semana in semanas
    ]
    if not metas:
        return float(MIN_PRESENCIAL_APOS_MUDANCA)
    return round(float(sum(metas) / len(metas)), 2)


def _percentual_vs_meta(media, meta: float) -> float:
    try:
        media_f = float(media)
        meta_f = float(meta)
    except Exception:
        return -100.0
    if meta_f <= 0:
        return 0.0
    return round(((media_f / meta_f) * 100) - 100, 2)


def _cor_vs_meta(media, meta: float) -> str:
    try:
        return "green" if float(media) >= float(meta) else "red"
    except Exception:
        return "red"


def register(app):
    @app.callback(
        Output('tela-inicial-filtros', 'style'),
        Input('url', 'pathname')
    )
    def rotear_tela_prefiltro(pathname):
        if pathname and pathname.rstrip('/') == "/prefiltro":
            return {
                'minHeight': '100vh',
                'display': 'flex',
                'alignItems': 'center',
                'justifyContent': 'center',
                'padding': '20px',
                'boxSizing': 'border-box',
                'backgroundColor': 'white',
                'fontFamily': 'VW Text',
            }
        return ESTILO_OCULTO

    @app.callback(
        Output('prefiltro-periodo', 'min'),
        Output('prefiltro-periodo', 'max'),
        Output('prefiltro-periodo', 'value'),
        Input('prefiltro-cenario', 'value'),
        State('prefiltro-periodo', 'value')
    )
    def atualizar_periodo_prefiltro(cenario, periodo_atual):
        cenario_norm, periodo = _normalizar_periodo_prefiltro(cenario, periodo_atual)
        min_i, max_i = (LT_C2_MIN, LT_C2_MAX) if cenario_norm == "c2" else (LT_C1_MIN, LT_C1_MAX)
        return min_i, max_i, periodo

    @app.callback(
        Output('pagina-geral', 'style', allow_duplicate=True),
        Output('desligados-toggle', 'value'),
        Output('viajam-toggle', 'value'),
        Output('dropdown-area', 'value'),
        Output('cenario-toggle', 'value'),
        Output('periodo-slider', 'value', allow_duplicate=True),
        Output('area-selecionada', 'data', allow_duplicate=True),
        Output('subarea-selecionada', 'data', allow_duplicate=True),
        Output('periodo-indices', 'data', allow_duplicate=True),
        Output('cargo-selecionado', 'data'),
        Output('areas-prefiltro', 'data'),
        Output('prefiltro-aplicado', 'data'),
        Output('url', 'pathname', allow_duplicate=True),
        Output('prefiltro-aviso', 'children'),
        Output('prefiltro-aviso', 'style'),
        Input('prefiltro-confirmar', 'n_clicks'),
        State('prefiltro-cargo', 'value'),
        State('prefiltro-escopo', 'value'),
        State('prefiltro-cenario', 'value'),
        State('prefiltro-periodo', 'value'),
        State('prefiltro-areas', 'value'),
        prevent_initial_call=True
    )
    def confirmar_prefiltro(n_clicks, cargo, escopo, cenario, periodo, areas):
        if not n_clicks:
            raise PreventUpdate

        cenario_norm, periodo_norm = _normalizar_periodo_prefiltro(cenario, periodo)
        cargo_norm = _normalizar_cargo_prefiltro(cargo)
        if not cargo_norm:
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                "Selecione pelo menos um tipo de colaborador.",
                {
                    "display": "block",
                    "marginTop": "12px",
                    "color": "#b00020",
                    "fontWeight": "bold",
                    "fontFamily": "VW Text",
                    "textAlign": "center",
                },
            )
        areas_norm = _normalizar_areas_prefiltro(areas)
        escopo_set = set(escopo or [])
        desligados = "left" if "desligados" in escopo_set else "right"
        viajam = "left" if "viajam" in escopo_set else "right"

        area_dropdown = "GERAL"
        areas_store: list[str] = []
        if len(areas_norm) == 1:
            area_dropdown = areas_norm[0]
        elif len(areas_norm) > 1:
            areas_store = areas_norm

        return (
            ESTILO_EXIBIR,
            desligados,
            viajam,
            area_dropdown,
            cenario_norm,
            periodo_norm,
            area_dropdown,
            None,
            periodo_norm,
            cargo_norm,
            areas_store,
            True,
            "/",
            "",
            {"display": "none"},
        )

    @app.callback(
        Output('areas-prefiltro', 'data', allow_duplicate=True),
        Input('dropdown-area', 'value'),
        State('areas-prefiltro', 'data'),
        prevent_initial_call=True
    )
    def limpar_prefiltro_multi_area(area, areas_prefiltro):
        if not areas_prefiltro or area == "GERAL":
            raise PreventUpdate
        return []

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
            Input('dropdown-subarea', 'value'),
            Input('cenario-toggle', 'value'),
            Input('periodo-slider', 'value'),
        ],
    )
    def orquestrador(area, sub_val_atual, cenario, slider_val):
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
        d0, d1 = periodo_limites(slider_out)
        d0 = pd.Timestamp(d0)
        d1 = pd.Timestamp(d1)
        periodo_txt = html.Span(
            f"Período selecionado: {fmt_mes_ano(d0)} a {fmt_mes_ano(d1)}",
            **{
                "data-i18n-period": "selected_period",
                "data-period-start": d0.strftime("%Y-%m"),
                "data-period-end": d1.strftime("%Y-%m"),
            },
        )

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
        Input('periodo-indices', 'data'),
        Input('cargo-selecionado', 'data'),
        Input('areas-prefiltro', 'data'),
        Input('prefiltro-aplicado', 'data')
    )
    def atualizar_tabela(
        df_desligados,
        viajam,
        chapa_selecionada,
        faixas,
        area_selecionada,
        subarea_selecionada,
        periodo_idx,
        cargo_prefiltro,
        areas_prefiltro,
        prefiltro_aplicado,
    ):
        if not prefiltro_aplicado:
            return html.Div()
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_df = _aplicar_prefiltros_inicio(media_df, cargo_prefiltro, areas_prefiltro)
        media_colab = media_df[
            ["Área", "Departamento", "Cadastro", "Nome", "Cargo Especifico", "Média Presença"]
        ].copy()
        media_colab.columns = ["Área", "Departamento", "Chapa", "Nome", "Cargo", "Média Dia"]
        media_colab["Chapa"] = media_colab["Chapa"].map(_normalizar_cadastro)
        media_colab['Média Dia'] = media_colab['Média Dia'].round(2)

        if chapa_selecionada:
            chapa_ref = _normalizar_cadastro(chapa_selecionada)
            media_colab = media_colab[media_colab['Chapa'].astype(str) == chapa_ref]

        meta_periodo = _meta_presencial_periodo(periodo_idx)
        media_colab = aplicar_filtro_faixas(media_colab, 'Média Dia', faixas)
        media_colab['Média %'] = media_colab['Média Dia'].apply(
            lambda valor: _percentual_vs_meta(valor, meta_periodo)
        )
        media_colab = media_colab.sort_values(by=['Área', 'Média %'], ascending=True)
        media_colab['Média %'] = media_colab['Média %'].astype(str) + ' %'
        try:
            p0 = int(periodo_idx[0]) if periodo_idx and len(periodo_idx) > 0 else LT_C1_MIN
            p1 = int(periodo_idx[1]) if periodo_idx and len(periodo_idx) > 1 else LT_C1_MAX
        except Exception:
            p0, p1 = LT_C1_MIN, LT_C1_MAX

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
                            dcc.Link(str(valor), href=f"/pessoa/{linha[2]}?p0={p0}&p1={p1}", style={
                                'display': 'block',
                                'width': '100%',
                                'height': '100%',
                                'color': (
                                    _cor_vs_meta(linha[5], meta_periodo)
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
        Input('periodo-indices', 'data'),
        Input('cargo-selecionado', 'data'),
        Input('areas-prefiltro', 'data'),
        Input('prefiltro-aplicado', 'data')
    )
    def atualizar_opcoes_chapa(
        df_desligados,
        viajam,
        faixas,
        area_selecionada,
        subarea_selecionada,
        periodo_idx,
        cargo_prefiltro,
        areas_prefiltro,
        prefiltro_aplicado,
    ):
        if not prefiltro_aplicado:
            return []
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_df = _aplicar_prefiltros_inicio(media_df, cargo_prefiltro, areas_prefiltro)
        media_presenca = media_df[['Cadastro', 'Nome', 'Média Presença']].copy()
        media_presenca.columns = ['Chapa', 'Nome', 'Média']
        media_presenca["Chapa"] = media_presenca["Chapa"].map(_normalizar_cadastro)
        media_presenca = aplicar_filtro_faixas(media_presenca, 'Média', faixas)
        media_presenca = media_presenca.sort_values(by='Nome')
        opcoes = [
            {"label": f"{row['Chapa']} - {row['Nome']}", "value": str(row['Chapa'])}
            for _, row in media_presenca.iterrows()
        ]

        return opcoes

    @app.callback(
        Output('grafico-heatmap', 'figure'),
        Input('desligados-toggle', 'value'),
        Input('viajam-toggle', 'value'),
        Input('faixa-selecionada', 'data'),
        Input('area-selecionada', 'data'),
        Input('subarea-selecionada', 'data'),
        Input('periodo-indices', 'data'),
        Input('cargo-selecionado', 'data'),
        Input('areas-prefiltro', 'data'),
        Input('prefiltro-aplicado', 'data')
    )
    def atualizar_heatmap(
        df_desligados,
        viajam,
        faixas,
        area_selecionada,
        subarea_selecionada,
        periodo_idx,
        cargo_prefiltro,
        areas_prefiltro,
        prefiltro_aplicado,
    ):
        if not prefiltro_aplicado:
            return figura_vazia_linha("Aguardando filtros iniciais.")
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_df = _aplicar_prefiltros_inicio(media_df, cargo_prefiltro, areas_prefiltro)
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
        meta_periodo = _meta_presencial_periodo(periodo_idx)

        for i, faixa in enumerate(x_faixas):
            fmin = int(faixa.split(" ")[0])
            qtd = y_faixas[i]
            if fmin < meta_periodo:
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
        Input('periodo-indices', 'data'),
        Input('cargo-selecionado', 'data'),
        Input('areas-prefiltro', 'data'),
        Input('prefiltro-aplicado', 'data')
    )
    def atualizar_dispersao(
        df_desligados,
        viajam,
        faixas,
        area_selecionada,
        subarea_selecionada,
        periodo_idx,
        cargo_prefiltro,
        areas_prefiltro,
        prefiltro_aplicado,
    ):
        if not prefiltro_aplicado:
            return figura_vazia_linha("Aguardando filtros iniciais.")
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_df = _aplicar_prefiltros_inicio(media_df, cargo_prefiltro, areas_prefiltro)
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
        Input('periodo-indices', 'data'),
        Input('cargo-selecionado', 'data'),
        Input('areas-prefiltro', 'data'),
        Input('prefiltro-aplicado', 'data')
    )
    def atualizar_presenca_cargo(
        df_desligados,
        viajam,
        faixas,
        area_selecionada,
        subarea_selecionada,
        periodo_idx,
        cargo_prefiltro,
        areas_prefiltro,
        prefiltro_aplicado,
    ):
        if not prefiltro_aplicado:
            return figura_vazia_linha("Aguardando filtros iniciais.")
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_df = _aplicar_prefiltros_inicio(media_df, cargo_prefiltro, areas_prefiltro)
        media_presenca_detalhada = media_df[['Cadastro', 'Média Presença', 'Cargo']].copy()
        media_presenca_detalhada = aplicar_filtro_faixas(media_presenca_detalhada, 'Média Presença', faixas)
        if media_presenca_detalhada.empty:
            return figura_vazia_linha("Sem dados para o período e filtros selecionados.")

        fig_cargo = go.Figure()
        for cod, nome, cor in [
            ('E', 'Executivos', "#1574b3"),
            ('M', 'Mensalistas', '#7cc3e9'),
            ('H', HORISTA_LABEL, '#3fbe81'),
            ('T', TERCEIRO_LABEL, '#f4a259'),
        ]:
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
        Input('periodo-indices', 'data'),
        Input('cargo-selecionado', 'data'),
        Input('areas-prefiltro', 'data'),
        Input('prefiltro-aplicado', 'data')
    )
    def atualizar_boxplot(
        df_desligados,
        viajam,
        faixas,
        area_selecionada,
        subarea_selecionada,
        periodo_idx,
        cargo_prefiltro,
        areas_prefiltro,
        prefiltro_aplicado,
    ):
        if not prefiltro_aplicado:
            return figura_vazia_linha("Aguardando filtros iniciais.")
        # Se nenhuma área específica foi selecionada, não carrega o gráfico
        areas_multiplas = _normalizar_areas_prefiltro(areas_prefiltro)
        if not area_selecionada or (area_selecionada == "GERAL" and not areas_multiplas):
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
        media_df = _aplicar_prefiltros_inicio(media_df, cargo_prefiltro, areas_prefiltro)
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
        meta_periodo = _meta_presencial_periodo(periodo_idx)
        AZUL_LINHA = "#3299dd"
        AZUL_FILL = 'rgba(21,116,179,0.30)'
        VERM_LINHA = "#FF0000"
        VERM_FILL = 'rgba(211,47,47,0.30)'

        for area_nome, dados_area in medias_individuais.groupby('Área'):
            s = dados_area['Média Presença'].dropna()
            tem_abaixo = (s.min() < meta_periodo)
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
                type="line", xref="paper", yref="y", x0=0, x1=1, y0=meta_periodo, y1=meta_periodo,
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
        Input('periodo-indices', 'data'),
        Input('cargo-selecionado', 'data'),
        Input('areas-prefiltro', 'data'),
        Input('prefiltro-aplicado', 'data')
    )
    def atualizar_info(
        df_desligados,
        viajam,
        area_selecionada,
        subarea_selecionada,
        periodo_idx,
        cargo_prefiltro,
        areas_prefiltro,
        prefiltro_aplicado,
    ):
        if not prefiltro_aplicado:
            return html.Div()
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_df = _aplicar_prefiltros_inicio(media_df, cargo_prefiltro, areas_prefiltro)

        total_colaboradores = media_df['Cadastro'].nunique() if 'Cadastro' in media_df.columns else 0
        total_mensalistas = media_df[media_df['Cargo'] == 'M']['Cadastro'].nunique() if 'Cargo' in media_df.columns else 0
        total_executivos = media_df[media_df['Cargo'] == 'E']['Cadastro'].nunique() if 'Cargo' in media_df.columns else 0
        total_horistas = media_df[media_df['Cargo'] == 'H']['Cadastro'].nunique() if 'Cargo' in media_df.columns else 0
        total_terceiros = media_df[media_df['Cargo'] == 'T']['Cadastro'].nunique() if 'Cargo' in media_df.columns else 0
        media_presenca_geral = _media_ponderada(media_df)
        media_presenca_mensalistas = _media_ponderada(media_df, cargo='M')
        media_presenca_executivos = _media_ponderada(media_df, cargo='E')
        media_presenca_horistas = _media_ponderada(media_df, cargo='H')
        media_presenca_terceiros = _media_ponderada(media_df, cargo='T')
        meta_periodo = _meta_presencial_periodo(periodo_idx)

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

        def _sorted_rows_desc(items, formatter=lambda x: x, keep_first: bool = False):
            def _sort_key(item):
                num = _to_number(item[1])
                return (num is None, num if num is not None else 0)

            fixed = list(items[:1]) if keep_first and items else []
            sortable = list(items[1:]) if keep_first and items else list(items)
            items_sorted = sorted(sortable, key=_sort_key, reverse=True)
            numericos = [item for item in items_sorted if _to_number(item[1]) is not None]
            nao_numericos = [item for item in items_sorted if _to_number(item[1]) is None]
            return [
                html.Tr([html.Td(label), html.Td(formatter(value))])
                for label, value in fixed + numericos + nao_numericos
            ]

        colab_items = [
            ("Total de Colaboradores:", total_colaboradores),
            (f"{HORISTA_LABEL}:", total_horistas),
            (f"{TERCEIRO_LABEL}:", total_terceiros),
            ("Mensalistas:", total_mensalistas),
            ("Executivos:", total_executivos),
        ]
        presenca_items = [
            ("Total:", media_presenca_geral),
            (f"{HORISTA_LABEL}:", media_presenca_horistas),
            (f"{TERCEIRO_LABEL}:", media_presenca_terceiros),
            ("Mensalistas:", media_presenca_mensalistas),
            ("Executivos:", media_presenca_executivos),
        ]

        rows = (
            _sorted_rows_desc(colab_items, keep_first=True)
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
                keep_first=True,
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
        Input('periodo-indices', 'data'),
        Input('cargo-selecionado', 'data'),
        Input('areas-prefiltro', 'data'),
        Input('prefiltro-aplicado', 'data')
    )
    def atualizar_resumo(
        df_desligados,
        viajam,
        faixas,
        area_selecionada,
        subarea_selecionada,
        periodo_idx,
        cargo_prefiltro,
        areas_prefiltro,
        prefiltro_aplicado,
    ):
        if not prefiltro_aplicado:
            return html.Div()
        faixas = _normalizar_faixas(faixas)
        media_df = _media_colaboradores(
            df_desligados,
            viajam,
            area_selecionada,
            subarea_selecionada,
            periodo_idx,
        )
        media_df = _aplicar_prefiltros_inicio(media_df, cargo_prefiltro, areas_prefiltro)
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
            Qtd_Terceiros=('Cargo', lambda x: (x == 'T').sum()),
            Media_Dia=('Média Dia', 'mean')
        ).reset_index()
        resumo_area['Média Dia'] = resumo_area['Media_Dia'].round(2)
        meta_periodo = _meta_presencial_periodo(periodo_idx)
        resumo_area['Média %'] = resumo_area['Média Dia'].apply(
            lambda valor: _percentual_vs_meta(valor, meta_periodo)
        )
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
                            html.Th(HORISTA_LABEL, style=th_style('left', '0%')),
                            html.Th(TERCEIRO_LABEL, style=th_style('left', '0%')),
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
                            html.Td(_td_link_area(row['Qtd_Terceiros'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(row['Qtd_Pessoas'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(row['Média Dia'], row['Área']),
                                    style=td_style('left', '0%')),
                            html.Td(_td_link_area(f"{row['Média %']} %", row['Área']),
                                    style=td_style('left', '0%')),
                        ],
                        style={'color': _cor_vs_meta(row['Média Dia'], meta_periodo)})
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
