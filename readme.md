<div style="
  width:100%;
  min-height:96px;
  border-radius:12px;
  background:linear-gradient(90deg,#030033 0%,#18145e 50%,#030033 100%);
  display:flex;
  align-items:center;
  justify-content:center;
  gap:12px;
  padding:12px 16px;
  box-shadow:0 4px 14px rgba(0,0,0,.12);
  margin:8px 0 16px 0;
  box-sizing:border-box;
  flex-wrap:wrap;
  text-align:center;
">
  <img
    src="project/images/logo_white.png"
    alt="VW"
    style="
      width:clamp(88px, 12vw, 130px);
      height:auto;
      max-height:72px;
      object-fit:contain;
      border-radius:10px;
      opacity:.9;
      flex:0 0 auto;
    "
  />

  <h1 style="
    color:#fff;
    margin:0;
    font-size:clamp(18px, 2.2vw, 28px);
    line-height:1.15;
    letter-spacing:.2px;
    padding-bottom:6px;
    border-bottom:1px solid rgba(255,255,255,.75);
    max-width:1100px;
  ">
    Dashboard sobre Monitoramento Comportamental — Volkswagen do Brasil
  </h1>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14.2-blue" />
  <img src="https://img.shields.io/badge/Dash-2.18-3EB489" />
  <img src="https://img.shields.io/badge/Status-Em%20Uso-brightgreen" />
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
- Linguagem: Python 3.14.2
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
│ │ ├── 📂 Registros/
│ │ │ ├── 📂 Executivos/
│ │ │ ├── 📂 Horistas/
│ │ │ ├── 📂 Mensalistas/
│ │ │ └── 📂 Terceiros/
│ │ │
│ │ └── 📂 Ajustes Manuais/
│ │   ├── 📂 Horistas/
│ │   ├── 📂 Mensalistas/
│ │   └── 📂 Terceiros/
│ │
│ ├── 📂 parquet/
│ │ ├── 📂 Ativos/
│ │ │ └── 🪶 Ativos.parquet
│ │ │
│ │ ├── 📂 Desligados/
│ │ │ └── 🪶 Desligados.parquet
│ │ │
│ │ ├── 📂 GPTW/
│ │ │ └── 🪶 GPTW.parquet
│ │ │
│ │ ├── 📂 Registros/
│ │ │ ├── 📂 Executivos/
│ │ │ ├── 📂 Horistas/
│ │ │ ├── 📂 Mensalistas/
│ │ │ └── 📂 Terceiros/
│ │ │
│ │ ├── 📂 Ajustes Manuais/
│ │ │ ├── 🪶 df_ajustes_manuais.parquet
│ │ │ ├── 📂 Horistas/
│ │ │ ├── 📂 Mensalistas/
│ │ │ └── 📂 Terceiros/
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
│     └── 💹 Movimentacoes.xlsx
│
├── 📂 Códigos Extras/
│ ├── 📂 Convertendo o Formato das Bases/
│ │ ├── 📓 Transformando de csv para parquet.ipynb
│ │ └── 📓 Transformando de xlsx para parquet.ipynb
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
│ ├── 📂 Documentação/
│ │ ├── 📂 Analisando Horas Extras de Colaboradores/
│ │ │ ├── 📂 saida_relatorios_ronda
│ │ │ │ ├── 💹 relatorio_abaixo_08h00.xlsx
│ │ │ │ ├── 💹 relatorio_acima_10h50.xlsx
│ │ │ │ └── 💹 relatorio_dias_com_registros_de_port_e_s_incongruentes.xlsx
│ │ │ │
│ │ │ ├── 📂 validations
│ │ │ │ └── 💹 checagem_3_exemplos_por_relatorio.xlsx
│ │ │ │
│ │ │ ├── 📂 xlsx
│ │ │ │ ├── 💹 Lista de funcionários.xlsx
│ │ │ │ ├── 💹 SPAC903_82_Colab_Tathi_Complemento_Original_.xlsx
│ │ │ │ └── 💹 SPAC903_82_Colab_Tathi_Original.xlsx
│ │ │ │
│ │ │ ├── 📓 Analisando Colaboradores que Fizeram Hora Extra.ipynb
│ │ │ ├── 🪶 df_ronda.parquet
│ │ │ ├── 📓 Inserindo a coluna funcao.ipynb
│ │ │ ├── 💹 SPAC903_82_Final.xlsx
│ │ │ └── 📓 Transformando de xlsx para parquet.ipynb
│ │ │
│ │ ├── 📂 Analisando Irregularidades dos Registros/
│ │ │ ├── 📂 outputs_irregularidades
│ │ │ │ ├── 📂 dfs
│ │ │ │ │ ├── 🪶 irregularidade_999_como_trajeto.parquet
│ │ │ │ │ ├── 🪶 irregularidade_ausencia_das_horas_presenciais_minimas.parquet
│ │ │ │ │ ├── 🪶 irregularidade_ausencia_de_descanso_entre_jornadas_de_trabalho.parquet
│ │ │ │ │ ├── 🪶 irregularidade_executivos_com_historico_de_999_como_trajeto.parquet
│ │ │ │ │ ├── 🪶 irregularidade_nao_entrou_no_refeitorio_mas_passou_no_grill.parquet
│ │ │ │ │ ├── 🪶 irregularidade_pessoas_sem_cumprir_os_3_dias_presenciais_em_semana_de_feriado_prolongado.parquet
│ │ │ │ │ ├── 🪶 irregularidade_pessoas_trabalhando_alem_da_jornada_de_trabalho.parquet
│ │ │ │ │ ├── 🪶 irregularidade_pessoas_trabalhando_sem_ganhar.parquet
│ │ │ │ │ ├── 🪶 irregularidade_ponto_sem_portaria.parquet
│ │ │ │ │ ├── 🪶 irregularidade_registro_sem_portaria.parquet
│ │ │ │ │ └── 🪶 irregularidade_registros_de_pessoas_desligadas.parquet
│ │ │ │ │
│ │ │ │ ├── 📂 pdfs
│ │ │ │ │ ├── 📝 irregularidade_999_como_trajeto.pdf
│ │ │ │ │ ├── 📝 irregularidade_ausencia_das_horas_presenciais_minimas.pdf
│ │ │ │ │ ├── 📝 irregularidade_ausencia_de_descanso_entre_jornadas_de_trabalho.pdf
│ │ │ │ │ ├── 📝 irregularidade_executivos_com_historico_de_999_como_trajeto.pdf
│ │ │ │ │ ├── 📝 irregularidade_nao_entrou_no_refeitorio_mas_passou_no_grill.pdf
│ │ │ │ │ ├── 📝 irregularidade_pessoas_sem_cumprir_os_3_dias_presenciais_em_semana_de_feriado_prolongado.pdf
│ │ │ │ │ ├── 📝 irregularidade_pessoas_trabalhando_alem_da_jornada_de_trabalho.pdf
│ │ │ │ │ ├── 📝 irregularidade_pessoas_trabalhando_sem_ganhar.pdf
│ │ │ │ │ ├── 📝 irregularidade_ponto_sem_portaria.pdf
│ │ │ │ │ ├── 📝 irregularidade_registro_sem_portaria.pdf
│ │ │ │ │ └── 📝 irregularidade_registros_de_pessoas_desligadas.pdf
│ │ │ │ │
│ │ │ │ └── 📓 Validando cada Irregularidade.ipynb
│ │ │ │
│ │ │ ├── 📓 Coluna Data_Dem.ipynb
│ │ │ ├── 📓 Criando Base das Irregularidades.ipynb
│ │ │ ├── 🪶 df_desligados.parquet
│ │ │ ├── 🪶 df_ronda.parquet
│ │ │ └── 📝 Termo de Adesão ao Trabalho Remoto.pdf
│ │ │
│ │ ├── 📂 Análise feita com PDFs/
│ │ │ ├── 📂 Base de Dados
│ │ │ │ ├── 📝 relatorio A.M.N.M.  01.24_31.03.pdf
│ │ │ │ └── 📝 relatorio N.P.N.I.  01.24_31.03.pdf
│ │ │ │
│ │ │ └── 📂 Códigos
│ │ │   ├── 📓 Análise dias presenciais A.M.N.M. - Nicholas.ipynb
│ │ │   ├── 📓 Análise dias presenciais N.P.N.I. - Nicholas.ipynb
│ │ │   ├── 💹 presenca_por_semana A.M.N.M. 01.24_31.03.xlsx
│ │ │   └── 💹 presenca_por_semana N.P.N.I. 01.24_31.03.xlsx
│ │ │
│ │ ├── 📂 Análise feita pelo Antigo Colaborador/
│ │ │ ├── 📂 Análise - Antigo Colaborador
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
│ │ │ ├── 📂 validation_base
│ │ │ │ ├── 📂 csv
│ │ │ │ │ └── 🧾 Colaboradores.csv
│ │ │ │ │
│ │ │ │ └── 📂 parquet
│ │ │ │   └── 🪶 Colaboradores.parquet
│ │ │ │
│ │ │ ├── 📂 xlsx
│ │ │ │  └── 💹 Horas Registradas.xlsx
│ │ │ │
│ │ │ ├── 📓 Análise das horas dos colaboradores.ipynb
│ │ │ ├── 💹 Arquivo Solicitado - Colaboradores não Presentes.xlsx
│ │ │ └── 📓 Transformando de csv para parquet.ipynb
│ │ │
│ │ ├── 📂 Análise sobre a área B-ROT (Irregularidade 999)/
│ │ │ ├── 📂 Bases Separadas
│ │ │ │ ├── 🧾 dados_individuais_2026.CSV
│ │ │ │ └── 📓 transformando csv em parquet.ipynb
│ │ │ │
│ │ │ ├── 📂 saidas_relatorio
│ │ │ │ ├── 💹 Linhas_Irregularidade_999_B-ROT.xlsx
│ │ │ │ └── 📝 Relatorio_Auditoria_Irregularidade_999_B-ROT.pdf
│ │ │ │
│ │ │ ├── 📓 Código.ipynb
│ │ │ ├── 🪶 dados.parquet
│ │ │ └── 🪶 df_ronda.parquet
│ │ │
│ │ ├── 📂 Análise sobre Base Inicial/
│ │ │ ├── 📓 Análise das movimentacoes.ipynb
│ │ │ ├── 📓 Análise geral.ipynb
│ │ │ └── 💹 Colaboradores e Areas com Problemas.xlsx
│ │ │
│ │ ├── 📂 Análise sobre Feriados Prolongados da Auditoria/
│ │ │ ├── 📓 Código.ipynb
│ │ │ └── 📝 Relatório da Auditoria Interna.pdf
│ │ │
│ │ ├── 📂 Análise sobre Possível Relacionamento/
│ │ │ ├── 📓 Código.ipynb
│ │ │ ├── 💹 comparacao_4062738_4063656.xlsx
│ │ │ ├── 💹 dados_4062738.xlsx
│ │ │ ├── 💹 dados_4063656.xlsx
│ │ │ ├── 📖 readme.md
│ │ │ └── 📦 requirements.txt
│ │ │
│ │ ├── 📂 Análise Tempo de Casa/
│ │ │ ├── 🖼️ code.png
│ │ │ └── 🖼️ resultado.png
│ │ │
│ │ ├── 📂 Consolidando as Planilhas do Excel/
│ │ │ ├── 📂 data
│ │ │ │ ├── 💹 Backlog 2025.xlsx
│ │ │ │ └── 💹 Backlog 2025_consolidado.xlsx
│ │ │ │
│ │ │ └── 📓 Análise das Planilhas.ipynb
│ │ │
│ │ ├── 📂 Convertendo o Formato das Bases/
│ │ │ ├── 📓 Transformando de csv para parquet.ipynb
│ │ │ └── 📓 Transformando de xlsx para parquet.ipynb
│ │ │
│ │ ├── 📂 Corrigindo CSV Fornecido/
│ │ │ ├── 📂 Executivos_SQL
│ │ │ │ └── 🧾 Executivos_SQL.csv
│ │ │ │
│ │ │ ├── 📂 Mensalistas_SQL
│ │ │ │ └── 🧾 Mensalistas_SQL.csv
│ │ │ │
│ │ │ └── 📓 Corrigindo o csv novo.ipynb
│ │ │
│ │ └── 📂 Tratando Base Misturada/
│ │   ├── 📂 Ativos e Desligados
│ │   │ └── 📂 xlsx
│ │   │   ├── 💹 Ativos e Desligados - 06-31-2025.xlsx
│ │   │   ├── 💹 Ativos e Desligados - 09-30-2025.xlsx
│ │   │   └── 💹 Ativos e Desligados - 12-31-2025.xlsx
│ │   │
│ │   └── 📂 Movimentacoes
│ │     ├── 📂 xlsx
│ │     │ ├── 💹 Movimentacoes_01-01-2023_09-30-2025.xlsx
│ │     │ └── 💹 Movimentacoes_10-01-2025_12-31-2025.xlsx
│ │     │
│ │     └── 📓 Validando novas bases.ipynb
│ │
│ ├── 📓 DDL.ipynb
│ ├── 📓 Projeto unificado.ipynb
│ ├── 🖼️ Visualização da Estrutura DW - Camada de Views.png
│ └── 🖼️ Visualização da Estrutura DW - Modelo Físico.png
│
├── 📁 project/
│ ├── 📂 database/
│ │ ├── 🗄️ db_login.sqlite
│ │ ├── 🗄️ dw_ronda.sqlite
│ │ ├── 🗄️ dw_ronda.sqlite-shm
│ │ └── 🗄️ dw_ronda.sqlite-wal
│ │
│ ├── 📂 images/
│ │ ├── 🧊 logo_blue.ico
│ │ └── 🖼️ logo_white.png
│ │
│ └── 📂 src/
│   ├── 📂 api/
│   │ ├── 🐍 area.py
│   │ ├── 🐍 general.py
│   │ ├── 🐍 individual.py
│   │ ├── 🐍 relacionamento.py
│   │ └── 🐍 router.py
│   │
│   ├── 📂 core/
│   │ ├── 🐍 config.py
│   │ └── 🐍 repo_global.py
│   │
│   ├── 📂 data/
│   │ ├── 🐍 datasets.py
│   │ ├── 🐍 fix_terceiros_dw.py
│   │ ├── 🐍 rebuild_dw_from_parquet.py
│   │ └── 🐍 reduce_terceiros_quarter.py
│   │
│   ├── 📂 domain/
│   │ ├── 🐍 builders.py
│   │ ├── 🐍 cache_utils.py
│   │ ├── 🐍 cargo.py
│   │ ├── 🐍 copresenca.py
│   │ ├── 🐍 exports.py
│   │ ├── 🐍 filters.py
│   │ ├── 🐍 gptw.py
│   │ ├── 🐍 periods.py
│   │ ├── 🐍 pipeline.py
│   │ └── 🐍 tenure.py
│   │
│   ├── 📂 ui/
│   │ ├── 🐍 figures.py
│   │ ├── 🐍 gptw.py
│   │ ├── 🐍 layout.py
│   │ ├── 🐍 tables.py
│   │ └── 🐍 theme.py
│   │
│   ├── 🐍 main.py
│   └── 🐍 sample_runner.py
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
|     📓    |       `.ipynb`      |                Notebooks Jupyter                |
|     🐍    |        `.py`        |                  Código Python                  |
|     🧊    |        `.ico`       |                 Ícones/favicons                 |
|     🖼️    |        `.png`       |                     Imagens                     |
|     ⚡    |        `.js`        |                Scripts JavaScript               |
|     🎨    |        `.css`       |                 Estilos visuais                 |
|     🧱    |       `.html`       |                   ui/front-end                  |
|     🗄️    |      `.sqlite`      |               Banco de Dados local              |
|     ⚙️    |     `.gitignore`    |            Regras de ignorados do Git           |
|     📖    |        `.md`        |              Documentação Markdown              |
|     📦    |  `requirements.txt` |              Dependências do Python             |


## 🗃️ Estrutura dos DataFrames (atualizado)

> Referência: DW otimizado **serving-only** (sem `evento_acesso_flat` no arquivo final) + `agg_semana_enriquecida` virou **VIEW** (não é mais tabela materializada).
> Regra geral: **fatos/aggs não carregam dimensão**; enriquecimento acontece via **views** ou `merge` pontual com `df_colaboradores`.

---

### 🪶 `project/database/df_ronda.parquet` — Base final de registros

**Origem:** `Base de Dados Original/parquet/Registros/` + `Base de Dados Original/parquet/Ajustes Manuais/`.

* `Manual = Não`: registros originais do Ronda.
* `Manual = Sim`: ajustes manuais consolidados a partir dos CSVs em `Base de Dados Original/csv/Ajustes Manuais/`.

Essa coluna permite analisar os ajustes manuais dentro da mesma trajetória dos registros,
sem separar uma base paralela para auditoria.

---

### 📆 `df_registros_semanais` — Presença semanal (fato/agg)

**Chave lógica:** (`Cadastro`, `Ano`, `Semana por Ano`) → **1 linha por semana por pessoa**

* `Cadastro` (string / Int64 — escolha e mantenha consistente)
* `Ano` (int)
* `Semana por Ano` (int)
* `Data` (datetime)

  > *Data âncora da semana (recomendado: **segunda-feira** ou outro “anchor” fixo). Mantida para preservar comportamentos antigos (slider/range/plots).*
* `Contagem Presença` (int)

  > *Contagem de dias de presença na semana (ex.: 0..7), conforme já era no app.*

**Observações**

* Não deve conter colunas de dimensão (Nome/Área/Depto/etc.). Isso vem de `df_colaboradores` **apenas quando necessário** (ou via view).
* `Data` deve ser **determinística** para (`Cadastro`,`Ano`,`Semana por Ano`). Se variar, pode quebrar filtros/plots e causar duplicação em merges.

---

### 🗓️ `df_diarios` — Presença diária (fato/agg)

**Chave lógica recomendada:** (`Cadastro`, `Data`)
*(se existir necessidade real de múltiplas plantas por dia, então (`Cadastro`, `Data`, `Planta`))*

* `Cadastro` (string / Int64)
* `Planta` (string/int/categorical) *(se aplicável)*
* `Data` (datetime)

**Observações**

* Colunas como `Dia Semana`, `Semana por Ano`, `Ano` **não precisam existir na base** (podem ser derivadas via `.dt` quando o app precisar).
* Esse é o fato enxuto para presença diária. Evite enriquecer com dimensões aqui.

---

### 🍽️ `df_almoco` — Registros de refeitório (fato auxiliar)

**Chave lógica típica:** (`Cadastro`, `Data`, `Hora`, `Coletor`) *(pode variar)*

* `Cadastro` (string / Int64)
* `Data` (datetime)
* `Hora` (string ou `datetime.time`)
* `Dir` (string)
* `Planta` (string/int/categorical)
* `Coletor` (int/string)
* `Descricao Coletor` (string)

**Observações**

* **Não** carrega mais dimensão (Nome, Área, Depto, Cargo, Desligado…).
* Se o app precisar exibir atributos do colaborador, faça `merge` com `df_colaboradores` por `Cadastro` **somente quando necessário** (ou crie uma view enriquecida pontual).

---

### 🧑‍💼 `df_colaboradores` — Dimensão de colaboradores (1:1 por pessoa)

**Chave:** `Cadastro` (deve ser única; se não for, tratar com `drop_duplicates` + regra)

* `Cadastro` (string / Int64)
* `Nome` (string)
* `Área` (string)
* `Departamento` (string)
* `Heranca` (string)
* `Cargo` (string)

  > **Regra:** `Cargo` == `SgEmp` (código vindo de ativos).
* `Cargo Especifico` (string)
* `Desligado` (string/bool, conforme já era)
* `Data_Admissão` (datetime)
* `Data_Demissão` (datetime)

  > *Vem de `df_desligados['Data_Dem']` renomeada (quando existir).*

**Mapeamento opcional de categoria de Cargo (somente se necessário)**
Se em algum lugar do app o “Cargo” era usado como **categoria** (Horista/Mensalista/Executivo), crie uma coluna extra (ex.: `Tipo_Cargo`) baseada na 1ª letra:

* `H` → `Horista`
* `M` → `Mensalista`
* `E` → `Executivo`
* outro → `Outros`

> **Importante:** não substitua `Cargo` (código) por essa categoria.

---

### 🔄 `df_movimentacoes` — Movimentações (fato)

**Chave lógica:** (`Cadastro`, `Data de alteração`, `Tipo da Movimentação`) → **1 linha por evento por pessoa**

* `Cadastro` (string / Int64 — escolha e mantenha consistente)
* `Tipo da Movimentação` (string)

  > *Ex.: Admissão, Transferência, Promoção, Desligamento (depende do arquivo).*
* `Data de alteração` (datetime)

  > *Data em que a mudança organizacional foi registrada.*
* `Abreviação UO antiga` (string)
* `Desc. UO antiga` (string)
* `Desc. Cargo antigo` (string)
* `Abreviação UO` (string)
* `Desc. UO` (string)
* `Desc. Cargo` (string)

**Observações**

* Não deve conter colunas de dimensão (Nome/Área/Departamento). Isso vem de `df_colaboradores` **apenas quando necessário**.
* Pode existir mais de 1 movimentação no mesmo dia para o mesmo `Cadastro`. Se ocorrer repetição, trate duplicados (`drop_duplicates`) ou crie uma chave técnica.
* Para exibir **Nome do colaborador**, faça `merge` com `df_colaboradores[['Cadastro','Nome']]` por `Cadastro` (garantindo unicidade).

---

### 🏆 `df_gptw` — Indicadores GPTW (dimensão/indicador)

* `Área` (string)
* `2025` (float/int)
* `2024` (float/int)
* `2023` (float/int)

> *Estrutura em formato largo (cada ano como coluna).*
> *Opcional (recomendado para evolução): converter para formato longo:* `Área`, `Ano`, `Nota`.

---

### ⭐ `df_semana_enriquecida` — **VIEW** (não materializada)

> **Atualização importante:** `df_semana_enriquecida` agora deve ser tratada como **view** (`vw_semana_enriquecida`) construída a partir de:

* `df_registros_semanais` (fato/agg “skinny”)
* `df_colaboradores` (dimensão)

**Objetivo:** disponibilizar campos de dimensão (Nome/Área/Depto/Herança/Cargo) **sem duplicar** essas colunas em uma tabela grande.

**Observações**

* Não use essa view como “fonte” para gerar novas tabelas grandes sem necessidade.
* A performance depende dos índices das tabelas base (`df_registros_semanais` e `df_colaboradores`), não de índice na view.

## 🔁 Lógica “Mesma Planta”

Nos heatmaps:
- Conta encontro **apenas** quando ambos estão **presentes no mesmo dia e na mesma `Planta`**.
- Percentual = `encontros / presença_base * 100`.

Implementação:  
→ `domain/copresenca.py`  
→ Função principal: `calcular_copresenca(df_datas, area)`

## ⚙️ Configuração via `.env`

Use `.env` local (ignorado pelo Git) com as variáveis abaixo:

```dotenv
# Fonte canonica (obrigatoria para equivalencia com o notebook)
RONDA_DW_PATH=../_dados_ronda_local/project/database/dw_ronda.sqlite

# Opcional: base de login (evite usar no modo publico)
RONDA_LOGIN_DB_PATH=../_dados_ronda_local/project/database/db_login.sqlite

# Opcional: pasta de dados brutos locais (csv/xlsx fora do repo)
RONDA_RAW_DATA_DIR=../_dados_ronda_local/Base de Dados Original

# Runtime
ND_PANDAS_LOCALE=pt_BR.utf8
ND_CACHE_TTL=900
ND_DEBUG=false
ND_PORT=8050

# Automacao de print da Consulta Pessoal via Playwright
CONSULTA_PESSOAL_BROWSER_CHANNEL=msedge
CONSULTA_PESSOAL_BROWSER_EXECUTABLE=
```

Sem `RONDA_DW_PATH`, o app tenta fallback parquet legado.

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
playwright>=1.58
```

## 🚀 Como rodar o projeto

```powershell
# 1) Ambiente virtual
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) Dependencias
pip install -r requirements.txt

# 3) Configurar .env local (baseado no .env.example)

# 4) Subir o MVC
py -3 -m project.src.main
```

App: `http://localhost:8050`

Comando unico alternativo (bootstrap rapido):

```powershell
py -3 -c "import project.src.main as m; m.create_app(); print('ok')"
```

## 🧪 Testes e Validação

Suíte automatizada rastreada: não identificada.

Validações mínimas recomendadas:

```powershell
# Compilar arquivos Python sem executar o dashboard
py -3 -m compileall project "Códigos Extras"

# Bootstrap do app, quando as variáveis de dados estiverem configuradas
py -3 -c "import project.src.main as m; m.create_app(); print('ok')"
```

Ao reintroduzir testes automatizados, priorize equivalência entre notebook e MVC:
- mesmas colunas/ordem
- mesmos valores numéricos
- delegacao dos builders para SQL canonica

## 🔐 Publicação Segura (repo público)

- Não versione dados reais, SQLite, WAL/SHM, dumps ou `.env` real.
- Mantenha dados locais fora do repositório em `../_dados_ronda_local/`.
- Use somente `.env.example` no Git.
- O MVC agora lê `RONDA_DW_PATH` externamente para reproduzir o notebook sem copiar base para dentro do repo.

## 🧠 Cache & Performance
- Cache leve (Flask-Caching) para DataFrames semanais
- TTL configurável via `ND_CACHE_TTL` (padrão: 900 s)
- Funções puras menores usam `functools.lru_cache` (ex.: normalização de `Cadastro` em `api/relacionamento.py`)
- Caches de escopo `register(app)` em `relacionamento.py` para o mapa `Cadastro→Nome` e opções de dropdown (evita refazer `drop_duplicates`/`iterrows` em cada disparo de callback)
- Filtragem do `df_datas` global feita por `isin` com variantes int/float/str — não converte a coluna inteira para string a cada callback
- Janelas curtas para o lazy-load do DW na aba Relacionamento (12 meses) e para a consulta de almoço (12 meses) — mantém o callback responsivo mesmo com histórico longo
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
| `general.py` | Aba inicial | KPIs, boxplots e indicadores gerais (meta semanal aplica regra vigente por período, com mudança em mai/2025) |
| `area.py` | Aba por área | Heatmaps e filtros dinâmicos por departamento |
| `relacionamento.py` | Aba de relacionamentos | Séries semanais, tags, modo Almoço, comparativos — com caches em `register(app)` para lookups pesados |
| `individual.py` | Relatório individual | Termômetro (gauge), histórico, gradiente de severidade por semana (0/1/2 dias) e exportação PDF/JPG |
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

## 🛠️ Solução de Problemas

| Problema | Causa | Solução |
|:----------|:--------|:--------|
| `ModuleNotFoundError: 'src.api'` | Execução fora da raiz | Execute `python -m src.main` |
| Meses não aparecem em pt-BR | Locale do SO | Usa `Timestamp.month_name(locale='pt_BR')` |
| Nenhum dado no gráfico | Coluna ausente | Confirme `Planta` e `Data` em `df_datas` |
| Tags não aparecem | Store vazio | Adicione tags via interface lateral |
| Slider bugado | Coluna `Data` inválida | Verifique `df_datas['Data']` coerente |
| `/relacionamento` "Updating..." infinito | Histórico longo + DW frio | Janela é capada em 12 meses; reinicie o servidor Dash para refletir as mudanças |
| Cores no `Imprimir` saem em cinza | `print-color-adjust` ausente | `ui/theme.py` força `-webkit-print-color-adjust: exact` para Plotly/DataTable/SVG |

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
      <img src="project\website\images\logo_white.png"
           width="150"
           style="vertical-align: middle;"
           alt="logo_blue VW">
    </td>
    <td style="border-left: 3px solid #ffffffff; padding-left: 10px;">
      <p style="margin: 0; font-size: 17px; font-weight: 700; color: #ffffffff;">Nicholas Birochi</p>
      <p style="margin: 2px 0; color: #444; font-size: 14px;">Estagiário de Análise de Dados | Data Analytics</p>
      <p style="margin: 2px 0; color: #444; font-size: 14px;">Volkswagen do Brasil</p>
      <p style="margin: 6px 0; font-size: 13px;">
        <span style="color: #0055A5; font-weight: 500;">Email corporativo sob demanda</span> &nbsp;•&nbsp;
        <a href="https://www.linkedin.com/in/nicholas-birochi/" style="color: #0A66C2; text-decoration: none; font-weight: 500;">LinkedIn</a> &nbsp;•&nbsp;
        <a href="https://github.com/nicholasbirochi" style="color: #181717; text-decoration: none; font-weight: 500;">GitHub</a> &nbsp;•&nbsp;
        <a href="https://app.rocketseat.com.br/me/nicholas-birochi-1501" style="color: #8257E5; text-decoration: none; font-weight: 500;">Rocketseat</a>
      </p>
    </td>
  </tr>
</table>
