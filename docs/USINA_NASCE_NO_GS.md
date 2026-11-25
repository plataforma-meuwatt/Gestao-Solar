# Usina, proprietária e pessoas nascem no GS

O dono (25/11/2026): "usina nasce no GS, empresa proprietária e usuários no GS, aí cada sistema faz seu rolê. Posso
até criar em outras plataformas, mas automaticamente ela será criada no GS."

A regra: o GS é o cadastro mestre (`gs_plant_links`, `gs_proprietarias`, `gs_users`). Criar no GS cria nos
sistemas; criar num sistema registra no GS (a parecida espera o gerente em oem-gs › Usinas › A confirmar).

## Onde estamos (conferido no código em 25/11/2026)

| Fluxo | Usina | Proprietária | Pessoa |
|---|---|---|---|
| GS → sistemas | ❌ não há "Nova usina" no GS | ❌ o GS só IMPORTA do meuPlano | ✅ cadastro pelo bot cria no meuPlano e no meuWatt e liga os tokens |
| meuPlano → GS | ⚠️ só a sessão aberta PELO GS registra (`gs_interno.registrar_usina_nova`) | ✅ importação (`proprietarias.importar_do_meuplano`) | — |
| TermoVision → GS | ✅ "Enviar ao GS" | — | — |
| meuWatt → GS | ❌ o mw-api não chama `POST /interno/usinas` | ❌ `mw_enterprise_id` vazio nas proprietárias | — |

## Fases

1. ✅ (25/11/2026: `POST /api/empresa/usinas/nova`, botão "Nova usina" no cartão da proprietária, em oem-gs ›
   Proprietárias; parecida = 409 com a lista, "É outra: criar mesmo assim"). **Nova usina no GS**: nome, proprietária, endereço, cidade, UF, coordenada e kWp → nasce em
   `gs_plant_links` e, com o token da EMPRESA, no meuPlano (`POST /meuacesso/usinas/` com `owner_id` = o
   `mp_owner_id` da proprietária); o `mp_usina_id` volta e fica gravado. O meuWatt entra quando a usina ganha
   coletor (lá a usina sem coletor não tem o que medir): o GS mostra "falta no meuWatt" até lá.
2. **Proprietária nova no GS** cria a organização PROPRIETARIA no meuPlano e grava o `mp_owner_id`.
3. **meuPlano → GS sempre**: registrar a usina nova também fora da sessão do GS (com a chave do sistema e a empresa
   da usina).
4. **meuWatt → GS**: o mw-api chama `POST /interno/usinas` ao criar a usina (precisa do OK do Renan para a main).
5. **Conciliação diária**: usina, proprietária ou pessoa que existe num sistema e não no GS vira pendência em
   oem-gs (nunca some calada).

## Eldorado Energia (proprietária 2), em 25/11/2026

Usinas: Ouro Fino, Pereiras, Pirapozinho, Tietê (as quatro no meuWatt e no meuPlano), Porto Feliz e Mairinque (só
meuPlano). Pessoas: fernando.labes e luiz.grossi, que recebem as seis no GS (`proprietarias.dar_usinas`).
