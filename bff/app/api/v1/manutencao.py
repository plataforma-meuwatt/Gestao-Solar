"""Manutenção — o histórico de ordens de serviço atendidas, vindo do meuPlano.

Esta aba responde uma pergunta que nenhuma outra tela respondia: **o que já foi
feito nas minhas usinas**. As telas existentes olham para a frente (o que está em
aberto, o que está agendado); o dono também precisa olhar para trás, para saber
se o contrato de O&M está sendo cumprido.

Duas decisões que moldam o resultado:

**"Atendida" é `closed_at` preenchido, não status textual.** O status é livre no
meuPlano e varia entre instalações; a data de fechamento é um fato. O predicado
de abertura é **importado** de `notifications`, e não recopiado, porque uma OS
contada como aberta numa tela e fechada na outra é o tipo de divergência que
destrói a confiança nas duas.

**A ordenação é por `closed_at` decrescente.** Histórico se lê do mais recente
para o mais antigo, e o meuPlano não garante ordem nenhuma na lista que devolve.
"""

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.plants import _instante_medida, usinas_do_usuario
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.plant import PlantLink
from app.models.user import User
from app.services import integracoes

router = APIRouter(prefix="/api/v1", tags=["app · manutenção"])


class OrdemAtendidaOut(BaseModel):
    id: int | None = None
    usina: str
    #: O que o serviço era. `objetivo` no meuPlano — o número da OS não diz nada a
    #: quem é dono da usina e não trabalha no sistema de manutenção.
    objetivo: str
    #: PREVENTIVA, CORRETIVA… do próprio meuPlano, sem reinterpretação.
    classificacao: str | None = None
    status: str | None = None

    fechada_em: datetime | None = None
    aprovada_em: datetime | None = None
    tecnico: str | None = None
    #: Minutos de execução, quando o meuPlano souber. A tela formata.
    execucao_min: int | None = None
    tarefas: int | None = None
    tarefas_feitas: int | None = None
    resumo: str | None = None


class ManutencaoOut(BaseModel):
    #: Nulo = nenhuma usina respondeu. Zero é "nenhuma OS atendida", que é diferente.
    total: int | None = None
    ordens: list[OrdemAtendidaOut] = []
    #: Quantas usinas do escopo têm vínculo com o meuPlano. Sem nenhuma, a aba explica
    #: por que está vazia em vez de parecer quebrada.
    usinas_com_manutencao: int = 0
    aviso: str | None = None


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    limpo = str(valor).strip()
    return limpo or None


def _inteiro(valor: Any) -> int | None:
    if isinstance(valor, bool) or valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _atendida(o: dict[str, Any]) -> bool:
    """OS efetivamente concluída.

    Importa o predicado de abertura em vez de inventar o inverso: assim as duas
    telas não podem discordar sobre a mesma ordem.
    """
    from app.api.v1.notifications import _esta_aberta  # noqa: PLC0415

    return not _esta_aberta(o)


@router.get("/manutencao", response_model=ManutencaoOut)
async def manutencao_atendida(
    limite: int = 50,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> ManutencaoOut:
    """Histórico de ordens de serviço atendidas nas usinas desta pessoa."""
    usinas = usinas_do_usuario(db, usuario)
    com_manutencao = [u for u in usinas if u.mp_usina_id]
    saida = ManutencaoOut(usinas_com_manutencao=len(com_manutencao))

    if not usinas:
        saida.aviso = "Você ainda não tem usina liberada."
        return saida
    if not com_manutencao:
        saida.aviso = "Nenhuma das suas usinas está ligada ao meuPlano."
        return saida

    try:
        cliente = await integracoes.cliente_meuplano(db)
    except Exception as exc:  # noqa: BLE001
        saida.aviso = f"meuPlano indisponível: {exc}"
        return saida

    # Uma chamada por usina, em paralelo: em série, sete usinas seriam sete latências
    # somadas numa tela que abre a frio.
    respostas = await asyncio.gather(
        *[cliente.ordens_servico(u.mp_usina_id) for u in com_manutencao],
        return_exceptions=True,
    )

    ordens: list[OrdemAtendidaOut] = []
    falharam: list[str] = []
    for link, resposta in zip(com_manutencao, respostas, strict=True):
        if not isinstance(resposta, list):
            # Uma usina fora do ar não derruba as outras — a tela mostra o que deu para
            # buscar e diz o que faltou.
            falharam.append(link.nome)
            continue
        for o in resposta:
            if not isinstance(o, dict) or not _atendida(o):
                continue
            ordens.append(_para_saida(o, link))

    # Mais recente primeiro. OS sem data de fechamento vai para o FIM, e não para o
    # topo: `datetime.min` a trataria como antiquíssima e `datetime.max` como
    # recentíssima — as duas mentem. A chave booleana a separa antes de comparar datas.
    datadas = sorted(
        (x for x in ordens if x.fechada_em is not None),
        key=lambda x: x.fechada_em,  # type: ignore[arg-type,return-value]
        reverse=True,
    )
    ordens = [*datadas, *(x for x in ordens if x.fechada_em is None)]

    saida.total = len(ordens)
    saida.ordens = ordens[: max(1, min(limite, 200))]

    if falharam:
        saida.aviso = f"Não deu para consultar: {', '.join(falharam)}."
    elif not ordens:
        saida.aviso = "Nenhuma ordem de serviço concluída até agora."
    return saida


def _para_saida(o: dict[str, Any], link: PlantLink) -> OrdemAtendidaOut:
    return OrdemAtendidaOut(
        id=_inteiro(o.get("id")),
        usina=link.nome,
        # O que descreve o serviço, na ordem em que o meuPlano costuma preencher.
        #
        # `objetivo` é o campo canônico, e nas OSs reais destas usinas ele vem VAZIO —
        # quem carrega a descrição é `name` ("Termografia", "Testes TC e TP") ou o
        # título do container ("Investigar reinício dos relés"). Parando no `objetivo`,
        # o histórico inteiro sairia como "OS 969", "OS 975", "OS 1005": números que
        # não dizem nada a quem é dono da usina e não trabalha no meuPlano.
        #
        # (A aba Notificações lê só `objetivo` e tem o mesmo buraco — fica anotado.)
        objetivo=(
            _texto(o.get("objetivo"))
            or _texto(o.get("name"))
            or _texto(o.get("container_title"))
            or f"OS {o.get('id')}"
        ),
        classificacao=_texto(o.get("classification")),
        status=_texto(o.get("status")),
        fechada_em=_instante_medida(o.get("closed_at")),
        aprovada_em=_instante_medida(o.get("approved_at")),
        tecnico=_texto(o.get("technician_name") or o.get("technician_label")),
        execucao_min=_inteiro(o.get("execution_minutes") or o.get("total_minutes")),
        tarefas=_inteiro(o.get("task_count")),
        tarefas_feitas=_inteiro(o.get("task_realized_count")),
        resumo=_texto(o.get("resumo") or o.get("conclusao_tecnico") or o.get("notes")),
    )
