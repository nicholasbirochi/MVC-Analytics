"""theme.py

Tema e padrões visuais para componentes e gráficos.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations


# Estilos utilitários ---------------------------------------------------------
VW_FONT_FAMILY = "'VW Text', Arial, sans-serif"
VW_PLOTLY_FONT = "VW Text"
GLOBAL_CSS = f"""
@font-face {{
  font-family: 'VW Text';
  src: local('VW Text');
}}
* {{
  font-family: {VW_FONT_FAMILY} !important;
}}
"""

ESTILO_OCULTO = {"display": "none"}
ESTILO_EXIBIR = {
    "display": "block",
    "padding": "20px",
    "backgroundColor": "white",
}

ORDENACAO_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
DIAS_PORTUGUES = {
    "Monday": "Segunda",
    "Tuesday": "Terça",
    "Wednesday": "Quarta",
    "Thursday": "Quinta",
    "Friday": "Sexta",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}


def aplicar_tema_pb(fig, *, largura_borda=2, so_y_boxplot=False, grade=False, clean=False):
    """Aplica tema preto/branco aos gráficos Plotly."""
    fig.update_layout(
        template=None,
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=60, r=30, t=60, b=50),
        font=dict(family=VW_PLOTLY_FONT, color="#000000"),
        hoverlabel=dict(font=dict(family=VW_PLOTLY_FONT)),
    )

    # Garante fonte VW na legenda sem sobrescrever outras configs de legenda.
    try:
        legend_dict = fig.layout.legend.to_plotly_json() if fig.layout.legend else {}
        legend_font = (legend_dict.get("font") or {})
        legend_font["family"] = VW_PLOTLY_FONT
        legend_dict["font"] = legend_font
        fig.update_layout(legend=legend_dict)
    except Exception:
        pass

    if so_y_boxplot:
        fig.update_xaxes(
            showline=True,
            linewidth=largura_borda,
            linecolor="black",
            mirror=True,
            ticks="outside",
            tickcolor="black",
            zeroline=True,
            zerolinecolor="black",
            showgrid=False,
        )
        fig.update_yaxes(
            showline=True,
            linewidth=largura_borda,
            linecolor="black",
            mirror=True,
            ticks="outside",
            tickcolor="black",
            zeroline=True,
            zerolinecolor="black",
            gridcolor="#a7a7a7",
        )
    else:
        if grade:
            fig.update_xaxes(
                showline=True,
                linewidth=largura_borda,
                linecolor="black",
                mirror=True,
                ticks="outside",
                tickcolor="black",
                zeroline=False,
                showgrid=False,
            )
            fig.update_yaxes(
                showline=True,
                linewidth=largura_borda,
                linecolor="black",
                mirror=True,
                ticks="outside",
                tickcolor="black",
                zeroline=False,
                gridcolor="#a7a7a7",
                griddash="dot",
            )
        else:
            if clean:
                fig.update_xaxes(
                    showline=True,
                    linewidth=largura_borda,
                    linecolor="black",
                    mirror=True,
                    ticks="outside",
                    tickcolor="black",
                    zeroline=False,
                    showgrid=False,
                )
                fig.update_yaxes(
                    showline=True,
                    linewidth=largura_borda,
                    linecolor="black",
                    mirror=True,
                    ticks="outside",
                    tickcolor="black",
                    zeroline=False,
                    showgrid=False,
                )
            else:
                fig.update_xaxes(
                    showline=True,
                    linewidth=largura_borda,
                    linecolor="black",
                    mirror=True,
                    ticks="outside",
                    tickcolor="black",
                    zeroline=True,
                    zerolinecolor="black",
                    gridcolor="#a7a7a7",
                )
                fig.update_yaxes(
                    showline=True,
                    linewidth=largura_borda,
                    linecolor="black",
                    mirror=True,
                    ticks="outside",
                    tickcolor="black",
                    zeroline=True,
                    zerolinecolor="black",
                    gridcolor="#a7a7a7",
                )

    return fig
