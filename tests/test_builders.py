def _contagem_col(df):
    for col in df.columns:
        if "Contagem" in col:
            return col
    raise AssertionError("Contagem column not found")


def test_build_dataframe_diario_area(builders_module):
    df = builders_module.build_dataframe_diario_area(
        area="A1",
        subarea=None,
        her_df=builders_module.repo.her,
        df_datas_local=builders_module.repo.df_datas,
        df_dept=builders_module.repo.df_departamentos,
        dt_ini="2024-01-01",
        dt_fim="2024-01-05",
    )

    assert not df.empty
    assert {"Cadastro", "Data"}.issubset(df.columns)
    cont_col = _contagem_col(df)
    assert df[cont_col].max() >= 1


def test_build_dataframe_almoco_area(builders_module):
    df = builders_module.build_dataframe_almoco_area(
        area="A1",
        subarea=None,
        her_df=builders_module.repo.her,
        df_almoco_local=builders_module.repo.df_almoco,
        df_dept=builders_module.repo.df_departamentos,
        dt_ini="2024-01-01",
        dt_fim="2024-01-05",
    )

    assert not df.empty
    assert df["Cadastro"].nunique() == 1
    cont_col = _contagem_col(df)
    assert df[cont_col].max() == 1


def test_cache_key_and_is_valid(builders_module):
    key = builders_module.cache_key("a", "b", "c", "d", 1, 2)
    assert key == ("a", "b", "c", "d", 1, 2)

    options = [{"value": "ok"}]
    assert builders_module.is_valid("ok", options)
    assert not builders_module.is_valid("missing", options)
