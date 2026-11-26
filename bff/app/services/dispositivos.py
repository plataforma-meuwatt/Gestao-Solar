"""O índice de dispositivos (o plano do guarda-chuva, fase 2, 26/11/2026): o índice de usinas um andar abaixo. O GS dá
um número a cada POSIÇÃO de equipamento da usina (o lugar: "transformador 1", "inversor da posição 3"; não o aparelho,
que pode ser trocado), e cada sistema guarda esse número ao lado do registro dele.

Nesta fase entram os transformadores e os inversores, vindos do meuWatt. Quem manda é o servidor do sistema, pela porta
da máquina (`api/v1/interno_dispositivos.py`), sempre com a lista INTEIRA da usina:

- a referência que o GS não conhece ganha um número; a conhecida tem o nome, o tipo e o pai atualizados;
- a que não veio NÃO é apagada: fica ausente (`ativo` falso, `ausente_desde`), e volta quando vier de novo;
- a referência que já é de OUTRA usina recusa o pedido inteiro (um dispositivo não muda de usina calado).

A grafia da referência do meuWatt é a que as rotas do mapa já usam (`interno_mapa_itens`): `trafo:<transformers.id>`,
`inv:<inverter_slots.id>` (depois `str:<slot_id>:<n>`, `rele:<relay_id>`). É A grafia padrão.
"""
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.plant import DeviceLink, PlantLink

#: os tipos que o índice conhece. Hoje entram os dois primeiros; os outros estão reservados (fases seguintes)
TIPOS = ("transformador", "inversor", "string", "rele", "estacao", "medidor", "stringbox", "gateway")
#: a coluna do dispositivo que guarda a referência dele em cada sistema
REFERENCIA = {"meuwatt": "mw_ref", "meuplano": "mp_node_id", "termovision": "tv_ref"}
#: a grafia aceita de cada sistema nesta fase: o prefixo da referência e o tipo que ele diz. Sistema fora daqui ainda
#: não manda dispositivos
GRAFIA = {"meuwatt": {"trafo": "transformador", "inv": "inversor"}}
#: o teto da lista de uma usina
TETO = 5000


class ListaInvalida(ValueError):
    """A lista não serve (422): a frase vai a quem mandou."""


class DeOutraUsina(ValueError):
    """Uma referência da lista já é de outra usina do GS (409)."""


def conferir(quem: str, itens: list[dict]) -> None:
    """A lista inteira antes de gravar: a grafia da referência, o tipo que ela diz, sem repetida, e o pai na própria
    lista."""
    grafia = GRAFIA[quem]
    padrao = re.compile(rf"({'|'.join(grafia)}):\d+")
    refs = set()
    for d in itens:
        ref = d["ref"]
        achado = padrao.fullmatch(ref)
        if achado is None:
            raise ListaInvalida(f"A referência {ref!r} não serve: use " + " ou ".join(f"{p}:<número>" for p in grafia)
                                + ".")
        if d["tipo"] != grafia[achado.group(1)]:
            raise ListaInvalida(f"A referência {ref} é de {grafia[achado.group(1)]}, e veio como {d['tipo']!r}.")
        if ref in refs:
            raise ListaInvalida(f"A referência {ref} veio mais de uma vez.")
        refs.add(ref)
    for d in itens:
        if d["pai"] is not None and (d["pai"] not in refs or d["pai"] == d["ref"]):
            raise ListaInvalida(f"O pai de {d['ref']} ({d['pai']}) tem de ser outro dispositivo da mesma lista.")


def da_usina(db: Session, quem: str, usina: PlantLink) -> list[DeviceLink]:
    """Os dispositivos da usina que têm referência do sistema `quem`, também os ausentes."""
    coluna = getattr(DeviceLink, REFERENCIA[quem])
    return list(db.scalars(select(DeviceLink).where(DeviceLink.plant_link_id == usina.id, coluna.isnot(None))
                           .order_by(DeviceLink.id)).all())


def gravar(db: Session, quem: str, usina: PlantLink, itens: list[dict]) -> dict:
    """Aplica a lista inteira dos dispositivos da usina no sistema `quem` (já conferida). Devolve quantos nasceram,
    quantos mudaram e quantos ficaram ausentes NESTE pedido. Não confirma: quem chama dá o commit."""
    campo = REFERENCIA[quem]
    coluna = getattr(DeviceLink, campo)
    refs = [d["ref"] for d in itens]
    de_outra = sorted(db.scalars(select(coluna).where(coluna.in_(refs), DeviceLink.plant_link_id != usina.id)).all()
                      ) if refs else []
    if de_outra:
        raise DeOutraUsina("Já em outra usina do GS: " + ", ".join(map(str, de_outra))
                           + ". Um dispositivo não muda de usina sozinho: nada foi gravado.")
    agora = datetime.now(UTC)
    daqui = {getattr(x, campo): x for x in da_usina(db, quem, usina)}
    nascidos, mudados = set(), set()
    for d in itens:
        linha = daqui.get(d["ref"])
        if linha is None:
            linha = DeviceLink(plant_link_id=usina.id, tipo=d["tipo"], nome=d["nome"], ativo=True, criado_em=agora,
                               atualizado_em=agora, **{campo: d["ref"]})
            db.add(linha)
            daqui[d["ref"]] = linha
            nascidos.add(d["ref"])
            continue
        if (linha.tipo, linha.nome) != (d["tipo"], d["nome"]):
            linha.tipo, linha.nome = d["tipo"], d["nome"]
            mudados.add(d["ref"])
        if not linha.ativo:                                # voltou
            linha.ativo, linha.ausente_desde = True, None
            mudados.add(d["ref"])
    db.flush()                                             # os novos ganham número: o pai é o número do GS
    for d in itens:
        linha = daqui[d["ref"]]
        pai = daqui[d["pai"]].id if d["pai"] is not None else None
        if linha.pai_id != pai:
            linha.pai_id = pai
            if d["ref"] not in nascidos:                   # o que nasceu agora não conta como mudado
                mudados.add(d["ref"])
    vieram, ausentes = set(refs), 0
    for ref, linha in daqui.items():
        if ref in vieram:
            if ref in mudados:
                linha.atualizado_em = agora
        elif linha.ativo:                                  # não veio: fica, ausente (a data é a da 1ª vez)
            linha.ativo, linha.ausente_desde, linha.atualizado_em = False, linha.ausente_desde or agora, agora
            ausentes += 1
    db.flush()
    return {"criados": len(nascidos), "alterados": len(mudados), "ausentes": ausentes}
