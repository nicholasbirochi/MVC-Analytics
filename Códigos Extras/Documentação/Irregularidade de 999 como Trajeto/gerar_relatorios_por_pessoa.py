from __future__ import annotations

import argparse
import tempfile
import os
import re
import time
import textwrap
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Evita backend Tk (TclError) no Python embutido.
os.environ["MPLBACKEND"] = "Agg"
import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
plt.switch_backend("Agg")
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from matplotlib.backends.backend_pdf import PdfPages

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None

CORTE_DIA_RASTREIO = pd.Timedelta(hours=5, minutes=30)
COR_DESTAQUE_NUMEROS = "#0A2E6E"
SCRIPT_DIR = Path(__file__).resolve().parent


def log_info(msg: str) -> None:
    print(msg, flush=True)


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _load_dotenv_simple(path: Path) -> None:
    if not path.exists():
        return
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    for line in raw.splitlines():
        ln = line.strip()
        if (not ln) or ln.startswith("#") or ("=" not in ln):
            continue
        key, val = ln.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and (key not in os.environ):
            os.environ[key] = val


_load_dotenv_simple(SCRIPT_DIR / ".env")
if Path.cwd() != SCRIPT_DIR:
    _load_dotenv_simple(Path.cwd() / ".env")

# Mantem fallback para CONSULTA_PESSOAL_EMAIL por compatibilidade com setups antigos.
DEFAULT_CONSULTA_PESSOAL_URL = "https://example.invalid/consulta-pessoal/default.htm"
CONSULTA_PESSOAL_URL = (
    str(os.getenv("CONSULTA_PESSOAL_URL", "")).strip()
    or str(os.getenv("CONSULTA_PESSOAL_EMAIL", "")).strip()
    or DEFAULT_CONSULTA_PESSOAL_URL
)
_parsed_consulta_url = urlparse(CONSULTA_PESSOAL_URL)
CONSULTA_PESSOAL_ORIGIN = (
    str(os.getenv("CONSULTA_PESSOAL_ORIGIN", "")).strip()
    or f"{_parsed_consulta_url.scheme}://{_parsed_consulta_url.netloc}"
    or "https://example.invalid"
)
CONSULTA_PESSOAL_USER = os.getenv("CONSULTA_PESSOAL_USER", "")
CONSULTA_PESSOAL_PASSWORD = os.getenv("CONSULTA_PESSOAL_PASSWORD", "")
CONSULTA_PESSOAL_TIMEOUT_S = max(_env_int("CONSULTA_PESSOAL_TIMEOUT_S", 0), 0)
CONSULTA_PESSOAL_CAPTURAR_PRINT = False
CONSULTA_PESSOAL_DEBUG_PASSOS = False


def parse_args() -> argparse.Namespace:
    base_default = SCRIPT_DIR

    parser = argparse.ArgumentParser(
        description="Gera CSV + PDF por pessoa para o Top 5 de 999 como trajeto."
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=base_default,
        help=(
            "Diretorio base com df_ronda.parquet e outputs_irregularidades/dfs/"
            "irregularidade_999_como_trajeto.parquet. "
            "Se nao existir, tenta detectar automaticamente."
        ),
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Quantidade de pessoas no top (default: 5).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250_000,
        help="Batch de leitura do df_ronda.parquet (default: 250000).",
    )
    parser.add_argument(
        "--janela-999-horas",
        type=float,
        default=6.0,
        help="Janela maxima para associar 999 ao ciclo de portaria (default: 6h).",
    )
    parser.add_argument(
        "--max-horas-fabrica-dia",
        type=float,
        default=1.0,
        help="Tempo maximo de permanencia em fabrica por ciclo E->S (default: 1h).",
    )
    parser.add_argument(
        "--nao-exigir-ponto-no-ciclo",
        action="store_true",
        help=(
            "Se informado, permite considerar 999 em eventos de portaria. "
            "Sem a flag, exige 999 em evento de ponto."
        ),
    )
    parser.add_argument(
        "--validar-logica",
        action="store_true",
        help="Roda cenarios sinteticos para validar a logica de 999 como trajeto.",
    )
    return parser.parse_args()


def resolve_base_dir(base_dir_arg: Path) -> Path:
    """
    Resolve automaticamente o base_dir quando o argumento informado nao contem as bases esperadas.
    """
    req_irreg = Path("outputs_irregularidades") / "dfs" / "irregularidade_999_como_trajeto.parquet"
    req_ronda = Path("df_ronda.parquet")

    candidatos = [
        Path(base_dir_arg).resolve(),
        SCRIPT_DIR.resolve(),
        (SCRIPT_DIR.parent / "Analisando Irregularidades dos Registros").resolve(),
        SCRIPT_DIR.parent.resolve(),
    ]
    vistos: set[str] = set()
    for cand in candidatos:
        key = str(cand)
        if key in vistos:
            continue
        vistos.add(key)
        if (cand / req_irreg).exists() and (cand / req_ronda).exists():
            return cand
    return Path(base_dir_arg).resolve()


def validar_args(args: argparse.Namespace) -> None:
    erros: list[str] = []
    if int(args.top_n) <= 0:
        erros.append("--top-n deve ser > 0.")
    if int(args.batch_size) <= 0:
        erros.append("--batch-size deve ser > 0.")
    if float(args.janela_999_horas) < 0:
        erros.append("--janela-999-horas deve ser >= 0.")
    if float(args.max_horas_fabrica_dia) <= 0:
        erros.append("--max-horas-fabrica-dia deve ser > 0.")
    if erros:
        raise ValueError("Parametros invalidos:\n- " + "\n- ".join(erros))


def pick_col(cands: list[str], cols: list[str]) -> str | None:
    cols_set = set(cols)
    for c in cands:
        if c in cols_set:
            return c
    return None


def slugify(text: str) -> str:
    norm = unicodedata.normalize("NFKD", str(text))
    ascii_txt = norm.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^A-Za-z0-9]+", "_", ascii_txt).strip("_")
    return clean or "SEM_NOME"


def safe_str_series(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip()


def normalize_ascii_upper(value: object) -> str:
    if pd.isna(value):
        return ""
    txt = unicodedata.normalize("NFKD", str(value))
    txt = txt.encode("ascii", "ignore").decode("ascii")
    return txt.strip().upper()


def normalizar_cpf_value(value: object) -> str:
    dig = re.sub(r"\D+", "", str(value or "").strip())
    return dig if len(dig) == 11 else ""


def valor_cpf_vazio_ou_zero(value: object) -> bool:
    txt = str(value or "").strip()
    dig = re.sub(r"\D+", "", txt)
    if not txt:
        return True
    if dig and set(dig) <= {"0"}:
        return True
    txt_u = normalize_ascii_upper(txt).replace(" ", "")
    return txt_u in {"*", "**", "***", "NA", "N/A", "SEMINFO", "SEMDADO"}


def garantir_cpf_rows(rows: list[list[str]], cpf: str) -> list[list[str]]:
    cpf_norm = normalizar_cpf_value(cpf)
    if not cpf_norm:
        return rows

    out: list[list[str]] = []
    found = False
    for row in list(rows or []):
        if not row:
            continue
        campo = str(row[0] if len(row) > 0 else "")
        valor = str(row[1] if len(row) > 1 else "")
        campo_u = normalize_ascii_upper(campo)
        if campo_u in {"CNPF", "CPF"}:
            found = True
            campo = "CNPF"
            if valor_cpf_vazio_ou_zero(valor):
                valor = cpf_norm
        out.append([campo, valor])

    if not found:
        out.append(["CNPF", cpf_norm])
    return out


def normalize_dir_value(value: object) -> str:
    txt = normalize_ascii_upper(value)
    if txt.startswith("E"):
        return "E"
    if txt.startswith("S"):
        return "S"
    if txt in {"ENTRADA", "IN"}:
        return "E"
    if txt in {"SAIDA", "OUT"}:
        return "S"
    return ""


def calcular_dia_rastreio(dt_series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(dt_series, errors="coerce")
    return (dt - CORTE_DIA_RASTREIO).dt.normalize()


def formatar_horas_amigavel(horas: float) -> str:
    h = max(float(horas), 0.0)
    total_min = int(round(h * 60))
    hh, mm = divmod(total_min, 60)
    if hh > 0 and mm > 0:
        return f"{hh}h {mm:02d}min"
    if hh > 0:
        return f"{hh}h"
    return f"{mm}min"


def extrair_ocorrencias_trajeto(df: pd.DataFrame) -> pd.DataFrame:
    cols_occ = ["_trajeto_occ_id", "trajeto_999_situacao", "trajeto_999_h_total"]
    if df.empty or (not all(c in df.columns for c in cols_occ)):
        return pd.DataFrame(columns=cols_occ)

    occ = df[cols_occ].copy()
    occ = occ.loc[occ["_trajeto_occ_id"].notna()].drop_duplicates(subset=["_trajeto_occ_id"], keep="last")
    if occ.empty:
        return occ

    occ["trajeto_999_situacao"] = safe_str_series(occ["trajeto_999_situacao"])
    occ["trajeto_999_h_total"] = pd.to_numeric(occ["trajeto_999_h_total"], errors="coerce").fillna(0.0)
    return occ


class ConsultaPessoalClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        timeout_s: int = CONSULTA_PESSOAL_TIMEOUT_S,
        verify_ssl: bool = False,
        capturar_print: bool = CONSULTA_PESSOAL_CAPTURAR_PRINT,
        debug_passos: bool = CONSULTA_PESSOAL_DEBUG_PASSOS,
    ) -> None:
        self.base_url = base_url
        self.user = str(user or "").strip()
        self.password = str(password or "").strip()
        self.timeout_s = int(max(timeout_s, 0))
        self.verify_ssl = bool(verify_ssl)
        self.session = requests.Session() if requests is not None else None
        self.enabled = bool(self.user and self.password)
        self.capturar_print = bool(capturar_print)
        self.debug_passos = bool(debug_passos)
        self._playwright_bloqueado = False
        self._playwright_bloqueio_msg = ""
        self._ultimas_variantes_busca: list[str] = []
        self._debug_form_info = ""

        if self.session is not None:
            self.session.verify = self.verify_ssl
            if not self.verify_ssl:
                try:
                    requests.packages.urllib3.disable_warnings()  # pragma: no cover
                except Exception:
                    pass

    def _timeout_value(self) -> int | None:
        return None if int(self.timeout_s) <= 0 else int(self.timeout_s)

    def consultar_por_cadastro(self, cadastro: str, nome: str = "") -> dict:
        cad = self._normalizar_numero_pessoal(cadastro)
        nome_hint = str(nome or "").strip()
        out = {
            "cadastro": cad,
            "ok": False,
            "mensagem": "",
            "url_final": "",
            "linhas": [],
            "print_path": "",
            "mensagem_print": "",
            "fichas": [],
            "foto_path": "",
            "fotos_por_chapa": {},
        }

        if not cad:
            out["mensagem"] = "Cadastro vazio."
            return out

        if not self.user or not self.password:
            out["mensagem"] = (
                "Credenciais vazias. Preencha CONSULTA_PESSOAL_USER/CONSULTA_PESSOAL_PASSWORD para habilitar."
            )
            return out

        req_out: dict | None = None
        if (self.session is not None) and (BeautifulSoup is not None):
            req_out = self._consultar_via_requests(cad, nome_hint=nome_hint)

        if not self.capturar_print:
            if req_out is not None:
                return req_out
            out["mensagem"] = "Consulta textual indisponivel (requests/bs4 nao disponiveis)."
            return out

        auto_out = self._consultar_via_playwright(cad)

        if bool(auto_out.get("ok")):
            if req_out is not None and bool(req_out.get("ok")) and (not auto_out.get("linhas")):
                auto_out["linhas"] = list(req_out.get("linhas") or [])
                if not str(auto_out.get("url_final") or "").strip():
                    auto_out["url_final"] = str(req_out.get("url_final") or "")
            if req_out is not None and bool(req_out.get("ok")):
                if not list(auto_out.get("fichas") or []):
                    auto_out["fichas"] = list(req_out.get("fichas") or [])
                if not str(auto_out.get("foto_path") or "").strip():
                    auto_out["foto_path"] = str(req_out.get("foto_path") or "")
                if not dict(auto_out.get("fotos_por_chapa") or {}):
                    auto_out["fotos_por_chapa"] = dict(req_out.get("fotos_por_chapa") or {})
            if req_out is not None and bool(req_out.get("ok")):
                auto_out["mensagem"] = "Consulta pessoal carregada com sucesso (texto + print)."
            else:
                auto_out["mensagem"] = "Consulta pessoal carregada com sucesso (via automacao)."
            return auto_out

        if req_out is not None and bool(req_out.get("ok")):
            req_out["mensagem_print"] = str(auto_out.get("mensagem") or "")
            req_out["print_path"] = str(auto_out.get("print_path") or "")
            if not req_out["print_path"]:
                req_out["print_path"] = self._gerar_print_fallback(
                    cad,
                    linhas=list(req_out.get("linhas") or []),
                    titulo="Consulta Pessoal - sem print automatizada",
                    detalhe=str(req_out.get("mensagem_print") or ""),
                )
            return req_out

        msgs = []
        if req_out is not None and str(req_out.get("mensagem") or "").strip():
            msgs.append(f"requests: {req_out['mensagem']}")
        if str(auto_out.get("mensagem") or "").strip():
            msgs.append(f"playwright: {auto_out['mensagem']}")
        out["mensagem"] = "Falha ao consultar cadastro {}: {}".format(
            cad,
            " | ".join(msgs) if msgs else "sem detalhes.",
        )
        out["print_path"] = str(auto_out.get("print_path") or "")
        out["mensagem_print"] = str(auto_out.get("mensagem") or "")
        if not out["print_path"]:
            out["print_path"] = self._gerar_print_fallback(
                cad,
                linhas=[],
                titulo="Consulta Pessoal - falha de automacao",
                detalhe=out["mensagem_print"] or out["mensagem"],
            )
        return out

    def consultar_por_nome(self, nome: str) -> dict:
        nome_hint = str(nome or "").strip()
        out = {
            "cadastro": "",
            "ok": False,
            "mensagem": "",
            "url_final": "",
            "linhas": [],
            "print_path": "",
            "mensagem_print": "",
            "fichas": [],
            "foto_path": "",
            "fotos_por_chapa": {},
        }

        if not nome_hint:
            out["mensagem"] = "Nome vazio."
            return out

        if not self.user or not self.password:
            out["mensagem"] = (
                "Credenciais vazias. Preencha CONSULTA_PESSOAL_USER/CONSULTA_PESSOAL_PASSWORD para habilitar."
            )
            return out

        req_out: dict | None = None
        if (self.session is not None) and (BeautifulSoup is not None):
            req_out = self._consultar_via_requests("", nome_hint=nome_hint, modo_busca="NOME", termo_busca=nome_hint)

        if req_out is None:
            out["mensagem"] = "Consulta textual indisponivel (requests/bs4 nao disponiveis)."
            return out

        if not self.capturar_print:
            return req_out

        # Consulta por nome prioriza retorno textual para evitar dependência de automação de navegador.
        if bool(req_out.get("ok")):
            req_out["mensagem_print"] = "Captura de print nao aplicada para consulta por nome."
        return req_out

    def consultar_por_cpf(self, cpf: str) -> dict:
        cpf_hint = re.sub(r"\D+", "", str(cpf or "").strip())
        out = {
            "cadastro": cpf_hint,
            "ok": False,
            "mensagem": "",
            "url_final": "",
            "linhas": [],
            "print_path": "",
            "mensagem_print": "",
            "fichas": [],
            "foto_path": "",
            "fotos_por_chapa": {},
        }

        if not cpf_hint:
            out["mensagem"] = "CPF vazio."
            return out

        if not self.user or not self.password:
            out["mensagem"] = (
                "Credenciais vazias. Preencha CONSULTA_PESSOAL_USER/CONSULTA_PESSOAL_PASSWORD para habilitar."
            )
            return out

        req_out: dict | None = None
        if (self.session is not None) and (BeautifulSoup is not None):
            req_out = self._consultar_via_requests(
                "",
                nome_hint="",
                modo_busca="CPF",
                termo_busca=cpf_hint,
            )

        if req_out is None:
            out["mensagem"] = "Consulta textual indisponivel (requests/bs4 nao disponiveis)."
            return out

        req_out["cpf_consultado"] = normalizar_cpf_value(cpf_hint)
        if not self.capturar_print:
            return req_out

        if bool(req_out.get("ok")):
            req_out["mensagem_print"] = "Captura de print nao aplicada para consulta por CPF."
        return req_out

    def validar_login(self) -> dict:
        out = {"ok": False, "mensagem": "", "url_final": ""}
        if requests is None:
            out["mensagem"] = "Biblioteca requests indisponivel no ambiente."
            return out
        if BeautifulSoup is None:
            out["mensagem"] = "Biblioteca bs4 indisponivel no ambiente."
            return out
        if self.session is None:
            out["mensagem"] = "Sessao requests indisponivel."
            return out
        if not self.user or not self.password:
            out["mensagem"] = "Credenciais vazias."
            return out

        try:
            resp_login = self.session.get(self.base_url, timeout=self._timeout_value())
            resp_login.raise_for_status()
            if self._response_indica_erro(resp_login):
                resp_login = self._follow_endereco_incorreto(resp_login)
            resp_pos_login = self._submit_login_requests(resp_login)
            if self._response_indica_erro(resp_pos_login):
                resp_pos_login = self._follow_endereco_incorreto(resp_pos_login)
            resp_pos_login = self._submit_prosseguir(resp_pos_login)
            form_search, _, _ = self._buscar_form_pesquisa(resp_pos_login)
            if form_search is None:
                out["mensagem"] = "Login nao validado: formulario de pesquisa nao encontrado apos autenticar."
                out["url_final"] = str(resp_pos_login.url or "")
                return out
            out["ok"] = True
            out["mensagem"] = "Login validado com sucesso no site da Consulta Pessoal."
            out["url_final"] = str(resp_pos_login.url or "")
            return out
        except Exception as exc:
            out["mensagem"] = f"Falha ao validar login no site: {self._clean_exc(exc)}"
            return out

    def _clean_exc(self, exc: Exception | str) -> str:
        txt = str(exc or "").replace("\r", "\n")
        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        if not lines:
            return "erro sem detalhes."
        first = lines[0]
        first = re.sub(r"\s+", " ", first).strip()
        return first[:320]

    def _normalizar_numero_pessoal(self, cadastro: str) -> str:
        txt = str(cadastro or "").strip()
        if not txt:
            return ""
        dig = re.sub(r"\D+", "", txt)
        return dig if dig else txt

    def _variantes_chapa(self, cadastro: str) -> list[str]:
        raw = str(cadastro or "").strip()
        norm = self._normalizar_numero_pessoal(raw)
        vals: list[str] = []
        for v in [raw, norm]:
            v2 = str(v or "").strip()
            if v2 and v2 not in vals:
                vals.append(v2)
        return vals

    def _extrair_chapa_de_url(self, url_text: str) -> str:
        m = re.search(r"[?&]chapa=([0-9]+)", str(url_text or ""), flags=re.I)
        return str(m.group(1)) if m else ""

    def _normalizar_chapa_key(self, chapa: str) -> str:
        dig = re.sub(r"\D+", "", str(chapa or "").strip())
        if dig.startswith("00") and (len(dig) > 2):
            dig = dig[2:]
        return dig or str(chapa or "").strip()

    def _temp_image_path(self, cadastro: str, kind: str, suffix: str) -> Path:
        cad = self._normalizar_chapa_key(str(cadastro or "").strip()) or "sem_chapa"
        tmp = tempfile.NamedTemporaryFile(
            prefix=f"consulta_pessoal_{cad}_{kind}_",
            suffix=suffix,
            delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.close()
        return tmp_path

    def _extrair_chapa_campos(self, campos: list[tuple[str, str]]) -> str:
        for k, v in list(campos or []):
            ku = normalize_ascii_upper(str(k or ""))
            if ku in {"NUMERO PESSOAL", "NO PESSOAL"}:
                return self._normalizar_chapa_key(str(v or ""))
        return ""

    def _normalizar_numero_pessoal_em_linha(self, linha: str) -> str:
        return str(linha or "")

    def _response_indica_erro(self, response) -> bool:
        try:
            txt = normalize_ascii_upper(BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True))
        except Exception:
            txt = normalize_ascii_upper(getattr(response, "text", ""))
        return ("ENDERECO INCORRETO" in txt) or ("ENDEREÇO INCORRETO" in txt)

    def _follow_endereco_incorreto(self, response):
        if BeautifulSoup is None:
            return response
        try:
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception:
            return response
        for a in soup.find_all("a", href=True):
            txt = normalize_ascii_upper(a.get_text(" ", strip=True))
            href = str(a.get("href") or "").strip()
            if not href:
                continue
            if ("CLIQUE AQUI" in txt) or ("DEFAULT" in normalize_ascii_upper(href)) or ("CONSULTAPESSOAL" in normalize_ascii_upper(href)):
                try:
                    u = urljoin(response.url, href)
                    r = self.session.get(u, timeout=self._timeout_value())
                    r.raise_for_status()
                    return r
                except Exception:
                    break
        return response

    def _response_tem_resultado(self, response) -> bool:
        url_u = normalize_ascii_upper(str(getattr(response, "url", "") or ""))
        if self._response_indica_erro(response):
            return False
        try:
            html_text = self._response_text(response)
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception:
            return False
        txt = normalize_ascii_upper(soup.get_text(" ", strip=True))
        has_link_exibe = False
        has_link_ficha = False
        for a in soup.find_all("a", href=True):
            hu = normalize_ascii_upper(str(a.get("href") or ""))
            if ("EXIBEPEOPLE" in hu) or ("EXIBEPEOLPLE" in hu) or ("EXIBEFICHA" in hu):
                has_link_exibe = True
            if "EXIBEFICHA" in hu:
                has_link_ficha = True
            if has_link_exibe and has_link_ficha:
                break
        if has_link_ficha:
            return True
        raw_u = normalize_ascii_upper(html_text)
        if ("EXIBEFICHA" in raw_u) or ("EXIBEPEOPLE" in raw_u) or ("EXIBEPEOLPLE" in raw_u):
            has_link_exibe = True
            if "EXIBEFICHA" in raw_u:
                has_link_ficha = True
        tem_resultado_tabela = False
        for tr in soup.find_all("tr"):
            cels = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            cels = [c for c in cels if c]
            if len(cels) < 2:
                continue
            c0u = normalize_ascii_upper(cels[0])
            c1u = normalize_ascii_upper(cels[1])
            if ("NO PESSOAL" in c0u) and ("NOME" in c1u):
                continue
            dig0 = re.sub(r"\D+", "", cels[0])
            if dig0 and (len(dig0) >= 5):
                tem_resultado_tabela = True
                break
        if tem_resultado_tabela:
            return True
        if ("RESULTADO DA PESQUISA" in txt) and (("NO PESSOAL" in txt) or ("NOME" in txt)):
            return True
        if "EXIBEFICHA" in url_u:
            if (("NUMERO PESSOAL" in txt) or ("NO PESSOAL" in txt)) and ("NOME" in txt):
                return True
        if (("EXIBEPEOPLE" in url_u) or ("EXIBEPEOLPLE" in url_u)) and has_link_exibe:
            return True
        return False

    def _extract_result_page_url(self, html_text: str, base_url: str) -> str:
        if BeautifulSoup is None:
            return ""
        try:
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception:
            return ""

        # meta refresh
        for m in soup.find_all("meta"):
            equiv = str(m.get("http-equiv") or "").strip().lower()
            content = str(m.get("content") or "")
            if equiv == "refresh" and "url=" in content.lower():
                try:
                    u = content.split("url=", 1)[1].strip().strip("\"'")
                    if ("EXIBEPEOPLE" in normalize_ascii_upper(u)) or ("EXIBEPEOLPLE" in normalize_ascii_upper(u)):
                        return urljoin(base_url, u)
                except Exception:
                    pass

        # anchors and frames
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "").strip()
            if ("EXIBEPEOPLE" in normalize_ascii_upper(href)) or ("EXIBEPEOLPLE" in normalize_ascii_upper(href)):
                return urljoin(base_url, href)
        for f in soup.find_all(["frame", "iframe"]):
            src = str(f.get("src") or "").strip()
            if ("EXIBEPEOPLE" in normalize_ascii_upper(src)) or ("EXIBEPEOLPLE" in normalize_ascii_upper(src)):
                return urljoin(base_url, src)

        # javascript redirects
        html_join = soup.get_text(" ", strip=True)
        for m in re.findall(r"(ExibePe(?:op|ol)p?le\.asp[^'\"\\s]*)", html_join, flags=re.I):
            return urljoin(base_url, m)
        return ""

    def _fix_exibepeople_url(self, url_txt: str) -> str:
        u = str(url_txt or "").strip()
        if "ExibePeolple.asp" in u:
            u = u.replace("ExibePeolple.asp", "ExibePeople.asp")
        if "exibepeolple.asp" in u:
            u = u.replace("exibepeolple.asp", "exibepeople.asp")
        return u

    def _page_is_ficha_conteudo(self, url_txt: str, html_text: str) -> bool:
        try:
            txt = normalize_ascii_upper(BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True))
        except Exception:
            txt = normalize_ascii_upper(html_text or "")
        if ("ENDERECO INCORRETO" in txt) or ("ENDEREÇO INCORRETO" in txt):
            return False
        tem_no_pessoal = ("NUMERO PESSOAL" in txt) or ("NO PESSOAL" in txt)
        tem_nome = (" NOME " in f" {txt} ") or ("| NOME" in txt) or ("NOME |" in txt)

        campos_funcionais = any(
            k in txt
            for k in [
                "CPI",
                "RAMAL",
                "AREA DE RH",
                "CENTRO DE CUSTO",
                "SUB GRUPO EMPREGADO",
                "ADMISSAO",
                "DEMISSAO",
            ]
        )
        campos_pessoais = any(
            k in txt
            for k in [
                "ENDERECO",
                "BAIRRO",
                "CEP",
                "CIDADE",
                "ESTADO CIVIL",
                "DATA NASCIMENTO",
                "NOME DO PAI",
                "NOME DA MAE",
            ]
        )
        campos_empresa_funcao = ("EMPRESA" in txt) and ("FUNCAO" in txt)

        if tem_no_pessoal and tem_nome and (campos_funcionais or campos_pessoais or campos_empresa_funcao):
            return True
        return False

    def _extrair_chapas_da_result_page(self, html_text: str, cadastro_hint: str = "") -> list[str]:
        vals: list[str] = []
        seen: set[str] = set()
        hint_norm = (re.sub(r"\D+", "", str(cadastro_hint or "")) or "")
        aceitar_todos = (hint_norm == "")

        def _add(raw_val: str) -> None:
            dig = re.sub(r"\D+", "", str(raw_val or ""))
            if not dig:
                return
            if (len(dig) < 5) or (len(dig) > 12):
                return
            if (not aceitar_todos) and (dig != hint_norm):
                return
            if dig not in seen:
                vals.append(dig)
                seen.add(dig)

        try:
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception:
            soup = None

        if soup is not None:
            for tr in soup.find_all("tr"):
                cels = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                cels = [c for c in cels if c]
                if not cels:
                    continue
                _add(cels[0])

            for a in soup.find_all("a", href=True):
                _add(a.get_text(" ", strip=True))
                href = str(a.get("href") or "")
                for m in re.findall(r"chapa\s*=\s*([0-9]{5,12})", href, flags=re.I):
                    _add(m)

            for tag in soup.find_all(attrs={"onclick": True}):
                onclick = str(tag.get("onclick") or "")
                for m in re.findall(r"chapa\s*=\s*([0-9]{5,12})", onclick, flags=re.I):
                    _add(m)

        for m in re.findall(r"chapa\s*=\s*([0-9]{5,12})", str(html_text or ""), flags=re.I):
            _add(m)

        return vals[:20]

    def _expandir_fichas_via_resultado(
        self,
        details: list[tuple[str, str]],
        cadastro_hint: str,
    ) -> list[tuple[str, str]]:
        if self.session is None:
            return details
        if BeautifulSoup is None:
            return details

        out = list(details)
        req_seen: set[str] = set()

        for url_det, html_det in list(details):
            base_url = str(url_det or "").strip() or self.base_url
            url_u = normalize_ascii_upper(base_url)

            txt_u = ""
            try:
                txt_u = normalize_ascii_upper(BeautifulSoup(html_det, "html.parser").get_text(" ", strip=True))
            except Exception:
                txt_u = normalize_ascii_upper(html_det or "")

            if ("EXIBEPEOPLE" not in url_u) and ("EXIBEPEOLPLE" not in url_u) and ("RESULTADO DA PESQUISA" not in txt_u):
                continue

            chapas = self._extrair_chapas_da_result_page(html_det, cadastro_hint=cadastro_hint)
            cand_urls: list[str] = []
            soup = BeautifulSoup(html_det, "html.parser")

            for a in soup.find_all("a", href=True):
                href = str(a.get("href") or "").strip()
                if not href:
                    continue
                hu = normalize_ascii_upper(href)
                if ("EXIBEFICHAFUNCIONAIS" in hu) or ("EXIBEFICHAPESSOAIS" in hu):
                    cand_urls.append(urljoin(base_url, href))

            for tag in soup.find_all(attrs={"onclick": True}):
                onclick = str(tag.get("onclick") or "")
                for m in re.findall(
                    r"([A-Za-z0-9_./-]*ExibeFicha(?:Funcionais|Pessoais)\.asp(?:\?[^'\"<>\s]+)?)",
                    onclick,
                    flags=re.I,
                ):
                    cand_urls.append(urljoin(base_url, m))

            # Nao inventa links de ficha: apenas segue links presentes na pagina/onclick.

            uniq_cands: list[str] = []
            seen_cands: set[str] = set()
            for u in cand_urls:
                uu = str(u or "").strip()
                if uu and (uu not in seen_cands):
                    uniq_cands.append(uu)
                    seen_cands.add(uu)

            for u in uniq_cands[:30]:
                req_key = f"{base_url}|{u}"
                if req_key in req_seen:
                    continue
                req_seen.add(req_key)
                try:
                    r = self.session.get(
                        u,
                        headers={
                            "Referer": base_url,
                            "Origin": CONSULTA_PESSOAL_ORIGIN,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        },
                        timeout=self._timeout_value(),
                    )
                    r.raise_for_status()
                    out.append((str(r.url or u), r.text))
                except Exception:
                    continue

            # Fallback importante: simula o "clique" pelo formulario da pagina de resultado.
            try:
                forms = soup.find_all("form")
            except Exception:
                forms = []

            hint_norm = (re.sub(r"\D+", "", str(cadastro_hint or "")) or "")
            for form in forms[:6]:
                try:
                    action, method, payload_base = self._form_to_request(base_url, form)
                except Exception:
                    continue

                submit_opts: list[tuple[str, str]] = []
                for inp in form.find_all("input"):
                    tp = str(inp.get("type") or "").strip().lower()
                    if tp not in {"submit", "button", "image"}:
                        continue
                    nm = str(inp.get("name") or "").strip()
                    val = str(inp.get("value") or "").strip()
                    submit_opts.append((nm, val))
                if not submit_opts:
                    submit_opts = [("", "")]

                chapa_fields: list[str] = []
                for inp in form.find_all("input"):
                    nm = str(inp.get("name") or "").strip()
                    if not nm:
                        continue
                    nu = normalize_ascii_upper(nm)
                    if ("CHAPA" in nu) or ("PESSOAL" in nu) or ("CADASTRO" in nu) or ("MATRIC" in nu):
                        chapa_fields.append(nm)

                chapas_try = self._extrair_chapas_da_result_page(html_det, cadastro_hint=cadastro_hint)
                chapas_try = [c for c in chapas_try if str(c).strip()]

                for chapa_val in chapas_try[:8]:
                    dig_norm = (re.sub(r"\D+", "", chapa_val) or "")
                    if hint_norm and dig_norm and (dig_norm != hint_norm):
                        continue

                    for sub_nm, sub_val in submit_opts[:4]:
                        payload_try = dict(payload_base)
                        if sub_nm:
                            payload_try[sub_nm] = sub_val
                        for fn in chapa_fields:
                            payload_try[fn] = chapa_val

                        req_key = f"FORM|{action}|{method}|{chapa_val}|{sub_nm}|{sub_val}"
                        if req_key in req_seen:
                            continue
                        req_seen.add(req_key)

                        try:
                            r = self._request_form(action, method, payload_try)
                            out.append((str(r.url or action), r.text))
                        except Exception:
                            continue

        return out

    def _is_devtools_bloqueado(self, msg: str) -> bool:
        m = normalize_ascii_upper(msg or "")
        return (
            ("DEVTOOLSACTIVEPORT" in m)
            or ("DEVTOOLS REMOTE DEBUGGING IS DISALLOWED" in m)
            or ("REMOTE DEBUGGING IS DISALLOWED" in m)
        )

    def _gerar_print_fallback(
        self,
        cadastro: str,
        linhas: list[str] | None,
        titulo: str,
        detalhe: str = "",
    ) -> str:
        try:
            cad = str(cadastro or "").strip() or "sem_cadastro"
            out_img = self._temp_image_path(cad, kind="fallback", suffix=".png")

            fig, ax = plt.subplots(figsize=(12, 7), dpi=120)
            ax.axis("off")
            fig.suptitle(titulo, fontsize=14, fontweight="bold")
            ax.text(
                0.02,
                0.92,
                f"Cadastro: {cad}",
                fontsize=11,
                fontweight="bold",
                color="white",
                ha="left",
                va="top",
                transform=ax.transAxes,
                bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.35"),
            )

            if detalhe:
                ax.text(
                    0.02,
                    0.84,
                    f"Detalhe: {detalhe}",
                    fontsize=9.2,
                    ha="left",
                    va="top",
                    transform=ax.transAxes,
                )

            y = 0.77
            linhas_show = list(linhas or [])
            if not linhas_show:
                linhas_show = ["Sem detalhes textuais para exibir."]
            for ln in linhas_show[:34]:
                wraps = textwrap.wrap(str(ln), width=135, break_long_words=False, break_on_hyphens=False) or [""]
                for part in wraps:
                    ax.text(0.02, y, part, fontsize=8.8, ha="left", va="top", transform=ax.transAxes)
                    y -= 0.024
                    if y < 0.05:
                        break
                if y < 0.05:
                    break

            fig.tight_layout(rect=[0, 0, 1, 0.96])
            fig.savefig(out_img, bbox_inches="tight")
            plt.close(fig)
            return str(out_img)
        except Exception:
            return ""

    def _consultar_via_requests(
        self,
        cadastro: str,
        nome_hint: str = "",
        modo_busca: str = "",
        termo_busca: str = "",
    ) -> dict:
        cad = self._normalizar_numero_pessoal(cadastro)
        out = {
            "cadastro": cad,
            "ok": False,
            "mensagem": "",
            "url_final": "",
            "linhas": [],
            "print_path": "",
            "mensagem_print": "",
            "fichas": [],
            "foto_path": "",
            "fotos_por_chapa": {},
        }

        if requests is None:
            out["mensagem"] = "Biblioteca requests indisponivel no ambiente."
            return out
        if BeautifulSoup is None:
            out["mensagem"] = "Biblioteca bs4 indisponivel no ambiente."
            return out
        if self.session is None:
            out["mensagem"] = "Sessao requests indisponivel."
            return out

        try:
            trace: list[str] = []
            resp_login = self.session.get(self.base_url, timeout=self._timeout_value())
            resp_login.raise_for_status()
            if self._response_indica_erro(resp_login):
                resp_login = self._follow_endereco_incorreto(resp_login)
            if self.debug_passos:
                trace.append(f"[PASSO 1] GET login OK: {resp_login.url}")

            resp_pos_login = self._submit_login_requests(resp_login)
            if self.debug_passos:
                trace.append(f"[PASSO 2] POST login OK: {resp_pos_login.url}")
            # Se ainda cair em "Endereco incorreto" ou continuar exibindo login, tenta novamente seguindo o link.
            if self._response_indica_erro(resp_pos_login):
                resp_pos_login = self._follow_endereco_incorreto(resp_pos_login)
                if self.debug_passos:
                    trace.append(f"[PASSO 2B] Seguiu clique-aqui: {resp_pos_login.url}")
            # evita re-login em formularios auxiliares (ex: clock)
            # apos login, precisa clicar "Prosseguir" para abrir tela de pesquisa
            resp_pos_login = self._submit_prosseguir(resp_pos_login)
            if self.debug_passos:
                trace.append(f"[PASSO 2D] Prosseguir OK: {resp_pos_login.url}")
            resp_search = self._submit_search(
                resp_pos_login,
                cad,
                nome_hint=nome_hint,
                modo_busca=modo_busca,
                termo_busca=termo_busca,
            )
            if self.debug_passos:
                trace.append(f"[PASSO 3] Pesquisa OK: {resp_search.url}")
                if self._debug_form_info:
                    trace.append(self._debug_form_info)
                    try:
                        print(self._debug_form_info)
                    except Exception:
                        pass

            # tentativa direta: se a pagina ja trouxe links de ficha, abre agora
            direct_details: list[tuple[str, str]] = []
            html_search = self._response_text(resp_search)
            for m in re.findall(
                r"(ExibeFicha(?:Funcionais|Pessoais)\.asp\?chapa=[0-9]+)",
                str(html_search or ""),
                flags=re.I,
            )[:6]:
                u = urljoin(str(resp_search.url or ""), m)
                try:
                    r0 = self.session.get(
                        u,
                        timeout=self._timeout_value(),
                        headers={
                            "Referer": str(resp_search.url or ""),
                            "Origin": CONSULTA_PESSOAL_ORIGIN,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    r0.raise_for_status()
                    if not getattr(r0, "encoding", None):
                        r0.encoding = "latin-1"
                    direct_details.append((str(r0.url or u), self._response_text(r0)))
                except Exception:
                    continue

            if direct_details:
                details = [(str(resp_search.url or ""), html_search)] + direct_details
                if self.debug_passos:
                    try:
                        trace.append(f"[PASSO 3X] direct_details={len(direct_details)}")
                    except Exception:
                        pass
            # Em alguns casos o portal mantém a URL em FindPeople.asp após o submit.
            # Força uma ida ao ExibePeople.asp para simular o passo do navegador,
            # mas sem "inventar" links de ficha (somente seguir o resultado real).
            try:
                if direct_details:
                    pass
                elif (not self._response_tem_resultado(resp_search)) and ("EXIBEPEOPLE" not in normalize_ascii_upper(str(resp_search.url or ""))):
                    html_search = self._response_text(resp_search)
                    url_exibe = self._extract_result_page_url(html_search, str(resp_search.url or ""))
                    if not url_exibe:
                        url_exibe = urljoin(str(resp_search.url or ""), "ExibePeople.asp")
                    url_exibe = self._fix_exibepeople_url(url_exibe)
                    r_people = self.session.get(
                        url_exibe,
                        headers={
                            "Referer": str(resp_search.url or ""),
                            "Origin": CONSULTA_PESSOAL_ORIGIN,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        },
                        timeout=self._timeout_value(),
                    )
                    if self.debug_passos:
                        trace.append(f"[PASSO 3B] GET ExibePeople: {r_people.url} (status={r_people.status_code})")
                    if r_people.ok:
                        # injeta a pagina de resultado no fluxo de detalhes
                        details = self._fetch_detail_pages(r_people, cad)
                    else:
                        # fallback: tenta submeter formularios do FindPeople para obter o resultado real
                        details = self._fetch_detail_pages(resp_search, cad)
                        if BeautifulSoup is not None:
                            try:
                                soup_fp = BeautifulSoup(resp_search.text, "html.parser")
                                forms = soup_fp.find_all("form")
                                if self.debug_passos:
                                    trace.append(f"[PASSO 3C] Forms no FindPeople: {len(forms)}")
                            except Exception:
                                forms = []
                            for form in forms[:4]:
                                try:
                                    action, method, payload = self._form_to_request(str(resp_search.url or ""), form)
                                    action = self._fix_exibepeople_url(action)
                                    # preserva submit de pesquisa caso exista
                                    for inp in form.find_all("input"):
                                        tp = str(inp.get("type") or "").strip().lower()
                                        if tp in {"submit", "button"} and inp.get("name"):
                                            payload[str(inp.get("name"))] = str(inp.get("value") or "")
                                    r_fp = self._request_form(action, method, payload)
                                    if self.debug_passos:
                                        trace.append(f"[PASSO 3C] POST resultado: {r_fp.url} (status={r_fp.status_code})")
                                    details = self._fetch_detail_pages(r_fp, cad)
                                    break
                                except Exception as exc_post:
                                    if self.debug_passos:
                                        trace.append(f"[PASSO 3C] Falha POST resultado: {exc_post}")
                                    continue
                else:
                    if not direct_details:
                        details = self._fetch_detail_pages(resp_search, cad)
            except Exception as exc_people:
                if self.debug_passos:
                    trace.append(f"[PASSO 3B] Falha ao abrir ExibePeople: {exc_people}")
                if not direct_details:
                    details = self._fetch_detail_pages(resp_search, cad)
            if self.debug_passos:
                trace.append(f"[PASSO 4] Paginas coletadas (antes expansão): {len(details)}")
            details = self._expandir_fichas_via_resultado(details, cadastro_hint=cad)
            if self.debug_passos:
                trace.append(f"[PASSO 5] Paginas coletadas (após expansão): {len(details)}")

            linhas: list[str] = []
            linhas_diag: list[str] = []
            urls_finais: list[str] = []
            urls_ficha: list[str] = []
            seen_linhas: set[str] = set()
            seen_diag: set[str] = set()
            fichas: list[dict] = []
            seen_fichas: set[str] = set()
            foto_path = ""
            fotos_por_chapa: dict[str, str] = {}

            for url_det, html_det in details:
                url_det = str(url_det or "").strip()
                if url_det and (url_det not in urls_finais):
                    urls_finais.append(url_det)
                eh_ficha = self._page_is_ficha_conteudo(url_det, html_det)
                url_u = normalize_ascii_upper(url_det)
                linhas_extraidas = self._extract_lines(html_det)
                txt_u = normalize_ascii_upper(" ".join(linhas_extraidas))
                is_endereco_incorreto = ("ENDERECO INCORRETO" in txt_u) or ("ENDEREÇO INCORRETO" in txt_u)
                if self.debug_passos and (
                    ("EXIBEPEOPLE" in url_u)
                    or ("EXIBEFICHA" in url_u)
                ):
                    trace.append(
                        f"[PASSO 6] URL={url_det} | ficha_valida={eh_ficha} | endereco_incorreto={is_endereco_incorreto}"
                    )

                if eh_ficha:
                    if url_det and (url_det not in urls_ficha):
                        urls_ficha.append(url_det)
                    if "EXIBEFICHAPESSOAIS" in url_u:
                        tag = "Pessoais"
                    elif "EXIBEFICHAFUNCIONAIS" in url_u:
                        tag = "Funcionais"
                    elif "EXIBEFICHA" in url_u:
                        tag = "Ficha"
                    else:
                        tag = "Detalhe"

                    head = f"[{tag}] {url_det}" if url_det else f"[{tag}]"
                    if head not in seen_linhas:
                        linhas.append(head)
                        seen_linhas.add(head)

                    for ln in linhas_extraidas:
                        ln = self._normalizar_numero_pessoal_em_linha(ln)
                        if ln not in seen_linhas:
                            linhas.append(ln)
                            seen_linhas.add(ln)

                    campos_ficha = self._extract_ficha_campos(html_det)
                    chapa_det = self._normalizar_chapa_key(self._extrair_chapa_de_url(url_det))
                    if (not chapa_det) and campos_ficha:
                        chapa_det = self._extrair_chapa_campos(campos_ficha)
                    if campos_ficha:
                        fkey = normalize_ascii_upper(url_det) or f"{tag}|{len(campos_ficha)}"
                        if fkey not in seen_fichas:
                            fichas.append(
                                {
                                    "tipo": tag,
                                    "url": url_det,
                                    "chapa": chapa_det,
                                    "campos": campos_ficha,
                                }
                            )
                            seen_fichas.add(fkey)
                    if chapa_det:
                        foto_det = self._baixar_foto_ficha(html_det, url_det, chapa_det)
                        if foto_det:
                            fotos_por_chapa[chapa_det] = foto_det
                            foto_path = foto_det
                    elif (not foto_path):
                        foto_path = self._baixar_foto_ficha(html_det, url_det, cad)
                else:
                    if len(linhas_diag) < 30:
                        for ln in linhas_extraidas:
                            lu = normalize_ascii_upper(ln)
                            if not (
                                ("ENDERECO INCORRETO" in lu)
                                or ("ENDEREÇO INCORRETO" in lu)
                                or ("CLIQUE AQUI" in lu)
                                or ("RESULTADO DA PESQUISA" in lu)
                                or ("CONSULTA DE PESSOAL" in lu)
                            ):
                                continue
                            if ln not in seen_diag:
                                linhas_diag.append(ln)
                                seen_diag.add(ln)
                            if len(linhas_diag) >= 30:
                                break

            # Garante que as duas visoes (Funcionais e Pessoais) sejam tentadas
            # quando ao menos uma ficha valida foi encontrada.
            tipos_existentes = {normalize_ascii_upper(str(f.get("tipo") or "")) for f in fichas}
            need_func = "FUNCIONAIS" not in tipos_existentes
            need_pess = "PESSOAIS" not in tipos_existentes
            if (need_func or need_pess) and self.session is not None:
                for base_ficha in list(urls_ficha)[:6]:
                    base_u = normalize_ascii_upper(base_ficha)
                    alvos: list[tuple[str, str]] = []
                    if need_pess and ("EXIBEFICHAFUNCIONAIS" in base_u):
                        alvos.append(("Pessoais", re.sub("ExibeFichaFuncionais\\.asp", "ExibeFichaPessoais.asp", base_ficha, flags=re.I)))
                    if need_func and ("EXIBEFICHAPESSOAIS" in base_u):
                        alvos.append(("Funcionais", re.sub("ExibeFichaPessoais\\.asp", "ExibeFichaFuncionais.asp", base_ficha, flags=re.I)))
                    for tag_alvo, url_alvo in alvos:
                        if not url_alvo:
                            continue
                        try:
                            r_alt = self.session.get(
                                url_alvo,
                                timeout=self._timeout_value(),
                                headers={
                                    "Referer": base_ficha,
                                    "Origin": CONSULTA_PESSOAL_ORIGIN,
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                },
                            )
                            r_alt.raise_for_status()
                            html_alt = self._response_text(r_alt)
                            url_alt = str(r_alt.url or url_alvo)
                            if not self._page_is_ficha_conteudo(url_alt, html_alt):
                                continue
                            campos_alt = self._extract_ficha_campos(html_alt)
                            if not campos_alt:
                                continue
                            key_alt = normalize_ascii_upper(url_alt)
                            if key_alt in seen_fichas:
                                continue
                            chapa_alt = self._normalizar_chapa_key(self._extrair_chapa_de_url(url_alt))
                            if (not chapa_alt) and campos_alt:
                                chapa_alt = self._extrair_chapa_campos(campos_alt)
                            fichas.append({"tipo": tag_alvo, "url": url_alt, "chapa": chapa_alt, "campos": campos_alt})
                            seen_fichas.add(key_alt)
                            if url_alt not in urls_ficha:
                                urls_ficha.append(url_alt)
                            if chapa_alt:
                                foto_alt = self._baixar_foto_ficha(html_alt, url_alt, chapa_alt)
                                if foto_alt:
                                    fotos_por_chapa[chapa_alt] = foto_alt
                                    foto_path = foto_alt
                            elif (not foto_path):
                                foto_path = self._baixar_foto_ficha(html_alt, url_alt, cad)
                            tipos_existentes.add(normalize_ascii_upper(tag_alvo))
                            need_func = "FUNCIONAIS" not in tipos_existentes
                            need_pess = "PESSOAIS" not in tipos_existentes
                        except Exception:
                            continue
                    if (not need_func) and (not need_pess):
                        break

            if linhas:
                out["ok"] = True
                out["mensagem"] = "Consulta pessoal carregada com sucesso."
                out["url_final"] = " | ".join((urls_ficha or urls_finais)[:6]) if (urls_ficha or urls_finais) else str(resp_search.url or "")
                out["linhas"] = (trace + linhas) if self.debug_passos else linhas
                out["fichas"] = fichas
                out["foto_path"] = foto_path
                out["fotos_por_chapa"] = fotos_por_chapa
                return out

            vars_txt = ", ".join(self._ultimas_variantes_busca[:16]) if self._ultimas_variantes_busca else cad
            out["ok"] = False
            out["mensagem"] = (
                "Consulta sem retorno de ficha (resultado nao encontrado no portal). "
                f"Tentativas de busca (opcao:valor): {vars_txt}."
            )
            out["url_final"] = " | ".join(urls_finais[:6]) if urls_finais else str(resp_search.url or "")
            out["linhas"] = (trace + linhas_diag) if self.debug_passos else linhas_diag
            return out
        except Exception as exc:
            out["mensagem"] = f"Falha ao consultar cadastro {cad}: {exc}"
            return out

    def _score_form_login(self, form) -> int:
        score = 0
        has_password = bool(form.find("input", attrs={"type": re.compile(r"password", re.IGNORECASE)}))
        if has_password:
            score += 10
        else:
            return 0
        txt = normalize_ascii_upper(
            " ".join(
                [
                    form.get_text(" ", strip=True),
                    str(form.get("id") or ""),
                    str(form.get("name") or ""),
                    str(form.get("action") or ""),
                ]
            )
        )
        for kw in ["SENHA", "PASSWORD", "USUARIO", "USER", "PESSOAL", "NUMERO", "CHAPA", "LOGIN", "NO PESSOAL"]:
            if kw in txt:
                score += 2
        txt_inputs = [
            i
            for i in form.find_all("input")
            if str(i.get("type") or "text").strip().lower() in {"", "text", "number", "password"}
            and str(i.get("name") or "").strip()
        ]
        names_txt = [str(i.get("name") or "").strip().lower() for i in txt_inputs]
        if names_txt and all(n in {"thedate", "face"} for n in names_txt):
            return 0
        if len(txt_inputs) >= 2:
            score += 2
        return score

    def _score_form_pesquisa(self, form) -> int:
        score = 0
        txt = normalize_ascii_upper(
            " ".join(
                [
                    form.get_text(" ", strip=True),
                    str(form.get("id") or ""),
                    str(form.get("name") or ""),
                    str(form.get("action") or ""),
                ]
            )
        )
        for kw in ["PESQUISA", "LOCALIZAR", "BUSCAR", "CONSULTA", "PESSOAL", "CHAPA", "NUMERO", "NOME", "PIS", "CPF"]:
            if kw in txt:
                score += 2
        inputs_text = [
            i
            for i in form.find_all("input")
            if str(i.get("type") or "text").strip().lower() in {"", "text", "number"}
            and str(i.get("name") or "").strip()
        ]
        if inputs_text:
            score += 4
        names_text = [str(i.get("name") or "").strip().lower() for i in inputs_text]
        if names_text and all(n in {"thedate", "face"} for n in names_text):
            return 0
        if inputs_text:
            keywords = {"pessoal", "numero", "no", "chapa", "cadastro", "matricula", "nome", "pis", "cpf"}
            if not any(any(k in str(i.get("name") or "").lower() for k in keywords) for i in inputs_text):
                score -= 2
        radios = form.find_all("input", attrs={"type": "radio"})
        if radios:
            score += 2
        submits = [
            i
            for i in form.find_all("input")
            if str(i.get("type") or "").strip().lower() in {"submit", "button", "image"}
        ]
        if submits:
            score += 2
        return score

    def _buscar_form_pesquisa(self, response):
        soup_base = BeautifulSoup(response.text, "html.parser")

        def _append_url(lst, seen, u):
            u = str(u or "").strip()
            if not u:
                return
            if u not in seen:
                lst.append(u)
                seen.add(u)

        urls_teste: list[str] = []
        seen_urls: set[str] = set()
        _append_url(urls_teste, seen_urls, response.url)
        _append_url(urls_teste, seen_urls, self.base_url)
        _append_url(urls_teste, seen_urls, urljoin(response.url, "./"))
        for guess in ["default.htm", "FindPeople.asp", "findpeople.asp", "default.asp", "index.asp"]:
            _append_url(urls_teste, seen_urls, urljoin(response.url, guess))

        for m in soup_base.find_all("meta"):
            equiv = str(m.get("http-equiv") or "").strip().lower()
            content = str(m.get("content") or "")
            if equiv == "refresh" and "url=" in content.lower():
                try:
                    u = content.split("url=", 1)[1].strip().strip("\"'")
                    _append_url(urls_teste, seen_urls, urljoin(response.url, u))
                except Exception:
                    pass

        for tg in soup_base.find_all(["frame", "iframe"]):
            src_ = str(tg.get("src") or "").strip()
            if src_:
                _append_url(urls_teste, seen_urls, urljoin(response.url, src_))

        for a in soup_base.find_all("a", href=True):
            href_ = str(a.get("href") or "").strip()
            if not href_:
                continue
            hu = normalize_ascii_upper(href_)
            if ("FINDPEOPLE" in hu) or ("CONSULTAPESSOAL" in hu) or hu.endswith(".ASP"):
                _append_url(urls_teste, seen_urls, urljoin(response.url, href_))

        # regex genérico para .asp no HTML
        for m in re.findall(r"([A-Za-z0-9_./-]+\.asp(?:\?[^'\"<>\s]+)?)", response.text, flags=re.I):
            _append_url(urls_teste, seen_urls, urljoin(response.url, m))

        melhor_form = None
        melhor_score = -1
        melhor_url = response.url
        melhor_soup = soup_base

        for u in urls_teste[:30]:
            try:
                r = self.session.get(u, timeout=self._timeout_value())
                r.raise_for_status()
                s = BeautifulSoup(r.text, "html.parser")

                for f in s.find_all("form"):
                    score = self._score_form_pesquisa(f)
                    if score > melhor_score:
                        melhor_form = f
                        melhor_score = score
                        melhor_url = r.url
                        melhor_soup = s

                if melhor_score >= 8:
                    break
            except Exception:
                continue

        if melhor_score < 3:
            return None, response.url, soup_base
        return melhor_form, melhor_url, melhor_soup

    def _buscar_form_login(self, response):
        soup_base = BeautifulSoup(response.text, "html.parser")

        def _append_url(lst, seen, u):
            u = str(u or "").strip()
            if not u:
                return
            if u not in seen:
                lst.append(u)
                seen.add(u)

        urls_teste: list[str] = []
        seen_urls: set[str] = set()

        _append_url(urls_teste, seen_urls, response.url)
        _append_url(urls_teste, seen_urls, self.base_url)
        _append_url(urls_teste, seen_urls, urljoin(response.url, "./"))
        for guess in ["default.htm", "default.asp", "index.asp", "login.asp", "FindPeople.asp", "findpeople.asp"]:
            _append_url(urls_teste, seen_urls, urljoin(response.url, guess))

        for m in soup_base.find_all("meta"):
            equiv = str(m.get("http-equiv") or "").strip().lower()
            content = str(m.get("content") or "")
            if equiv == "refresh" and "url=" in content.lower():
                try:
                    u = content.split("url=", 1)[1].strip().strip("\"'")
                    _append_url(urls_teste, seen_urls, urljoin(response.url, u))
                except Exception:
                    pass

        for tg in soup_base.find_all(["frame", "iframe"]):
            src_ = str(tg.get("src") or "").strip()
            if src_:
                _append_url(urls_teste, seen_urls, urljoin(response.url, src_))

        for a in soup_base.find_all("a", href=True):
            href_ = str(a.get("href") or "").strip()
            if not href_:
                continue
            hu = normalize_ascii_upper(href_)
            if (
                ("CONSULTAPESSOAL" in hu)
                or ("FINDPEOPLE" in hu)
                or ("EXIBE" in hu)
                or hu.endswith(".ASP")
            ):
                _append_url(urls_teste, seen_urls, urljoin(response.url, href_))

        melhor_form = None
        melhor_score = -1
        melhor_url = response.url
        melhor_soup = soup_base

        for u in urls_teste[:30]:
            try:
                r = self.session.get(u, timeout=self._timeout_value())
                r.raise_for_status()
                s = BeautifulSoup(r.text, "html.parser")

                for f in s.find_all("form"):
                    score = self._score_form_login(f)
                    if score > melhor_score:
                        melhor_form = f
                        melhor_score = score
                        melhor_url = r.url
                        melhor_soup = s

                if melhor_form is None:
                    inputs_text = [
                        i
                        for i in s.find_all("input")
                        if str(i.get("type") or "text").strip().lower() in {"", "text", "number", "password"}
                        and str(i.get("name") or "").strip()
                    ]
                    has_password = any(
                        str(i.get("type") or "").strip().lower() == "password" for i in inputs_text
                    )
                    if has_password and (len(inputs_text) >= 2):
                        f_login = s.new_tag("form")
                        f_login["action"] = r.url
                        f_login["method"] = "post"
                        for i_tag in inputs_text:
                            f_login.append(i_tag)
                        melhor_form = f_login
                        melhor_score = max(melhor_score, 4)
                        melhor_url = r.url
                        melhor_soup = s

                if melhor_score >= 10:
                    break
            except Exception:
                continue

        return melhor_form, melhor_url, melhor_soup

    def _submit_login_requests(self, response):
        form_login, url_login_base, soup_login = self._buscar_form_login(response)
        if form_login is None:
            titulo_pg = str(soup_login.title.get_text(" ", strip=True) if soup_login and soup_login.title else "")
            txt_diag = ""
            try:
                txt_diag = " ".join(soup_login.get_text(" ", strip=True).split())[:180] if soup_login else ""
            except Exception:
                txt_diag = ""
            raise RuntimeError(
                f"Formulario de login nao encontrado. URL={url_login_base} | title={titulo_pg} | snippet={txt_diag}"
            )

        action, method, payload = self._form_to_request(url_login_base, form_login)

        user_name = self._find_input_name(
            form_login,
            keywords=["user", "usuario", "pessoal", "numero", "no", "chapa", "login", "no pessoal"],
            preferred_types={"text", "number", "password"},
        )
        pass_name = self._find_input_name(
            form_login,
            keywords=["senha", "password", "pass", "pwd"],
            preferred_types={"password", "text", "number"},
        )

        # fallback: usa id quando name não existir
        if not user_name or not pass_name:
            txt_inputs_login = [
                i
                for i in form_login.find_all("input")
                if str(i.get("type") or "text").strip().lower() in {"", "text", "number", "password"}
            ]
            if not user_name and txt_inputs_login:
                non_pwd = [i for i in txt_inputs_login if str(i.get("type") or "text").strip().lower() != "password"]
                cand = non_pwd[0] if non_pwd else txt_inputs_login[0]
                nm = str(cand.get("name") or "").strip()
                if not nm:
                    nm = str(cand.get("id") or "").strip()
                user_name = nm or user_name
            if not pass_name:
                pass_inputs = [
                    i
                    for i in form_login.find_all("input")
                    if str(i.get("type") or "").strip().lower() == "password"
                ]
                if pass_inputs:
                    nm = str(pass_inputs[0].get("name") or "").strip()
                    if not nm:
                        nm = str(pass_inputs[0].get("id") or "").strip()
                    pass_name = nm or pass_name
        if user_name and pass_name and (user_name == pass_name):
            pass_inputs = [
                i
                for i in form_login.find_all("input")
                if str(i.get("type") or "").strip().lower() == "password"
            ]
            if pass_inputs:
                nm = str(pass_inputs[0].get("name") or "").strip()
                if not nm:
                    nm = str(pass_inputs[0].get("id") or "").strip()
                if nm:
                    pass_name = nm

        # inclui submit se existir (alguns ASP validam isso)
        for inp in form_login.find_all("input"):
            tp = str(inp.get("type") or "").strip().lower()
            nm = str(inp.get("name") or "").strip()
            val = str(inp.get("value") or "").strip()
            if tp in {"submit", "button", "image"} and nm and val:
                payload[nm] = val
                break
            if tp == "image" and nm:
                payload[f"{nm}.x"] = "10"
                payload[f"{nm}.y"] = "10"

        if self.debug_passos:
            try:
                inputs_dbg = []
                for inp in form_login.find_all("input"):
                    nm = str(inp.get("name") or "").strip()
                    if not nm:
                        nm = str(inp.get("id") or "").strip()
                    tp = str(inp.get("type") or "").strip().lower()
                    if nm:
                        inputs_dbg.append(f"{nm}:{tp}")
                print(f"[DEBUG LOGIN] action={action} method={method} user={user_name} pass={pass_name} inputs={inputs_dbg[:12]}")
            except Exception:
                pass

        if not user_name:
            txt_inputs_login = [
                i
                for i in form_login.find_all("input")
                if str(i.get("type") or "text").strip().lower() in {"", "text", "number", "password"}
            ]
            user_name = str(txt_inputs_login[0].get("name") or "").strip() if txt_inputs_login else ""

        if not pass_name:
            pass_inputs = [
                i
                for i in form_login.find_all("input")
                if str(i.get("type") or "").strip().lower() == "password"
            ]
            if pass_inputs:
                pass_name = str(pass_inputs[0].get("name") or "").strip()
            else:
                txt_inputs_login = [
                    i
                    for i in form_login.find_all("input")
                    if str(i.get("type") or "text").strip().lower() in {"", "text", "number", "password"}
                ]
                nomes = [str(i.get("name") or "").strip() for i in txt_inputs_login if str(i.get("name") or "").strip()]
                for nm in nomes:
                    if nm != user_name:
                        pass_name = nm
                        break

        if not user_name or not pass_name:
            raise RuntimeError("Campos User/Password nao identificados no login.")

        payload[user_name] = self.user
        payload[pass_name] = self.password
        return self._request_form(action, method, payload)

    def _submit_prosseguir(self, response):
        if BeautifulSoup is None:
            return response
        try:
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception:
            return response
        forms = soup.find_all("form")
        if not forms:
            return response
        for form in forms:
            btn_ok = False
            for inp in form.find_all("input"):
                tp = str(inp.get("type") or "").strip().lower()
                val = str(inp.get("value") or "").strip()
                if tp in {"submit", "button", "image"} and val and re.search(r"prosseguir", val, flags=re.I):
                    btn_ok = True
                    break
            if not btn_ok:
                continue
            try:
                action, method, payload = self._form_to_request(response.url, form)
                for inp in form.find_all("input"):
                    tp = str(inp.get("type") or "").strip().lower()
                    nm = str(inp.get("name") or "").strip()
                    val = str(inp.get("value") or "").strip()
                    if tp in {"submit", "button", "image"} and nm and val:
                        payload[nm] = val
                        if tp == "image":
                            payload[f"{nm}.x"] = "10"
                            payload[f"{nm}.y"] = "10"
                        break
                return self._request_form(action, method, payload)
            except Exception:
                continue
        return response

    def _submit_search(
        self,
        response,
        cadastro: str,
        nome_hint: str = "",
        modo_busca: str = "",
        termo_busca: str = "",
    ):
        cadastro = self._normalizar_numero_pessoal(cadastro)
        nome_hint = str(nome_hint or "").strip()
        modo_busca_u = normalize_ascii_upper(str(modo_busca or "").strip())
        termo_forcado = str(termo_busca or "").strip()
        form_search, url_search_base, soup = self._buscar_form_pesquisa(response)
        if form_search is None:
            raise RuntimeError("Formulario de pesquisa nao encontrado apos login.")
        action, method, payload_base = self._form_to_request(url_search_base, form_search)
        if self.debug_passos:
            try:
                inputs_dbg = []
                for inp in form_search.find_all("input"):
                    nm = str(inp.get("name") or "").strip()
                    if not nm:
                        nm = str(inp.get("id") or "").strip()
                    tp = str(inp.get("type") or "").strip().lower()
                    if nm:
                        inputs_dbg.append(f"{nm}:{tp}")
                selects_dbg = []
                for sel in form_search.find_all("select"):
                    nm = str(sel.get("name") or "").strip()
                    if nm:
                        selects_dbg.append(nm)
                radios_dbg = []
                for r in form_search.find_all("input", attrs={"type": "radio"}):
                    nm = str(r.get("name") or "").strip()
                    val = str(r.get("value") or "").strip()
                    if nm:
                        radios_dbg.append(f"{nm}={val}")
                self._debug_form_info = (
                    f"[DEBUG FORM] url={url_search_base} action={action} method={method} "
                    f"inputs={inputs_dbg[:12]} radios={radios_dbg[:12]} selects={selects_dbg[:8]}"
                )
            except Exception:
                self._debug_form_info = ""

        # Em alguns ASPs o submit precisa ir no payload para validar a pesquisa.
        for inp in form_search.find_all("input"):
            tp = str(inp.get("type") or "").strip().lower()
            nm = str(inp.get("name") or "").strip()
            if not nm:
                nm = str(inp.get("id") or "").strip()
            val = str(inp.get("value") or "").strip()
            if tp in {"submit", "button"} and nm and val and re.search(r"localizar|pesquisa|buscar|ok", val, flags=re.I):
                payload_base[nm] = val
                break
        # Inputs do tipo image às vezes exigem coordenadas.
        image_buttons = []
        for inp in form_search.find_all("input"):
            tp = str(inp.get("type") or "").strip().lower()
            nm = str(inp.get("name") or "").strip()
            if not nm:
                nm = str(inp.get("id") or "").strip()
            val = str(inp.get("value") or "").strip()
            if tp == "image":
                image_buttons.append((nm, val))

        campo_busca = self._find_input_name(
            form_search,
            keywords=["pessoal", "numero", "no", "chapa", "cadastro", "matricula", "nome", "pis", "cpf"],
            preferred_types={"text", "number"},
        )
        if not campo_busca:
            inputs_text = [
                i for i in form_search.find_all("input") if (i.get("type", "text").lower() in {"", "text", "number"})
            ]
            campo_busca = inputs_text[0].get("name", "") if inputs_text else ""
        if not campo_busca:
            raise RuntimeError("Campo de pesquisa nao encontrado no formulario.")

        def _radio_marker(radio) -> str:
            parts = [
                str(radio.get("name") or ""),
                str(radio.get("id") or ""),
                str(radio.get("value") or ""),
            ]
            try:
                parts.append(str(radio.parent.get_text(" ", strip=True) or ""))
            except Exception:
                pass
            try:
                nxt = radio.next_sibling
                if nxt is not None:
                    parts.append(str(nxt))
            except Exception:
                pass
            return normalize_ascii_upper(" ".join(parts))

        radios = []
        for r in form_search.find_all("input", attrs={"type": "radio"}):
            nm = str(r.get("name") or "").strip()
            if not nm:
                continue
            marker = _radio_marker(r)
            kind = "OUTRO"
            if (str(r.get("value") or "").strip() == "0"):
                kind = "NO_PESSOAL"
            elif ("NO PESSOAL" in marker) or ("NUMERO PESSOAL" in marker) or ("NÚMERO PESSOAL" in marker) or ("CHAPA" in marker):
                kind = "NO_PESSOAL"
            elif "NOME" in marker:
                kind = "NOME"
            elif "PIS" in marker:
                kind = "PIS"
            elif "CPF" in marker:
                kind = "CPF"
            radios.append(
                {
                    "name": nm,
                    "value": str(r.get("value") or ""),
                    "marker": marker,
                    "kind": kind,
                }
            )

        if not radios:
            radios = [{"name": "", "value": "", "marker": "", "kind": "NO_PESSOAL"}]

        # Prioridade:
        # - consulta por cadastro: NO_PESSOAL
        # - consulta por nome: NOME
        # - fallback geral: NO_PESSOAL -> NOME -> PIS -> CPF -> OUTRO
        kind_ord = {"NO_PESSOAL": 0, "NOME": 1, "PIS": 2, "CPF": 3, "OUTRO": 4}
        radios = sorted(radios, key=lambda x: kind_ord.get(str(x.get("kind") or "OUTRO"), 9))
        radios_no_pessoal = [r for r in radios if str(r.get("kind") or "") == "NO_PESSOAL"]
        radios_nome = [r for r in radios if str(r.get("kind") or "") == "NOME"]
        radios_modo = [r for r in radios if str(r.get("kind") or "") == modo_busca_u]
        if modo_busca_u and radios_modo:
            radios = radios_modo + [r for r in radios if str(r.get("kind") or "") != modo_busca_u]
        elif cadastro and radios_no_pessoal:
            radios = radios_no_pessoal
        elif (not cadastro) and nome_hint and radios_nome:
            radios = radios_nome + [r for r in radios if str(r.get("kind") or "") != "NOME"]
        elif radios_no_pessoal:
            radios = radios_no_pessoal

        vars_chapa = [str(v).strip() for v in self._variantes_chapa(cadastro) if str(v).strip()]
        nome_vars = []
        if nome_hint:
            nome_vars.append(nome_hint)
            nome_ascii = normalize_ascii_upper(nome_hint)
            if nome_ascii and (nome_ascii not in nome_vars):
                nome_vars.append(nome_ascii)
            partes = [p for p in re.split(r"\s+", nome_hint.strip()) if p]
            if len(partes) >= 2:
                n2 = f"{partes[0]} {partes[1]}"
                if n2 not in nome_vars:
                    nome_vars.append(n2)
            if partes:
                n1 = partes[0]
                if n1 not in nome_vars:
                    nome_vars.append(n1)

        termos_por_kind: dict[str, list[str]] = {
            "NO_PESSOAL": vars_chapa,
            "NOME": nome_vars if nome_vars else vars_chapa,
            "PIS": vars_chapa,
            "CPF": vars_chapa,
            "OUTRO": vars_chapa,
        }
        if termo_forcado:
            termos_forcados = [termo_forcado]
            if modo_busca_u in termos_por_kind:
                termos_por_kind[modo_busca_u] = list(termos_forcados)
            for k in list(termos_por_kind.keys()):
                if (k != modo_busca_u) and (not termos_por_kind.get(k)):
                    termos_por_kind[k] = list(termos_forcados)
        if nome_hint and (not radios_nome):
            for k in list(termos_por_kind.keys()):
                termos_por_kind[k] = list(nome_vars)

        tentativas: list[str] = []
        ultimo_resp = None

        action_candidates: list[str] = []
        fixed = self._fix_exibepeople_url(action)
        for cand in [fixed, action]:
            c = str(cand or "").strip()
            if c and (c not in action_candidates):
                action_candidates.append(c)

        for radio in radios:
            kind = str(radio.get("kind") or "OUTRO")
            termos = [str(t).strip() for t in termos_por_kind.get(kind, vars_chapa) if str(t).strip()]
            if not termos:
                continue

            for termo in termos:
                base_payload = dict(payload_base)
                nm_r = str(radio.get("name") or "").strip()
                if nm_r:
                    base_payload[nm_r] = str(radio.get("value") or "")
                base_payload[campo_busca] = termo
                tentativas.append(f"{kind}:{termo}")

                # tentativa 1: payload base
                for act in action_candidates:
                    try:
                        resp_try = self._request_form(act, method, dict(base_payload))
                        ultimo_resp = resp_try
                        if self._response_tem_resultado(resp_try):
                            self._ultimas_variantes_busca = tentativas
                            return resp_try
                    except Exception as exc:
                        _ = str(exc)
                        continue

                # tentativa 2: simula click em botão imagem
                for nm_img, _ in image_buttons[:2]:
                    if not nm_img:
                        continue
                    payload_img = dict(base_payload)
                    payload_img[f"{nm_img}.x"] = "10"
                    payload_img[f"{nm_img}.y"] = "10"
                    for act in action_candidates:
                        try:
                            resp_try2 = self._request_form(act, method, payload_img)
                            ultimo_resp = resp_try2
                            if self._response_tem_resultado(resp_try2):
                                self._ultimas_variantes_busca = tentativas
                                return resp_try2
                        except Exception:
                            continue

                # tentativa 3: submit genérico (quando botão não tem name)
                payload_gen = dict(base_payload)
                payload_gen["submit"] = "Localizar"
                for act in action_candidates:
                    try:
                        resp_try3 = self._request_form(act, method, payload_gen)
                        ultimo_resp = resp_try3
                        if self._response_tem_resultado(resp_try3):
                            self._ultimas_variantes_busca = tentativas
                            return resp_try3
                    except Exception:
                        continue

        self._ultimas_variantes_busca = tentativas
        if ultimo_resp is None:
            raise RuntimeError("Falha ao submeter pesquisa na consulta pessoal.")
        return ultimo_resp

    def _fetch_detail_pages(self, response, cadastro: str) -> list[tuple[str, str]]:
        """
        Retorna páginas de detalhe da consulta pessoal, juntando:
        - ExibeFichaFuncionais
        - ExibeFichaPessoais
        - página de resultado atual (fallback)
        """
        cadastro_vals = [str(v).strip() for v in self._variantes_chapa(cadastro) if str(v).strip()]
        cadastro_vars = [normalize_ascii_upper(v) for v in cadastro_vals]
        seen_urls: set[str] = set()
        queue: list[str] = []
        out_pages: list[tuple[str, str]] = []

        def _add_cand(cands: list[tuple[int, str]], rank: int, base_url: str, u: str) -> None:
            uu = str(u or "").strip()
            if not uu:
                return
            if uu.lower().startswith("javascript:"):
                return
            cands.append((int(rank), urljoin(base_url, uu)))

        def _rank_link(href_u: str, txt_u: str) -> int:
            if ("EXIBEPEOPLE" in href_u) or ("EXIBEPEOLPLE" in href_u):
                return 0
            if "EXIBEFICHAFUNCIONAIS" in href_u:
                return 1
            if "EXIBEFICHAPESSOAIS" in href_u:
                return 2
            if "EXIBEFICHA" in href_u:
                return 3
            if any(v and ((v in href_u) or (v in txt_u)) for v in cadastro_vars):
                return 4
            if ("CONSULTAPESSOAL" in href_u) and href_u.endswith(".ASP"):
                return 8
            return 99

        def _enqueue_links(base_url: str, html_text: str) -> None:
            soup = BeautifulSoup(html_text, "html.parser")
            cands: list[tuple[int, str]] = []

            # Apenas resultado da pesquisa; fichas serão abertas a partir de links/acoes reais da pagina.
            _add_cand(cands, 0, base_url, "ExibePeople.asp")

            # meta refresh
            for m in soup.find_all("meta"):
                equiv = str(m.get("http-equiv") or "").strip().lower()
                content = str(m.get("content") or "")
                if equiv == "refresh" and "url=" in content.lower():
                    try:
                        u = content.split("url=", 1)[1].strip().strip("\"'")
                        _add_cand(cands, 2, base_url, u)
                    except Exception:
                        pass
            for a in soup.find_all("a", href=True):
                href = str(a.get("href") or "").strip()
                if not href:
                    continue
                href_u = normalize_ascii_upper(href)
                txt_u = normalize_ascii_upper(a.get_text(" ", strip=True))
                rank = _rank_link(href_u, txt_u)
                if (rank >= 99) and href_u.endswith(".ASP") and ("CONSULTAPESSOAL" in normalize_ascii_upper(base_url)):
                    rank = 20
                if rank < 99:
                    _add_cand(cands, rank, base_url, href)

            # onclick com redirecionamento para .asp
            for tag in soup.find_all(attrs={"onclick": True}):
                onclick = str(tag.get("onclick") or "")
                for m in re.findall(r"([A-Za-z0-9_./-]*Exibe[A-Za-z0-9_]*\.asp(?:\?[^'\"<>\s]+)?)", onclick, flags=re.I):
                    hu = normalize_ascii_upper(m)
                    _add_cand(cands, _rank_link(hu, ""), base_url, m)

            # scripts com links hardcoded
            script_txt = " ".join([str(sc.get_text(" ", strip=True) or "") for sc in soup.find_all("script")])
            html_join = " ".join([str(html_text or ""), script_txt])
            for m in re.findall(r"([A-Za-z0-9_./-]*Exibe[A-Za-z0-9_]*\.asp(?:\?[^'\"<>\s]+)?)", html_join, flags=re.I):
                hu = normalize_ascii_upper(m)
                _add_cand(cands, _rank_link(hu, ""), base_url, m)
            # fallback direto no HTML bruto (quando a pagina vem quebrada)
            for m in re.findall(r"(ExibeFicha(?:Funcionais|Pessoais)\.asp\?chapa=[0-9]+)", str(html_text or ""), flags=re.I):
                hu = normalize_ascii_upper(m)
                _add_cand(cands, _rank_link(hu, ""), base_url, m)

            cands.sort(key=lambda x: (x[0], x[1]))
            for _, url_abs in cands:
                if url_abs not in seen_urls and url_abs not in queue:
                    queue.append(url_abs)

        # inclui página atual e expande todos os links de ficha/opções internas
        base_url = str(response.url or "")
        html_text = self._response_text(response)
        out_pages.append((base_url, html_text))
        seen_urls.add(base_url)
        _enqueue_links(base_url, html_text)
        # se a pagina de resultado ja traz links de ficha, abre direto
        direct_links = re.findall(
            r"(ExibeFicha(?:Funcionais|Pessoais)\.asp\?chapa=[0-9]+)",
            str(html_text or ""),
            flags=re.I,
        )
        for m in direct_links[:6]:
            u = urljoin(base_url, m)
            if u in seen_urls:
                continue
            try:
                r0 = self.session.get(
                    u,
                    timeout=self._timeout_value(),
                    headers={
                        "Referer": base_url,
                        "Origin": CONSULTA_PESSOAL_ORIGIN,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                r0.raise_for_status()
                if not getattr(r0, "encoding", None):
                    r0.encoding = "latin-1"
                html0 = self._response_text(r0)
                out_pages.append((str(r0.url or u), html0))
                seen_urls.add(str(r0.url or u))
            except Exception:
                continue
        if not queue:
            # fallback: HTML quebrado pode impedir o parser de achar links.
            for m in re.findall(
                r"(ExibeFicha(?:Funcionais|Pessoais)\.asp\?chapa=[0-9]+)",
                str(html_text or ""),
                flags=re.I,
            ):
                u = urljoin(base_url, m)
                if u not in seen_urls and u not in queue:
                    queue.append(u)
            # tenta buscar diretamente as fichas encontradas no HTML bruto
            for u in list(queue)[:6]:
                if u in seen_urls:
                    continue
                try:
                    r0 = self.session.get(
                        u,
                        timeout=self._timeout_value(),
                        headers={
                            "Referer": base_url,
                            "Origin": CONSULTA_PESSOAL_ORIGIN,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    r0.raise_for_status()
                    if not getattr(r0, "encoding", None):
                        r0.encoding = "latin-1"
                    html0 = self._response_text(r0)
                    out_pages.append((str(r0.url or u), html0))
                    seen_urls.add(str(r0.url or u))
                except Exception:
                    continue

        # busca mais páginas para cobrir todas as opções internas da pessoa
        while queue and len(out_pages) < 30:
            u = queue.pop(0)
            if u in seen_urls:
                continue
            seen_urls.add(u)
            try:
                r = self.session.get(
                    u,
                    timeout=self._timeout_value(),
                    headers={
                        "Referer": base_url,
                        "Origin": CONSULTA_PESSOAL_ORIGIN,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                r.raise_for_status()
                if not getattr(r, "encoding", None):
                    r.encoding = "latin-1"
                html_r = self._response_text(r)
                out_pages.append((str(r.url or u), html_r))
                _enqueue_links(r.url, html_r)
            except Exception:
                continue

        # garante ao menos resultado base
        if not out_pages:
            out_pages.append((str(response.url or ""), html_text))

        # mantém Funcionais/Pessoais primeiro
        def _page_rank(item: tuple[str, str]) -> tuple[int, str]:
            u = normalize_ascii_upper(item[0])
            if "EXIBEPEOPLE" in u:
                return (0, item[0])
            if "EXIBEFICHAFUNCIONAIS" in u:
                return (1, item[0])
            if "EXIBEFICHAPESSOAIS" in u:
                return (2, item[0])
            if "FINDPEOPLE" in u:
                return (3, item[0])
            return (4, item[0])

        # dedup final por URL
        dedup = {}
        for u, html in out_pages:
            uu = str(u or "").strip()
            if uu not in dedup:
                dedup[uu] = html
        out_pages = sorted([(u, h) for u, h in dedup.items()], key=_page_rank)
        return out_pages

    def _consultar_via_playwright(self, cadastro: str) -> dict:
        cad = self._normalizar_numero_pessoal(cadastro)
        out = {
            "cadastro": cad,
            "ok": False,
            "mensagem": "",
            "url_final": "",
            "linhas": [],
            "print_path": "",
            "mensagem_print": "",
            "fichas": [],
            "foto_path": "",
            "fotos_por_chapa": {},
        }

        if self._playwright_bloqueado:
            msg_blk = self._playwright_bloqueio_msg or "Playwright/browser indisponivel."
            out["mensagem"] = f"Automacao de print indisponivel: {msg_blk}"
            out["mensagem_print"] = out["mensagem"]
            return out

        try:
            from playwright.sync_api import sync_playwright
        except Exception as e_imp:
            out["mensagem"] = f"Playwright indisponivel para captura: {e_imp}"
            out["mensagem_print"] = out["mensagem"]
            return out

        png_ok = self._temp_image_path(cad, kind="playwright_ok", suffix=".png")
        png_fail = self._temp_image_path(cad, kind="playwright_fail", suffix=".png")

        timeout_ms = (int(self.timeout_s) * 1000) if int(self.timeout_s) > 0 else 30_000
        short_timeout_ms = min(max(timeout_ms, 1000), 5000)

        def _launch_browser(pw):
            args = [
                "--disable-gpu",
                "--ignore-certificate-errors",
                "--allow-insecure-localhost",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
            executable = str(os.getenv("CONSULTA_PESSOAL_BROWSER_EXECUTABLE", "")).strip()
            if executable:
                return pw.chromium.launch(
                    executable_path=executable,
                    headless=True,
                    args=args,
                    timeout=timeout_ms,
                )

            preferred = str(os.getenv("CONSULTA_PESSOAL_BROWSER_CHANNEL", "msedge")).strip()
            channels = []
            if preferred:
                channels.append(preferred)
            for channel in ("msedge", "chrome", "chromium"):
                if channel not in channels:
                    channels.append(channel)

            errors: list[str] = []
            for channel in channels:
                try:
                    if channel == "chromium":
                        return pw.chromium.launch(headless=True, args=args, timeout=timeout_ms)
                    return pw.chromium.launch(channel=channel, headless=True, args=args, timeout=timeout_ms)
                except Exception as exc:
                    errors.append(f"{channel}: {self._clean_exc(exc)}")
            raise RuntimeError("Falha ao iniciar navegador Playwright: " + " | ".join(errors))

        def _iter_contexts(max_frames: int = 10):
            frames = []
            try:
                frames.append(page.main_frame)
                frames.extend(f for f in page.frames if f is not page.main_frame)
            except Exception:
                pass
            return frames[: max_frames + 1]

        def _elem_haystack(elem):
            def _attr(name: str) -> str:
                try:
                    return str(elem.get_attribute(name) or "")
                except Exception:
                    return ""

            attrs = " ".join(
                [
                    _attr("name"),
                    _attr("id"),
                    _attr("placeholder"),
                    _attr("aria-label"),
                    _attr("value"),
                    _attr("title"),
                    _attr("outerHTML"),
                ]
            )
            around = ""
            try:
                around = str(
                    elem.evaluate(
                        """
                        el => {
                            const p = el.closest('label,td,tr,div,form,body');
                            return p ? (p.innerText || '') : '';
                        }
                        """
                    )
                    or ""
                )
            except Exception:
                around = ""
            return normalize_ascii_upper(attrs + " " + around)

        def _elem_score(elem, hints: list[str]) -> int:
            txt = _elem_haystack(elem)
            return sum(1 for h in hints if normalize_ascii_upper(h) in txt)

        def _visible_text_inputs(frame):
            inputs = []
            try:
                candidates = frame.query_selector_all("input")
            except Exception:
                return inputs
            for item in candidates:
                try:
                    input_type = str(item.get_attribute("type") or "text").strip().lower()
                    if item.is_visible() and input_type in {"", "text", "number", "password"}:
                        inputs.append(item)
                except Exception:
                    continue
            return inputs

        def _find_best_context(hints: list[str]):
            best_ctx = page.main_frame
            best_score = -1
            for ctx in _iter_contexts():
                try:
                    inputs = _visible_text_inputs(ctx)
                    if len(inputs) < 2:
                        continue
                    score = 0
                    for i in inputs:
                        score += _elem_score(i, hints)
                    radios = ctx.query_selector_all("input[type='radio']")
                    score += (3 if radios else 0)
                    if score > best_score:
                        best_score = score
                        best_ctx = ctx
                except Exception:
                    continue
            return best_ctx

        def _find_button(frame, hints: list[str]):
            btns = []
            for selector in ("input[type='submit']", "input[type='button']", "button"):
                try:
                    btns.extend(frame.query_selector_all(selector))
                except Exception:
                    continue
            btns = [b for b in btns if b.is_visible()]
            if not btns:
                return None
            btns = sorted(
                btns,
                key=lambda b: sum(
                    1
                    for h in hints
                    if normalize_ascii_upper(h)
                    in normalize_ascii_upper(
                        str(b.text_content() or "") + " " + str(b.get_attribute("value") or "")
                    )
                ),
                reverse=True,
            )
            return btns[0]

        def _collect_page_texts():
            texts = []
            for ctx in _iter_contexts():
                try:
                    txt = str(ctx.evaluate("document.body ? (document.body.innerText || '') : ''") or "").strip()
                    if txt:
                        texts.append(txt)
                except Exception:
                    continue
            return texts

        def _wait_after_action() -> None:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=short_timeout_ms)
            except Exception:
                pass

        def _wait_until(predicate, detail: str) -> None:
            deadline = time.monotonic() + (timeout_ms / 1000)
            while True:
                try:
                    if predicate():
                        return
                except Exception:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError(detail)
                time.sleep(0.05)

        browser = None
        context = None
        page = None

        try:
            with sync_playwright() as pw:
                browser = _launch_browser(pw)
                context = browser.new_context(
                    ignore_https_errors=not self.verify_ssl,
                    viewport={"width": 1600, "height": 1100},
                )
                page = context.new_page()
                page.goto(self.base_url, wait_until="domcontentloaded", timeout=timeout_ms)

                login_ctx = _find_best_context(["senha", "password", "no pessoal", "pessoal", "user", "usuario", "login"])
                inputs_login = _visible_text_inputs(login_ctx)
                if len(inputs_login) < 2:
                    raise RuntimeError("Campos de login (No Pessoal/Senha) nao encontrados na tela.")

                pwd_candidates = [
                    i for i in inputs_login if str(i.get_attribute("type") or "").strip().lower() == "password"
                ]
                if not pwd_candidates:
                    pwd_candidates = sorted(
                        inputs_login,
                        key=lambda e: _elem_score(e, ["senha", "password", "pass", "pwd"]),
                        reverse=True,
                    )
                inp_pwd = pwd_candidates[0]

                user_candidates = [i for i in inputs_login if i != inp_pwd]
                user_candidates = sorted(
                    user_candidates,
                    key=lambda e: _elem_score(e, ["no pessoal", "pessoal", "numero", "no", "user", "usuario", "chapa"]),
                    reverse=True,
                )
                if not user_candidates:
                    raise RuntimeError("Campo de usuario (No Pessoal) nao encontrado na tela.")
                inp_user = user_candidates[0]

                inp_user.fill(self.user, timeout=short_timeout_ms)
                inp_pwd.fill(self.password, timeout=short_timeout_ms)

                btn_login = _find_button(login_ctx, ["prosseguir", "entrar", "login", "ok", "acessar"])
                if btn_login is not None:
                    btn_login.click(timeout=short_timeout_ms)
                else:
                    inp_pwd.press("Enter", timeout=short_timeout_ms)
                _wait_after_action()

                _wait_until(
                    lambda: any(len(_visible_text_inputs(frame)) > 0 for frame in _iter_contexts()),
                    "Campos pos-login nao encontrados na tela.",
                )

                search_ctx = _find_best_context(["localizar", "pesquisa", "chapa", "pessoal", "matricula"])
                radios = search_ctx.query_selector_all("input[type='radio']")
                for r in radios:
                    marker = _elem_haystack(r)
                    if ("PESSOAL" in marker) or ("CHAPA" in marker):
                        if not r.is_checked():
                            r.click(timeout=short_timeout_ms)
                        break

                search_inputs = [
                    i
                    for i in _visible_text_inputs(search_ctx)
                    if str(i.get_attribute("type") or "text").strip().lower() in {"", "text", "number"}
                ]
                if not search_inputs:
                    raise RuntimeError("Campo de pesquisa nao encontrado na tela de consulta.")
                search_inputs = sorted(
                    search_inputs,
                    key=lambda e: _elem_score(e, ["pessoal", "numero", "chapa", "cadastro", "matricula", "no"]),
                    reverse=True,
                )
                inp_search = search_inputs[0]
                inp_search.fill(cad, timeout=short_timeout_ms)

                btn_search = _find_button(search_ctx, ["localizar", "pesquisa", "buscar", "ok", "procurar"])
                if btn_search is not None:
                    btn_search.click(timeout=short_timeout_ms)
                else:
                    inp_search.press("Enter", timeout=short_timeout_ms)
                _wait_after_action()

                clicou_ficha = False
                for _ in range(3):
                    for ctx in _iter_contexts():
                        try:
                            links = ctx.query_selector_all("a")
                            for a in links:
                                marker = normalize_ascii_upper(
                                    str(a.get_attribute("href") or "") + " " + str(a.text_content() or "")
                                )
                                if ("EXIBEFICHA" in marker) or (cad in marker):
                                    a.click(timeout=short_timeout_ms)
                                    clicou_ficha = True
                                    _wait_after_action()
                                    break
                            if clicou_ficha:
                                break
                        except Exception:
                            continue
                    if clicou_ficha:
                        break

                _wait_until(
                    lambda: any(ctx.query_selector("body") is not None for ctx in _iter_contexts()),
                    "Corpo da pagina nao encontrado apos a busca.",
                )
                page.screenshot(path=str(png_ok))

                linhas = []
                for txt in _collect_page_texts():
                    linhas.extend([ln.strip() for ln in txt.splitlines() if str(ln).strip()])

                if not linhas and BeautifulSoup is not None:
                    linhas = self._extract_lines(page.content())

                unicas = []
                seen = set()
                for ln in linhas:
                    if ln not in seen:
                        unicas.append(ln)
                        seen.add(ln)

                out["ok"] = True
                out["url_final"] = str(page.url or "")
                out["linhas"] = unicas[:120]
                out["print_path"] = str(png_ok)
                out["mensagem"] = "Consulta pessoal carregada via automacao."
                out["mensagem_print"] = "Print da tela Consulta Pessoal capturado."
                return out
        except Exception as exc:
            try:
                if page is not None:
                    page.screenshot(path=str(png_fail))
                    out["print_path"] = str(png_fail)
            except Exception:
                pass
            msg_exc = self._clean_exc(exc)
            if ("Executable doesn't exist" in msg_exc) or ("browser executable" in msg_exc.lower()):
                self._playwright_bloqueado = True
                self._playwright_bloqueio_msg = "Navegador Playwright/Edge nao encontrado."
                out["mensagem"] = f"Falha ao automatizar consulta pessoal ({cad}): navegador Playwright/Edge nao encontrado."
            else:
                out["mensagem"] = f"Falha ao automatizar consulta pessoal ({cad}): {msg_exc}"
            out["mensagem_print"] = out["mensagem"]
            return out
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass

    def _extract_lines(self, html_text: str) -> list[str]:
        soup = BeautifulSoup(html_text, "html.parser")
        linhas: list[str] = []

        for tr in soup.find_all("tr"):
            cels = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            cels = [c for c in cels if c]
            if cels:
                linhas.append(self._normalizar_numero_pessoal_em_linha(" | ".join(cels)))

        if not linhas:
            txt = soup.get_text("\n", strip=True)
            linhas = [self._normalizar_numero_pessoal_em_linha(ln.strip()) for ln in txt.splitlines() if ln.strip()]

        limpas: list[str] = []
        for ln in linhas:
            ln2 = re.sub(r"\s+", " ", str(ln or "")).strip()
            if not ln2:
                continue
            ln_u = normalize_ascii_upper(ln2)
            if ln_u.startswith("JAVASCRIPT:"):
                continue
            if len(ln2) > 280 and (("HTTP://" in ln_u) or ("HTTPS://" in ln_u)):
                continue
            limpas.append(ln2)

        unicas: list[str] = []
        seen: set[str] = set()
        for ln in limpas:
            if ln not in seen:
                unicas.append(ln)
                seen.add(ln)
        return unicas[:160]

    def _extract_ficha_campos(self, html_text: str) -> list[tuple[str, str]]:
        if BeautifulSoup is None:
            return []
        try:
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception:
            return []

        def _norm_txt(v: str) -> str:
            return re.sub(r"\s+", " ", str(v or "")).strip(" \t\r\n:|-")

        def _norm_bg(tag) -> str:
            bg = str(tag.get("bgcolor") or "").strip().upper().replace("#", "")
            if bg:
                return bg
            style = normalize_ascii_upper(str(tag.get("style") or ""))
            m = re.search(r"BACKGROUND(?:-COLOR)?\s*:\s*#?([0-9A-F]{6})", style)
            return str(m.group(1) if m else "")

        def _ajustar_valor(chave: str, valor: str) -> str:
            k = normalize_ascii_upper(chave)
            v = _norm_txt(valor)
            if k in {"NUMERO PESSOAL", "NO PESSOAL"}:
                dig = re.sub(r"\D+", "", v)
                if dig.startswith("00") and (len(dig) > 2):
                    dig = dig[2:]
                if dig:
                    return dig
            return v

        def _eh_linha_menu(chave: str, valor: str) -> bool:
            kv = normalize_ascii_upper(f"{chave} {valor}")
            if not kv:
                return True
            tokens_menu = [
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
            ]
            if any(t in kv for t in tokens_menu):
                # ignora somente quando for claramente linha de navegacao
                keep_tokens = ["NUMERO PESSOAL", "NO PESSOAL", "NOME", "UNIDADE ORGANIZACIONAL"]
                if not any(t in kv for t in keep_tokens):
                    return True
            if kv in {"|", "||"}:
                return True
            return False

        campos: list[tuple[str, str]] = []
        seen: set[str] = set()
        headers_pending: list[str] | None = None

        for tr in soup.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue

            txts = [_norm_txt(c.get_text(" ", strip=True)) for c in cells]
            bgs = [_norm_bg(c) for c in cells]
            txts = [t for t in txts if t]
            if not txts:
                continue

            score_head = sum(1 for b in bgs if b == "D4E1F2")
            score_val = sum(1 for b in bgs if b == "F1EAD3")
            has_th = any(str(c.name or "").lower() == "th" for c in cells)
            is_header = has_th or (score_head > 0 and score_head >= score_val)
            is_value = (score_val > 0 and score_val >= score_head)

            if is_header:
                headers_pending = txts
                continue

            if headers_pending and is_value:
                for i, rot in enumerate(headers_pending):
                    chave = _norm_txt(rot)
                    if not chave:
                        continue
                    val = _ajustar_valor(chave, _norm_txt(txts[i] if i < len(txts) else ""))
                    if not val:
                        continue
                    if _eh_linha_menu(chave, val):
                        continue
                    ksig = f"{normalize_ascii_upper(chave)}|{normalize_ascii_upper(val)}"
                    if ksig in seen:
                        continue
                    campos.append((chave, val))
                    seen.add(ksig)
                headers_pending = None
                continue

            if (len(txts) >= 2):
                chave = _norm_txt(txts[0])
                # Em tabelas matriciais (ex.: Headcount/GPTW), preserva todas as colunas apos a primeira.
                val_raw = " | ".join([_norm_txt(x) for x in txts[1:] if _norm_txt(x)])
                val = _ajustar_valor(chave, val_raw)
                if chave and val:
                    if _eh_linha_menu(chave, val):
                        continue
                    ksig = f"{normalize_ascii_upper(chave)}|{normalize_ascii_upper(val)}"
                    if ksig not in seen:
                        campos.append((chave, val))
                        seen.add(ksig)

        if not campos:
            linhas = self._extract_lines(html_text)
            for ln in linhas:
                if "|" not in ln:
                    continue
                parts = [p.strip() for p in str(ln).split("|")]
                if len(parts) < 2:
                    continue
                chave = _norm_txt(parts[0])
                val_raw = " | ".join([_norm_txt(p) for p in parts[1:] if _norm_txt(p)])
                val = _ajustar_valor(chave, val_raw)
                if not chave or not val:
                    continue
                if _eh_linha_menu(chave, val):
                    continue
                ksig = f"{normalize_ascii_upper(chave)}|{normalize_ascii_upper(val)}"
                if ksig not in seen:
                    campos.append((chave, val))
                    seen.add(ksig)

        return campos[:140]

    def _baixar_foto_ficha(self, html_text: str, page_url: str, cadastro: str) -> str:
        if (self.session is None) or (BeautifulSoup is None):
            return ""
        try:
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception:
            return ""

        img_src = ""
        for img in soup.find_all("img", src=True):
            src = str(img.get("src") or "").strip()
            if not src:
                continue
            src_u = normalize_ascii_upper(src)
            if ("IMAGEMASP.ASP" in src_u) or ("IMAGEM" in src_u):
                img_src = src
                break
        if not img_src:
            return ""

        img_url = urljoin(str(page_url or self.base_url), img_src)
        try:
            r = self.session.get(
                img_url,
                timeout=self._timeout_value(),
                headers={
                    "Referer": str(page_url or self.base_url),
                    "Origin": CONSULTA_PESSOAL_ORIGIN,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
            r.raise_for_status()
            blob = r.content or b""
            if len(blob) < 100:
                return ""
            if blob[:1] == b"<":
                return ""

            ctype = normalize_ascii_upper(str(r.headers.get("content-type") or ""))
            ext = ".jpg"
            if "PNG" in ctype:
                ext = ".png"
            elif "GIF" in ctype:
                ext = ".gif"
            elif "BMP" in ctype:
                ext = ".bmp"

            cad_key = self._normalizar_chapa_key(str(cadastro or "").strip())
            if not cad_key:
                cad_key = self._normalizar_chapa_key(self._extrair_chapa_de_url(page_url))
            if not cad_key:
                cad_key = "sem_chapa"
            out_img = self._temp_image_path(cad_key, kind="foto", suffix=ext)
            out_img.write_bytes(blob)
            return str(out_img)
        except Exception:
            return ""

    def _form_to_request(self, current_url: str, form):
        action = urljoin(current_url, str(form.get("action") or current_url))
        method = str(form.get("method") or "post").strip().lower()
        payload: dict[str, str] = {}

        for inp in form.find_all("input"):
            name = str(inp.get("name") or "").strip()
            if not name:
                name = str(inp.get("id") or "").strip()
            if not name:
                continue
            inp_type = str(inp.get("type") or "text").strip().lower()
            if inp_type in {"submit", "button", "image"}:
                continue
            payload[name] = str(inp.get("value") or "")

        for sel in form.find_all("select"):
            name = str(sel.get("name") or "").strip()
            if not name:
                continue
            opt = sel.find("option", selected=True) or sel.find("option")
            payload[name] = str(opt.get("value") if opt is not None else "")

        for ta in form.find_all("textarea"):
            name = str(ta.get("name") or "").strip()
            if not name:
                continue
            payload[name] = ta.get_text("", strip=False)

        return action, method, payload

    def _find_input_name(self, form, keywords: list[str], preferred_types: set[str] | None = None) -> str | None:
        scored: list[tuple[int, str]] = []
        pref = set(preferred_types or [])

        for inp in form.find_all("input"):
            name = str(inp.get("name") or "").strip()
            if not name:
                continue
            inp_type = str(inp.get("type") or "text").strip().lower()
            if pref and (inp_type not in pref):
                continue

            hay = normalize_ascii_upper(
                " ".join(
                    [
                        name,
                        str(inp.get("id") or ""),
                        str(inp.get("placeholder") or ""),
                        str(inp.get("aria-label") or ""),
                    ]
                )
            )
            score = 0
            for k in keywords:
                if normalize_ascii_upper(k) in hay:
                    score += 1
            if score > 0:
                scored.append((score, name))

        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _request_form(self, action: str, method: str, payload: dict[str, str]):
        headers = {
            "Referer": action,
            "Origin": CONSULTA_PESSOAL_ORIGIN,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if method == "get":
            resp = self.session.get(action, params=payload, timeout=self._timeout_value(), headers=headers)
        else:
            resp = self.session.post(action, data=payload, timeout=self._timeout_value(), headers=headers)
        if not getattr(resp, "encoding", None):
            resp.encoding = "latin-1"
        resp.raise_for_status()
        return resp

    def _response_text(self, response) -> str:
        try:
            txt = response.text or ""
        except Exception:
            txt = ""
        if len(txt.strip()) >= 200:
            return txt
        try:
            raw = response.content or b""
        except Exception:
            raw = b""
        if raw:
            try:
                return raw.decode("latin-1", errors="ignore")
            except Exception:
                return txt
        return txt


def setup_plot_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "font.size": 11,
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
        }
    )


def cleanup_saida(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("*"):
        if p.is_file() and p.suffix.lower() in {".csv", ".pdf", ".parquet"}:
            p.unlink()


def cleanup_consulta_pessoal_prints_dirs(base_dir: Path, script_dir: Path) -> None:
    """
    Remove sobras antigas de imagens da consulta pessoal.
    Mantem apenas o que for estritamente necessario em memoria durante a execução.
    """
    dirs = [
        script_dir / "_tmp_consulta_pessoal_prints",
        script_dir / "outputs_irregularidades" / "consulta_pessoal_prints",
        Path.cwd() / "outputs_irregularidades" / "consulta_pessoal_prints",
        base_dir / "outputs_irregularidades" / "consulta_pessoal_prints",
    ]
    seen: set[str] = set()
    for d in dirs:
        d_key = str(d.resolve()) if d.exists() else str(d)
        if d_key in seen:
            continue
        seen.add(d_key)
        if not d.exists() or (not d.is_dir()):
            continue
        for p in d.glob("consulta_pessoal_*"):
            if (not p.is_file()) or (p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".bmp"}):
                continue
            try:
                p.unlink()
            except Exception:
                pass
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except Exception:
            pass


def cleanup_pastas_legadas_vazias(base_dir: Path, out_dir_oficial: Path) -> None:
    """
    Remove pastas de saida legadas que ficam perdidas, apenas quando estiverem vazias.
    """
    legado_saida = base_dir / "irregularidade_999_como_trajeto" / "saidas"
    legado_raiz = base_dir / "irregularidade_999_como_trajeto"

    try:
        if legado_saida.resolve() == out_dir_oficial.resolve():
            return
    except Exception:
        pass

    for d in [legado_saida, legado_raiz]:
        try:
            if d.exists() and d.is_dir() and (not any(d.iterdir())):
                d.rmdir()
        except Exception:
            pass


def cleanup_consulta_pessoal_imagens_temporarias(consulta_info: dict | None) -> None:
    """
    Remove imagens temporarias de consulta pessoal apos inclusão no PDF.
    """
    if not isinstance(consulta_info, dict):
        return

    raw_paths: list[str] = []
    for key in ["print_path", "foto_path"]:
        raw_paths.append(str(consulta_info.get(key) or "").strip())

    fotos_por_chapa = consulta_info.get("fotos_por_chapa") or {}
    if isinstance(fotos_por_chapa, dict):
        for _, v in fotos_por_chapa.items():
            raw_paths.append(str(v or "").strip())

    paths: list[Path] = []
    seen_paths: set[str] = set()
    for raw in raw_paths:
        if not raw:
            continue
        try:
            p = Path(raw)
        except Exception:
            continue
        key = str(p)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        paths.append(p)

    for p in paths:
        if (not p.exists()) or (not p.is_file()):
            continue
        nm = normalize_ascii_upper(p.name)
        if "CONSULTA_PESSOAL" not in nm:
            continue
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".bmp"}:
            continue
        try:
            p.unlink()
        except Exception:
            pass

    for p in paths:
        try:
            parent = p.parent
            if parent.exists() and parent.is_dir() and (not any(parent.iterdir())):
                parent.rmdir()
        except Exception:
            pass

    consulta_info["print_path"] = ""
    consulta_info["foto_path"] = ""
    if isinstance(consulta_info.get("fotos_por_chapa"), dict):
        consulta_info["fotos_por_chapa"] = {}


def annotate_bar(
    ax,
    values,
    fs: int = 8,
    fmt: str = "{:.0f}",
    suffix: str = "",
    boxed: bool = True,
) -> None:
    for i, v in enumerate(values):
        try:
            v_num = float(v)
        except Exception:
            continue
        if v_num <= 0:
            continue
        kwargs = {}
        if boxed:
            kwargs["color"] = "white"
            kwargs["bbox"] = {
                "boxstyle": "round,pad=0.18",
                "facecolor": COR_DESTAQUE_NUMEROS,
                "edgecolor": COR_DESTAQUE_NUMEROS,
                "alpha": 0.95,
            }
        ax.text(i, v_num, f"{fmt.format(v_num)}{suffix}", ha="center", va="bottom", fontsize=fs, **kwargs)


def remover_cadastros_area_bv(df: pd.DataFrame, col_area: str | None) -> pd.DataFrame:
    if df.empty or not col_area or col_area not in df.columns:
        return df

    area_norm = safe_str_series(df[col_area]).str.upper()
    cadastros_bv = set(safe_str_series(df.loc[area_norm.str.startswith("B-V"), "cadastro"]))
    if not cadastros_bv:
        return df

    return df.loc[~safe_str_series(df["cadastro"]).isin(cadastros_bv)].copy()


def build_is_999(df: pd.DataFrame) -> pd.Series:
    masks: list[pd.Series] = []

    col_flag_999 = pick_col(["999", "is_999", "flag_999"], list(df.columns))
    if col_flag_999:
        src = df[col_flag_999]
        if pd.api.types.is_bool_dtype(src):
            masks.append(src.fillna(False).astype(bool))
        else:
            src_num = pd.to_numeric(src, errors="coerce")
            src_txt = safe_str_series(src).str.upper()
            masks.append(src_num.eq(999) | src_num.eq(1) | src_txt.isin({"TRUE", "T", "SIM", "S", "Y", "YES"}))

    if "planta" in df.columns:
        masks.append(pd.to_numeric(df["planta"], errors="coerce").eq(999))

    # fallback legado: so usa coletor quando nao ha outra sinalizacao de 999
    if (not masks) and ("coletor" in df.columns):
        masks.append(pd.to_numeric(df["coletor"], errors="coerce").eq(999))

    if not masks:
        return pd.Series(False, index=df.index)

    out = masks[0].copy()
    for m in masks[1:]:
        out = out | m
    return out


def selecionar_999_sobrando_por_paridade(events: pd.DataFrame, lado: str) -> pd.DataFrame:
    if events.empty:
        return events.iloc[0:0].copy()

    ev = events.dropna(subset=["_dt_evento"]).sort_values("_dt_evento", kind="mergesort").copy()
    if ev.empty:
        return ev

    # evita duplicidade de batidas no mesmo timestamp inflar paridade
    ev = ev.drop_duplicates(subset=["_dt_evento"], keep="last")
    if len(ev) % 2 == 0:
        return ev.iloc[0:0].copy()

    if lado == "before":
        return ev.tail(1).copy()
    return ev.head(1).copy()


def add_event_flags(df: pd.DataFrame, desc_col: str | None) -> pd.DataFrame:
    d = df.copy()

    if desc_col and desc_col in d.columns:
        desc = safe_str_series(d[desc_col])
        d["_is_port"] = desc.str.contains(r"PORTARIA|PORT", case=False, na=False, regex=True)
        d["_is_ponto"] = desc.str.contains(r"PONTO|MARCA", case=False, na=False, regex=True)
    else:
        d["_is_port"] = False
        d["_is_ponto"] = False

    d["_is_999"] = build_is_999(d)
    return d


def manter_somente_eventos_relevantes(df: pd.DataFrame, desc_col: str | None) -> pd.DataFrame:
    if df.empty:
        return df

    d = add_event_flags(df, desc_col)
    d = d.loc[d["_is_port"] | d["_is_ponto"] | d["_is_999"]].copy()
    return d


def remover_dias_com_mais_de_uma_planta(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "planta" not in df.columns:
        return df

    d = df.copy()
    dia_col = "_dia_rastreio" if "_dia_rastreio" in d.columns else "dia_operacional"
    if dia_col not in d.columns:
        return d

    planta_num = pd.to_numeric(d["planta"], errors="coerce")
    d["_planta_num"] = planta_num

    fisicas = d.loc[d["_planta_num"].notna() & (~d["_planta_num"].eq(999))].copy()
    if fisicas.empty:
        return d.drop(columns=["_planta_num"], errors="ignore")

    resumo = (
        fisicas.groupby(["cadastro", dia_col], as_index=False)["_planta_num"]
        .nunique()
        .rename(columns={"_planta_num": "qtd_plantas_fisicas"})
    )

    keys_ok = resumo.loc[resumo["qtd_plantas_fisicas"] <= 1, ["cadastro", dia_col]].copy()

    # dias sem planta física também podem permanecer
    keys_all = d[["cadastro", dia_col]].drop_duplicates()
    keys_final = keys_all.merge(keys_ok.assign(_ok=True), on=["cadastro", dia_col], how="left")
    keys_final["_ok"] = keys_final["_ok"].eq(True)

    # mantém dias que não apareceram no resumo (ou seja, 0 planta física) ou que têm 1 planta física
    keys_sem_resumo = keys_all.merge(
        resumo[["cadastro", dia_col]].assign(_tem_resumo=True),
        on=["cadastro", dia_col],
        how="left",
    )
    mask_sem_resumo = keys_sem_resumo["_tem_resumo"].isna()

    keys_validas = pd.concat(
        [
            keys_ok,
            keys_sem_resumo.loc[mask_sem_resumo, ["cadastro", dia_col]],
        ],
        ignore_index=True,
    ).drop_duplicates()

    d = d.merge(keys_validas.assign(_mantem=True), on=["cadastro", dia_col], how="inner")
    return d.drop(columns=["_planta_num"], errors="ignore")

def selecionar_dias_validos_999_trajeto(
    df: pd.DataFrame,
    desc_col: str | None,
    janela_999_horas: float = 6.0,
    max_horas_fabrica_dia: float = 1.0,
    exigir_ponto_no_ciclo: bool = True,
) -> pd.DataFrame:
    """
    Alinha a logica do script com o bloco 999 como trajeto do notebook
    "Criando Base das Irregularidades":
    - considera eventos ponto/portaria (sem ALA);
    - jornada diaria = primeira entrada + ultima saida (E/S) por dia;
    - associa 999 na janela antes/depois da jornada;
    - restricoes: horas_fabrica_dia < max_horas_fabrica_dia e no maximo 1 planta fisica/dia;
    - classifica situacao: Antes / Depois / Antes e Depois.

    Regra de ponto para evento 999:
    - exigir_ponto_no_ciclo=True: 999 deve ocorrer em evento de ponto;
    - exigir_ponto_no_ciclo=False: 999 pode ocorrer em ponto ou portaria.
    """
    if df.empty:
        return df

    missing_cols = [c for c in ["cadastro", "_dt_evento"] if c not in df.columns]
    if missing_cols:
        raise KeyError(
            "Colunas obrigatorias ausentes em selecionar_dias_validos_999_trajeto: "
            + ", ".join(missing_cols)
        )

    janela_999 = pd.Timedelta(hours=max(float(janela_999_horas), 0.0))
    max_horas = max(float(max_horas_fabrica_dia), 0.0)
    max_plantas_dia = int(globals().get("max_plantas_por_dia_999_trajeto", 1))
    re_ala = globals().get("regex_ala_999_trajeto", r"(?i)\bALA(?:S)?\b")

    d = df.copy()
    if "_dia_rastreio" not in d.columns:
        d["_dia_rastreio"] = calcular_dia_rastreio(d["_dt_evento"])
    d = d.loc[d["_dt_evento"].notna() & d["_dia_rastreio"].notna()].copy()
    d = d.sort_values(["cadastro", "_dia_rastreio", "_dt_evento"], kind="mergesort")
    if d.empty:
        return d

    if desc_col and (desc_col in d.columns):
        desc_norm = safe_str_series(d[desc_col]).map(normalize_ascii_upper)
    else:
        desc_norm = pd.Series("", index=d.index, dtype="string")

    if "Ponto" in d.columns:
        is_ponto = d["Ponto"].fillna(False).astype(bool)
    else:
        is_ponto = desc_norm.str.contains(r"PONTO|MARCA", case=False, na=False, regex=True)

    if "Portaria" in d.columns:
        is_port = d["Portaria"].fillna(False).astype(bool)
    else:
        is_port = desc_norm.str.contains(r"PORTARIA|PORT", case=False, na=False, regex=True)

    mask_ala = desc_norm.str.contains(re_ala, case=False, na=False, regex=True)
    mask_evt = (is_ponto | is_port) & (~mask_ala)

    base_evt = d.loc[mask_evt].copy()
    if base_evt.empty:
        return d.head(0).copy()

    base_evt["_is_ponto"] = is_ponto.loc[base_evt.index].astype(bool).to_numpy()
    base_evt["_is_port"] = is_port.loc[base_evt.index].astype(bool).to_numpy()
    base_evt["_dir_norm"] = base_evt["dir"].map(normalize_dir_value) if "dir" in base_evt.columns else ""

    planta_num = (
        pd.to_numeric(base_evt["planta"], errors="coerce")
        if "planta" in base_evt.columns
        else pd.Series(np.nan, index=base_evt.index, dtype="float64")
    )
    if "999" in base_evt.columns:
        src_999 = base_evt["999"]
        if pd.api.types.is_bool_dtype(src_999):
            is_999_col = src_999.fillna(False).astype(bool)
        else:
            s_num = pd.to_numeric(src_999, errors="coerce")
            s_txt = safe_str_series(src_999).str.upper()
            is_999_col = s_num.eq(999) | s_num.eq(1) | s_txt.isin({"TRUE", "T", "SIM", "S", "Y", "YES"})
        base_evt["_is_999"] = is_999_col | planta_num.eq(999)
    else:
        base_evt["_is_999"] = planta_num.eq(999)
    base_evt["_planta_num"] = planta_num

    port = base_evt.loc[
        # Jornada E->S deve vir de eventos de portaria "fisicos".
        # Excluir 999 evita que o proprio trajeto 999 vire referencia de entrada/saida.
        base_evt["_is_port"] & (~base_evt["_is_999"]) & base_evt["_dir_norm"].isin(["E", "S"]),
        ["cadastro", "_dia_rastreio", "_dt_evento", "_dir_norm"],
    ].copy(deep=False)

    ent = (
        port.loc[port["_dir_norm"].eq("E")]
        .groupby(["cadastro", "_dia_rastreio"], sort=False)["_dt_evento"]
        .min()
        .rename("t_ent")
        .reset_index()
    )
    sai = (
        port.loc[port["_dir_norm"].eq("S")]
        .groupby(["cadastro", "_dia_rastreio"], sort=False)["_dt_evento"]
        .max()
        .rename("t_sai")
        .reset_index()
    )

    jornada = ent.merge(sai, on=["cadastro", "_dia_rastreio"], how="inner")
    jornada["horas_fabrica_dia"] = (
        (jornada["t_sai"] - jornada["t_ent"]) / pd.Timedelta(hours=1)
    ).where(jornada["t_sai"] >= jornada["t_ent"], np.nan)

    plantas_dia = base_evt.loc[
        (~base_evt["_is_999"]) & base_evt["_planta_num"].notna(),
        ["cadastro", "_dia_rastreio", "_planta_num"],
    ].copy(deep=False)

    if plantas_dia.empty:
        agg_plantas = pd.DataFrame(columns=["cadastro", "_dia_rastreio", "n_plantas_dia", "planta_referencia"])
    else:
        agg_plantas = (
            plantas_dia.groupby(["cadastro", "_dia_rastreio"], sort=False)["_planta_num"]
            .agg(n_plantas_dia="nunique")
            .reset_index()
        )
        planta_ref = (
            plantas_dia.groupby(["cadastro", "_dia_rastreio", "_planta_num"], sort=False)
            .size()
            .rename("n")
            .reset_index()
            .sort_values(
                ["cadastro", "_dia_rastreio", "n", "_planta_num"],
                ascending=[True, True, False, True],
                kind="mergesort",
            )
            .drop_duplicates(subset=["cadastro", "_dia_rastreio"], keep="first")
        )
        agg_plantas = agg_plantas.merge(
            planta_ref[["cadastro", "_dia_rastreio", "_planta_num"]].rename(columns={"_planta_num": "planta_referencia"}),
            on=["cadastro", "_dia_rastreio"],
            how="left",
        )

    if exigir_ponto_no_ciclo:
        mask_999_evento = base_evt["_is_999"] & base_evt["_is_ponto"]
    else:
        mask_999_evento = base_evt["_is_999"] & (base_evt["_is_ponto"] | base_evt["_is_port"])

    ev_999 = base_evt.loc[mask_999_evento, ["cadastro", "_dia_rastreio", "_dt_evento"]].copy(deep=False)

    if jornada.empty or ev_999.empty:
        return d.head(0).copy()

    ev = ev_999.merge(jornada, on=["cadastro", "_dia_rastreio"], how="inner")

    def _paridade_por_grupo(df_side: pd.DataFrame, lado: str) -> pd.DataFrame:
        if df_side.empty:
            return df_side.head(0).copy()
        chunks: list[pd.DataFrame] = []
        for _, grp in df_side.groupby(["cadastro", "_dia_rastreio"], sort=False):
            sel = selecionar_999_sobrando_por_paridade(grp, lado)
            if not sel.empty:
                chunks.append(sel)
        if not chunks:
            return df_side.head(0).copy()
        return pd.concat(chunks, ignore_index=True)

    ev_before_all = ev.loc[ev["_dt_evento"] < ev["t_ent"], ["cadastro", "_dia_rastreio", "_dt_evento", "t_ent"]].copy()
    if ev_before_all.empty:
        before = ev_before_all.head(0).assign(t_999_before=pd.NaT)[["cadastro", "_dia_rastreio", "t_999_before"]]
    else:
        before = _paridade_por_grupo(ev_before_all, "before")
        before = before.loc[
            before["_dt_evento"] >= (before["t_ent"] - janela_999),
            ["cadastro", "_dia_rastreio", "_dt_evento"],
        ].rename(columns={"_dt_evento": "t_999_before"})

    ev_after_all = ev.loc[ev["_dt_evento"] > ev["t_sai"], ["cadastro", "_dia_rastreio", "_dt_evento", "t_sai"]].copy()
    if ev_after_all.empty:
        after = ev_after_all.head(0).assign(t_999_after=pd.NaT)[["cadastro", "_dia_rastreio", "t_999_after"]]
    else:
        after = _paridade_por_grupo(ev_after_all, "after")
        after = after.loc[
            after["_dt_evento"] <= (after["t_sai"] + janela_999),
            ["cadastro", "_dia_rastreio", "_dt_evento"],
        ].rename(columns={"_dt_evento": "t_999_after"})

    traj_dia = (
        jornada.merge(before, on=["cadastro", "_dia_rastreio"], how="left")
        .merge(after, on=["cadastro", "_dia_rastreio"], how="left")
    )
    traj_dia["h_before"] = (
        (traj_dia["t_ent"] - traj_dia["t_999_before"]) / pd.Timedelta(hours=1)
    ).where(traj_dia["t_999_before"].notna(), 0.0).clip(lower=0.0)
    traj_dia["h_after"] = (
        (traj_dia["t_999_after"] - traj_dia["t_sai"]) / pd.Timedelta(hours=1)
    ).where(traj_dia["t_999_after"].notna(), 0.0).clip(lower=0.0)
    traj_dia["horas_trajeto_999_dia"] = traj_dia["h_before"].fillna(0.0) + traj_dia["h_after"].fillna(0.0)
    traj_dia["situacao_trajeto_999"] = np.select(
        [
            traj_dia["h_before"].gt(0) & traj_dia["h_after"].gt(0),
            traj_dia["h_before"].gt(0) & (~traj_dia["h_after"].gt(0)),
            (~traj_dia["h_before"].gt(0)) & traj_dia["h_after"].gt(0),
        ],
        ["Antes e Depois", "Antes", "Depois"],
        default="",
    )

    traj_dia = traj_dia.merge(agg_plantas, on=["cadastro", "_dia_rastreio"], how="left")
    traj_dia["n_plantas_dia"] = traj_dia["n_plantas_dia"].fillna(0).astype(int)
    traj_dia["planta_referencia"] = pd.to_numeric(traj_dia["planta_referencia"], errors="coerce")

    traj_dia = traj_dia.loc[traj_dia["n_plantas_dia"].le(max_plantas_dia)].copy()
    traj_dia = traj_dia.loc[traj_dia["horas_fabrica_dia"].notna() & traj_dia["horas_fabrica_dia"].lt(max_horas)].copy()
    traj_dia = traj_dia.loc[traj_dia["horas_trajeto_999_dia"].fillna(0.0).gt(0)].copy()
    if traj_dia.empty:
        return d.head(0).copy()

    cols_traj = [
        "cadastro",
        "_dia_rastreio",
        "t_ent",
        "t_sai",
        "t_999_before",
        "t_999_after",
        "h_before",
        "h_after",
        "horas_trajeto_999_dia",
        "situacao_trajeto_999",
        "n_plantas_dia",
        "planta_referencia",
        "horas_fabrica_dia",
    ]
    out = base_evt.merge(traj_dia[cols_traj], on=["cadastro", "_dia_rastreio"], how="inner")
    out = out.sort_values(["cadastro", "_dia_rastreio", "_dt_evento"], kind="mergesort")

    out["_trajeto_occ_id"] = (
        out["cadastro"].astype(str).str.strip()
        + "|"
        + pd.to_datetime(out["_dia_rastreio"], errors="coerce").dt.strftime("%Y-%m-%d")
    )
    out["trajeto_999_h_before"] = pd.to_numeric(out["h_before"], errors="coerce").fillna(0.0)
    out["trajeto_999_h_after"] = pd.to_numeric(out["h_after"], errors="coerce").fillna(0.0)
    out["trajeto_999_h_total"] = pd.to_numeric(out["horas_trajeto_999_dia"], errors="coerce").fillna(0.0)
    out["trajeto_999_situacao"] = safe_str_series(out["situacao_trajeto_999"])
    out["dia_operacional"] = out["_dia_rastreio"]

    return out


def _build_df_validacao_999(rows: list[dict[str, object]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["_dt_evento"] = pd.to_datetime(df["_dt_evento"], errors="coerce")
    df["_dia_rastreio"] = calcular_dia_rastreio(df["_dt_evento"])
    return df


def validar_logica_999_trajeto() -> list[str]:
    """
    Executa cenarios sinteticos para validar regras centrais de 999 como trajeto.
    Lanca AssertionError se alguma regra esperada falhar.
    """
    checks_ok: list[str] = []

    cenario_antes = _build_df_validacao_999(
        [
            {"cadastro": "A", "_dt_evento": "2026-01-01 07:50:00", "dir": "E", "planta": 999, "descricao_coletor": "PONTO 999"},
            {"cadastro": "A", "_dt_evento": "2026-01-01 08:00:00", "dir": "E", "planta": 1, "descricao_coletor": "PORTARIA ENTRADA"},
            {"cadastro": "A", "_dt_evento": "2026-01-01 08:30:00", "dir": "S", "planta": 1, "descricao_coletor": "PORTARIA SAIDA"},
        ]
    )
    out_antes = selecionar_dias_validos_999_trajeto(
        cenario_antes,
        "descricao_coletor",
        janela_999_horas=2.0,
        max_horas_fabrica_dia=1.0,
        exigir_ponto_no_ciclo=True,
    )
    sit_antes = set(safe_str_series(out_antes.get("situacao_trajeto_999", pd.Series(dtype="string"))).tolist())
    sit_antes.discard("")
    if out_antes.empty or sit_antes != {"Antes"}:
        raise AssertionError(f"Cenario 'Antes' falhou. situacoes={sorted(sit_antes)}")
    checks_ok.append("Classificacao 'Antes' validada.")

    cenario_ambos = _build_df_validacao_999(
        [
            {"cadastro": "B", "_dt_evento": "2026-01-01 07:50:00", "dir": "E", "planta": 999, "descricao_coletor": "PONTO 999"},
            {"cadastro": "B", "_dt_evento": "2026-01-01 08:00:00", "dir": "E", "planta": 1, "descricao_coletor": "PORTARIA ENTRADA"},
            {"cadastro": "B", "_dt_evento": "2026-01-01 08:30:00", "dir": "S", "planta": 1, "descricao_coletor": "PORTARIA SAIDA"},
            {"cadastro": "B", "_dt_evento": "2026-01-01 08:45:00", "dir": "S", "planta": 999, "descricao_coletor": "PONTO 999"},
        ]
    )
    out_ambos = selecionar_dias_validos_999_trajeto(
        cenario_ambos,
        "descricao_coletor",
        janela_999_horas=2.0,
        max_horas_fabrica_dia=1.0,
        exigir_ponto_no_ciclo=True,
    )
    sit_ambos = set(safe_str_series(out_ambos.get("situacao_trajeto_999", pd.Series(dtype="string"))).tolist())
    sit_ambos.discard("")
    if out_ambos.empty or sit_ambos != {"Antes e Depois"}:
        raise AssertionError(f"Cenario 'Antes e Depois' falhou. situacoes={sorted(sit_ambos)}")
    checks_ok.append("Classificacao 'Antes e Depois' validada.")

    cenario_fora_janela = _build_df_validacao_999(
        [
            {"cadastro": "C", "_dt_evento": "2026-01-01 01:00:00", "dir": "E", "planta": 999, "descricao_coletor": "PONTO 999"},
            {"cadastro": "C", "_dt_evento": "2026-01-01 08:00:00", "dir": "E", "planta": 1, "descricao_coletor": "PORTARIA ENTRADA"},
            {"cadastro": "C", "_dt_evento": "2026-01-01 08:30:00", "dir": "S", "planta": 1, "descricao_coletor": "PORTARIA SAIDA"},
        ]
    )
    out_fora = selecionar_dias_validos_999_trajeto(
        cenario_fora_janela,
        "descricao_coletor",
        janela_999_horas=2.0,
        max_horas_fabrica_dia=1.0,
        exigir_ponto_no_ciclo=True,
    )
    if not out_fora.empty:
        raise AssertionError("Cenario de 999 fora da janela deveria ser descartado.")
    checks_ok.append("Regra de janela 999 validada.")

    cenario_ponto_flag = _build_df_validacao_999(
        [
            {"cadastro": "D", "_dt_evento": "2026-01-01 07:50:00", "dir": "E", "planta": 999, "descricao_coletor": "PORTARIA 999"},
            {"cadastro": "D", "_dt_evento": "2026-01-01 08:00:00", "dir": "E", "planta": 1, "descricao_coletor": "PORTARIA ENTRADA"},
            {"cadastro": "D", "_dt_evento": "2026-01-01 08:30:00", "dir": "S", "planta": 1, "descricao_coletor": "PORTARIA SAIDA"},
        ]
    )
    out_exige = selecionar_dias_validos_999_trajeto(
        cenario_ponto_flag,
        "descricao_coletor",
        janela_999_horas=2.0,
        max_horas_fabrica_dia=1.0,
        exigir_ponto_no_ciclo=True,
    )
    out_nao_exige = selecionar_dias_validos_999_trajeto(
        cenario_ponto_flag,
        "descricao_coletor",
        janela_999_horas=2.0,
        max_horas_fabrica_dia=1.0,
        exigir_ponto_no_ciclo=False,
    )
    if (not out_exige.empty) or out_nao_exige.empty:
        raise AssertionError("Flag exigir_ponto_no_ciclo nao esta alterando o comportamento como esperado.")
    checks_ok.append("Flag exigir_ponto_no_ciclo validada.")

    cenario_horas_fabrica = _build_df_validacao_999(
        [
            {"cadastro": "E", "_dt_evento": "2026-01-01 07:50:00", "dir": "E", "planta": 999, "descricao_coletor": "PONTO 999"},
            {"cadastro": "E", "_dt_evento": "2026-01-01 08:00:00", "dir": "E", "planta": 1, "descricao_coletor": "PORTARIA ENTRADA"},
            {"cadastro": "E", "_dt_evento": "2026-01-01 10:30:00", "dir": "S", "planta": 1, "descricao_coletor": "PORTARIA SAIDA"},
        ]
    )
    out_horas = selecionar_dias_validos_999_trajeto(
        cenario_horas_fabrica,
        "descricao_coletor",
        janela_999_horas=2.0,
        max_horas_fabrica_dia=1.0,
        exigir_ponto_no_ciclo=True,
    )
    if not out_horas.empty:
        raise AssertionError("Cenario com horas_fabrica acima do limite deveria ser descartado.")
    checks_ok.append("Filtro de horas em fabrica validado.")

    cenario_homeoffice_abre_fecha = _build_df_validacao_999(
        [
            {"cadastro": "F", "_dt_evento": "2026-01-01 07:45:00", "dir": "E", "planta": 999, "descricao_coletor": "MARCACOES CAPTURA PONTO 373"},
            {"cadastro": "F", "_dt_evento": "2026-01-01 16:03:00", "dir": "E", "planta": 999, "descricao_coletor": "MARCACOES CAPTURA PONTO 373"},
            {"cadastro": "F", "_dt_evento": "2026-01-01 16:23:00", "dir": "E", "planta": 1, "descricao_coletor": "PORTARIA ENTRADA"},
            {"cadastro": "F", "_dt_evento": "2026-01-01 16:35:00", "dir": "S", "planta": 1, "descricao_coletor": "PORTARIA SAIDA"},
        ]
    )
    out_homeoffice = selecionar_dias_validos_999_trajeto(
        cenario_homeoffice_abre_fecha,
        "descricao_coletor",
        janela_999_horas=6.0,
        max_horas_fabrica_dia=1.0,
        exigir_ponto_no_ciclo=True,
    )
    if not out_homeoffice.empty:
        raise AssertionError(
            "Cenario de home office (abre/fecha antes da portaria) deveria ser descartado como trajeto."
        )
    checks_ok.append("Regra de paridade do home office (abre/fecha) validada.")

    return checks_ok


def gerar_pdf_pessoa(
    pdf_path: Path,
    df_pessoa: pd.DataFrame,
    cadastro: str,
    nome: str,
    qtd_dias_irregulares: int,
    desc_col: str | None,
    consulta_pessoal: dict | None = None,
) -> None:
    d = df_pessoa.copy()
    if d.empty:
        return

    d["_dt_evento"] = pd.to_datetime(d["_dt_evento"], errors="coerce")
    dia_col = "_dia_rastreio" if "_dia_rastreio" in d.columns else "dia_operacional"
    d[dia_col] = pd.to_datetime(d[dia_col], errors="coerce")
    d = d.sort_values([dia_col, "_dt_evento"], kind="mergesort")
    d_flags = add_event_flags(d, desc_col)

    por_dia = (
        d.groupby(dia_col, dropna=True)
        .size()
        .rename("eventos")
        .sort_index()
    )

    ordem_situacao = ["Antes", "Depois", "Antes e Depois"]
    ordem_situacao_vis = ["Antes", "Depois", "Ambos"]
    occ = extrair_ocorrencias_trajeto(d)
    if occ.empty:
        tempo_por_situacao = pd.Series(0.0, index=ordem_situacao)
        qtd_por_situacao = pd.Series(0.0, index=ordem_situacao)
        pct_por_situacao = pd.Series(0.0, index=ordem_situacao)
    else:
        tempo_por_situacao = (
            occ.groupby("trajeto_999_situacao", dropna=True)["trajeto_999_h_total"]
            .sum()
            .reindex(ordem_situacao, fill_value=0.0)
        )
        qtd_por_situacao = (
            occ["trajeto_999_situacao"]
            .value_counts()
            .reindex(ordem_situacao, fill_value=0)
            .astype(float)
        )
        pct_por_situacao = (
            (qtd_por_situacao / float(qtd_por_situacao.sum())) * 100.0
            if float(qtd_por_situacao.sum()) > 0
            else pd.Series(0.0, index=ordem_situacao)
        )
    horas_totais = float(tempo_por_situacao.sum())
    pct_horas_por_situacao = (
        (tempo_por_situacao / horas_totais) * 100.0
        if horas_totais > 0
        else pd.Series(0.0, index=ordem_situacao)
    )

    horas_base = d_flags.loc[d_flags["_is_999"] & d_flags["_dt_evento"].notna(), "_dt_evento"]
    if horas_base.empty:
        horas_base = d_flags.loc[d_flags["_dt_evento"].notna(), "_dt_evento"]
    dist_hora = horas_base.dt.hour.value_counts().reindex(range(24), fill_value=0).sort_index()
    if int(dist_hora.sum()) > 0:
        pct_hora = (dist_hora / float(dist_hora.sum())) * 100.0
    else:
        pct_hora = pd.Series(0.0, index=range(24))
    heat_pct = pct_hora.values.reshape(1, 24)

    # remove Home Office / planta 999 do top plantas
    if "planta" in d.columns:
        planta_num = pd.to_numeric(d["planta"], errors="coerce")
        top_plantas = (
            d.loc[planta_num.notna() & (~planta_num.eq(999)), "planta"]
            .astype("string")
            .fillna("")
            .str.strip()
            .replace({"nan": ""})
            .loc[lambda s: s.ne("")]
            .value_counts()
            .head(10)
        )
    else:
        top_plantas = pd.Series(dtype="int64")

    def _render_consulta_pessoal_pagina_unica() -> None:
        consulta_ok = bool((consulta_pessoal or {}).get("ok"))
        consulta_msg = str((consulta_pessoal or {}).get("mensagem") or "Consulta nao executada.")
        consulta_url = str((consulta_pessoal or {}).get("url_final") or "")
        consulta_print_path = str((consulta_pessoal or {}).get("print_path") or "").strip()
        consulta_foto_path = str((consulta_pessoal or {}).get("foto_path") or "").strip()
        consulta_cpf = normalizar_cpf_value(
            (consulta_pessoal or {}).get("cpf_consultado")
            or (consulta_pessoal or {}).get("cpf")
            or (consulta_pessoal or {}).get("cadastro")
        )
        fotos_por_chapa_raw = dict((consulta_pessoal or {}).get("fotos_por_chapa") or {})
        fotos_por_chapa: dict[str, str] = {}

        def _norm_chapa_value(val: object) -> str:
            dig = re.sub(r"\D+", "", str(val or "").strip())
            if dig.startswith("00") and (len(dig) > 2):
                dig = dig[2:]
            return dig or str(val or "").strip()

        for k, v in fotos_por_chapa_raw.items():
            kk = _norm_chapa_value(k)
            vv = str(v or "").strip()
            if kk and vv:
                fotos_por_chapa[kk] = vv

        img_candidates = [consulta_foto_path]
        img_candidates.extend([str(v or "").strip() for v in fotos_por_chapa.values()])
        img_candidates.append(consulta_print_path)
        consulta_img_path = ""
        for cand in img_candidates:
            if cand and Path(cand).exists():
                consulta_img_path = cand
                break
        has_print_img = bool(consulta_img_path)

        fichas_consulta = list((consulta_pessoal or {}).get("fichas") or [])
        if fichas_consulta:
            ord_f = {"FUNCIONAIS": 0, "PESSOAIS": 1, "FICHA": 2}
            fichas_consulta = sorted(
                fichas_consulta,
                key=lambda x: (
                    ord_f.get(normalize_ascii_upper(str(x.get("tipo") or "")), 9),
                    str(x.get("url") or ""),
                ),
            )

        linhas_consulta = list((consulta_pessoal or {}).get("linhas") or [])

        def _fmt_num_pessoal(chave: str, valor: str) -> str:
            ku = normalize_ascii_upper(chave)
            vv = str(valor or "").strip()
            if ku in {"NUMERO PESSOAL", "NO PESSOAL"}:
                dig = re.sub(r"\D+", "", vv)
                if dig.startswith("00") and (len(dig) > 2):
                    dig = dig[2:]
                if dig:
                    return dig
            return vv

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

        def _build_rows_for_fichas(fichas_in: list[dict], linhas_fallback: list[str]) -> list[list[str]]:
            merged: dict[str, dict] = {}
            order_keys: list[str] = []

            def _is_placeholder_value(v: str) -> bool:
                vu = normalize_ascii_upper(str(v or ""))
                vu = vu.replace(" ", "")
                if not vu:
                    return True
                if re.fullmatch(r"[-|]+", vu):
                    return True
                return vu in {"N/A", "NA", "SEM_DADO", "SEMINFO"}

            def _add_row(k: str, v: str) -> None:
                kk = re.sub(r"\s+", " ", str(k or "")).strip(" \t\r\n:|-")
                vv = re.sub(r"\s+", " ", str(v or "")).strip(" \t\r\n|")
                if (not kk) or (not vv):
                    return
                kvu = normalize_ascii_upper(f"{kk} {vv}")
                if any(t in kvu for t in tokens_menu):
                    keep_tokens = {"NUMERO PESSOAL", "NO PESSOAL", "NOME", "UNIDADE ORGANIZACIONAL", "EMPRESA", "FUNCAO"}
                    if not any(t in kvu for t in keep_tokens):
                        return
                vv = _fmt_num_pessoal(kk, vv)
                ku = normalize_ascii_upper(kk)
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

        def _build_rows_from_linhas_consulta(linhas_in: list[str]) -> list[list[str]]:
            rows_out: list[list[str]] = []
            idx = 1
            for ln in list(linhas_in or []):
                txt = re.sub(r"\s+", " ", str(ln or "")).strip()
                if (not txt) or txt.startswith("[PASSO") or txt.startswith("[DEBUG"):
                    continue
                if "|" in txt:
                    parts = [p.strip() for p in txt.split("|") if p.strip()]
                    if len(parts) >= 2:
                        rows_out.append([parts[0], " | ".join(parts[1:])])
                        continue
                if ":" in txt:
                    k, v = txt.split(":", 1)
                    k = str(k or "").strip()
                    v = str(v or "").strip()
                    if k and v:
                        rows_out.append([k, v])
                        continue
                rows_out.append([f"Detalhe {idx}", txt])
                idx += 1
                if idx > 60:
                    break
            return rows_out

        def _wrap_text(txt: str, width: int) -> str:
            raw = str(txt or "").replace("\r", "\n")
            parts = [p.strip() for p in re.split(r"\s*(?:\||;|\n)\s*", raw) if p.strip()]
            if (not parts) and raw.strip():
                parts = [raw.strip()]
            wrapped_parts: list[str] = []
            for p in parts:
                if not p:
                    continue
                wrapped_parts.append(textwrap.fill(p, width=max(20, int(width))))
            return "\n".join(wrapped_parts) if wrapped_parts else ""

        def _extract_latest_date_from_pairs(pairs_in: list[tuple[str, str]] | list[list[str]]) -> pd.Timestamp:
            best = pd.NaT

            def _try_set_best(ts_raw: object) -> None:
                nonlocal best
                ts = pd.to_datetime(ts_raw, errors="coerce", dayfirst=True)
                if pd.notna(ts):
                    ts = pd.Timestamp(ts).normalize()
                    if pd.isna(best) or (ts > best):
                        best = ts

            for campo, valor in pairs_in:
                ku = normalize_ascii_upper(campo)
                if not any(tok in ku for tok in ["ADMISSAO", "INICIO", "ENTRADA"]):
                    continue
                txt = str(valor or "")
                for dt_txt in re.findall(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b", txt):
                    _try_set_best(dt_txt)
                for dt_txt in re.findall(r"\b\d{4}[/-]\d{2}[/-]\d{2}\b", txt):
                    _try_set_best(pd.to_datetime(dt_txt, errors="coerce"))
            return best

        def _extract_admissao_mais_proxima_from_pairs(
            pairs_in: list[tuple[str, str]] | list[list[str]],
        ) -> pd.Timestamp:
            melhor = pd.NaT
            hoje = pd.Timestamp.today().normalize()

            def _try_set_melhor(ts_raw: object) -> None:
                nonlocal melhor
                ts = pd.to_datetime(ts_raw, errors="coerce", dayfirst=True)
                if pd.isna(ts):
                    return
                ts = pd.Timestamp(ts).normalize()
                if pd.isna(melhor):
                    melhor = ts
                    return
                dist_new = abs(int((hoje - ts).days))
                dist_old = abs(int((hoje - melhor).days))
                if (dist_new < dist_old) or ((dist_new == dist_old) and (ts > melhor)):
                    melhor = ts

            for campo, valor in pairs_in:
                ku = normalize_ascii_upper(campo)
                if "ADMIS" not in ku:
                    continue
                txt = str(valor or "")
                for dt_txt in re.findall(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b", txt):
                    _try_set_melhor(dt_txt)
                for dt_txt in re.findall(r"\b\d{4}[/-]\d{2}[/-]\d{2}\b", txt):
                    _try_set_melhor(pd.to_datetime(dt_txt, errors="coerce"))
            return melhor

        def _selecionar_perfil_mais_novo(perfis_in: list[dict]) -> list[dict]:
            if len(perfis_in) <= 1:
                return perfis_in

            def _score(perfil: dict) -> tuple[int, float, pd.Timestamp, int, float]:
                pares_brutos = list(perfil.get("campos_raw") or [])
                rows = list(perfil.get("rows") or [])
                origem = pares_brutos if pares_brutos else rows
                dt_adm = _extract_admissao_mais_proxima_from_pairs(origem)
                dt_ref = dt_adm if pd.notna(dt_adm) else _extract_latest_date_from_pairs(origem)
                ordem_ref = int(perfil.get("_ordem_consulta") or 0)
                cad_ref = _norm_chapa_value(perfil.get("cadastro_ref") or "")
                cad_num = pd.to_numeric(cad_ref, errors="coerce")
                cad_score = float(cad_num) if pd.notna(cad_num) else float("-inf")
                has_adm = 1 if pd.notna(dt_adm) else 0
                ts_score = dt_ref if pd.notna(dt_ref) else pd.Timestamp.min
                if pd.notna(dt_ref):
                    hoje = pd.Timestamp.today().normalize()
                    proximidade = -float(abs(int((hoje - pd.Timestamp(dt_ref).normalize()).days)))
                else:
                    proximidade = float("-inf")
                return (has_adm, proximidade, ts_score, ordem_ref, cad_score)

            melhor = max(perfis_in, key=_score)
            melhor = dict(melhor)
            melhor["rotulo"] = "Registro por admissao mais proxima"
            return [melhor]

        perfis: list[dict] = []
        if fichas_consulta:
            grupos: dict[str, list[dict]] = {}
            ordem_grupos: list[str] = []
            for idx_f, ficha in enumerate(fichas_consulta, start=1):
                campos_f = list(ficha.get("campos") or [])
                chave = _norm_chapa_value(ficha.get("chapa") or "")
                if not chave:
                    for k, v in campos_f:
                        if normalize_ascii_upper(str(k or "")) in {"NUMERO PESSOAL", "NO PESSOAL"}:
                            chave = _norm_chapa_value(v)
                            break
                if not chave:
                    chave = f"SEM_CHAPA_{idx_f}"
                if chave not in grupos:
                    grupos[chave] = []
                    ordem_grupos.append(chave)
                grupos[chave].append(ficha)

            total_registros = max(1, len(ordem_grupos))
            for idx_g, chave in enumerate(ordem_grupos, start=1):
                fichas_grupo = list(grupos.get(chave, []))
                rows = garantir_cpf_rows(_build_rows_for_fichas(fichas_grupo, []), consulta_cpf)
                campos_raw: list[tuple[str, str]] = []
                for ficha_g in fichas_grupo:
                    for k_raw, v_raw in list(ficha_g.get("campos") or []):
                        campos_raw.append((str(k_raw), str(v_raw)))
                if (not rows) and campos_raw:
                    rows = garantir_cpf_rows(
                        _build_rows_from_linhas_consulta([f"{k}: {v}" for k, v in campos_raw]),
                        consulta_cpf,
                    )
                if not rows:
                    rows = garantir_cpf_rows(_build_rows_from_linhas_consulta(linhas_consulta), consulta_cpf)
                if not rows:
                    rows = [["Status consulta", consulta_msg or "Sem dados estruturados retornados."]]
                img_reg = str(fotos_por_chapa.get(chave) or "").strip()
                if (not img_reg) and consulta_img_path:
                    img_reg = consulta_img_path
                rotulo = f"Registro {idx_g}/{total_registros}"
                if not str(chave).startswith("SEM_CHAPA_"):
                    rotulo = f"{rotulo} - No pessoal {chave}"
                perfis.append(
                    {
                        "rows": rows,
                        "img_path": img_reg,
                        "rotulo": rotulo,
                        "cadastro_ref": chave,
                        "_ordem_consulta": idx_g,
                        "campos_raw": campos_raw,
                        "url": str((grupos.get(chave) or [{}])[0].get("url") or "").strip(),
                    }
                )

        if not perfis:
            rows_fallback = garantir_cpf_rows(_build_rows_for_fichas([], linhas_consulta), consulta_cpf)
            if not rows_fallback:
                rows_fallback = garantir_cpf_rows(
                    _build_rows_from_linhas_consulta(linhas_consulta),
                    consulta_cpf,
                )
            if not rows_fallback:
                rows_fallback = [["Status consulta", consulta_msg or "Sem dados estruturados retornados."]]
            perfis.append(
                {
                    "rows": rows_fallback,
                    "img_path": consulta_img_path,
                    "rotulo": "Registro 1/1",
                    "cadastro_ref": _norm_chapa_value(cadastro),
                    "_ordem_consulta": 1,
                    "campos_raw": [],
                    "url": consulta_url,
                }
            )

        # Exibe somente o registro mais novo da consulta pessoal por pessoa.
        perfis = _selecionar_perfil_mais_novo(perfis)

        total_perfis = len(perfis)
        for idx_p, perfil in enumerate(perfis, start=1):
            rows = list(perfil.get("rows") or [])
            img_path_pf = str(perfil.get("img_path") or "").strip()
            has_print_img_pf = bool(img_path_pf and Path(img_path_pf).exists())

            rows_fmt: list[list[str]] = []
            row_units: list[float] = []
            for campo, valor in rows:
                c = _wrap_text(campo, 26)
                v = _wrap_text(valor, 62)
                rows_fmt.append([c, v])
                lc = max(c.count("\n") + 1, v.count("\n") + 1)
                row_units.append(float(lc) + 0.25)

            figc, axc = plt.subplots(figsize=(11.69, 8.27))
            axc.axis("off")
            figc.suptitle(
                "Consulta Pessoal - Top piores (irregularidade 999 como trajeto)",
                fontsize=15,
                fontweight="bold",
                y=0.985,
            )

            axc.text(
                0.02,
                0.93,
                f"{cadastro} - {nome}",
                fontsize=12,
                fontweight="bold",
                color="white",
                ha="left",
                va="top",
                transform=axc.transAxes,
                bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.35"),
            )
            axc.text(
                0.02,
                0.87,
                f"Status: {'OK' if consulta_ok else 'FALHA'}",
                fontsize=10,
                fontweight="bold",
                color="white",
                ha="left",
                va="top",
                transform=axc.transAxes,
                bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.25"),
            )

            rotulo_pf = str(perfil.get("rotulo") or f"Registro {idx_p}/{total_perfis}")
            axc.text(
                0.02,
                0.82,
                rotulo_pf,
                fontsize=9.5,
                fontweight="bold",
                color="#1a1a1a",
                ha="left",
                va="top",
                transform=axc.transAxes,
            )

            if idx_p == 1:
                axc.text(0.02, 0.79, consulta_msg, fontsize=9.0, ha="left", va="top", transform=axc.transAxes)

            if total_perfis > 1:
                axc.text(
                    0.985,
                    0.98,
                    f"Pagina consulta {idx_p}/{total_perfis}",
                    fontsize=8.5,
                    ha="right",
                    va="top",
                    transform=axc.transAxes,
                    color="#333333",
                )

            if rows_fmt:
                width_tbl = 0.62 if has_print_img_pf else 0.95
                ax_tbl = figc.add_axes([0.02, 0.06, width_tbl, 0.72])
                ax_tbl.axis("off")
                table = ax_tbl.table(
                    cellText=rows_fmt,
                    colLabels=["Campo", "Valor"],
                    colLoc="left",
                    cellLoc="left",
                    colWidths=[0.35, 0.63],
                    loc="upper left",
                )
                table.auto_set_font_size(False)
                n_rows = len(rows_fmt)
                if n_rows <= 16:
                    fsz = 8.8
                elif n_rows <= 28:
                    fsz = 8.0
                elif n_rows <= 40:
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
                        cell.set_facecolor(COR_DESTAQUE_NUMEROS)
                        cell.set_text_props(color="white", weight="bold")
                        cell.set_height(unit_h * header_units)
                    elif c == 0:
                        cell.set_facecolor("#D4E1F2")
                    else:
                        cell.set_facecolor("#F1EAD3")
                    if r > 0:
                        idx = r - 1
                        if 0 <= idx < len(row_units):
                            cell.set_height(unit_h * row_units[idx])
            else:
                axc.text(
                    0.02,
                    0.72,
                    "Sem dados estruturados retornados.",
                    fontsize=9.8,
                    ha="left",
                    va="top",
                    transform=axc.transAxes,
                )

            if has_print_img_pf:
                try:
                    img_cons = plt.imread(img_path_pf)
                    ax_img = figc.add_axes([0.67, 0.30, 0.30, 0.46])
                    ax_img.imshow(img_cons)
                    ax_img.axis("off")
                    ax_img.set_title(
                        "Imagem Consulta Pessoal",
                        fontsize=9.0,
                        color="white",
                        pad=4,
                        bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.2"),
                    )
                except Exception as exc_img:
                    axc.text(
                        0.67,
                        0.74,
                        f"Falha ao renderizar imagem: {exc_img}",
                        fontsize=8.0,
                        ha="left",
                        va="top",
                        transform=axc.transAxes,
                    )

            figc.subplots_adjust(left=0.01, right=0.99, top=0.96, bottom=0.03)
            pdf.savefig(figc, bbox_inches="tight")
            plt.close(figc)

    with PdfPages(pdf_path) as pdf:
        # Pagina 1: titulo + KPI principal + heatmap percentual por hora
        fig0, (ax0, axh) = plt.subplots(2, 1, figsize=(11.69, 8.27), gridspec_kw={"height_ratios": [1.0, 1.9]})
        fig0.suptitle("Irregularidade - 999 como Trajeto", fontsize=17, fontweight="bold")

        ax0.axis("off")
        ax0.add_patch(
            plt.Rectangle(
                (0.03, 0.20), 0.94, 0.62, transform=ax0.transAxes, facecolor=COR_DESTAQUE_NUMEROS, edgecolor="none"
            )
        )
        ax0.text(
            0.50,
            0.66,
            "Horas totais da irregularidade 999 como trajeto",
            color="white",
            fontsize=14,
            fontweight="bold",
            ha="center",
            va="center",
            transform=ax0.transAxes,
        )
        ax0.text(
            0.50,
            0.42,
            formatar_horas_amigavel(horas_totais),
            color="white",
            fontsize=30,
            fontweight="bold",
            ha="center",
            va="center",
            transform=ax0.transAxes,
        )

        ax0.text(
            0.22,
            0.10,
            f"Ocorrencias: {len(occ)}",
            color="white",
            fontsize=11,
            fontweight="bold",
            ha="center",
            va="center",
            transform=ax0.transAxes,
            bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.25"),
        )
        ax0.text(
            0.78,
            0.10,
            f"Dias validos: {qtd_dias_irregulares}",
            color="white",
            fontsize=11,
            fontweight="bold",
            ha="center",
            va="center",
            transform=ax0.transAxes,
            bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.25"),
        )

        im = axh.imshow(heat_pct, aspect="auto", cmap="Blues", vmin=0, vmax=max(float(pct_hora.max()), 1.0))
        axh.set_title("Heatmap percentual por hora - irregularidade 999 como trajeto")
        axh.set_xlabel("Hora")
        axh.set_yticks([0])
        axh.set_yticklabels(["%"])
        axh.set_xticks(range(24))
        axh.set_xticklabels([str(h) for h in range(24)], fontsize=8)

        for h in range(24):
            val = float(heat_pct[0, h])
            cor_txt = "white" if val >= 4 else "black"
            axh.text(
                h,
                0,
                f"{val:.1f}%",
                ha="center",
                va="center",
                fontsize=8,
                color=cor_txt,
                fontweight="bold",
            )
        fig0.colorbar(im, ax=axh, fraction=0.025, pad=0.02, label="%")
        fig0.tight_layout(rect=[0, 0, 1, 0.95])
        pdf.savefig(fig0, bbox_inches="tight")
        plt.close(fig0)

        # Renderizacao antiga da consulta (desativada; mantida por compatibilidade)
        consulta_ok = bool((consulta_pessoal or {}).get("ok"))
        consulta_msg = str((consulta_pessoal or {}).get("mensagem") or "Consulta nao executada.")
        consulta_msg_print = str((consulta_pessoal or {}).get("mensagem_print") or "")
        consulta_url = str((consulta_pessoal or {}).get("url_final") or "")
        consulta_print_path = str((consulta_pessoal or {}).get("print_path") or "").strip()
        consulta_foto_path = str((consulta_pessoal or {}).get("foto_path") or "").strip()
        if (not consulta_print_path) and consulta_foto_path:
            consulta_print_path = consulta_foto_path
        has_print_img = bool(consulta_print_path and Path(consulta_print_path).exists())
        fichas_consulta = list((consulta_pessoal or {}).get("fichas") or [])
        if fichas_consulta:
            ord_f = {"FUNCIONAIS": 0, "PESSOAIS": 1, "FICHA": 2}
            fichas_consulta = sorted(
                fichas_consulta,
                key=lambda x: (
                    ord_f.get(normalize_ascii_upper(str(x.get("tipo") or "")), 9),
                    str(x.get("url") or ""),
                ),
            )
        linhas_consulta = list((consulta_pessoal or {}).get("linhas") or [])

        render_consulta_aqui = False
        rendered_ficha_page = False
        if render_consulta_aqui and fichas_consulta:
            for idx_ficha, ficha in enumerate(fichas_consulta):
                tipo_ficha = str(ficha.get("tipo") or "Ficha").strip()
                url_ficha = str(ficha.get("url") or "").strip()
                campos_ficha = list(ficha.get("campos") or [])
                if not campos_ficha:
                    continue

                linhas_tabela = [[str(k), str(v)] for k, v in campos_ficha]
                linhas_por_pag = 22
                total_pag_ficha = max(1, (len(linhas_tabela) + linhas_por_pag - 1) // linhas_por_pag)

                for idx_pag in range(total_pag_ficha):
                    rendered_ficha_page = True
                    ini = idx_pag * linhas_por_pag
                    fim = min(len(linhas_tabela), ini + linhas_por_pag)
                    chunk = linhas_tabela[ini:fim]

                    figc, axc = plt.subplots(figsize=(11.69, 8.27))
                    axc.axis("off")
                    sufixo = (
                        f" - {tipo_ficha}"
                        if total_pag_ficha == 1
                        else f" - {tipo_ficha} ({idx_pag + 1}/{total_pag_ficha})"
                    )
                    figc.suptitle(
                        f"Consulta Pessoal - Top piores (irregularidade 999 como trajeto){sufixo}",
                        fontsize=15,
                        fontweight="bold",
                        y=0.985,
                    )

                    cabec = f"{cadastro} - {nome}"
                    axc.text(
                        0.02,
                        0.93,
                        cabec,
                        fontsize=12,
                        fontweight="bold",
                        color="white",
                        ha="left",
                        va="top",
                        transform=axc.transAxes,
                        bbox=dict(
                            facecolor=COR_DESTAQUE_NUMEROS,
                            edgecolor=COR_DESTAQUE_NUMEROS,
                            boxstyle="round,pad=0.35",
                        ),
                    )
                    axc.text(
                        0.02,
                        0.87,
                        f"Status: {'OK' if consulta_ok else 'FALHA'}",
                        fontsize=10,
                        fontweight="bold",
                        color="white",
                        ha="left",
                        va="top",
                        transform=axc.transAxes,
                        bbox=dict(
                            facecolor=COR_DESTAQUE_NUMEROS,
                            edgecolor=COR_DESTAQUE_NUMEROS,
                            boxstyle="round,pad=0.25",
                        ),
                    )

                    if idx_pag == 0:
                        axc.text(0.02, 0.82, consulta_msg, fontsize=9.5, ha="left", va="top", transform=axc.transAxes)
                        if consulta_msg_print:
                            axc.text(0.02, 0.79, consulta_msg_print, fontsize=8.4, ha="left", va="top", transform=axc.transAxes)
                        if url_ficha:
                            axc.text(0.02, 0.76, f"URL ficha: {url_ficha}", fontsize=8.3, ha="left", va="top", transform=axc.transAxes)

                    left = 0.02
                    width_tbl = 0.62 if has_print_img else 0.95
                    top_tbl = 0.72 if idx_pag == 0 else 0.84
                    height_tbl = 0.62 if idx_pag == 0 else 0.74
                    ax_tbl = figc.add_axes([left, 0.08, width_tbl, height_tbl])
                    ax_tbl.axis("off")
                    table = ax_tbl.table(
                        cellText=chunk,
                        colLabels=["Campo", "Valor"],
                        colLoc="left",
                        cellLoc="left",
                        colWidths=[0.36, 0.62],
                        loc="upper left",
                    )
                    table.auto_set_font_size(False)
                    table.set_fontsize(8.5)
                    table.scale(1.0, 1.22)

                    for (r, c), cell in table.get_celld().items():
                        if r == 0:
                            cell.set_facecolor(COR_DESTAQUE_NUMEROS)
                            cell.set_text_props(color="white", weight="bold")
                        elif c == 0:
                            cell.set_facecolor("#D4E1F2")
                        else:
                            cell.set_facecolor("#F1EAD3")

                    if has_print_img and (idx_pag == 0):
                        try:
                            img_cons = plt.imread(consulta_print_path)
                            ax_img = figc.add_axes([0.67, 0.28, 0.30, 0.50])
                            ax_img.imshow(img_cons)
                            ax_img.axis("off")
                            ax_img.set_title(
                                "Imagem Consulta Pessoal",
                                fontsize=9.2,
                                color="white",
                                pad=4,
                                bbox=dict(
                                    facecolor=COR_DESTAQUE_NUMEROS,
                                    edgecolor=COR_DESTAQUE_NUMEROS,
                                    boxstyle="round,pad=0.2",
                                ),
                            )
                        except Exception as exc_img:
                            axc.text(
                                0.67,
                                0.74,
                                f"Falha ao renderizar imagem: {exc_img}",
                                fontsize=8.2,
                                ha="left",
                                va="top",
                                transform=axc.transAxes,
                            )

                    if idx_pag < (total_pag_ficha - 1):
                        axc.text(0.98, 0.02, "continua...", fontsize=9, ha="right", va="bottom", transform=axc.transAxes)

                    figc.subplots_adjust(left=0.01, right=0.99, top=0.96, bottom=0.03)
                    pdf.savefig(figc, bbox_inches="tight")
                    plt.close(figc)

        if render_consulta_aqui and (not rendered_ficha_page):
            linhas_render: list[str] = []
            wrap_width = 86 if has_print_img else 150
            if linhas_consulta:
                for ln in linhas_consulta:
                    wraps = textwrap.wrap(ln, width=wrap_width, break_long_words=False, break_on_hyphens=False)
                    linhas_render.extend(wraps or [""])
            if not linhas_render:
                linhas_render = ["Sem detalhes retornados para exibir."]

            linhas_por_pagina = 34
            total_paginas_consulta = max(1, (len(linhas_render) + linhas_por_pagina - 1) // linhas_por_pagina)

            for idx_pag in range(total_paginas_consulta):
                ini = idx_pag * linhas_por_pagina
                fim = min(len(linhas_render), ini + linhas_por_pagina)
                chunk = linhas_render[ini:fim]

                figc, axc = plt.subplots(figsize=(11.69, 8.27))
                axc.axis("off")
                sufixo = "" if idx_pag == 0 else f" (continuação {idx_pag + 1}/{total_paginas_consulta})"
                figc.suptitle(
                    f"Consulta Pessoal - Top piores (irregularidade 999 como trajeto){sufixo}",
                    fontsize=16,
                    fontweight="bold",
                    y=0.985,
                )

                cabec = f"{cadastro} - {nome}"
                axc.text(
                    0.02,
                    0.93,
                    cabec,
                    fontsize=12,
                    fontweight="bold",
                    color="white",
                    ha="left",
                    va="top",
                    transform=axc.transAxes,
                    bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.35"),
                )
                axc.text(
                    0.02,
                    0.87,
                    f"Status: {'OK' if consulta_ok else 'FALHA'}",
                    fontsize=10,
                    fontweight="bold",
                    color="white",
                    ha="left",
                    va="top",
                    transform=axc.transAxes,
                    bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.25"),
                )
                if idx_pag == 0:
                    axc.text(0.02, 0.82, consulta_msg, fontsize=10, ha="left", va="top", transform=axc.transAxes)
                    y = 0.74
                else:
                    y = 0.82

                passo = 0.020
                for ln in chunk:
                    axc.text(0.02, y, ln, fontsize=8.8, ha="left", va="top", transform=axc.transAxes)
                    y -= passo
                    if y < 0.05:
                        break

                figc.tight_layout(rect=[0, 0, 1, 0.95])
                pdf.savefig(figc, bbox_inches="tight")
                plt.close(figc)

        # Pagina 2: graficos individuais
        fig, axs = plt.subplots(2, 2, figsize=(11.69, 8.27))
        (ax1, ax2), (ax3, ax4) = axs

        fig.suptitle(f"{cadastro} - {nome}", fontsize=16, fontweight="bold")
        fig.text(
            0.5,
            0.94,
            f"Dias validos: {qtd_dias_irregulares}",
            ha="center",
            va="center",
            color="white",
            fontsize=10.5,
            fontweight="bold",
            bbox=dict(facecolor=COR_DESTAQUE_NUMEROS, edgecolor=COR_DESTAQUE_NUMEROS, boxstyle="round,pad=0.3"),
        )

        # 1) Tendencia mensal (media por mes; meses sem eventos = 0)
        if por_dia.empty:
            ax1.axis("off")
            ax1.text(0.02, 0.90, "Tendencia mensal de eventos", fontsize=13, fontweight="bold", va="top")
            ax1.text(0.02, 0.75, "Sem dados para exibir.", fontsize=10, va="top")
        else:
            serie_dia = por_dia.copy()
            serie_dia.index = pd.to_datetime(serie_dia.index, errors="coerce")
            serie_dia = serie_dia.loc[serie_dia.index.notna()].sort_index()

            dias_idx = pd.date_range(serie_dia.index.min(), serie_dia.index.max(), freq="D")
            serie_dia = serie_dia.reindex(dias_idx, fill_value=0.0).astype(float)
            tendencia_mes = serie_dia.resample("MS").mean().astype(float)
            meses_idx = pd.date_range(tendencia_mes.index.min(), tendencia_mes.index.max(), freq="MS")
            tendencia_mes = tendencia_mes.reindex(meses_idx, fill_value=0.0)
            dias_com_ocorrencia_mes = (serie_dia > 0).resample("MS").sum().astype(int)
            dias_com_ocorrencia_mes = dias_com_ocorrencia_mes.reindex(meses_idx, fill_value=0).astype(int)

            x_dt = pd.to_datetime(tendencia_mes.index, errors="coerce")
            y_vals = pd.to_numeric(tendencia_mes.values, errors="coerce")
            dias_ocorrencia_vals = np.asarray(dias_com_ocorrencia_mes.values, dtype=int)
            mask_ok = x_dt.notna() & pd.notna(y_vals)
            x_dt = x_dt[mask_ok]
            y_vals = np.asarray(y_vals[mask_ok], dtype=float)
            dias_ocorrencia_vals = dias_ocorrencia_vals[mask_ok]

            if len(x_dt) >= 3:
                x_num = mdates.date2num(pd.to_datetime(x_dt).to_pydatetime())
                amp = float(np.ptp(x_num))
                if amp <= 0:
                    amp = 1.0
                x_scaled = (x_num - x_num.min()) / amp
                deg = min(3, len(x_scaled) - 1)
                coef = np.polyfit(x_scaled, y_vals, deg=deg)
                x_dense_scaled = np.linspace(float(x_scaled.min()), float(x_scaled.max()), 320)
                y_dense = np.polyval(coef, x_dense_scaled)
                y_dense = np.clip(y_dense, 0.0, None)
                x_dense_num = x_dense_scaled * amp + x_num.min()

                ax1.plot(
                    mdates.num2date(x_dense_num),
                    y_dense,
                    linewidth=2.8,
                    linestyle="-",
                    color="#1f77b4",
                    solid_capstyle="round",
                    solid_joinstyle="round",
                    zorder=10,
                )
                ax1.fill_between(mdates.num2date(x_dense_num), y_dense, color="#1f77b4", alpha=0.12, zorder=1)
            else:
                ax1.plot(
                    pd.to_datetime(x_dt),
                    y_vals,
                    linewidth=2.8,
                    linestyle="-",
                    color="#1f77b4",
                    solid_capstyle="round",
                    solid_joinstyle="round",
                    zorder=10,
                )
            ax1.scatter(
                pd.to_datetime(x_dt),
                y_vals,
                s=22,
                color="#7ec8ff",
                alpha=0.85,
                zorder=3,
                edgecolors="none",
            )
            y_min_plot, y_max_plot = ax1.get_ylim()
            y_span = float(y_max_plot - y_min_plot)
            if y_span <= 0:
                y_span = 1.0
            y_offset = 0.03 * y_span
            y_margin = 0.015 * y_span
            for x_pt, y_pt, qtd_dias in zip(pd.to_datetime(x_dt), y_vals, dias_ocorrencia_vals):
                y_label = float(y_pt) + y_offset
                y_label = min(y_label, float(y_max_plot) - y_margin)
                y_label = max(y_label, float(y_min_plot) + y_margin)
                va_label = "bottom" if y_label >= float(y_pt) else "top"
                ax1.text(
                    x_pt,
                    y_label,
                    f"{int(qtd_dias)}",
                    ha="center",
                    va=va_label,
                    fontsize=8,
                    color="black",
                    zorder=2,
                    clip_on=True,
                    bbox=dict(
                        boxstyle="round,pad=0.22",
                        facecolor="#d7ecff",
                        edgecolor="none",
                        linewidth=0.0,
                        alpha=0.95,
                    ),
                )
            n_mes = max(1, len(x_dt))
            intv = max(1, int(np.ceil(n_mes / 8)))
            ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=intv))
            ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%Y"))
            ax1.set_title("Tendencia mensal de eventos (media por dia do mes)")
            ax1.set_xlabel("Mes")
            ax1.set_ylabel("Media diaria de eventos")
            ax1.grid(alpha=0.25)
            ax1.tick_params(axis="x", rotation=45)

        if (horas_totais <= 0) and (float(qtd_por_situacao.sum()) <= 0):
            ax2.axis("off")
            ax2.text(0.02, 0.90, "Heatmap de concentração por separação", fontsize=13, fontweight="bold", va="top")
            ax2.text(0.02, 0.75, "Sem ocorrências para consolidar o heatmap.", fontsize=10, va="top")
        else:
            heat_conc = pd.DataFrame(
                [pct_horas_por_situacao.values, pct_por_situacao.values],
                index=["% Horas acumuladas", "% Ocorrências"],
                columns=ordem_situacao_vis,
            )
            vmax_heat = max(float(heat_conc.to_numpy().max()), 1.0)
            im2 = ax2.imshow(heat_conc.values, aspect="auto", cmap="Blues", vmin=0.0, vmax=vmax_heat)
            ax2.set_title("Heatmap de concentração (tempo x ocorrências)")
            ax2.set_xlabel("Separação")
            ax2.set_ylabel("Métrica")
            ax2.set_xticks(range(len(ordem_situacao_vis)))
            ax2.set_xticklabels(ordem_situacao_vis, rotation=20)
            ax2.set_yticks(range(len(heat_conc.index)))
            ax2.set_yticklabels(list(heat_conc.index))

            for yi in range(heat_conc.shape[0]):
                for xi in range(heat_conc.shape[1]):
                    pct_v = float(heat_conc.iloc[yi, xi])
                    cor_txt = "white" if pct_v >= 45 else "black"
                    if yi == 0:
                        txt_cell = f"{float(tempo_por_situacao.iloc[xi]):.2f}h\n({pct_v:.0f}%)"
                    else:
                        txt_cell = f"{pct_v:.1f}%\n({int(qtd_por_situacao.iloc[xi])})"
                    ax2.text(
                        xi,
                        yi,
                        txt_cell,
                        ha="center",
                        va="center",
                        fontsize=8.8,
                        color=cor_txt,
                        fontweight="bold",
                    )

            cbar2 = fig.colorbar(im2, ax=ax2, fraction=0.046, pad=0.04)
            cbar2.set_label("% por métrica (linha = 100%)")
            ax2.text(
                0.0,
                -0.24,
                f"Total horas: {horas_totais:.2f}h | Total ocorrências: {int(qtd_por_situacao.sum())}",
                transform=ax2.transAxes,
                fontsize=8.3,
                ha="left",
                va="top",
            )

        if top_plantas.empty:
            ax3.axis("off")
            ax3.text(0.02, 0.90, "Top plantas", fontsize=13, fontweight="bold", va="top")
            ax3.text(0.02, 0.75, "Sem dados de planta.", fontsize=10, va="top")
        else:
            ax3.bar(top_plantas.index.astype(str), top_plantas.values)
            ax3.set_title("Top plantas (sem 999)")
            ax3.set_xlabel("Planta")
            ax3.set_ylabel("Qtd eventos")
            ax3.grid(axis="y", alpha=0.25)
            ax3.tick_params(axis="x", rotation=45)
            annotate_bar(ax3, top_plantas.values)

        if float(pct_por_situacao.sum()) <= 0:
            ax4.axis("off")
            ax4.text(0.02, 0.90, "Percentual por separacao", fontsize=13, fontweight="bold", va="top")
            ax4.text(0.02, 0.75, "Sem ocorrencias para calcular percentual.", fontsize=10, va="top")
        else:
            ax4.bar(ordem_situacao_vis, pct_por_situacao.values)
            ax4.set_title("Percentual de ocorrencias por separacao")
            ax4.set_xlabel("Separacao")
            ax4.set_ylabel("Percentual (%)")
            ax4.set_ylim(0, 100)
            ax4.grid(axis="y", alpha=0.25)
            ax4.tick_params(axis="x", rotation=20)
            annotate_bar(ax4, pct_por_situacao.values, fmt="{:.1f}", suffix="%")

        fig.tight_layout(rect=[0, 0, 1, 0.92])
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        # Pagina 3: consulta pessoal
        _render_consulta_pessoal_pagina_unica()

def main() -> None:
    setup_plot_style()
    args = parse_args()
    validar_args(args)

    if bool(args.validar_logica):
        log_info("[INFO validacao] Iniciando validacao sintetica da logica 999 como trajeto...")
        checks_ok = validar_logica_999_trajeto()
        log_info(f"[INFO validacao] {len(checks_ok)} checks concluidos com sucesso.")
        for check in checks_ok:
            log_info(f"  - {check}")

    base_dir = resolve_base_dir(args.base_dir)
    out_dir = (SCRIPT_DIR / "saidas").resolve()

    p_irreg = base_dir / "outputs_irregularidades" / "dfs" / "irregularidade_999_como_trajeto.parquet"
    p_ronda = base_dir / "df_ronda.parquet"
    log_info(f"[INFO] Base de leitura: {base_dir}")
    log_info(f"[INFO] Base irregularidade: {p_irreg}")
    log_info(f"[INFO] Base ronda: {p_ronda}")

    if not p_irreg.exists():
        raise FileNotFoundError(f"Base de irregularidade nao encontrada: {p_irreg}")
    if not p_ronda.exists():
        raise FileNotFoundError(f"Base bruta nao encontrada: {p_ronda}")

    cleanup_saida(out_dir)
    cleanup_consulta_pessoal_prints_dirs(base_dir=base_dir, script_dir=SCRIPT_DIR)
    cleanup_pastas_legadas_vazias(base_dir=base_dir, out_dir_oficial=out_dir)
    try:
        os.chdir(out_dir)
    except Exception as exc:
        raise RuntimeError(f"Nao foi possivel entrar na pasta de saida: {out_dir}") from exc
    log_info(f"[INFO] Diretorio de execucao: {Path.cwd()}")

    cols_irreg = list(pq.ParquetFile(str(p_irreg)).schema.names)
    col_area_irreg = pick_col(["area", "área"], cols_irreg)

    cols_irreg_read = ["cadastro", "nome", "dia_operacional"]
    if col_area_irreg and col_area_irreg not in cols_irreg_read:
        cols_irreg_read.append(col_area_irreg)

    dirreg = pd.read_parquet(p_irreg, columns=cols_irreg_read)
    dirreg["cadastro"] = dirreg["cadastro"].astype("string").fillna("").str.strip()
    dirreg["dia_operacional"] = pd.to_datetime(dirreg["dia_operacional"], errors="coerce").dt.normalize()
    dirreg = dirreg.loc[dirreg["cadastro"].ne("") & dirreg["dia_operacional"].notna()].copy()

    if col_area_irreg and col_area_irreg in dirreg.columns:
        dirreg = remover_cadastros_area_bv(dirreg, col_area_irreg)

    keys = dirreg[["cadastro", "dia_operacional"]].drop_duplicates()
    counts_base = (
        keys.groupby("cadastro", sort=False)
        .size()
        .rename("qtd_dias_base")
        .reset_index()
        .sort_values(["qtd_dias_base", "cadastro"], ascending=[False, True], kind="mergesort")
    )

    if counts_base.empty:
        raise SystemExit("Sem dados para gerar Top 5.")

    nome_map = (
        dirreg.loc[dirreg["nome"].notna(), ["cadastro", "nome"]]
        .drop_duplicates(subset=["cadastro"], keep="last")
        .set_index("cadastro")["nome"]
        .to_dict()
    )

    # universo de candidatos mais amplo para aguentar os filtros finais
    n_candidatos = max(int(args.top_n) * 30, 150)
    candidatos = counts_base.head(n_candidatos).copy()
    candidatos["nome"] = candidatos["cadastro"].map(nome_map).fillna("")

    candidatos_cads = set(candidatos["cadastro"].astype(str).tolist())

    pf = pq.ParquetFile(str(p_ronda))
    cols_ronda = list(pf.schema.names)

    col_desc = pick_col(["descricao_coletor", "descricao coletor"], cols_ronda)
    col_area = pick_col(["area", "área"], cols_ronda)
    col_uso = pick_col(["uso_acesso", "uso acesso"], cols_ronda)
    col_cargo_esp = pick_col(["cargo_especifico", "cargo especifico"], cols_ronda)

    cols_raw = [
        "cadastro",
        "nome",
        "data",
        "hora",
        "dir",
        "planta",
        "coletor",
        "tipo",
        "acesso",
        "cargo",
        "heranca",
        "desligado",
    ]
    for c in [col_desc, col_area, col_uso, col_cargo_esp]:
        if c and (c not in cols_raw):
            cols_raw.append(c)
    cols_raw = [c for c in cols_raw if c in cols_ronda]

    raw_parts: list[pd.DataFrame] = []
    n_batches = 0
    n_linhas_lidas = 0
    n_linhas_candidatas = 0
    batch_size = int(args.batch_size)
    log_info(f"[INFO] Iniciando leitura de df_ronda em batches (batch_size={batch_size})...")
    for batch in pf.iter_batches(columns=cols_raw, batch_size=int(args.batch_size)):
        n_batches += 1
        n_linhas_lidas += int(batch.num_rows)
        if (n_batches % 10) == 0:
            log_info(
                "[INFO] Batches processados: "
                f"{n_batches} | linhas lidas: {n_linhas_lidas} | linhas candidatas: {n_linhas_candidatas}"
            )
        part = batch.to_pandas()
        if "cadastro" not in part.columns:
            continue

        part["cadastro"] = part["cadastro"].astype("string").fillna("").str.strip()
        part = part.loc[part["cadastro"].ne("")].copy()
        if part.empty:
            continue

        data_dt = pd.to_datetime(part["data"], dayfirst=True, errors="coerce")
        hora_s = (
            part["hora"]
            .astype("string")
            .fillna("00:00")
            .str.strip()
            .replace({"": "00:00", "nan": "00:00", "NaT": "00:00"})
        )
        hhmm = hora_s.str.match(r"^\d{1,2}:\d{2}$", na=False)
        hora_s = hora_s.where(~hhmm, hora_s + ":00")
        hora_td = pd.to_timedelta(hora_s, errors="coerce")

        part["_dt_evento"] = data_dt.dt.normalize() + hora_td
        part = part.loc[part["_dt_evento"].notna()].copy()
        if part.empty:
            continue

        part["_dia_rastreio"] = calcular_dia_rastreio(part["_dt_evento"])
        part["dia_operacional"] = part["_dia_rastreio"]
        part = part.loc[part["cadastro"].isin(candidatos_cads)].copy()
        if part.empty:
            continue

        n_linhas_candidatas += int(len(part))
        raw_parts.append(part)

    log_info(
        "[INFO] Leitura de df_ronda concluida: "
        f"{n_batches} batches | linhas lidas: {n_linhas_lidas} | linhas candidatas: {n_linhas_candidatas}"
    )

    if raw_parts:
        raw_all = pd.concat(raw_parts, ignore_index=True)
        raw_all = raw_all.drop_duplicates().sort_values(["cadastro", "_dia_rastreio", "_dt_evento"], kind="mergesort")
    else:
        raw_all = pd.DataFrame(columns=cols_raw + ["_dt_evento", "_dia_rastreio", "dia_operacional"])

    raw_all = remover_cadastros_area_bv(raw_all, col_area)
    raw_all = manter_somente_eventos_relevantes(raw_all, col_desc)
    raw_all = remover_dias_com_mais_de_uma_planta(raw_all)
    log_info("[INFO] Aplicando filtros finais da logica 999 como trajeto...")
    raw_valid = selecionar_dias_validos_999_trajeto(
        raw_all,
        col_desc,
        janela_999_horas=float(args.janela_999_horas),
        max_horas_fabrica_dia=float(args.max_horas_fabrica_dia),
        exigir_ponto_no_ciclo=(not bool(args.nao_exigir_ponto_no_ciclo)),
    )
    log_info(f"[INFO] Linhas apos filtros finais: {len(raw_valid)}")

    if raw_valid.empty:
        raise SystemExit("Sem dados finais apos aplicar os filtros.")

    dia_ref_col = "_dia_rastreio" if "_dia_rastreio" in raw_valid.columns else "dia_operacional"

    counts_final = (
        raw_valid[["cadastro", dia_ref_col]]
        .drop_duplicates()
        .groupby("cadastro", sort=False)
        .size()
        .rename("qtd_dias_irregulares_999")
        .reset_index()
        .sort_values(["qtd_dias_irregulares_999", "cadastro"], ascending=[False, True], kind="mergesort")
    )

    top = counts_final.head(int(max(1, args.top_n))).copy()
    top["nome"] = top["cadastro"].map(nome_map).fillna("")
    top = top[["cadastro", "nome", "qtd_dias_irregulares_999"]]
    log_info(f"[INFO] Top selecionado: {len(top)} cadastros.")

    top_cads = set(top["cadastro"].astype(str).tolist())
    raw_saida = raw_valid.loc[raw_valid["cadastro"].astype("string").fillna("").str.strip().isin(top_cads)].copy()
    top_cads_sorted = [str(c).strip() for c in top["cadastro"].astype(str).tolist()]

    consulta_user = str(CONSULTA_PESSOAL_USER or os.getenv("CONSULTA_PESSOAL_USER", "")).strip()
    consulta_password = str(CONSULTA_PESSOAL_PASSWORD or os.getenv("CONSULTA_PESSOAL_PASSWORD", "")).strip()
    consulta_capturar_print = str(
        os.getenv("CONSULTA_PESSOAL_CAPTURAR_PRINT", str(CONSULTA_PESSOAL_CAPTURAR_PRINT))
    ).strip().lower() in {"1", "true", "t", "sim", "s", "yes", "y"}
    consulta_client = ConsultaPessoalClient(
        base_url=CONSULTA_PESSOAL_URL,
        user=consulta_user,
        password=consulta_password,
        timeout_s=CONSULTA_PESSOAL_TIMEOUT_S,
        capturar_print=consulta_capturar_print,
    )
    consulta_por_cadastro: dict[str, dict] = {}

    if not consulta_client.enabled:
        msg_consulta = (
            "Consulta pessoal desabilitada. Preencha CONSULTA_PESSOAL_USER/CONSULTA_PESSOAL_PASSWORD "
            "(ou variaveis de ambiente com esses mesmos nomes)."
        )
        log_info(f"[INFO consulta pessoal] {msg_consulta}")
        for cad in top_cads_sorted:
            consulta_por_cadastro[cad] = {
                "cadastro": cad,
                "ok": False,
                "mensagem": msg_consulta,
                "url_final": "",
                "linhas": [],
                "fichas": [],
                "foto_path": "",
            }
    else:
        if not consulta_client.capturar_print:
            log_info(
                "[INFO consulta pessoal] Captura de print desabilitada "
                "(CONSULTA_PESSOAL_CAPTURAR_PRINT=False)."
            )
        nome_hint_map = (
            top.assign(cadastro=top["cadastro"].astype(str).str.strip())
               .set_index("cadastro")["nome"]
               .astype(str)
               .to_dict()
        )
        total_consultas = len(top_cads_sorted)
        for idx_consulta, cad in enumerate(top_cads_sorted, start=1):
            nome_hint = str(nome_hint_map.get(str(cad).strip(), "") or "").strip()
            log_info(f"[INFO consulta pessoal] Consultando cadastro {idx_consulta}/{total_consultas}: {cad}")
            info = consulta_client.consultar_por_cadastro(cad, nome=nome_hint)
            consulta_por_cadastro[cad] = info
            if not bool(info.get("ok")):
                log_info(f"[WARN consulta pessoal] {info.get('mensagem', '')}")
            msg_print = str(info.get("mensagem_print") or "").strip()
            if msg_print and (msg_print != str(info.get("mensagem") or "").strip()):
                log_info(f"[WARN print consulta pessoal] {msg_print}")

    gerados: list[tuple[Path, Path]] = []
    total_geracao = len(top)
    log_info(f"[INFO] Iniciando geracao de arquivos por pessoa ({total_geracao} pessoas)...")

    for idx_geracao, row in enumerate(top.itertuples(index=False), start=1):
        cadastro = str(row.cadastro).strip()
        nome = str(row.nome).strip()
        qtd_dias = int(row.qtd_dias_irregulares_999)
        log_info(f"[INFO] Gerando arquivos {idx_geracao}/{total_geracao} para cadastro {cadastro}...")

        df_pessoa = raw_saida.loc[
            raw_saida["cadastro"].astype("string").fillna("").str.strip().eq(cadastro)
        ].copy()
        if df_pessoa.empty:
            continue

        token = slugify(nome)
        csv_path = out_dir / f"{cadastro}_{token}.csv"
        pdf_path = out_dir / f"{cadastro}_{token}.pdf"
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        alias_cols: dict[str, str] = {}
        for src, dst in [
            (col_desc, "descricao_coletor"),
            (col_area, "area"),
            (col_uso, "uso_acesso"),
            (col_cargo_esp, "cargo_especifico"),
        ]:
            if src and (src in df_pessoa.columns) and (src != dst) and (dst not in df_pessoa.columns):
                alias_cols[src] = dst
        if alias_cols:
            df_pessoa = df_pessoa.rename(columns=alias_cols)

        cols_drop = ["_is_port", "_is_ponto", "_is_999"]
        ordem_cols = [
            "cadastro",
            "nome",
            "data",
            "hora",
            "dir",
            "planta",
            "descricao_coletor",
            "desligado",
            "area",
            "cargo",
            "heranca",
            "cargo_especifico",
            "uso_acesso",
            "coletor",
            "tipo",
            "acesso",
            "_dt_evento",
            "_dia_rastreio",
            "dia_operacional",
            "_mantem",
            "_dir_norm",
            "_planta_num",
            "t_ent",
            "t_sai",
            "t_999_before",
            "t_999_after",
            "h_before",
            "h_after",
            "horas_trajeto_999_dia",
            "situacao_trajeto_999",
            "n_plantas_dia",
            "planta_referencia",
            "horas_fabrica_dia",
            "_trajeto_occ_id",
            "trajeto_999_h_before",
            "trajeto_999_h_after",
            "trajeto_999_h_total",
            "trajeto_999_situacao",
        ]
        cols_export = [c for c in ordem_cols if c in df_pessoa.columns and c not in cols_drop]
        cols_rest = [c for c in df_pessoa.columns if c not in cols_drop and c not in cols_export]
        dia_ref_pessoa = "_dia_rastreio" if "_dia_rastreio" in df_pessoa.columns else "dia_operacional"
        sort_cols = [c for c in [dia_ref_pessoa, "_dt_evento"] if c in df_pessoa.columns]
        df_pessoa = df_pessoa[cols_export + cols_rest]
        if sort_cols:
            df_pessoa = df_pessoa.sort_values(sort_cols, kind="mergesort")

        df_pessoa.to_csv(csv_path, index=False, encoding="utf-8-sig")

        info_consulta = consulta_por_cadastro.get(cadastro)
        try:
            gerar_pdf_pessoa(
                pdf_path=pdf_path,
                df_pessoa=df_pessoa,
                cadastro=cadastro,
                nome=nome,
                qtd_dias_irregulares=qtd_dias,
                desc_col=col_desc,
                consulta_pessoal=info_consulta,
            )
        finally:
            cleanup_consulta_pessoal_imagens_temporarias(info_consulta)
        gerados.append((csv_path, pdf_path))
        log_info(f"[INFO] Arquivos gerados para {cadastro}: {csv_path.name} e {pdf_path.name}")

    log_info("Top 5 final:")
    log_info(top.to_string(index=False))

    log_info("\nArquivos gerados por pessoa:")
    for csv_p, pdf_p in gerados:
        log_info(str(csv_p))
        log_info(str(pdf_p))

    log_info(f"\nTotal de pessoas com arquivos gerados: {len(gerados)}")
    log_info(f"Linhas finais de saida: {len(raw_saida)}")


if __name__ == "__main__":
    main()
