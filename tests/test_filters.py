import pandas as pd

from project.scripts.src.domain import filters as f


def test_normaliza_str_trims_and_handles_none():
    assert f.normaliza_str(None) == ""
    assert f.normaliza_str("  valor  ") == "valor"


def test_aplicar_filtro_por_area_respects_subareas():
    base = pd.DataFrame(
        {
            "Area": ["A1", "A1-Sub", "A2"],
            "Heranca": ["H1", "H1-1", "H2"],
        }
    )
    her_df = pd.DataFrame({"Area": ["A1", "A1-Sub"], "Heranca": ["H1", "H1-1"]})

    filtrado_area = f.aplicar_filtro_por_area(base, "A1", None, her_df)
    assert set(filtrado_area["Area"]) == {"A1", "A1-Sub"}

    filtrado_sub = f.aplicar_filtro_por_area(base, "A1", "A1-Sub", her_df)
    assert set(filtrado_sub["Area"]) == {"A1-Sub"}


def test_resolver_areas_viajantes_builds_prefix_sets():
    her_df = pd.DataFrame(
        {"Area": ["B-SNP", "B-SNP1"], "Heranca": ["H1", "H2"]}
    )
    areas, herancas = f.resolver_areas_viajantes(her_df, areas_base=["B-SNP"])

    assert "B-SNP" in areas
    assert "H1" in herancas


def test_filtrar_por_periodo_limits_date_range():
    df = pd.DataFrame(
        {"Data": pd.to_datetime(["2024-01-02", "2024-02-15", "2024-03-01"])}
    )
    filtrado = f.filtrar_por_periodo(df, "2024-01-15", "2024-02-20")

    assert filtrado["Data"].min() >= pd.Timestamp("2024-01-15")
    assert filtrado["Data"].max() <= pd.Timestamp("2024-02-20")
    assert len(filtrado) == 2
