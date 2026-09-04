/**
 * Paradas — Quanto tempo e quanta energia perdi com paradas?
 *
 * ⛔ ESQUELETO. A tela real entra no item PT-5 do plano do portal do cliente. Este arquivo
 * existe para o roteador ter um destino desde o primeiro dia: uma rota que aponta para o
 * vazio quebra a navegação inteira, e um placeholder honesto — que DIZ que ainda não foi
 * construído — é melhor que uma tela em branco que se lê como erro.
 *
 * Ao implementar: apague este conteúdo, não o arquivo. O caminho do módulo está no
 * `src/App.tsx` e o nome do arquivo é o contrato com o roteador.
 */

import { Pagina, Vazio } from '@/components/base'

export default function Paradas() {
  return (
    <Pagina titulo="Paradas" subtitulo="Quanto tempo e quanta energia perdi com paradas?">
      <Vazio
        titulo="Em construção"
        descricao="Esta tela ainda não foi construída. Ela vai responder: quanto tempo e quanta energia perdi com paradas?"
      />
    </Pagina>
  )
}
