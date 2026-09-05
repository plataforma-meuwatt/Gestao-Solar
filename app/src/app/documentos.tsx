/**
 * Ponte permanente: `/documentos` → `/relatorios`.
 *
 * A aba mudou de nome, e no expo-router o nome do arquivo **é** a rota: `(tabs)/documentos.tsx`
 * virou `(tabs)/relatorios.tsx`. Nada no repositório gera `gestaosolar://documentos` — não há
 * listener de resposta a notificação, e nenhuma tela liga para cá —, mas o esquema
 * `gestaosolar` torna a rota válida por construção, e link que alguém guardou não pode virar
 * rota morta. O expo-router não redireciona sozinho: sem este arquivo, quem abrir o endereço
 * antigo cai na tela de rota desconhecida.
 *
 * Permanente de propósito. Uma ponte com prazo é uma ponte que ninguém lembra de conferir
 * antes de derrubar — e o custo dela é um arquivo de doze linhas.
 */

import { Redirect } from 'expo-router'

export default function PonteDocumentos() {
  return <Redirect href="/relatorios" />
}
