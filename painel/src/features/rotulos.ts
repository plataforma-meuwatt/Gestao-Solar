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
 *  (`token`); o helper reconhece a pessoa pelo do meuWatt. */
export const PARTES_DO_BOT: { campo: ProdutoDoBot; rotulo: string; token: Produto }[] = [
  { campo: 'bot_meuwatt', rotulo: 'Geração (meuWatt)', token: 'meuwatt' },
  { campo: 'bot_meuplano', rotulo: 'Manutenção (meuPlano)', token: 'meuplano' },
  { campo: 'bot_helper', rotulo: 'Usina ao vivo (helper)', token: 'meuwatt' },
]

/** "Geração (meuWatt) · Manutenção (meuPlano) (falta o token)" — o liberado, e o que está parado. */
export function textoDoBot(liberado: ProdutoDoBot[], tokens: Produto[], temCelular: boolean): string {
  if (!temCelular) return 'sem celular — o bot não reconhece a pessoa'
  const partes = PARTES_DO_BOT.filter((p) => liberado.includes(p.campo)).map((p) =>
    tokens.includes(p.token) ? p.rotulo : `${p.rotulo} (falta o token)`,
  )
  return partes.join(' · ') || 'bloqueado'
}

/** Desativar tira a pessoa na hora (painel, aplicativo e bot): pergunta antes. Reativar, não. */
export function confirmaAtivacao(nome: string, ativoAgora: boolean): boolean {
  return (
    !ativoAgora ||
    window.confirm(`Desativar ${nome}? A pessoa para de entrar na hora (painel, aplicativo e bot). Dá para reativar depois.`)
  )
}

export function quando(iso: string | null): string {
  if (!iso) return 'nunca'
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo' })
}
