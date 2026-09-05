/**
 * Talk Solar — o app de PC falando com o servidor.
 *
 * DUAS COISAS IMPORTAM AQUI, e são a razão do arquivo:
 *
 * 1. **A identidade é emprestada.** O usuário entra com a senha DO SISTEMA dele (meuPlano,
 *    meuWatt, Gestão Solar); o app troca esse token por uma sessão da Talk Solar
 *    (`POST /v1/sessao`). Não existe senha da Talk Solar — e é por isso que desligar alguém
 *    em UM lugar basta.
 *
 * 2. **A sessão não pode cair.** O JWT dura horas e este app fica aberto o dia inteiro: no
 *    401 ele renova com o `refresh` e REPETE a chamada — uma vez só, senão um token inválido
 *    de verdade viraria laço infinito.
 */

const API = {
  //: o servidor da Talk Solar (serviço próprio no Railway)
  base: 'https://talk-solar-production.up.railway.app',
  //: o sistema de onde vem a identidade
  app: 'meuplano',
  //: onde esse sistema mora (só para o login; depois o servidor cuida de tudo)
  sistemaBase: 'https://meuplano-production.up.railway.app',
  token: null,
  refresh: null,
  usuario: null,
};

/** Os sistemas que sabem entrar. Acrescentar um é uma linha — o resto é do servidor. */
const SISTEMAS = [
  { slug: 'meuplano', nome: 'meuPlano',
    base: 'https://meuplano-production.up.railway.app',
    login: '/api/v1/meuacesso/auth/login' },
  { slug: 'gestaosolar', nome: 'Gestão Solar', base: '', login: '/api/auth/login' },
  { slug: 'meuwatt', nome: 'meuWatt', base: '', login: '/api/auth/login' },
];

function definirBase(url) { if (url) API.base = String(url).replace(/\/+$/, ''); }
function definirSistema(slug, base) {
  API.app = slug || API.app;
  if (base) API.sistemaBase = String(base).replace(/\/+$/, '');
}

async function carregarSessao() {
  const s = await window.talkSolar.lerSessao();
  if (s && s.token) {
    Object.assign(API, {
      token: s.token, refresh: s.refresh || null, usuario: s.usuario || null,
      base: s.base || API.base, app: s.app || API.app,
      sistemaBase: s.sistemaBase || API.sistemaBase,
    });
  }
  return API.usuario;
}

async function guardarSessao() {
  await window.talkSolar.gravarSessao({
    token: API.token, refresh: API.refresh, usuario: API.usuario,
    base: API.base, app: API.app, sistemaBase: API.sistemaBase,
  });
}

async function esquecerSessao() {
  API.token = API.refresh = API.usuario = null;
  await window.talkSolar.gravarSessao(null);
}

/**
 * Entrar: senha no SISTEMA → token do sistema → sessão da Talk Solar.
 *
 * O primeiro passo fala com o sistema; o segundo, só com a Talk Solar. Se o sistema recusar a
 * senha, a mensagem é dele — e é o que o usuário precisa ler, não um "erro de login" genérico.
 */
async function entrar(email, senha) {
  const sistema = SISTEMAS.find((s) => s.slug === API.app) || SISTEMAS[0];
  const r1 = await fetch(`${API.sistemaBase}${sistema.login}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password: senha }),
  });
  const d1 = await r1.json().catch(() => ({}));
  if (!r1.ok || !d1.token) throw new Error(d1.detail || `Não consegui entrar no ${sistema.nome}.`);

  const r2 = await fetch(`${API.base}/v1/sessao`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      app: API.app, token: d1.token,
      dispositivo: `Talk Solar · ${navigator.platform || 'PC'}`,
    }),
  });
  const d2 = await r2.json().catch(() => ({}));
  if (!r2.ok) throw new Error(d2.detail || 'A Talk Solar não conseguiu confirmar quem é você.');
  API.token = d2.token;
  API.refresh = d2.refresh;
  API.usuario = d2.usuario;
  await guardarSessao();
  return API.usuario;
}

/** `false` = a sessão morreu de verdade (revogada ou parada tempo demais). */
async function renovar() {
  if (!API.refresh) return false;
  try {
    const r = await fetch(`${API.base}/v1/sessao/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: API.refresh }),
    });
    if (!r.ok) return false;
    const d = await r.json();
    if (!d.token) return false;
    API.token = d.token;
    await guardarSessao();
    return true;
  } catch { return false; }
}

async function chamar(caminho, opcoes = {}, jaRenovou = false) {
  const cab = Object.assign({}, opcoes.headers || {});
  if (API.token) cab.Authorization = `Bearer ${API.token}`;
  if (opcoes.body && !(opcoes.body instanceof FormData)) cab['Content-Type'] = 'application/json';
  const r = await fetch(`${API.base}${caminho}`, Object.assign({}, opcoes, { headers: cab }));
  if (r.status === 401 && !jaRenovou && await renovar()) {
    return chamar(caminho, opcoes, true);
  }
  if (r.status === 401) {
    await esquecerSessao();
    document.dispatchEvent(new CustomEvent('sessao-caiu'));
    throw new Error('Sessão expirada.');
  }
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `Erro ${r.status}`);
  }
  return r.status === 204 ? null : r.json();
}

const get = (c) => chamar(c);
const post = (c, corpo) => chamar(c, { method: 'POST', body: JSON.stringify(corpo || {}) });

// --------------------------------------------------------------- a conversa
const listarCanais = () => get('/v1/canais');
const listarMensagens = (cid) => get(`/v1/canais/${cid}/mensagens`);
const enviarTexto = (cid, conteudo, refs) =>
  post(`/v1/canais/${cid}/mensagens`, { conteudo, refs: refs || [] });
const marcarLido = (cid, ultimaId) => post(`/v1/canais/${cid}/lido`, { ultima_id: ultimaId });
const listarPessoas = () => get('/v1/pessoas');
const abrirDM = (ids) => post('/v1/canais/dm', { usuarios: ids });
const canalDoAlvo = (tipo, id) => post('/v1/canais/do-alvo', { tipo, id: String(id) });
const buscarRefs = (q) => get(`/v1/refs/buscar?q=${encodeURIComponent(q)}`);

/** Mensagem COM arquivos: um pedido só — o servidor recusa arquivo sem dono. */
function enviarComAnexos(cid, arquivos, conteudo, refs) {
  const fd = new FormData();
  arquivos.forEach((f) => fd.append('arquivos', f, f.name));
  fd.append('conteudo', conteudo || '');
  if (refs && refs.length) {
    fd.append('refs', JSON.stringify(refs.map((r) => ({ tipo: r.tipo, id: String(r.id) }))));
  }
  return chamar(`/v1/canais/${cid}/mensagens/anexos`, { method: 'POST', body: fd });
}

window.API = {
  estado: API, SISTEMAS, definirBase, definirSistema, carregarSessao, entrar, esquecerSessao,
  renovar, listarCanais, listarMensagens, enviarTexto, enviarComAnexos, marcarLido,
  listarPessoas, abrirDM, canalDoAlvo, buscarRefs,
};
