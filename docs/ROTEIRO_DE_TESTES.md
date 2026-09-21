# Roteiro de testes — notificações por WhatsApp

Este documento serve a duas perguntas diferentes, e é importante não confundi-las:

| Pergunta | Quem responde | Como rodar |
|---|---|---|
| *O código faz o que promete?* | `pytest`, no repositório | `cd bff && PYTHONPATH=. venv/bin/python -m pytest -q` |
| *Está tudo ligado AGORA?* | **a bateria de autoteste**, contra o ambiente real | Painel → Diagnóstico → **Rodar autoteste** |

O `pytest` continua verde mesmo com o token da Meta vencido, porque ele não fala com a
Meta. A bateria existe para isso: ela roda contra as credenciais de verdade e responde se
o mundo em volta do código continua no lugar.

**A bateria não altera nada.** Nenhum envio real, nenhuma linha gravada — o motor roda em
modo simulação. Pode ser rodada a qualquer hora, inclusive num dia de trabalho, quantas
vezes quiser. É por isso que ela serve de conferência periódica: o resultado de hoje e o
de daqui a três semanas têm de ser o mesmo.

---

## Como rodar

**Pela tela:** Painel → Diagnóstico → *Rodar autoteste*. Exige a área `diagnostico`.

**Pela API**, para quem quiser automatizar:

```bash
curl -s -X POST https://gestao-solar-production.up.railway.app/api/painel/autoteste \
     -H "Authorization: Bearer <token de sessão do painel>" | jq
```

A resposta traz `passou` (booleano), `resumo` (quantos ok / alerta / falha), `duracao_ms`
e a lista de itens, cada um com `situacao`, `detalhe` e `evidencia`.

**Verde é ausência de FALHA.** `alerta` não reprova: ele marca um estado que é normal hoje
e não pode virar permanente — "nenhum cliente marcou aviso", por exemplo, é esperado numa
instalação nova e é problema daqui a um mês.

---

## O que cada item prova, e o que fazer quando acende

### 1. `banco` — Banco de dados
Prova que o BFF fala com o Postgres e conta clientes e usinas ativas.
**Falha:** o banco está fora ou a `DATABASE_URL` mudou. Nada mais funciona; comece por aqui.

### 2. `credencial` — Credencial do WhatsApp
Prova que o gateway responde e que o último teste contra a Meta passou.
**Falha comum:** token vencido. Tokens de usuário do sistema não expiram sozinhos, mas são
revogados quando alguém clica em "Anular tokens" ou troca a senha da conta. Gere outro em
Gerenciador de Negócios → Usuários do sistema e grave em Painel → WhatsApp.

### 3. `numero` — Número em uso
Compara o Phone Number ID gravado com a lista de números da conta na Meta.
**Existe por um erro real:** em 21/09/2026 o número de *teste* foi gravado no lugar do
comercial, e o teste de conexão respondeu "ok" — porque enviar usa o id do número, e
aquele id existia. Só a comparação com a conta revela a troca.
**Falha:** o número gravado não é desta conta. Confira Phone Number ID e WABA ID.

### 4. `templates` — Modelos de mensagem
Prova que existe um modelo **aprovado** para cada tipo do catálogo, com o nome que o motor
procura (`gs_usina_parada`, `gs_manutencao_iniciada`, …).
**Falha:** falta modelo na Meta. Crie com o nome exato, categoria *Utilidade*, idioma
Português (BR).
**Alerta:** modelo existe mas está em análise ou reprovado — nada sai até aprovar.

### 5. `catalogo` — Catálogo × modelos
Prova que os dois lados do código concordam: todo tipo tem modelo, e todo modelo tem tipo.
**Falha:** alguém acrescentou um tipo sem modelo (ou o contrário). É defeito de código, não
de configuração.

### 6. `clientes` — Clientes aptos
Conta quem pode receber: conta ativa, com telefone e com o aceite registrado.
**Alerta:** ninguém apto. A frase diz qual dos três falta e em quantas contas.

### 7. `preferencias` — Preferências marcadas
Conta a matriz tipo × usina × cliente e procura **marcações órfãs**: preferência de uma
usina que não é mais daquele cliente. Elas não enviam nada (o motor reconfere o escopo),
mas enganam quem lê a tela.
**Alerta:** existem órfãs, ou não existe marcação nenhuma.

### 8. `motor` — Motor (simulação)
Roda o motor inteiro sem enviar: coletores leem os upstreams, a matriz decide quem
receberia, a trava de repetição é consultada. É o item que prova que o caminho funciona
hoje.
**Zero evento não é falha** — pode simplesmente não haver nada acontecendo, que é o estado
desejável de uma usina.
**Alerta:** algum coletor não conseguiu ler (upstream fora, usina sem ninguém conectado).
A frase diz qual usina e por quê.
**Falha:** o motor levantou exceção. É defeito de código.

### 9. `log` — Log de notificações (7 dias)
Resume o que saiu na última semana, por situação (`enviada`, `entregue`, `lida`, `falhou`).
**Alerta:** nada foi registrado, ou houve falhas no meio.
**Falha:** *todas* falharam — sinal de template pausado, número bloqueado ou conta sem
forma de pagamento.

---

## Roteiro manual — o que a bateria não alcança

Três coisas dependem de um aparelho de verdade e devem ser feitas na primeira validação, e
de novo sempre que o número ou os modelos mudarem:

1. **Envio real.** Painel → WhatsApp → *Enviar teste*: escolha um modelo aprovado e o seu
   próprio telefone. Deve chegar em segundos, com o nome **Gestão Solar** no topo.
2. **Trilha de status.** Depois de receber, abra a mensagem e espere um minuto. Em
   Painel → Notificações → histórico do cliente, a linha tem de andar de `enviada` para
   `entregue` e, depois de você abrir, para `lida`. Isso prova o webhook de status inteiro.
3. **Recebimento.** Mande um "oi" do seu celular para o número da empresa. Ele tem de
   aparecer no gateway (tabela `wa_mensagens`, direção `entrada`). Prova o webhook de
   entrada, que é o que a janela de 24 h do atendimento depende.

---

## Rodando o motor de verdade

O motor é **idempotente**: a trava está em `gs_notificacoes_enviadas` (único por
destinatário + chave do evento), então rodar duas vezes não manda duas vezes.

```bash
# simulação — não envia nada, mostra o que sairia
curl -s -X POST "https://gestao-solar-production.up.railway.app/api/v1/interno/notificacoes/disparar?simular=true" \
     -H "X-Avisos-Token: <AVISOS_TOKEN>" | jq

# de verdade
curl -s -X POST "https://gestao-solar-production.up.railway.app/api/v1/interno/notificacoes/disparar" \
     -H "X-Avisos-Token: <AVISOS_TOKEN>" | jq
```

Pela tela, Painel → Notificações → *Disparar agora* **vem com a simulação ligada por
padrão**: um clique distraído não pode mandar mensagem para cliente.

---

## O que ainda não é coberto

- **Envio de PDF** — em construção.
- **Grupos do WhatsApp** — a API oficial só fala com grupos criados por ela, com no máximo
  oito participantes e exigindo Conta Comercial Oficial. Por isso os avisos vão para cada
  pessoa no privado, via contatos da usina.
- **Texto livre (atendimento)** — o gateway ainda só envia template; a janela de 24 h será
  a próxima frente.
