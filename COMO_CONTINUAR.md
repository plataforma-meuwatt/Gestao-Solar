# Como continuar — Gestão Solar

Escrito em **16/09/2026**, para quem abrir este repositório numa máquina nova (ou numa sessão
nova de assistente). Descreve o que **está no ar**, o que **falta**, e as armadilhas que já
custaram tempo. Quando este arquivo divergir do código, o código vence.

Leia antes: [`CLAUDE.md`](CLAUDE.md) (regras do projeto) e
[`docs/PLANO_WHATSAPP_NOTIFICACOES.md`](docs/PLANO_WHATSAPP_NOTIFICACOES.md) (o plano em curso,
com as fases e o que cada uma entrega).

---

## 1. Onde estão os segredos

**`C:\Dev\Gestao Solar\.env`** — o cofre. Não é lido por aplicação nenhuma: cada serviço lê o
`.env` dele ou as variáveis do Railway. É o que você leva no pendrive.

Está dividido em blocos, e o bloco **[1]** é o que a sua máquina precisa: copie-o para
`bff/.env` e o backend local sobe. Os blocos [2]–[4] são espelho do que está em produção
(Railway), e o [5] é o `.env.txt` da raiz copiado como está (tokens do Expo, do Railway, do
Render e da Meta).

Os outros dois projetos têm cofre equivalente: `C:\Dev\meuPlano\.env` e `C:\Dev\meuWatt\.env`.

⚠️ **Os três estão fora do git** — conferido com `git check-ignore`. Não renomeie: no meuPlano
só o nome exato `.env` é ignorado, e um `.env.bak` entraria num `git add -A`.

⚠️ **A senha do banco escrita no `.env.txt` não é a que está em uso.** Conferido em 16/09/2026:
a do `.env.txt` tem 15 caracteres e nenhum `#`; a que o BFF usa tem 17 e traz `%23`. **Não são
a mesma senha em formatos diferentes** — são senhas diferentes, e a boa é a do `bff/.env`. Se
precisar montar uma URL nova, parta dela.

**A chave que não pode se perder é a `GATEWAY_ENCRYPTION_KEY`** (bloco [3]): é ela que decifra
o token da Meta guardado no banco do gateway. Perdê-la significa recadastrar as credenciais na
tela — não é fatal, mas é trabalho.

---

## 2. O que está no ar, hoje

| Peça | Endereço | Deploy |
|---|---|---|
| **back** (BFF) | `gestao-solar-production.up.railway.app` | **no push** |
| **painel** (gestor) | `gestaosolar.up.railway.app` | ⛔ à mão |
| **portal** (cliente) | `appgestao-production-15cb.up.railway.app` | ⛔ à mão |
| **gateway WhatsApp** | `whatsapp-production-2201.up.railway.app` | ⛔ à mão |
| **app** (Expo) | lojas / APK interno | OTA, canal `preview` |

⛔ **Só o BFF sobe no push.** Um push que mexe só em `painel/`, `portal/` ou `whatsapp/` **não
muda nada em produção**, e a falha é silenciosa: o site continua no ar com o código antigo e o
healthcheck diz que está tudo bem. Publicar é à mão:

```bash
unset RAILWAY_TOKEN   # o token do .env.txt tem escopo menor e ESCONDE metade do projeto
P=ae0386b7-5b51-44fe-bb74-d41ac885903a
railway redeploy --service front     --environment production --project $P --from-source -y
railway redeploy --service whatsapp  --environment production --project $P --from-source -y
```

`--from-source` é o que importa: sem ele o comando reimplanta a mesma imagem e o bundle antigo
volta parecendo deploy novo. **Confirme por arquivo ou por probe, nunca pelo status** — o
passo a passo está no `CLAUDE.md` §6 e §9.

### Rodar local

```powershell
.\dev.ps1 -Instalar    # primeira vez
.\dev.ps1              # back (8100) + painel (5180) + portal (5181)
```

Testes: `cd bff; $env:PYTHONPATH="$PWD"; .\venv\Scripts\python.exe -m pytest` (965 passam) ·
`cd painel; npx tsc --noEmit` · `cd whatsapp; $env:PYTHONPATH="$PWD"; pytest` (51 passam).

---

## 3. O que acabou de ser feito (11–16/09/2026)

1. **Alarme de parada em minutos, não em 16.** O meuPlano consultava o meuWatt de 10 em 10
   minutos; passou para 5, e o meuWatt agora **avisa por webhook** assim que confirma a parada.
   Os dois lados estão no ar e foi provado em produção.
2. **Central de notificações** no painel, dentro da ficha do cliente: telefone, aceite por
   contrato e a matriz *tipo de aviso × usinas daquele cliente*. **Nada nasce ligado.**
3. **Gateway de WhatsApp** (`whatsapp/`), serviço próprio: recebe da Meta e envia pela Meta.
4. **Painel → Sistema → WhatsApp**: a tela onde as credenciais da Meta são cadastradas —
   cifradas no banco do gateway, **não em variável de ambiente**, porque quem configura precisa
   testar sem pedir um redeploy a cada tentativa.

---

## 4. O próximo passo, na ordem

### 4.1 Na Meta (é o que destrava tudo)

1. Gerar um token **permanente** (usuário do sistema, no Gerenciador de Negócios). O token que
   o painel do app mostra expira em 24 horas.
2. Abrir **Painel → WhatsApp** e colar token, Phone Number ID e segredo do app. A tela testa
   contra a Meta antes de gravar: se ela recusar, a credencial anterior continua de pé e o
   motivo aparece escrito.
3. Registrar o webhook com o endereço que a própria tela mostra para copiar
   (`https://whatsapp-production-2201.up.railway.app/webhook`) e assinar o campo `messages`.
4. Submeter os **6 templates** (categoria utilidade) da tabela do plano — parada, OS iniciada,
   OS finalizada, energia do dia/semana/mês.

Identificadores já conhecidos (número de **teste**): Phone Number ID `1352387357947608`,
WABA `1050499467726264`, App `1088684893680434`, Business `1991828342203971`.

### 4.2 Depois, nesta ordem

| # | Onde | O quê |
|---|---|---|
| 0 | meuPlano | **Corrigir o vazamento do PAT no assistente** — está detalhado no plano, §Entrega 0. É falha de segurança, vem antes do resto. |
| 3 | mw-api | `plant_day_closures` + rota de fechamento do dia (o "ok" do meuWatt para os avisos de energia) e o **500 do `GET /plants/{slug}/breakdowns/range`**, cuja causa provável já está escrita no plano. |
| 4 | meuPlano | `service_order_eventos` — o carimbo de "OS iniciada/finalizada" que hoje não existe. |
| 5 | BFF | O **motor**: quem decide quem recebe o quê, com a trava contra repetição. |
| 7 | Railway | O relógio que chama as rotas internas, primeiro com `simular=true`. |

---

## 5. Armadilhas registradas (todas custaram um erro real)

- **`railwayConfigFile` não é mais aceito pela API do Railway.** Config as Code está deprecado;
  a configuração do serviço `whatsapp` mora no painel, gravada por API. O `whatsapp/railway.json`
  continua no repo porque arquivos existentes valem **até 2026-12-01**.
- **Dois serviços no mesmo banco precisam de `version_table` própria no Alembic.** O gateway
  divide o Supabase com o BFF; sem isso ele leu a cadeia de migrations do BFF e morreu com
  `Can't locate revision identified by 'c41d9b6e7a05'` — mensagem que parece migration
  corrompida e é a cadeia errada. O gateway usa `alembic_version_gateway`.
- **Não exporte `RAILWAY_TOKEN`.** A máquina está logada na conta; o token do `.env.txt` tem
  escopo de projeto e faz `front` e `appgestao` sumirem da listagem, com um `Unauthorized` que
  parece falta de permissão da conta.
- **O `urllib` do Python é barrado (403) pela API do Railway** por User-Agent. Use `curl` ou
  mande um `User-Agent` qualquer.
- **SQLite em memória nos testes precisa de `StaticPool`**, senão o TestClient (que atende em
  outra thread) enxerga um banco vazio e o erro sai como `no such table`.

---

## 6. Como provar que algo está no ar

Status não é prova. O par rota-nova × caminho-irmão-inexistente:

```bash
B=https://gestao-solar-production.up.railway.app
curl -s -o /dev/null -w "%{http_code}\n" $B/api/painel/whatsapp-nao-existe   # 404 = controle
curl -s -o /dev/null -w "%{http_code}\n" $B/api/painel/whatsapp              # 401 = está no ar

G=https://whatsapp-production-2201.up.railway.app
curl -s $G/health                        # {"status":"ok","ambiente":"production"}
curl -s -o /dev/null -w "%{http_code}\n" $G/interno/credenciais   # 401 — se der 200, é grave
```

Para abrir uma **tela** do painel sem a senha do dono, há um caminho com Playwright descrito no
`CLAUDE.md` §6 (sessão injetada no `localStorage` antes do primeiro render, chave
`gs_painel_sessao`, no formato `{token, nome, apelido, perfil}`).

---

## 7. A máquina Linux (`srvclaude`) — conferido em 17/09/2026

O trabalho também roda num servidor Ubuntu 24.04 (`srvclaude`), com o repositório em
`/root/DEVV/Gestao Solar/Gestao-Solar`. Os caminhos `C:\Dev\...` deste guia e do `CLAUDE.md`
não existem lá. O que muda:

- **Não há `.env.txt`.** Os valores dele estão comentados no bloco **[5]** do `.env` da raiz
  (`# Expo: …`, `# Token Railway: …`). O comando do `CLAUDE.md` §9 não acha nada lá; use:
  `export EXPO_TOKEN=$(sed -n 's/^# Expo:[[:space:]]*//p' .env | tr -d '\r')`.
- **Credenciais testadas e válidas:** `gh` logado como `prnmarchesini` (push funciona),
  `railway whoami` → conta (enxerga os cinco serviços depois do `railway link`), `EXPO_TOKEN`
  autentica no `eas-cli`, e as quatro `DATABASE_URL` (a do `bff/.env` e as três do cofre)
  conectam no Supabase.
- **Falta instalar:** `bff/venv` não existe, `eas` só por `npx eas-cli@latest`, sem `psql`.
  O `dev.ps1` é PowerShell e não roda lá — suba cada parte à mão.
