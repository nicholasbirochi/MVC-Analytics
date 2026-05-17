import json
import unicodedata
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


ANALISE_DIR = Path(
    r"C:\Users\A1CLNDO\OneDrive - Volkswagen AG\Trabalho\Projetos\3 - Ronda"
    r"\Códigos Extras\Documentação\Análise sobre Possível Relacionamento Benéfico"
)
BASE_COMPLETA_PATH = ANALISE_DIR.parent / "Analisando Irregularidades dos Registros" / "df_ronda.parquet"
OUTPUT_XLSX = ANALISE_DIR / "analise_bvsp_sem_ponto_e_apos_17h.xlsx"
OUTPUT_IPYNB = ANALISE_DIR / "Analise_B-VSP_sem_ponto_e_apos_17h.ipynb"

AREA_PREFIXO = "B-VSP"
LIMITE_SEM_PONTO_MIN = 60
HORA_CORTE_APOS_17 = 17
BATCH_SIZE = 250_000

COLS_DESEJADAS = [
    "cadastro",
    "nome",
    "data",
    "hora",
    "dir",
    "planta",
    "descricao_coletor",
    "area",
    "cargo",
    "heranca",
    "desligado",
    "departamento",
    "tipo",
    "acesso",
]

REGEX_PORTARIA = (
    r"\bPORTARIA\b|\bPORT\.\b|\bPORT(?=[\.\-/ ])|\bCANCELA\b|\bGUARITA\b|"
    r"\bPEDESTRES?\b|\bVISITANTE\b|\bFUNCIONARIO\b|\bVEICULOS?\b"
)
REGEX_PONTO = r"\bMARCA\b|\bPONTO\b|\bPONT\b"


def normalizar_texto(valor):
    if pd.isna(valor):
        return ""
    texto = str(valor)
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return texto.upper().strip()


def colunas_existentes(parquet_path, colunas):
    pf = pq.ParquetFile(parquet_path)
    nomes = set(pf.schema.names)
    return [col for col in colunas if col in nomes]


def carregar_base_area(parquet_path, area_prefixo):
    pf = pq.ParquetFile(parquet_path)
    colunas = colunas_existentes(parquet_path, COLS_DESEJADAS)
    partes = []

    for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=colunas, use_threads=False):
        parte = batch.to_pandas()
        area = parte["area"].astype("string").str.strip()
        planta = parte["planta"].astype("string").str.strip()
        mascara = area.str.startswith(area_prefixo, na=False) & planta.ne("999")
        if mascara.any():
            partes.append(parte.loc[mascara].copy())

    if not partes:
        return pd.DataFrame(columns=colunas)

    return pd.concat(partes, ignore_index=True)


def preparar_base(df):
    df = df.rename(columns={"descricao_coletor": "descricao coletor"})

    for col in ["cadastro", "nome", "planta", "dir", "cargo", "heranca", "desligado", "area"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    df["_dir_norm"] = df["dir"].astype("string").str.upper().str.strip()

    data_dt = pd.to_datetime(df["data"], errors="coerce").dt.normalize()
    hora_s = df["hora"].astype("string").str.strip()
    hora_s = hora_s.replace({"": "00:00:00", "<NA>": "00:00:00", "nan": "00:00:00", "NaT": "00:00:00"})
    hora_s = hora_s.where(~hora_s.str.match(r"^\d{1,2}:\d{2}$", na=False), hora_s + ":00")
    hora_td = pd.to_timedelta(hora_s, errors="coerce")

    df["dia_analisado"] = data_dt
    df["_dt_ronda"] = data_dt + hora_td
    df["data_registro"] = data_dt.dt.strftime("%Y-%m-%d")
    df["hora_registro"] = df["_dt_ronda"].dt.strftime("%H:%M:%S")

    desc_norm = df["descricao coletor"].map(normalizar_texto)
    df["Portaria"] = desc_norm.str.contains(REGEX_PORTARIA, regex=True, na=False)
    df["Ponto"] = desc_norm.str.contains(REGEX_PONTO, regex=True, na=False)
    return df


def agregar_tempo(df, mascara, direcao, funcao, nome_coluna):
    filtro = mascara if direcao is None else mascara & df["_dir_norm"].eq(direcao)
    return (
        df.loc[filtro & df["_dt_ronda"].notna(), ["cadastro", "dia_analisado", "_dt_ronda"]]
        .groupby(["cadastro", "dia_analisado"], as_index=False)["_dt_ronda"]
        .agg(funcao)
        .rename(columns={"_dt_ronda": nome_coluna})
    )


def calcular_dias(df):
    dias = df[["cadastro", "nome", "dia_analisado"]].dropna().drop_duplicates()
    meta_cols = [c for c in ["cadastro", "nome", "area", "cargo", "heranca", "desligado"] if c in df.columns]
    meta = df[meta_cols].drop_duplicates("cadastro")
    dias = dias.merge(meta.drop(columns=["nome"]), on="cadastro", how="left")

    agregados = [
        agregar_tempo(df, df["Portaria"], "E", "min", "primeira_entrada_portaria"),
        agregar_tempo(df, df["Portaria"], "S", "max", "ultima_saida_portaria"),
        agregar_tempo(df, df["Ponto"], None, "min", "primeiro_ponto"),
        agregar_tempo(df, df["Ponto"], None, "max", "ultimo_ponto"),
    ]
    for agregado in agregados:
        dias = dias.merge(agregado, on=["cadastro", "dia_analisado"], how="left")

    antes = dias["primeiro_ponto"] - dias["primeira_entrada_portaria"]
    depois = dias["ultima_saida_portaria"] - dias["ultimo_ponto"]
    dias["min_antes_do_ponto"] = antes.dt.total_seconds().div(60).where(antes > pd.Timedelta(0), 0).fillna(0).round(2)
    dias["min_depois_do_ponto"] = depois.dt.total_seconds().div(60).where(depois > pd.Timedelta(0), 0).fillna(0).round(2)
    dias["min_total_sem_ponto"] = (dias["min_antes_do_ponto"] + dias["min_depois_do_ponto"]).round(2)
    dias["horas_total_sem_ponto"] = (dias["min_total_sem_ponto"] / 60).round(2)
    dias["ocorrencia_sem_ponto_maior_1h"] = dias["min_total_sem_ponto"].gt(LIMITE_SEM_PONTO_MIN)

    corte_17 = dias["dia_analisado"] + pd.Timedelta(hours=HORA_CORTE_APOS_17)
    inicio_apos_17 = dias["primeira_entrada_portaria"].where(dias["primeira_entrada_portaria"].gt(corte_17), corte_17)
    apos_17 = dias["ultima_saida_portaria"] - inicio_apos_17
    dias["min_apos_17h"] = apos_17.dt.total_seconds().div(60).where(apos_17 > pd.Timedelta(0), 0).fillna(0).round(2)
    dias["horas_apos_17h"] = (dias["min_apos_17h"] / 60).round(2)
    dias["ocorrencia_apos_17h"] = dias["min_apos_17h"].gt(0)

    dias["horas_total_dois_casos"] = (
        dias["horas_total_sem_ponto"].where(dias["ocorrencia_sem_ponto_maior_1h"], 0)
        + dias["horas_apos_17h"]
    ).round(2)

    dias["tipo_sem_ponto"] = pd.NA
    dias.loc[
        dias["ocorrencia_sem_ponto_maior_1h"]
        & dias["min_antes_do_ponto"].gt(0)
        & dias["min_depois_do_ponto"].gt(0),
        "tipo_sem_ponto",
    ] = "Antes e depois do ponto"
    dias.loc[
        dias["ocorrencia_sem_ponto_maior_1h"]
        & dias["min_antes_do_ponto"].gt(0)
        & dias["min_depois_do_ponto"].eq(0),
        "tipo_sem_ponto",
    ] = "Antes do ponto"
    dias.loc[
        dias["ocorrencia_sem_ponto_maior_1h"]
        & dias["min_antes_do_ponto"].eq(0)
        & dias["min_depois_do_ponto"].gt(0),
        "tipo_sem_ponto",
    ] = "Depois do ponto"

    return dias.sort_values(["nome", "dia_analisado"]).reset_index(drop=True)


def anexar_registros(df, eventos, cols_metricas):
    if eventos.empty:
        return df.iloc[0:0].copy()

    chaves = eventos[["cadastro", "dia_analisado"]].drop_duplicates()
    registros = df.merge(chaves, on=["cadastro", "dia_analisado"], how="inner")
    registros = registros.merge(eventos[cols_metricas], on=["cadastro", "dia_analisado"], how="left")
    ordem = [
        "cadastro",
        "nome",
        "area",
        "cargo",
        "heranca",
        "desligado",
        "dia_analisado",
        "data_registro",
        "hora_registro",
        "dir",
        "planta",
        "descricao coletor",
        "Portaria",
        "Ponto",
        "primeira_entrada_portaria",
        "primeiro_ponto",
        "ultimo_ponto",
        "ultima_saida_portaria",
        "min_antes_do_ponto",
        "min_depois_do_ponto",
        "min_total_sem_ponto",
        "horas_total_sem_ponto",
        "min_apos_17h",
        "horas_apos_17h",
        "horas_total_dois_casos",
        "tipo_sem_ponto",
    ]
    return registros[[c for c in ordem if c in registros.columns]].sort_values(["nome", "dia_analisado", "hora_registro"])


def montar_saidas(df, dias):
    dias_sem_ponto = dias.loc[dias["ocorrencia_sem_ponto_maior_1h"]].copy()
    dias_apos_17h = dias.loc[dias["ocorrencia_apos_17h"]].copy()
    dias_algum = dias.loc[dias["ocorrencia_sem_ponto_maior_1h"] | dias["ocorrencia_apos_17h"]].copy()

    cols_metricas = [
        "cadastro",
        "dia_analisado",
        "primeira_entrada_portaria",
        "primeiro_ponto",
        "ultimo_ponto",
        "ultima_saida_portaria",
        "min_antes_do_ponto",
        "min_depois_do_ponto",
        "min_total_sem_ponto",
        "horas_total_sem_ponto",
        "min_apos_17h",
        "horas_apos_17h",
        "horas_total_dois_casos",
        "tipo_sem_ponto",
    ]
    registros_sem_ponto = anexar_registros(df, dias_sem_ponto, cols_metricas)
    registros_apos_17h = anexar_registros(df, dias_apos_17h, cols_metricas)

    for col in ["horas_sem_ponto_contabil", "horas_apos_17h_contabil"]:
        if col in dias_algum.columns:
            dias_algum = dias_algum.drop(columns=[col])

    dias_algum["horas_sem_ponto_contabil"] = dias_algum["horas_total_sem_ponto"].where(
        dias_algum["ocorrencia_sem_ponto_maior_1h"],
        0,
    )
    dias_algum["horas_apos_17h_contabil"] = dias_algum["horas_apos_17h"].where(
        dias_algum["ocorrencia_apos_17h"],
        0,
    )

    meta_group = ["cadastro", "nome", "area", "cargo", "heranca", "desligado"]
    estatistica_geral = (
        dias_algum.groupby(meta_group, dropna=False)
        .agg(
            dias_com_algum_caso=("dia_analisado", "nunique"),
            dias_sem_ponto_maior_1h=("ocorrencia_sem_ponto_maior_1h", "sum"),
            horas_sem_ponto_maior_1h=("horas_sem_ponto_contabil", "sum"),
            dias_apos_17h=("ocorrencia_apos_17h", "sum"),
            horas_apos_17h=("horas_apos_17h_contabil", "sum"),
            horas_total_dois_casos=("horas_total_dois_casos", "sum"),
            primeiro_dia=("dia_analisado", "min"),
            ultimo_dia=("dia_analisado", "max"),
            max_horas_sem_ponto_dia=("horas_total_sem_ponto", "max"),
            max_horas_apos_17h_dia=("horas_apos_17h", "max"),
        )
        .reset_index()
        .sort_values(["horas_total_dois_casos", "dias_com_algum_caso"], ascending=False)
    )
    for col in [
        "horas_sem_ponto_maior_1h",
        "horas_apos_17h",
        "horas_total_dois_casos",
        "max_horas_sem_ponto_dia",
        "max_horas_apos_17h_dia",
    ]:
        estatistica_geral[col] = estatistica_geral[col].astype(float).round(2)

    dias_cols = [
        "cadastro",
        "nome",
        "area",
        "cargo",
        "heranca",
        "desligado",
        "dia_analisado",
        "primeira_entrada_portaria",
        "primeiro_ponto",
        "ultimo_ponto",
        "ultima_saida_portaria",
        "min_antes_do_ponto",
        "min_depois_do_ponto",
        "min_total_sem_ponto",
        "horas_total_sem_ponto",
        "min_apos_17h",
        "horas_apos_17h",
        "horas_total_dois_casos",
        "tipo_sem_ponto",
    ]
    return {
        "registros_sem_ponto": registros_sem_ponto,
        "dias_sem_ponto": dias_sem_ponto[[c for c in dias_cols if c in dias_sem_ponto.columns]].sort_values(
            ["nome", "dia_analisado"]
        ),
        "registros_apos_17h": registros_apos_17h,
        "dias_apos_17h": dias_apos_17h[[c for c in dias_cols if c in dias_apos_17h.columns]].sort_values(
            ["nome", "dia_analisado"]
        ),
        "estatistica_geral": estatistica_geral,
    }


def escrever_excel(saidas, resumo):
    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        saidas["registros_sem_ponto"].to_excel(writer, sheet_name="registros_sem_ponto", index=False)
        saidas["dias_sem_ponto"].to_excel(writer, sheet_name="dias_sem_ponto", index=False)
        saidas["registros_apos_17h"].to_excel(writer, sheet_name="registros_apos_17h", index=False)
        saidas["dias_apos_17h"].to_excel(writer, sheet_name="dias_apos_17h", index=False)
        saidas["estatistica_geral"].to_excel(writer, sheet_name="estatistica_geral", index=False)
        pd.DataFrame([resumo]).to_excel(writer, sheet_name="parametros", index=False)

    from openpyxl import load_workbook

    wb = load_workbook(OUTPUT_XLSX)
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for column_cells in ws.columns:
            col_letter = column_cells[0].column_letter
            max_len = max((len(str(cell.value)) for cell in column_cells[:200] if cell.value is not None), default=8)
            ws.column_dimensions[col_letter].width = min(max(max_len + 2, 10), 45)
    wb.save(OUTPUT_XLSX)


def criar_notebook():
    script = Path(__file__).read_text(encoding="utf-8")
    script = script.replace("criar_notebook()\n", "")
    nb = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": (
                    "# Analise B-VSP - sem ponto e apos 17h\n\n"
                    "Recorte: areas que comecam com `B-VSP`, removendo somente `planta == 999`."
                ),
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": script,
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUTPUT_IPYNB.write_text(json.dumps(nb, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    df = preparar_base(carregar_base_area(BASE_COMPLETA_PATH, AREA_PREFIXO))
    dias = calcular_dias(df)
    saidas = montar_saidas(df, dias)
    resumo = {
        "area": f"{AREA_PREFIXO}*",
        "filtro_planta": "planta != 999",
        "filtro_executivos": "nenhum; executivos incluidos",
        "criterio_sem_ponto": "min_antes_do_ponto + min_depois_do_ponto > 60",
        "criterio_apos_17h": "ultima_saida_portaria depois de 17h; horas de max(17h, primeira_entrada) ate ultima_saida",
        "linhas_area_filtrada": len(df),
        "pessoas_area_filtrada": int(df["cadastro"].nunique()),
        "dias_avaliados": len(dias),
        "dias_sem_ponto_maior_1h": len(saidas["dias_sem_ponto"]),
        "pessoas_sem_ponto_maior_1h": int(saidas["dias_sem_ponto"]["cadastro"].nunique())
        if not saidas["dias_sem_ponto"].empty
        else 0,
        "dias_apos_17h": len(saidas["dias_apos_17h"]),
        "pessoas_apos_17h": int(saidas["dias_apos_17h"]["cadastro"].nunique())
        if not saidas["dias_apos_17h"].empty
        else 0,
        "base_origem": str(BASE_COMPLETA_PATH),
    }
    escrever_excel(saidas, resumo)
    criar_notebook()
    print(resumo)
    print(saidas["estatistica_geral"].to_string(index=False))
    print(f"Excel: {OUTPUT_XLSX}")
    print(f"Notebook: {OUTPUT_IPYNB}")


if __name__ == "__main__":
    main()
