/**
 * Testes do Talk Solar — rodam em node, sem Electron.
 *
 * O que se testa aqui é o que quebra em silêncio e só aparece no uso: a ESCAPADA do texto (a
 * conversa é escrita por gente, e gente cola `<`), a RENOVAÇÃO da sessão (o app fica aberto o
 * dia inteiro e o JWT dura 12 h), e o formato do envio COM ANEXO (o servidor recusa o que não
 * vier no formato certo, e descobrir isso na frente do usuário é tarde).
 *
 *     node testes/talk.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

let ok = 0;
const falhas = [];

// As checagens rodam EM FILA e com await. Teste assíncrono solto se atropela com o seguinte —
// o estado da sessão vaza de um para o outro e o erro aparece no teste errado. Foi exatamente
// o que aconteceu na primeira rodada: a falha apontou o teste do anexo, e o defeito era o
// harness.
const fila = [];
function checar(nome, fn) { fila.push([nome, fn]); }

async function rodar() {
  for (const [nome, fn] of fila) {
    try {
      await fn();
      ok += 1;
      console.log('  OK   ' + nome);
    } catch (e) {
      falhas.push(nome);
      console.log('  FALHA ' + nome + ' — ' + e.message);
    }
  }
  console.log(`\n${ok} OK / ${falhas.length} falha(s)`);
  process.exit(falhas.length ? 1 : 0);
}

// ---------------------------------------------------------------- ambiente falso
// A tela roda no Electron; aqui montamos o mínimo para os módulos carregarem: um `window`,
// um `document` que não faz nada e a ponte `talkSolar` (que no app real toca o disco).
const sessaoFalsa = { valor: null };
const janela = {
  talkSolar: {
    lerSessao: async () => sessaoFalsa.valor,
    gravarSessao: async (d) => { sessaoFalsa.valor = d; return true; },
  },
  navigator: { platform: 'TestePC' },
};
global.window = janela;
global.document = { getElementById: () => null, dispatchEvent: () => {} };
global.navigator = janela.navigator;
global.CustomEvent = function CustomEvent(t) { this.type = t; };
global.FormData = class FormData {
  constructor() { this.itens = []; }
  append(k, v, n) { this.itens.push([k, v, n]); }
  get(k) { const i = this.itens.find((x) => x[0] === k); return i ? i[1] : null; }
  todos(k) { return this.itens.filter((x) => x[0] === k).map((x) => x[1]); }
};

function carregar(rel) {
  const codigo = fs.readFileSync(path.join(__dirname, '..', 'app', 'js', rel), 'utf8');
  new Function(codigo).call(janela);        // eslint-disable-line no-new-func
}
carregar('ui.js');
carregar('api.js');
const UI = janela.UI;
const API = janela.API;

// ---------------------------------------------------------------- texto vindo de gente
checar('escapa HTML colado na conversa', () => {
  const s = UI.esc('<script>alert(1)</script>');
  assert.ok(!s.includes('<script'), 'deixou passar a tag');
  assert.ok(s.includes('&lt;script&gt;'), 'não escapou');
});

checar('o NOME do autor também é escapado (vem do sistema, não do céu)', () => {
  const h = UI.htmlMensagem({
    autor: { id: 1, nome: '<img src=x onerror=1>' }, conteudo: 'oi',
    criada_em: new Date().toISOString(),
  }, false);
  assert.ok(!h.includes('<img src=x'), 'nome injetou HTML');
});

checar('tamanho em pt-BR (vírgula, não ponto)', () => {
  assert.strictEqual(UI.bytesBR(900), '900 B');
  assert.strictEqual(UI.bytesBR(2048), '2 KB');
  assert.ok(UI.bytesBR(1500000).includes(','), 'deveria usar vírgula decimal');
});

// ---------------------------------------------------------------- a foto na conversa
checar('imagem aparece pela MINIATURA, não pelo arquivo cheio', () => {
  const h = UI.htmlAnexos([{
    id: 1, nome: 'f.png', imagem: true, bytes: 10,
    url: 'https://s/cheia.png', thumb_url: 'https://s/thumb.png',
  }]);
  assert.ok(h.includes('src="https://s/thumb.png"'), 'não usou a miniatura');
  assert.ok(h.includes('data-cheia="https://s/cheia.png"'), 'perdeu o caminho da imagem cheia');
});

checar('arquivo que não é imagem vira cartão com o nome', () => {
  const h = UI.htmlAnexos([{
    id: 2, nome: 'laudo.pdf', imagem: false, bytes: 2048,
    url: 'https://s/l.pdf', thumb_url: 'https://s/l.pdf',
  }]);
  assert.ok(h.includes('laudo.pdf') && h.includes('class="arquivo"'), 'não virou cartão');
  assert.ok(!h.includes('<img'), 'renderizou PDF como imagem');
});

checar('o chip de citação LEVA ao endereço que o SISTEMA mandou', () => {
  // a URL vem PRONTA do servidor: quem sabe montar o endereço de uma OS é o sistema dono dela,
  // não este app — é o que permite o mesmo código servir meuPlano, meuWatt e Gestão Solar
  const h = UI.htmlRefs([{ tipo: 'os', id: '1016', label: 'OS 1016',
                           url: 'https://meuplano.x/os-list?os=1016' }]);
  assert.ok(h.includes('https://meuplano.x/os-list?os=1016'), 'chip sem destino: ' + h);
});

checar('tipo desconhecido não some da tela (o vocabulário é de cada sistema)', () => {
  const h = UI.htmlRefs([{ tipo: 'proposta', id: '9', label: 'Proposta 9', url: 'https://x/9' }]);
  assert.ok(h.includes('Proposta 9'), 'sumiu: ' + h);
});

// ---------------------------------------------------------------- a sessão não pode cair
checar('entrar é em DOIS passos: senha no sistema, sessão na Talk Solar', async () => {
  const chamadas = [];
  global.fetch = async (url, opts) => {
    chamadas.push(url);
    if (url.includes('/auth/login')) {
      return { ok: true, status: 200, json: async () => ({ token: 'TOKEN-DO-SISTEMA' }) };
    }
    const corpo = JSON.parse(opts.body);
    // é o TOKEN DO SISTEMA que a Talk Solar troca por uma sessão — nunca a senha
    assert.strictEqual(corpo.token, 'TOKEN-DO-SISTEMA', 'mandou outra coisa: ' + opts.body);
    assert.strictEqual(corpo.app, 'meuplano', 'não disse de qual sistema');
    assert.ok(corpo.dispositivo, 'não disse que computador é este');
    return { ok: true, status: 200,
             json: async () => ({ token: 'T1', refresh: 'R1',
                                  usuario: { id: 7, nome: 'Eu', externo_id: '179' } }) };
  };
  await API.entrar('a@b.c', 'x');
  assert.ok(chamadas[0].includes('/auth/login'), 'não falou com o sistema primeiro');
  assert.ok(chamadas[1].includes('/v1/sessao'), 'não trocou por sessão da Talk Solar');
  assert.strictEqual(API.estado.refresh, 'R1');
  assert.strictEqual(sessaoFalsa.valor.refresh, 'R1', 'não guardou em disco');
});

checar('>> a SENHA nunca chega à Talk Solar', async () => {
  let corpoTalk = null;
  global.fetch = async (url, opts) => {
    if (url.includes('/auth/login')) {
      return { ok: true, status: 200, json: async () => ({ token: 'TK' }) };
    }
    corpoTalk = opts.body;
    return { ok: true, status: 200,
             json: async () => ({ token: 'T', refresh: 'R', usuario: { id: 1, nome: 'x' } }) };
  };
  await API.entrar('a@b.c', 'senha-secreta-123');
  assert.ok(!String(corpoTalk).includes('senha-secreta-123'),
            'a senha vazou para a Talk Solar: ' + corpoTalk);
});

checar('no 401 renova e REPETE a chamada — uma vez só', async () => {
  API.estado.token = 'VELHO';
  API.estado.refresh = 'R1';
  const chamadas = [];
  let renovacoes = 0;
  global.fetch = async (url, opts) => {
    chamadas.push(url);
    if (url.includes('/v1/sessao/refresh')) {
      renovacoes += 1;
      return { ok: true, status: 200, json: async () => ({ token: 'NOVO' }) };
    }
    const auth = (opts.headers || {}).Authorization;
    if (auth === 'Bearer VELHO') return { ok: false, status: 401, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ([{ id: 1 }]) };
  };
  const r = await API.listarCanais();
  assert.strictEqual(renovacoes, 1, 'renovou ' + renovacoes + ' vez(es)');
  assert.deepStrictEqual(r, [{ id: 1 }], 'não repetiu a chamada depois de renovar');
  assert.strictEqual(API.estado.token, 'NOVO');
});

checar('sessão morta de verdade não vira laço infinito', async () => {
  API.estado.token = 'VELHO';
  API.estado.refresh = 'R1';
  let tentativas = 0;
  global.fetch = async (url) => {
    tentativas += 1;
    if (url.includes('/v1/sessao/refresh')) return { ok: false, status: 401, json: async () => ({}) };
    return { ok: false, status: 401, json: async () => ({}) };
  };
  await assert.rejects(() => API.listarCanais());
  assert.ok(tentativas <= 2, 'tentou ' + tentativas + ' vezes — deveria desistir');
  assert.strictEqual(API.estado.token, null, 'não esqueceu a sessão morta');
});

// ---------------------------------------------------------------- anexo + citação
checar('mensagem com anexo vai num pedido só, com as citações junto', async () => {
  API.estado.token = 'T';
  API.estado.refresh = 'R';
  let recebido = null;
  let destino = null;
  global.fetch = async (url, opts) => {
    destino = url; recebido = opts.body;
    return { ok: true, status: 200, json: async () => ({ id: 9 }) };
  };
  const arq = { name: 'foto.png', type: 'image/png' };
  await API.enviarComAnexos(3, [arq], 'olha isso', [{ tipo: 'usina', id: 5, label: 'X' }]);
  assert.ok(destino.includes('/v1/canais/3/mensagens/anexos'), destino);
  assert.ok(recebido instanceof global.FormData, 'não foi multipart');
  assert.strictEqual(recebido.todos('arquivos').length, 1, 'perdeu o arquivo');
  assert.strictEqual(recebido.get('conteudo'), 'olha isso');
  const refs = JSON.parse(recebido.get('refs'));
  assert.deepStrictEqual(refs, [{ tipo: 'usina', id: '5' }],
                         'citação foi errada: ' + recebido.get('refs'));
});

void rodar();
