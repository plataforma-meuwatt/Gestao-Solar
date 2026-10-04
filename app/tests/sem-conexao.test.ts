/**
 * O que este arquivo guarda: o aplicativo nunca mais acusa a rede de QUEM USA por
 * lentidão do nosso servidor.
 *
 * Em 04/10/2026 o dono abriu o app no Wi-Fi e no 5G e leu "Sem conexão" na faixa do
 * alto. A rede dele estava perfeita: `GET /api/v1/home` estava levando 5 a 30 s (o elo
 * lento era a leitura ao vivo do MICRO, nos portais dos fabricantes) e o aplicativo
 * desiste em 12 s. A faixa calculava `offline` como "existe erro", então o nosso timeout
 * virava falta de internet — e a pessoa vai reiniciar o roteador.
 *
 * **Como rodar:** `cd app && node --test tests/sem-conexao.test.ts`
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'

const RAIZ = join(import.meta.dirname, '..', 'src')

test('o frescor distingue rede, demora e erro do servidor', () => {
  const cache = readFileSync(join(RAIZ, 'lib', 'cache.ts'), 'utf8')

  // O campo existe e tem os três valores nomeados.
  assert.match(cache, /problema: 'rede' \| 'demora' \| 'servidor' \| null/)
  // E `offline` passa a DERIVAR dele, em vez de ser "existe erro".
  assert.match(cache, /offline: problema === 'rede'/)
  assert.ok(
    !/offline: mostrandoCache && consulta\.error != null/.test(cache),
    'voltou a chamar qualquer erro de "sem conexão"',
  )

  // O estouro de prazo é reconhecido pelos três jeitos que o axios usa — testar só um
  // deixava o timeout cair no ramo de "sem resposta", que é o defeito original.
  for (const marca of ["'ECONNABORTED'", "'ETIMEDOUT'", '/timeout/i']) {
    assert.ok(cache.includes(marca), `o reconhecimento de prazo perdeu ${marca}`)
  }
})

test('a faixa do alto diz de QUEM é o problema', () => {
  const base = readFileSync(join(RAIZ, 'components', 'base.tsx'), 'utf8')

  assert.match(base, /'Sem conexão'/)
  assert.match(base, /'O servidor demorou'/)
  assert.match(base, /'O servidor falhou'/)
  // A frase antiga dizia "Sem conexão" para os três casos.
  assert.ok(
    !/frescor\.offline \? \(\s*<>\s*Sem conexão/.test(base),
    'a faixa voltou a culpar a conexão por qualquer falha',
  )
})

test('o prazo do aplicativo e a mensagem de erro continuam combinando', () => {
  const api = readFileSync(join(RAIZ, 'lib', 'api.ts'), 'utf8')
  const prazo = /timeout:\s*(\d+)/.exec(api)
  assert.ok(prazo, 'o axios ficou sem prazo declarado')
  // Um prazo muito curto transforma servidor lento em erro; muito longo deixa a tela
  // cinza. 12 s é o valor medido como suportável com o cache na frente.
  assert.ok(Number(prazo[1]) >= 10_000, 'prazo curto demais: lentidão vira erro')
  // E o erro de prazo tem frase própria, que não fala de internet.
  assert.match(api, /ECONNABORTED.*demorou/s)
})
