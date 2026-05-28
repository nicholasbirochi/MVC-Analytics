from pathlib import Path
import re
import shutil
import unicodedata

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]

RAW_BASE_DIR = PROJECT_ROOT / "Base de Dados Original"
CSV_DIR = RAW_BASE_DIR / "csv" / "Ajustes Manuais"
PARQUET_DIR = RAW_BASE_DIR / "parquet" / "Ajustes Manuais"

AJUSTES_PATH = PARQUET_DIR / "df_ajustes_manuais.parquet"
RONDA_FINAL_PATH = PROJECT_ROOT / "project" / "database" / "df_ronda.parquet"
RONDA_TEMP_PATH = RONDA_FINAL_PATH.with_name(f"{RONDA_FINAL_PATH.name}.tmp")

# Saidas mantidas por compatibilidade com a analise desta pasta.
LEGACY_PARQUET_DIR = SCRIPT_DIR / "base" / "parquet"
LEGACY_AJUSTES_PATH = LEGACY_PARQUET_DIR / "df_ajustes_manuais.parquet"
LEGACY_RONDA_PATH = LEGACY_PARQUET_DIR / "df_ronda.parquet"

CHAPAS_VALIDACAO = [
    "2038897",
    "3000011",
    "4021525",
    "4034525",
    "4065785",
    "4065787",
]

CSV_KEY_TO_OUTPUT = {
    "CHAPA": "CHAPA",
    "CODIGO_RELOGIO": "CODIGO_RELOGIO",
    "DESCRICAO_RELOGIO": "DESCRICAO_RELOGIO",
    "DESCRI_AO_RELOGIO": "DESCRICAO_RELOGIO",
    "DESCRIAO_RELOGIO": "DESCRICAO_RELOGIO",
    "NOME_FUNCIONARIO": "NOME_COLABORADOR",
    "NOME_COLABORADOR": "NOME_COLABORADOR",
    "FILIAL": "FILIAL",
    "DATA_ACESSO": "DATA_ACESSO",
    "HORA_ACESSO": "HORA_ACESSO",
    "SEQUENCIA_ACESSO": "SEQUENCIA_ACESSO",
    "DIRACAO_ACESSO": "DIRECAO_ACESSO",
    "DIRECAO_ACESSO": "DIRECAO_ACESSO",
    "TIPO_ACESSO": "TIPO_ACESSO",
    "USO_MARCACAO": "USO_MARCACAO",
    "USO_MARCA_O": "USO_MARCACAO",
    "USU_MARCACAO": "USO_MARCACAO",
    "USU_MARCA_O": "USO_MARCACAO",
    "PLANTA": "CODIGO_PLANTA",
    "CODIGO_PLANTA": "CODIGO_PLANTA",
}

OUTPUT_COLUMNS = [
    "CHAPA",
    "CODIGO_RELOGIO",
    "DESCRICAO_RELOGIO",
    "NOME_COLABORADOR",
    "FILIAL",
    "DATA_ACESSO",
    "HORA_ACESSO",
    "SEQUENCIA_ACESSO",
    "DIRECAO_ACESSO",
    "TIPO_ACESSO",
    "USO_MARCACAO",
    "CODIGO_PLANTA",
]

CATEGORY_CARGO = {
    "Executivos": "E",
    "Mensalistas": "M",
    "Horistas": "H",
    "Terceiros": "T",
}

CHUNK_SIZE = 500_000
ARROW_SCHEMA = pa.schema([(column, pa.string()) for column in OUTPUT_COLUMNS])

BASE_FIELDS = [
    ("cadastro", pa.string()),
    ("nome", pa.string()),
    ("filial", pa.string()),
    ("data", pa.timestamp("ns")),
    ("hora", pa.time64("us")),
    ("dir", pa.string()),
    ("tipo", pa.string()),
    ("acesso", pa.string()),
    ("planta", pa.string()),
    ("coletor", pa.string()),
    ("descricao_coletor", pa.string()),
    ("uso_acesso", pa.string()),
    ("cargo", pa.string()),
    ("desligado", pa.string()),
    ("area", pa.string()),
    ("departamento", pa.string()),
    ("heranca", pa.string()),
    ("cargo_especifico", pa.string()),
]
BASE_COLS = [name for name, _ in BASE_FIELDS]
FULL_SCHEMA = pa.schema(BASE_FIELDS + [("Manual", pa.string())])


def normalize_column_key(value):
    text = str(value).strip().upper()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def normalize_chunk(chunk, csv_file):
    rename_map = {}
    for column in chunk.columns:
        output = CSV_KEY_TO_OUTPUT.get(normalize_column_key(column))
        if output:
            rename_map[column] = output

    frame = chunk.rename(columns=rename_map)
    missing = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(
            f"Colunas ausentes em {csv_file.name}: {missing}. "
            f"Colunas encontradas: {list(chunk.columns)}"
        )
    return frame.reindex(columns=OUTPUT_COLUMNS).astype("string")


def write_adjustment_parquet(csv_file, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    writer = pq.ParquetWriter(
        output_path,
        ARROW_SCHEMA,
        compression="snappy",
        use_dictionary=True,
    )
    total = 0
    try:
        reader = pd.read_csv(
            csv_file,
            encoding="latin1",
            dtype=str,
            keep_default_na=False,
            chunksize=CHUNK_SIZE,
        )
        for chunk in reader:
            frame = normalize_chunk(chunk, csv_file)
            table = pa.Table.from_pandas(frame, schema=ARROW_SCHEMA, preserve_index=False)
            writer.write_table(table)
            total += table.num_rows
    finally:
        writer.close()
    return total


def discover_categories():
    categories = []
    for category in CATEGORY_CARGO:
        folder = CSV_DIR / category
        if folder.exists() and any(folder.glob("*.csv")):
            categories.append(category)
    return categories


def convert_all_adjustment_csvs():
    categories = discover_categories()
    if not categories:
        raise FileNotFoundError(f"Nenhum CSV de ajuste manual encontrado em {CSV_DIR}")

    summary = {}
    for category in categories:
        source_files = sorted((CSV_DIR / category).glob("*.csv"))
        summary[category] = {}
        print(f"\nConvertendo {category}")
        for csv_file in source_files:
            output_path = PARQUET_DIR / category / f"{csv_file.stem}.parquet"
            count = write_adjustment_parquet(csv_file, output_path)
            summary[category][output_path.name] = count
            print(f"- {csv_file.name}: {count:,} linhas")
    return summary


def consolidate_adjustments():
    selects = []
    for category, cargo in CATEGORY_CARGO.items():
        files = sorted((PARQUET_DIR / category).glob("*.parquet"))
        if not files:
            continue
        source_glob = (PARQUET_DIR / category / "*.parquet").resolve().as_posix()
        selects.append(
            f"""
            SELECT
              REGEXP_REPLACE(TRIM(CAST(CHAPA AS VARCHAR)), '\\\\.0$', '') AS cadastro,
              CAST(NOME_COLABORADOR AS VARCHAR) AS nome,
              CAST(FILIAL AS VARCHAR) AS filial,
              COALESCE(
                TRY_STRPTIME(TRIM(CAST(DATA_ACESSO AS VARCHAR)), '%m/%d/%Y'),
                TRY_STRPTIME(TRIM(CAST(DATA_ACESSO AS VARCHAR)), '%d/%m/%Y'),
                TRY_CAST(DATA_ACESSO AS TIMESTAMP)
              ) AS data,
              CAST(
                TIME '00:00:00'
                + (
                    (TRY_CAST(HORA_ACESSO AS BIGINT) % 1440)
                    * INTERVAL 1 MINUTE
                  )
                AS TIME
              ) AS hora,
              CAST(DIRECAO_ACESSO AS VARCHAR) AS dir,
              CAST(TIPO_ACESSO AS VARCHAR) AS tipo,
              CAST(SEQUENCIA_ACESSO AS VARCHAR) AS acesso,
              CAST(CODIGO_PLANTA AS VARCHAR) AS planta,
              CAST(CODIGO_RELOGIO AS VARCHAR) AS coletor,
              CAST(DESCRICAO_RELOGIO AS VARCHAR) AS descricao_coletor,
              CAST(USO_MARCACAO AS VARCHAR) AS uso_acesso,
              '{cargo}' AS cargo,
              CAST(NULL AS VARCHAR) AS desligado,
              CAST(NULL AS VARCHAR) AS area,
              CAST(NULL AS VARCHAR) AS departamento,
              CAST(NULL AS VARCHAR) AS heranca,
              CAST(NULL AS VARCHAR) AS cargo_especifico
            FROM read_parquet('{source_glob}', union_by_name=true)
            WHERE DATA_ACESSO IS NOT NULL
              AND HORA_ACESSO IS NOT NULL
              AND TRY_CAST(HORA_ACESSO AS BIGINT) IS NOT NULL
            """
        )

    if not selects:
        raise FileNotFoundError(f"Nenhum parquet de ajuste manual encontrado em {PARQUET_DIR}")

    manual_sql = "\nUNION ALL\n".join(selects)
    temp_path = AJUSTES_PATH.with_name(f"{AJUSTES_PATH.name}.tmp")
    if temp_path.exists():
        temp_path.unlink()

    with duckdb.connect(":memory:") as con:
        con.execute("PRAGMA threads=4")
        con.execute(
            f"""
            COPY (
              SELECT *
              FROM ({manual_sql})
              WHERE cadastro IS NOT NULL
                AND cadastro <> ''
                AND data IS NOT NULL
                AND hora IS NOT NULL
            ) TO '{temp_path.as_posix()}' (FORMAT PARQUET, COMPRESSION SNAPPY)
            """
        )

    temp_path.replace(AJUSTES_PATH)


def schema_has_manual(path):
    return "Manual" in pq.ParquetFile(path).schema_arrow.names


def sql_select_base_without_manual(source_path):
    fields = []
    for name, field_type in BASE_FIELDS:
        if pa.types.is_timestamp(field_type):
            fields.append(f"CAST({name} AS TIMESTAMP) AS {name}")
        elif pa.types.is_time64(field_type):
            fields.append(f"CAST({name} AS TIME) AS {name}")
        else:
            fields.append(f"CAST({name} AS VARCHAR) AS {name}")

    where = ""
    if schema_has_manual(source_path):
        where = """
        WHERE COALESCE(UPPER(TRIM(CAST("Manual" AS VARCHAR))), '') <> 'SIM'
        """

    return f"""
        SELECT
          {", ".join(fields)},
          'Não' AS "Manual"
        FROM read_parquet('{source_path.resolve().as_posix()}', union_by_name=true)
        {where}
    """


def sql_select_manual_adjustments():
    fields = []
    for name, field_type in BASE_FIELDS:
        if pa.types.is_timestamp(field_type):
            fields.append(f"CAST({name} AS TIMESTAMP) AS {name}")
        elif pa.types.is_time64(field_type):
            fields.append(f"CAST({name} AS TIME) AS {name}")
        else:
            fields.append(f"CAST({name} AS VARCHAR) AS {name}")

    return f"""
        SELECT
          {", ".join(fields)},
          'Sim' AS "Manual"
        FROM read_parquet('{AJUSTES_PATH.resolve().as_posix()}', union_by_name=true)
    """


def build_ronda_with_manual():
    if not RONDA_FINAL_PATH.exists():
        raise FileNotFoundError(f"Base final df_ronda nao encontrada: {RONDA_FINAL_PATH}")
    if RONDA_TEMP_PATH.exists():
        RONDA_TEMP_PATH.unlink()

    base_sql = sql_select_base_without_manual(RONDA_FINAL_PATH)
    manual_sql = sql_select_manual_adjustments()

    with duckdb.connect(":memory:") as con:
        con.execute("PRAGMA threads=4")
        con.execute(
            f"""
            COPY (
              {base_sql}
              UNION ALL
              {manual_sql}
            ) TO '{RONDA_TEMP_PATH.resolve().as_posix()}'
            (FORMAT PARQUET, COMPRESSION SNAPPY)
            """
        )

    RONDA_TEMP_PATH.replace(RONDA_FINAL_PATH)

    with duckdb.connect(":memory:") as con:
        original_rows, manual_rows = con.execute(
            f"""
            SELECT
              SUM(CASE WHEN UPPER(TRIM(CAST("Manual" AS VARCHAR))) = 'SIM' THEN 0 ELSE 1 END),
              SUM(CASE WHEN UPPER(TRIM(CAST("Manual" AS VARCHAR))) = 'SIM' THEN 1 ELSE 0 END)
            FROM read_parquet('{RONDA_FINAL_PATH.resolve().as_posix()}')
            """
        ).fetchone()
    return int(original_rows or 0), int(manual_rows or 0)


def sync_legacy_outputs():
    LEGACY_PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(AJUSTES_PATH, LEGACY_AJUSTES_PATH)
    shutil.copy2(RONDA_FINAL_PATH, LEGACY_RONDA_PATH)

    for category in CATEGORY_CARGO:
        source = PARQUET_DIR / category
        if source.exists():
            destination = LEGACY_PARQUET_DIR / category
            shutil.copytree(source, destination, dirs_exist_ok=True)


def validate_chapas():
    chapas_sql = ",".join(f"'{chapa}'" for chapa in CHAPAS_VALIDACAO)
    with duckdb.connect(":memory:") as con:
        print("\nChapas no df_ajustes_manuais.parquet:")
        print(
            con.execute(
                f"""
                SELECT cadastro, any_value(nome) AS nome, any_value(cargo) AS cargo,
                       count(*) AS linhas,
                       min(CAST(data AS DATE)) AS primeira_data,
                       max(CAST(data AS DATE)) AS ultima_data
                FROM read_parquet('{AJUSTES_PATH.resolve().as_posix()}')
                WHERE CAST(cadastro AS VARCHAR) IN ({chapas_sql})
                GROUP BY cadastro
                ORDER BY cadastro
                """
            ).fetchdf().to_string(index=False)
        )

        print("\nManual no df_ronda.parquet final:")
        print(
            con.execute(
                f"""
                SELECT cadastro, "Manual", any_value(nome) AS nome, any_value(cargo) AS cargo,
                       count(*) AS linhas,
                       min(CAST(data AS DATE)) AS primeira_data,
                       max(CAST(data AS DATE)) AS ultima_data
                FROM read_parquet('{RONDA_FINAL_PATH.resolve().as_posix()}')
                WHERE CAST(cadastro AS VARCHAR) IN ({chapas_sql})
                GROUP BY cadastro, "Manual"
                ORDER BY cadastro, "Manual"
                """
            ).fetchdf().to_string(index=False)
        )


def print_file_stats():
    for path in [AJUSTES_PATH, RONDA_FINAL_PATH, LEGACY_RONDA_PATH]:
        pf = pq.ParquetFile(path)
        print(
            f"{path}: {pf.metadata.num_rows:,} linhas, "
            f"{path.stat().st_size / 1024 / 1024:.2f} MB"
        )


def main():
    if not CSV_DIR.exists():
        raise FileNotFoundError(f"Pasta de CSV nao encontrada: {CSV_DIR}")

    convert_all_adjustment_csvs()

    print("\nConsolidando Base de Dados Original/parquet/Ajustes Manuais/df_ajustes_manuais.parquet...")
    consolidate_adjustments()

    print("Reconstruindo project/database/df_ronda.parquet com coluna Manual...")
    linhas_original, linhas_manual = build_ronda_with_manual()
    print(f"- Original Manual=Nao: {linhas_original:,} linhas")
    print(f"- Ajustes Manual=Sim: {linhas_manual:,} linhas")

    print("Sincronizando copias legadas da analise de ajustes manuais...")
    sync_legacy_outputs()

    print_file_stats()
    validate_chapas()


if __name__ == "__main__":
    main()
