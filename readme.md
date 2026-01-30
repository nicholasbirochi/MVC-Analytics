<div style="width:100%; height:96px; border-radius:12px; 
background: linear-gradient(90deg, #030033ff 0%, #18145eff 50%, #030033ff 100%); 
display:flex; align-items:center; justify-content:center; 
box-shadow: 0 4px 14px rgba(0,0,0,0.12); margin: 8px 0 16px 0;">
  <images src="Projeto/Front-End/images/logo_white.png" alt="VW" width="130" height="100" style="vertical-align:middle; margin-right:8px; border-radius:8px; opacity:0.85;" />
  <h1 style="color:White; margin:0; font-size:28px; letter-spacing:0.3px; border-bottom: 1px solid #ffffffff">
    Dashboard de Presença — Volkswagen do Brasil
  </h1>
</div>

<p align="center">
  <images src="https://images.shields.io/badge/Python-3.11-blue" />
  <images src="https://images.shields.io/badge/Dash-2.18-3EB489" />
  <images src="https://images.shields.io/badge/Status-Em%20Uso-brightgreen" />
</p>
<p align="center" style="font-size:14px; color:#f0f0f0; margin-top:-6px;">
  Desenvolvido por <b>Nicholas Birochi</b> — Data Analytics | Volkswagen do Brasil
</p>

## 📚 Tabela de Conteúdos

<div align="center">

| [🧾 Resumo Técnico](#-resumo-tecnico) | 
[💼 Sobre o Projeto](#-sobre-o-projeto) | 
[✨ Funcionalidades Principais](#-funcionalidades-principais) | 
[🏛️ Arquitetura (MVC + Camada de Serviços)](#-arquitetura-mvc-camada-de-servicos) | 
[🗃️ Estrutura dos DataFrames](#-estrutura-dos-dataframes) | 
[🔁 Lógica “Mesma Planta”](#-logica-mesma-planta) | 
[⚙️ Configuração via .env](#-configuracao-via-env) | 
[🧰 Dependências](#-dependencias) | 
[🚀 Como rodar o projeto](#-como-rodar-o-projeto) | 
[🧠 Cache & Performance](#-cache--performance) | 
[🪄 Estilo Visual e UX](#-estilo-visual-e-ux) | 
[🔍 Logs e Diagnóstico](#-logs-e-diagnostico) | 
[🐍 Estrutura de Módulos Python](#-estrutura-de-modulos-python) | 
[♻️ Convenções de Código](#-convencoes-de-codigo) | 
[🧪 Testes e Validação](#-testes-e-validacao) | 
[🛠️ Solução de Problemas](#-solucao-de-problemas) | 
[🔐 Segurança e Acesso](#-seguranca-e-acesso) | 
[💡 Boas Práticas](#-boas-praticas) | 
[📄 Licença](#-licenca) | 
[🖋️ Assinatura Profissional](#-assinatura-profissional) |

</div>

## 🧾 Resumo Técnico
- Linguagem: Python 3.11
- Framework: Dash (Plotly + Flask)
- Arquitetura: MVC + Camada de Serviços
- Banco: Parquet + SQLite
- Cache: Flask-Caching (TTL 900s)
- Localização: pt_BR

## 💼 Sobre o Projeto

Dashboard corporativo construído com **Dash (Plotly + Flask)** para monitorar a presença semanal de colaboradores (Mensalistas e Executivos), com visão geral, relatórios por área e relatórios individuais — incluindo **validação de co-presença na mesma planta**, sistema de **tags interativas** e **carregamento progressivo de gráficos**.

## ✨ Funcionalidades Principais

### 📊 **Visão Geral**
- Distribuição por faixas (0–1 … 6–7 dias/semana)
- Dispersão e Boxplots por área
- Indicadores automáticos (totais e médias por cargo)
- Gráficos com **carregamento progressivo** para melhor desempenho e UX

### 🗂️ **Visão por Área/Subárea**
- Heatmap **Mensalistas × Executivos** (encontros na **mesma planta** no mesmo dia)
- Heatmap **Executivos × Executivos**
- Mini-tabela **GPTW**, com comparativo de tendência e filtro dinâmico
- Dropdown com bloqueio de subáreas já selecionadas

### 👤 **Relatório Individual**
- Gauge / Termômetro de presença
- Série temporal de presença semanal
- Heatmaps pessoais por semana
- Download direto em **JPG** e **PDF**

### ⚙️ **Filtros Dinâmicos**
- Período (cenários + slider mensal)
- Desligados / Viagem
- Área/Subárea (com **Herança** e exclusões automáticas)

### ⚡ **Performance e Interatividade**
- Sistema de **cache leve** (Flask-Caching)
- Gráficos e dados renderizados em **etapas progressivas**
- Navegação instantânea entre abas
- Tags de eventos personalizáveis (datas, nomes, cores)

## 🏛️ Arquitetura (MVC + Camada de Serviços)

Estrutura modular para manter **baixo acoplamento** e **alta manutenibilidade**.  
Os arquivos estão organizados conforme o padrão **Model–View–Controller (MVC)**.

```plaintext
📁 Projeto Geral/
├── 📁 Base de Dados Original/
│ ├── 📂 csv/
│ │ ├── 📂 Executivos/
│ │ │ ├── 🧾 Executivos_01-08-2024_03-31-2025.csv
│ │ │ ├── 🧾 Executivos_04-01-2025_09-30-2025.csv
│ │ │ └── 🧾 Executivos_10-01-2025_12-31-2025.csv
│ │ │
│ │ ├── 📂 Horistas/
│ │ │
│ │ └── 📂 Mensalistas/
│ │   ├── 🧾 Mensalistas_01-08-2024_03-31-2025.csv
│ │   ├── 🧾 Mensalistas_04-01-2025_09-30-2025.csv
│ │   └── 🧾 Mensalistas_10-01-2025_12-31-2025.csv
│ │
│ ├── 📂 parquet/
│ │ ├── 📂 Ativos/
│ │ │ └── 🪶 Ativos.parquet
│ │ │
│ │ ├── 📂 Desligados/
│ │ │ └── 🪶 Desligados.parquet
│ │ │
│ │ ├── 📂 Executivos/
│ │ │ ├── 🪶 Executivos_01-08-2024_03-31-2025.parquet
│ │ │ ├── 🪶 Executivos_04-01-2025_09-30-2025.parquet
│ │ │ └── 🪶 Executivos_10-01-2025_12-31-2025.parquet
│ │ │
│ │ ├── 📂 GPTW/
│ │ │ └── 🪶 GPTW.parquet
│ │ │
│ │ ├── 📂 Horistas/
│ │ │ 
│ │ ├── 📂 Mensalistas/
│ │ │ ├── 🪶 Mensalistas_01-08-2024_03-31-2025.parquet
│ │ │ ├── 🪶 Mensalistas_04-01-2025_09-30-2025.parquet
│ │ │ └── 🪶 Mensalistas_10-01-2025_12-31-2025.parquet
│ │ │
│ │ └── 📂 Movimentacoes/
│ │   └── 🪶 Movimentacoes.parquet
│ │
│ └── 📂 xlsx/
│   ├── 📂 Ativos e Desligados/  
│   │ └── 💹 Ativos e Desligados.xlsx
│   │
│   ├── 📂 GPTW/ 
│   │ └── 💹 GPTW.xlsx
│   │
│   └── 📂 Movimentacoes/ 
│     └── 💹 Movimentacoes.xls
│
├── 📂 Códigos Extras/
│ ├── 📂 Convertendo o Formato das Bases/
│ │ ├── 📓 Transformando de csv para parquet.ipynb
│ │ └── 📓 Transformando de xlsx para parquet.ipynb
│ │
│ ├── 📂 Documentação/
│ │ ├── 📂 Analisando Fraudes dos Registros/
│ │ │ ├── 📓 Análise das Fraudes.ipynb
│ │ │ └── 💹 Registros Suspeitos.xlsx
│ │ │
│ │ ├── 📂 Análise feita com PDFs/
│ │ │ ├── 📂 Base de Dados/
│ │ │ │ ├── 📝 relatorio A.M.N.M.  01.24_31.03.pdf
│ │ │ │ └── 📝 relatorio N.P.N.I.  01.24_31.03.pdf
│ │ │ │
│ │ │ └── 📂 Códigos/
│ │ │   ├── 📓 Análise Dias Presenciais A.M.N.M. - Nicholas.ipynb
│ │ │   ├── 📓 Análise Dias Presenciais N.P.N.I. - Nicholas.ipynb
│ │ │   ├── 💹 presenca_por_semana A.M.N.M. 01.24_31.03.xlsx
│ │ │   └── 💹 presenca_por_semana N.P.N.I. 01.24_31.03.xlsx
│ │ │
│ │ ├── 📂 Análise feita pelo Antigo Colaborador/
│ │ │ ├── 📂 Análise - Antigo Colaborador/
│ │ │ │ ├── 📝 Análise Dias Presenciais A.M.N.M. Python Script.pdf
│ │ │ │ └── 📝 Análise Dias Presenciais N.P.N.I. Python Script.pdf
│ │ │ │
│ │ │ ├── 📓 Análise Dias Presenciais A.M.N.M..ipynb
│ │ │ ├── 📓 Análise Dias Presenciais N.P.N.I..ipynb
│ │ │ ├── 💹 presenca_por_semana A.M.N.M. 01.24_31.03.xlsx
│ │ │ ├── 📝 relatorio A.M.N.M.  01.24_31.03.pdf
│ │ │ └── 📝 relatorio N.P.N.I.  01.24_31.03.pdf
│ │ │
│ │ ├── 📂 Análise por Colaborador para Horas Extras/
│ │ │ ├── 📂 validation_base/
│ │ │ │ ├── 📂 csv
│ │ │ │ │ └── 🧾 Colaboradores.csv
│ │ │ │ │
│ │ │ │ └── 📂 parquet
│ │ │ │   └── 🪶 Colaboradores.parquet
│ │ │ │
│ │ │ ├── 📂 xlsx/
│ │ │ │ └── 💹 Horas Registradas.xlsx
│ │ │ │
│ │ │ ├── 📓 Análise das horas dos colaboradores.ipynb
│ │ │ ├── 💹 Arquivo Solicitado - Colaboradores não Presentes.xlsx
│ │ │ └── 📓 Transformando de csv para parquet.ipynb
│ │ │
│ │ ├── 📂 Análise Tempo de Casa/
│ │ │ ├── 🖼️ code.png
│ │ │ └── 🖼️ resultado.png
│ │ │
│ │ ├── 📂 Consolidando as Planilhas do Excel/
│ │ │ ├── 📂 data
│ │ │ │ ├── 💹 Backlog 2025_consolidado.xlsx
│ │ │ │ └── 💹 Backlog 2025.xlsx
│ │ │ │
│ │ │ └── 📓 Análise das Planilhas.ipynb
│ │ │
│ │ ├── 📂 Corrigindo CSV/
│ │ │ ├── 📂 Executivos_SQL/
│ │ │ │ └── 🧾 Executivos_SQL.csv
│ │ │ │
│ │ │ ├── 📂 Mensalistas_SQL/
│ │ │ │ └── 🧾 Mensalistas_SQL.csv
│ │ │ │
│ │ │ └── 📓 Corrigindo o csv novo.ipynb
│ │ │
│ │ ├── 📓 Análise das movimentacoes.ipynb
│ │ ├── 📓 Análise geral.ipynb
│ │ └── 💹 Colaboradores e Áreas com Problemas.xlsx
│ │
│ ├── 📂 Tratando Base Misturada/
│ │ ├── 📂 Ativos e Desligados
│ │ │ ├── 📂 xlsx
│ │ │ │ ├── 💹 Ativos e Desligados - 06-31-2025.xlsx
│ │ │ │ ├── 💹 Ativos e Desligados - 09-30-2025.xlsx
│ │ │ │ └── 💹 Ativos e Desligados - 12-31-2025.xlsx
│ │ │ │
│ │ │ └── 📓 Validando novas bases.ipynb
│ │ │
│ │ └── 📂 Movimentacoes
│ │   ├── 📂 xlsx
│ │   │ ├── 💹 Movimentacoes_01-01-2023_09-30-2025.xlsx
│ │   │ └── 💹 Movimentacoes_10-01-2025_12-31-2025.xlsx
│ │   │
│ │   └── 📓 Validando novas bases.ipynb
│ │
│ ├── 📓 ETL.ipynb
│ └── 📓 Projeto unificado.ipynb
│
├── 📁 project/
│ ├── 📂 scripts/
│ │ ├── 📂 src/
│ │ │ ├── 📂 api/
│ │ │ │ ├── 🐍 area.py
│ │ │ │ ├── 🐍 general.py
│ │ │ │ ├── 🐍 individual.py
│ │ │ │ ├── 🐍 relacionamento.py
│ │ │ │ └── 🐍 router.py
│ │ │ │
│ │ │ ├── 📂 core/
│ │ │ │ ├── 🐍 config.py
│ │ │ │ └── 🐍 repo_global.py
│ │ │ │
│ │ │ ├── 📂 data/
│ │ │ │ └── 🐍 datasets.py
│ │ │ │
│ │ │ ├── 📂 domain/
│ │ │ │ ├── 🐍 builders.py
│ │ │ │ ├── 🐍 cache_utils.py
│ │ │ │ ├── 🐍 copresenca.py
│ │ │ │ ├── 🐍 exports.py
│ │ │ │ ├── 🐍 filters.py
│ │ │ │ ├── 🐍 gptw.py
│ │ │ │ ├── 🐍 periods.py
│ │ │ │ └── 🐍 tenure.py
│ │ │ │
│ │ │ ├── 📂 ui/
│ │ │ │ ├── 🐍 figures.py
│ │ │ │ ├── 🐍 gptw.py
│ │ │ │ ├── 🐍 layout.py
│ │ │ │ ├── 🐍 tables.py
│ │ │ │ └── 🐍 theme.py
│ │ │ │
│ │ │ └── 🐍 main.py
│ │ │
│ │ └── 🐍 security_login.py
│ │
│ ├── 📂 database/
│ │ ├── 🪶 Desligados.parquet
│ │ ├── 🪶 Almoco.parquet
│ │ ├── 🪶 ArquivoFinal.parquet
│ │ ├── 🪶 ArquivoFinalDatas.parquet
│ │ ├── 🪶 ArquivoFinalSemana.parquet
│ │ ├── 🗄️ Banco Login.sqlite
│ │ ├── 🪶 Ativos.parquet
│ │ └── 🪶 GPTW.parquet
│ │
│ └── 📂 web/
│   ├── 📂 images/
│   │ ├── 🖼️ logo_white.png
│   │ └── 🧊 logo_blue.ico
│   │
│   ├── 📂 javascript/
│   │ ├── ⚡ app.js
│   │ └── ⚡ login.js
│   │
│   ├── 📂 style/
│   │ ├── 🎨 login.css
│   │ └── 🎨 styles.css
│   │
│   └── 📂 ui/
│     ├── 🧱 index.html
│     └── 🧱 login.html
│  
├── ⚙️ .gitignore
├── 📖 readme.md
└── 📦 requirements.txt
```

>*Certifique-se de que todas as pastas acima contenham `__init__.py`.*

### 🎨 Legenda de Ícones

| **Ícone** | **Tipo de Arquivo** |                  **Descrição**                  |
| :-------: | :-----------------: | :---------------------------------------------: |
|     🧾    |        `.csv`       |      Dados tabulares separados por vírgulas     |
|     📝    |        `.pdf`       | Documentos em PDF (relatórios, contratos, etc.) |
|     🪶    |      `.parquet`     |      Formato colunar otimizado para análise     |
|     💹    |       `.xlsx`       |                 Planilhas Excel                 |
|     💹    |        `.xls`       |                 Planilhas Excel                 |
|     📓    |       `.ipynb`      |                Notebooks Jupyter                |
|     🐍    |        `.py`        |                  Código Python                  |
|     🧊    |        `.ico`       |                 Ícones/favicons                 |
|     🖼️    |        `.png`       |                     Imagens                     |
|     ⚡    |        `.js`        |                Scripts JavaScript               |
|     🎨    |        `.css`       |                 Estilos visuais                 |
|     🧱    |       `.html`       |                   ui/front-end                  |
|     🗄️    |      `.sqlite`      |               Banco de dados local              |
|     ⚙️    |     `.gitignore`    |            Regras de ignorados do Git           |
|     📖    |        `.md`        |              Documentação Markdown              |
|     📦    |  `requirements.txt` |              Dependências do Python             |



## 🗃️ Estrutura dos DataFrames

### 📆 df_semana_merged — Presença semanal consolidada
- `Cadastro` (str)
- `Nome` (str)
- `Area` (str)
- `Departamento` (str)
- `Heranca` (str)
- `Cargo Especifico` (str)
- `Cargo` (str)
- `Afastado` (str)
- `Ano` (int)
- `Semana por Ano` (int)
- `Contagem Presença` (float/int)
>*As colunas `Início da Semana` e `Fim da Semana` existem na base mas não são utilizadas.<br>
>*O campo `Viaja` não está presente no* DataFrame, apenas inferido via herança/área.*

### 🗓️ df_datas — Presença diária (usado para validar co-presença, acessos e controle de entrada)
- `Cadastro` (str)
- `Planta` (array)
- `Data` (datetime)
- `Dia Semana` (str)
- `Semana por Ano` (int)
- `Ano` (int)
>*As demais colunas originais (`Nome`, `Area`, `Departamento`, `Heranca`, `Cargo Especifico`, `Dir`, `Tipo`, `Acesso`, `Coletor`, `Descricao Coletor`, `Uso Acesso`, `Cargo`, `Afastado` e `Hora`) não são utilizadas pelo app.*

### 🍽️ df_almoco — Acesso ao refeitório (base auxiliar)
- `Cadastro` (str)
- `Nome` (str)
- `Data` (datetime)
- `Hora` (object)
- `Dir` (str)
- `Planta` (array)
- `Coletor` (int)
- `Descricao Coletor` (str)
- `Cargo` (str)
- `Afastado` (str)
- `Departamento` (str) (str)
- `Heranca` (str)
- `Cargo Especifico` (str)
>*As colunas de controle de acesso (`Filial`, `Tipo`, `Acesso`, `Uso Acesso` e `Area`) não são utilizadas.*

### 🏢 df_ativos — Estrutura hierárquica de áreas
- `Cadastro` (str)
- `Departamento` (str)
- `Area` (str)
- `Data_Admissão` (datetime)
>*Demais colunas (`Nome completo`, `Heranca`, `Cargo Especifico`, `Local` e `Afast_RH`) não são usadas.<br>
>*Serve como base auxiliar para montar* o DataFrame `her` (hierarquia de áreas).*

### 🚑 df_desligados (opcional) — Cadastro de colaboradores desligados
- `Cadastro` (str)
- `Departamento` (str)
- `Area` (str)
- `Data_Adm` (datetime)
- `Data_Dem` (datetime)
>*Outras colunas (`Nome completo`, `Heranca`, `Cargo Especifico` e `Local`) não são utilizadas.*

### 🏆 df_gptw — Indicadores de clima e satisfação
- `Área` (str)
- `2025` (float/int)
- `2024` (float/int)
- `2023` (float/int)
>*Estrutura em formato largo (cada ano como coluna).*<br>
>*Caso seja convertida para formato longo, ficaria: `Área`, `Ano`, `Nota`.*

## 🔁 Lógica “Mesma Planta”

Nos heatmaps:
- Conta encontro **apenas** quando ambos estão **presentes no mesmo dia e na mesma `Planta`**.
- Percentual = `encontros / presença_base * 100`.

Implementação:  
→ `domain/copresenca.py`  
→ Função principal: `calcular_copresenca(df_datas, area)`

## ⚙️ Configuração via `.env`

```python
pasta_desligados=Projeto/Banco de Dados/Desligados.parquet
pasta_ativos=Projeto/Banco de Dados/Ativos.parquet
caminho_gptw=Projeto/Banco de Dados/GPTW.parquet
caminho_semana=Projeto/Banco de Dados/ArquivoFinal.parquet
caminho_datas=Projeto/Banco de Dados/ArquivoFinalDatas.parquet

ND_PANDAS_LOCALE=pt_BR
ND_CACHE_TTL=900
ND_DEBUG=true
ND_PORT=8050
```
Edite `src/settings.py` se precisar de valores padrão diferentes.

## 🧰 Dependências

`requirements.txt` mínimo:
```text
dash>=2.18
flask>=3.0
numpy>=1.26
pandas>=2.2
plotly>=5.22
seaborn>=0.13
pyarrow>=16.0
matplotlib>=3.8
flask-caching>=2.3
python-dateutil>=2.9
```

## 🚀 Como rodar o projeto

```cmd
# 1️⃣ Criar o ambiente virtual
python -m venv .venv

# 2️⃣ Ativar o ambiente virtual
# Windows
.\.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# 3️⃣ Instalar dependências
pip install -r requirements.txt

# 4️⃣ Executar o projeto
cd Projeto\app
python -m src.main

# 5️⃣ Acesse em:  
http://localhost:8050
```
>*Atenção: Execute sempre a partir da raiz do projeto, não de dentro da pasta `src/`.*

## 🧠 Cache & Performance
- Cache leve (Flask-Caching) para DataFrames semanais  
- TTL configurável via `ND_CACHE_TTL` (padrão: 900 s)  
- Funções puras menores podem usar `functools.lru_cache`  
- Renderização dos gráficos é progressiva (`dcc.Store` + `dcc.Interval`)

## 🪄 Estilo Visual e UX
- Paleta Volkswagen Data Blue / Gray Neutral  
- Inspiração em VS Code (cards, bordas e ícones coloridos)  
- Layout fluido com Grid + Flexbox Dash  
- Tags coloridas e pontilhadas com rótulos personalizados  
- Hierarquia temporal no eixo X (Semana → Mês → Ano)  
- Suporte completo a pt_BR (meses, datas, labels)

## 🔍 Logs e Diagnóstico
- Logs configurados em `config.py` (modo `ND_DEBUG`)  
- Console exibe: tempo de carregamento por aba, cache hit/miss, eventos de filtro e seletores  
- Logs podem futuramente ser direcionados a arquivos `.log`

## 🐍 Estrutura de Módulos Python

### 🧩 **Controllers** (`controllers/*.py`) — Camada de controle e callbacks Dash

| Arquivo | Função | Descrição |
|:-------- |:--------|:-----------|
| `general.py` | Aba inicial | KPIs, boxplots e indicadores gerais |
| `area.py` | Aba por área | Heatmaps e filtros dinâmicos por departamento |
| `relacionamento.py` | Aba de relacionamentos | Séries semanais, tags e comparativos |
| `individual.py` | Relatório individual | Termômetro, histórico e exportação PDF/JPG |
| `router.py` | Roteamento Dash | Redireciona `dcc.Location` → layout correto |

### 🛠️ **Services** (`services/*.py`) — Camada de lógica e regras de negócio

| Arquivo | Função | Descrição |
|:-------- |:--------|:-----------|
| `builders.py` | Construtores de DataFrame | Une datasets brutos e normaliza colunas |
| `copresenca.py` | Regra “Mesma Planta” | Calcula co-presença (Data, Cadastro, Planta) |
| `cache_utils.py` | Cache e invalidação | Gerencia cache Flask e memória RAM |
| `filters.py` | Filtros de dashboards | Filtragem por área, cargo, cenário, período |
| `gptw.py` | GPTW mini table | Cálculo e tendência GPTW (ano a ano) |
| `exports.py` | Exportações | Gera JPG e PDF via Matplotlib/ReportLab |
| `periods.py` | Controle de períodos | Define cenários (Jan–Abr, Mai–Atual) e slider mensal |
| `tenure.py` | Tempo de empresa | Calcula KPIs de permanência e senioridade |

### 🎨 **ui** (`ui/*.py`) — Camada visual e geração de gráficos

| Arquivo | Função | Descrição |
|:-------- |:--------|:-----------|
| `layout.py` | Layout principal | Estrutura base (Tabs, Cards, Containers) |
| `figures.py` | Criação de gráficos | Heatmaps, Boxplots, Termômetros e Séries |
| `tables.py` | Tabelas HTML | Geração de mini-tabelas e tabelas responsivas |
| `theme.py` | Paleta e estilos | Define cores, gradientes, bordas e tipografia |
| `gptw.py` | Módulo GPTW | Renderiza gráfico de tendência e notas por área |

## ♻️ Convenções de Código
- PEP 8 e tipagem gradual: `from __future__ import annotations`
- Prefixo `df_` para DataFrames<br>
- Constantes em MAIÚSCULAS<br>
- Comentários de seção em bloco: `# '''~~~~~~~~~~~~~~~~~~~~~~~ Seção ~~~~~~~~~~~~~~~~~~~~~~~'''`
- IDs do Dash seguem o padrão: `grafico-aba-elemento`

## 🧪 Testes e Validação
- Cada aba possui callback de *sanity check* para verificar:  
  - Se as colunas obrigatórias existem  
  - Se o DataFrame retornado não está vazio  
- O módulo `domain/validators.py` (opcional) pode conter verificações automáticas

## 🛠️ Solução de Problemas

| Problema | Causa | Solução |
|:----------|:--------|:--------|
| `ModuleNotFoundError: 'src.api'` | Execução fora da raiz | Execute `python -m src.main` |
| Meses não aparecem em pt-BR | Locale do SO | Usa `Timestamp.month_name(locale='pt_BR')` |
| Nenhum dado no gráfico | Coluna ausente | Confirme `Planta` e `Data` em `df_datas` |
| Tags não aparecem | Store vazio | Adicione tags via interface lateral |
| Slider bugado | Coluna `Data` inválida | Verifique `df_datas['Data']` coerente |

## 🔐 Segurança e Acesso
- Login controlado via SQLite + Flask Session
- Rotas protegidas por autenticação simples (`login.py`)

## 💡 Boas Práticas
- Evite *hardcodes* → use variáveis `ND_*`  
- Normalize sempre as colunas (`Cadastro`, `Data`)  
- Evite *joins* com tipos mistos  
- Use `PreventUpdate` para callbacks sem mudança de estado  
- Prefira `@cache.memoize()` em cálculos pesados

## 📄 Licença
Projeto interno — uso corporativo.
<br>© 2025 Volkswagen do Brasil / Nicholas Birochi

## 🖋️ Assinatura Profissional
<!-- Assinatura HTML -->
<table style="font-family: 'Segoe UI', Arial, sans-serif; border: none; border-collapse: collapse;">
  <tr>
    <td style="padding-right: 0px; vertical-align: middle;">
      <images src="Projeto/Front-End/images/logo_white.png"
           width="150"
           style="vertical-align: middle;"
           alt="logo_blue VW">
    </td>
    <td style="border-left: 3px solid #ffffffff; padding-left: 10px;">
      <p style="margin: 0; font-size: 17px; font-weight: 700; color: #ffffffff;">Nicholas Birochi</p>
      <p style="margin: 2px 0; color: #444; font-size: 14px;">Estagiário de Análise de Dados | Data Analytics</p>
      <p style="margin: 2px 0; color: #444; font-size: 14px;">Volkswagen do Brasil</p>
      <p style="margin: 6px 0; font-size: 13px;">
        <a href="mailto:seu_email@exemplo.com" style="color: #0055A5; text-decoration: none; font-weight: 500;">Email</a> &nbsp;•&nbsp;
        <a href="https://www.linkedin.com/in/nicholas-birochi/" style="color: #0A66C2; text-decoration: none; font-weight: 500;">LinkedIn</a> &nbsp;•&nbsp;
        <a href="https://github.com/nicholasbirochi" style="color: #181717; text-decoration: none; font-weight: 500;">GitHub</a> &nbsp;•&nbsp;
        <a href="https://app.rocketseat.com.br/me/nicholas-birochi-1501" style="color: #8257E5; text-decoration: none; font-weight: 500;">Rocketseat</a>
      </p>
    </td>
  </tr>
</table>