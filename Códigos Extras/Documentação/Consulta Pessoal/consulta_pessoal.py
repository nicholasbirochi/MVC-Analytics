from __future__ import annotations

import argparse
import base64
import csv
import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
import traceback
import unicodedata
import zipfile
from datetime import date, datetime
from html import escape as html_escape
from pathlib import Path
from typing import Any

# Evita dependencia de Tcl/Tk ao gerar PDF no runtime embutido.
os.environ["MPLBACKEND"] = "Agg"

try:
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    plt.switch_backend("Agg")
    from matplotlib.backends.backend_pdf import PdfPages
except Exception:  # pragma: no cover
    plt = None
    PdfPages = None


DEFAULT_BASE_URL = "https://vwbransvprve1.sa.vwg/recursos.humanos.consultapessoal/default.htm"
COR_DESTAQUE = "#123B82"
COR_CABECALHO_TABELA = "#123B82"
COR_CAMPO = "#D4E1F2"
COR_VALOR = "#F1EAD3"
PASTA_SAIDA_CONSULTA = "saidas consulta pessoal"
PASTA_BASE_CONSULTA = r"Z:\Nicholas Birochi\Consulta Pessoal"
EXECUTAVEL_CONSULTA = r"Z:\Nicholas Birochi\Consulta Pessoal.exe"
TIPO_BUSCA_AUTO = "auto"
TIPO_BUSCA_CHAPA = "chapa"
TIPO_BUSCA_NOME = "nome_completo"
TIPO_BUSCA_CPF = "cpf"
TIPOS_BUSCA_VALIDOS = {TIPO_BUSCA_AUTO, TIPO_BUSCA_CHAPA, TIPO_BUSCA_NOME, TIPO_BUSCA_CPF}
MENSAGEM_NOME_NAO_ENCONTRADO = "Não foi encontrado ninguém com esse nome"
ENV_CHAVE_BUSCA = "CONSULTA_PESSOAL_CHAVE_BUSCA"
ENV_CHAVE_BUSCA_LEGADA = "CONSULTA_PESSOAL_SOLICITADA"
WEB_ERROR_LOG = "consulta_pessoal_web_error.log"


def _data_hoje() -> date:
    return date.today()


def _data_pt_br(dt: date) -> str:
    return dt.strftime("%d/%m/%Y")


def _data_para_nome_arquivo(dt: date) -> str:
    return dt.strftime("%Y-%m-%d")


def _nome_solicitante_para_arquivo(raw: str) -> str:
    txt = unicodedata.normalize("NFKD", str(raw or ""))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = re.sub(r"[^A-Za-z0-9]+", "_", txt).strip("_")
    txt = re.sub(r"_+", "_", txt)
    return txt or "nao_informado"


def _nome_arquivo_relatorio_base(data_ref: date, solicitante: str) -> str:
    data_token = _data_para_nome_arquivo(data_ref)
    sol_token = _nome_solicitante_para_arquivo(solicitante)
    return f"consulta_pessoal_relatorio_{data_token}_{sol_token}"


def _parse_data_referencia(raw: str) -> date:
    txt = str(raw or "").strip()
    if not txt:
        return _data_hoje()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, fmt).date()
        except Exception:
            pass
    raise SystemExit(
        "Data invalida em --data-referencia. Use formato DD-MM-YYYY, ex: 15-04-2026."
    )


def _solicitante_from_env() -> str:
    keys = (
        "CONSULTA_PESSOAL_SOLICITANTE_NOME",
        "CONSULTA_PESSOAL_SOLICITANTE",
        "CONSULTA_PESSOAL_REQUESTER_NAME",
    )
    for key in keys:
        val = str(os.getenv(key, "")).strip()
        if val:
            return val
    # Fallback para nao deixar capa vazia quando existir apenas matricula no .env.
    return str(os.getenv("CONSULTA_PESSOAL_USER", "")).strip()


def _nomes_solicitados_from_env() -> list[str]:
    raw = ""
    for key in (ENV_CHAVE_BUSCA, ENV_CHAVE_BUSCA_LEGADA):
        raw = str(os.getenv(key, "")).strip()
        if raw:
            break
    if not raw:
        return []
    txt = raw.replace("\\n", "\n")
    vals = [v.strip() for v in re.split(r"[|\n;,]+", txt) if v and v.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for v in vals:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def _find_repo_root_for_env(start: Path) -> Path:
    cur = Path(start).resolve()
    for cand in [cur, *cur.parents]:
        if (cand / "requirements.txt").exists():
            return cand
    return cur


def _path_under_base(path: Path, base: Path) -> bool:
    try:
        path_txt = str(Path(path).resolve())
    except Exception:
        path_txt = str(path)
    try:
        base_txt = str(Path(base).resolve())
    except Exception:
        base_txt = str(base)
    path_txt = path_txt.replace("/", "\\").rstrip("\\").upper()
    base_txt = base_txt.replace("/", "\\").rstrip("\\").upper()
    return bool(path_txt == base_txt or path_txt.startswith(base_txt + "\\"))


def _env_persist_enabled(repo_root: Path, script_dir: Path) -> bool:
    # No compartilhamento Z:\Nicholas Birochi nao persistimos nada em arquivos .env.
    bloqueio_base = Path(r"Z:\Nicholas Birochi")
    if _path_under_base(script_dir, bloqueio_base):
        return False
    if _path_under_base(repo_root, bloqueio_base):
        return False
    return True


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if (not line) or line.startswith("#") or ("=" not in line):
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        val = val.strip().strip("'").strip('"')
        if key not in os.environ:
            os.environ[key] = val


def _tipo_busca_normalizado(raw: str) -> str:
    val = str(raw or "").strip().lower()
    if val in {"nome", "nome completo", "nome_completo"}:
        return TIPO_BUSCA_NOME
    if val in {"chapa", "cadastro", "numero_pessoal", "numero pessoal"}:
        return TIPO_BUSCA_CHAPA
    if val == "cpf":
        return TIPO_BUSCA_CPF
    if val == TIPO_BUSCA_AUTO:
        return TIPO_BUSCA_AUTO
    return TIPO_BUSCA_AUTO


def _env_encode_value(val: str) -> str:
    txt = str(val or "")
    txt = txt.replace("\r", "").replace("\n", "\\n")
    txt = txt.replace("'", "\\'")
    return f"'{txt}'"


def _upsert_env_file(path: Path, updates: dict[str, str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    idx_by_key: dict[str, int] = {}
    for i, raw in enumerate(lines):
        line = str(raw or "").strip()
        if (not line) or line.startswith("#") or ("=" not in line):
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            idx_by_key[key] = i
    for k, v in updates.items():
        line_new = f"{k}={_env_encode_value(v)}"
        if k in idx_by_key:
            lines[idx_by_key[k]] = line_new
        else:
            lines.append(line_new)
    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def _remove_env_keys(path: Path, keys_to_remove: set[str]) -> None:
    path = Path(path)
    if (not path.exists()) or (not keys_to_remove):
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    for raw in lines:
        line = str(raw or "")
        txt = line.strip()
        if (not txt) or txt.startswith("#") or ("=" not in txt):
            out_lines.append(line)
            continue
        key = txt.split("=", 1)[0].strip()
        if key in keys_to_remove:
            continue
        out_lines.append(line)
    content = "\n".join(out_lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def _sync_env_values(
    repo_root: Path,
    script_dir: Path,
    updates: dict[str, str],
    remove_keys: list[str] | None = None,
) -> list[Path]:
    keys_remove_set = {str(k or "").strip() for k in list(remove_keys or []) if str(k or "").strip()}
    written: list[Path] = []
    candidates = [repo_root / ".env", script_dir / ".env"]
    seen: set[str] = set()
    for p in candidates:
        key = str(Path(p).resolve())
        if key in seen:
            continue
        seen.add(key)
        if keys_remove_set:
            _remove_env_keys(Path(p), keys_remove_set)
        _upsert_env_file(Path(p), updates)
        written.append(Path(p))
    for k, v in updates.items():
        os.environ[str(k)] = str(v)
    for k in keys_remove_set:
        if k in updates:
            continue
        if k in os.environ:
            os.environ.pop(k, None)
    return written


def _split_targets_from_text(raw: str, tipo_busca: str) -> list[str]:
    txt = str(raw or "").replace("\r", "\n")
    out: list[str] = []
    if tipo_busca in {TIPO_BUSCA_CHAPA, TIPO_BUSCA_CPF}:
        chunks = re.split(r"[\n;,|]+", txt)
        for item in chunks:
            dig = "".join(ch for ch in str(item or "") if ch.isdigit())
            if dig:
                out.append(dig)
    else:
        chunks = re.split(r"[\n;|]+", txt)
        for item in chunks:
            val = re.sub(r"\s+", " ", str(item or "")).strip()
            if val:
                out.append(val)
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = _normalize_name_match(item) if tipo_busca == TIPO_BUSCA_NOME else item
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def _targets_to_env_value(targets: list[str]) -> str:
    return "|".join(str(x or "").strip() for x in targets if str(x or "").strip())


def _safe_int(raw: object, default: int) -> int:
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _run_cmd_text(args: list[str]) -> str:
    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        return str(cp.stdout or "")
    except Exception:
        return ""


def _pids_listening_tcp_port(port: int) -> set[int]:
    out = _run_cmd_text(["netstat", "-ano", "-p", "tcp"])
    pids: set[int] = set()
    port_txt = str(int(max(port, 1)))
    for raw in out.splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        cols = re.split(r"\s+", line)
        if len(cols) < 5:
            continue
        if str(cols[0]).strip().upper() != "TCP":
            continue
        local_addr = str(cols[1] or "").strip()
        state = str(cols[3] or "").strip().upper()
        pid_txt = str(cols[4] or "").strip()
        if state != "LISTENING":
            continue
        if local_addr.rsplit(":", 1)[-1] != port_txt:
            continue
        if pid_txt.isdigit():
            pids.add(int(pid_txt))
    return pids


def _taskkill_pid(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    cp = subprocess.run(
        ["taskkill", "/PID", str(int(pid)), "/F", "/T"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    return bool(cp.returncode == 0)


def _reiniciar_instancias_web(web_port: int) -> None:
    current_pid = int(os.getpid())
    killed: set[int] = set()

    # No .exe empacotado, encerra instancias anteriores do mesmo executavel.
    exe_name = str(Path(getattr(sys, "executable", "") or "").name).strip()
    if bool(getattr(sys, "frozen", False)) and exe_name:
        out = _run_cmd_text(["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/FO", "CSV", "/NH"])
        for row in csv.reader(out.splitlines()):
            if (not row) or (len(row) < 2):
                continue
            if str(row[0] or "").strip().upper().startswith("INFO:"):
                continue
            pid_digits = "".join(ch for ch in str(row[1] or "") if ch.isdigit())
            if not pid_digits:
                continue
            pid = int(pid_digits)
            if pid == current_pid:
                continue
            if _taskkill_pid(pid):
                killed.add(pid)

    # Garante porta livre para subir novamente ao abrir o executavel.
    for pid in sorted(_pids_listening_tcp_port(int(max(web_port, 1)))):
        if pid == current_pid:
            continue
        if _taskkill_pid(pid):
            killed.add(pid)

    if killed:
        lst = ", ".join(str(p) for p in sorted(killed))
        print(f"[INFO] Reinicio solicitado: instancias anteriores encerradas ({lst}).")


def _pasta_base_consulta(_script_dir: Path) -> Path:
    return Path(PASTA_BASE_CONSULTA)


def _log_web_error(script_dir: Path, exc: Exception) -> None:
    try:
        log_path = Path(script_dir) / WEB_ERROR_LOG
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        chunk = f"[{now}] {type(exc).__name__}: {exc}\n{tb}\n{'-'*90}\n"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(chunk)
    except Exception:
        pass


def _load_relatorio_module():
    here = Path(__file__).resolve()
    doc_dir = here.parent.parent
    candidatos = [
        here.with_name("gerar_relatorios_por_pessoa.py"),
        doc_dir / "Irregularidade de 999 como Trajeto" / "gerar_relatorios_por_pessoa.py",
        doc_dir / "Irregularidade de 999 como Trajeto" / "irregularidade_999_como_trajeto" / "gerar_relatorios_por_pessoa.py",
        doc_dir / "Analisando Irregularidades dos Registros" / "irregularidade_999_como_trajeto" / "gerar_relatorios_por_pessoa.py",
    ]
    mod_path = None
    vistos: set[str] = set()
    for cand in candidatos:
        key = str(cand)
        if key in vistos:
            continue
        vistos.add(key)
        if cand.exists():
            mod_path = cand
            break
    if mod_path is None:
        tentativas = "\n".join(f"- {p}" for p in candidatos)
        raise FileNotFoundError(f"Arquivo nao encontrado. Caminhos tentados:\n{tentativas}")
    spec = importlib.util.spec_from_file_location("relatorio_999_mod", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nao foi possivel carregar modulo: {mod_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_ascii_upper(txt: str) -> str:
    t = unicodedata.normalize("NFKD", str(txt or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return t.upper()


def _formatar_numero_pessoal(val: str) -> str:
    v = str(val or "").strip()
    dig = "".join(ch for ch in v if ch.isdigit())
    if dig.startswith("00") and (len(dig) > 2):
        dig = dig[2:]
    return dig or v


def _rows_from_sources(fichas: list[dict[str, Any]], linhas: list[str] | None = None) -> list[list[str]]:
    fichas = list(fichas or [])
    if fichas:
        ord_f = {"FUNCIONAIS": 0, "PESSOAIS": 1, "FICHA": 2}
        fichas = sorted(
            fichas,
            key=lambda x: (
                ord_f.get(_normalize_ascii_upper(str(x.get("tipo") or "")), 9),
                str(x.get("url") or ""),
            ),
        )

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
        "CLIQUE AQUI",
        "ENDERECO INCORRETO",
        "ENDEREÇO INCORRETO",
    }
    keep_tokens = {"NUMERO PESSOAL", "NO PESSOAL", "NOME", "UNIDADE ORGANIZACIONAL", "EMPRESA", "FUNCAO"}
    merged: dict[str, dict[str, Any]] = {}
    order_keys: list[str] = []

    def _add_row(k: str, v: str) -> None:
        kk = re.sub(r"\s+", " ", str(k or "")).strip(" \t\r\n:|-")
        vv = re.sub(r"\s+", " ", str(v or "")).strip(" \t\r\n|")
        if (not kk) or (not vv):
            return
        kvu = _normalize_ascii_upper(f"{kk} {vv}")
        if any(t in kvu for t in tokens_menu) and (not any(t in kvu for t in keep_tokens)):
            return
        ku = _normalize_ascii_upper(kk)
        if ku in {"NUMERO PESSOAL", "NO PESSOAL"}:
            vv = _formatar_numero_pessoal(vv)
        if ku not in merged:
            merged[ku] = {"campo": kk, "vals": [vv]}
            order_keys.append(ku)
            return
        if vv not in merged[ku]["vals"]:
            merged[ku]["vals"].append(vv)

    for ficha in fichas:
        for k, v in list(ficha.get("campos") or []):
            _add_row(str(k), str(v))

    if not merged:
        for ln in list(linhas or []):
            txt = str(ln or "")
            if ("|" not in txt) or txt.startswith("[PASSO") or txt.startswith("[DEBUG"):
                continue
            parts = [p.strip() for p in txt.split("|") if p.strip()]
            if len(parts) >= 2:
                _add_row(parts[0], parts[1])

    rows = [[merged[k]["campo"], " | ".join(merged[k]["vals"])] for k in order_keys]
    return rows


def _rows_from_result(info: dict[str, Any]) -> list[list[str]]:
    return _rows_from_sources(list(info.get("fichas") or []), list(info.get("linhas") or []))


def _extract_chapa_from_url(url_text: str) -> str:
    m = re.search(r"[?&]chapa=([0-9]+)", str(url_text or ""), flags=re.I)
    return _formatar_numero_pessoal(str(m.group(1))) if m else ""


def _extract_row_first(rows: list[list[str]], keys: set[str]) -> str:
    for k, v in rows:
        if _normalize_ascii_upper(k) in keys:
            return str(v or "").strip()
    return ""


def _first_existing_path(candidates: list[str]) -> str:
    for cand in candidates:
        p = str(cand or "").strip()
        if p and Path(p).exists():
            return p
    return ""


def _split_items_for_display(txt: str) -> list[str]:
    raw = str(txt or "").replace("\r", "\n")
    parts = [p.strip() for p in re.split(r"\s*(?:\||;|\n)\s*", raw) if p.strip()]
    return parts


def _split_items_for_name_match(txt: str) -> list[str]:
    raw = str(txt or "").replace("\r", "\n")
    parts = [p.strip(" \t\r\n|:") for p in re.split(r"\s*(?:\||;|,|/|\n)\s*", raw) if p.strip()]
    return parts


def _normalize_name_match(txt: str) -> str:
    t = _normalize_ascii_upper(str(txt or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _iter_nomes_candidatos(info: dict[str, Any]):
    for ficha in list(info.get("fichas") or []):
        for k, v in list(ficha.get("campos") or []):
            if _normalize_ascii_upper(str(k or "")) != "NOME":
                continue
            val = str(v or "").strip()
            if val:
                yield val
            for part in _split_items_for_name_match(val):
                if part:
                    yield part

    for ln in list(info.get("linhas") or []):
        txt = str(ln or "").strip()
        if (not txt) or txt.startswith("[PASSO") or txt.startswith("[DEBUG"):
            continue
        txt_u = _normalize_ascii_upper(txt)
        if "NOME" not in txt_u:
            continue
        matched = False
        if "|" in txt:
            parts = [p.strip() for p in txt.split("|")]
            for i in range(0, len(parts) - 1):
                if _normalize_ascii_upper(parts[i]) != "NOME":
                    continue
                val = str(parts[i + 1] or "").strip()
                if val:
                    yield val
                    for part in _split_items_for_name_match(val):
                        if part:
                            yield part
                matched = True
                break
        if matched:
            continue
        m = re.search(r"\bNOME\b\s*[:\-]\s*(.+)$", txt, flags=re.I)
        if m:
            val = str(m.group(1) or "").strip()
            if val:
                yield val
                for part in _split_items_for_name_match(val):
                    if part:
                        yield part


def _nome_exato_presente(info: dict[str, Any], nome_alvo: str) -> bool:
    alvo = _normalize_name_match(nome_alvo)
    if not alvo:
        return True

    for cand in _iter_nomes_candidatos(info):
        if _normalize_name_match(cand) == alvo:
            return True
    return False


def _aplicar_restricao_nome_exato(info: dict[str, Any], nome_alvo: str) -> dict[str, Any]:
    out = dict(info or {})
    if not str(nome_alvo or "").strip():
        return out
    if not bool(out.get("ok")):
        return out
    if _nome_exato_presente(out, nome_alvo):
        return out

    out["ok"] = False
    out["mensagem"] = MENSAGEM_NOME_NAO_ENCONTRADO
    out["cadastro"] = ""
    out["url_final"] = ""
    out["linhas"] = []
    out["fichas"] = []
    out["foto_path"] = ""
    out["fotos_por_chapa"] = {}
    out["print_path"] = ""
    return out


def _mensagem_indica_nao_encontrado_nome(msg: str) -> bool:
    txt = _normalize_ascii_upper(str(msg or ""))
    if not txt:
        return False
    pads = (
        "CONSULTA SEM RETORNO DE FICHA",
        "RESULTADO NAO ENCONTRADO",
        "NENHUM REGISTRO COM NOME IDENTICO",
    )
    return any(p in txt for p in pads)


def _padronizar_mensagem_nome(info: dict[str, Any]) -> dict[str, Any]:
    out = dict(info or {})
    if bool(out.get("ok")):
        return out
    if _mensagem_indica_nao_encontrado_nome(str(out.get("mensagem") or "")):
        out["mensagem"] = MENSAGEM_NOME_NAO_ENCONTRADO
    return out


def _profiles_from_result(info: dict[str, Any]) -> list[dict[str, Any]]:
    fichas = list(info.get("fichas") or [])
    linhas = list(info.get("linhas") or [])
    msg = str(info.get("mensagem") or "").strip()
    ok = bool(info.get("ok"))
    nome_solicitado = str(info.get("nome_solicitado") or "").strip()
    cadastro_base = _formatar_numero_pessoal(str(info.get("cadastro") or "").strip())

    print_path = str(info.get("print_path") or "").strip()
    foto_path = str(info.get("foto_path") or "").strip()
    fallback_img = ""

    fotos_map_raw = dict(info.get("fotos_por_chapa") or {})
    fotos_map: dict[str, str] = {}
    for k, v in fotos_map_raw.items():
        kk = _formatar_numero_pessoal(str(k or ""))
        vv = str(v or "").strip()
        if kk and vv:
            fotos_map[kk] = vv
    fallback_img = _first_existing_path([print_path, foto_path, *list(fotos_map.values())])

    foto_por_nome: dict[str, str] = {}
    for ficha in fichas:
        chapa_ficha = _formatar_numero_pessoal(str(ficha.get("chapa") or "").strip())
        if not chapa_ficha:
            chapa_ficha = _extract_chapa_from_url(str(ficha.get("url") or ""))
        if not chapa_ficha:
            for k, v in list(ficha.get("campos") or []):
                if _normalize_ascii_upper(str(k or "")) in {"NUMERO PESSOAL", "NO PESSOAL"}:
                    chapa_ficha = _formatar_numero_pessoal(v)
                    if chapa_ficha:
                        break
        nome_ficha = ""
        for k, v in list(ficha.get("campos") or []):
            if _normalize_ascii_upper(str(k or "")) == "NOME":
                nome_ficha = str(v or "").strip()
                if nome_ficha:
                    break
        nome_key = _normalize_name_match(nome_ficha)
        if (not nome_key) or (not chapa_ficha):
            continue
        img_ficha = str(fotos_map.get(chapa_ficha) or "").strip()
        if img_ficha:
            # Quando surgir nova chapa para a mesma pessoa, a foto mais recente substitui a anterior.
            foto_por_nome[nome_key] = img_ficha

    if not fichas:
        rows = _rows_from_sources([], linhas)
        cad = cadastro_base or _formatar_numero_pessoal(_extract_row_first(rows, {"NUMERO PESSOAL", "NO PESSOAL"}))
        nome = nome_solicitado or _extract_row_first(rows, {"NOME"})
        return [
            {
                "cadastro": cad,
                "nome": nome,
                "rows": rows,
                "ok": ok,
                "mensagem": msg,
                "img_path": fallback_img,
            }
        ]

    groups: dict[str, list[dict[str, Any]]] = {}
    order_keys: list[str] = []
    for ficha in fichas:
        chave = _formatar_numero_pessoal(str(ficha.get("chapa") or "").strip())
        if not chave:
            chave = _extract_chapa_from_url(str(ficha.get("url") or ""))
        if not chave:
            for k, v in list(ficha.get("campos") or []):
                if _normalize_ascii_upper(k) in {"NUMERO PESSOAL", "NO PESSOAL"}:
                    chave = _formatar_numero_pessoal(v)
                    break
        if not chave:
            chave = f"SEM_CHAPA_{len(order_keys) + 1}"
        if chave not in groups:
            groups[chave] = []
            order_keys.append(chave)
        groups[chave].append(ficha)

    profiles: list[dict[str, Any]] = []
    for gk in order_keys:
        gf = groups[gk]
        rows = _rows_from_sources(gf, [])
        cad_row = _formatar_numero_pessoal(_extract_row_first(rows, {"NUMERO PESSOAL", "NO PESSOAL"}))
        nome_row = _extract_row_first(rows, {"NOME"})
        cad = cad_row or ("" if gk.startswith("SEM_CHAPA_") else gk) or cadastro_base
        nome = nome_row or nome_solicitado
        nome_key = _normalize_name_match(nome)
        img = _first_existing_path(
            [
                fotos_map.get(cad, ""),
                fotos_map.get(cad_row, ""),
                foto_por_nome.get(nome_key, ""),
                fallback_img if len(order_keys) == 1 else "",
            ]
        )
        profiles.append(
            {
                "cadastro": cad,
                "nome": nome,
                "rows": rows,
                "ok": ok,
                "mensagem": msg,
                "img_path": img,
            }
        )

    if (len(profiles) == 1) and (not profiles[0]["rows"]):
        profiles[0]["rows"] = _rows_from_sources([], linhas)
        if not profiles[0]["cadastro"]:
            profiles[0]["cadastro"] = cadastro_base
        if (not profiles[0]["nome"]) and nome_solicitado:
            profiles[0]["nome"] = nome_solicitado

    return profiles


def _best_header_text(cad: str, nome: str, rows: list[list[str]]) -> str:
    cad = str(cad or "").strip()
    nome = str(nome or "").strip()
    cad_row = ""
    nome_row = ""
    for k, v in rows:
        ku = _normalize_ascii_upper(k)
        if (not cad_row) and ku in {"NUMERO PESSOAL", "NO PESSOAL"}:
            cad_row = _formatar_numero_pessoal(v)
        if (not nome_row) and ku == "NOME":
            nome_row = str(v or "").strip()
    cad_final = cad or cad_row
    nome_final = nome or nome_row
    if cad_final and nome_final:
        return f"{cad_final} - {nome_final}"
    if nome_final:
        return nome_final
    if cad_final:
        return cad_final
    return "Registro sem identificacao"


def _render_pdf_page(pdf, profile: dict[str, Any], idx: int, total: int) -> None:
    rows = list(profile.get("rows") or [])
    title_person = _best_header_text(str(profile.get("cadastro") or ""), str(profile.get("nome") or ""), rows)
    ok = bool(profile.get("ok"))
    msg = str(profile.get("mensagem") or "").strip()
    img_path = str(profile.get("img_path") or "").strip()
    has_img = bool(img_path and Path(img_path).exists())

    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    ax.axis("off")
    fig.suptitle("Consulta Pessoal - Relatorio Consolidado", fontsize=15, fontweight="bold", y=0.975)

    ax.text(
        0.02,
        0.93,
        title_person,
        fontsize=12,
        fontweight="bold",
        color="white",
        ha="left",
        va="top",
        transform=ax.transAxes,
        bbox=dict(facecolor=COR_DESTAQUE, edgecolor=COR_DESTAQUE, boxstyle="round,pad=0.35"),
    )
    ax.text(
        0.02,
        0.875,
        f"Status: {'OK' if ok else 'FALHA'}",
        fontsize=10,
        fontweight="bold",
        color="white",
        ha="left",
        va="top",
        transform=ax.transAxes,
        bbox=dict(facecolor=COR_DESTAQUE, edgecolor=COR_DESTAQUE, boxstyle="round,pad=0.25"),
    )

    y_msg = 0.83
    for ln in textwrap.wrap(msg or "Sem mensagem.", width=130, break_long_words=False, break_on_hyphens=False)[:4]:
        ax.text(0.02, y_msg, ln, fontsize=9.2, ha="left", va="top", transform=ax.transAxes)
        y_msg -= 0.028

    if rows:
        def _wrap(txt: str, width: int) -> str:
            parts = _split_items_for_display(txt)
            if not parts:
                base = str(txt or "").strip()
                parts = [base] if base else []
            out = [textwrap.fill(p, width=max(20, int(width)), break_long_words=False, break_on_hyphens=False) for p in parts]
            return "\n".join(out) if out else ""

        rows_fmt: list[list[str]] = []
        row_units: list[float] = []
        for campo, valor in rows:
            c = _wrap(campo, 28)
            v = _wrap(valor, 68)
            rows_fmt.append([c, v])
            lc = max(c.count("\n") + 1, v.count("\n") + 1)
            row_units.append(float(lc) + 0.25)

        width_tbl = 0.62 if has_img else 0.95
        ax_tbl = fig.add_axes([0.02, 0.05, width_tbl, 0.73])
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
                cell.set_facecolor(COR_CABECALHO_TABELA)
                cell.set_text_props(color="white", weight="bold")
                cell.set_height(unit_h * header_units)
            elif c == 0:
                cell.set_facecolor(COR_CAMPO)
            else:
                cell.set_facecolor(COR_VALOR)
            if r > 0:
                idx_row = r - 1
                if 0 <= idx_row < len(row_units):
                    cell.set_height(unit_h * row_units[idx_row])
    else:
        ax.text(0.02, 0.72, "Sem dados estruturados retornados.", fontsize=9.8, ha="left", va="top", transform=ax.transAxes)

    if has_img:
        try:
            img = plt.imread(img_path)
            ax_img = fig.add_axes([0.67, 0.30, 0.30, 0.46])
            ax_img.imshow(img)
            ax_img.axis("off")
            ax_img.set_title(
                "Imagem Consulta Pessoal",
                fontsize=9.0,
                color="white",
                pad=4,
                bbox=dict(facecolor=COR_DESTAQUE, edgecolor=COR_DESTAQUE, boxstyle="round,pad=0.2"),
            )
        except Exception:
            pass

    ax.text(
        0.985,
        0.02,
        f"Pagina {idx}/{total}",
        fontsize=8.8,
        ha="right",
        va="bottom",
        transform=ax.transAxes,
        color="#333333",
    )
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.03)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _render_pdf_capa(
    pdf,
    out_pdf: Path,
    data_referencia: date,
    solicitante: str,
    total_consultados: int,
    total_paginas: int,
    total_ok: int,
    total_falha: int,
) -> None:
    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    ax.axis("off")
    fig.patch.set_facecolor("white")

    titulo = "Consulta Pessoal - Relatorio Consolidado"
    subtitulo = "Capa"
    data_txt = _data_pt_br(data_referencia)

    ax.text(
        0.5,
        0.79,
        titulo,
        fontsize=24,
        fontweight="bold",
        color=COR_DESTAQUE,
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.72,
        subtitulo,
        fontsize=14,
        color="#3A5E9D",
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.60,
        f"Data de criacao: {data_txt}",
        fontsize=13,
        color="#202020",
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.53,
        f"Solicitante: {solicitante or 'Nao informado no .env'}",
        fontsize=11,
        color="#202020",
        ha="center",
        va="center",
        transform=ax.transAxes,
    )

    resumo = [
        f"Total consultados: {total_consultados}",
        f"Paginas de pessoas: {total_paginas}",
        f"OK: {total_ok}",
        f"Falha: {total_falha}",
    ]
    y = 0.37
    for linha in resumo:
        ax.text(
            0.5,
            y,
            linha,
            fontsize=12,
            color="#202020",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        y -= 0.06

    ax.text(
        0.5,
        0.08,
        "Gerado automaticamente por consulta_pessoal.py",
        fontsize=9.5,
        color="#4A4A4A",
        ha="center",
        va="center",
        transform=ax.transAxes,
    )

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _gerar_pdf_unico(
    resultados: list[dict[str, Any]],
    out_pdf: Path,
    data_referencia: date,
    solicitante: str,
) -> str:
    if (plt is None) or (PdfPages is None):
        return ""
    if not resultados:
        return ""
    pages: list[dict[str, Any]] = []
    for info in resultados:
        pages.extend(_profiles_from_result(info))
    if not pages:
        return ""
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    total_ok = sum(1 for r in resultados if bool(r.get("ok")))
    total_falha = len(resultados) - total_ok
    with PdfPages(out_pdf) as pdf:
        total = len(pages)
        _render_pdf_capa(
            pdf,
            out_pdf=out_pdf,
            data_referencia=data_referencia,
            solicitante=solicitante,
            total_consultados=len(resultados),
            total_paginas=total,
            total_ok=total_ok,
            total_falha=total_falha,
        )
        for i, profile in enumerate(pages, start=1):
            _render_pdf_page(pdf, profile, i, total)
    return str(out_pdf)


def _docx_paragraph(texto: str, *, bold: bool = False) -> str:
    txt = str(texto or "")
    if not txt:
        return "<w:p/>"
    run_props = "<w:rPr><w:b/></w:rPr>" if bool(bold) else ""
    safe_txt = html_escape(txt, quote=False)
    return (
        "<w:p>"
        "<w:r>"
        f"{run_props}"
        f"<w:t xml:space=\"preserve\">{safe_txt}</w:t>"
        "</w:r>"
        "</w:p>"
    )


def _docx_page_break() -> str:
    return "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"


def _docx_image_content_type(path: Path) -> tuple[str, str] | None:
    ext = str(path.suffix or "").strip().lower()
    if ext == ".png":
        return ("png", "image/png")
    if ext in {".jpg", ".jpeg"}:
        return ("jpg", "image/jpeg")
    if ext == ".gif":
        return ("gif", "image/gif")
    if ext == ".bmp":
        return ("bmp", "image/bmp")
    return None


def _image_size_px(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    if len(data) < 24:
        return None
    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        w = int.from_bytes(data[16:20], "big", signed=False)
        h = int.from_bytes(data[20:24], "big", signed=False)
        if w > 0 and h > 0:
            return (w, h)
        return None
    # GIF
    if data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
        w = int.from_bytes(data[6:8], "little", signed=False)
        h = int.from_bytes(data[8:10], "little", signed=False)
        if w > 0 and h > 0:
            return (w, h)
        return None
    # BMP
    if data[:2] == b"BM" and len(data) >= 26:
        w = int.from_bytes(data[18:22], "little", signed=True)
        h = int.from_bytes(data[22:26], "little", signed=True)
        if w > 0 and h > 0:
            return (w, h)
        if w > 0 and h < 0:
            return (w, abs(h))
        return None
    # JPEG
    if data[:2] == b"\xFF\xD8":
        i = 2
        while i + 8 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            i += 2
            if marker in {0xD8, 0xD9}:
                continue
            if i + 2 > len(data):
                break
            seg_len = int.from_bytes(data[i : i + 2], "big", signed=False)
            if seg_len < 2:
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                if i + 7 <= len(data):
                    h = int.from_bytes(data[i + 3 : i + 5], "big", signed=False)
                    w = int.from_bytes(data[i + 5 : i + 7], "big", signed=False)
                    if w > 0 and h > 0:
                        return (w, h)
                break
            i += seg_len
    return None


def _docx_image_extent_emu(path: Path) -> tuple[int, int]:
    max_w = int(2.8 * 914400)  # ~2.8in (encaixe na coluna direita)
    max_h = int(3.2 * 914400)  # ~3.2in
    size_px = _image_size_px(path)
    if (not size_px) or size_px[0] <= 0 or size_px[1] <= 0:
        return (max_w, int(max_h * 0.75))
    w_px, h_px = size_px
    w = int(max(1, round(w_px * 9525)))
    h = int(max(1, round(h_px * 9525)))
    scale = min(max_w / float(w), max_h / float(h), 1.0)
    return (int(max(1, round(w * scale))), int(max(1, round(h * scale))))


def _docx_run_text(texto: str, *, bold: bool = False, color: str = "") -> str:
    txt = str(texto or "")
    parts = txt.splitlines() or [txt]
    rpr_parts: list[str] = []
    if bold:
        rpr_parts.append("<w:b/>")
    if color:
        rpr_parts.append(f"<w:color w:val=\"{color}\"/>")
    rpr = f"<w:rPr>{''.join(rpr_parts)}</w:rPr>" if rpr_parts else ""
    runs: list[str] = []
    for i, part in enumerate(parts):
        safe_txt = html_escape(part if part else " ", quote=False)
        runs.append(f"<w:r>{rpr}<w:t xml:space=\"preserve\">{safe_txt}</w:t></w:r>")
        if i < (len(parts) - 1):
            runs.append("<w:r><w:br/></w:r>")
    return "".join(runs)


def _docx_table_cell(texto: str, *, width_dxa: int, fill: str, bold: bool = False, color: str = "") -> str:
    shd = f"<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"{fill}\"/>" if fill else ""
    tc_pr = (
        "<w:tcPr>"
        f"<w:tcW w:w=\"{int(width_dxa)}\" w:type=\"dxa\"/>"
        f"{shd}"
        "<w:vAlign w:val=\"top\"/>"
        "</w:tcPr>"
    )
    p = "<w:p><w:pPr><w:spacing w:before=\"20\" w:after=\"20\"/></w:pPr>" + _docx_run_text(
        texto, bold=bold, color=color
    ) + "</w:p>"
    return "<w:tc>" + tc_pr + p + "</w:tc>"


def _docx_table_rows(rows: list[list[str]]) -> str:
    tbl_pr = (
        "<w:tblPr>"
        "<w:tblStyle w:val=\"TableGrid\"/>"
        "<w:tblW w:w=\"0\" w:type=\"auto\"/>"
        "<w:tblLayout w:type=\"fixed\"/>"
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:left w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:right w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "</w:tblBorders>"
        "</w:tblPr>"
    )
    campo_w = 3400
    valor_w = 9700
    grid = f"<w:tblGrid><w:gridCol w:w=\"{campo_w}\"/><w:gridCol w:w=\"{valor_w}\"/></w:tblGrid>"

    out_rows: list[str] = []
    header = (
        "<w:tr>"
        + _docx_table_cell("Campo", width_dxa=campo_w, fill="123B82", bold=True, color="FFFFFF")
        + _docx_table_cell("Valor", width_dxa=valor_w, fill="123B82", bold=True, color="FFFFFF")
        + "</w:tr>"
    )
    out_rows.append(header)
    for row in rows:
        if (not isinstance(row, (list, tuple))) or len(row) < 2:
            continue
        campo = str(row[0] or "").strip()
        valor = str(row[1] or "").strip()
        out_rows.append(
            "<w:tr>"
            + _docx_table_cell(campo, width_dxa=campo_w, fill="D4E1F2")
            + _docx_table_cell(valor, width_dxa=valor_w, fill="F1EAD3")
            + "</w:tr>"
        )

    return "<w:tbl>" + tbl_pr + grid + "".join(out_rows) + "</w:tbl>"


def _docx_image_paragraph(rel_id: str, doc_pr_id: int, name: str, cx: int, cy: int) -> str:
    safe_name = html_escape(str(name or "Imagem"), quote=False)
    return (
        "<w:p><w:r><w:drawing>"
        "<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
        f"<wp:extent cx=\"{int(cx)}\" cy=\"{int(cy)}\"/>"
        "<wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>"
        f"<wp:docPr id=\"{int(doc_pr_id)}\" name=\"{safe_name}\"/>"
        "<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect=\"1\"/></wp:cNvGraphicFramePr>"
        "<a:graphic>"
        "<a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        "<pic:pic>"
        "<pic:nvPicPr>"
        f"<pic:cNvPr id=\"{int(doc_pr_id)}\" name=\"{safe_name}\"/>"
        "<pic:cNvPicPr/>"
        "</pic:nvPicPr>"
        "<pic:blipFill>"
        f"<a:blip r:embed=\"{html_escape(rel_id, quote=False)}\"/>"
        "<a:stretch><a:fillRect/></a:stretch>"
        "</pic:blipFill>"
        "<pic:spPr>"
        "<a:xfrm>"
        "<a:off x=\"0\" y=\"0\"/>"
        f"<a:ext cx=\"{int(cx)}\" cy=\"{int(cy)}\"/>"
        "</a:xfrm>"
        "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom>"
        "</pic:spPr>"
        "</pic:pic>"
        "</a:graphicData>"
        "</a:graphic>"
        "</wp:inline>"
        "</w:drawing></w:r></w:p>"
    )


def _docx_table_cell_xml(inner_xml: str, *, width_dxa: int, fill: str = "") -> str:
    shd = f"<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"{fill}\"/>" if fill else ""
    tc_pr = (
        "<w:tcPr>"
        f"<w:tcW w:w=\"{int(width_dxa)}\" w:type=\"dxa\"/>"
        f"{shd}"
        "<w:vAlign w:val=\"top\"/>"
        "</w:tcPr>"
    )
    content = str(inner_xml or "").strip() or "<w:p/>"
    if content.endswith("</w:tbl>"):
        content += "<w:p/>"
    elif not content.endswith("</w:p>"):
        content += "<w:p/>"
    return "<w:tc>" + tc_pr + content + "</w:tc>"


def _docx_profile_side_by_side(rows: list[list[str]], image_xml: str) -> str:
    total_w = 13800
    left_w = 9200
    right_w = total_w - left_w
    left_inner = _docx_table_rows(rows) if rows else _docx_paragraph("Sem dados estruturados retornados.")
    right_inner = str(image_xml or "").strip() or _docx_paragraph("Sem imagem disponivel.")
    tbl_pr = (
        "<w:tblPr>"
        "<w:tblStyle w:val=\"TableGrid\"/>"
        f"<w:tblW w:w=\"{total_w}\" w:type=\"dxa\"/>"
        "<w:tblLayout w:type=\"fixed\"/>"
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:left w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:right w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"D0D8E8\"/>"
        "</w:tblBorders>"
        "</w:tblPr>"
    )
    grid = f"<w:tblGrid><w:gridCol w:w=\"{left_w}\"/><w:gridCol w:w=\"{right_w}\"/></w:tblGrid>"
    row = (
        "<w:tr>"
        + _docx_table_cell_xml(left_inner, width_dxa=left_w)
        + _docx_table_cell_xml(right_inner, width_dxa=right_w)
        + "</w:tr>"
    )
    return "<w:tbl>" + tbl_pr + grid + row + "</w:tbl>"


def _gerar_word_unico(
    resultados: list[dict[str, Any]],
    out_word: Path,
    data_referencia: date,
    solicitante: str,
) -> str:
    if not resultados:
        return ""
    pages: list[dict[str, Any]] = []
    for info in resultados:
        pages.extend(_profiles_from_result(info))
    if not pages:
        return ""
    out_word.parent.mkdir(parents=True, exist_ok=True)
    total_ok = sum(1 for r in resultados if bool(r.get("ok")))
    total_falha = len(resultados) - total_ok

    body_parts: list[str] = [
        _docx_paragraph("Consulta Pessoal - Relatorio Consolidado", bold=True),
        _docx_paragraph(f"Data de criacao: {_data_pt_br(data_referencia)}"),
        _docx_paragraph(f"Solicitante: {solicitante or 'Nao informado no .env'}"),
        _docx_paragraph(
            f"Total consultados: {len(resultados)} | OK: {total_ok} | Falha: {total_falha}"
        ),
    ]
    if pages:
        body_parts.append(_docx_page_break())

    rels_parts: list[str] = []
    media_files: list[tuple[str, bytes, str]] = []
    next_rid = 1
    next_docpr = 1
    total_paginas = len(pages)
    for i, profile in enumerate(pages, start=1):
        rows = list(profile.get("rows") or [])
        title_person = _best_header_text(
            str(profile.get("cadastro") or ""),
            str(profile.get("nome") or ""),
            rows,
        )
        ok = bool(profile.get("ok"))
        msg = str(profile.get("mensagem") or "").strip() or "Sem mensagem."
        body_parts.append(_docx_paragraph(f"{i}/{total_paginas} - {title_person}", bold=True))
        body_parts.append(_docx_paragraph(f"Status: {'OK' if ok else 'FALHA'}", bold=True))
        body_parts.append(_docx_paragraph(f"Mensagem: {msg}"))
        img_block_xml = ""

        img_path = Path(str(profile.get("img_path") or "").strip())
        if img_path.exists() and img_path.is_file():
            img_ct = _docx_image_content_type(img_path)
            if img_ct is not None:
                ext, content_type = img_ct
                rid = f"rId{next_rid}"
                next_rid += 1
                media_name = f"image_{i}_{next_docpr}.{ext}"
                rels_parts.append(
                    "<Relationship "
                    f"Id=\"{rid}\" "
                    "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/image\" "
                    f"Target=\"media/{media_name}\"/>"
                )
                try:
                    media_files.append((media_name, img_path.read_bytes(), content_type))
                    cx, cy = _docx_image_extent_emu(img_path)
                    img_block_xml = _docx_image_paragraph(
                        rel_id=rid,
                        doc_pr_id=next_docpr,
                        name=img_path.name,
                        cx=cx,
                        cy=cy,
                    )
                    next_docpr += 1
                except Exception:
                    pass

        body_parts.append(_docx_profile_side_by_side(rows, img_block_xml))

        if i < total_paginas:
            body_parts.append(_docx_page_break())

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document "
        "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
        "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
        "xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        "<w:body>"
        + "".join(body_parts)
        + (
            "<w:sectPr>"
            "<w:pgSz w:w=\"16838\" w:h=\"11906\" w:orient=\"landscape\"/>"
            "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" "
            "w:header=\"708\" w:footer=\"708\" w:gutter=\"0\"/>"
            "</w:sectPr>"
        )
        + "</w:body>"
        "</w:document>"
    )
    content_types_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Default Extension=\"png\" ContentType=\"image/png\"/>"
        "<Default Extension=\"jpg\" ContentType=\"image/jpeg\"/>"
        "<Default Extension=\"jpeg\" ContentType=\"image/jpeg\"/>"
        "<Default Extension=\"gif\" ContentType=\"image/gif\"/>"
        "<Default Extension=\"bmp\" ContentType=\"image/bmp\"/>"
        "<Override PartName=\"/word/document.xml\" "
        "ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "</Types>"
    )
    rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" "
        "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
        "Target=\"word/document.xml\"/>"
        "</Relationships>"
    )
    document_rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        + "".join(rels_parts)
        + "</Relationships>"
    )
    with zipfile.ZipFile(out_word, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", document_rels_xml)
        for media_name, media_bytes, _content_type in media_files:
            zf.writestr(f"word/media/{media_name}", media_bytes)
    return str(out_word)


def _resultados_para_pdf(resultados: list[dict[str, Any]], tipo_busca: str) -> list[dict[str, Any]]:
    tipo = _tipo_busca_normalizado(tipo_busca)
    itens = list(resultados or [])
    if tipo != TIPO_BUSCA_NOME:
        return itens
    return [r for r in itens if bool(r.get("ok"))]


def _resultados_para_word(resultados: list[dict[str, Any]], tipo_busca: str) -> list[dict[str, Any]]:
    return _resultados_para_pdf(resultados, tipo_busca)


def _split_cadastros(raw: str) -> list[str]:
    vals: list[str] = []
    for x in str(raw or "").replace(";", ",").split(","):
        c = "".join(ch for ch in x if ch.isdigit())
        if c:
            vals.append(c)
    return vals


def _split_nomes(raw: str) -> list[str]:
    vals: list[str] = []
    txt = str(raw or "").replace(";", "\n").replace("|", "\n")
    for x in txt.splitlines():
        n = str(x or "").strip()
        if n:
            vals.append(n)
    return vals


def _read_names_txt(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de nomes nao encontrado: {path}")
    return _split_nomes(path.read_text(encoding="utf-8"))


def _read_targets_csv(path: Path) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            row_lc = {str(k or "").strip().lower(): str(v or "").strip() for k, v in row.items()}
            cad = (
                row_lc.get("cadastro")
                or row_lc.get("chapa")
                or row_lc.get("numero_pessoal")
                or row_lc.get("numero pessoal")
                or ""
            )
            nome = row_lc.get("nome") or ""
            for c in _split_cadastros(cad):
                targets.append({"cadastro": c, "nome": nome})
    return targets


def _merge_targets(
    cadastro_args: list[str],
    cadastros_arg: str,
    input_csv: str,
    nome_args: list[str],
    nomes_arg: str,
    input_nomes: str,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []

    for cad in cadastro_args:
        for c in _split_cadastros(cad):
            merged.append({"cadastro": c, "nome": ""})

    for c in _split_cadastros(cadastros_arg):
        merged.append({"cadastro": c, "nome": ""})

    if input_csv:
        p_csv = Path(input_csv)
        if not p_csv.exists():
            raise FileNotFoundError(f"CSV de entrada nao encontrado: {p_csv}")
        merged.extend(_read_targets_csv(p_csv))

    for nome in nome_args:
        for n in _split_nomes(nome):
            merged.append({"cadastro": "", "nome": n})

    for n in _split_nomes(nomes_arg):
        merged.append({"cadastro": "", "nome": n})

    if input_nomes:
        p_names = Path(input_nomes)
        for n in _read_names_txt(p_names):
            merged.append({"cadastro": "", "nome": n})

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in merged:
        cad = str(item.get("cadastro") or "").strip()
        nome = str(item.get("nome") or "").strip()
        if cad:
            key = f"CAD::{cad}"
        else:
            key = f"NOME::{_normalize_name_match(nome)}"
        if (not cad and not nome) or (key in seen):
            continue
        out.append({"cadastro": cad, "nome": nome})
        seen.add(key)
    return out


def _consultar_item_por_tipo(
    client: Any,
    tipo_busca: str,
    cadastro: str,
    nome: str,
) -> dict[str, Any]:
    tipo = _tipo_busca_normalizado(tipo_busca)
    cad = str(cadastro or "").strip()
    nome_hint = str(nome or "").strip()
    digits = "".join(ch for ch in (cad or nome_hint) if ch.isdigit())
    if tipo == TIPO_BUSCA_CPF:
        termo = cad or nome_hint or digits
        consultar_cpf = getattr(client, "consultar_por_cpf", None)
        if callable(consultar_cpf):
            info_cpf = consultar_cpf(termo)
            if bool(info_cpf.get("ok")):
                if not str(info_cpf.get("cadastro") or "").strip():
                    info_cpf["cadastro"] = digits or termo
                return info_cpf
            # Fallback automatico para chapa quando o valor nao parece CPF.
            if digits:
                info_cad = client.consultar_por_cadastro(digits, nome=nome_hint)
                if bool(info_cad.get("ok")):
                    msg_old = str(info_cad.get("mensagem") or "").strip()
                    info_cad["mensagem"] = (
                        "Entrada ajustada automaticamente para busca por Chapa. "
                        + msg_old
                    ).strip()
                    if not str(info_cad.get("cadastro") or "").strip():
                        info_cad["cadastro"] = digits
                    return info_cad
            return info_cpf
        return client.consultar_por_nome(termo or digits)
    if tipo == TIPO_BUSCA_NOME:
        termo_nome = nome_hint or cad
        info_nome = client.consultar_por_nome(termo_nome)
        info_nome = _aplicar_restricao_nome_exato(info_nome, termo_nome)
        return _padronizar_mensagem_nome(info_nome)
    if tipo == TIPO_BUSCA_CHAPA:
        termo_cad = digits or cad or "".join(ch for ch in nome_hint if ch.isdigit())
        info_cad = client.consultar_por_cadastro(termo_cad, nome=nome_hint)
        if bool(info_cad.get("ok")):
            if not str(info_cad.get("cadastro") or "").strip():
                info_cad["cadastro"] = termo_cad
            return info_cad
        # Fallback automatico: se parece CPF, tenta busca por CPF.
        if len(termo_cad) == 11:
            consultar_cpf = getattr(client, "consultar_por_cpf", None)
            if callable(consultar_cpf):
                info_cpf = consultar_cpf(termo_cad)
                if bool(info_cpf.get("ok")):
                    msg_old = str(info_cpf.get("mensagem") or "").strip()
                    info_cpf["mensagem"] = (
                        "Entrada parece CPF; busca CPF aplicada automaticamente. "
                        + msg_old
                    ).strip()
                    if not str(info_cpf.get("cadastro") or "").strip():
                        info_cpf["cadastro"] = termo_cad
                    return info_cpf
        return info_cad
    if cad:
        return client.consultar_por_cadastro(cad, nome=nome_hint)
    info_nome = client.consultar_por_nome(nome_hint)
    info_nome = _aplicar_restricao_nome_exato(info_nome, nome_hint)
    return _padronizar_mensagem_nome(info_nome)


def _validar_login_site(client: Any) -> dict[str, Any]:
    validar_fn = getattr(client, "validar_login", None)
    if callable(validar_fn):
        try:
            out = dict(validar_fn() or {})
            out.setdefault("ok", False)
            out.setdefault("mensagem", "")
            out.setdefault("url_final", "")
            return out
        except Exception as exc:
            return {"ok": False, "mensagem": f"Falha ao validar login: {exc}", "url_final": ""}
    return {"ok": bool(getattr(client, "enabled", False)), "mensagem": "Validador indisponivel no cliente.", "url_final": ""}


def _image_data_uri(path_raw: str) -> str:
    p = Path(str(path_raw or "").strip())
    if (not p.exists()) or (not p.is_file()):
        return ""
    mime_by_ext = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    mime = mime_by_ext.get(p.suffix.lower(), "")
    if not mime:
        return ""
    try:
        blob = p.read_bytes()
    except Exception:
        return ""
    payload = base64.b64encode(blob).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _build_web_page(
    form_values: dict[str, str],
    status_msgs: list[tuple[bool, str]],
    result_rows: list[dict[str, Any]],
    resumo: list[str],
    pdf_path: str,
    word_path: str,
) -> str:
    mode = _tipo_busca_normalizado(form_values.get("tipo_busca", TIPO_BUSCA_NOME))
    if mode == TIPO_BUSCA_AUTO:
        mode = TIPO_BUSCA_NOME

    def _sel(val: str) -> str:
        return " selected" if mode == val else ""

    status_toasts_json = json.dumps(
        [
            {"ok": bool(ok), "msg": str(msg or "").strip()}
            for ok, msg in status_msgs
            if str(msg or "").strip()
        ],
        ensure_ascii=False,
    ).replace("</", "<\\/")

    resumo_html = ""
    if resumo:
        linhas = "".join(f"<li>{html_escape(str(x or ''))}</li>" for x in resumo)
        resumo_html = f"<ul class='resumo'>{linhas}</ul>"

    table_html = ""
    if result_rows:
        cards = []
        for idx, row in enumerate(result_rows, start=1):
            rows = list(row.get("rows") or [])
            if not rows:
                rows = [
                    ["Alvo informado", str(row.get("alvo") or "")],
                    ["Status", str(row.get("status") or "")],
                    ["Cadastro retornado", str(row.get("cadastro") or "")],
                    ["Mensagem", str(row.get("mensagem") or "")],
                ]
            preview_rows = rows[:5]
            extra_rows = rows[5:]
            trs_preview = []
            for campo, valor in preview_rows:
                trs_preview.append(
                    "<tr>"
                    f"<td>{html_escape(str(campo or ''))}</td>"
                    f"<td>{html_escape(str(valor or ''))}</td>"
                    "</tr>"
                )
            trs_extra = []
            for campo, valor in extra_rows:
                trs_extra.append(
                    "<tr>"
                    f"<td>{html_escape(str(campo or ''))}</td>"
                    f"<td>{html_escape(str(valor or ''))}</td>"
                    "</tr>"
                )
            title_txt = str(row.get("titulo") or "").strip() or str(row.get("alvo") or "").strip() or f"Item {idx}"
            detalhe_txt = str(row.get("detalhe") or "").strip()
            if detalhe_txt:
                title_txt = f"{title_txt} ({detalhe_txt})"
            alvo_txt = str(row.get("alvo") or "").strip()
            cadastro_txt = str(row.get("cadastro") or "").strip()
            status_txt = str(row.get("status") or "").strip() or ("OK" if bool(row.get("ok")) else "FALHA")
            msg_txt = str(row.get("mensagem") or "").strip() or "Sem mensagem."

            img_src = _image_data_uri(str(row.get("img_path") or ""))
            if img_src:
                img_html = f"<img class='item-image' src='{img_src}' alt='Imagem Consulta Pessoal' />"
            else:
                img_html = "<div class='item-image-empty'>Sem imagem disponivel</div>"
            details_parts = [
                (
                    f"<div class='item-status {'ok' if str(status_txt).strip().upper() == 'OK' else 'err'}'>"
                    f"Status: {html_escape(status_txt)} | Mensagem: {html_escape(msg_txt)}"
                    "</div>"
                )
            ]
            if trs_extra:
                details_parts.append(
                    "<div class='item-table-wrap item-table-more'>"
                    "<table class='item-table'><thead><tr><th>Campo</th><th>Valor</th></tr></thead><tbody>"
                    + "".join(trs_extra)
                    + "</tbody></table>"
                    "</div>"
                )
            details_html = (
                "<details class='item-more'>"
                "<summary><span class='when-closed'>Mostrar mais</span><span class='when-open'>Mostrar menos</span></summary>"
                "<div class='item-more-body'>"
                + "".join(details_parts)
                + "</div>"
                "</details>"
            )

            cards.append(
                "<section class='item-card'>"
                "<div class='item-head'>"
                f"<div class='item-title'>{html_escape(title_txt)}</div>"
                "<div class='item-meta'>"
                f"Alvo: <strong>{html_escape(alvo_txt)}</strong>"
                + (
                    f" | Cadastro: <strong>{html_escape(cadastro_txt)}</strong>"
                    if cadastro_txt
                    else ""
                )
                + "</div>"
                "</div>"
                "<div class='item-grid'>"
                "<div class='item-table-wrap'>"
                "<table class='item-table'><thead><tr><th>Campo</th><th>Valor</th></tr></thead><tbody>"
                + "".join(trs_preview)
                + "</tbody></table>"
                "</div>"
                f"<div class='item-image-wrap'>{img_html}</div>"
                "</div>"
                + details_html
                + "</section>"
            )
        table_html = "<div class='item-list'>" + "".join(cards) + "</div>"

    pdf_html = ""
    if str(pdf_path or "").strip():
        pdf_html = f"<div class='file-path'>PDF gerado: <code>{html_escape(str(pdf_path))}</code></div>"
    word_html = ""
    if str(word_path or "").strip():
        word_html = f"<div class='file-path'>Word gerado: <code>{html_escape(str(word_path))}</code></div>"

    user_val = html_escape(form_values.get("user", ""))
    password_val = html_escape(form_values.get("password", ""))
    solicitante_val = html_escape(form_values.get("solicitante", ""))
    data_ref_val = html_escape(form_values.get("data_referencia", ""))
    lista_val = html_escape(form_values.get("lista_alvos", ""))
    base_url_val = html_escape(form_values.get("base_url", DEFAULT_BASE_URL))

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Consulta Pessoal</title>
  <style>
    :root {{
      --blue: #123B82;
      --blue-soft: #d7ecff;
      --bg: #f4f7fb;
      --card: #ffffff;
      --ok: #146c43;
      --err: #8a1f2d;
      --bd: #d7e0ef;
      --text: #1c2735;
      --font-scale: 1.5;
    }}
    body {{
      margin: 0;
      font-family: Segoe UI, Arial, sans-serif;
      font-size: calc(16px * var(--font-scale));
      background: linear-gradient(180deg, #eef3fb 0%, #f8fbff 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1100px;
      margin: 22px auto;
      padding: 0 14px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--bd);
      border-radius: 12px;
      box-shadow: 0 5px 20px rgba(18, 59, 130, 0.08);
      padding: 18px;
    }}
    h1 {{
      margin: 0 0 14px 0;
      color: var(--blue);
      font-size: calc(24px * var(--font-scale));
    }}
    .grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .grid3 {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    label {{
      font-size: calc(13px * var(--font-scale));
      font-weight: 600;
      display: block;
      margin-bottom: 6px;
    }}
    input, select, textarea {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid #bfd0ea;
      border-radius: 8px;
      padding: 10px 11px;
      font-size: calc(14px * var(--font-scale));
      color: #1e2a3a;
      background: #fff;
    }}
    textarea {{
      min-height: 180px;
      resize: vertical;
      font-family: Consolas, monospace;
    }}
    .row {{
      margin-top: 10px;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      margin-top: 14px;
      flex-wrap: wrap;
    }}
    button {{
      border: 0;
      background: var(--blue);
      color: #fff;
      border-radius: 9px;
      padding: 10px 14px;
      font-size: calc(14px * var(--font-scale));
      cursor: pointer;
      font-weight: 600;
    }}
    button.secondary {{
      background: #3f5f96;
    }}
    .msg {{
      border-radius: 8px;
      padding: 9px 11px;
      margin: 10px 0;
      border: 1px solid transparent;
      font-size: calc(13.5px * var(--font-scale));
    }}
    .msg.ok {{
      background: #eaf7ef;
      color: var(--ok);
      border-color: #b3e2c5;
    }}
    .msg.err {{
      background: #fdeef0;
      color: var(--err);
      border-color: #f3c2ca;
    }}
    .web-toast-stack {{
      position: fixed;
      top: 14px;
      right: 14px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 10px;
      width: min(470px, calc(100vw - 28px));
      pointer-events: none;
    }}
    .web-toast {{
      border-radius: 10px;
      border: 1px solid #bfd0ea;
      background: #eef4ff;
      color: #173459;
      padding: 10px 12px;
      font-size: calc(13px * var(--font-scale));
      box-shadow: 0 10px 24px rgba(10, 25, 58, 0.18);
      opacity: 0;
      transform: translateY(-8px);
      transition: opacity 180ms ease, transform 180ms ease;
    }}
    .web-toast.show {{
      opacity: 1;
      transform: translateY(0);
    }}
    .web-toast.ok {{
      background: #eaf7ef;
      border-color: #b3e2c5;
      color: #145a39;
    }}
    .web-toast.err {{
      background: #fdeef0;
      border-color: #f3c2ca;
      color: #7f1e2c;
    }}
    .item-list {{
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .item-card {{
      border: 1px solid #d9e3f2;
      border-radius: 10px;
      background: #fbfdff;
      padding: 10px;
    }}
    .item-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .item-title {{
      font-size: calc(13.5px * var(--font-scale));
      font-weight: 700;
      color: #123B82;
    }}
    .item-meta {{
      font-size: calc(12px * var(--font-scale));
      color: #3c5278;
    }}
    .item-status {{
      margin-top: 8px;
      border-radius: 7px;
      border: 1px solid transparent;
      padding: 8px 9px;
      font-size: calc(12.5px * var(--font-scale));
    }}
    .item-status.ok {{
      background: #eaf7ef;
      color: #145a39;
      border-color: #b3e2c5;
    }}
    .item-status.err {{
      background: #fdeef0;
      color: #7f1e2c;
      border-color: #f3c2ca;
    }}
    .item-grid {{
      margin-top: 9px;
      display: grid;
      gap: 10px;
      grid-template-columns: minmax(0, 2fr) minmax(220px, 1fr);
      align-items: start;
    }}
    .item-table-wrap {{
      overflow-x: auto;
    }}
    .item-table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 620px;
    }}
    .item-table th, .item-table td {{
      border: 1px solid #d9e3f2;
      padding: 8px 9px;
      font-size: calc(12.5px * var(--font-scale));
      text-align: left;
      vertical-align: top;
    }}
    .item-table th {{
      background: #edf3fc;
      color: #26497f;
    }}
    .item-image-wrap {{
      border: 1px solid #d9e3f2;
      border-radius: 8px;
      background: #ffffff;
      min-height: 220px;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 8px;
    }}
    .item-image {{
      width: 100%;
      max-height: 360px;
      object-fit: contain;
    }}
    .item-image-empty {{
      color: #6d809f;
      font-size: calc(12px * var(--font-scale));
      text-align: center;
    }}
    .item-more {{
      margin-top: 8px;
      border: 1px solid #d3dded;
      border-radius: 8px;
      background: #ffffff;
    }}
    .item-more summary {{
      cursor: pointer;
      list-style: none;
      padding: 8px 10px;
      font-size: calc(12.5px * var(--font-scale));
      font-weight: 600;
      color: #1f4a86;
      user-select: none;
    }}
    .item-more summary::-webkit-details-marker {{
      display: none;
    }}
    .item-more .when-open {{
      display: none;
    }}
    .item-more[open] .when-open {{
      display: inline;
    }}
    .item-more[open] .when-closed {{
      display: none;
    }}
    .item-more-body {{
      padding: 0 10px 10px 10px;
    }}
    .item-more-body .item-status {{
      margin-top: 0;
    }}
    .item-table-more {{
      margin-top: 8px;
    }}
    .hint {{
      margin-top: 6px;
      font-size: calc(12px * var(--font-scale));
      color: #556a89;
    }}
    .resumo {{
      margin: 10px 0 0 0;
      padding-left: 20px;
      font-size: calc(13px * var(--font-scale));
    }}
    .file-path {{
      margin-top: 8px;
      font-size: calc(13px * var(--font-scale));
      color: #2f4d7d;
    }}
    code {{
      background: #f2f6fc;
      border: 1px solid #dce6f5;
      border-radius: 6px;
      padding: 2px 5px;
    }}
    @media (max-width: 920px) {{
      .grid, .grid3 {{
        grid-template-columns: 1fr;
      }}
      .item-grid {{
        grid-template-columns: 1fr;
      }}
      .item-table {{
        min-width: 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>Consulta Pessoal</h1>
      <form method="post">
        <div class="grid">
          <div>
            <label>Usuario</label>
            <input type="text" name="user" value="{user_val}" autocomplete="username" />
          </div>
          <div>
            <label>Senha</label>
            <input type="password" name="password" value="{password_val}" autocomplete="current-password" />
          </div>
        </div>
        <div class="grid3 row">
          <div>
            <label>Tipo de Busca</label>
            <select name="tipo_busca">
              <option value="{TIPO_BUSCA_CHAPA}"{_sel(TIPO_BUSCA_CHAPA)}>Chapa</option>
              <option value="{TIPO_BUSCA_NOME}"{_sel(TIPO_BUSCA_NOME)}>Nome Completo</option>
              <option value="{TIPO_BUSCA_CPF}"{_sel(TIPO_BUSCA_CPF)}>CPF</option>
            </select>
          </div>
          <div>
            <label>Data para Relatório (DD-MM-YYYY)</label>
            <input type="text" name="data_referencia" value="{data_ref_val}" />
          </div>
          <div>
            <label>Solicitante</label>
            <input type="text" name="solicitante" value="{solicitante_val}" />
          </div>
        </div>
        <input type="hidden" name="base_url" value="{base_url_val}" />
        <div class="row">
          <label>Lista de Alvos (Ctrl+V)</label>
          <div class="hint">Cole itens separados por Enter (quebra de linha), ";" ou "|".</div>
        </div>
        <div class="row">
          <textarea name="lista_alvos" placeholder="Cole aqui sua lista">{lista_val}</textarea>
        </div>
        <div class="actions">
          <button type="submit" name="acao" value="validar" class="secondary">Validar Login no Site</button>
          <button type="submit" name="acao" value="executar">Executar Consulta e Gerar PDF</button>
          <button type="submit" name="acao" value="executar_word">Executar Consulta e Gerar Word</button>
        </div>
      </form>
      {resumo_html}
      {pdf_html}
      {word_html}
      {table_html}
    </div>
  </div>
  <div id="web-toast-stack" class="web-toast-stack"></div>
  <script>
    (function () {{
      const items = {status_toasts_json};
      if (!Array.isArray(items) || !items.length) return;
      const stack = document.getElementById("web-toast-stack");
      if (!stack) return;

      function showToast(item) {{
        const cls = item && item.ok ? "ok" : "err";
        const msg = (item && item.msg ? String(item.msg) : "").trim();
        if (!msg) return;
        const div = document.createElement("div");
        div.className = "web-toast " + cls;
        div.textContent = msg;
        stack.appendChild(div);
        requestAnimationFrame(function () {{ div.classList.add("show"); }});
        const hideMs = cls === "ok" ? 1400 : 1900;
        setTimeout(function () {{
          div.classList.remove("show");
          setTimeout(function () {{ div.remove(); }}, 180);
        }}, hideMs);
      }}

      items.forEach(function (item) {{
        showToast(item);
      }});
    }})();
  </script>
</body>
</html>
"""


def _run_web_front(args: argparse.Namespace, script_dir: Path, repo_root: Path) -> None:
    try:
        from flask import Flask, request
    except Exception as exc:
        raise SystemExit(
            "Flask nao encontrado no ambiente. Instale dependencias e rode novamente."
        ) from exc

    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = False
    persistir_env = _env_persist_enabled(repo_root=repo_root, script_dir=script_dir)
    if persistir_env:
        _sync_env_values(
            repo_root=repo_root,
            script_dir=script_dir,
            updates={},
            remove_keys=["CONSULTA_PESSOAL_USER", "CONSULTA_PESSOAL_PASSWORD"],
        )
    else:
        os.environ.pop("CONSULTA_PESSOAL_USER", None)
        os.environ.pop("CONSULTA_PESSOAL_PASSWORD", None)

    @app.route("/", methods=["GET", "POST"])
    def _index() -> str:
        default_mode = TIPO_BUSCA_CHAPA
        data_ref_default = _data_hoje().strftime("%d-%m-%Y")
        default_targets = _nomes_solicitados_from_env()
        form_values: dict[str, str] = {
            "user": "",
            "password": "",
            "tipo_busca": default_mode,
            "data_referencia": data_ref_default,
            "solicitante": _solicitante_from_env(),
            "lista_alvos": "\n".join(default_targets),
            "base_url": str(args.base_url or DEFAULT_BASE_URL).strip(),
            "capturar_print": "1" if bool(args.capturar_print) else "",
            "debug_passos": "1" if bool(args.debug_passos) else "",
            "verify_ssl": "1" if bool(args.verify_ssl) else "",
        }
        status_msgs: list[tuple[bool, str]] = []
        result_rows: list[dict[str, Any]] = []
        resumo: list[str] = []
        pdf_path = ""
        word_path = ""
        try:
            if request.method == "POST":
                form_values = {
                    "user": str(request.form.get("user", "")).strip(),
                    "password": str(request.form.get("password", "")).strip(),
                    "tipo_busca": _tipo_busca_normalizado(request.form.get("tipo_busca", default_mode)),
                    "data_referencia": str(request.form.get("data_referencia", "")).strip() or data_ref_default,
                    "solicitante": str(request.form.get("solicitante", "")).strip(),
                    "lista_alvos": str(request.form.get("lista_alvos", "")).strip(),
                    "base_url": str(request.form.get("base_url", "")).strip() or DEFAULT_BASE_URL,
                    "capturar_print": "1" if str(request.form.get("capturar_print", "")).strip() == "1" else "",
                    "debug_passos": "1" if str(request.form.get("debug_passos", "")).strip() == "1" else "",
                    "verify_ssl": "1" if str(request.form.get("verify_ssl", "")).strip() == "1" else "",
                }
                acao = str(request.form.get("acao", "")).strip().lower()
                tipo_busca = _tipo_busca_normalizado(form_values["tipo_busca"])
                targets = _split_targets_from_text(form_values["lista_alvos"], tipo_busca)
                env_updates = {
                    ENV_CHAVE_BUSCA: _targets_to_env_value(targets),
                    "CONSULTA_PESSOAL_SOLICITANTE_NOME": form_values["solicitante"],
                }
                if persistir_env:
                    env_files = _sync_env_values(
                        repo_root=repo_root,
                        script_dir=script_dir,
                        updates=env_updates,
                        remove_keys=[
                            ENV_CHAVE_BUSCA_LEGADA,
                            "CONSULTA_PESSOAL_USER",
                            "CONSULTA_PESSOAL_PASSWORD",
                        ],
                    )
                    status_msgs.append(
                        (
                            True,
                            f"Variaveis atualizadas no .env (chave unica: {ENV_CHAVE_BUSCA}, sem salvar login/senha): "
                            + ", ".join(str(p) for p in env_files),
                        )
                    )
                else:
                    for k, v in env_updates.items():
                        os.environ[str(k)] = str(v)
                    os.environ.pop(ENV_CHAVE_BUSCA_LEGADA, None)
                    os.environ.pop("CONSULTA_PESSOAL_USER", None)
                    os.environ.pop("CONSULTA_PESSOAL_PASSWORD", None)
                    status_msgs.append(
                        (
                            True,
                            "Modo sem persistencia em .env ativo para este endereco (Z:\\Nicholas Birochi).",
                        )
                    )

                mod = _load_relatorio_module()
                client = mod.ConsultaPessoalClient(
                    base_url=form_values["base_url"],
                    user=form_values["user"],
                    password=form_values["password"],
                    verify_ssl=bool(form_values["verify_ssl"]),
                    capturar_print=bool(form_values["capturar_print"]),
                    debug_passos=bool(form_values["debug_passos"]),
                )

                valid_login = _validar_login_site(client)
                status_msgs.append((bool(valid_login.get("ok")), str(valid_login.get("mensagem") or "")))

                if acao in {"executar", "executar_word"}:
                    if not bool(valid_login.get("ok")):
                        status_msgs.append((False, "Execucao cancelada: login nao validado no site."))
                    elif not targets:
                        status_msgs.append((False, "Nenhum alvo valido informado para consulta."))
                    else:
                        data_ref = _parse_data_referencia(form_values["data_referencia"])
                        solicitante = form_values["solicitante"] or _solicitante_from_env()
                        out_dir = _pasta_base_consulta(script_dir) / PASTA_SAIDA_CONSULTA
                        out_dir.mkdir(parents=True, exist_ok=True)
                        nome_base_rel = _nome_arquivo_relatorio_base(data_ref, solicitante)
                        out_pdf = out_dir / f"{nome_base_rel}.pdf"
                        out_word = out_dir / f"{nome_base_rel}.docx"

                        resultados: list[dict[str, Any]] = []
                        for alvo in targets:
                            if tipo_busca == TIPO_BUSCA_NOME:
                                cad = ""
                                nome = alvo
                            else:
                                cad = alvo
                                nome = ""
                            info = _consultar_item_por_tipo(client, tipo_busca, cad, nome)
                            info["nome_solicitado"] = nome
                            if (not str(info.get("cadastro") or "").strip()) and cad:
                                info["cadastro"] = cad
                            if not cad and (not str(info.get("cadastro") or "").strip()):
                                info["cadastro"] = ""
                            resultados.append(info)
                            profiles = list(_profiles_from_result(info) or [])
                            if not profiles:
                                profiles = [
                                    {
                                        "cadastro": str(info.get("cadastro") or ""),
                                        "nome": str(info.get("nome_solicitado") or ""),
                                        "rows": _rows_from_sources([], list(info.get("linhas") or [])),
                                        "ok": bool(info.get("ok")),
                                        "mensagem": str(info.get("mensagem") or ""),
                                        "img_path": str(info.get("foto_path") or ""),
                                    }
                                ]
                            total_profiles = len(profiles)
                            for p_idx, profile in enumerate(profiles, start=1):
                                rows_profile = list(profile.get("rows") or [])
                                cad_profile = str(profile.get("cadastro") or info.get("cadastro") or "").strip()
                                nome_profile = str(profile.get("nome") or info.get("nome_solicitado") or "").strip()
                                titulo_profile = _best_header_text(cad_profile, nome_profile, rows_profile)
                                detalhe_profile = f"{p_idx}/{total_profiles}" if total_profiles > 1 else ""
                                status_profile = "OK" if bool(profile.get("ok")) else "FALHA"
                                result_rows.append(
                                    {
                                        "alvo": alvo,
                                        "titulo": titulo_profile,
                                        "detalhe": detalhe_profile,
                                        "status": status_profile,
                                        "cadastro": cad_profile,
                                        "mensagem": str(profile.get("mensagem") or info.get("mensagem") or ""),
                                        "rows": rows_profile,
                                        "img_path": str(profile.get("img_path") or ""),
                                        "ok": bool(profile.get("ok")),
                                    }
                                )
                            msg_info = str(info.get("mensagem") or "").strip()
                            if not msg_info:
                                msg_info = "Consulta concluida." if bool(info.get("ok")) else "Nao encontrado."
                            status_msgs.append((bool(info.get("ok")), f"{alvo}: {msg_info}"))

                        resultados_pdf = _resultados_para_pdf(resultados, tipo_busca)
                        resultados_word = _resultados_para_word(resultados, tipo_busca)
                        if acao == "executar":
                            try:
                                pdf_path = _gerar_pdf_unico(resultados_pdf, out_pdf, data_ref, solicitante)
                            except Exception as exc_pdf:
                                _log_web_error(script_dir=script_dir, exc=exc_pdf)
                                pdf_path = ""
                                status_msgs.append(
                                    (
                                        False,
                                        "Falha ao gerar PDF. Veja detalhes em "
                                        + str(Path(script_dir) / WEB_ERROR_LOG),
                                    )
                                )
                        elif acao == "executar_word":
                            try:
                                word_path = _gerar_word_unico(resultados_word, out_word, data_ref, solicitante)
                            except Exception as exc_word:
                                _log_web_error(script_dir=script_dir, exc=exc_word)
                                word_path = ""
                                status_msgs.append(
                                    (
                                        False,
                                        "Falha ao gerar Word. Veja detalhes em "
                                        + str(Path(script_dir) / WEB_ERROR_LOG),
                                    )
                                )
                        cleanup_fn = getattr(mod, "cleanup_consulta_pessoal_imagens_temporarias", None)
                        if callable(cleanup_fn):
                            for info in resultados:
                                try:
                                    cleanup_fn(info)
                                except Exception:
                                    pass
                        total = len(resultados)
                        ok = sum(1 for r in resultados if bool(r.get("ok")))
                        falha = total - ok
                        resumo = [
                            f"Total consultados: {total}",
                            f"OK: {ok}",
                            f"Falha: {falha}",
                        ]
                        if acao == "executar":
                            if (tipo_busca == TIPO_BUSCA_NOME) and (not resultados_pdf):
                                status_msgs.append((False, "Nenhum nome exato encontrado. Nenhum PDF foi gerado."))
                            elif pdf_path:
                                status_msgs.append((True, "PDF gerado com sucesso."))
                            else:
                                status_msgs.append((False, "PDF nao gerado (matplotlib indisponivel ou sem resultados)."))
                        else:
                            if (tipo_busca == TIPO_BUSCA_NOME) and (not resultados_word):
                                status_msgs.append((False, "Nenhum nome exato encontrado. Nenhum Word foi gerado."))
                            elif word_path:
                                status_msgs.append((True, "Word gerado com sucesso."))
                            else:
                                status_msgs.append((False, "Word nao gerado (sem resultados)."))
                        status_msgs.append((falha == 0, f"Execucao concluida. OK: {ok} | Falha: {falha}"))
        except Exception as exc:
            _log_web_error(script_dir=script_dir, exc=exc)
            status_msgs.append(
                (
                    False,
                    "Erro interno na solicitacao. Veja detalhes em "
                    + str(Path(script_dir) / WEB_ERROR_LOG)
                    + f" ({type(exc).__name__}).",
                )
            )

        return _build_web_page(form_values, status_msgs, result_rows, resumo, pdf_path, word_path)

    host = str(args.web_host or "127.0.0.1").strip() or "127.0.0.1"
    port = int(max(_safe_int(args.web_port, 8501), 1))
    print(f"[INFO] Front disponivel em http://{host}:{port}")
    app.run(host=host, port=port, debug=bool(args.web_debug))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consulta Pessoal isolada (reaproveita a mesma logica do gerar_relatorios_por_pessoa.py).",
        epilog=f"Pasta base: {PASTA_BASE_CONSULTA} | Executavel: {EXECUTAVEL_CONSULTA}",
    )
    parser.add_argument("--cadastro", action="append", default=[], help="Cadastro/chapa (pode repetir).")
    parser.add_argument(
        "--cadastros",
        default="",
        help="Lista de cadastros separados por virgula, ex: 4064327,4040086",
    )
    parser.add_argument(
        "--input-csv",
        default="",
        help="CSV com colunas cadastro/chapa/numero_pessoal e opcional nome.",
    )
    parser.add_argument("--nome", action="append", default=[], help="Nome para pesquisa (pode repetir).")
    parser.add_argument(
        "--nomes",
        default="",
        help="Lista de nomes separados por ';' ou '|'.",
    )
    parser.add_argument(
        "--input-nomes",
        default="",
        help="TXT com um nome por linha.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"URL base do portal (padrao: {DEFAULT_BASE_URL})",
    )
    parser.add_argument("--user", default="", help="Usuario (override de CONSULTA_PESSOAL_USER).")
    parser.add_argument("--password", default="", help="Senha (override de CONSULTA_PESSOAL_PASSWORD).")
    parser.add_argument("--verify-ssl", action="store_true", help="Ativa validacao SSL.")
    parser.add_argument("--capturar-print", action="store_true", help="Tenta capturar print da tela.")
    parser.add_argument("--debug-passos", action="store_true", help="Liga logs detalhados da consulta.")
    parser.add_argument("--out-dir", default="", help="Diretorio de saida do PDF.")
    parser.add_argument("--out-pdf", default="", help="Caminho do PDF consolidado (1 pagina por pessoa).")
    parser.add_argument(
        "--data-referencia",
        default="",
        help="Data da capa e do nome automatico do PDF no formato DD-MM-YYYY (default: hoje).",
    )
    parser.add_argument(
        "--env-file",
        default="",
        help="Arquivo .env para carregar credenciais (default: tenta .env da pasta atual e da raiz do repo).",
    )
    parser.add_argument(
        "--tipo-busca",
        default=TIPO_BUSCA_AUTO,
        choices=[TIPO_BUSCA_AUTO, TIPO_BUSCA_CHAPA, TIPO_BUSCA_NOME, TIPO_BUSCA_CPF],
        help="Tipo de busca da lista informada no .env (default: auto).",
    )
    parser.add_argument("--web", action="store_true", help="Sobe um front web para a consulta pessoal.")
    parser.add_argument("--web-host", default="127.0.0.1", help="Host do front web (default: 127.0.0.1).")
    parser.add_argument("--web-port", type=int, default=8501, help="Porta do front web (default: 8501).")
    parser.add_argument("--web-debug", action="store_true", help="Ativa debug do Flask.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    repo_root = _find_repo_root_for_env(script_dir)

    env_candidates: list[Path] = []
    if args.env_file:
        env_candidates.append(Path(args.env_file))
    else:
        env_candidates.append(script_dir / ".env")
        env_candidates.append(Path.cwd() / ".env")
        env_candidates.append(repo_root / ".env")
    seen_env: set[str] = set()
    for p in env_candidates:
        k = str(Path(p))
        if k in seen_env:
            continue
        seen_env.add(k)
        _load_env_file(p)

    if bool(args.web):
        _reiniciar_instancias_web(int(max(_safe_int(args.web_port, 8501), 1)))
        _run_web_front(args=args, script_dir=script_dir, repo_root=repo_root)
        return

    user = str(args.user or os.getenv("CONSULTA_PESSOAL_USER", "")).strip()
    password = str(args.password or os.getenv("CONSULTA_PESSOAL_PASSWORD", "")).strip()
    tipo_busca_env = _tipo_busca_normalizado(os.getenv("CONSULTA_PESSOAL_TIPO_BUSCA", TIPO_BUSCA_AUTO))
    tipo_busca = _tipo_busca_normalizado(args.tipo_busca)
    if tipo_busca == TIPO_BUSCA_AUTO:
        tipo_busca = tipo_busca_env

    targets = _merge_targets(
        args.cadastro,
        args.cadastros,
        args.input_csv,
        args.nome,
        args.nomes,
        args.input_nomes,
    )
    if not targets:
        nomes_env = _nomes_solicitados_from_env()
        if not nomes_env:
            raise SystemExit(
                f"Nenhum alvo informado. Defina {ENV_CHAVE_BUSCA} no .env "
                "(nomes separados por |, ; ou quebra de linha), ou passe --nome/--nomes/--input-nomes."
            )
        if tipo_busca in {TIPO_BUSCA_CHAPA, TIPO_BUSCA_CPF}:
            targets = [{"cadastro": "".join(ch for ch in n if ch.isdigit()), "nome": ""} for n in nomes_env]
            targets = [t for t in targets if str(t.get("cadastro") or "").strip()]
        else:
            targets = [{"cadastro": "", "nome": n} for n in nomes_env]
        print(f"[INFO] Nenhum alvo informado; usando {ENV_CHAVE_BUSCA} com {len(targets)} itens.")

    mod = _load_relatorio_module()
    client = mod.ConsultaPessoalClient(
        base_url=str(args.base_url).strip(),
        user=user,
        password=password,
        verify_ssl=bool(args.verify_ssl),
        capturar_print=bool(args.capturar_print),
        debug_passos=bool(args.debug_passos),
    )

    if not client.enabled:
        raise SystemExit(
            "Consulta pessoal desabilitada. Preencha CONSULTA_PESSOAL_USER/CONSULTA_PESSOAL_PASSWORD "
            "ou passe --user/--password."
        )

    out_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else (_pasta_base_consulta(script_dir) / PASTA_SAIDA_CONSULTA)
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    data_referencia = _parse_data_referencia(args.data_referencia)
    solicitante = _solicitante_from_env()
    out_pdf = (
        Path(args.out_pdf).resolve()
        if args.out_pdf
        else (
            out_dir
            / f"{_nome_arquivo_relatorio_base(data_referencia, solicitante)}.pdf"
        )
    )
    try:
        os.chdir(out_dir)
    except Exception as exc:
        raise RuntimeError(f"Nao foi possivel entrar na pasta de saida: {out_dir}") from exc
    print(f"[INFO] Diretorio de execucao: {Path.cwd()}")

    resultados: list[dict[str, Any]] = []
    for item in targets:
        cad = str(item.get("cadastro") or "").strip()
        nome = str(item.get("nome") or "").strip()
        info = _consultar_item_por_tipo(client, tipo_busca, cad, nome)
        info["nome_solicitado"] = nome
        if not cad and (not str(info.get("cadastro") or "").strip()):
            info["cadastro"] = ""
        resultados.append(info)
        status = "OK" if bool(info.get("ok")) else "FALHA"
        alvo = cad if cad else nome
        print(f"[{status}] {alvo}")
        print(f"       {str(info.get('mensagem') or '').strip()}")

    total = len(resultados)
    ok = sum(1 for r in resultados if bool(r.get("ok")))
    falha = total - ok
    resultados_pdf = _resultados_para_pdf(resultados, tipo_busca)
    pdf_path = _gerar_pdf_unico(resultados_pdf, out_pdf, data_referencia, solicitante)
    cleanup_fn = getattr(mod, "cleanup_consulta_pessoal_imagens_temporarias", None)
    if callable(cleanup_fn):
        for info in resultados:
            try:
                cleanup_fn(info)
            except Exception:
                pass
    print("\nResumo:")
    print(f"- Total consultados: {total}")
    print(f"- OK: {ok}")
    print(f"- Falha: {falha}")
    if (tipo_busca == TIPO_BUSCA_NOME) and (not resultados_pdf):
        print("- PDF : nao gerado (nenhum nome exato encontrado).")
    elif pdf_path:
        print(f"- PDF : {pdf_path}")
    else:
        print("- PDF : nao gerado (matplotlib indisponivel ou sem resultados).")


if __name__ == "__main__":
    main()
