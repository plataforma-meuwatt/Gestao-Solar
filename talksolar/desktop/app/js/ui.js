/**
 * Talk Solar — pedaços de tela que a conversa desenha muitas vezes, num lugar só.
 *
 * Especialmente `esc()`: TUDO o que vem do servidor passa por ele antes de virar HTML. Numa
 * conversa o texto é escrito por gente, e gente cola `<` por engano (ou não). A tela roda com
 * CSP fechada, mas a CSP é a segunda barreira — a primeira é não injetar.
 *
 * A URL do chip de citação **vem pronta do servidor** (`ref.url`): quem sabe montar o endereço
 * de uma OS é o sistema dono dela, e não este app. Foi isso que permitiu o mesmo código servir
 * meuPlano, meuWatt e Gestão Solar sem um `if` por sistema.
 */

const $ = (id) => document.getElementById(id);

function esc(t) {
  return String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function hhmm(iso) {
  try {
    return new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

/** Tamanho em pt-BR — "1,4 MB", não "1468006 bytes". */
function bytesBR(n) {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`;
}

/** O rótulo do TIPO é só enfeite de leitura: o vocabulário é de cada sistema, e um tipo
 *  desconhecido aparece como veio, em vez de sumir. */
const ROTULO_REF = {
  usina: 'Usina', os: 'OS', tarefa: 'Tarefa', equipamento: 'Equipamento',
  container: 'Pendência', planta: 'Planta', alarme: 'Alarme', cliente: 'Cliente',
  proposta: 'Proposta', contrato: 'Contrato',
};
const rotuloRef = (tipo) => ROTULO_REF[tipo] || String(tipo || '');

function htmlAnexos(anexos) {
  if (!anexos || !anexos.length) return '';
  const imgs = anexos.filter((a) => a.imagem);
  const arqs = anexos.filter((a) => !a.imagem);
  let h = '<div class="anexos">';
  // a MINIATURA na conversa: rolar dez fotos de 4 MB trava a tela, e quem usa conclui que o
  // programa é ruim — não que a foto é grande
  imgs.forEach((a) => {
    h += `<img src="${esc(a.thumb_url)}" alt="${esc(a.nome)}" loading="lazy"
             data-cheia="${esc(a.url)}" />`;
  });
  arqs.forEach((a) => {
    h += `<a class="arquivo" href="${esc(a.url)}" data-externo="1">📄
            <span>${esc(a.nome)}</span>
            <span class="tam">${bytesBR(a.bytes)}</span></a>`;
  });
  return `${h}</div>`;
}

function htmlRefs(refs) {
  if (!refs || !refs.length) return '';
  return `<div class="refs">${refs.map((r) => `
    <a class="refChip" href="${esc(r.url || '#')}" data-externo="1">
      <b>${esc(rotuloRef(r.tipo))}</b>${esc(r.label || '#' + r.id)}
    </a>`).join('')}</div>`;
}

function htmlMensagem(m, souEu) {
  const autor = (m.autor && m.autor.nome) || (m.do_sistema ? 'sistema' : 'alguém');
  const inicial = m.do_sistema ? '⚙' : autor.trim().charAt(0).toUpperCase();
  const corpo = m.apagada
    ? '<p class="texto apagada">mensagem apagada</p>'
    : (m.conteudo ? `<p class="texto">${esc(m.conteudo)}</p>` : '');
  return `
    <div class="msg ${souEu ? 'minha' : ''} ${m.do_sistema ? 'sistema' : ''}">
      <div class="inicial">${esc(inicial)}</div>
      <div class="corpo">
        <p class="autor">${esc(autor)}<span class="hora">${hhmm(m.criada_em)}</span></p>
        ${corpo}
        ${m.apagada ? '' : htmlAnexos(m.anexos)}
        ${m.apagada ? '' : htmlRefs(m.refs)}
      </div>
    </div>`;
}

window.UI = { $, esc, hhmm, bytesBR, htmlMensagem, htmlAnexos, htmlRefs, rotuloRef, ROTULO_REF };
