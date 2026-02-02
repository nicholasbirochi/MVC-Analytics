"""builders.py

Builders para preparar data marts e agregações.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import repo_global as repo
from .filters import normalizar_str


def build_df_count_por_semana(df_semana_merged: pd.DataFrame) -> pd.DataFrame:
    """Conta presenca por dia da semana (heatmap geral)."""
    if "Dia Semana" in df_semana_merged.columns:
        out = (
            df_semana_merged.groupby(
                [
                    "Cadastro",
                    "Nome",
                    "Area",
                    "Departamento",
                    "Heranca",
                    "Cargo Especifico",
                    "Desligado",
                ]
            )["Dia Semana"]
            .value_counts()
            .reset_index()
        )
        out.columns = [
            "Cadastro",
            "Nome",
            "Area",
            "Departamento",
            "Heranca",
            "Cargo Especifico",
            "Desligado",
            "Dia Semana",
            "Contagem Presença",
        ]
        return out
    return pd.DataFrame(
        columns=[
            "Cadastro",
            "Nome",
            "Area",
            "Departamento",
            "Heranca",
            "Cargo Especifico",
            "Desligado",
            "Dia Semana",
            "Contagem Presença",
        ]
    )


def build_her(df_semana_merged: pd.DataFrame) -> pd.DataFrame:
    """Construtor da tabela de heranca de areas para dropdowns."""
    if df_semana_merged is None or df_semana_merged.empty:
        return pd.DataFrame(columns=["Area", "Departamento", "Heranca"])
    return (
        df_semana_merged[["Area", "Departamento", "Heranca"]]
        .drop_duplicates()
        .sort_values("Area")
    )


def build_dropdown_options(her_df: pd.DataFrame) -> list[dict]:
    """Opcoes de area/subarea para os filtros iniciais."""
    if her_df is None or her_df.empty:
        return [{"label": "Geral (todas as areas)", "value": "GERAL"}]
    base = [
        {
            "label": "Geral (todas as areas)",
            "value": "GERAL",
        }
    ]
    opts = [
        {"label": f"{row['Area']} {row['Departamento']}", "value": row["Area"]}
        for _, row in her_df.iterrows()
    ]
    return base + opts


def get_area(pathname: str | None) -> tuple[str | None, str | None]:
    if not pathname or "/area/" not in pathname:
        return None, None
    base = pathname.split("/area/", 1)[1]
    if "?" in base:
        areaslug, query = base.split("?", 1)
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        dep = normalizar_str(params.get("dep")) if "dep" in params else None
    else:
        areaslug, dep = base, None
    return normalizar_str(areaslug), dep


def _empty_diario() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "Data",
            "Cadastro",
            "Nome",
            "Cargo",
            "Area",
            "Departamento",
            "Planta",
            "Contagem Presença",
        ]
    )


def _normalize_many(*dfs: pd.DataFrame) -> None:
    for df in dfs:
        if df is None:
            continue
        for col in ("Heranca", "Area", "Departamento", "Cadastro"):
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()


def build_dataframe_diario_area(
    area: str | None,
    subarea: str | None,
    her_df: pd.DataFrame | None = None,
    df_datas_local: pd.DataFrame | None = None,
    df_dept: pd.DataFrame | None = None,
    dt_ini: pd.Timestamp | str | None = None,
    dt_fim: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    her_df = her_df.copy() if her_df is not None else repo.her.copy()
    df_datas_local = (
        df_datas_local.copy() if df_datas_local is not None else repo.df_datas.copy()
    )
    df_dept = (
        df_dept.copy() if df_dept is not None else repo.df_df_ativos.copy()
    )

    if her_df is None or her_df.empty or df_datas_local is None or df_datas_local.empty:
        return _empty_diario()

    _normalize_many(her_df, df_dept, df_datas_local)
    alvo = subarea or area

    if alvo:
        if "Area" in df_dept.columns:
            if subarea:
                mask_area = df_dept["Area"].eq(alvo)
            else:
                mask_area = df_dept["Area"].str.contains(str(area), case=False, na=False)
            base_dept = df_dept.loc[mask_area, ["Cadastro", "Area", "Departamento"]].drop_duplicates()
        else:
            base_dept = pd.DataFrame(columns=["Cadastro", "Area", "Departamento"])

        if base_dept.empty:
            herancas = (
                her_df.loc[her_df["Area"].eq(alvo), "Heranca"].dropna().unique()
                if {"Area", "Heranca"}.issubset(her_df.columns)
                else []
            )
            if not herancas and {"Area", "Heranca"}.issubset(her_df.columns):
                herancas = (
                    her_df[
                        her_df["Area"].str.contains(str(alvo), case=False, na=False)
                    ]["Heranca"]
                    .dropna()
                    .unique()
                )
            if not herancas:
                return _empty_diario()
            starts_any = lambda h: any(str(h).startswith(p) for p in herancas)
            if "Heranca" in df_dept.columns:
                mask = df_dept["Heranca"].apply(starts_any)
                base_dept = df_dept.loc[mask, ["Cadastro", "Area", "Departamento"]].drop_duplicates()
            else:
                base_dept = df_dept.loc[mask_area, ["Cadastro", "Area", "Departamento"]].drop_duplicates()
    else:
        base_dept = df_dept[["Cadastro", "Area", "Departamento"]].drop_duplicates()

    if base_dept.empty:
        return _empty_diario()

    ref_cols = ["Cadastro", "Nome", "Cargo"]
    df_ref = repo.df_semana_merged[ref_cols].drop_duplicates()
    chaves = base_dept.merge(df_ref, on="Cadastro", how="left")

    dfp = df_datas_local[df_datas_local["Cadastro"].isin(chaves["Cadastro"])].copy()
    if dfp.empty:
        return _empty_diario()

    dfp["Data"] = pd.to_datetime(dfp["Data"], errors="coerce")
    dfp = dfp.dropna(subset=["Data"])

    if dt_ini is not None and dt_fim is not None:
        dt_ini = pd.Timestamp(dt_ini).normalize()
        dt_fim = pd.Timestamp(dt_fim).normalize()
        dfp = dfp[(dfp["Data"] >= dt_ini) & (dfp["Data"] <= dt_fim)]
    if dfp.empty:
        return _empty_diario()

    datas = pd.date_range(
        dfp["Data"].min().normalize(), dfp["Data"].max().normalize(), freq="D"
    )
    cad_unicos = chaves["Cadastro"].unique()
    grade = (
        pd.MultiIndex.from_product([datas, cad_unicos], names=["Data", "Cadastro"])
        .to_frame(index=False)
        .merge(chaves, on="Cadastro", how="left")
    )

    pres = (
        dfp.sort_values("Data")
        .groupby(["Cadastro", "Data"], as_index=False)
        .agg(
            Planta=(
                "Planta",
                lambda s: s.dropna().iloc[-1] if s.dropna().size else np.nan,
            )
        )
    )
    pres["Contagem Presença"] = 1

    df_full = (
        grade.merge(pres, on=["Cadastro", "Data"], how="left")
        .fillna({"Contagem Presença": 0})
        .sort_values(["Cadastro", "Data"])
    )
    df_full["Contagem Presença"] = df_full["Contagem Presença"].astype(int)

    for col in ["Nome", "Cargo", "Area", "Departamento"]:
        if col not in df_full.columns:
            df_full[col] = np.nan

    return df_full


def build_dataframe_almoco_area(
    area: str | None,
    subarea: str | None,
    her_df: pd.DataFrame | None = None,
    df_almoco_local: pd.DataFrame | None = None,
    df_dept: pd.DataFrame | None = None,
    dt_ini: pd.Timestamp | str | None = None,
    dt_fim: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    if df_almoco_local is None or df_almoco_local.empty:
        return pd.DataFrame(
            columns=[
                "Data",
                "Cadastro",
                "Nome",
                "Cargo",
                "Area",
                "Departamento",
                "Planta",
                "Contagem Presença",
            ]
        )

    her_df = her_df.copy() if her_df is not None else repo.her.copy()
    df_dept = (
        df_dept.copy() if df_dept is not None else repo.df_df_ativos.copy()
    )

    _normalize_many(her_df, df_dept)
    alvo = subarea or area

    base_dept = pd.DataFrame(columns=["Cadastro", "Area", "Departamento"])
    if "Area" in df_dept.columns:
        if subarea:
            mask_area = df_dept["Area"].eq(alvo)
        else:
            mask_area = df_dept["Area"].str.contains(str(area), case=False, na=False)
        base_dept = df_dept.loc[mask_area, ["Cadastro", "Area", "Departamento"]].drop_duplicates()

    if base_dept.empty and alvo:
        herancas = (
            her_df.loc[her_df["Area"].eq(alvo), "Heranca"].dropna().unique()
            if {"Area", "Heranca"}.issubset(her_df.columns)
            else []
        )
        if not herancas and {"Area", "Heranca"}.issubset(her_df.columns):
            herancas = (
                her_df[
                    her_df["Area"].str.contains(str(alvo), case=False, na=False)
                ]["Heranca"]
                .dropna()
                .unique()
            )
        if herancas and "Heranca" in df_dept.columns:
            mask = df_dept["Heranca"].apply(lambda h: any(str(h).startswith(p) for p in herancas))
            base_dept = df_dept.loc[mask, ["Cadastro", "Area", "Departamento"]].drop_duplicates()

    if base_dept.empty:
        return pd.DataFrame(
            columns=[
                "Data",
                "Cadastro",
                "Nome",
                "Cargo",
                "Area",
                "Departamento",
                "Planta",
                "Contagem Presença",
            ]
        )

    ref_cols = ["Cadastro", "Nome", "Cargo"]
    df_ref = repo.df_semana_merged[ref_cols].drop_duplicates()
    chaves = base_dept.merge(df_ref, on="Cadastro", how="left")
    cad_ok = set(chaves["Cadastro"].astype(str))

    df = df_almoco_local.copy()
    df.columns = df.columns.str.strip()
    for col in ("Nome", "Dir", "Descricao Coletor", "Cadastro"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    df = df[df["Cadastro"].astype(str).isin(cad_ok)].copy()

    df["Data"] = pd.to_datetime(df["Data"], dayfirst=True, errors="coerce")
    horas_raw = df["Hora"].astype(str).str.strip()
    df["Hora"] = pd.to_datetime(horas_raw, format="%H:%M:%S", errors="coerce")
    df.loc[df["Hora"].isna(), "Hora"] = pd.to_datetime(
        horas_raw, format="%H:%M", errors="coerce"
    )
    df = df.dropna(subset=["Data", "Hora", "Dir"])
    df["Data_norm"] = df["Data"].dt.normalize()

    h_ini = pd.to_datetime("11:00:00", format="%H:%M:%S").time()
    h_fim = pd.to_datetime("14:00:00", format="%H:%M:%S").time()
    df = df[(df["Hora"].dt.time >= h_ini) & (df["Hora"].dt.time <= h_fim)]
    df = df[df["Dir"].isin(["E", "S"])]

    if dt_ini is not None and dt_fim is not None:
        dt_ini = pd.Timestamp(dt_ini).normalize()
        dt_fim = pd.Timestamp(dt_fim).normalize()
        df = df[(df["Data"] >= dt_ini) & (df["Data"] <= dt_fim)]
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Data",
                "Cadastro",
                "Nome",
                "Cargo",
                "Area",
                "Departamento",
                "Planta",
                "Contagem Presença",
            ]
        )

    def cluster_por_janela(group: pd.DataFrame, chave_prefix: str, janela_min: int = 3) -> pd.DataFrame:
        group = group.sort_values("Hora").copy()
        tmins = (
            group["Hora"].dt.hour * 60
            + group["Hora"].dt.minute
            + group["Hora"].dt.second / 60.0
        )
        novo = (tmins.diff().fillna(9999) >= janela_min).astype(int).cumsum()
        group["_cluster"] = (
            group["Data_norm"].dt.strftime("%Y-%m-%d")
            + "|"
            + chave_prefix
            + "|"
            + novo.astype(str)
        )
        return group

    parts: list[pd.DataFrame] = []

    def normalizar_coletor(desc: str | None) -> str:
        if not isinstance(desc, str):
            return "NA"
        desc_low = desc.lower().strip()
        if "ref" in desc_low:
            return desc_low
        if "port" in desc_low:
            return "portaria"
        return desc_low

    if {"Descricao Coletor"}.issubset(df.columns):
        df["Descricao Agrupada"] = df["Descricao Coletor"].apply(normalizar_coletor)
        for (_, _, col_norm), group in df[df["Dir"] == "E"].groupby(
            ["Data_norm", "Dir", "Descricao Agrupada"], dropna=False
        ):
            chave = f"E|{col_norm if pd.notna(col_norm) else 'NA'}"
            janela_min = 1 if str(col_norm).startswith("ref") else 3
            parts.append(cluster_por_janela(group, chave, janela_min))
    else:
        for _, group in df[df["Dir"] == "E"].groupby(["Data_norm", "Dir"]):
            parts.append(cluster_por_janela(group, "E", 3))

    for _, group in df[df["Dir"] == "S"].groupby(["Data_norm", "Dir"]):
        parts.append(cluster_por_janela(group, "S"))

    if not parts:
        return pd.DataFrame(
            columns=[
                "Data",
                "Cadastro",
                "Nome",
                "Cargo",
                "Area",
                "Departamento",
                "Planta",
                "Contagem Presença",
            ]
        )

    dfc = pd.concat(parts, ignore_index=True)
    clusters = (
        dfc.groupby(["Data_norm", "Cadastro"])["_cluster"]
        .apply(lambda s: frozenset(s.dropna().unique().tolist()))
        .reset_index()
    )
    clusters.rename(columns={"Data_norm": "Data"}, inplace=True)

    out = clusters.merge(chaves, on="Cadastro", how="left")
    out["Contagem Presença"] = out["_cluster"].apply(lambda st: int(len(st) > 0))
    out = out.rename(columns={"_cluster": "Planta"})
    out["Data"] = pd.to_datetime(out["Data"], errors="coerce")
    out["Planta"] = out["Planta"].apply(
        lambda x: x if isinstance(x, (set, frozenset)) else frozenset()
    )

    for col in ["Nome", "Cargo", "Area", "Departamento"]:
        if col not in out.columns:
            out[col] = np.nan

    pres_por_dia = out.groupby("Data")["Cadastro"].nunique().reset_index(name="qtde")
    dias_com_encontros = set(pres_por_dia.loc[pres_por_dia["qtde"] > 1, "Data"])
    out = out[out["Data"].isin(dias_com_encontros)]

    return out[
        [
            "Data",
            "Cadastro",
            "Nome",
            "Cargo",
            "Area",
            "Departamento",
            "Planta",
            "Contagem Presença",
        ]
    ]


def obter_heranca_do_cadastro(
    cad_exec: str | None,
    df_dept: pd.DataFrame | None = None,
    her_df: pd.DataFrame | None = None,
) -> str | None:
    if cad_exec is None:
        return None
    cad_exec = str(cad_exec)
    df_dept = df_dept if df_dept is not None else repo.df_df_ativos
    her_df = her_df if her_df is not None else repo.her

    if "Cadastro" in df_dept.columns:
        linha = df_dept[df_dept["Cadastro"].astype(str).eq(cad_exec)]
        if not linha.empty:
            if "Heranca" in df_dept.columns and pd.notna(linha.iloc[0].get("Heranca")):
                return str(linha.iloc[0]["Heranca"]).strip()
            if "Area" in df_dept.columns and pd.notna(linha.iloc[0].get("Area")):
                area_exec = str(linha.iloc[0]["Area"]).strip()
                if {"Area", "Heranca"}.issubset(her_df.columns):
                    her = her_df.loc[
                        her_df["Area"].astype(str).eq(area_exec), "Heranca"
                    ]
                    if not her.empty:
                        return str(her.iloc[0]).strip()
    return None


def obter_area_do_cadastro(
    cad: str | None,
    df_dept: pd.DataFrame | None = None,
) -> str | None:
    if not cad:
        return None
    df_dept = df_dept if df_dept is not None else repo.df_df_ativos
    linha = df_dept[df_dept["Cadastro"].astype(str).eq(str(cad))]
    if linha.empty:
        return None
    area = linha.iloc[-1].get("Area", None)
    return None if pd.isna(area) else str(area).strip()


def cache_key(
    area_base,
    subarea_sel,
    df_desligados_area,
    viajam_area,
    i0,
    i1,
) -> tuple:
    return (
        str(area_base or ""),
        str(subarea_sel or ""),
        str(df_desligados_area or ""),
        str(viajam_area or ""),
        int(i0 if isinstance(i0, (int, np.integer)) else 0),
        int(i1 if isinstance(i1, (int, np.integer)) else 0),
    )


def is_valid(val, options) -> bool:
    if val is None or options in (None,):
        return False
    return any(opt.get("value") == val for opt in options or [])
