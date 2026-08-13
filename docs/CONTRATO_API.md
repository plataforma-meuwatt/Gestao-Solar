# Contrato da API do BFF

Base: `/api/v1`. Todo endpoint exige `Authorization: Bearer <jwt do Gestão Solar>`, exceto
`/auth/login` e `/health`.

Formato de erro: `{"detail": "mensagem em português"}` — o app exibe `detail` direto.

---

## Autenticação

### `POST /auth/login`

```json
{ "email": "dono@empresa.com.br", "senha": "..." }
```

O BFF tenta autenticar nos dois upstreams. Basta um aceitar.

```json
{
  "token": "eyJ...",
  "expira_em": "2026-08-12T14:30:00Z",
  "usuario": {
    "id": 12,
    "nome": "Renan",
    "email": "dono@empresa.com.br",
    "empresa": "Solar Ltda",
    "tem_meuwatt": true,
    "tem_meuplano": true,
    "nivel_acesso": 2
  }
}
```

`401` quando nenhum dos dois aceita. `403` quando o usuário existe mas não é proprietário.

### `GET /me`

Devolve o mesmo objeto `usuario` acima, com a lista de usinas acessíveis.

---

## Início

### `GET /home`

Tudo que a tela inicial precisa, numa chamada só.

```json
{
  "potencia_agora_kw": 4820.5,
  "capacidade_total_kwp": 6200.0,
  "energia_hoje_mwh": 28.4,
  "atencao": [
    { "severidade": "parado", "texto": "2 inversores parados em Porto Ferreira",
      "usina_id": 3, "equipamento_id": "slot-14" }
  ],
  "meuwatt": {
    "geracao_mes_mwh": 612.3, "meta_mes_mwh": 680.0, "pr_pct": 81.4
  },
  "meuplano": {
    "servicos_mes_concluidos": 3, "servicos_mes_total": 4,
    "meses": ["verde","verde","azul","laranja",null,null,null,null,null,null,null,null]
  },
  "financeiro": { "situacao": "em_dia", "proximo_vencimento": "2026-09-05" },
  "notificacoes": [ { "id": 88, "titulo": "...", "resumo": "...", "quando": "2026-08-11T09:12:00Z", "lida": false } ]
}
```

---

## Usinas

### `GET /plants`

```json
[
  { "id": 3, "nome": "Porto Ferreira", "cidade": "Porto Ferreira", "uf": "SP",
    "kwp": 2400.0, "status": "ok",
    "energia_hoje_mwh": 12.8, "potencia_agora_kw": 1980.0,
    "curva_dia": [0, 12, 340, 890, 1450, 1980, 1870, 1200, 410, 0],
    "tem_meuwatt": true, "tem_meuplano": true }
]
```

`status` é sempre um dos seis tons: `parado` · `alerta` · `multiplos` · `tempo_ruim` ·
`ok` · `sem_dados`.

### `GET /plants/{id}/overview`

KPIs do dia, curva de potência + irradiância, resumo de equipamentos, situação da
manutenção e clima. Alimenta a aba "Geral" da usina.

### `GET /plants/{id}/generation/daily?date=YYYY-MM-DD`

Espelha `DailyGenerationReport` do mw-api, reduzido ao que a tela usa: KPIs, curva,
lista por UC, eventos do dia.

### `GET /plants/{id}/generation/range?start=&end=`

Mensal e anual usam o mesmo endpoint, mudando só o intervalo. Máximo de 366 dias (limite
do upstream).

### `GET /plants/{id}/ucs?start=&end=`

Ranking por UC (= transformador), série diária e conta de energia quando houver.

### `GET /plants/{id}/map`

Árvore esquemática para a tela de Mapa da Planta:

```json
{
  "resumo": { "potencia_agora_kw": 1980.0, "energia_hoje_mwh": 12.8,
              "pr_pct": 81.4, "equipamentos_ok": 18, "equipamentos_total": 20 },
  "protecao_geral": { "id": "relay-1", "nome": "Relé Geral", "status": "ok" },
  "transformadores": [
    { "id": "trafo-1", "nome": "Skid 1", "kva": 1500,
      "inversores": [
        { "id": "slot-1", "nome": "INV 01", "potencia_kw": 118.4, "status": "ok" }
      ] }
  ],
  "estacoes": [ { "id": "ws-1", "nome": "Solarimétrica", "irradiancia_wm2": 812.0,
                  "temp_modulo_c": 48.2, "status": "ok" } ],
  "reles_temperatura": []
}
```

### `GET /plants/{id}/equipment`

Lista agrupada por tipo, com leitura principal e status de cada item.

### `GET /equipment/{id}`

Detalhe do equipamento. O formato varia por tipo (`tipo`: `inversor` |
`estacao_solarimetrica` | `rele_protecao` | `rele_temperatura` | `transformador`), sempre
com `kpis[]`, `status`, `serie_dia[]` e, para inversor, `paradas[]` com início, fim,
duração em minutos, causa e perda estimada.

### `GET /plants/{id}/breakdowns?start=&end=`

Histórico de paradas, agrupado por dia.

---

## Manutenção

### `GET /plants/{id}/schedule`

Matriz do cronograma anual. As cores vêm prontas do meuPlano — o BFF não recalcula.

```json
{
  "ano": 2026,
  "itens": [
    { "id": 41, "nome": "Termografia",
      "meses": [null,"verde",null,null,"azul",null,null,null,null,null,null,null] }
  ],
  "legenda": { "verde": "Cumprido", "azul": "No prazo",
               "laranja": "Venceu há pouco", "vermelho": "Vencido" }
}
```

### `GET /plants/{id}/schedule/{itemId}?mes=YYYY-MM`

O item e as OS que o atenderam.

### `GET /plants/{id}/service-orders?status=&start=&end=`

### `GET /service-orders/{id}`

Detalhe da OS: dados, tarefas com situação individual, parecer, fotos.

---

## Documentos

### `GET /documents?tipo=&plant_id=`

`tipo`: `relatorio` | `os` | `cronograma`.

```json
[
  { "id": "mw-report-1841", "tipo": "relatorio", "titulo": "Relatório de Geração",
    "periodo": "Julho 2026", "emitido_em": "2026-08-03", "tamanho_bytes": 2841022,
    "plant_id": 3 }
]
```

### `POST /documents/generate`

```json
{ "tipo": "mensal", "plant_id": 3, "competencia": "2026-07" }
```

Dispara o Chromium headless. Responde `202` com `{"job_id": "..."}`;
`GET /documents/jobs/{job_id}` devolve `{"estado": "processando|pronto|erro", "documento_id": "..."}`.

### `GET /documents/{id}/file`

Bytes do PDF, `Content-Type: application/pdf`.

---

## Financeiro

### `GET /billing`

```json
{
  "situacao": "em_dia",
  "assinaturas": [
    { "id": 1, "produto": "meuwatt", "valor_mensal": 1200.00, "dia_vencimento": 5,
      "competencia_atual": { "id": 55, "competencia": "2026-08", "situacao": "a_vencer",
                             "vencimento": "2026-09-05", "valor": 1200.00 } }
  ],
  "historico": [
    { "id": 54, "produto": "meuwatt", "competencia": "2026-07", "valor": 1200.00,
      "vencimento": "2026-08-05", "pago_em": "2026-08-04", "situacao": "pago" }
  ]
}
```

`situacao` da fatura: `pago` · `a_vencer` · `em_aberto` · `vencido`.

### `GET /billing/invoices/{id}`

Detalhe, com `comprovante_url` quando houver.

---

## Assistente

### `POST /assistant/chat`

```json
{ "mensagem": "Quando foi a última manutenção do inversor 3?", "plant_id": 3 }
```

Responde `{"run_id": "..."}`. A execução é assíncrona no meuPlano.

### `GET /assistant/runs/{run_id}`

```json
{ "estado": "processando|pronto|erro",
  "etapa": "consultando as usinas…",
  "resposta": "...",
  "credenciais": [ { "nome": "Portal CPFL", "usuario": "solar@...", "acesso_id": 92 } ] }
```

Credencial nunca vem com o valor. Revelar exige chamada explícita.

### `POST /assistant/reveal`

```json
{ "acesso_id": 92 }
```

Devolve o valor e registra em `AccessRevealLog` no meuPlano. `403` se o nível do usuário
não alcança o nível do acesso.

---

## Notificações

### `GET /notifications?grupo=&nao_lidas=`

### `GET /notifications/unread-count`

### `POST /notifications/{id}/read` · `POST /notifications/read-all`

### `POST /me/push-token`

```json
{ "token": "ExponentPushToken[...]" }
```

---

## Painel do gestor — conexões

> Base **`/api/painel`**, não `/api/v1`: é o time interno, com sessão própria e curta
> (`gs_painel_sessao_horas`). Tudo aqui exige perfil de administrador.

A ponte com cada produto se estabelece por **token pessoal**: alguém gera um token na
própria conta do meuWatt/meuPlano e cola no painel. Formato e motivos em
[`DECISAO_IDENTIDADE.md`](DECISAO_IDENTIDADE.md) § 2b.

### `GET /integracoes`

Uma linha por produto, configurada ou não.

```json
[
  { "produto": "meuwatt", "configurada": true, "base_url": "https://api.meuwatt.com.br",
    "estado": "ok", "detalhe": "Conectado como Fulano da Silva. 12 usina(s) visíveis.",
    "testada_em": "2026-08-13T12:50:00Z", "usinas_visiveis": 12,
    "por_token": true, "token_prefixo": "mw_pat_kOdt",
    "token_dono_nome": "Fulano da Silva", "token_dono_email": "fulano@meuwatt.com.br",
    "token_gravado_em": "2026-08-13T12:49:00Z", "usuario_servico": null }
]
```

`estado`: `nunca` · `ok` · `falhou`. `por_token: false` = conexão antiga, ainda por conta de
serviço com senha — a tela mostra o aviso de migração em cima dela.

### `PUT /integracoes/{produto}/token`

```json
{ "base_url": "https://api.meuwatt.com.br", "token": "mw_pat_…" }
```

Valida o formato (local), identifica o dono e conta as usinas — **só grava se as três
passarem**. Responde com o resultado do teste, não com a integração: o que interessa neste
instante é se funcionou e como quem.

```json
{ "ok": true, "detalhe": "Conectado como Fulano da Silva. 12 usina(s) visíveis.",
  "usinas_visiveis": 12, "dono_nome": "Fulano da Silva",
  "dono_email": "fulano@meuwatt.com.br" }
```

Quando `ok: false`, **nada foi gravado** e a conexão anterior continua de pé. O `detalhe`
distingue os casos, porque cada um pede uma correção diferente: token do produto errado,
cópia truncada, token revogado ou expirado (a frase vem do próprio produto), endereço
errado, servidor fora, e "aceito mas não enxerga usina nenhuma".

### `POST /integracoes/{produto}/testar`

Mesmo corpo de resposta. Exercita a credencial gravada.

### `DELETE /integracoes/{produto}/token`

Para de usar o token deste lado e devolve a integração limpa. **Não revoga** nada no
produto de origem — só quem emitiu pode, e é lá que a porta se fecha de verdade.

### `GET /integracoes/{produto}/eventos`

Histórico da ponte, mais recente primeiro. Responde "desde quando parou?", que o estado
atual sozinho não responde.

```json
[ { "evento": "teste_falhou", "ocorrido_em": "2026-08-13T13:02:00Z",
    "ator_email": "admin@gestaosolar.local", "token_prefixo": "mw_pat_kOdt",
    "detalhe": "Token revogado. Emita um novo no meuWatt.", "usinas_visiveis": null } ]
```

`evento`: `token_gravado` · `token_removido` · `teste_ok` · `teste_falhou` ·
`senha_gravada`. O valor do token nunca aparece — só o prefixo.

---

## Os tokens, do lado de cada produto

Rotas dos produtos, não do BFF. Documentadas aqui porque é o painel que manda o gestor
até elas.

| | meuWatt | meuPlano |
|---|---|---|
| Emitir | `POST /auth/tokens` | `POST /api/v1/meuacesso/auth/tokens` |
| Listar | `GET /auth/tokens` | `GET /api/v1/meuacesso/auth/tokens` |
| Revogar | `DELETE /auth/tokens/{id}` | `DELETE /api/v1/meuacesso/auth/tokens/{id}` |
| Corpo da emissão | `{"name": "...", "expires_in_days": 365}` | `{"nome": "...", "validade_dias": 365}` |

`expires_in_days` / `validade_dias` nulo = sem prazo, que é o certo para integração de
servidor. A emissão devolve o valor em claro **uma única vez**; listar nunca o devolve.
Emitir e revogar exigem sessão — um token não gerencia tokens.
