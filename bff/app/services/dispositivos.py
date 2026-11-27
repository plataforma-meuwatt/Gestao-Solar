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

O meuPlano não cria dispositivo (fase 3, 1ª fatia, 27/11/2026): ele diz "o meu nó N é a posição que vocês conhecem como
`inv:99`" e o GS guarda o nó naquela linha (`ligar_nos`). Os pares vêm já casados por uma pessoa na tela do meuPlano,
por isso não há fila de confirmação aqui.

- um nó é UMA posição: o nó que já está em outro dispositivo recusa o pedido inteiro, a não ser que o mesmo pedido tire
  aquele dispositivo do nó (a troca);
- o dispositivo que NÃO veio no pedido fica como está (não vir não é desligar: o vínculo é com a posição e atravessa a
  troca do aparelho no meuPlano). Desligar é mandar o nó nulo;
- a referência que o GS não conhece nesta usina não é erro: volta em `sem_dispositivo`.
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
PADRAO = {"trafo": "transformador", "inv": "inversor"}
#: a STRING (fase 4, 27/11/2026) também é uma POSIÇÃO: a do inversor mais o número da entrada CC em que ela está
#: ligada (`str:<inverter_slots.id>:<n>`; o número tem buracos, não é a ordem numa lista). O pai é o inversor dela
#: (`inv:<o mesmo slot>`), na mesma lista. O nó do meuPlano de cada string é ligado pela rotina do meuPlano, que conhece a
#: árvore dele (`ligar_nos`, também com `str:`); a pessoa só casa transformadores e inversores (`PADRAO`).
GRAFIA = {"meuwatt": {**PADRAO, "str": "string"}}
#: o que vem depois do prefixo: um número só, a não ser na string (a vaga e a entrada)
_NUMERO = r"\d+"
_CORPO = {"str": r"\d+:\d+"}
#: como se escreve cada referência, para a frase da recusa
_EXEMPLO = {"str": "str:<vaga do inversor>:<número da entrada>"}
#: quem liga os nós dele aos dispositivos que já existem (não cria dispositivo)
LIGA_NOS = ("meuplano",)
#: o teto da lista de uma usina
TETO = 5000


class ListaInvalida(ValueError):
    """A lista não serve (422): a frase vai a quem mandou."""


class DeOutraUsina(ValueError):
    """Uma referência da lista já é de outra usina do GS (409)."""


class NoDeOutro(ValueError):
    """O nó do pedido já está em outro dispositivo, que o pedido não tira de lá (409)."""

    def __init__(self, no: int, gd: int):
        super().__init__(f"nó {no} no dispositivo {gd}")
        self.no, self.gd = no, gd


def _padrao(grafia: dict[str, str]) -> re.Pattern:
    """A referência de qualquer um dos prefixos de `grafia`; o grupo que casou diz qual (`lastgroup`)."""
    return re.compile("|".join(f"(?P<{p}>{p}:{_CORPO.get(p, _NUMERO)})" for p in grafia))


def conferir(quem: str, itens: list[dict]) -> None:
    """A lista inteira antes de gravar: a grafia da referência, o tipo que ela diz, sem repetida, e o pai na própria
    lista. A string tem de ter por pai o inversor DELA (`str:111:7` debaixo de `inv:111`)."""
    grafia = GRAFIA[quem]
    padrao = _padrao(grafia)
    refs = set()
    for d in itens:
        ref = d["ref"]
        achado = padrao.fullmatch(ref)
        if achado is None:
            raise ListaInvalida(f"A referência {ref!r} não serve: use "
                                + " ou ".join(_EXEMPLO.get(p, f"{p}:<número>") for p in grafia) + ".")
        if d["tipo"] != grafia[achado.lastgroup]:
            raise ListaInvalida(f"A referência {ref} é de {grafia[achado.lastgroup]}, e veio como {d['tipo']!r}.")
        if ref in refs:
            raise ListaInvalida(f"A referência {ref} veio mais de uma vez.")
        refs.add(ref)
    for d in itens:
        if d["pai"] is not None and (d["pai"] not in refs or d["pai"] == d["ref"]):
            raise ListaInvalida(f"O pai de {d['ref']} ({d['pai']}) tem de ser outro dispositivo da mesma lista.")
        if d["tipo"] == "string":                          # a string é a entrada DAQUELE inversor
            dele = "inv:" + d["ref"].split(":")[1]
            if d["pai"] != dele:
                raise ListaInvalida(f"O pai da string {d['ref']} tem de ser o inversor dela ({dele}), na mesma lista.")


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


def todos_da_usina(db: Session, usina: PlantLink) -> list[DeviceLink]:
    """Todos os dispositivos da usina, de qualquer sistema, também os ausentes."""
    return list(db.scalars(select(DeviceLink).where(DeviceLink.plant_link_id == usina.id).order_by(DeviceLink.id)).all())


def conferir_nos(itens: list[dict]) -> None:
    """Os pares (referência, nó) antes de gravar: a grafia padrão (também a da string), sem referência repetida e
    sem nó repetido."""
    grafia = GRAFIA["meuwatt"]
    padrao = _padrao(grafia)
    refs, nos = set(), set()
    for d in itens:
        ref, no = d["ref"], d["node_id"]
        if padrao.fullmatch(ref) is None:
            raise ListaInvalida(f"A referência {ref!r} não serve: use "
                                + " ou ".join(_EXEMPLO.get(p, f"{p}:<número>") for p in grafia) + ".")
        if ref in refs:
            raise ListaInvalida(f"A referência {ref} veio mais de uma vez.")
        if no is not None and no in nos:
            raise ListaInvalida(f"O nó {no} veio mais de uma vez: um nó é uma posição só.")
        refs.add(ref)
        nos.add(no)


def ligar_nos(db: Session, usina: PlantLink, itens: list[dict]) -> dict:
    """Guarda o nó do meuPlano nos dispositivos da usina que o pedido nomeia pela referência padrão (já conferido). Só
    mexe no que veio. Devolve quantos ganharam (ou trocaram de) nó e quantos perderam NESTE pedido, e as referências
    que não são de dispositivo desta usina. Não confirma: quem chama dá o commit."""
    por_ref = {x.mw_ref: x for x in todos_da_usina(db, usina) if x.mw_ref}
    sem = [d["ref"] for d in itens if d["ref"] not in por_ref]
    feito = aplicar_nos(db, {por_ref[d["ref"]]: d["node_id"] for d in itens if d["ref"] in por_ref})
    return {**feito, "sem_dispositivo": sem}


def aplicar_nos(db: Session, pedido: dict[DeviceLink, int | None]) -> dict:
    """O nó de cada dispositivo do `pedido` (nulo desliga), com a regra de sempre: um nó é uma posição só, e a troca
    cabe num pedido. É a mesma para a porta da máquina (`ligar_nos`) e para a pessoa no oem-gs. Não confirma."""
    mudam = {linha: no for linha, no in pedido.items() if linha.mp_node_id != no}
    nos = [no for no in mudam.values() if no is not None]
    if nos:                                                # um nó é uma posição: quem o tem hoje sai dele NESTE pedido?
        for dono in db.scalars(select(DeviceLink).where(DeviceLink.mp_node_id.in_(nos)).order_by(DeviceLink.id)).all():
            if dono not in mudam:
                raise NoDeOutro(dono.mp_node_id, dono.id)
    agora = datetime.now(UTC)
    desligados = sum(1 for no in mudam.values() if no is None)
    for linha in mudam:                                    # primeiro todos soltam o nó (a troca não esbarra na trava)
        linha.mp_node_id, linha.atualizado_em = None, agora
    db.flush()
    for linha, no in mudam.items():
        linha.mp_node_id = no
    db.flush()
    return {"ligados": len(nos), "desligados": desligados}
