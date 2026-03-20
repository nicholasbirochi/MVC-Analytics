# Base de Dados Original

Este diretorio concentra as bases de entrada em formatos `csv`, `parquet` e `xlsx`.

## Estrutura completa

```text
Base de Dados Original/
├── readme.md
├── csv/
│   ├── Executivos/
│   │   ├── Executivos_01-01-2024_03-31-2025.csv
│   │   ├── Executivos_04-01-2025_09-30-2025.csv
│   │   └── Executivos_10-01-2025_12-31-2025.csv
│   │
│   ├── Horistas/
│   │   ├── Horistas_01-01-2024_12-31-2024.csv
│   │   └── Horistas_01-01-2025_12-31-2025.csv
│   │
│   └── Mensalistas/
│       ├── Mensalistas_01-01-2024_03-31-2025.csv
│       ├── Mensalistas_04-01-2025_09-30-2025.csv
│       └── Mensalistas_10-01-2025_12-31-2025.csv
│
├── parquet/
│   ├── Ativos/
│   │   └── Ativos.parquet
│   │
│   ├── Desligados/
│   │   └── Desligados.parquet
│   │
│   ├── Executivos/
│   │   ├── Executivos_01-01-2024_03-31-2025.parquet
│   │   ├── Executivos_01-08-2024_03-31-2025.parquet
│   │   ├── Executivos_04-01-2025_09-30-2025.parquet
│   │   └── Executivos_10-01-2025_12-31-2025.parquet
│   │
│   ├── GPTW/
│   │   └── GPTW.parquet
│   │
│   ├── Horistas/
│   │   ├── Horistas_01-01-2024_12-31-2024.parquet
│   │   └── Horistas_01-01-2025_12-31-2025.parquet
│   │
│   ├── Mensalistas/
│   │   ├── Mensalistas_01-01-2024_03-31-2025.parquet
│   │   ├── Mensalistas_01-08-2024_03-31-2025.parquet
│   │   ├── Mensalistas_04-01-2025_09-30-2025.parquet
│   │   └── Mensalistas_10-01-2025_12-31-2025.parquet
│   │
│   └── Movimentacoes/
│       └── Movimentacoes.parquet
│
└── xlsx/
    ├── Ativos e Desligados/
    │   └── Ativos e Desligados.xlsx
    │
    ├── GPTW/
    │   └── GPTW.xlsx
    │
    └── Movimentacoes/
        └── Movimentacoes.xlsx
```

## Padrao de nomenclatura dos arquivos

- Snapshot por periodo (`csv`/`parquet`):
  - `<Categoria>_<MM-DD-AAAA>_<MM-DD-AAAA>.<ext>`
  - Exemplo: `Mensalistas_04-01-2025_09-30-2025.parquet`
- Bases consolidadas (sem intervalo no nome):
  - `Ativos.parquet`
  - `Desligados.parquet`
  - `Movimentacoes.parquet`
  - `GPTW.parquet`
- Fontes originais em planilha:
  - `Ativos e Desligados.xlsx`
  - `Movimentacoes.xlsx`
  - `GPTW.xlsx`

## Convencao por pasta

- `csv/`: arquivos historicos em texto (origem/extracao).
- `parquet/`: versao otimizada para processamento analitico.
- `xlsx/`: planilhas de origem para carga e validacao.
