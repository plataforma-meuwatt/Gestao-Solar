/**
 * Talk Solar — a tela.
 *
 * Três decisões que definem o comportamento:
 *
 * 1. **O WebSocket ACELERA; não é a fonte da verdade.** A lista recarrega ao abrir o canal e a
 *    cada 30 s. Um mensageiro que só funciona com a conexão viva perde mensagem em túnel de
 *    elevador — e perder mensagem é a única falha que um mensageiro não pode ter.
 * 2. **Notificação só do que é para você**: o que não está na tela aberta. Avisar tudo
 *    transforma o aviso em ruído, e ruído se aprende a ignorar em uma semana.
 * 3. **Anexo e mensagem vão juntos** (um pedido só): o servidor recusa arquivo sem dono, e o
 *    caminho de dois passos deixaria arquivo órfão ou mensagem vazia quando falhasse no meio.
 */

const { $, esc, htmlMensagem, rotuloRef } = window.UI;

const estado = {
  canais: [],
  canalAtivo: null,
  msgs: [],
  pendentes: [],     // arquivos escolhidos e ainda não enviados
  refs: [],          // citações escolhidas e ainda não enviadas
  ws: null,
  reconectarEm: 1000,
  filtro: '',
};

// ------------------------------------------------------------------ entrar / sair
async function iniciar() {
  const info = await window.talkSolar.info();
  $('versaoApp').textContent = `v${info.versao}`;
  montarSistemas();
  const usuario = await window.API.carregarSessao();
  if (usuario) {
    const vivo = await window.API.renovar().catch(() => false);
    if (vivo || window.API.estado.token) return abrirConversa();
  }
  mostrarLogin();
}

/** De qual sistema vem a identidade. Acrescentar um é uma linha em `API.SISTEMAS`. */
function montarSistemas() {
  const sel = $('loginSistema');
  sel.innerHTML = window.API.SISTEMAS.map((s) =>
    `<option value="${esc(s.slug)}">${esc(s.nome)}</option>`).join('');
  sel.value = window.API.estado.app;
  sel.onchange = () => {
    const s = window.API.SISTEMAS.find((x) => x.slug === sel.value);
    $('loginSistemaBase').value = s && s.base ? s.base : '';
  };
  const atual = window.API.SISTEMAS.find((x) => x.slug === sel.value);
  $('loginSistemaBase').value = window.API.estado.sistemaBase
    || (atual && atual.base) || '';
}

function mostrarLogin() {
  $('telaLogin').classList.remove('oculto');
  $('telaConversa').classList.add('oculto');
  $('loginBase').value = window.API.estado.base;
  $('loginEmail').focus();
}

async function entrar() {
  const email = $('loginEmail').value.trim();
  const senha = $('loginSenha').value;
  if (!email || !senha) return;
  $('loginErro').textContent = '';
  $('btnEntrar').disabled = true;
  try {
    window.API.definirBase($('loginBase').value.trim() || window.API.estado.base);
    window.API.definirSistema($('loginSistema').value, $('loginSistemaBase').value.trim());
    await window.API.entrar(email, senha);
    $('loginSenha').value = '';
    await abrirConversa();
  } catch (e) {
    $('loginErro').textContent = e.message || 'Não consegui entrar.';
  } finally {
    $('btnEntrar').disabled = false;
  }
}

async function abrirConversa() {
  $('telaLogin').classList.add('oculto');
  $('telaConversa').classList.remove('oculto');
  $('meuNome').textContent = (window.API.estado.usuario || {}).nome || 'eu';
  await recarregarCanais();
  conectarTempoReal();
  // rede de segurança do tempo real: a lista se corrige sozinha mesmo com o socket caído
  setInterval(() => { void recarregarCanais(); }, 30000);
}

// ------------------------------------------------------------------ canais
async function recarregarCanais() {
  try {
    estado.canais = await window.API.listarCanais();
    desenharCanais();
    const total = estado.canais.reduce((t, c) => t + (c.nao_lidas || 0), 0);
    window.talkSolar.badge(total);   // o aviso que se vê sem ler nada
  } catch { /* offline: a tela continua com o que já tinha */ }
}

function rotuloCanal(c) {
  if (c.tipo === 'dm') {
    const eu = (window.API.estado.usuario || {}).id;
    const outros = (c.pessoas || []).filter((p) => p.id !== eu).map((p) => p.nome);
    return outros.join(', ') || 'conversa direta';
  }
  return c.nome || `canal ${c.id}`;
}

function desenharCanais() {
  const alvo = $('listaCanais');
  const termo = estado.filtro.toLowerCase();
  const lista = estado.canais.filter((c) => !termo || rotuloCanal(c).toLowerCase().includes(termo));
  if (!lista.length) {
    alvo.innerHTML = '<p class="vazio">nenhuma conversa</p>';
    return;
  }
  alvo.innerHTML = lista.map((c) => `
    <button class="canalItem ${c.id === estado.canalAtivo ? 'ativo' : ''}" data-canal="${c.id}">
      <span class="nome">${c.tipo === 'dm' ? '' : '# '}${esc(rotuloCanal(c))}
        <span class="previa">${esc(c.ultima_previa || 'sem mensagens')}</span></span>
      ${c.nao_lidas ? `<span class="naoLidas">${c.nao_lidas}</span>` : ''}
    </button>`).join('');
  alvo.querySelectorAll('[data-canal]').forEach((b) => {
    b.onclick = () => escolherCanal(Number(b.dataset.canal));
  });
}

async function escolherCanal(cid) {
  estado.canalAtivo = cid;
  const c = estado.canais.find((x) => x.id === cid);
  $('canalNome').textContent = c ? rotuloCanal(c) : '';
  $('canalTopico').textContent = (c && c.topico) || '';
  const chip = $('canalAlvo');
  if (c && c.alvo) {
    chip.textContent = `${rotuloRef(c.alvo.tipo)}: ${c.alvo.label || c.alvo.id}`;
    chip.href = c.alvo.url || '#';
    chip.dataset.externo = '1';
    chip.classList.remove('oculto');
  } else {
    chip.classList.add('oculto');
  }
  $('composer').classList.remove('oculto');
  desenharCanais();
  await recarregarMensagens();
}

// ------------------------------------------------------------------ mensagens
async function recarregarMensagens() {
  if (!estado.canalAtivo) return;
  try {
    estado.msgs = await window.API.listarMensagens(estado.canalAtivo);
    desenharMensagens();
    const ultima = estado.msgs[estado.msgs.length - 1];
    if (ultima) {
      await window.API.marcarLido(estado.canalAtivo, ultima.id).catch(() => {});
      void recarregarCanais();
    }
  } catch (e) {
    $('mensagens').innerHTML = `<p class="vazio">${esc(e.message || 'não consegui carregar')}</p>`;
  }
}

function desenharMensagens() {
  const eu = (window.API.estado.usuario || {}).id;
  const box = $('mensagens');
  box.innerHTML = estado.msgs.length
    ? estado.msgs.map((m) => htmlMensagem(m, (m.autor || {}).id === eu)).join('')
    : '<p class="vazio">Ninguém falou nada aqui ainda.</p>';
  box.scrollTop = box.scrollHeight;

  box.querySelectorAll('img[data-cheia]').forEach((img) => {
    img.onclick = () => {
      $('lightboxImg').src = img.dataset.cheia;
      $('lightbox').classList.remove('oculto');
    };
  });
  // link do sistema abre no NAVEGADOR: a janela do mensageiro não vira browser
  box.querySelectorAll('[data-externo]').forEach((a) => {
    a.onclick = (e) => { e.preventDefault(); window.talkSolar.abrirExterno(a.href); };
  });
}

// ------------------------------------------------------------------ enviar
function desenharPendentes() {
  const box = $('pendentes');
  const arquivos = estado.pendentes.map((f, i) => `
    <span class="pendente">
      ${f.type.startsWith('image/') ? `<img src="${URL.createObjectURL(f)}" alt="" />` : '📄'}
      <span>${esc(f.name)}</span><button data-tirar-arq="${i}">✕</button>
    </span>`).join('');
  const refs = estado.refs.map((r, i) => `
    <span class="pendente ref">
      <b>${esc(rotuloRef(r.tipo))}</b> ${esc(r.label || '')}
      <button data-tirar-ref="${i}">✕</button>
    </span>`).join('');
  box.innerHTML = arquivos + refs;
  box.querySelectorAll('[data-tirar-arq]').forEach((b) => {
    b.onclick = () => { estado.pendentes.splice(Number(b.dataset.tirarArq), 1); desenharPendentes(); };
  });
  box.querySelectorAll('[data-tirar-ref]').forEach((b) => {
    b.onclick = () => { estado.refs.splice(Number(b.dataset.tirarRef), 1); desenharPendentes(); };
  });
}

async function enviar() {
  const texto = $('texto').value.trim();
  if ((!texto && !estado.pendentes.length) || !estado.canalAtivo) return;
  const arquivos = estado.pendentes.slice();
  const refs = estado.refs.slice();
  $('btnEnviar').disabled = true;
  try {
    const salva = arquivos.length
      ? await window.API.enviarComAnexos(estado.canalAtivo, arquivos, texto, refs)
      : await window.API.enviarTexto(estado.canalAtivo, texto, refs);
    estado.msgs.push(salva);
    desenharMensagens();
    $('texto').value = '';
    estado.pendentes = []; estado.refs = [];
    desenharPendentes();
    void recarregarCanais();
  } catch (e) {
    // NÃO limpa o campo: texto perdido é imperdoável, e escolher o arquivo de novo é pior
    $('erroEnvio').textContent = e.message || 'Não consegui enviar.';
    setTimeout(() => { $('erroEnvio').textContent = ''; }, 6000);
  } finally {
    $('btnEnviar').disabled = false;
    $('texto').focus();
  }
}

// ------------------------------------------------------------------ citar
let citarTimer = null;
function buscarCitacao() {
  const q = $('citarTermo').value.trim();
  clearTimeout(citarTimer);
  if (q.length < 2) { $('citarLista').innerHTML = ''; return; }
  // atraso curto: cada tecla batendo no sistema hospedeiro deixaria o seletor inútil
  citarTimer = setTimeout(async () => {
    try {
      const achados = await window.API.buscarRefs(q);
      $('citarLista').innerHTML = achados.length ? achados.map((r, i) => `
        <button class="citarItem" data-cit="${i}">
          <span class="tipo">${esc(rotuloRef(r.tipo))}</span>
          <span class="rot">${esc(r.label)}</span>
        </button>`).join('') : '<p class="vazio" style="margin:6px">nada encontrado</p>';
      $('citarLista').querySelectorAll('[data-cit]').forEach((b) => {
        b.onclick = () => {
          const r = achados[Number(b.dataset.cit)];
          if (!estado.refs.some((x) => x.tipo === r.tipo && x.id === r.id)) estado.refs.push(r);
          $('citarCaixa').classList.add('oculto');
          $('btnCitar').classList.remove('ligado');
          $('citarTermo').value = ''; $('citarLista').innerHTML = '';
          desenharPendentes();
          $('texto').focus();
        };
      });
    } catch { $('citarLista').innerHTML = ''; }
  }, 250);
}

// ------------------------------------------------------------------ tempo real
function conectarTempoReal() {
  if (estado.ws) { try { estado.ws.close(); } catch { /* já morto */ } }
  const url = `${window.API.estado.base.replace(/^http/, 'ws')}/v1/ws`
    + `?token=${encodeURIComponent(window.API.estado.token || '')}`;
  const ws = new WebSocket(url);
  estado.ws = ws;

  ws.onopen = () => {
    estado.reconectarEm = 1000;
    $('estadoConexao').textContent = 'conectado';
    $('estadoConexao').className = 'estado ok';
  };
  ws.onmessage = (ev) => {
    let dados;
    try { dados = JSON.parse(ev.data); } catch { return; }
    if (dados.tipo !== 'mensagem') return;
    const m = dados.msg;
    if (dados.canal === estado.canalAtivo) {
      estado.msgs.push(m);
      desenharMensagens();
      window.API.marcarLido(estado.canalAtivo, m.id).catch(() => {});
    } else {
      const c = estado.canais.find((x) => x.id === dados.canal);
      window.talkSolar.notificar({
        titulo: c ? rotuloCanal(c) : 'Talk Solar',
        corpo: `${(m.autor || {}).nome || 'alguém'}: ${m.conteudo || '(arquivo)'}`.slice(0, 140),
        canalId: dados.canal,
      });
    }
    void recarregarCanais();
  };
  ws.onclose = async (ev) => {
    $('estadoConexao').textContent = 'reconectando…';
    $('estadoConexao').className = 'estado caiu';
    // 4401 = o servidor recusou o token. O app fica aberto o dia inteiro e o JWT dura horas:
    // sem renovar ANTES de reconectar, a partir do vencimento seria um laço de recusas.
    if (ev && ev.code === 4401) await window.API.renovar().catch(() => false);
    setTimeout(conectarTempoReal, estado.reconectarEm);
    estado.reconectarEm = Math.min(estado.reconectarEm * 2, 30000);
  };
  ws.onerror = () => { try { ws.close(); } catch { /* o onclose reconecta */ } };
}

// ------------------------------------------------------------------ ligações da tela
$('btnEntrar').onclick = () => void entrar();
$('loginSenha').onkeydown = (e) => { if (e.key === 'Enter') void entrar(); };
$('btnSair').onclick = async () => {
  await window.API.esquecerSessao();
  if (estado.ws) try { estado.ws.close(); } catch { /* ignora */ }
  mostrarLogin();
};
$('filtroCanais').oninput = (e) => { estado.filtro = e.target.value; desenharCanais(); };
$('btnEnviar').onclick = () => void enviar();
$('texto').onkeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void enviar(); }
};
/** COLAR (Ctrl+V) vira anexo: é o gesto mais comum do escritório — o print da tela. */
$('texto').onpaste = (e) => {
  const imgs = Array.from(e.clipboardData?.items || [])
    .filter((i) => i.type.startsWith('image/')).map((i) => i.getAsFile()).filter(Boolean);
  if (imgs.length) {
    e.preventDefault();
    estado.pendentes = estado.pendentes.concat(imgs).slice(0, 10);
    desenharPendentes();
  }
};
$('btnAnexar').onclick = () => $('arquivoInput').click();
$('arquivoInput').onchange = (e) => {
  const fs = Array.from(e.target.files || []);
  e.target.value = '';
  if (fs.length) { estado.pendentes = estado.pendentes.concat(fs).slice(0, 10); desenharPendentes(); }
};
$('btnCitar').onclick = () => {
  const caixa = $('citarCaixa');
  caixa.classList.toggle('oculto');
  $('btnCitar').classList.toggle('ligado', !caixa.classList.contains('oculto'));
  if (!caixa.classList.contains('oculto')) $('citarTermo').focus();
};
$('citarTermo').oninput = () => buscarCitacao();
$('lightbox').onclick = () => $('lightbox').classList.add('oculto');

const area = $('areaSolta');
area.addEventListener('dragover', (e) => { e.preventDefault(); area.classList.add('arrastando'); });
area.addEventListener('dragleave', () => area.classList.remove('arrastando'));
area.addEventListener('drop', (e) => {
  e.preventDefault();
  area.classList.remove('arrastando');
  const fs = Array.from(e.dataTransfer?.files || []);
  if (fs.length) { estado.pendentes = estado.pendentes.concat(fs).slice(0, 10); desenharPendentes(); }
});

// clicar na notificação do Windows abre a conversa certa
window.talkSolar.aoAbrirCanal((cid) => { void escolherCanal(cid); });
document.addEventListener('sessao-caiu', () => mostrarLogin());

void iniciar();
