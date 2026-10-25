"""Log do bot: a linha 59 diz "Respondeu", e o pedido parou no meio; a promessa sai da conversa.

Em 24/10/2026 18:13, depois do Sim que concluiu a ficha da OS 1638, o meuPlano mandou o próximo
passo em TEXTO ("Confirmando os dois, eu fecho a 1638 e registro a 1843"), sem nada para confirmar:
o bot repassou a promessa, nada ficou esperando o Sim e a 1638 não foi fechada (avaliação 19). O log
marcou "Respondeu" (avaliação 20). A resposta fica como foi mandada (é o registro do que a pessoa
leu); o resultado e o erro passam a dizer o que aconteceu.

E a conversa guardada — o que a IA lê a cada turno — ainda tinha a promessa: um "confirmo os dois"
seria lido como resposta a algo que nunca esperou confirmação. A fala vira a nota do que houve.
Só a linha e a fala com aquele texto: num banco sem elas, nada muda.

Revisão: f5a7c9e1b3d4
Anterior: e4f6a8c0b2d3
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "f5a7c9e1b3d4"
down_revision = "e4f6a8c0b2d3"
branch_labels = None
depends_on = None

PROMESSA = "Confirmando os dois, eu fecho a 1638 e registro a 1843"
ERRO = ("O meuPlano mandou o próximo passo em texto («Confirmando os dois, eu fecho a 1638 e registro a 1843»), "
        "sem nada para confirmar: o pedido parou no meio e a OS 1638 não foi fechada. Hoje o bot pede o passo de "
        "novo ao meuPlano e, se ele não vier, avisa a pessoa e marca erro aqui.")
NOTA = ("(Correção do sistema: aqui eu repassei em texto dois passos que o meuPlano descreveu — fechar a OS 1638 "
        "e concluir a tarefa 9330 da OS 1843 com os dias 23 e 24/10 do Michel —, mas nada ficou esperando o Sim: "
        "nenhum dos dois foi feito. Para fazer, a pessoa pede de novo.) Perguntei também se ela quer uma pendência "
        "na UFV Ibitinga para o acabamento com roçadeira costal e veneno.")


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE gs_bot_registros SET resultado = 'erro', erro = :erro WHERE id = 59 AND ferramentas = 'confirmacao' "
        "AND resultado = 'respondeu' AND resposta LIKE :promessa"), {"erro": ERRO, "promessa": f"%{PROMESSA}%"})
    conversas = bind.execute(sa.text("SELECT id, mensagens FROM gs_whatsapp_conversas WHERE mensagens LIKE :p"),
                             {"p": f"%{PROMESSA}%"}).all()
    for cid, mensagens in conversas:
        turnos = json.loads(mensagens)
        for t in turnos:
            if PROMESSA in (t.get("content") or ""):     # só a fala do bot a tem (conferido no banco)
                t["content"] = NOTA
        bind.execute(sa.text("UPDATE gs_whatsapp_conversas SET mensagens = :m WHERE id = :id"),
                     {"m": json.dumps(turnos, ensure_ascii=False), "id": cid})


def downgrade() -> None:
    # Sem volta: o "Respondeu" e a promessa eram os falsos.
    pass
