from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)

# Função para autenticar o usuário
def autenticar(username, senha):
    conn = sqlite3.connect('Banco Login.sqlite')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM usuarios WHERE username=? AND senha=?', (username, senha))
    usuario = cursor.fetchone()
    conn.close()
    return usuario is not None

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
