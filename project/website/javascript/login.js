// Alternar visibilidade da senha
const senha = document.getElementById('senha');
const reveal = document.querySelector('.reveal');

// aplica lazy loading para evitar carga simultânea das imagens
document.querySelectorAll('img').forEach((img) => {
  if (!img.hasAttribute('loading')) img.setAttribute('loading', 'lazy');
  if (!img.hasAttribute('decoding')) img.setAttribute('decoding', 'async');
  if (!img.hasAttribute('fetchpriority')) img.setAttribute('fetchpriority', 'low');
});

if (reveal && senha) {
  reveal.addEventListener('click', () => {
    const isPwd = senha.type === 'password';
    senha.type = isPwd ? 'text' : 'password';
    reveal.textContent = isPwd ? 'Ocultar' : 'Mostrar';
    senha.focus();
  });
}

// Simular login adm (preenche campos "1"/"1")
function admLogin() {
  const u = document.getElementById('username');
  const p = document.getElementById('senha');
  if (u && p) {
    u.value = 'adm';
    p.value = 'senha123';
    u.focus();
  }
}

// botão "Entrar como Administrador"
document.getElementById('btn-adm')?.addEventListener('click', admLogin);

// Validação simples na submissão (destaca campos obrigatórios vazios)
document.querySelector('form')?.addEventListener('submit', (e) => {
  const form = e.currentTarget;
  const requiredEmpty = [...form.querySelectorAll('input[required]')].filter(i => !i.value.trim());
  if (requiredEmpty.length) {
    e.preventDefault();
    requiredEmpty.forEach(i => i.style.boxShadow = '0 0 0 4px #ef444422');
    requiredEmpty[0].focus();
  }
});
