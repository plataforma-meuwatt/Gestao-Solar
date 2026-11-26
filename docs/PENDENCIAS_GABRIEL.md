# Pendências do Gabriel (26/11/2026)

O Renan quer **tudo isto rodado hoje**. Cada item diz o que fazer, onde está o material e como provar que ficou pronto.
Avise o Renan (ou o terminal do Claude da VM dele) ao terminar cada um: alguns só fecham quando algo é desligado lá.

Acessos que você já tem: cofre (coleções "Gestão Solar · meuWatt · meuPlano", "TermoVision", "meuGuarda" e "Gabriel"),
GitHub (Gestao-Solar, meuPlano, termosolar e meuGuarda), bancos só leitura do meuPlano e do GS, a cópia do banco do
meuPlano para editar, a bancada (http://10.200.20.32:8092) e o `dev-helper.gestao.solar`. Tudo pela VPN.

## 1. Aceitar os convites do GitHub (2 min)
Os 6 repositórios da organização meuGuarda (contratos, agente-usina, servidor-central, api-gestao, frontends, infra), com
escrita. **Pronto quando:** você consegue dar push num deles.

## 2. Conhecer o que mudou na sua VM (produção do helper) — não desfazer
Hoje à tarde a produção do helper saiu da VM do Renan e foi para a sua (srvmwhelpoer):
- `~/.config/mw-helper/env` do gabriel ganhou `MW_BOT_CALLERS_FILE` (a porta do bot do GS), `MW_TRACKER_EXECUTOR=1`
  (a automação dos trackers de Ibitinga, ARMADA; só pode haver UM executor, e agora é o seu) e `MW_NETMON*` (o monitor
  de rede, fonte `srvmwhelpoer`). Backups: `env.bak.20261126-*`.
- Dois serviços de sistema novos (root): `bot-filtro` (o filtro do túnel, só deixa passar o bot, o selo da VPN e o
  unifilar público; 127.0.0.1:18081) e `tunel-helper` (túnel reverso até a KingHost, usuário `tunelhelper`, que só
  pendura 10.0.1.1:18081). O GS chama o helper por `HELPER_BOT_URL=http://10.0.1.1:18081`.
- O deploy da main não toca em nada disso (o rsync não leva o `~/.config`).
**Pronto quando:** você leu e sabe que esses serviços e variáveis agora são produção.

## 3. As duas sondas dentro do coletor (mw-core)
Hoje elas rodam como agendamentos na VM do Renan e passam pela API do meuWatt. O Renan: "isso precisa fazer parte do
coletor". Código de referência (o que cada uma lê e para onde manda): `docs/referencia-sondas/`.

**3a. Diagnóstico dos inversores** (`mw-diag-sonda.py`, 06h–10h, a cada 10 min): dos Huawei que ainda não ligaram no
dia, lê 32008+87 (alarmes, isolação, status, código de falha, hora da partida) e, na 1ª partida, o 42097 (limite).
O coletor hoje manda `fault_code` NULL de todas as usinas: só esta sonda lê o motivo. Destino:
`POST /ingestion/plants/{slug}/inverter-diagnostics` com `source = "coletor"`.
**Pronto quando:** o diagnóstico chega com `source = "coletor"` de todas as usinas. Aí o Renan desliga o
`mw-diag-sonda.timer` na VM dele.

**3b. Limites do gêmeo** (`gemeo-limites-sonda.py`, todo dia 11h30): para as usinas com gêmeo
(`GET /gemeos/limites/alvos` do mw-analise), o ajuste de potência ativa em vigor (35300–35303) de cada Huawei; às
segundas e na 1ª vez também 30073–30076, 40120–40127 e 42405–42406. Destino hoje: `POST /gemeos/limites/leituras` do
mw-analise, assinado como o espelho (HMAC). Decida se o coletor manda direto ao mw-analise ou ao mw-api (que repassa).
**Pronto quando:** a leitura diária chega pelo coletor. Aí o Renan desliga o `gemeo-limites.timer`.

## 4. Concluir o Plano Assistente GS (automações e memória do bot)
O plano inteiro: `docs/PLANO_ASSISTENTE_GS.md` (a Fase 1 está no ar desde 26/11; a seção "Automações e memória do bot"
do `CLAUDE.md` diz como o código funciona). Decisões do Renan já tomadas:
- **2.** "Me lembra de…" é lembrete do GS; "cria um lembrete no meuPlano" vai ao meuPlano (já é assim).
- **3.** O dono de usina pode criar regra com IA, **só para ele**: tirar a trava `EQUIPE` em
  `automacoes._rodar_ia` e em `assistente_automacoes.criar_automacao`, tirar o "(só a equipe)" da descrição da
  ferramenta, inverter o teste `test_cliente_nao_pede_analise_de_ia_na_automacao` (pode, e avisa só a ele). O teto de
  20 IAs por dia por pessoa continua.
- **4.** Pedir a regra ao bot vale como aceite dela (já é assim).
- **5.** Fase 2: o bot pode PROPOR o que notar do jeito da pessoa, gravando só com o Sim.
- **6.** E-mail por remetente próprio do GS: o Renan cria a caixa; o DNS do gestao.solar hoje tem SPF `-all` e DMARC
  `reject` (recusa tudo) e precisa do SPF/DKIM do provedor; o envio usa `GS_SMTP_*` (já existe no código do "esqueci a
  senha").
- **1.** Os modelos de mensagem da Meta (`gs_aviso` etc.) ficam com o Renan.
Depois, as Fases 2 e 3 do plano. **Regra:** mudança no prompt ou nas ferramentas do bot só vai à main depois do banco
de perguntas inteiro no seu branch, pela bancada (Testes do bot).

## 5. Bot: dizer o motivo quando o helper não está liberado
Caso do Marlon (26/11): ele pediu "Destrave" e o bot respondeu "não tenho ferramenta de comando de tracker", porque a
parte helper dele estava desligada. A resposta certa é "comandar equipamento não está liberado para você; peça ao
gerente (oem-gs › Bot do WhatsApp)". **Pronto quando:** o caso entra no banco de perguntas e passa.

## 6. App do meuPlano com o nome "GS meuPlano"
Regra do Renan: APK novo da família sai com o nome começando por GS. Hoje o `expo.name` do `mobile/app.json` é
"meuPlano Campo"; a bancada recusa o APK até trocar. Troque, publique na main e peça o APK pela bancada.

## 7. Banco de perguntas: os 26 casos que falham
26 dos 399 casos do `testes-ia/banco.json` falham (os mesmos de antes das automações). A regra da casa pede o banco todo
certo. Rode pela bancada, ataque os casos e volte a rodar.

## 8. HTTPS do helper.gestao.solar (opcional hoje)
O nome aponta para o IP da VPN (10.200.20.34): o certificado só sai por validação no DNS da Hostinger. Hoje o nginx
responde com o certificado do nome antigo. Ponha o `server_name` novo e o certificado quando tiver como validar.

## O que NÃO é seu (fica com o Renan ou com o Claude da VM dele)
OTA do app (sai pela bancada, pelo script seguro), a IA paliativa (`llm-claude`, na VM do Renan), os modelos da Meta,
a troca dos segredos que apareceram numa saída de comando em 26/11, a senha de atuação do Marlon.
