"""O motor de notificações: o que aconteceu, quem quer saber, e o envio.

Três perguntas, nesta ordem, e cada uma mora num lugar:

1. **O que aconteceu** — os coletores deste arquivo, um por tipo do catálogo. Eles leem
   os upstreams e devolvem eventos com uma CHAVE estável.
2. **Quem quer saber** — `services/notificacoes.destinatarios`, que aplica preferência do
   cliente, escopo de usina e aptidão (ativo, telefone, aceite). O motor não reimplementa
   nada disso: a tela da central mostra exatamente o que esta função responde.
3. **O envio** — um template aprovado por tipo, pelo gateway.

**A chave é o que impede repetir.** Ela descreve o EVENTO, não a execução: rodar o motor
de dez em dez minutos não manda dez vezes o mesmo aviso, porque a linha em
`gs_notificacoes_enviadas` (único por `user_id + chave`) já existe. E ela carrega o que
torna o evento novo — a parada do mesmo inversor DEPOIS de ele voltar tem `down_since`
diferente, então é evento novo e avisa de novo. É a diferença entre silenciar repetição e
silenciar o assunto.

**Toda tentativa vira linha, inclusive a que falhou.** O log existe para responder "por que
o cliente não recebeu", e uma tabela que só guarda sucesso não responde isso. Falha grava
`falhou` com a frase da Meta; a trava de repetição continua valendo, para um erro
permanente (número bloqueado, template pausado) não virar mil tentativas.

**Fora da janela de 24 h só sai template.** Todo aviso daqui é a empresa começando a
conversa, então é sempre template — nunca texto livre. Ver `TEMPLATE_POR_TIPO`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import whatsapp as gateway
from app.core.datas import hoje as hoje_na_usina
from app.models.integracao import Produto
from app.models.notificacao import NotificacaoEnviada
from app.models.plant import PlantLink
from app.models.user import User
from app.services import avisos as svc_avisos
from app.services import notificacoes as catalogo
from app.services import vinculos

log = logging.getLogger("gs.motor")

#: O modelo aprovado na Meta para cada tipo do catálogo.
#:
#: O nome é acordo com a conta da Meta: mudar aqui sem criar lá (ou o contrário) produz
#: recusa no envio, não erro de programa — por isso o diagnóstico confere os dois lados.
TEMPLATE_POR_TIPO: dict[str, str] = {
    "parada": "gs_usina_parada",
    "os_iniciada": "gs_manutencao_iniciada",
    "os_finalizada": "gs_manutencao_concluida",
    "energia_dia": "gs_energia_dia",
    "energia_semana": "gs_energia_semana",
    "energia_mes": "gs_energia_mes",
}


@dataclass(frozen=True)
class Evento:
    """Algo que aconteceu numa usina, pronto para virar mensagem."""

    tipo: str
    plant_link_id: int
    #: Estável e descritiva do evento — não da execução. Entra em `gs_notificacoes_enviadas`.
    chave: str
    #: Os `{{1}}`, `{{2}}`… do template, na ordem.
    parametros: list[str]


@dataclass
class Linha:
    """O que aconteceu com UM destinatário de UM evento."""

    tipo: str
    chave: str
    usuario_id: int
    usuario: str
    usina: str
    situacao: str  # enviada | falhou | repetida | simulada
    detalhe: str | None = None


@dataclass
class Relatorio:
    eventos: int = 0
    enviadas: int = 0
    falhas: int = 0
    repetidas: int = 0
    simuladas: int = 0
    linhas: list[Linha] = field(default_factory=list)
    #: Tipos que não puderam ser coletados, com o motivo. Não é erro do motor: upstream
    #: fora do ar, usina sem vínculo, ninguém com token.
    avisos: list[str] = field(default_factory=list)


# ── formatação ──────────────────────────────────────────────────────────────


def _numero(valor: float) -> str:
    """pt-BR: ponto de milhar, vírgula decimal. O cliente lê a mensagem, não o JSON."""
    return f"{valor:,.1f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _data(d: date) -> str:
    return d.strftime("%d/%m/%Y")


MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def _mes_por_extenso(d: date) -> str:
    return f"{MESES[d.month - 1]} de {d.year}"


# ── leitura dos upstreams ───────────────────────────────────────────────────


def _usinas_com_interesse(db: Session, tipo: str) -> dict[int, PlantLink]:
    """As usinas em que ALGUÉM marcou este tipo — o universo que vale a pena consultar.

    Sem este filtro o motor leria todas as usinas a cada volta para descobrir, no fim, que
    ninguém pediu aviso nenhum. A carga no upstream é do tamanho do interesse real.
    """
    from app.models.notificacao import NotificacaoPreferencia

    ids = set(
        db.scalars(
            select(NotificacaoPreferencia.plant_link_id).where(
                NotificacaoPreferencia.tipo == tipo
            )
        ).all()
    )
    if not ids:
        return {}
    links = db.scalars(
        select(PlantLink).where(PlantLink.id.in_(ids), PlantLink.ativo)
    ).all()
    return {l.id: l for l in links}


def _leitor(db: Session, plant_link_id: int, produto: Produto) -> int | None:
    """Um cliente com acesso à usina E com token do produto — quem empresta a leitura.

    Mesma razão de `services/avisos`: a leitura de uma usina é igual para todo mundo que a
    enxerga, e repeti-la por pessoa multiplicaria a carga no upstream sem trazer dado novo.
    Usina sem ninguém conectado fica de fora, em silêncio — não temos como saber o estado
    dela, e calar é melhor do que inventar.
    """
    from app.models.user import UserPlantAccess

    candidatos = db.scalars(
        select(User)
        .join(UserPlantAccess, UserPlantAccess.user_id == User.id)
        .where(UserPlantAccess.plant_link_id == plant_link_id, User.ativo)
    ).all()
    for pessoa in candidatos:
        if vinculos.obter(db, pessoa.id, produto) is not None:
            return pessoa.id
    return None


# ── coletores ───────────────────────────────────────────────────────────────


async def _coletar_parada(db: Session, rel: Relatorio) -> list[Evento]:
    """Inversor em falha material agora, pela mesma régua das telas (`services/avisos`)."""
    eventos: list[Evento] = []
    for link in _usinas_com_interesse(db, "parada").values():
        if not link.mw_plant_slug:
            continue
        dono = _leitor(db, link.id, Produto.MEUWATT)
        if dono is None:
            rel.avisos.append(f"{link.nome}: ninguém com token do meuWatt para ler.")
            continue
        try:
            cliente = vinculos.cliente_meuwatt(db, dono)
            agora = await cliente.monitoramento_atual(link.mw_plant_slug)
        except Exception as exc:  # noqa: BLE001
            rel.avisos.append(f"{link.nome}: monitoramento indisponível ({exc}).")
            continue

        for inv in svc_avisos._parados(agora):
            equipamento = str(inv.get("id") or "")
            nome = str(inv.get("name") or inv.get("serial_number") or "Inversor")
            desde = inv.get("down_since")
            hora = "—"
            if isinstance(desde, str) and len(desde) >= 16:
                try:
                    hora = datetime.fromisoformat(desde.replace("Z", "+00:00")).strftime("%H:%M")
                except ValueError:
                    hora = "—"
            eventos.append(
                Evento(
                    tipo="parada",
                    plant_link_id=link.id,
                    # `down_since` entra na chave: o mesmo inversor parando OUTRA vez,
                    # depois de voltar, é evento novo e avisa de novo.
                    chave=f"parada:{link.id}:{equipamento}:{desde or ''}",
                    parametros=[link.nome, nome, hora],
                )
            )
    return eventos


async def _coletar_manutencao(db: Session, rel: Relatorio, tipo: str) -> list[Evento]:
    """OS agendada para hoje (`os_iniciada`) ou fechada hoje (`os_finalizada`).

    `closed_at` é o que o meuPlano preenche de fato quando o serviço termina — o `status`
    é texto livre e não serve de gatilho. Para o começo não existe campo equivalente, e
    por isso o gatilho é a data agendada: é o que o sistema sabe, e o texto do modelo diz
    exatamente isso, sem afirmar que o técnico já chegou.
    """
    hoje = hoje_na_usina()
    eventos: list[Evento] = []
    for link in _usinas_com_interesse(db, tipo).values():
        if not link.mp_usina_id:
            continue
        dono = _leitor(db, link.id, Produto.MEUPLANO)
        if dono is None:
            rel.avisos.append(f"{link.nome}: ninguém com token do meuPlano para ler.")
            continue
        try:
            cliente = vinculos.cliente_meuplano(db, dono)
            ordens = await cliente.ordens_servico(link.mp_usina_id)
        except Exception as exc:  # noqa: BLE001
            rel.avisos.append(f"{link.nome}: ordens de serviço indisponíveis ({exc}).")
            continue

        for o in ordens:
            if not isinstance(o, dict):
                continue
            os_id = o.get("id")
            if tipo == "os_iniciada":
                quando = str(o.get("scheduled_date") or "")[:10]
                if quando != hoje.isoformat():
                    continue
                eventos.append(
                    Evento(
                        tipo=tipo,
                        plant_link_id=link.id,
                        chave=f"os_iniciada:{os_id}",
                        parametros=[link.nome, _data(hoje), str(os_id)],
                    )
                )
            else:
                fechada = str(o.get("closed_at") or "")[:10]
                if fechada != hoje.isoformat():
                    continue
                eventos.append(
                    Evento(
                        tipo=tipo,
                        plant_link_id=link.id,
                        chave=f"os_finalizada:{os_id}",
                        parametros=[link.nome, _data(hoje)],
                    )
                )
    return eventos


async def _coletar_energia(db: Session, rel: Relatorio, tipo: str) -> list[Evento]:
    """Resumo de energia de um período FECHADO.

    Período fechado, e não o corrente, por honestidade: "a usina gerou 1.284 kWh hoje"
    enviado às duas da tarde é um número que vai mudar, e o cliente guarda o primeiro.
    O dia só vira aviso quando acabou; a semana, na segunda; o mês, no dia 1º.
    """
    hoje = hoje_na_usina()
    if tipo == "energia_dia":
        inicio = fim = hoje - timedelta(days=1)
        rotulo = _data(inicio)
    elif tipo == "energia_semana":
        if hoje.weekday() != 0:  # só na segunda-feira
            return []
        fim = hoje - timedelta(days=1)
        inicio = fim - timedelta(days=6)
        rotulo = _data(fim)
    else:  # energia_mes
        if hoje.day != 1:
            return []
        fim = hoje - timedelta(days=1)
        inicio = fim.replace(day=1)
        rotulo = _mes_por_extenso(inicio)

    eventos: list[Evento] = []
    for link in _usinas_com_interesse(db, tipo).values():
        if not link.mw_plant_slug:
            continue
        dono = _leitor(db, link.id, Produto.MEUWATT)
        if dono is None:
            rel.avisos.append(f"{link.nome}: ninguém com token do meuWatt para ler.")
            continue
        try:
            cliente = vinculos.cliente_meuwatt(db, dono)
            relatorio = await cliente.geracao_periodo(link.mw_plant_slug, inicio, fim)
        except Exception as exc:  # noqa: BLE001
            rel.avisos.append(f"{link.nome}: geração indisponível ({exc}).")
            continue

        total = relatorio.get("total_generation_kwh") if isinstance(relatorio, dict) else None
        if not isinstance(total, (int, float)):
            # Sem número não há aviso. Mandar "0 kWh" quando não se sabe é o erro que a
            # REGRA 0 reserva para ausência: o dono leria "não gerou".
            rel.avisos.append(f"{link.nome}: sem total de geração no período.")
            continue

        eventos.append(
            Evento(
                tipo=tipo,
                plant_link_id=link.id,
                chave=f"{tipo}:{link.id}:{fim.isoformat()}",
                parametros=[rotulo, link.nome, _numero(float(total))],
            )
        )
    return eventos


COLETORES = {
    "parada": _coletar_parada,
    "os_iniciada": lambda db, rel: _coletar_manutencao(db, rel, "os_iniciada"),
    "os_finalizada": lambda db, rel: _coletar_manutencao(db, rel, "os_finalizada"),
    "energia_dia": lambda db, rel: _coletar_energia(db, rel, "energia_dia"),
    "energia_semana": lambda db, rel: _coletar_energia(db, rel, "energia_semana"),
    "energia_mes": lambda db, rel: _coletar_energia(db, rel, "energia_mes"),
}


# ── envio ───────────────────────────────────────────────────────────────────


async def disparar(
    db: Session, *, tipos: list[str] | None = None, simular: bool = False
) -> Relatorio:
    """Coleta, decide quem recebe e envia. Idempotente por construção.

    `simular=True` percorre tudo e não manda nada — é o que a rota de diagnóstico usa
    para provar o caminho inteiro sem acordar cliente às duas da manhã.
    """
    rel = Relatorio()
    escolhidos = tipos or list(TEMPLATE_POR_TIPO)

    for tipo in escolhidos:
        if tipo not in COLETORES:
            rel.avisos.append(f"Tipo sem coletor: {tipo}.")
            continue
        try:
            eventos = await COLETORES[tipo](db, rel)
        except Exception as exc:  # noqa: BLE001 — um tipo quebrado não derruba os outros
            log.exception("coletor %s falhou", tipo)
            rel.avisos.append(f"Coletor {tipo} falhou: {exc}")
            continue

        rel.eventos += len(eventos)
        for evento in eventos:
            await _entregar(db, evento, rel, simular=simular)

    return rel


async def _entregar(db: Session, evento: Evento, rel: Relatorio, *, simular: bool) -> None:
    usina = db.get(PlantLink, evento.plant_link_id)
    nome_usina = usina.nome if usina else str(evento.plant_link_id)
    template = TEMPLATE_POR_TIPO[evento.tipo]

    for destino in catalogo.destinos(db, evento.tipo, evento.plant_link_id):
        ja = (
            catalogo.ja_enviada(db, destino.id, evento.chave)
            if destino.especie == "cliente"
            else catalogo.ja_enviada_para_contato(db, destino.id, evento.chave)
        )
        if ja:
            rel.repetidas += 1
            rel.linhas.append(
                Linha(evento.tipo, evento.chave, destino.id, destino.nome, nome_usina,
                      "repetida", "já avisado antes")
            )
            continue

        if simular:
            rel.simuladas += 1
            rel.linhas.append(
                Linha(evento.tipo, evento.chave, destino.id, destino.nome, nome_usina,
                      "simulada", f"{template}({' | '.join(evento.parametros)})")
            )
            continue

        # A linha nasce ANTES do envio, como no gateway: se o processo morrer no meio, o
        # que fica é uma tentativa registrada — e não um envio invisível.
        linha = NotificacaoEnviada(
            user_id=destino.id if destino.especie == "cliente" else None,
            contato_id=destino.id if destino.especie == "contato" else None,
            tipo=evento.tipo,
            chave=evento.chave,
            plant_link_id=evento.plant_link_id,
            canal="whatsapp",
            destino=destino.telefone,
            status="pendente",
        )
        db.add(linha)
        db.commit()

        try:
            r = await gateway.enviar_template(
                telefone=destino.telefone,
                template=template,
                parametros=evento.parametros,
                origem=f"motor:{evento.tipo}",
            )
            ok = bool(r.get("ok"))
            linha.wamid = r.get("wamid")
            linha.status = "enviada" if ok else "falhou"
            linha.erro = None if ok else str(r.get("erro") or "recusado pela Meta")
        except Exception as exc:  # noqa: BLE001 — gateway fora não derruba a volta inteira
            ok = False
            linha.status = "falhou"
            linha.erro = str(exc)[:500]

        linha.status_em = datetime.now(UTC)
        db.commit()

        if ok:
            rel.enviadas += 1
        else:
            rel.falhas += 1
        rel.linhas.append(
            Linha(evento.tipo, evento.chave, destino.id, destino.nome, nome_usina,
                  linha.status, linha.erro)
        )


def registrar_status(db: Session, wamid: str, status: str, erro: str | None = None) -> bool:
    """A Meta disse o que aconteceu com a mensagem. Devolve se alguma linha foi atualizada.

    O status só ANDA para frente (`pendente → enviada → entregue → lida`): as entregas da
    Meta chegam fora de ordem, e sem essa trava um aviso de "entregue" atrasado apagaria o
    "lida" que já tinha chegado — o log diria menos do que sabe.
    """
    ordem = {"pendente": 0, "enviada": 1, "entregue": 2, "lida": 3}
    linha = db.scalar(select(NotificacaoEnviada).where(NotificacaoEnviada.wamid == wamid))
    if linha is None:
        return False
    if status == "falhou":
        linha.status = "falhou"
        linha.erro = erro
    elif ordem.get(status, -1) > ordem.get(linha.status, -1):
        linha.status = status
    else:
        return False
    linha.status_em = datetime.now(UTC)
    db.commit()
    return True
