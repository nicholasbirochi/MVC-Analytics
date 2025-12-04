import importlib
import sys
import types

import pandas as pd
import pytest


def _make_stub_repo() -> types.ModuleType:
    repo = types.ModuleType("project.scripts.src.core.repo_global")

    repo.df_semana_merged = pd.DataFrame(
        {
            "Cadastro": ["1", "2"],
            "Nome": ["Alice", "Bob"],
            "Cargo": ["M", "E"],
            "Area": ["A1", "A1-Sub"],
            "Departamento": ["D1", "D1-1"],
            "Heranca": ["H1", "H1-1"],
            "Data": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        }
    )

    repo.df_datas = pd.DataFrame(
        {
            "Cadastro": ["1", "1"],
            "Data": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "Planta": ["P1", "P1"],
        }
    )

    repo.df_departamentos = pd.DataFrame(
        {
            "Cadastro": ["1", "2"],
            "Area": ["A1", "A1-Sub"],
            "Departamento": ["D1", "D1-1"],
            "Heranca": ["H1", "H1-1"],
        }
    )

    repo.df_almoco = pd.DataFrame(
        {
            "Cadastro": ["1", "1"],
            "Nome": ["Alice", "Alice"],
            "Hora": ["12:10:00", "12:25:00"],
            "Data": ["02/01/2024", "02/01/2024"],
            "Dir": ["E", "S"],
            "Descricao Coletor": ["Portaria", "Portaria"],
        }
    )

    repo.her = pd.DataFrame(
        {
            "Area": ["A1", "A1-Sub"],
            "Departamento": ["D1", "D1-1"],
            "Heranca": ["H1", "H1-1"],
        }
    )

    return repo


@pytest.fixture
def builders_module():
    """Load builders module with a stubbed repo_global to avoid parquet access."""
    repo = _make_stub_repo()
    sys.modules["project.scripts.src.core.repo_global"] = repo
    core_pkg = types.ModuleType("project.scripts.src.core")
    core_pkg.repo_global = repo
    sys.modules["project.scripts.src.core"] = core_pkg

    module = importlib.import_module("project.scripts.src.domain.builders")
    importlib.reload(module)
    module.repo = repo

    yield module

    for name in [
        "project.scripts.src.domain.builders",
        "project.scripts.src.core.repo_global",
        "project.scripts.src.core",
    ]:
        sys.modules.pop(name, None)
