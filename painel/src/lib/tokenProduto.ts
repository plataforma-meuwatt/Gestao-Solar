/**
 * Confere o token colado ANTES de mandar ao servidor.
 *
 * O erro provável na tela de Conexões é trocar as duas caixas de lugar — os valores são
 * longos, parecidos, e estão os dois na área de transferência. Reparar nisso enquanto a
 * pessoa ainda olha para o campo é muito melhor do que devolver "credencial recusada"
 * três segundos depois, quando a atenção já foi para outro lugar.
 *
 * Aqui só o que é barato e não pode divergir: prefixo, tamanho e alfabeto. O DÍGITO
 * VERIFICADOR fica com o BFF de propósito — reimplementar CRC-32 em JavaScript seria uma
 * terceira cópia do formato para ganhar meio segundo, e uma cópia a mais é uma a mais
 * para divergir em silêncio. O servidor responde rápido e com a frase certa.
 *
 * Fonte do formato: bff/app/core/tokens_produto.py.
 */

import type { Produto } from '@/features/api'

const PREFIXO: Record<Produto, string> = {
  meuwatt: 'mw_pat_',
  meuplano: 'mp_pat_',
}

const NOME: Record<Produto, string> = {
  meuwatt: 'meuWatt',
  meuplano: 'meuPlano',
}

/** 7 do prefixo + 32 de sorteio + 6 de verificação. */
export const TAMANHO_TOKEN = 45

const ALFABETO = /^[0-9A-Za-z]+$/

export function prefixoDe(produto: Produto): string {
  return PREFIXO[produto]
}

/** `null` quando está tudo bem; senão, a frase que o gestor precisa ler. */
export function problemaNoToken(produto: Produto, valor: string): string | null {
  const limpo = valor.trim()
  if (!limpo) return null // campo vazio não é erro, é campo vazio

  if (!limpo.startsWith(PREFIXO[produto])) {
    const outro = (Object.keys(PREFIXO) as Produto[]).find(
      (p) => p !== produto && limpo.startsWith(PREFIXO[p]),
    )
    if (outro) {
      return `Este é um token do ${NOME[outro]}, e o campo é do ${NOME[produto]}. Confira se os dois não foram trocados de lugar.`
    }
    return `Um token do ${NOME[produto]} começa com "${PREFIXO[produto]}".`
  }

  if (limpo.length < TAMANHO_TOKEN) {
    return `Faltam ${TAMANHO_TOKEN - limpo.length} caracteres — a cópia veio cortada.`
  }
  if (limpo.length > TAMANHO_TOKEN) {
    return `Sobram ${limpo.length - TAMANHO_TOKEN} caracteres — pode ter vindo espaço ou aspas junto.`
  }
  if (!ALFABETO.test(limpo.slice(PREFIXO[produto].length))) {
    return 'O token tem caracteres que não pertencem ao formato.'
  }
  return null
}

/** Pronto para enviar: formato plausível e completo. */
export function tokenPreenchido(produto: Produto, valor: string): boolean {
  return valor.trim().length === TAMANHO_TOKEN && problemaNoToken(produto, valor) === null
}
