"""theme.py

Tema e padrões visuais para componentes e gráficos.

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations


# Estilos utilitários ---------------------------------------------------------
VW_FONT_FAMILY = "'VW Text', Arial, sans-serif"
VW_PLOTLY_FONT = "VW Text"
GLOBAL_CSS = f"""
@font-face {{
  font-family: 'VW Text';
  src: local('VW Text');
}}
* {{
  font-family: {VW_FONT_FAMILY} !important;
}}
.lang-wrap {{
  display: grid;
  justify-items: end;
  position: relative;
  z-index: 30;
  flex: 0 0 132px;
  min-width: 132px;
}}
.flag-switcher {{
  position: relative;
  width: 132px;
  min-width: 132px;
  height: 48px;
  min-height: 48px;
  overflow: visible;
  isolation: isolate;
}}
.flag-switcher::before {{
  content: "";
  position: absolute;
  top: -9px;
  right: -9px;
  width: calc(100% + 18px);
  height: calc(var(--menu-height, 48px) + 18px);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(0, 0, 0, 0.10);
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.18);
  opacity: 0;
  transform: translateY(-4px);
  transition: opacity 160ms ease, transform 160ms ease;
  pointer-events: none;
  z-index: -1;
}}
.flag-switcher.open {{
  z-index: 50;
}}
.flag-switcher.open::before {{
  opacity: 1;
  transform: translateY(0);
}}
.lang-flag {{
  position: absolute;
  top: 0;
  right: 0;
  display: flex;
  width: 132px;
  min-width: 132px;
  height: 48px;
  padding: 5px 14px 5px 5px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  background: rgba(245, 247, 250, 0.96);
  color: #000000;
  align-items: center;
  justify-content: flex-start;
  gap: 11px;
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transform: translateY(var(--menu-y, 0px));
  transition: transform 160ms ease, background 160ms ease,
              border-color 160ms ease, box-shadow 160ms ease, opacity 120ms ease;
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.10);
}}
.lang-flag.active {{
  opacity: 1;
  pointer-events: auto;
  background: #ffffff;
  border-color: rgba(0, 30, 80, 0.58);
  box-shadow: 0 10px 24px rgba(0, 30, 80, 0.18);
}}
.flag-switcher.open .lang-flag {{
  opacity: 1;
  pointer-events: auto;
}}
.lang-flag.active::after {{
  content: "▾";
  margin-left: auto;
  font-size: 13px;
  line-height: 1;
  color: rgba(0, 0, 0, 0.70);
  letter-spacing: 0;
}}
.flag-switcher.open .lang-flag.active::after {{
  content: "▴";
}}
.lang-flag:hover {{
  transform: translateY(calc(var(--menu-y, 0px) - 1px));
  background: #ffffff;
  border-color: rgba(0, 30, 80, 0.38);
}}
.lang-flag[data-lang="pt"] {{ background: rgba(179, 229, 196, 0.34); }}
.lang-flag[data-lang="en"] {{ background: rgba(194, 220, 245, 0.36); }}
.lang-flag[data-lang="de"] {{ background: rgba(223, 227, 234, 0.38); }}
.lang-flag[data-lang="es"] {{ background: rgba(248, 228, 170, 0.40); }}
.lang-flag[data-lang="pl"] {{ background: rgba(247, 214, 221, 0.38); }}
.lang-flag[data-lang="sk"] {{ background: rgba(210, 225, 247, 0.38); }}
.lang-flag[data-lang="zh"] {{ background: rgba(248, 210, 198, 0.38); }}
.lang-flag[data-lang="hi"] {{ background: rgba(232, 232, 232, 0.42); }}
.lang-flag:focus-visible {{
  outline: 3px solid rgba(0, 87, 184, 0.32);
  outline-offset: 2px;
}}
.flag-disc {{
  width: 38px;
  height: 38px;
  border-radius: 999px;
  overflow: hidden;
  flex: 0 0 38px;
  border: 2px solid rgba(255, 255, 255, 0.90);
  background: #ffffff;
  box-shadow: 0 3px 9px rgba(0, 0, 0, 0.18);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}}
.flag-disc img {{
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}}
.flag-label {{
  display: inline-block;
  min-width: 28px;
  text-align: left;
}}
.prefiltro-panel {{
  width: min(980px, calc(100vw - 32px));
  background: #e0e0e0;
  border: 1px solid rgba(0, 0, 0, 0.10);
  border-radius: 20px;
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.16);
  overflow: hidden;
}}
.prefiltro-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 24px 28px 20px;
  background: #ffffff;
  border-bottom: 1px solid rgba(0, 0, 0, 0.12);
}}
.prefiltro-form-grid {{
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(260px, 0.85fr);
  gap: 18px;
  padding: 22px 28px 8px;
}}
.prefiltro-field {{
  min-width: 0;
}}
.prefiltro-field-wide {{
  grid-column: 1 / -1;
}}
.prefiltro-field-shell {{
  background: rgba(255, 255, 255, 0.70);
  border: 1px solid rgba(0, 0, 0, 0.10);
  border-radius: 10px;
  padding: 14px;
}}
.prefiltro-field-title {{
  display: block;
  margin-bottom: 10px;
  color: #000000;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0;
}}
.prefiltro-cargo-lista {{
  display: grid !important;
  grid-template-columns: repeat(auto-fit, minmax(165px, 1fr));
  gap: 10px;
}}
.prefiltro-opcoes-lista {{
  display: grid !important;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}}
.prefiltro-cargo-lista label,
.prefiltro-opcoes-lista label,
.prefiltro-cenario-lista label {{
  display: inline-flex !important;
  align-items: center;
  gap: 8px;
  min-height: 48px;
  margin: 0 !important;
  padding: 10px 12px;
  background: #ffffff;
  border: 1px solid rgba(0, 0, 0, 0.16);
  border-radius: 8px;
  box-shadow: 0 2px 7px rgba(0, 0, 0, 0.07);
  cursor: pointer;
  line-height: 1.15;
  min-width: 0;
  transition: border-color 120ms ease, box-shadow 120ms ease, background 120ms ease;
}}
.prefiltro-cargo-lista label:has(input:checked),
.prefiltro-opcoes-lista label:has(input:checked),
.prefiltro-cenario-lista label:has(input:checked) {{
  background: #f7fbff;
  border-color: rgba(0, 30, 80, 0.72);
  box-shadow: 0 7px 16px rgba(0, 30, 80, 0.14);
}}
.prefiltro-cargo-lista input,
.prefiltro-opcoes-lista input,
.prefiltro-cenario-lista input {{
  width: 16px;
  height: 16px;
  margin: 0 !important;
  accent-color: #001e50;
  flex: 0 0 auto;
}}
.prefiltro-cargo-badge {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #e0e0e0;
  color: #000000;
  font-weight: 800;
  flex: 0 0 28px;
}}
.prefiltro-cargo-lista label span:last-child {{
  min-width: 0;
  overflow-wrap: normal;
  white-space: nowrap;
}}
.prefiltro-cenario-lista {{
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-bottom: 14px;
}}
.prefiltro-footer {{
  display: flex;
  justify-content: flex-end;
  padding: 14px 28px 26px;
}}
.prefiltro-confirmar {{
  min-width: 150px;
}}
@media (max-width: 1120px) {{
  .prefiltro-panel {{
    width: min(980px, calc(100vw - 28px));
  }}
  .prefiltro-form-grid {{
    grid-template-columns: 1fr;
  }}
  .prefiltro-cargo-lista {{
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }}
}}
@media (max-width: 980px) {{
  .prefiltro-panel {{
    width: min(760px, calc(100vw - 28px));
  }}
  .prefiltro-header {{
    align-items: flex-start;
    flex-direction: column;
    padding: 22px 24px 18px;
  }}
  .prefiltro-form-grid {{
    grid-template-columns: 1fr;
    padding: 20px 24px 6px;
  }}
  .prefiltro-cargo-lista {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
  .prefiltro-footer {{
    padding: 14px 24px 24px;
  }}
}}
@media (max-width: 620px) {{
  .prefiltro-panel {{
    width: calc(100vw - 20px);
    border-radius: 14px;
  }}
  .prefiltro-header {{
    padding: 18px;
  }}
  .prefiltro-form-grid {{
    gap: 14px;
    padding: 16px 18px 4px;
  }}
  .prefiltro-field-shell {{
    padding: 12px;
  }}
  .prefiltro-cargo-lista {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
  .prefiltro-opcoes-lista {{
    grid-template-columns: 1fr;
  }}
  .prefiltro-cenario-lista label {{
    flex: 1 1 100%;
    justify-content: flex-start;
  }}
  .prefiltro-footer {{
    padding: 12px 18px 20px;
  }}
  .prefiltro-confirmar {{
    width: 100%;
  }}
}}
@media (max-width: 390px) {{
  .prefiltro-cargo-lista {{
    grid-template-columns: 1fr;
  }}
}}
@media (max-width: 760px) {{
  .lang-wrap {{
    flex-basis: 112px;
    min-width: 112px;
  }}
  .flag-switcher,
  .lang-flag {{
    width: 112px;
    min-width: 112px;
  }}
  .lang-flag {{
    height: 46px;
    padding-right: 11px;
    gap: 9px;
    font-size: 14px;
  }}
  .flag-disc {{
    width: 34px;
    height: 34px;
    flex-basis: 34px;
  }}
}}
"""

LANGUAGE_JS = r"""
(function () {
  const storageKey = "mvc-dashboard-idioma";
  const preferred = ["pt", "en", "de", "es", "pl", "sk", "zh", "hi"];
  const translations = {
    pt: {
      html_lang: "pt-BR",
      title: "Relatório Presencial - Volkswagen",
      main_title: "Relatório Presencial Geral de toda a Volkswagen",
      selected_period_prefix: "Período selecionado",
      selected_period_to: "a",
      show_inactive: "Mostrar as pessoas desligadas?",
      show_travel: "Mostrar as áreas que viajam?",
      yes: "Sim",
      no: "Não",
      scenario_1: "Jan/2024 a Abr/2025",
      scenario_2: "Mai/2025 em diante",
      area_summary: "Resumo Específico por Área",
      relationship_link: "Relacionamento entre Colaboradores ⭢",
      people_presence: "Presença dos Colaboradores",
      distribution_title: "Distribuição de Colaboradores por Faixa",
      average_band_axis: "Faixa de Média (dias/semana)",
      collaborator_info: "Informações de Colaboradores",
      total_collaborators: "Total de Colaboradores:",
      third_parties: "Terceiros:",
      hourly: "Horistas:",
      monthly: "Mensalistas:",
      executives: "Executivos:",
      weekly_avg: "Média de Presença por Semana",
      total: "Total:",
      scatter_title: "Dispersão Geral (Todos)",
      presence_cargo_title: "Presença por Cargo (Todos)",
      people_axis: "Pessoas",
      average_presence: "Média Presença",
      dropdown_general: "Geral (todas as areas)",
      search_chapa: "Buscar colaborador pela chapa..."
    },
    en: {
      html_lang: "en",
      title: "On-site Attendance Report - Volkswagen",
      main_title: "General On-site Attendance Report for Volkswagen",
      selected_period_prefix: "Selected period",
      selected_period_to: "to",
      show_inactive: "Show terminated people?",
      show_travel: "Show areas that travel?",
      yes: "Yes",
      no: "No",
      scenario_1: "Jan/2024 to Apr/2025",
      scenario_2: "May/2025 onward",
      area_summary: "Area-specific Summary",
      relationship_link: "Employee Relationship ⭢",
      people_presence: "Employee Attendance",
      distribution_title: "Employee Distribution by Range",
      average_band_axis: "Average Range (days/week)",
      collaborator_info: "Employee Information",
      total_collaborators: "Total Employees:",
      third_parties: "Third parties:",
      hourly: "Hourly:",
      monthly: "Monthly:",
      executives: "Executives:",
      weekly_avg: "Average Attendance per Week",
      total: "Total:",
      scatter_title: "General Dispersion (All)",
      presence_cargo_title: "Attendance by Role (All)",
      people_axis: "People",
      average_presence: "Average Attendance",
      dropdown_general: "General (all areas)",
      search_chapa: "Search employee by badge..."
    },
    de: {
      html_lang: "de",
      title: "Anwesenheitsbericht - Volkswagen",
      main_title: "Allgemeiner Präsenzbericht für Volkswagen",
      selected_period_prefix: "Ausgewählter Zeitraum",
      selected_period_to: "bis",
      show_inactive: "Ausgeschiedene Personen anzeigen?",
      show_travel: "Reisende Bereiche anzeigen?",
      yes: "Ja",
      no: "Nein",
      scenario_1: "Jan/2024 bis Apr/2025",
      scenario_2: "Ab Mai/2025",
      area_summary: "Bereichsspezifische Zusammenfassung",
      relationship_link: "Beziehungen zwischen Mitarbeitenden ⭢",
      people_presence: "Anwesenheit der Mitarbeitenden",
      distribution_title: "Verteilung der Mitarbeitenden nach Bereich",
      average_band_axis: "Durchschnittsbereich (Tage/Woche)",
      collaborator_info: "Mitarbeitendeninformationen",
      total_collaborators: "Mitarbeitende gesamt:",
      third_parties: "Dritte:",
      hourly: "Stundenlohn:",
      monthly: "Monatslohn:",
      executives: "Führungskräfte:",
      weekly_avg: "Durchschnittliche Anwesenheit pro Woche",
      total: "Gesamt:",
      scatter_title: "Allgemeine Streuung (Alle)",
      presence_cargo_title: "Anwesenheit nach Rolle (Alle)",
      people_axis: "Personen",
      average_presence: "Durchschnittliche Anwesenheit",
      dropdown_general: "Allgemein (alle Bereiche)",
      search_chapa: "Mitarbeitende nach Ausweis suchen..."
    },
    es: {
      html_lang: "es",
      title: "Informe Presencial - Volkswagen",
      main_title: "Informe Presencial General de Volkswagen",
      selected_period_prefix: "Periodo seleccionado",
      selected_period_to: "a",
      show_inactive: "¿Mostrar personas desligadas?",
      show_travel: "¿Mostrar áreas que viajan?",
      yes: "Sí",
      no: "No",
      scenario_1: "Ene/2024 a Abr/2025",
      scenario_2: "Desde May/2025",
      area_summary: "Resumen Específico por Área",
      relationship_link: "Relación entre Colaboradores ⭢",
      people_presence: "Presencia de Colaboradores",
      distribution_title: "Distribución de Colaboradores por Rango",
      average_band_axis: "Rango de Media (días/semana)",
      collaborator_info: "Información de Colaboradores",
      total_collaborators: "Total de Colaboradores:",
      third_parties: "Terceros:",
      hourly: "Por hora:",
      monthly: "Mensuales:",
      executives: "Ejecutivos:",
      weekly_avg: "Media de Presencia por Semana",
      total: "Total:",
      scatter_title: "Dispersión General (Todos)",
      presence_cargo_title: "Presencia por Cargo (Todos)",
      people_axis: "Personas",
      average_presence: "Media de Presencia",
      dropdown_general: "General (todas las áreas)",
      search_chapa: "Buscar colaborador por matrícula..."
    },
    pl: {
      html_lang: "pl",
      title: "Raport Obecności - Volkswagen",
      main_title: "Ogólny Raport Obecności Volkswagen",
      selected_period_prefix: "Wybrany okres",
      selected_period_to: "do",
      show_inactive: "Pokazać osoby zwolnione?",
      show_travel: "Pokazać obszary podróżujące?",
      yes: "Tak",
      no: "Nie",
      scenario_1: "Sty/2024 do Kwi/2025",
      scenario_2: "Od Maj/2025",
      area_summary: "Podsumowanie według Obszaru",
      relationship_link: "Relacje między Pracownikami ⭢",
      people_presence: "Obecność Pracowników",
      distribution_title: "Rozkład Pracowników według Zakresu",
      average_band_axis: "Zakres Średniej (dni/tydzień)",
      collaborator_info: "Informacje o Pracownikach",
      total_collaborators: "Łącznie pracowników:",
      third_parties: "Zewnętrzni:",
      hourly: "Godzinowi:",
      monthly: "Miesięczni:",
      executives: "Kadra kierownicza:",
      weekly_avg: "Średnia Obecność na Tydzień",
      total: "Razem:",
      scatter_title: "Rozproszenie Ogólne (Wszyscy)",
      presence_cargo_title: "Obecność według Roli (Wszyscy)",
      people_axis: "Osoby",
      average_presence: "Średnia Obecność",
      dropdown_general: "Ogólnie (wszystkie obszary)",
      search_chapa: "Szukaj pracownika po numerze..."
    },
    sk: {
      html_lang: "sk",
      title: "Prehľad Prezenčnej Účasti - Volkswagen",
      main_title: "Všeobecný Prehľad Prezenčnej Účasti Volkswagen",
      selected_period_prefix: "Vybrané obdobie",
      selected_period_to: "do",
      show_inactive: "Zobraziť ukončených pracovníkov?",
      show_travel: "Zobraziť cestujúce oblasti?",
      yes: "Áno",
      no: "Nie",
      scenario_1: "Jan/2024 do Apr/2025",
      scenario_2: "Od Máj/2025",
      area_summary: "Súhrn podľa Oblasti",
      relationship_link: "Vzťahy medzi Pracovníkmi ⭢",
      people_presence: "Účasť Pracovníkov",
      distribution_title: "Rozdelenie Pracovníkov podľa Rozsahu",
      average_band_axis: "Priemerný Rozsah (dni/týždeň)",
      collaborator_info: "Informácie o Pracovníkoch",
      total_collaborators: "Pracovníci spolu:",
      third_parties: "Tretie strany:",
      hourly: "Hodinoví:",
      monthly: "Mesační:",
      executives: "Vedúci:",
      weekly_avg: "Priemerná Účasť za Týždeň",
      total: "Spolu:",
      scatter_title: "Všeobecný Rozptyl (Všetci)",
      presence_cargo_title: "Účasť podľa Roly (Všetci)",
      people_axis: "Osoby",
      average_presence: "Priemerná Účasť",
      dropdown_general: "Všeobecne (všetky oblasti)",
      search_chapa: "Hľadať pracovníka podľa čísla..."
    },
    zh: {
      html_lang: "zh-CN",
      title: "现场出勤报告 - Volkswagen",
      main_title: "Volkswagen 现场出勤总览报告",
      selected_period_prefix: "已选期间",
      selected_period_to: "至",
      show_inactive: "显示离职人员？",
      show_travel: "显示出差区域？",
      yes: "是",
      no: "否",
      scenario_1: "2024年1月 至 2025年4月",
      scenario_2: "2025年5月起",
      area_summary: "按区域汇总",
      relationship_link: "员工关系 ⭢",
      people_presence: "员工出勤",
      distribution_title: "员工按区间分布",
      average_band_axis: "平均区间（天/周）",
      collaborator_info: "员工信息",
      total_collaborators: "员工总数：",
      third_parties: "第三方：",
      hourly: "小时工：",
      monthly: "月薪：",
      executives: "管理层：",
      weekly_avg: "每周平均出勤",
      total: "总计：",
      scatter_title: "总体分布（全部）",
      presence_cargo_title: "按角色出勤（全部）",
      people_axis: "人数",
      average_presence: "平均出勤",
      dropdown_general: "全部（所有区域）",
      search_chapa: "按工号搜索员工..."
    },
    hi: {
      html_lang: "hi-IN",
      title: "ऑन-साइट उपस्थिति रिपोर्ट - Volkswagen",
      main_title: "Volkswagen की सामान्य ऑन-साइट उपस्थिति रिपोर्ट",
      selected_period_prefix: "चयनित अवधि",
      selected_period_to: "से",
      show_inactive: "सेवा समाप्त लोगों को दिखाएं?",
      show_travel: "यात्रा करने वाले क्षेत्र दिखाएं?",
      yes: "हाँ",
      no: "नहीं",
      scenario_1: "जन/2024 से अप्र/2025",
      scenario_2: "मई/2025 से आगे",
      area_summary: "क्षेत्र के अनुसार सारांश",
      relationship_link: "कर्मचारी संबंध ⭢",
      people_presence: "कर्मचारी उपस्थिति",
      distribution_title: "श्रेणी के अनुसार कर्मचारी वितरण",
      average_band_axis: "औसत श्रेणी (दिन/सप्ताह)",
      collaborator_info: "कर्मचारी जानकारी",
      total_collaborators: "कुल कर्मचारी:",
      third_parties: "तृतीय पक्ष:",
      hourly: "घंटेवार:",
      monthly: "मासिक:",
      executives: "कार्यकारी:",
      weekly_avg: "प्रति सप्ताह औसत उपस्थिति",
      total: "कुल:",
      scatter_title: "सामान्य प्रसार (सभी)",
      presence_cargo_title: "भूमिका के अनुसार उपस्थिति (सभी)",
      people_axis: "लोग",
      average_presence: "औसत उपस्थिति",
      dropdown_general: "सामान्य (सभी क्षेत्र)",
      search_chapa: "बैज से कर्मचारी खोजें..."
    }
  };
  const monthForms = {
    Janeiro: 0, Jan: 0, jan: 0, January: 0, Ene: 0, Sty: 0, "2024年1月": 0, "जन": 0,
    Fevereiro: 1, Fev: 1, fev: 1, February: 1, Feb: 1,
    Março: 2, Mar: 2, mar: 2, March: 2,
    Abril: 3, Abr: 3, abr: 3, April: 3, Apr: 3, Kwi: 3, "अप्र": 3,
    Maio: 4, Mai: 4, mai: 4, May: 4, Maj: 4, Máj: 4, "मई": 4,
    Junho: 5, Jun: 5, jun: 5, June: 5,
    Julho: 6, Jul: 6, jul: 6, July: 6,
    Agosto: 7, Ago: 7, ago: 7, August: 7, Aug: 7,
    Setembro: 8, Set: 8, set: 8, September: 8, Sep: 8,
    Outubro: 9, Out: 9, out: 9, October: 9, Oct: 9,
    Novembro: 10, Nov: 10, nov: 10, November: 10,
    Dezembro: 11, Dez: 11, dez: 11, December: 11, Dec: 11
  };
  const monthLabels = {
    pt: ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"],
    en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    de: ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
    es: ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"],
    pl: ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"],
    sk: ["Január", "Február", "Marec", "Apríl", "Máj", "Jún", "Júl", "August", "September", "Október", "November", "December"],
    zh: ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
    hi: ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
  };
  let translating = false;
  let observer = null;
  let scheduled = false;
  const valueToKey = {};

  Object.keys(translations).forEach(function (lang) {
    Object.keys(translations[lang]).forEach(function (key) {
      const value = translations[lang][key];
      if (typeof value === "string" && value) {
        valueToKey[value.trim()] = key;
      }
    });
  });

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function getLang() {
    const saved = window.localStorage ? window.localStorage.getItem(storageKey) : null;
    return translations[saved] ? saved : "pt";
  }

  function setLang(lang) {
    if (window.localStorage && translations[lang]) {
      window.localStorage.setItem(storageKey, lang);
    }
  }

  function replaceKnownMonths(text, lang) {
    let out = text;
    Object.keys(monthForms)
      .sort(function (a, b) { return b.length - a.length; })
      .forEach(function (label) {
        const idx = monthForms[label];
        const target = (monthLabels[lang] || monthLabels.pt)[idx];
        out = out.replace(new RegExp("\\b" + escapeRegExp(label) + "\\b", "g"), target);
      });
    return out;
  }

  function translatePeriod(raw, lang) {
    const trimmed = String(raw || "").trim();
    const periodKeys = Object.keys(translations).map(function (key) {
      return translations[key].selected_period_prefix + ":";
    });
    const hasPrefix = periodKeys.some(function (prefix) { return trimmed.indexOf(prefix) === 0; });
    if (!hasPrefix) {
      return null;
    }
    let body = trimmed;
    periodKeys.forEach(function (prefix) {
      if (body.indexOf(prefix) === 0) {
        body = body.slice(prefix.length).trim();
      }
    });
    Object.keys(translations).forEach(function (key) {
      const joinWord = translations[key].selected_period_to;
      body = body.replace(new RegExp("\\s+" + escapeRegExp(joinWord) + "\\s+", "g"), " __TO__ ");
    });
    body = replaceKnownMonths(body, lang).replace(/\s+__TO__\s+/g, " " + translations[lang].selected_period_to + " ");
    return translations[lang].selected_period_prefix + ": " + body;
  }

  function formatMonthYear(value, lang) {
    const parts = String(value || "").split("-");
    if (parts.length < 2) {
      return value || "";
    }
    const year = parts[0];
    const monthIdx = Math.max(0, Math.min(11, parseInt(parts[1], 10) - 1));
    if (lang === "zh") {
      return year + "年" + String(monthIdx + 1) + "月";
    }
    return (monthLabels[lang] || monthLabels.pt)[monthIdx] + "/" + year;
  }

  function translatePeriodElements(lang) {
    document.querySelectorAll("[data-i18n-period]").forEach(function (el) {
      const start = el.getAttribute("data-period-start");
      const end = el.getAttribute("data-period-end");
      if (!start || !end) {
        return;
      }
      el.textContent = [
        translations[lang].selected_period_prefix + ":",
        formatMonthYear(start, lang),
        translations[lang].selected_period_to,
        formatMonthYear(end, lang)
      ].join(" ");
    });
  }

  function translateValue(value, lang) {
    const original = String(value || "");
    const trimmed = original.trim();
    if (!trimmed) {
      return original;
    }
    const key = valueToKey[trimmed];
    const translated = key ? (translations[lang][key] || translations.pt[key]) : translatePeriod(trimmed, lang);
    if (!translated || translated === trimmed) {
      return original;
    }
    const prefix = original.match(/^\s*/)[0];
    const suffix = original.match(/\s*$/)[0];
    return prefix + translated + suffix;
  }

  function syncLanguageMenu(activeLang) {
    const picker = document.getElementById("idioma-picker");
    const buttons = Array.from(document.querySelectorAll(".lang-flag"));
    if (!picker || !buttons.length) {
      return;
    }
    const compact = window.matchMedia("(max-width: 760px)").matches;
    const menuStep = compact ? 52 : 54;
    const menuBaseHeight = compact ? 46 : 48;
    const available = buttons.map(function (button) { return button.dataset.lang; });
    const ordered = [activeLang].concat(
      preferred.filter(function (lang) { return lang !== activeLang && available.indexOf(lang) >= 0; })
    );
    buttons.forEach(function (button) {
      const active = button.dataset.lang === activeLang;
      const slot = Math.max(0, ordered.indexOf(button.dataset.lang));
      button.style.setProperty("--menu-y", String(slot * menuStep) + "px");
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    const height = Math.max(menuBaseHeight, menuBaseHeight + (ordered.length - 1) * menuStep);
    picker.style.setProperty("--menu-height", String(height) + "px");
  }

  function closeLanguageMenu() {
    const picker = document.getElementById("idioma-picker");
    if (!picker) {
      return;
    }
    picker.classList.remove("open");
    picker.setAttribute("aria-expanded", "false");
  }

  function toggleLanguageMenu() {
    const picker = document.getElementById("idioma-picker");
    if (!picker) {
      return;
    }
    const open = !picker.classList.contains("open");
    picker.classList.toggle("open", open);
    picker.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function translateStaticElements(lang) {
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      const key = el.getAttribute("data-i18n");
      const value = translations[lang][key] || translations.pt[key];
      if (value && el.textContent !== value) {
        el.textContent = value;
      }
    });
  }

  function translateTextNodes(lang) {
    const root = document.getElementById("pagina-geral") || document.body;
    if (!root) {
      return;
    }
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          const parent = node.parentElement;
          if (!parent || parent.closest(".lang-wrap, [data-i18n-period], script, style, noscript, textarea")) {
            return NodeFilter.FILTER_REJECT;
          }
          return node.nodeValue && node.nodeValue.trim()
            ? NodeFilter.FILTER_ACCEPT
            : NodeFilter.FILTER_REJECT;
        }
      }
    );
    const nodes = [];
    let node = walker.nextNode();
    while (node) {
      nodes.push(node);
      node = walker.nextNode();
    }
    nodes.forEach(function (textNode) {
      const translated = translateValue(textNode.nodeValue, lang);
      if (translated !== textNode.nodeValue) {
        textNode.nodeValue = translated;
      }
    });
  }

  function applyLanguage(lang) {
    if (!translations[lang]) {
      lang = "pt";
    }
    translating = true;
    try {
      setLang(lang);
      document.documentElement.lang = translations[lang].html_lang || "pt-BR";
      document.title = translations[lang].title || translations.pt.title;
      syncLanguageMenu(lang);
      translateStaticElements(lang);
      translatePeriodElements(lang);
      translateTextNodes(lang);
    } finally {
      translating = false;
    }
  }

  function scheduleTranslate(delay) {
    if (scheduled) {
      return;
    }
    scheduled = true;
    window.setTimeout(function () {
      scheduled = false;
      applyLanguage(getLang());
    }, delay || 80);
  }

  function bindLanguagePicker() {
    if (window.__mvcIdiomaPickerBound) {
      return;
    }
    document.addEventListener("click", function (event) {
      const button = event.target.closest ? event.target.closest(".lang-flag") : null;
      const picker = document.getElementById("idioma-picker");
      if (button) {
        event.preventDefault();
        event.stopPropagation();
        const lang = button.dataset.lang || "pt";
        const current = getLang();
        if (lang === current && button.classList.contains("active")) {
          toggleLanguageMenu();
          return;
        }
        applyLanguage(lang);
        closeLanguageMenu();
        return;
      }
      if (picker && !picker.contains(event.target)) {
        closeLanguageMenu();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeLanguageMenu();
      }
    });
    window.addEventListener("resize", function () {
      syncLanguageMenu(getLang());
    });
    window.__mvcIdiomaPickerBound = true;
  }

  function initObserver() {
    if (observer || !window.MutationObserver) {
      return;
    }
    const root = document.getElementById("pagina-geral") || document.body;
    if (!root) {
      return;
    }
    observer = new MutationObserver(function () {
      if (!translating && getLang() !== "pt") {
        scheduleTranslate(120);
      }
    });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
  }

  function init() {
    bindLanguagePicker();
    applyLanguage(getLang());
    initObserver();
    scheduleTranslate(200);
    scheduleTranslate(700);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
"""

ESTILO_OCULTO = {"display": "none"}
ESTILO_EXIBIR = {
    "display": "block",
    "padding": "20px",
    "backgroundColor": "white",
}

ORDENACAO_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
DIAS_PORTUGUES = {
    "Monday": "Segunda",
    "Tuesday": "Terça",
    "Wednesday": "Quarta",
    "Thursday": "Quinta",
    "Friday": "Sexta",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}


def aplicar_tema_pb(fig, *, largura_borda=2, so_y_boxplot=False, grade=False, clean=False):
    """Aplica tema preto/branco aos gráficos Plotly."""
    fig.update_layout(
        template=None,
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=60, r=30, t=60, b=50),
        font=dict(family=VW_PLOTLY_FONT, color="#000000"),
        hoverlabel=dict(font=dict(family=VW_PLOTLY_FONT)),
    )

    # Garante fonte VW na legenda sem sobrescrever outras configs de legenda.
    try:
        legend_dict = fig.layout.legend.to_plotly_json() if fig.layout.legend else {}
        legend_font = (legend_dict.get("font") or {})
        legend_font["family"] = VW_PLOTLY_FONT
        legend_dict["font"] = legend_font
        fig.update_layout(legend=legend_dict)
    except Exception:
        pass

    if so_y_boxplot:
        fig.update_xaxes(
            showline=True,
            linewidth=largura_borda,
            linecolor="black",
            mirror=True,
            ticks="outside",
            tickcolor="black",
            zeroline=True,
            zerolinecolor="black",
            showgrid=False,
        )
        fig.update_yaxes(
            showline=True,
            linewidth=largura_borda,
            linecolor="black",
            mirror=True,
            ticks="outside",
            tickcolor="black",
            zeroline=True,
            zerolinecolor="black",
            gridcolor="#a7a7a7",
        )
    else:
        if grade:
            fig.update_xaxes(
                showline=True,
                linewidth=largura_borda,
                linecolor="black",
                mirror=True,
                ticks="outside",
                tickcolor="black",
                zeroline=False,
                showgrid=False,
            )
            fig.update_yaxes(
                showline=True,
                linewidth=largura_borda,
                linecolor="black",
                mirror=True,
                ticks="outside",
                tickcolor="black",
                zeroline=False,
                gridcolor="#a7a7a7",
                griddash="dot",
            )
        else:
            if clean:
                fig.update_xaxes(
                    showline=True,
                    linewidth=largura_borda,
                    linecolor="black",
                    mirror=True,
                    ticks="outside",
                    tickcolor="black",
                    zeroline=False,
                    showgrid=False,
                )
                fig.update_yaxes(
                    showline=True,
                    linewidth=largura_borda,
                    linecolor="black",
                    mirror=True,
                    ticks="outside",
                    tickcolor="black",
                    zeroline=False,
                    showgrid=False,
                )
            else:
                fig.update_xaxes(
                    showline=True,
                    linewidth=largura_borda,
                    linecolor="black",
                    mirror=True,
                    ticks="outside",
                    tickcolor="black",
                    zeroline=True,
                    zerolinecolor="black",
                    gridcolor="#a7a7a7",
                )
                fig.update_yaxes(
                    showline=True,
                    linewidth=largura_borda,
                    linecolor="black",
                    mirror=True,
                    ticks="outside",
                    tickcolor="black",
                    zeroline=True,
                    zerolinecolor="black",
                    gridcolor="#a7a7a7",
                )

    return fig
