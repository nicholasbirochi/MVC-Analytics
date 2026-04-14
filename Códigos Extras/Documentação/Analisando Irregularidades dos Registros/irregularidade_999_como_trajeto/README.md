# Analise `irregularidade_999_como_trajeto` (Top 5 dados crus)

Este diretorio foi criado para isolar a analise de `999 como trajeto`, seguindo a logica do notebook:

- `Códigos Extras/Documentação/Análise sobre a Área B-ROT (Irregularidade 999)/Código.ipynb`

## Logica aplicada

- Usa a base consolidada `outputs_irregularidades/dfs/irregularidade_999_como_trajeto.parquet`
  (gerada pela logica do notebook B-ROT) para identificar os dias/cadastros irregulares.
- Rele o `df_ronda.parquet` atual e extrai somente os registros crus dos Top 5 casos.
- Gera tambem uma visao `relevante` (foco em ponto/portaria/999).

## Execucao

No PowerShell, a partir desta pasta:

```powershell
..\..\..\..\.venv\Scripts\python.exe .\gerar_top5_dados_crus.py --base-dir ..
```

Opcional (mudar top):

```powershell
..\..\..\..\.venv\Scripts\python.exe .\gerar_top5_dados_crus.py --base-dir .. --top-n 5
```

## Saidas

As saidas sao gravadas em `./saidas`:

- `top5_irregularidade_999_resumo.csv`
- `top5_irregularidade_999_chaves.csv`
- `top5_irregularidade_999_dados_crus.csv`
- `top5_irregularidade_999_dados_crus.parquet`

`top5_irregularidade_999_dados_crus.*` contem somente os registros dos dias/cadastros do Top 5.
