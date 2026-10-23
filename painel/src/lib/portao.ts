/**
 * Qual PORTA do painel este endereço é — escrito em `/config.js` quando o contêiner sobe
 * (`PORTAO`, ver `entrypoint.sh`). O mesmo bundle serve os dois endereços:
 *
 * - `plataforma` → adm-gs: só o administrador/atendimento da plataforma;
 * - `empresa`    → oem-gs: só o gerente da empresa de O&M (e o técnico dela);
 * - vazio        → desenvolvimento e os endereços provisórios: aceita todos.
 *
 * Isto é ORGANIZAÇÃO, não segurança: quem separa os perfis de verdade é a API, que só abre
 * a cada token as rotas do portão dele.
 */
import type { Escopo } from '@/store/auth'

declare global {
  interface Window {
    __GS_PORTAO__?: string
    __GS_ENDERECO_GS__?: string
    __GS_ENDERECO_OEM__?: string
  }
}

export const PORTAO = (window.__GS_PORTAO__ ?? '') as '' | 'plataforma' | 'empresa'

export function aceita(escopo: string): boolean {
  if (PORTAO === 'plataforma') return escopo === 'painel'
  if (PORTAO === 'empresa') return escopo === 'empresa' || escopo === 'tecnico'
  return true
}

/** O endereço certo para quem bateu na porta errada. */
export function enderecoDe(escopo: Escopo | string): string {
  return (escopo === 'painel' ? window.__GS_ENDERECO_GS__ : window.__GS_ENDERECO_OEM__) ?? ''
}

export function fraseDaPortaErrada(escopo: Escopo | string): string {
  const destino = enderecoDe(escopo)
  const quem = escopo === 'painel' ? 'da administração da plataforma' : 'do gerente da empresa de O&M'
  return `Esta conta é ${quem}${destino ? ` — entre em ${destino.replace(/^https?:\/\//, '')}` : ''}.`
}

export const TITULO =
  PORTAO === 'plataforma'
    ? 'Administração da plataforma'
    : PORTAO === 'empresa'
      ? 'Painel da empresa de O&M'
      : 'Painel de administração'
