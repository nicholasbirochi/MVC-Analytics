"""individual.py

Callbacks e geração do relatório individual (colaborador).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations
from dash import Input, Output, State, dcc, html, no_update

import base64
import io
import importlib.util
import os
import re
import textwrap
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, unquote
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import matplotlib.patheffects as patheffects
from matplotlib.backends.backend_pdf import PdfPages

from ..core.repo_global import (
    df_semana_merged,
    df_datas,
)
from ..domain.exports import (
    fig_to_bytes,
    gerar_relatorio_formatado,
    calcular_percentual_presenca,
    min_presencial_exigido,
    MIN_PRESENCIAL_APOS_MUDANCA,
)
from ..domain.pipeline import dw_fetch_diarios, dw_fetch_semana_enriquecida
from ..domain.periods import (
    LT_C1_MAX,
    LT_C1_MIN,
    LT_C2_MAX,
    LT_C2_MIN,
    periodo_limites,
)
from ..domain.tenure import obter_periodo_admissao
from ..ui.theme import (
    ESTILO_EXIBIR,
    ESTILO_OCULTO,
    ORDENACAO_DIAS,
    DIAS_PORTUGUES,
)

estilo_exibir = ESTILO_EXIBIR
estilo_oculto = ESTILO_OCULTO
ordenacao_dias = ORDENACAO_DIAS
dias_portugues = DIAS_PORTUGUES

CONSULTA_BASE_URL_DEFAULT = os.getenv(
    "CONSULTA_PESSOAL_BASE_URL",
    "https://example.invalid/consulta-pessoal/default.htm",
).strip()
CONSULTA_COR_DESTAQUE = "#123B82"
CONSULTA_COR_CAMPO = "#D4E1F2"
CONSULTA_COR_VALOR = "#F1EAD3"
_CONSULTA_RELATORIO_MODULE = None
_CONSULTA_RELATORIO_MODULE_ATTEMPTED = False


def _normalize_ascii_upper(value: object) -> str:
    txt = str(value or "").strip()
    if not txt:
        return ""
    txt = unicodedata.normalize("NFD", txt)
    txt = "".join(ch for ch in txt if unicodedata.category(ch) != "Mn")
    return txt.upper()


def _normalize_cadastro_key(value: object) -> str:
    dig = re.sub(r"\D+", "", str(value or "").strip())
    if dig.startswith("00") and (len(dig) > 2):
        dig = dig[2:]
    return dig or str(value or "").strip()


def _split_items_for_display(txt: str) -> list[str]:
    raw = str(txt or "").replace("\r", "\n")
    return [p.strip() for p in re.split(r"\s*(?:\||;|\n)\s*", raw) if p and p.strip()]


def _first_existing_path(candidates: list[str]) -> str:
    for cand in candidates:
        p = str(cand or "").strip()
        if p and Path(p).exists():
            return p
    return ""


def _image_data_uri(path_raw: str) -> str:
    path = Path(str(path_raw or "").strip())
    if (not path.exists()) or (not path.is_file()):
        return ""
    mime_by_ext = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    mime = mime_by_ext.get(path.suffix.lower(), "")
    if not mime:
        return ""
    try:
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return ""
    return f"data:{mime};base64,{payload}"


def _find_repo_root(start: Path) -> Path:
    cur = Path(start).resolve()
    for cand in [cur, *cur.parents]:
        if (cand / "requirements.txt").exists():
            return cand
    return cur


def _load_relatorio_consulta_module():
    global _CONSULTA_RELATORIO_MODULE
    global _CONSULTA_RELATORIO_MODULE_ATTEMPTED

    if _CONSULTA_RELATORIO_MODULE_ATTEMPTED:
        return _CONSULTA_RELATORIO_MODULE
    _CONSULTA_RELATORIO_MODULE_ATTEMPTED = True

    here = Path(__file__).resolve()
    repo_root = _find_repo_root(here.parent)
    candidates = [
        repo_root
        / "Códigos Extras"
        / "Documentação"
        / "Irregularidade de 999 como Trajeto"
        / "gerar_relatorios_por_pessoa.py",
        repo_root
        / "Códigos Extras"
        / "Documentação"
        / "Analisando Irregularidades dos Registros"
        / "irregularidade_999_como_trajeto"
        / "gerar_relatorios_por_pessoa.py",
    ]
    mod_path = next((p for p in candidates if p.exists()), None)
    if mod_path is None:
        return None

    try:
        spec = importlib.util.spec_from_file_location("irreg999_consulta_bridge", str(mod_path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CONSULTA_RELATORIO_MODULE = mod
        return _CONSULTA_RELATORIO_MODULE
    except Exception:
        return None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "t", "yes", "y", "on", "sim"}


def _consulta_info_por_cadastro(chapa: str, nome: str) -> tuple[dict, object | None]:
    out = {
        "cadastro": _normalize_cadastro_key(chapa),
        "ok": False,
        "mensagem": "Consulta pessoal nao executada.",
        "url_final": "",
        "linhas": [],
        "print_path": "",
        "mensagem_print": "",
        "fichas": [],
        "foto_path": "",
        "fotos_por_chapa": {},
        "nome_solicitado": str(nome or "").strip(),
    }

    mod = _load_relatorio_consulta_module()
    if mod is None:
        out["mensagem"] = "Modulo da consulta pessoal nao encontrado no repositorio."
        return out, None

    base_url = str(
        os.getenv("CONSULTA_PESSOAL_URL", os.getenv("CONSULTA_PESSOAL_EMAIL", CONSULTA_BASE_URL_DEFAULT))
    ).strip()
    user = str(os.getenv("CONSULTA_PESSOAL_USER", "")).strip()
    password = str(os.getenv("CONSULTA_PESSOAL_PASSWORD", "")).strip()
    try:
        timeout_s = int(max(0, int(str(os.getenv("CONSULTA_PESSOAL_TIMEOUT_S", "0")).strip() or "0")))
    except Exception:
        timeout_s = 0
    verify_ssl = _env_bool("CONSULTA_PESSOAL_VERIFY_SSL", default=False)
    capturar_print = _env_bool("CONSULTA_PESSOAL_CAPTURAR_PRINT", default=True)
    debug_passos = _env_bool("CONSULTA_PESSOAL_DEBUG_PASSOS", default=False)

    try:
        client = mod.ConsultaPessoalClient(
            base_url=base_url,
            user=user,
            password=password,
            timeout_s=timeout_s,
            verify_ssl=verify_ssl,
            capturar_print=capturar_print,
            debug_passos=debug_passos,
        )
    except Exception as exc:
        out["mensagem"] = f"Falha ao inicializar consulta pessoal: {exc}"
        return out, mod

    if not client.enabled:
        out["mensagem"] = (
            "Consulta pessoal desabilitada no MVC. Defina CONSULTA_PESSOAL_USER e CONSULTA_PESSOAL_PASSWORD no .env."
        )
        return out, mod

    try:
        info = client.consultar_por_cadastro(str(chapa), nome=str(nome or ""))
        if isinstance(info, dict):
            info["nome_solicitado"] = str(nome or "").strip()
            if not str(info.get("cadastro") or "").strip():
                info["cadastro"] = _normalize_cadastro_key(chapa)
            return info, mod
    except Exception as exc:
        out["mensagem"] = f"Falha ao consultar pessoal para {chapa}: {exc}"

    return out, mod


def _build_rows_for_fichas(fichas_in: list[dict], linhas_fallback: list[str]) -> list[list[str]]:
    tokens_menu = {
        "NOVA PESQUISA",
        "PESSOAIS",
        "FUNCIONAIS",
        "CONSULTA DE PESSOAL",
        "VWW",
        "RH HOME",
        "ANCHIETA",
        "TAUBATE",
        "RESENDE",
        "SAO CARLOS",
        "SERVICOS FINANCEIROS",
        "CURITIBA",
    }

    merged: dict[str, dict] = {}
    order_keys: list[str] = []

    def _is_placeholder_value(v: str) -> bool:
        vu = _normalize_ascii_upper(str(v or "")).replace(" ", "")
        if not vu:
            return True
        if re.fullmatch(r"[-|]+", vu):
            return True
        return vu in {"N/A", "NA", "SEM_DADO", "SEMINFO"}

    def _fmt_num_pessoal(chave: str, valor: str) -> str:
        ku = _normalize_ascii_upper(chave)
        vv = str(valor or "").strip()
        if ku in {"NUMERO PESSOAL", "NO PESSOAL"}:
            dig = _normalize_cadastro_key(vv)
            if dig:
                return dig
        return vv

    def _add_row(k: str, v: str) -> None:
        kk = re.sub(r"\s+", " ", str(k or "")).strip(" \t\r\n:|-")
        vv = re.sub(r"\s+", " ", str(v or "")).strip(" \t\r\n|")
        if (not kk) or (not vv):
            return
        kvu = _normalize_ascii_upper(f"{kk} {vv}")
        if any(t in kvu for t in tokens_menu):
            keep_tokens = {"NUMERO PESSOAL", "NO PESSOAL", "NOME", "UNIDADE ORGANIZACIONAL", "EMPRESA", "FUNCAO"}
            if not any(t in kvu for t in keep_tokens):
                return
        vv = _fmt_num_pessoal(kk, vv)
        ku = _normalize_ascii_upper(kk)
        if ku not in merged:
            merged[ku] = {"campo": kk, "vals": [vv]}
            order_keys.append(ku)
        else:
            vals = merged[ku]["vals"]
            novo_placeholder = _is_placeholder_value(vv)
            atuais_nao_placeholder = [x for x in vals if not _is_placeholder_value(str(x))]
            if (not novo_placeholder) and vals and (not atuais_nao_placeholder):
                merged[ku]["vals"] = [vv]
            elif vv not in vals:
                merged[ku]["vals"].append(vv)

    for ficha in fichas_in:
        for k, v in list(ficha.get("campos") or []):
            _add_row(str(k), str(v))

    if not merged:
        for ln in linhas_fallback:
            if "|" not in str(ln):
                continue
            parts = [p.strip() for p in str(ln).split("|") if str(p).strip()]
            if len(parts) >= 2:
                _add_row(parts[0], " | ".join(parts[1:]))

    return [[merged[ku]["campo"], "\n".join(merged[ku]["vals"])] for ku in order_keys]


def _profiles_from_consulta(consulta_info: dict | None) -> list[dict]:
    info = dict(consulta_info or {})
    fichas = list(info.get("fichas") or [])
    linhas = list(info.get("linhas") or [])
    cadastro_base = _normalize_cadastro_key(info.get("cadastro") or "")
    nome_base = str(info.get("nome_solicitado") or "").strip()
    print_path = str(info.get("print_path") or "").strip()
    foto_path = str(info.get("foto_path") or "").strip()

    fotos_raw = dict(info.get("fotos_por_chapa") or {})
    fotos_map: dict[str, str] = {}
    for k, v in fotos_raw.items():
        kk = _normalize_cadastro_key(k)
        vv = str(v or "").strip()
        if kk and vv:
            fotos_map[kk] = vv

    fallback_img = _first_existing_path([foto_path, *list(fotos_map.values()), print_path])

    if fichas:
        ord_f = {"FUNCIONAIS": 0, "PESSOAIS": 1, "FICHA": 2}
        fichas = sorted(
            fichas,
            key=lambda x: (
                ord_f.get(_normalize_ascii_upper(str(x.get("tipo") or "")), 9),
                str(x.get("url") or ""),
            ),
        )
        groups: dict[str, list[dict]] = {}
        order_keys: list[str] = []
        for idx, ficha in enumerate(fichas, start=1):
            campos_f = list(ficha.get("campos") or [])
            key = _normalize_cadastro_key(ficha.get("chapa") or "")
            if not key:
                for k, v in campos_f:
                    if _normalize_ascii_upper(str(k or "")) in {"NUMERO PESSOAL", "NO PESSOAL"}:
                        key = _normalize_cadastro_key(v)
                        break
            if not key:
                key = f"SEM_CHAPA_{idx}"
            if key not in groups:
                groups[key] = []
                order_keys.append(key)
            groups[key].append(ficha)

        profiles: list[dict] = []
        total = max(1, len(order_keys))
        for idx, key in enumerate(order_keys, start=1):
            rows = _build_rows_for_fichas(groups.get(key, []), [])
            if not rows:
                continue
            cad = "" if key.startswith("SEM_CHAPA_") else key
            img = _first_existing_path([fotos_map.get(key, ""), fallback_img, *list(fotos_map.values())])
            label = f"Registro {idx}/{total}"
            if cad:
                label = f"{label} - No pessoal {cad}"
            profiles.append(
                {
                    "cadastro": cad,
                    "nome": nome_base,
                    "rows": rows,
                    "img_path": img,
                    "registro_label": label,
                }
            )
        if profiles:
            return profiles

    rows_fb = _build_rows_for_fichas([], linhas)
    return [
        {
            "cadastro": cadastro_base,
            "nome": nome_base,
            "rows": rows_fb,
            "img_path": fallback_img,
            "registro_label": "Registro 1/1",
        }
    ]


def _render_consulta_pdf_page(
    pdf,
    profile: dict,
    status_ok: bool,
    status_msg: str,
    idx_page: int,
    total_pages: int,
    cadastro_base: str,
    nome_base: str,
) -> None:
    rows = list(profile.get("rows") or [])
    cadastro = str(profile.get("cadastro") or "").strip() or str(cadastro_base or "").strip()
    nome = str(profile.get("nome") or "").strip() or str(nome_base or "").strip()
    registro_label = str(profile.get("registro_label") or f"Registro {idx_page}/{total_pages}")
    img_path = str(profile.get("img_path") or "").strip()
    has_img = bool(img_path and Path(img_path).exists())

    def _wrap(txt: str, width: int) -> str:
        parts = _split_items_for_display(txt)
        if not parts:
            base = str(txt or "").strip()
            parts = [base] if base else []
        out = [textwrap.fill(p, width=max(20, int(width)), break_long_words=False, break_on_hyphens=False) for p in parts]
        return "\n".join(out) if out else ""

    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    ax.axis("off")
    fig.suptitle("Consulta Pessoal - Relatorio Individual (MVC)", fontsize=15, fontweight="bold", y=0.975)

    header_txt = f"{cadastro} - {nome}" if cadastro and nome else (nome or cadastro or "Registro sem identificacao")
    ax.text(
        0.02,
        0.93,
        header_txt,
        fontsize=12,
        fontweight="bold",
        color="white",
        ha="left",
        va="top",
        transform=ax.transAxes,
        bbox=dict(facecolor=CONSULTA_COR_DESTAQUE, edgecolor=CONSULTA_COR_DESTAQUE, boxstyle="round,pad=0.35"),
    )
    ax.text(
        0.02,
        0.875,
        f"Status: {'OK' if status_ok else 'FALHA'}",
        fontsize=10,
        fontweight="bold",
        color="white",
        ha="left",
        va="top",
        transform=ax.transAxes,
        bbox=dict(facecolor=CONSULTA_COR_DESTAQUE, edgecolor=CONSULTA_COR_DESTAQUE, boxstyle="round,pad=0.25"),
    )
    ax.text(0.02, 0.835, registro_label, fontsize=9.4, fontweight="bold", ha="left", va="top", transform=ax.transAxes)

    y_msg = 0.79
    for ln in textwrap.wrap(status_msg or "Sem mensagem.", width=130, break_long_words=False, break_on_hyphens=False)[:3]:
        ax.text(0.02, y_msg, ln, fontsize=9.0, ha="left", va="top", transform=ax.transAxes)
        y_msg -= 0.028

    if rows:
        rows_fmt: list[list[str]] = []
        row_units: list[float] = []
        for campo, valor in rows:
            c = _wrap(campo, 28)
            v = _wrap(valor, 68)
            rows_fmt.append([c, v])
            lc = max(c.count("\n") + 1, v.count("\n") + 1)
            row_units.append(float(lc) + 0.25)

        width_tbl = 0.62 if has_img else 0.95
        ax_tbl = fig.add_axes([0.02, 0.05, width_tbl, 0.70])
        ax_tbl.axis("off")
        table = ax_tbl.table(
            cellText=rows_fmt,
            colLabels=["Campo", "Valor"],
            colLoc="left",
            cellLoc="left",
            colWidths=[0.34, 0.64],
            loc="upper left",
        )
        table.auto_set_font_size(False)
        n_rows = len(rows_fmt)
        if n_rows <= 16:
            fsz = 8.8
        elif n_rows <= 28:
            fsz = 8.0
        elif n_rows <= 42:
            fsz = 7.2
        elif n_rows <= 58:
            fsz = 6.6
        else:
            fsz = 6.0
        table.set_fontsize(fsz)
        table.scale(1.0, 1.0)
        header_units = 1.35
        total_units = header_units + float(sum(row_units)) if row_units else header_units
        unit_h = 1.0 / max(total_units, 1.0)
        for (r, c), cell in table.get_celld().items():
            if r == 0:
                cell.set_facecolor(CONSULTA_COR_DESTAQUE)
                cell.set_text_props(color="white", weight="bold")
                cell.set_height(unit_h * header_units)
            elif c == 0:
                cell.set_facecolor(CONSULTA_COR_CAMPO)
            else:
                cell.set_facecolor(CONSULTA_COR_VALOR)
            if r > 0:
                idx_row = r - 1
                if 0 <= idx_row < len(row_units):
                    cell.set_height(unit_h * row_units[idx_row])
    else:
        ax.text(0.02, 0.72, "Sem dados estruturados retornados.", fontsize=9.8, ha="left", va="top", transform=ax.transAxes)

    if has_img:
        try:
            img = plt.imread(img_path)
            ax_img = fig.add_axes([0.67, 0.30, 0.30, 0.44])
            ax_img.imshow(img)
            ax_img.axis("off")
            ax_img.set_title(
                "Imagem Consulta Pessoal",
                fontsize=9.0,
                color="white",
                pad=4,
                bbox=dict(facecolor=CONSULTA_COR_DESTAQUE, edgecolor=CONSULTA_COR_DESTAQUE, boxstyle="round,pad=0.2"),
            )
        except Exception:
            pass

    ax.text(
        0.985,
        0.02,
        f"Consulta {idx_page}/{total_pages}",
        fontsize=8.8,
        ha="right",
        va="bottom",
        transform=ax.transAxes,
        color="#333333",
    )
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.03)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _build_pdf_bytes_with_consulta(fig_base, consulta_info: dict, cadastro: str, nome: str) -> bytes:
    buf = io.BytesIO()
    status_ok = bool((consulta_info or {}).get("ok"))
    status_msg = str((consulta_info or {}).get("mensagem") or "Consulta nao executada.").strip()
    profiles = _profiles_from_consulta(consulta_info)

    with PdfPages(buf) as pdf:
        pdf.savefig(fig_base, bbox_inches="tight")
        if profiles:
            total = len(profiles)
            for idx, profile in enumerate(profiles, start=1):
                _render_consulta_pdf_page(
                    pdf,
                    profile,
                    status_ok=status_ok,
                    status_msg=status_msg,
                    idx_page=idx,
                    total_pages=total,
                    cadastro_base=str(cadastro or ""),
                    nome_base=str(nome or ""),
                )
    buf.seek(0)
    return buf.read()


def register(app):
    @app.callback(
        Output('conteudo-individual', 'children'),
        Output('conteudo-individual', 'style'),
        Output('pagina-geral', 'style', allow_duplicate=True),
        Output('url', 'pathname', allow_duplicate=True),
        Input('url', 'pathname'),
        Input('botao-voltar', 'n_clicks'),
        Input('url', 'search'),
        State('periodo-indices', 'data'),
        State('cenario-toggle', 'value'),
        State('periodo-slider', 'value'),
        prevent_initial_call=True
    )
    def exibir_conteudo_individual(pathname, n_clicks, search, periodo_idx_state, cenario_state, periodo_slider_state):
        # Voltar
        if n_clicks is not None and n_clicks > 0:
            return None, estilo_oculto, estilo_exibir, "/"

        # Roteamento
        if not pathname or '/pessoa/' not in pathname:
            return None, estilo_oculto, no_update, no_update

        chapa_input = unquote(pathname.split('/pessoa/', 1)[1])
        chapa_input = chapa_input.split('?', 1)[0].split('/', 1)[0].strip()
        if chapa_input.endswith(".0") and chapa_input[:-2].isdigit():
            chapa_input = chapa_input[:-2]
        if not chapa_input:
            return None, estilo_oculto, estilo_exibir, no_update

        dt_ini = None
        dt_fim = None
        periodo_idx = None
        try:
            qs = parse_qs((search or "").lstrip("?"))
            if "p0" in qs and "p1" in qs:
                periodo_idx = [int(qs.get("p0", [0])[0]), int(qs.get("p1", [0])[0])]
            elif isinstance(periodo_slider_state, (list, tuple)) and len(periodo_slider_state) == 2:
                periodo_idx = [int(periodo_slider_state[0]), int(periodo_slider_state[1])]
            elif isinstance(periodo_idx_state, (list, tuple)) and len(periodo_idx_state) == 2:
                periodo_idx = [int(periodo_idx_state[0]), int(periodo_idx_state[1])]
        except Exception:
            periodo_idx = None

        if periodo_idx is None:
            if str(cenario_state) == "c2":
                periodo_idx = [LT_C2_MIN, LT_C2_MAX]
            else:
                periodo_idx = [LT_C1_MIN, LT_C1_MAX]

        try:
            dt_ini, dt_fim = periodo_limites(periodo_idx)
        except Exception:
            dt_ini, dt_fim = None, None

        # Filtra dados da pessoa
        df_chapa_semana = dw_fetch_semana_enriquecida(
            cadastro=str(chapa_input),
            dt_ini=dt_ini,
            dt_fim=dt_fim,
        )
        if df_chapa_semana.empty:
            return None, estilo_oculto, estilo_exibir, no_update

        nome_input = df_chapa_semana['Nome'].iloc[0].title()

        periodo_ini_calc = pd.Timestamp(dt_ini).normalize()
        periodo_fim_calc = pd.Timestamp(dt_fim).normalize()
        data_adm, data_dem = obter_periodo_admissao(chapa_input)
        adm_ts = pd.to_datetime(data_adm, errors="coerce")
        dem_ts = pd.to_datetime(data_dem, errors="coerce")
        if pd.notna(adm_ts):
            periodo_ini_calc = max(periodo_ini_calc, adm_ts.normalize())
        if pd.notna(dem_ts):
            periodo_fim_calc = min(periodo_fim_calc, dem_ts.normalize())
        if periodo_ini_calc > periodo_fim_calc:
            return None, estilo_oculto, estilo_exibir, no_update

        # Semana-Ano
        df_chapa_semana["Data"] = pd.to_datetime(df_chapa_semana["Data"], errors="coerce").dt.normalize()
        df_chapa_semana = df_chapa_semana[
            (df_chapa_semana["Data"] >= periodo_ini_calc)
            & (df_chapa_semana["Data"] <= periodo_fim_calc)
        ].copy()
        if df_chapa_semana.empty:
            return None, estilo_oculto, estilo_exibir, no_update

        df_chapa_semana['Semana_Ano'] = (
            df_chapa_semana['Ano'].astype(str) + "-" + df_chapa_semana['Semana por Ano'].astype(str).str.zfill(2)
        )

        # Datas reais da chapa em df_datas
        df_chapa_data = dw_fetch_diarios(
            [str(chapa_input)],
            dt_ini=periodo_ini_calc,
            dt_fim=periodo_fim_calc,
        )[['Data', 'Cadastro']].copy()
        df_chapa_data['Data'] = pd.to_datetime(
            df_chapa_data['Data'], errors='coerce'
        ).dt.normalize()
        df_chapa_data = df_chapa_data.dropna(subset=['Data']).drop_duplicates(['Data'])

        min_real = periodo_ini_calc
        max_real = periodo_fim_calc

        def _fmt_mes_ano(dt_ref: pd.Timestamp) -> str:
            try:
                return f"{dt_ref.month_name(locale='pt_BR').capitalize()} de {dt_ref.year}"
            except Exception:
                return dt_ref.strftime("%b de %Y").capitalize()

        m0 = _fmt_mes_ano(min_real)
        m1 = _fmt_mes_ano(max_real)

        mes_ano_inicio = m0
        mes_ano_fim    = m1

        # cria rótulos dinâmicos
        periodo_label_completo = f"{mes_ano_inicio} a {mes_ano_fim}"

        mes_ano_inicio = min_real.strftime("%b %Y").capitalize()
        mes_ano_fim    = max_real.strftime("%b %Y").capitalize()
        periodo_label_curto = f"{mes_ano_inicio} a {mes_ano_fim}"

        # Gera TODAS as datas no período [min_real .. max_real]
        todas_datas = pd.date_range(min_real.normalize(), max_real.normalize(), freq='D')

        # Monta dataframe de referência (com rótulos ISO semanais e dias em PT)
        _dias_pt = {0:'Segunda',1:'Terça',2:'Quarta',3:'Quinta',4:'Sexta',5:'Sábado',6:'Domingo'}
        inicio_sem = todas_datas - pd.to_timedelta(todas_datas.weekday, unit='D')
        fim_sem = inicio_sem + pd.to_timedelta(6, unit='D')

        df_todas_datas = pd.DataFrame({
            "Data": todas_datas,
            "Ano": todas_datas.isocalendar().year.astype(int),
            "Semana_Num": todas_datas.isocalendar().week.astype(int),
            "Início da Semana": inicio_sem,
            "Fim da Semana": fim_sem,
        })
        df_todas_datas["Semana_Label"] = (
            df_todas_datas["Ano"].astype(str) + "-" + df_todas_datas["Semana_Num"].astype(str).str.zfill(2)
            + " | " + df_todas_datas["Início da Semana"].dt.strftime('%d/%m/%Y')
            + "-" + df_todas_datas["Fim da Semana"].dt.strftime('%d/%m/%Y')
        )
        df_todas_datas["Dia da Semana"] = df_todas_datas["Data"].dt.weekday.map(_dias_pt)

        # Merge de presença (1 se existe linha para a Data daquela chapa)
        df_merged = df_todas_datas.merge(df_chapa_data[["Data", "Cadastro"]], on="Data", how="left")
        df_merged["Presente"] = df_merged["Cadastro"].notna().astype(int)

        tabela_heatmap = (
            df_merged
            .pivot_table(index="Semana_Label", columns="Dia da Semana", values="Presente", aggfunc="sum", fill_value=0)
            .reindex(columns=ordenacao_dias)
            .sort_index()
        )

        df_todas_datas["Semana_Num"] = df_todas_datas["Data"].dt.isocalendar().week
        df_todas_datas["Início da Semana"] = df_todas_datas["Data"] - pd.to_timedelta(df_todas_datas["Data"].dt.weekday, unit="d")
        df_todas_datas["Fim da Semana"] = df_todas_datas["Início da Semana"] + pd.to_timedelta(6, unit="d")
        df_todas_datas["Semana_Label"] = (
            df_todas_datas["Ano"].astype(str) + "-" + df_todas_datas["Semana_Num"].astype(str).str.zfill(2)
            + " | " + df_todas_datas["Início da Semana"].dt.strftime('%d/%m/%Y')
            + "-" + df_todas_datas["Fim da Semana"].dt.strftime('%d/%m/%Y')
        )
        df_todas_datas["Dia da Semana"] = df_todas_datas["Data"].dt.day_name().map(dias_portugues).fillna(
            df_todas_datas["Data"].dt.day_name()
        )

        df_merged = df_todas_datas.merge(df_chapa_data[["Data", "Cadastro"]], how="left", on="Data")
        tabela_heatmap = df_merged.pivot_table(
            index="Semana_Label",
            columns="Dia da Semana",
            values="Cadastro",
            aggfunc="count",
            fill_value=0
        ).reindex(columns=ordenacao_dias)

        semana_labels = tabela_heatmap.index.to_series().astype(str)
        semana_codigos = (
            semana_labels
            .str.split(" | ", regex=False)
            .str[0]
            .str.replace(" ", "-", regex=False)
        )
        dias_presenca_por_semana = tabela_heatmap.sum(axis=1).astype(float)
        dias_presenca_por_semana.index = semana_codigos
        dias_presenca_por_semana = dias_presenca_por_semana.sort_index()

        if dias_presenca_por_semana.empty:
            return None, estilo_oculto, estilo_exibir, no_update

        media_presenca_semana = round(float(dias_presenca_por_semana.mean()), 2)
        min_req_por_semana = (
            dias_presenca_por_semana.index.to_series().apply(min_presencial_exigido)
        )
        media_min_req = (
            round(float(min_req_por_semana.mean()), 2)
            if len(min_req_por_semana)
            else MIN_PRESENCIAL_APOS_MUDANCA
        )
        if pd.isna(media_min_req) or media_min_req <= 0:
            media_min_req = MIN_PRESENCIAL_APOS_MUDANCA

        percentual_da_media = round(
            ((media_presenca_semana / media_min_req) * 100) - 100,
            2,
        )
        percentuais_presenca = calcular_percentual_presenca(dias_presenca_por_semana)

        # Distribuição e tendência usam a mesma série semanal exibida no heatmap.
        distribuicao_presencas = dias_presenca_por_semana.round().astype(int).value_counts().sort_index()
        x = sorted(set(distribuicao_presencas.index))
        y_presencas = distribuicao_presencas.reindex(x, fill_value=0)

        dias_presenca_por_semana_ordenado = dias_presenca_por_semana.sort_index()
        x_semanas = list(range(1, len(dias_presenca_por_semana_ordenado) + 1))
        y_presenca_por_semana = dias_presenca_por_semana_ordenado.values

        # ======= Figura (Matplotlib) =======
        fig = plt.figure(figsize=(28, 45))
        gs = gridspec.GridSpec(3, 2, height_ratios=[0.7, 0.5, 3.0], width_ratios=[1.9, 1.9])
        gs_heatmaps = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=gs[2, 0],
                                                       height_ratios=[max(1, tabela_heatmap.shape[0]), 1], hspace=0.02)

        # Título e linha de topo
        fig.suptitle(
            f"{nome_input} — Chapa {chapa_input}",
            x=0.01, y=1.012, fontsize=30, fontweight='bold', ha='left'
        )
        fig.lines.append(
            Line2D([0.01, 0.99], [0.992, 0.992], color='gray', linestyle='dashed', linewidth=1.5,
                alpha=0.6, transform=fig.transFigure, figure=fig)
        )
        fig.text(0.5, 0.953, f"Relatório de Frequência e Regime de Trabalho no Período de {periodo_label_completo}\n\n\n",
                 fontsize=28, ha='center')

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 1 - Gauge ~~~~~~~~~~~~~~~~~~~~~
        ax_clock = fig.add_subplot(gs[0, 0], polar=True)
        ax_clock.set_theta_offset(np.pi)
        ax_clock.set_theta_direction(-1)
        current_val = float(media_presenca_semana)
        meta_gauge = max(0.0, float(media_min_req))
        colors = [
            '#ffb3b3' if (i + 1) <= meta_gauge - 1 else
            '#f4cccc' if (i + 1) <= meta_gauge else
            '#fff9a9' if i >= 5 else
            '#d9ead3' if i == int(meta_gauge) else
            '#b6e6c5'
            for i in range(7)
        ]
        bounds = [0, 1, 2, 3, 4, 5, 6, 7]
        ax_clock.set_yticklabels([]); ax_clock.set_xticklabels([]); ax_clock.set_axis_off()
        for i in range(len(colors)):
            start = np.pi * (bounds[i] / 7)
            end = np.pi * (bounds[i + 1] / 7)
            ax_clock.barh(1, end - start, left=start, height=0.4, color=colors[i], edgecolor='black')
        tick_vals = [0, 1, 2, 3, 4, 5, 6, 7]
        tick_angles = [np.pi * (val / 7) for val in tick_vals]
        for ang, label in zip(tick_angles, [f"{val:.1f}" for val in tick_vals]):
            ax_clock.text(ang, 1.3, label, ha='center', va='center', fontsize=17, color='gray')
        angle = np.pi * (min(current_val, 7) / 7)
        ax_clock.arrow(angle, 0, 0, 0.95, width=0.03, head_width=0.08, head_length=0.15, fc='black', ec='black', zorder=5)
        ax_clock.text(0, 0, f"\n\n\n{current_val:.2f} dias/semana", fontsize=20, ha='center', va='center', color='#444')
        rect = Rectangle((0.264, 0.385), 0.48, 0.07, linewidth=2, edgecolor='black', facecolor='none',
                         transform=ax_clock.transAxes, zorder=10)
        ax_clock.add_patch(rect)
        ax_clock.set_title(f"\n\nFrequência da Contagem de Presencial\npor Semana ({periodo_label_curto})\n", va='bottom', fontsize=20, pad=35)
        if current_val > media_min_req:
            ax_clock.text(0.01, 0, f"\n\n\n\n\n Acima do necessário! \n+{percentual_da_media}%",
                          ha='center', va='center', fontsize=34, color='green', fontweight='bold',
                          path_effects=[patheffects.withStroke(linewidth=3, foreground='white')])
        elif current_val < media_min_req:
            ax_clock.text(0.01, 0, f"\n\n\n\n\n Abaixo do esperado! \n{percentual_da_media}%",
                          ha='center', va='center', fontsize=34, color='red', fontweight='bold',
                          path_effects=[patheffects.withStroke(linewidth=3, foreground='white')])
        ax_clock.patch.set_facecolor('white'); ax_clock.patch.set_alpha(0)
        ax_clock.text(-0.15, -0.16,
                      'Indicador de frequência presencial semanal de "0" a "7" dias úteis por semana.\n'
                      'Esse gráfico ajuda a saber a média que o colaborador está presente na planta.',
                      ha='left', va='center', fontsize=14, wrap=True, transform=ax_clock.transAxes)

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 2 - Distribuição por contagem semanal ~~~~~~~~~~~~~~~~~~~~~
        ax_line = fig.add_axes([0.618, 0.8195, 0.35, 0.120])
        ax_line.plot(x, y_presencas, color='#3fbe81', linewidth=4, label='Presencial')
        ax_line.fill_between(x, y_presencas, color='#96ddb1', alpha=0.5)
        for xi, yi in zip(x, y_presencas):
            ax_line.text(xi, yi + 0.14, f"{yi}", ha='center', fontsize=17)
        ax_line.set_xticks(x)
        ax_line.set_xlabel('Qtd. de Presencial na Semana', fontsize=20)
        ax_line.set_ylabel('Número de Ocorrências', fontsize=20)
        ax_line.set_title(f'Distribuição da Contagem de Presencial\npor Semana ({periodo_label_curto})', fontsize=20, pad=25)
        ax_line.grid(True, linestyle='--')
        ax_line.tick_params(axis='x', labelsize=17)
        ax_line.tick_params(axis='y', labelsize=17)
        ax_line.text(0, -0.28,
                     "Quantidade de semanas para uma certa quantidade de presença.\n"
                     "Esse gráfico ajuda a visualizar picos de frequência, transições de regime.",
                     ha='left', va='center', fontsize=14, wrap=True, transform=ax_line.transAxes)

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 3 - Série temporal + tendência ~~~~~~~~~~~~~~~~~~~~~
        x_np = np.array(sorted(x_semanas))
        y_np = np.array([y for _, y in sorted(zip(x_semanas, y_presenca_por_semana))])
        ax_line2 = fig.add_axes([0.204, 0.626, 0.680, 0.119])
        ax_line2.plot(x_np, y_np, color='#3fbe81', linewidth=4, label='Presencial')
        if len(x_np) >= 2:
            deg = 1 if len(x_np) == 2 else 2
            coef_poly = np.polyfit(x_np, y_np, deg=deg)
            poly_fn = np.poly1d(coef_poly)
            x_pred = np.linspace(x_np[0], x_np[-1], 500)
            fim = poly_fn(x_pred[-1])
            cor_tendencia = 'red' if fim < media_min_req else '#256b2b'
            ax_line2.plot(x_pred, poly_fn(x_pred), color=cor_tendencia, linestyle='--', linewidth=2, label='Tendência')
        ax_line2.set_xlim(x_np[0], x_np[-1] if len(x_np) else 1)
        anos = [label.split("-")[0] for label in dias_presenca_por_semana_ordenado.index]
        semanas = [int(label.split("-")[1]) for label in dias_presenca_por_semana_ordenado.index]
        ax_line2.set_xticks(x_semanas)
        ax_line2.set_xticklabels(semanas, fontsize=16)
        semanas_por_ano = defaultdict(list)
        for xv, ano in zip(x_semanas, anos):
            semanas_por_ano[ano].append(xv)
        for ano, semanas_ano in semanas_por_ano.items():
            centro = np.mean(semanas_ano)
            ax_line2.text(
                centro,
                -0.24,
                ano,
                transform=ax_line2.get_xaxis_transform(),
                ha='center',
                va='center',
                fontsize=18,
                color='gray'
            )
        for i in range(1, len(anos)):
            if anos[i] != anos[i - 1]:
                x_val = x_semanas[i] - 0.5
                x_fig, _ = ax_line2.transData.transform((x_val, 0))
                x_fig_norm = fig.transFigure.inverted().transform((x_fig, 0))[0]
                bbox = ax_line2.get_position()
                y_fig = bbox.y0 - 0.015
                fig.lines.append(Line2D([x_fig_norm, x_fig_norm], [y_fig, y_fig + 0.015],
                                        transform=fig.transFigure, linestyle='--', color='gray', linewidth=2, alpha=0.7))
        ax_line2.set_xlabel('', fontsize=20)
        ax_line2.set_ylabel('Quantidade de Presença', fontsize=20)
        ax_line2.set_title(f'Distribuição da Contagem de Presencial em cada Semana ({periodo_label_curto})', fontsize=20, pad=25)
        ax_line2.grid(True, linestyle='--')
        ax_line2.legend(fontsize=16, loc='upper right')
        ax_line2.tick_params(axis='x', labelsize=17)
        ax_line2.tick_params(axis='y', labelsize=17)
        ax_line2.text(0, -0.31,
                      "Número de presença em cada semana de todo esse período, esse gráfico ajuda a visualizar picos de frequência, "
                      "transições de regime e a tendência do colaborador.\n\n\n\n\n\n",
                      ha='left', va='center', fontsize=14, wrap=True, transform=ax_line2.transAxes)

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 4 - Heatmap (semanas x dias) ~~~~~~~~~~~~~~~~~~~~~
        ax_heatmap = fig.add_subplot(gs_heatmaps[0])
        if tabela_heatmap.empty:
            ax_heatmap.axis('off')
        else:
            sns.heatmap(
                tabela_heatmap,
                cmap=ListedColormap(['#d9ead3']),
                linewidths=1, linecolor='gray',
                annot=True, annot_kws={"size": 17},
                cbar=False, ax=ax_heatmap
            )

        # Coloração por presença baixa
        for y_idx, semana_label in enumerate(tabela_heatmap.index):
            semana_codigo = semana_label.split(" |")[0].replace(" ", "-")
            if semana_codigo in dias_presenca_por_semana.index:
                qtd_presenca = dias_presenca_por_semana.loc[semana_codigo]
                qtd_float = 0.0 if pd.isna(qtd_presenca) else float(qtd_presenca)
                meta_semana = float(min_presencial_exigido(semana_codigo))
                cor_destaque = (
                    "#d9ead3" if qtd_float >= meta_semana else
                    "#ffb3b3" if qtd_float <= max(0.0, meta_semana - 2.0) else
                    "#f4cccc"
                )
                for col_idx in range(tabela_heatmap.shape[1]):
                    ax_heatmap.add_patch(
                        plt.Rectangle((col_idx, y_idx), 1, 1, facecolor=cor_destaque,
                                      edgecolor='gray', linewidth=2, zorder=1)
                    )
        ax_heatmap.set_title(f'\n\n\n\n\n\n\nDistribuição da Contagem de Presencial por\nAno e Semana para cada Dia da Semana ({periodo_label_curto})\n',
                             fontsize=20, pad=40)
        ax_heatmap.xaxis.set_label_position('top')
        ax_heatmap.xaxis.tick_top()
        ax_heatmap.tick_params(axis='x', bottom=False, labelbottom=False)
        ax_heatmap.set_ylabel(''); ax_heatmap.set_xlabel('')
        ax_heatmap.set_xticklabels(ax_heatmap.get_xticklabels(), fontsize=20)
        ax_heatmap.set_yticklabels(ax_heatmap.get_yticklabels(), fontsize=20)

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 5 - Texto + mini heatmap de semanas baixas ~~~~~~~~~~~~~~~~~~~~~
        ax_report = fig.add_subplot(gs[2, 1])
        relatorio_formatado = gerar_relatorio_formatado(nome_input, chapa_input, media_presenca_semana, percentuais_presenca, periodo_label_completo)
        ax_report.text(0, 1.058, relatorio_formatado, fontsize=20, ha='left', va='top', wrap=True, usetex=False)
        ax_report.axis('off')

        semanas_baixa = [
            sem
            for sem, qtd in dias_presenca_por_semana.items()
            if (0.0 if pd.isna(qtd) else float(qtd)) < float(min_presencial_exigido(sem))
        ]
        tabela_heatmap_baixa = tabela_heatmap[
            tabela_heatmap.index.str.split(r" \|").str[0].isin(semanas_baixa)
        ]

        if not tabela_heatmap_baixa.empty:
            left = 0.69; width = 0.30
            num_linhas = tabela_heatmap_baixa.shape[0]
            altura_base = 0.30; linhas_base = 34
            height = (num_linhas / linhas_base) * altura_base
            top = 0.410; bottom = top - height
            ax_heatmap3 = fig.add_axes([left, bottom, width, height])
            sns.heatmap(tabela_heatmap_baixa, cmap=ListedColormap(['#ffb3b3', '#f4cccc']),
                        linewidths=1, linecolor='gray', annot=True, annot_kws={'size': 13},
                        cbar=False, ax=ax_heatmap3)
            for y_idx, semana_label in enumerate(tabela_heatmap_baixa.index):
                semana_codigo = semana_label.split(" |")[0].replace(" ", "-")
                if semana_codigo in dias_presenca_por_semana.index:
                    qtd_presenca = dias_presenca_por_semana.loc[semana_codigo]
                    qtd_float = 0.0 if pd.isna(qtd_presenca) else float(qtd_presenca)
                    meta_semana = float(min_presencial_exigido(semana_codigo))
                    cor_destaque = (
                        "#ffb3b3" if qtd_float <= max(0.0, meta_semana - 2.0) else
                        "#f4cccc"
                    )
                    for col_idx in range(tabela_heatmap_baixa.shape[1]):
                        ax_heatmap3.add_patch(
                            plt.Rectangle((col_idx, y_idx), 1, 1, facecolor=cor_destaque,
                                          edgecolor='gray', linewidth=2, zorder=1)
                        )
            ax_heatmap3.set_ylabel(''); ax_heatmap3.set_xlabel('')
            ax_heatmap3.set_xticklabels(ax_heatmap3.get_xticklabels(), fontsize=14)
            ax_heatmap3.set_yticklabels(ax_heatmap3.get_yticklabels(), fontsize=14, rotation=0)
        else:
            pass

        # ~~~~~~~~~~~~~~~~~~~~~ Subplot 6 - Heatmap TOTAL do colaborador (dias) ~~~~~~~~~~~~~~~~~~~~~
        ax_heatmap2 = fig.add_subplot(gs_heatmaps[1])

        # Fonte diária de presença
        df_chapa_data = dw_fetch_diarios(
            [str(chapa_input)],
            dt_ini=periodo_ini_calc,
            dt_fim=periodo_fim_calc,
        )[['Data']].copy()
        df_chapa_data['Data'] = pd.to_datetime(
            df_chapa_data['Data'], errors='coerce'
        ).dt.normalize()
        df_chapa_data = df_chapa_data.dropna(subset=['Data']).drop_duplicates(['Data'])

        if df_chapa_data.empty:
            ax_heatmap2.axis('off')
        else:
            # Dia da semana em PT (mantém PT se já estiver)
            _dias_pt = {
                'Monday':'Segunda','Tuesday':'Terça','Wednesday':'Quarta',
                'Thursday':'Quinta','Friday':'Sexta','Saturday':'Sábado','Sunday':'Domingo'
            }
            nomes_en = df_chapa_data['Data'].dt.day_name()
            df_chapa_data['Dia Semana'] = nomes_en.map(_dias_pt).fillna(nomes_en)

            # Contagem por dia da semana, na ordem desejada
            counts = (df_chapa_data['Dia Semana']
                    .value_counts()
                    .reindex(ordenacao_dias, fill_value=0)
                    .astype(int))

            # 1 linha (Total) x 7 colunas (dias)
            heatmap_data = pd.DataFrame(
                [counts.values.tolist()],
                columns=ordenacao_dias,
                index=['Total']
            )

            cmap_personalizado = ListedColormap(["#ffb3b3", "#f4cccc", "#e3dacd", "#dae5d1", "#d9ead3"])
            sns.heatmap(
                heatmap_data,
                annot=True, fmt='g',
                cmap=cmap_personalizado,
                linewidths=1, linecolor='gray',
                annot_kws={'color': 'black', 'size': 17},
                cbar=False, ax=ax_heatmap2
            )

            # Ticks centralizados nas células
            ax_heatmap2.set_xticks(np.arange(heatmap_data.shape[1]) + 0.5)
            ax_heatmap2.set_xticklabels(list(heatmap_data.columns), fontsize=20, rotation=0)

            ax_heatmap2.set_yticks(np.arange(heatmap_data.shape[0]) + 0.5)
            ax_heatmap2.set_yticklabels(list(heatmap_data.index), fontsize=20, rotation=0)

            ax_heatmap2.set_xlabel('')
            ax_heatmap2.set_ylabel('')
            ax_heatmap2.tick_params(axis='y', left=True)

        # Layout final
        plt.subplots_adjust(wspace=1.4)
        fig.tight_layout()
        consulta_info, consulta_mod = _consulta_info_por_cadastro(str(chapa_input), str(nome_input))

        # Gera binários
        png_bytes = fig_to_bytes(fig, fmt="png")
        pdf_bytes = _build_pdf_bytes_with_consulta(
            fig,
            consulta_info=consulta_info,
            cadastro=str(chapa_input),
            nome=str(nome_input),
        )
        if not pdf_bytes:
            pdf_bytes = fig_to_bytes(fig, fmt="pdf")
        plt.close(fig)

        consulta_preview_src = _image_data_uri(
            _first_existing_path(
                [
                    str((consulta_info or {}).get("print_path") or ""),
                    str((consulta_info or {}).get("foto_path") or ""),
                    *[
                        str(v or "")
                        for v in dict((consulta_info or {}).get("fotos_por_chapa") or {}).values()
                    ],
                ]
            )
        )

        cleanup_fn = getattr(consulta_mod, "cleanup_consulta_pessoal_imagens_temporarias", None)
        if callable(cleanup_fn):
            try:
                cleanup_fn(consulta_info)
            except Exception:
                pass

        # Converte em strings base64 (Dash)
        images_base64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        png_b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        pdf_b64 = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode()

        conteudo = html.Div([
            html.Button("Voltar", id='botao-voltar', n_clicks=0, style={
                'color': 'Black', 'fontFamily': 'VW Text', 'fontWeight': 'bold', 'marginTop': '20px',
                'display': 'block', 'marginTop': '10px', 'marginLeft': '10px', 'marginRight': 'auto',
                'padding': '10px 20px', 'fontSize': '14px', 'backgroundColor': '#e0e0e0', 'border': 'none',
                'borderRadius': '5px', 'cursor': 'pointer', 'boxShadow': '0px 2px 6px rgba(0, 0, 0, 0.25)'}),

            html.Div([
                html.A("Baixar PNG", href=png_b64, download=f"relatorio_{chapa_input}.png",
                    style={"fontSize": "16px", "marginRight": "20px",
                            "padding": "8px 14px", "backgroundColor": "#e0e0e0",
                            "color": "Black", "fontFamily": "VW Text", "borderRadius": "6px",
                            "textDecoration": "none",}),
                html.A("Baixar PDF", href=pdf_b64, download=f"relatorio_{chapa_input}.pdf",
                    style={"fontSize": "16px", "padding": "8px 14px",
                            "backgroundColor": "#ff0000", "color": "white",
                            "fontFamily": "VW Text", "borderRadius": "6px",
                            "textDecoration": "none",}),
            ], style={"textAlign": "center", "marginTop": "10px"}),

            html.Img(
                src=consulta_preview_src,
                style={
                    'width': '100%', 'maxWidth': '1100px', 'marginTop': '20px', 'marginBottom': '24px',
                    'background': 'white', 'display': 'block', 'marginLeft': 'auto', 'marginRight': 'auto'
                }
            ) if consulta_preview_src else None,

            html.Img(src=images_base64, style={
                'width': '100%', 'maxWidth': '1400px', 'marginTop': '20px', 'background': 'white',
                'display': 'block', 'marginLeft': 'auto', 'marginRight': 'auto'
            }),
        ])

        # >>> devolvemos o conteúdo individual e escondemos a página geral
        return conteudo, {'display': 'block'}, {'display': 'none'}, no_update
