# Base SQLite do Projeto

Este diretorio concentra os bancos SQLite usados pela aplicacao.

## Estrutura completa

```text
project/database/
├── readme.md
├── db_login.sqlite
├── dw_ronda.sqlite
└── dw_ronda.sqlite-shm
```

> Observacao: em execucao, o SQLite tambem pode gerar `dw_ronda.sqlite-wal`.

## Padrao de cada arquivo

- `db_login.sqlite`
  - Banco transacional de autenticacao/login.
  - Uso principal: `project/scripts/security_login.py`.

- `dw_ronda.sqlite`
  - Data Warehouse analitico principal do Projeto Ronda.
  - Uso principal: pipeline SQL-first do MVC.

- `dw_ronda.sqlite-shm`
  - Arquivo auxiliar de memoria compartilhada do modo WAL do SQLite.
  - Gerado automaticamente pelo engine.

- `dw_ronda.sqlite-wal` (quando existir)
  - Write-Ahead Log do SQLite.
  - Arquivo temporario/operacional durante escrita concorrente.

## Variaveis de ambiente relacionadas

- `LOGIN_DB_PATH`: caminho do banco de login.
- `ND_DATA_DIR`: diretorio base onde o app procura os bancos/datasets locais.

Exemplo (PowerShell):

```powershell
$env:LOGIN_DB_PATH = ".\\project\\database\\db_login.sqlite"
$env:ND_DATA_DIR = ".\\project\\database"
```
