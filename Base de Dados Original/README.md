# Base de Dados Original

Este diretorio concentra as bases de entrada em formatos `csv`, `parquet` e `xlsx`.

## Estrutura completa

```text
Base de Dados Original/
├── readme.md
├── csv/
│   ├── Registros/
│   │   ├── Executivos/
│   │   ├── Horistas/
│   │   ├── Mensalistas/
│   │   └── Terceiros/
│   │
│   └── Ajustes Manuais/
│       ├── Horistas/
│       ├── Mensalistas/
│       └── Terceiros/
│
├── parquet/
│   ├── Ativos/
│   │
│   ├── Desligados/
│   │
│   ├── GPTW/
│   │
│   ├── Registros/
│   │   ├── Executivos/
│   │   ├── Horistas/
│   │   ├── Mensalistas/
│   │   └── Terceiros/
│   │
│   ├── Ajustes Manuais/
│   │   ├── Horistas/
│   │   ├── Mensalistas/
│   │   └── Terceiros/
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
  - `df_ajustes_manuais.parquet`
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
- `csv/Ajustes Manuais/`: ajustes manuais extraidos do Ronda, separados por categoria.
- `parquet/Ajustes Manuais/`: mesmos ajustes em parquet e base consolidada
  `df_ajustes_manuais.parquet`.
- Os ajustes manuais entram na base final `project/database/df_ronda.parquet`
  pela coluna `Manual`: `Não` para registros originais e `Sim` para ajustes manuais.
