# Apresentacao Seitz

Gera a resposta executiva sobre home office na fabrica, usando o
`project/database/dw_ronda.sqlite`.

## O que responde

- Quantas pessoas estao abaixo de 90% da meta.
- Quanto esse grupo representa entre as pessoas consideradas.
- Abertura acumulada por media semanal: ate 1,0 dia, 1,5 dia, 2,0 dias e 2,5 dias.
- Apoio gerencial: onde agir primeiro por volume e por percentual.
- Aprofundamento: tendencia semanal, cargo, area, departamentos e heatmap.

## Saidas

- `saida/apresentacao_seitz_presencial_fraco.html`
- `saida/apresentacao_seitz_presencial_fraco.xlsx`
- `saida/resumo_execucao.md`
- `saida/resumo_execucao.json`
- `saida/pessoas_abaixo_90.csv`
- `saida/pessoas_consideradas.csv`

No Excel, comece pela aba `Leia Primeiro`. Use `Aprofundamento Gestor` se precisar explicar area/departamento.

## Regras

- Ativos, cargos `M` e `E`.
- Areas `B-`, exceto `B-V` e `B-SNP`.
- Semana normal: meta de 3 dias presenciais.
- Semana com feriado: critica apenas com 0 ou 1 dia presencial.
- Ferias coletivas fora da conta.

## Como executar

```powershell
py -3 ".\Códigos Extras\Documentação\Apresentação Seitz\gerar_apresentacao_seitz.py"
```

Parametros uteis:

```powershell
py -3 ".\Códigos Extras\Documentação\Apresentação Seitz\gerar_apresentacao_seitz.py" `
  --reference-date 2026-04-23 `
  --dw-path ".\project\database\dw_ronda.sqlite"
```
