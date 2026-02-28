## Dados Locais (Nao Versionados)

Os bancos locais foram movidos para fora deste repositorio para evitar exposicao acidental.

Local padrao:
- `../_dados_ronda_local/project/database/`

Arquivos esperados nesse local:
- `db_login.sqlite`
- `dw_ronda.sqlite`
- (opcional) outros bancos locais usados para desenvolvimento

Configuracao:
- `LOGIN_DB_PATH` para o login Flask (`project/scripts/security_login.py`)
- `ND_DATA_DIR` para o app principal (`project/scripts/src/core/config.py`)

Exemplo (PowerShell):
```powershell
$env:LOGIN_DB_PATH = "..\\_dados_ronda_local\\project\\database\\db_login.sqlite"
$env:ND_DATA_DIR = "..\\_dados_ronda_local\\project\\database"
```
