/**
 * Os nomes que as telas do adm-gs e do oem-gs repetem — papel, partes do bot, produto e
 * data — num lugar só, para as telas não discordarem entre si sobre o mesmo fato.
 */

import type { Produto, ProdutoDoBot } from '@/features/api'

export const PAPEL: Record<string, string> = {
  administrador: 'Administrador da plataforma',
  atendimento: 'Atendimento da plataforma',
  gestor_empresa: 'Gerente da empresa',
  tecnico: 'Técnico',
  cliente: 'Dono de usina',
}

export const NOME_DO_PRODUTO: Record<Produto, string> = { meuwatt: 'meuWatt', meuplano: 'meuPlano' }

/** As partes do assistente do WhatsApp. Cada uma responde com o token PRÓPRIO da pessoa
 *  (`token`); o helper reconhece a pessoa pelo do meuWatt. O meuGuarda (câmeras) não pede token
 *  (`null`): ele confere a sessão do Gestão Solar da própria pessoa. */
export const PARTES_DO_BOT: { campo: ProdutoDoBot; rotulo: string; token: Produto | null }[] = [
  { campo: 'bot_meuwatt', rotulo: 'Geração (meuWatt)', token: 'meuwatt' },
  { campo: 'bot_meuplano', rotulo: 'Manutenção (meuPlano)', token: 'meuplano' },
  { campo: 'bot_helper', rotulo: 'Usina ao vivo (helper)', token: 'meuwatt' },
  { campo: 'bot_meuguarda', rotulo: 'Atuar nas câmeras (meuGuarda)', token: null },
]

/** O que falta para LIGAR a parte, ou nulo: o celular, o token próprio, ou (atuação nas câmeras) o acesso ao
 *  meuGuarda liberado em Usuários. */
export function faltaParaLigar(
  parte: { campo: ProdutoDoBot; token: Produto | null },
  u: { telefone: string | null; produtos: Produto[]; meuguarda_liberado: boolean },
): string | null {
  if (!u.telefone) return 'o celular'
  if (parte.token !== null && !u.produtos.includes(parte.token)) return `o token próprio do ${NOME_DO_PRODUTO[parte.token]}`
  if (parte.campo === 'bot_meuguarda' && !u.meuguarda_liberado) return 'liberar o meuGuarda'
  return null
}

/** A parte tem o que precisa para responder: o token dela, ou nenhum (meuGuarda). */
export const temOToken = (parte: { token: Produto | null }, tokens: Produto[]) =>
  parte.token === null || tokens.includes(parte.token)

/** "Geração (meuWatt) · Manutenção (meuPlano) (falta o token)" — o liberado, e o que está parado. */
export function textoDoBot(liberado: ProdutoDoBot[], tokens: Produto[], temCelular: boolean): string {
  if (!temCelular) return 'sem celular: o bot não reconhece a pessoa'
  const partes = PARTES_DO_BOT.filter((p) => liberado.includes(p.campo)).map((p) =>
    temOToken(p, tokens) ? p.rotulo : `${p.rotulo} (falta o token)`,
  )
  return partes.join(' · ') || 'desligado'
}

/** Desativar tira a pessoa na hora (painel, aplicativo e bot): pergunta antes. Reativar, não. */
export function confirmaAtivacao(nome: string, ativoAgora: boolean): boolean {
  return (
    !ativoAgora ||
    window.confirm(`Desativar ${nome}? A pessoa para de entrar na hora (painel, aplicativo e bot). Dá para reativar depois.`)
  )
}

/** A troca de perfil da equipe da plataforma grava ao escolher: pergunta antes, dizendo o que muda
 *  (avaliação de 24/10/2026 — gravava sem confirmar). */
export function confirmaPerfil(nome: string, novo: 'administrador' | 'atendimento'): boolean {
  return window.confirm(
    novo === 'administrador'
      ? `Dar o perfil Administrador a ${nome}? Administrador abre todas as telas da plataforma, inclusive Usuários.`
      : `Mudar ${nome} para Atendimento? A pessoa passa a abrir só as telas concedidas a ela.`,
  )
}

export function quando(iso: string | null): string {
  if (!iso) return 'nunca'
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' })
}
