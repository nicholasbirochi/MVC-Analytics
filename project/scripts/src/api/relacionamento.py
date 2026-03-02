"""relacionamento.py

Co-presença/relacionamento entre colaboradores e seleção de áreas/subáreas.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations
from dash import Input, Output, State, dcc, html, dash_table, no_update, ALL
from dash.exceptions import PreventUpdate
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from ..core.repo_global import df_datas, df_semana_merged, df_df_ativos, df_df_gptw, her
from ..ui.gptw import df_gptw_tabela_empilhada
from ..ui.theme import ESTILO_EXIBIR, ESTILO_OCULTO


estilo_exibir = ESTILO_EXIBIR
estilo_oculto = ESTILO_OCULTO


def register(app):
    def _people_base_df() -> pd.DataFrame:
        if {"Cadastro", "Nome"}.issubset(df_semana_merged.columns) and not df_semana_merged.empty:
            return df_semana_merged[["Cadastro", "Nome"]].copy()
        if {"Cadastro", "Nome"}.issubset(df_df_ativos.columns) and not df_df_ativos.empty:
            return df_df_ativos[["Cadastro", "Nome"]].copy()
        return pd.DataFrame(columns=["Cadastro", "Nome"])

    @app.callback(
        Output('tabela-df_gptw-rel', 'children'),
        Input('dropdown-area-df_gptw', 'value')
    )
    def renderizar_tabela_df_gptw(areas):
        # quando nada selecionado, retorna vazio (Div)
        return df_gptw_tabela_empilhada(areas, df_df_gptw=df_df_gptw, her_df=her)

    def add_calendar_stack(
        fig, semanas,
        week_font_size=11,
        month_font_size=12,
        year_font_size=12,
        month_as_number=True,
        month_y=-0.18,
        year_y=-0.30,
        bottom_margin=70,
        yshift_mes=-20,
        yshift_ano=-28
    ):
        if not semanas:
            return fig

        idx = pd.to_datetime(pd.Series(semanas)).sort_values().reset_index(drop=True)
        df = pd.DataFrame({"x": idx})
        iso = df['x'].dt.isocalendar()
        df['ano'] = iso.year.astype(int)
        df['sem_iso'] = iso.week.astype(int)
        df['mes'] = df['x'].dt.month

        # Ticks semanais (1..N reiniciando por ano)
        week_labels = []
        for _, g in df.groupby('ano', sort=True):
            g = g.sort_values('x').copy()
            seq_map = {w: i+1 for i, w in enumerate(g['sem_iso'].tolist())}
            week_labels.extend([str(seq_map[w]) for w in g['sem_iso']])

        fig.update_xaxes(
            type='date',
            tickmode='array',
            tickvals=df['x'],
            ticktext=week_labels,
            tickangle=0,
            tickfont=dict(size=week_font_size),
            ticks='outside',
            showgrid=True,
            gridcolor='rgba(0,0,0,0.06)'
        )

        x_first = df['x'].iloc[0]

        # MÊS
        for (_, m), g in df.groupby(['ano', 'mes'], sort=True):
            g = g.sort_values('x')
            x0, x1 = g['x'].iloc[0], g['x'].iloc[-1]
            xc = x0 + (x1 - x0) / 2
            mes_label = (str(m) if month_as_number else g['x'].dt.strftime('%b').iloc[0])

            fig.add_annotation(
                x=xc, y=month_y, yref='paper', yshift=yshift_mes,
                text=mes_label,
                showarrow=False,
                font=dict(size=month_font_size),
                xanchor='center', align='center'
            )
            if x0 != x_first:
                fig.add_vline(x=x0, line_color='rgba(0,0,0,0.20)', line_width=1.5)

        # ANO — rótulo central + linha pontilhada NA FRONTEIRA entre anos
        grupos = [(a, g.sort_values('x')) for a, g in df.groupby('ano', sort=True)]

        # 1) Rótulos centrados em cada ano
        for a, g in grupos:
            x0, x1 = g['x'].iloc[0], g['x'].iloc[-1]
            xc = x0 + (x1 - x0) / 2
            fig.add_annotation(
                x=xc, y=year_y, yref='paper', yshift=yshift_ano,
                text=str(a),
                showarrow=False,
                font=dict(size=year_font_size),
                xanchor='center', align='center'
            )

        # margem inferior para caber as anotações
        fig.update_layout(
            margin=dict(
                t=(fig.layout.margin.t if fig.layout.margin and fig.layout.margin.t else 110),
                r=20, b=bottom_margin, l=60
            )
        )
        return fig

    def aplicar_tags(fig, semanas, tags, dash='dot', width=4):
        """
        Desenha vlines pontilhadas e títulos no topo (paper y=1) para cada tag.
        - Encaixa a data da tag na semana mais próxima (SemIni), pra manter alinhamento.
        """
        if not semanas or not tags:
            return fig

        xs = pd.to_datetime(pd.Series(semanas)).sort_values().reset_index(drop=True)

        for t in (tags or []):
            data_str = (t or {}).get('data')
            nome     = (t or {}).get('nome') or ''
            cor      = (t or {}).get('cor')  or '#3221cc'

            try:
                dt = pd.to_datetime(data_str)
            except Exception:
                continue

            # acha a semana mais próxima
            idx = (xs - dt).abs().argmin()
            xline = xs.iloc[idx]

            fig.add_vline(x=xline, line_color=cor, line_dash=dash, line_width=width)
            if nome:
                fig.add_annotation(
                    x=xline, y=1, yref='paper', xref='x',
                    text=nome, showarrow=False,
                    xanchor='left', yanchor='bottom',
                    font=dict(color=cor, size=12),
                    bgcolor='rgba(255,255,255,0.6)'
                )
        return fig

    def _fmt_hex(c):
        """Normaliza para #RRGGBB; retorna None se inválido."""
        if c is None or str(c).strip() == "":
            return None
        s = str(c).strip().lower()
        if s.startswith("#"):
            s = s[1:]
        if len(s) == 3 and all(ch in "0123456789abcdef" for ch in s):
            s = "".join(ch*2 for ch in s)  # ex: #abc -> #aabbcc
        if len(s) == 6 and all(ch in "0123456789abcdef" for ch in s):
            return "#" + s
        # tenta rgb(a)
        if s.startswith("rgb"):
            try:
                nums = "".join(ch if ch.isdigit() or ch in ",." else " " for ch in s)
                r,g,b = [int(float(x)) for x in nums.split(",")[:3]]
                r,g,b = max(0,min(255,r)), max(0,min(255,g)), max(0,min(255,b))
                return f"#{r:02x}{g:02x}{b:02x}"
            except Exception:
                return None
        return None

    def _tag_pill(txt, cor_hex):
        cor = _fmt_hex(cor_hex) or "#999999"
        return html.Span(
            txt,
            style={
                "display": "inline-block",
                "padding": "2px 8px",
                "margin": "2px 4px 2px 0",
                "borderRadius": "10px",
                "fontSize": "12px",
                "border": "1px solid #111",
                "backgroundColor": cor,
                "color": "white",
                "lineHeight": "18px",
            }
        )

    def render_tags(df_tags):
        if df_tags is None or df_tags.empty:
            return html.Span("Sem tags")
        items = []
        for _, row in df_tags.iterrows():
            items.append(_tag_pill(str(row.get("tag", "")), row.get("cor")))
        return html.Div(items, style={"display": "flex", "flexWrap": "wrap"})

    @app.callback(
        Output("dropdown_df_gptw", "options"),
        Output("dropdown_df_gptw", "value"),
        Input("dropdown_df_gptw", "value"),
        prevent_initial_call=True
    )
    def atualizar_dropdown_df_gptw(valor_atual):
        df = df_df_gptw.copy()
        todas_areas = sorted(df["Área"].dropna().unique().tolist())

        # normaliza valor atual
        if not valor_atual:
            valor_atual = []
        elif isinstance(valor_atual, str):
            valor_atual = [valor_atual]
        valor_atual = [v.strip() for v in valor_atual]

        # mapeamento área → subáreas, se existir coluna
        if "Subarea" in df.columns:
            mapa = (
                df[["Área", "Subarea"]]
                .dropna()
                .groupby("Área")["Subarea"]
                .apply(set)
                .to_dict()
            )
        else:
            # fallback: considera prefixo (ex: B-I → B-IA, B-IE, ...)
            mapa = {a: {b for b in todas_areas if b.startswith(a) and b != a}
                    for a in todas_areas}

        # subáreas a remover
        ocultar = set()
        for area_sel in valor_atual:
            ocultar.update(mapa.get(area_sel, set()))

        # remove as subáreas da lista de opções
        visiveis = [a for a in todas_areas if a not in ocultar]
        opcoes = [{"label": a, "value": a} for a in visiveis]

        # também limpa do value qualquer item que tenha sido ocultado
        valor_filtrado = [v for v in valor_atual if v in visiveis]

        return opcoes, valor_filtrado

    @app.callback(
        Output('dropdown-area-df_gptw', 'value'),
        Input('dropdown-area-df_gptw', 'value'),
        Input('url', 'pathname'),
        State('dropdown-area-df_gptw', 'options'),
        prevent_initial_call=True
    )
    def atualizar_valor_areas(value, pathname, options):
        if not pathname or '/relacionamento' not in pathname:
            raise PreventUpdate

        # pega só os valores que ainda existem nas opções
        op_values = {opt['value'] for opt in (options or [])}
        novos = [v for v in (value or []) if v in op_values]
        return novos

    @app.callback(
        Output('rel-tags', 'data', allow_duplicate=True),
        Input('tag-tabela', 'active_cell'),
        State('tag-tabela', 'data'),
        State('rel-tags', 'data'),
        prevent_initial_call=True
    )
    def _delete_row(ac, rows, tags):
        if not ac or ac.get('column_id') != 'del':
            raise PreventUpdate
        idx = ac.get('row')
        if idx is None or idx < 0 or idx >= len(rows or []):
            raise PreventUpdate

        rid = rows[idx].get('id')
        novos = [t for t in (tags or []) if t.get('id') != rid]
        return novos

    @app.callback(
        Output('tag-tabela', 'data'),
        Input('rel-tags', 'data')
    )
    def _sync_table_from_store(tags):
        rows = []
        for t in (tags or []):
            nome   = t.get('nome', '')
            data   = t.get('data', '')
            corhex = t.get('cor', '#3221cc')

            # 🧹 Garante que a cor seja válida
            if not isinstance(corhex, str) or not corhex.startswith('#') or len(corhex) not in (4, 7):
                corhex = '#3221cc'  # cor padrão de fallback

            # 🗓️ converte data para DD/MM/YYYY
            try:
                data_br = pd.to_datetime(data).strftime('%d/%m/%Y')
            except Exception:
                data_br = ''

            # ✅ HTML seguro
            swatch = (
                f"<div style='display:inline-block;width:12px;height:12px;"
                f"border:1px solid #888;margin-left:6px;"
                f"background-color:{corhex};vertical-align:middle;'></div>"
            )

            rows.append({
                'id': t.get('id'),
                'nome_md': nome,
                'data_br': data_br,
                'cor': swatch,
                'del': "🗑️"
            })

        return rows

    @app.callback(
        Output('rel-tags', 'data', allow_duplicate=True),
        Output('tag-nome', 'value'),
        Output('tag-data', 'date'),
        Output('tag-cor',  'value'),
        Input('tag-add', 'n_clicks'),
        State('tag-nome', 'value'),
        State('tag-data', 'date'),
        State('tag-cor',  'value'),
        State('rel-tags', 'data'),
        prevent_initial_call=True
    )
    def _add_tag(n, nome, data_iso, cor, tags):
        tags = list(tags or [])
        if not data_iso:
            raise PreventUpdate

        novo = {
            'id':   str(time.time()),      # <— id único
            'nome': (nome or 'Evento'),
            'data': str(data_iso),         # 'YYYY-MM-DD'
            'cor':  (cor  or '#3221cc')
        }
        tags.append(novo)
        return tags, "", None, "#3221cc"

    @app.callback(
        Output('rel-tags', 'data', allow_duplicate=True),
        Input('tag-tabela', 'data'),
        State('rel-tags', 'data'),
        prevent_initial_call=True
    )
    def _sync_store_from_table(rows, tags):
        # tags atuais no store
        tags = list(tags or [])
        by_id = {t["id"]: t for t in tags}

        # percorre as linhas da tabela e atualiza só o que mudou
        for r in (rows or []):
            rid = r.get("id")
            if rid in by_id:
                # data
                data_iso = None
                if r.get("data_br"):
                    try:
                        data_iso = pd.to_datetime(r["data_br"], dayfirst=True).strftime("%Y-%m-%d")
                    except Exception:
                        data_iso = None

                by_id[rid]["data"] = data_iso
                by_id[rid]["cor"]  = r.get("cor") or by_id[rid].get("cor")

                # se quiser permitir mudar o nome direto na tabela:
                nome_md = r.get("nome_md") or ""
                # tira o ** ... ** se o usuário não tirou
                nome_limpo = nome_md.replace("**", "").strip()
                if nome_limpo:
                    by_id[rid]["nome"] = nome_limpo

        # MUITO IMPORTANTE: devolve TODAS as tags (não só as da tabela)
        return list(by_id.values())

    @app.callback(
        Output('dropdown-pessoas-rel', 'options'),
        Input('url', 'pathname')
    )
    def carregar_opcoes_pessoas(_):
        df_p = (_people_base_df()
                .dropna()
                .drop_duplicates())
        df_p['Cadastro'] = df_p['Cadastro'].astype(str)
        df_p = df_p.sort_values('Nome')

        # Exclusivo de pessoas, com rótulo "CHAPA - NOME"
        return [
            {'label': f"{row['Cadastro']} - {row['Nome']}",
             'value': f"PESSOA::{row['Cadastro']}"}
            for _, row in df_p.iterrows()
        ]

    @app.callback(
        Output('cores-pessoas-container', 'children'),
        Input('dropdown-pessoas-rel', 'value')
    )
    def gerar_inputs_cor(selecionados):
        if not selecionados:
            return []
        pessoas_ids = [v for v in selecionados if isinstance(v, str) and v.startswith("PESSOA::")]
        if not pessoas_ids:
            return []

        cad_to_nome = (_people_base_df()
                       .drop_duplicates()
                       .assign(Cadastro=lambda d: d['Cadastro'].astype(str))
                       .set_index('Cadastro')['Nome']
                       .to_dict())

        def label_pessoa(pid):
            cad = pid.split("PESSOA::",1)[1]
            nome = cad_to_nome.get(cad, cad)
            return f"{nome} ({cad})"

        return [
            html.Div([
                html.Label(label_pessoa(pid)),
                dcc.Input(
                    type='color',
                    id={'type':'cor-pessoa','index':pid},
                    value=f"#{np.random.randint(0, 0xFFFFFF):06x}",
                    debounce=True,
                    style={'marginLeft':'10px','width':'60px'}
                )
            ], style={'display':'flex','alignItems':'center','justifyContent':'space-between', 'gap':'8px'})
            for pid in pessoas_ids
        ]

    @app.callback(
        Output('grafico-relacionamento-linhas', 'figure'),
        Output('grafico-mini-media-movel', 'figure'),
        Input('dropdown-pessoas-rel', 'value'),
        Input({'type':'cor-pessoa','index': ALL}, 'value'),
        Input('rel-tags', 'data'),
    )
    def atualizar_graficos(selecionados, cores, tags):
        def fig_msg(msg):
            f = go.Figure()
            f.update_layout(template="plotly_white", title=msg)
            return f

        # 🔒 1) deixa as tags sempre válidas
        def sanitize_tags(tag_list):
            fixed = []
            for t in (tag_list or []):
                cor = t.get("cor") or "#3221cc"
                # se vier '#fff' tá ok, se vier 'fff' corrige, se vier 'white' troca
                if isinstance(cor, str):
                    cor = cor.strip()
                    if not cor:
                        cor = "#3221cc"
                    elif not cor.startswith("#"):
                        # veio 'white' ou 'red' -> força padrão
                        cor = "#3221cc"
                    elif len(cor) not in (4, 7):
                        cor = "#3221cc"
                else:
                    cor = "#3221cc"

                fixed.append({
                    "id":   t.get("id"),
                    "nome": t.get("nome", "Evento"),
                    "data": t.get("data"),
                    "cor":  cor,
                })
            return fixed

        tags = sanitize_tags(tags)
        # 🔒 fim sanitização

        # ------------------ seleção ------------------
        pessoas_ids = [v for v in (selecionados or []) if isinstance(v, str) and v.startswith("PESSOA::")]
        cad_list = [pid.split("PESSOA::",1)[1] for pid in pessoas_ids]
        if len(cad_list) == 0:
            msg = fig_msg("Selecione pelo menos 1 pessoa")
            return msg, fig_msg("—")

        # ------------------ base df_datas segura ------------------
        if 'df_datas' not in globals() or not isinstance(globals()['df_datas'], pd.DataFrame):
            info = fig_msg("Base df_datas ausente")
            return info, fig_msg("—")

        dfp = globals()['df_datas'].copy()
        if 'Data' not in dfp.columns:
            info = fig_msg("df_datas sem coluna 'Data'")
            return info, fig_msg("—")

        dfp['Cadastro'] = dfp['Cadastro'].astype(str)
        dfp['Data'] = pd.to_datetime(dfp['Data'], errors='coerce').dt.normalize()
        dfp = dfp.dropna(subset=['Data'])
        dfp = dfp[dfp['Cadastro'].isin(cad_list)]
        if dfp.empty:
            info = fig_msg("Sem registros de presença para as pessoas selecionadas")
            return info, fig_msg("—")

        # ------------------ nomes ------------------
        cad_to_nome = (_people_base_df()
                       .drop_duplicates()
                       .assign(Cadastro=lambda d: d['Cadastro'].astype(str))
                       .set_index('Cadastro')['Nome']
                       .to_dict())

        # ------------------ semana ISO ------------------
        iso = dfp['Data'].dt.isocalendar()
        dfp['AnoISO'] = iso.year.astype(int)
        dfp['SemISO'] = iso.week.astype(int)
        dfp['SemIni'] = pd.to_datetime(
            dfp['AnoISO'].astype(str) + dfp['SemISO'].astype(str).str.zfill(2) + '1',
            format='%G%V%u', errors='coerce'
        )

        # ------------------ séries: presença semanal ------------------
        semanas = sorted(dfp['SemIni'].dropna().unique())
        presenca_semana = {}
        for cad in cad_list:
            s = (dfp[dfp['Cadastro']==cad]
                 .groupby('SemIni')['Data'].nunique()
                 .reindex(semanas, fill_value=0)
                 .astype(float))
            presenca_semana[cad] = s

        # ------------------ FIG 1 ------------------
        fig_pres = go.Figure()
        cores_map_by_pid = {}
        if isinstance(cores, list):
            for i, pid in enumerate(pessoas_ids):
                c = cores[i] if i < len(cores) else None
                if isinstance(c, str) and c.strip():
                    cores_map_by_pid[pid] = c.strip()

        for cad in cad_list:
            pid = f"PESSOA::{cad}"
            nome = cad_to_nome.get(cad, cad)
            cor = cores_map_by_pid.get(pid, None)
            hover = (nome + "<br>Semana: %{x|%Y-%m-%d}"
                     + "<br>Dias presentes: %{y:.0f}<extra></extra>")
            fig_pres.add_trace(go.Scatter(
                x=semanas,
                y=presenca_semana[cad].values,
                mode='lines+markers',
                name=nome,
                line=(dict(width=2, **({'color': cor} if cor else {}))),
                hovertemplate=hover
            ))

        fig_pres.update_layout(
            template="plotly_white",
            title="Presenças semanais (dias)",
            xaxis_title="",
            yaxis_title="Dias presentes",
            showlegend=False,
            margin=dict(t=110, r=20, b=60, l=60)
        )

        # ------------------ ENCONTROS (% vs referência) → minis ------------------
        ref = cad_list[0]
        outros = cad_list[1:]
        ref_nome = cad_to_nome.get(ref, ref)

        # mapa por semana: conjuntos de datas por pessoa (sem planta)
        def mapa_datas_por_semana(df):
            out = {}
            for sem, g in df.groupby('SemIni'):
                g = g[['Cadastro','Data']].dropna()
                out[sem] = {cad: set(gc['Data'].tolist()) for cad, gc in g.groupby('Cadastro')}
            return out

        mapa = mapa_datas_por_semana(dfp)
        semanas_mapa = sorted(mapa.keys())  # garante ordem a partir do mapa

        # Série: média do percentual de encontros (0–100) por semana
        pct_medias = []
        for sem in semanas_mapa:
            d = mapa.get(sem, {})
            datas_ref = d.get(ref, set())
            pcts = []
            for cad in outros:
                datas_outro = d.get(cad, set())
                denom = len(datas_outro)
                if denom > 0:
                    num = len(datas_ref & datas_outro)
                    pcts.append(100.0 * num / denom)
            # média entre "outros" que tiveram presença na semana
            if len(pcts) == 0:
                pct_medias.append(float('nan'))
            else:
                pct_medias.append(round(float(np.nanmean(pcts)), 2))

        # --- depois de calcular serie_pct / mm3_pct ---
        serie_pct = pd.Series(pct_medias, index=semanas_mapa).astype(float).round(2)
        mm3_pct = serie_pct.rolling(window=3, min_periods=1).mean().round(2)

        # 1) reindexa pro mesmo eixo X do gráfico de cima
        mm3_pct = mm3_pct.reindex(semanas)

        # 2) constrói o mini usando o mesmo X
        fig_mini_movel = go.Figure()
        fig_mini_movel.add_trace(go.Scatter(
            x=semanas,                      # <- mesmo X do fig_pres
            y=list(mm3_pct.values),
            mode='lines',
            line_shape='spline',            # (opcional) linha lisa
            line=dict(width=2),
            name=f'% encontros vs {ref_nome}'
        ))

        # 2) fixa o mesmo range de X em ambos
        common_x_range = [semanas[0], semanas[-1]] if len(semanas) else None
        fig_pres.update_xaxes(type='date', range=common_x_range, showgrid=True, gridcolor='rgba(0,0,0,0.05)')
        fig_mini_movel.update_xaxes(type='date', range=common_x_range, showgrid=True, gridcolor='rgba(0,0,0,0.05)')


        # 3) (opcional) hover e margens iguais para “casar” visualmente
        fig_pres.update_layout(hovermode='x unified')
        fig_mini_movel.update_layout(
            template="plotly_white",
            title="Média móvel",
            xaxis_title="", yaxis_title="Percentual",
            yaxis=dict(ticksuffix="%", rangemode="tozero"),
            showlegend=False,
            hovermode='x unified',
            margin=dict(t=110, r=20, b=60, l=60)  # use as mesmas laterais do fig_pres
        )

        # (garante que ambos usam o mesmo range já definido por você)
        common_x_range = [semanas[0], semanas[-1]] if len(semanas) else None
        fig_pres.update_xaxes(type='date', range=common_x_range, showgrid=True, gridcolor='rgba(0,0,0,0.05)')
        fig_mini_movel.update_xaxes(type='date', range=common_x_range, showgrid=True, gridcolor='rgba(0,0,0,0.05)')

        # >>> AQUI: adiciona as 3 camadas de rótulos
        fig_pres = add_calendar_stack(
            fig_pres, semanas,
            week_font_size=8,month_font_size=12, year_font_size=14,
            month_as_number=True,  # mantém como está
            month_y=-0.18,
            year_y=-0.30,
            bottom_margin=100,  # posições atuais (perfeito)
            yshift_mes=-8,
            yshift_ano=-15
        )

        fig_mini_movel = add_calendar_stack(
            fig_mini_movel, semanas,
            week_font_size=8, month_font_size=10, year_font_size=12,
            month_as_number=True,
            month_y=-0.28,   # ↓ desce os meses
            year_y=-0.42,    # ↓ desce ainda mais os anos
            bottom_margin=90,  # dá espaço para as duas linhas baixas
            yshift_mes=-18,
            yshift_ano=-25
        )

        # --- TAG (linha vertical) robusta ---
        fig_pres       = aplicar_tags(fig_pres, semanas, tags, dash='dot', width=4)
        fig_mini_movel = aplicar_tags(fig_mini_movel, semanas, tags, dash='dot', width=4)

        # opcional: manter hover unificado
        fig_pres.update_layout(hovermode='x unified')
        fig_mini_movel.update_layout(hovermode='x unified')

        # Sempre 2 figuras:
        return fig_pres, fig_mini_movel

    @app.callback(
        Output('dropdown-area-df_gptw', 'options'),
        Input('dropdown-area-df_gptw', 'value'),
        Input('url', 'pathname')
    )
    def atualizar_opcoes_areas(selecionadas, pathname):
        if not pathname or '/relacionamento' not in pathname:
            raise PreventUpdate

        # todas as áreas conhecidas
        if 'Área' in df_df_ativos.columns:
            todas = sorted(df_df_ativos['Área'].dropna().unique().tolist())
        else:
            todas = (
                sorted(df_semana_merged['Área'].dropna().unique().tolist())
                if 'Área' in df_semana_merged.columns
                else []
            )

        her_df = globals().get('her', pd.DataFrame())
        selecionadas = [str(a).strip() for a in (selecionadas or [])]

        # função recursiva: obtém descendentes
        def descendentes(area):
            if not isinstance(her_df, pd.DataFrame) or her_df.empty or not {'Área', 'Heranca'}.issubset(her_df.columns):
                return [a for a in todas if a != area and a.startswith(area)]
            filhos = her_df.loc[her_df['Heranca'] == area, 'Área'].astype(str).tolist()
            netos = []
            for f in filhos:
                netos.extend(descendentes(f))
            return filhos + netos

        # remove descendentes das áreas selecionadas
        ocultar = set()
        for mae in selecionadas:
            ocultar.update(descendentes(mae))

        visiveis = [a for a in todas if a not in ocultar]
        return [{'label': a, 'value': a} for a in visiveis]

    @app.callback(
        Output('url', 'pathname', allow_duplicate=True),
        Input('botao-voltar-relacionamento', 'n_clicks'),
        prevent_initial_call=True
    )
    def voltar_home(n_clicks):
        if n_clicks:
            return '/'
        raise PreventUpdate

    @app.callback(
        Output('conteudo-relacionamento', 'children'),
        Output('conteudo-relacionamento', 'style'),
        Output('pagina-geral', 'style', allow_duplicate=True),
        Input('url', 'pathname'),
        prevent_initial_call=True
    )
    def exibir_relacionamento(pathname):
        # Se a URL atual for a aba de relacionamentos → mostra conteúdo
        if pathname and '/relacionamento' in pathname:
            conteudo = html.Div([
                # Sequenciador de loading da aba Relacionamento
                dcc.Store(id='rel-load-step', data=0),
                dcc.Interval(id='rel-load-interval', interval=500, n_intervals=0, disabled=False, max_intervals=2),

                # Cabeçalho
                html.Div([
                    html.Button("Voltar", id='botao-voltar-relacionamento', n_clicks=0, style={
                        'color': 'Black', 'fontFamily': 'VW Text', 'fontWeight': 'bold', 'margin': '0',
                        'display': 'inline-block', 'padding': '10px 20px', 'fontSize': '14px',
                        'backgroundColor': '#e0e0e0', 'border': 'none', 'borderRadius': '5px',
                        'cursor': 'pointer', 'boxShadow': '0px 2px 6px rgba(0,0,0,0.25)'
                    }),
                    html.H2("Relacionamento entre Colaboradores", style={
                        'margin': '0', 'fontFamily': 'VW Text', 'fontWeight': 'bold', 'textAlign': 'center', 'flex': '1'
                    }),
                    html.Div(style={'width': '120px'})
                ], style={
                    'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between',
                    'margin': '10px 0 10px 10px', 'gap': '12px', 'width': '100%'
                }),

                # Seletor (pessoas/áreas) + gráfico de linhas
                html.Div([
                    html.Div([
                        html.Label("Selecionar pessoas"),
                        dcc.Dropdown(
                            id='dropdown-pessoas-rel',
                            options=[], value=[], multi=True, placeholder='Busque pessoas…',
                            style={'width': '300px'}
                        ),
                        html.Div(id='cores-pessoas-container', style={'marginTop': '8px'}),

                        html.Div([
                            html.Hr(),
                            html.Label("Adicionar evento:"),
                            html.Br(),

                            dcc.Input(id='tag-nome', type='text', placeholder='Nome do evento',
                                      style={'width': '70%', 'marginBottom': '6px'}),

                            dcc.Input(id='tag-cor', type='color', value="#3221cc",
                                      style={'width': '70px', 'marginLeft': '8px', 'verticalAlign': 'middle'}),

                            html.Br(),

                            html.Div([
                                dcc.DatePickerSingle(
                                    id='tag-data',
                                    display_format='DD/MM/YYYY',
                                    placeholder='Data',
                                    clearable=True,
                                    date=None,
                                    className='dp-compact',
                                    style={'width': '120px'}
                                ),
                                html.Button("Adicionar evento", id='tag-add', n_clicks=0,
                                            style={'marginLeft': '45px', 'height': '36px',
                                                   'padding': '0 10px', 'whiteSpace': 'nowrap'}),
                            ], style={
                                'display': 'flex', 'alignItems': 'center', 'gap': '8px', 'flexWrap': 'wrap'
                            }),

                            dash_table.DataTable(
                                id='tag-tabela',
                                columns=[
                                    {'name': 'Nome', 'id': 'nome_md', 'editable': False},
                                    {'name': 'Data', 'id': 'data_br', 'editable': True},
                                    {'name': 'Cor', 'id': 'cor', 'presentation': 'markdown', 'editable': False},
                                    {'name': '', 'id': 'del', 'presentation': 'markdown', 'editable': False},
                                ],
                                data=[],
                                markdown_options={'html': True},
                                row_deletable=False,
                                style_table={'marginTop': '8px', 'minWidth': '280px'},
                                style_cell={'fontFamily': 'VW Text', 'fontSize': '14px', 'padding': '6px'},
                                style_header={'backgroundColor': '#f0f0f0', 'fontWeight': 'bold', 'textAlign': 'center'},
                                style_data={'whiteSpace': 'nowrap'},
                                style_cell_conditional=[
                                    {'if': {'column_id': 'nome_md'}, 'textAlign': 'left', 'width': '60%'},
                                    {'if': {'column_id': 'data_br'}, 'textAlign': 'center', 'width': '20%'},
                                    {'if': {'column_id': 'cor'}, 'textAlign': 'center', 'width': '15%'},
                                    {'if': {'column_id': 'del'}, 'textAlign': 'center', 'width': '5%'},
                                ],
                            ),
                            dcc.Store(id='rel-tags', data=[])
                        ], style={'marginTop': '10px'})
                    ], style={'flex': '0 0 300px'}),

                    html.Div([
                        dcc.Loading(
                            id='loading-rel-main',
                            children=dcc.Graph(id='grafico-relacionamento-linhas',
                                               style={'height': '420px', 'marginBottom': '16px'})
                        ),
                        dcc.Loading(
                            id='loading-rel-mini',
                            children=dcc.Graph(id='grafico-mini-media-movel',
                                               style={'height': '300px', 'flex': '1', 'minWidth': '260px'})
                        )
                    ], style={'flex': '1', 'minWidth': '360px', 'paddingLeft': '24px'})
                ], style={
                    'display': 'flex', 'gap': '24px', 'alignItems': 'flex-start',
                    'padding': '16px', 'boxSizing': 'border-box', 'backgroundColor': "#e0e0e0",
                    'borderRadius': '8px', 'boxShadow': '0px 3px 6px rgba(0,0,0,0.1)', 'flexWrap': 'wrap'
                }),

                # GPTW
                html.Div([
                    html.Div([
                        dcc.Dropdown(
                            id='dropdown-area-df_gptw',
                            options=[], value=[], multi=True, placeholder='Selecione áreas…',
                            style={'minWidth': '260px', 'maxWidth': '520px', 'width': '100%', 'margin': '0'}
                        ),
                    ], style={'marginBottom': '10px', 'display': 'flex'}),
                    html.Div(id='tabela-df_gptw-rel', style={'display': 'flex', 'justifyContent': 'center'})
                ], style={'padding': '16px', 'background': '#fff', 'borderRadius': '12px', 'margin': '10px'})
            ], style={'padding': '10px', 'backgroundColor': 'white'})

            # mostra a aba e esconde a home
            return conteudo, {'display': 'block'}, {'display': 'none'}

        # Quando está em qualquer outra página
        return no_update, {'display': 'none'}, {'display': 'flex', 'flexDirection': 'column', 'width': '100%',
                                                     'height': '100%', 'backgroundColor': "#ffffff", 'padding': '16px',
                                                     'boxSizing': 'border-box'
                                                     }
