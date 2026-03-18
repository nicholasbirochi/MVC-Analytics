from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sqlite3
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)


def _default_login_db_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root.parent / "_dados_ronda_local" / "project" / "database" / "db_login.sqlite").resolve()


LOGIN_DB_PATH = Path(os.getenv("LOGIN_DB_PATH", str(_default_login_db_path()))).expanduser()


def _hash_password_pbkdf2(password: str) -> str:
    """Gera hash PBKDF2-SHA256 no formato: pbkdf2_sha256$iter$salt$hash."""
    iterations = 200_000
    salt = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${salt}${encoded}"


def _verify_password(stored_value: str | None, provided_password: str) -> bool:
    """Valida senha suportando PBKDF2 e fallback legado em texto puro."""
    if not stored_value:
        return False

    if stored_value.startswith("pbkdf2_sha256$"):
        try:
            _, raw_iterations, salt, expected = stored_value.split("$", 3)
            iterations = int(raw_iterations)
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                provided_password.encode("utf-8"),
                salt.encode("utf-8"),
                iterations,
            )
            computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
            return hmac.compare_digest(computed, expected)
        except Exception:
            return False

    # Fallback legado para manter compatibilidade.
    return hmac.compare_digest(str(stored_value), str(provided_password))


def autenticar(username: str, senha: str) -> bool:
    """Autentica o usuário usando banco local externo ao repositório."""
    try:
        with sqlite3.connect(str(LOGIN_DB_PATH)) as conn:
            cursor = conn.cursor()
            # Compatível com esquemas que usam username, email ou nome como identificador.
            cursor.execute(
                """
                SELECT rowid, senha
                FROM usuarios
                WHERE (username = ? OR email = ? OR nome = ?)
                LIMIT 1
                """,
                (username, username, username),
            )
            row = cursor.fetchone()
            if row is None:
                return False

            rowid, stored_password = row
            is_valid = _verify_password(stored_password, senha)
            if not is_valid:
                return False

            # Migração transparente: substitui senha legada por hash forte após login válido.
            if stored_password and not str(stored_password).startswith("pbkdf2_sha256$"):
                new_hash = _hash_password_pbkdf2(senha)
                cursor.execute("UPDATE usuarios SET senha = ? WHERE rowid = ?", (new_hash, rowid))
                conn.commit()

            return True
    except sqlite3.Error:
        return False


@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        senha = request.form['senha']
        
        # Verificar credenciais
        if autenticar(username, senha):
            return redirect(url_for('index'))  # Redireciona para o index.html
        else:
            return "Usuário ou senha inválidos", 400  # Retorna erro caso as credenciais sejam inválidas
    
    return render_template('login.html')  # Exibe a tela de login

@app.route('/index')
def index():
    return render_template('index.html')  # Exibe a página principal após login


if __name__ == '__main__':
    app.run(debug=False)
