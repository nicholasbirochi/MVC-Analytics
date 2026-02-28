from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)


def _default_login_db_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root.parent / "_dados_ronda_local" / "project" / "database" / "db_login.sqlite").resolve()


LOGIN_DB_PATH = Path(os.getenv("LOGIN_DB_PATH", str(_default_login_db_path()))).expanduser()


def autenticar(username: str, senha: str) -> bool:
    """Autentica o usuário usando banco local externo ao repositório."""
    try:
        conn = sqlite3.connect(str(LOGIN_DB_PATH))
        cursor = conn.cursor()
        # Compatível com esquemas que usam username, email ou nome como identificador.
        cursor.execute(
            """
            SELECT 1
            FROM usuarios
            WHERE (username = ? OR email = ? OR nome = ?)
              AND senha = ?
            LIMIT 1
            """,
            (username, username, username, senha),
        )
        usuario = cursor.fetchone()
        conn.close()
        return usuario is not None
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
