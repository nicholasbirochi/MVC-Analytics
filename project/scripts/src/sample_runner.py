"""CLI para reproduzir o fluxo do notebook via MVC controllers."""
from __future__ import annotations

from .mvc.controllers.sample_controller import run_sample


if __name__ == "__main__":
    run_sample(area="GERAL", subarea=None, periodo_idx=None, max_rows=5)
