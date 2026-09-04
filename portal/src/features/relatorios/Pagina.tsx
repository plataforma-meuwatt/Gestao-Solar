/**
 * Relatórios — O que a equipe fez no período, em um documento?
 *
 * ⛔ ESQUELETO. A tela real entra no item PT-10 do plano do portal do cliente. Este arquivo
 * existe para o roteador ter um destino desde o primeiro dia: uma rota que aponta para o
 * vazio quebra a navegação inteira, e um placeholder honesto — que DIZ que ainda não foi
 * construído — é melhor que uma tela em branco que se lê como erro.
 *
 * Ao implementar: apague este conteúdo, não o arquivo. O caminho do módulo está no
 * `src/App.tsx` e o nome do arquivo é o contrato com o roteador.
 */

import { Pagina, Vazio } from '@/components/base'

export default function Relatorios() {
  return (
    <Pagina titulo="Relatórios" subtitulo="O que a equipe fez no período, em um documento?">
      <Vazio
        titulo="Em construção"
        descricao="Esta tela ainda não foi construída. Ela vai responder: o que a equipe fez no período, em um documento?"
      />
    </Pagina>
  )
}
