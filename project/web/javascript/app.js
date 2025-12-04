// util: alterna item ativo do menu
function setActive(linkEl) {
  document.querySelectorAll('.menu-opcoes a').forEach(a => a.removeAttribute('aria-current'));
  linkEl.setAttribute('aria-current', 'page');
}

// troca o src do iframe
function setFrameSrc(url) {
  const frame = document.getElementById('dynframe');
  if (!frame) return;
  frame.src = url;
}

// resolve a âncora/hash para um link
function getLinkByKey(key) {
  return document.querySelector(`.menu-opcoes a[data-key="${key}"]`);
}

document.addEventListener('DOMContentLoaded', () => {
  // ano do rodapé
  document.getElementById('year').textContent = new Date().getFullYear();

  const links = document.querySelectorAll('.menu-opcoes a');
  const frame = document.getElementById('dynframe');
  const reloadBtn = document.getElementById('reload');

  // clique no menu
  links.forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const url = link.dataset.src;
      const key = link.dataset.key;
      if (url) setFrameSrc(url);
      if (key) location.hash = key; // persiste a escolha
      setActive(link);
    });
  });

  // restaura a aba ativa pelo hash (#visao-geral, #por-pessoa, #por-area)
  const fromHash = location.hash.replace('#', '').trim();
  const linkFromHash = fromHash ? getLinkByKey(fromHash) : null;

  if (linkFromHash) {
    setActive(linkFromHash);
    setFrameSrc(linkFromHash.dataset.src);
  } else {
    // padrão: primeiro link
    const first = links[0];
    if (first) {
      setActive(first);
      setFrameSrc(first.dataset.src);
      location.hash = first.dataset.key || '';
    }
  }

  // botão recarregar
  if (reloadBtn && frame) {
    reloadBtn.addEventListener('click', () => {
      // força reload preservando o src atual
      const current = frame.getAttribute('src');
      frame.setAttribute('src', current);
    });
  }
});