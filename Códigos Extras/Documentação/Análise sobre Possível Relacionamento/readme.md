# Comparação de Registros do Ronda 

> Projeto de apoio ao time de **Data Analytics** para comparar eventos entre dois cadastros e gerar um Excel final.

Este repositório/nota executável retorna **dois grupos** e concatena:

1. **IGUAIS (sem `port`)** → pares em que `Descricao Coletor` é **idêntica** entre A e B **somente quando ambos NÃO contêm** o termo `port` (case‑insensitive).  
2. **PORTS (extras)** → pares em que **ambos** contêm `port` (case‑insensitive), **sem exigir igualdade literal** na `Descricao Coletor`, e **apenas aqueles que não entraram** no grupo (1).

Para ambos os grupos, é aplicada uma **janela de horário ≤ 5 minutos** entre os registros pareados.

---

## Estrutura (como no print)

```
.
├─ Código.ipynb
├─ comparacao_chapa1_chapa2.xlsx
├─ readme.md
└─ requirements.txt
```

- **Código.ipynb**: notebook onde você pode colar/rodar o script.  
- **comparacao_chapa1_chapa2.xlsx**: gerado após a execução.  
- **readme.md**: este arquivo.  
- **requirements.txt**: dependências mínimas (pandas e openpyxl).

---

## Regras de pareamento

- **Grupo 1 — IGUAIS (sem `port`)**  
  - `Descricao Coletor` **idêntica** entre A (Cadastro `chapa1`) e B (Cadastro `chapa2`).  
  - **Somente** se **ambos** os lados **NÃO** contiverem `port` no texto.

- **Grupo 2 — PORTS (extras)**  
  - Quando **algum** lado contiver `port`, o **outro** também deve conter `port` (case‑insensitive).  
  - **Não** exige igualdade literal de `Descricao Coletor`.  
  - São considerados **apenas** os ports **que não apareceram** no Grupo 1.

- **Janela de tempo**  
  - Apenas pares com diferença absoluta entre horários **≤ 5 minutos** entram no resultado final.
  - Formatos aceitos de `Hora`: `HH:MM:SS` (preferencial) ou `HH:MM` (fallback).

> O termo usado para identificar portaria é `port` (case‑insensitive). Se quiser mudar (ex.: `porta`, `portaria`), altere a constante `PORT_TOKEN` no script.

---

## Requisitos

Crie/atualize um `requirements.txt` com, no mínimo:

```
pandas>=2.0.0
openpyxl>=3.1.0
```

Instalação rápida:

```bash
pip install -r requirements.txt
```

---

## Colunas esperadas no `df_ronda`

- `Cadastro` (str/int)  
- `Coletor` (str/int) — **registros com `Coletor == 999` são excluídos**  
- `Data` (string ou date) — o script normaliza para `date`  
- `Hora` (string) — `HH:MM:SS` ou `HH:MM`  
- `Nome` (opcional; usado apenas para sufixos “amigáveis” no resultado)  
- `Descricao Coletor` (string)

> Garanta que o **formato de `Data`** seja consistente entre A e B no mesmo dia.

---

## Como usar

1. Abra **Código.ipynb** (ou crie um `.py`).  
2. **Cole o script** de comparação (versão “iguais (sem port) + ports extras”).  
3. Ajuste no início do script:
   - `PARQUET_PATH` (entrada Parquet)  
   - `OUTPUT_PATH` (Excel de saída)  
   - `ID_A`, `ID_B` (cadastros) — padrão: `chapa1` e `chapa2`  
   - `MATCH_SAME_DATE_EQ` (se `True`, exige mesma Data para os **iguais sem port**)  
   - `PORT_TOKEN` (token que identifica portaria, padrão `port`)
4. Execute. Ao final, será impresso algo como:
   ```
   Arquivo salvo: .\comparacao_chapa1_chapa2.xlsx | Linhas: 42 (iguais_sem_port=0, ports=42)
   ```

---

## Saída (Excel)

O arquivo **comparacao_chapa1_chapa2.xlsx** contém, além das colunas originais de A e B:

- `dif_min` — diferença absoluta (em minutos) entre os horários pareados.  
- `RegraPareamento` — indica o grupo que gerou o par:
  - `igual_descricao_sem_port`
  - `ambos_contem_port`

> Em caso de qualquer duplicidade acidental, a preferência é manter o par do grupo **`igual_descricao_sem_port`**.

---

## Dicas e problemas comuns

- **Sem linhas no resultado** → verifique se as **Datas** batem entre A e B e se os **horários** estão no formato correto.  
- **Erro ao salvar Excel** → ajuste `OUTPUT_PATH` para uma pasta com permissão (no Windows, prefira strings `r'.\comparacao_chapa1_chapa2.xlsx'`).  
- **Texto “port” com variações** → o matching é case‑insensitive em cima do token `PORT_TOKEN`. Adapte se houver abreviações diferentes.

---

## Observações de negócio

- Registros com `Coletor == 999` são descartados conforme regra atual.  
- O script **normaliza `Data`** para `date` (sem hora).  
- A lógica é pensada para uso diário pelo **estagiário de Análise de Dados ( do Brasil)** e pode ser expandida para múltiplos cadastros com pequenas adaptações.

