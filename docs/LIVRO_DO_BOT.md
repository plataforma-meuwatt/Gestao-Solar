# Livro de aprendizado do bot

O que o dono ensinou ao bot do Gestão Solar, com o caso que ensinou. A lição vale acima do palpite do bot: o
diagnóstico (`bff/app/services/diagnostico.py`) a aplica e cita o número no aviso, e um teste reprova o código que a
esquecer.

Lição nova: as palavras do dono como ele disse, o caso, o que o bot faz agora, a regra e o teste. Número novo no fim;
lição que muda ganha a data da mudança, não um número novo.

## Lição 1 · Dois DJ BT não desligam juntos de manhã (24/11/2026)

> "Dois DJ BT diferentes desligados juntos logo de manhã. Isso é praticamente impossível. Se não ver trip, mas também
> não tiver comunicação, é bem provável que seja trip." (Renan)

**O caso.** Pereiras, 24/11 07:07: dois avisos "inversores não ligaram … sem trip no relé do skid: falta de tensão no
AC do inversor (disjuntor de BT aberto)", um do TR-01 e outro do TR-02. Os relés do TR-01 (UFV 01 e Geral) estavam sem
comunicação desde 23/11 14:42, então o "sem trip" era só não ver. E não foi trip nem DJ BT: o relé do TR-02 mediu a
média tensão normal a noite toda (8,1 kV, 60 Hz), e 8 dos 12 inversores ligaram entre 05:20 e 05:25. O INV16 ligou às
05:45 e caiu das 06:05 às 06:45; o INV11, o INV15 e o INV21 só ligaram entre 06:35 e 06:50. A matriz do meuWatt deu R6
("para avaliar") e R1/R3 (falha de leitura), nenhuma parada.

**O que o bot faz.**
- Relé do skid sem comunicação, com a comunicação não conferida, com o histórico de trips que não veio, ou skid sem
  relé no meuWatt: nunca diz "sem trip". Diz qual relé está mudo, desde quando, e que o trip não aparece.
- O skid inteiro parado e sem como ver trip: o provável é trip.
- Dois ou mais skids inteiros que começaram a parar juntos (até 15 min): uma causa comum, num aviso só. Com algum relé
  mudo, o provável é trip; com os relés lendo sem trip, a rede ou a proteção geral. Nunca o DJ BT de cada skid.
- Os outros inversores do mesmo skid gerando: havia tensão no skid, então não é trip nem DJ BT. É o inversor
  (isolação baixa de manhã, falha).
- DJ BT aberto só quando o skid inteiro parou e o relé dele está lendo, sem trip.

**Regra:** `diagnostico.py`, regra 2 (`_sem_trip`; a frota de cada skid vem do detector, `fleet_by_transformer`).
**Teste:** `bff/tests/test_diagnostico.py::test_livro_1_dois_dj_bt_nao_desligam_juntos`.
