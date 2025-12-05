"""Controller para reproduzir o fluxo do notebook unificado."""
from __future__ import annotations

from ..models.data_access import load_data
from ..models.attendance import recorte_presenca
from ..views.cli_display import describe_data_inventory, describe_frames


def run_sample(area: str | None = "GERAL", subarea: str | None = None, periodo_idx=None, max_rows: int = 5) -> None:
    """Executa o fluxo de exemplo (presença e almoço) e exibe no CLI."""
    data = load_data()
    describe_data_inventory(data)
    recortes = recorte_presenca(area=area, subarea=subarea, periodo_idx=periodo_idx, data=data)
    describe_frames(recortes, max_rows=max_rows)
