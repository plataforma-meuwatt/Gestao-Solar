"""O motor das automações (Plano Assistente GS, 26/11/2026). O dono: "tudo é gatilho, ação e onde enviar. Gatilho são
todos os parâmetros do meuWatt, meuPlano e até mesmo meuGuarda. Ação pode ser muita coisa, até um prompt de IA. E aí o
envio é WhatsApp ou e-mail, para uma ou mais pessoas."

Uma volta por minuto (`rodar_tique`, chamada pelo `main.py`). Cada regra (`gs_automacoes`) é pega com uma trava no
banco (`rodando_ate`), avaliada e solta com a próxima hora em que acorda. O que mora aqui e o que não mora:

* **Cada sistema detecta o que é dele.** O meuWatt diz o estado de cada leitura (a tela Leituras), a temperatura das
  sondas, quem está parado (a régua do aviso de parada, `avisos._parados`); o meuPlano diz as OS; o meuGuarda, os
  eventos de câmera e central. Daqui só sai a comparação com o limite da pessoa e o tempo que ela dura.
* **Toda regra lê com o token do DONO** (`so_proprio=True`), como o bot. Sem o token dele, ou com a parte desligada,
  a regra fica CEGA e diz por quê; nunca cai no token da empresa.
* **Nunca enganar.** A duração conta pela hora da LEITURA, só com dado fresco; sem dado novo com sol, a regra avisa
  que está cega (uma vez por episódio) e, quando volta, que voltou a ler; "voltou ao normal" só depois de 10 min
  seguidos dentro do limite. Toda saída vira linha em `gs_automacao_disparos`, inclusive em ensaio.
* **Entrega da Fase 1: ao próprio dono.** WhatsApp em texto só dentro da janela de 24 h (aberta pela última mensagem
  DELE: o aviso automático não abre janela); push do aplicativo; senão o aviso espera a próxima mensagem dele (24 h).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time as dtime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.datas import BRT
from app.models.automacao import Automacao, AutomacaoDisparo
from app.models.plant import PlantLink
from app.models.user import Perfil, User

log = logging.getLogger("gs.automacoes")

#: A volta do motor (`main.py`).
VOLTA_S = 60
#: Quanto a volta segura a regra: um deploy no meio só a atrasa isto.
TRAVA = timedelta(minutes=10)
#: Horário atrasado até aqui ainda dispara (dizendo a hora que era); mais que isso vira "perdida".
ATRASO_MAX = timedelta(minutes=60)
#: Sem dado novo por isto, com sol, a regra está cega. O relé tem ritmo próprio no coletor (Ibitinga ficou 19 min).
CEGA = {"leituras": timedelta(minutes=20), "monitoramento": timedelta(minutes=15), "meuguarda": timedelta(minutes=5)}
#: "Voltou ao normal" só com este tempo seguido dentro do limite, com dado fresco (a regra do "nunca enganar").
VOLTOU = timedelta(minutes=10)
#: De quanto em quanto tempo cada gatilho lê (a carga no meuWatt): relé e câmera a cada volta; o monitoramento a cada 2.
CADENCIA_S = {"tensao_rele": 60, "temperatura_trafo": 120, "usina_parada": 120, "camera": 60}
#: Leituras de outro sistema por volta, somando todas as regras; o resto espera a volta seguinte.
MAX_LEITURAS_POR_VOLTA = 40
MAX_REGRAS = 30
IA_POR_DIA = 20
#: O aviso que esperou a próxima mensagem da pessoa vale até aqui.
ADIADA_VALE = timedelta(hours=24)
#: A Meta aceita texto livre até 24 h depois da última mensagem DA PESSOA (a mesma folga de `avisos`).
JANELA = timedelta(hours=23, minutes=50)
#: Abaixo disto a fase está sem tensão: o PISO que o próprio meuWatt usa para julgar a fase zerada (readings/service).
TENSAO_PISO_V = 1000.0
#: Gente na usina: os eventos de câmera e de central do meuGuarda que dizem "alguém chegou".
GENTE = ("pessoa", "invasao_area", "linha_cruzada", "veiculo", "presenca", "porta_aberta")
_NOMES_GENTE = {"pessoa": "uma pessoa", "invasao_area": "invasão de área", "linha_cruzada": "linha cruzada",
                "veiculo": "um veículo", "presenca": "presença (sensor da central)", "porta_aberta": "porta aberta"}
#: OS aberta no meuPlano (a mesma régua da Central de Automação de lá, `os_comum.py`).
OS_ABERTA = ("ABERTA", "PROGRAMADA", "EM_EXECUCAO")
DIAS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
GRANDEZAS = {"tensao_rele": "tensão do relé", "temperatura_trafo": "temperatura do trafo",
             "usina_parada": "usina parada"}
#: Quem pode pedir análise de IA numa automação (a ponte da IA é cara e lenta): a equipe, não o cliente (Fase 1).
EQUIPE = (Perfil.GESTOR_EMPRESA, Perfil.TECNICO)

#: A prova de vida do motor desde o último deploy (a tela mostra): o log da API não mostra os registros do motor.
ULTIMA_VOLTA: datetime | None = None
#: Quando a tarefa do motor subiu neste processo (a tela diz "sem nenhuma volta desde que subiu às HH:MM").
INICIADO_EM: datetime | None = None


class RegraInvalida(Exception):
    """A frase vai à pessoa como veio."""


class _Cega(Exception):
    """A regra não enxerga a usina nesta volta (sem token, parte desligada, o sistema não respondeu)."""


class _Adiar(Exception):
    """Passou do teto de leituras desta volta: a regra espera a próxima."""


# ── utilitários ─────────────────────────────────────────────────────────────


def _agora() -> datetime:
    return datetime.now(UTC)


def _utc(dt: datetime | None) -> datetime | None:
    """O SQLite devolve sem fuso (gravado em UTC); o Postgres, com."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _ts(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return _utc(v)
    if not v:
        return None
    try:
        return _utc(datetime.fromisoformat(str(v).replace("Z", "+00:00")))
    except ValueError:
        return None


def _hora(dt: datetime | None, com_dia: bool | None = None) -> str:
    """"14:12" hoje, "26/11 14:12" em outro dia (Brasília)."""
    if dt is None:
        return "—"
    local = _utc(dt).astimezone(BRT)
    if com_dia is None:
        com_dia = local.date() != datetime.now(BRT).date()
    return local.strftime("%d/%m %H:%M" if com_dia else "%H:%M")


def _n(v: float | None, casas: int = 1) -> str:
    if v is None:
        return "—"
    s = f"{float(v):,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(str(int(p)) if p.isdigit() else p for p in s.split())


def _casa(termo: Any, nome: Any) -> bool:
    """O nome falado no nome do equipamento ("skid 1" em "Relé Skid 1", "tr 2" em "TR-02"). Sem termo, todos."""
    t, n = _norm(termo), _norm(nome)
    if not t:
        return True
    return f" {t} " in f" {n} " or n == t


def _minutos(td: timedelta) -> int:
    return max(0, int(td.total_seconds() // 60))


# ── o calendário ────────────────────────────────────────────────────────────


def _dias(gatilho: dict) -> set[int]:
    ds = gatilho.get("dias")
    if not ds:
        return set(range(7))
    return {d for d in ds if isinstance(d, int) and 0 <= d <= 6}


def proxima_execucao(gatilho: dict, depois: datetime) -> datetime | None:
    """A próxima hora marcada estritamente depois de `depois` (Brasília). Lembrete: a hora dele (uma vez)."""
    if gatilho.get("tipo") == "uma_vez":
        return _ts(gatilho.get("em"))
    if gatilho.get("tipo") != "horario":
        return None
    h, _, m = str(gatilho.get("hora") or "").partition(":")
    hora = dtime(int(h), int(m or 0))
    dias = _dias(gatilho) or set(range(7))
    base = _utc(depois).astimezone(BRT)
    for k in range(0, 9):
        dia = base.date() + timedelta(days=k)
        if dia.weekday() not in dias:
            continue
        quando = datetime.combine(dia, hora, tzinfo=BRT)
        if quando > base:
            return quando.astimezone(UTC)
    return None


def _dias_em_palavras(gatilho: dict) -> str:
    ds = sorted(_dias(gatilho))
    if ds == list(range(7)):
        return "todo dia"
    if ds == [0, 1, 2, 3, 4]:
        return "de segunda a sexta"
    return ", ".join(DIAS[d] for d in ds)


def descrever(regra: Automacao) -> str:
    """O gatilho e a ação em palavras (a lista do bot e a tela)."""
    g, a = regra.gatilho or {}, regra.acao or {}
    tipo = g.get("tipo")
    if tipo == "uma_vez":
        quando = f"uma vez, {_hora(_ts(g.get('em')), com_dia=True)}"
    elif tipo == "horario":
        quando = f"{_dias_em_palavras(g)} às {g.get('hora')}"
    elif tipo == "leitura":
        gr = g.get("grandeza")
        alvo = f" {g['alvo']}" if g.get("alvo") else ""
        if alvo and _norm(alvo).split()[0] in ("rele", "tr", "trafo", "transformador"):   # "tensão do Relé Skid 1"
            alvo = f" {g['alvo']}"
            base = {"tensao_rele": "tensão do", "temperatura_trafo": "temperatura do"}.get(gr, GRANDEZAS.get(gr, gr))
        else:
            base = GRANDEZAS.get(gr, gr)
        if gr == "usina_parada":
            quando = "usina parada"
        else:
            unidade = "V" if gr == "tensao_rele" else "°C"
            op = "abaixo de" if (g.get("operador") or ("<" if gr == "tensao_rele" else ">")) == "<" else "acima de"
            limite = g.get("limite") or (TENSAO_PISO_V if gr == "tensao_rele" else None)
            quando = f"{base}{alvo} {op} {_n(limite, 0)} {unidade}"
            if gr == "tensao_rele" and op == "abaixo de":
                quando += " (ou fase zerada)"
        if g.get("duracao_min"):
            quando += f" por {g['duracao_min']} min"
    elif tipo == "camera":
        quando = "gente na usina (câmera ou central do meuGuarda)"
    else:
        quando = str(tipo)
    if any(c.get("tipo") == "os_aberta" for c in regra.condicoes or []):
        quando += ", com OS aberta"
    for c in regra.condicoes or []:
        if c.get("tipo") == "pr_dia":
            quando += f", se o PR do dia ficar abaixo de {_n(c.get('limite'), 0)}%"
    o_que = {"resumo_geracao": "o resumo da geração", "ia": "a análise da IA"}.get(a.get("tipo"), "")
    return f"{quando}{': ' + o_que if o_que else ''}"


# ── cadastro (o bot e a tela) ───────────────────────────────────────────────


def onde(db: Session, regra: Automacao) -> str | None:
    """Em quais usinas a regra vale, em palavras ("todas as usinas menos Tiete"). None no lembrete (sem usina)."""
    e = regra.escopo or {}
    if e.get("todas"):
        menos = [u.nome for u in db.scalars(select(PlantLink).where(PlantLink.id.in_(e.get("menos") or [])))]
        return "todas as usinas" + (f" menos {', '.join(menos)}" if menos else "")
    if e.get("usinas"):
        return ", ".join(u.nome for u in db.scalars(select(PlantLink).where(PlantLink.id.in_(e["usinas"])))) or None
    return None


def ativas(db: Session, user_id: int) -> list[Automacao]:
    return list(db.scalars(select(Automacao).where(Automacao.user_id == user_id, Automacao.apagada_em.is_(None),
                                                   Automacao.situacao != "concluida").order_by(Automacao.id)).all())


def criar(db: Session, dono: User, *, nome: str, gatilho: dict, acao: dict, condicoes: list | None = None,
          escopo: dict | None = None, entrega: dict | None = None, situacao: str = "ligada",
          texto_original: str | None = None, origem: str = "bot", agora: datetime | None = None) -> Automacao:
    if len(ativas(db, dono.id)) >= MAX_REGRAS:
        raise RegraInvalida(f"Você já tem {MAX_REGRAS} regras: apague alguma antes de criar outra.")
    agora = agora or _agora()
    tipo = gatilho.get("tipo")
    proxima = proxima_execucao(gatilho, agora) if tipo in ("horario", "uma_vez") else agora
    if tipo in ("horario", "uma_vez") and proxima is None:
        raise RegraInvalida("Não entendi a hora da regra.")
    if tipo == "uma_vez" and proxima <= agora:
        raise RegraInvalida(f"Essa hora já passou ({_hora(proxima, com_dia=True)}): diga outra.")
    regra = Automacao(user_id=dono.id, empresa_id=dono.empresa_id, nome=nome[:160], texto_original=texto_original,
                      gatilho=gatilho, condicoes=condicoes or [], escopo=escopo or {}, acao=acao,
                      entrega=entrega or {"canais": ["whatsapp", "push"]}, situacao=situacao, estado={},
                      proxima_em=proxima, origem=origem)
    db.add(regra)
    db.commit()
    return regra


def achar(db: Session, dono: User, qual: Any) -> Automacao:
    """A regra da pessoa pelo número ou por um pedaço do nome."""
    regras = [r for r in db.scalars(select(Automacao).where(Automacao.user_id == dono.id,
                                                            Automacao.apagada_em.is_(None))).all()]
    alvo = str(qual or "").strip().lstrip("#")
    if not regras:
        raise RegraInvalida("Você não tem nenhuma regra.")
    if alvo.isdigit():
        for r in regras:
            if r.id == int(alvo):
                return r
        raise RegraInvalida(f"Não achei a regra {alvo}. Suas regras: " + ", ".join(f"{r.id} ({r.nome})" for r in regras))
    cands = [r for r in regras if alvo and _norm(alvo) in _norm(r.nome)]
    if len(cands) == 1:
        return cands[0]
    raise RegraInvalida(("Mais de uma regra casa: " if cands else "Qual regra? ")
                        + ", ".join(f"{r.id} ({r.nome})" for r in (cands or regras)) + ". Diga o número.")


def mudar(db: Session, regra: Automacao, situacao: str, agora: datetime | None = None) -> None:
    agora = agora or _agora()
    if (situacao in ("ligada", "ensaio") and (regra.gatilho or {}).get("tipo") == "uma_vez"
            and (_utc(regra.proxima_em) is None or _utc(regra.proxima_em) <= agora)):
        # ligado de novo, o lembrete vencido dispararia na hora ("era para…") e concluiria: melhor dizer
        raise RegraInvalida("Essa hora já passou: o lembrete não tem o que ligar. Peça um lembrete novo.")
    regra.situacao = situacao
    regra.rodando_ate = None
    if situacao in ("ligada", "ensaio"):
        tipo = (regra.gatilho or {}).get("tipo")
        if tipo == "horario":
            regra.proxima_em = proxima_execucao(regra.gatilho, agora)
        elif tipo in ("leitura", "camera"):
            regra.proxima_em = agora
        # ao ligar ou voltar ao ensaio, a regra olha de novo do zero: o episódio que o ensaio segurou avisa agora
        regra.estado = {"ensaio_mandado": False}
    regra.atualizada_em = agora
    db.commit()


def apagar(db: Session, regra: Automacao) -> None:
    regra.apagada_em = _agora()
    regra.rodando_ate = None
    db.commit()


def tem_regra_de_parada_ligada(db: Session, user_id: int) -> bool:
    """Quem tem regra de usina parada LIGADA sai do aviso de parada antigo (o push de `avisos`): a regra é que avisa,
    com "todas menos X", e o aviso não sai em dobro nem da usina que a pessoa tirou."""
    for r in db.scalars(select(Automacao).where(Automacao.user_id == user_id, Automacao.situacao == "ligada",
                                                Automacao.apagada_em.is_(None))):
        if (r.gatilho or {}).get("grandeza") == "usina_parada":
            return True
    return False


def ultimo_disparo(db: Session, regra: Automacao) -> AutomacaoDisparo | None:
    return db.scalar(select(AutomacaoDisparo).where(AutomacaoDisparo.automacao_id == regra.id)
                     .order_by(AutomacaoDisparo.id.desc()).limit(1))


def segurados(db: Session, regra: Automacao) -> int:
    """Os avisos de ensaio que ficaram só no registro."""
    return int(db.scalar(select(func.count(AutomacaoDisparo.id)).where(
        AutomacaoDisparo.automacao_id == regra.id, AutomacaoDisparo.status == "simulada",
        AutomacaoDisparo.evento.not_in(("teste", "nao_valeu")))) or 0)


# ── a volta ─────────────────────────────────────────────────────────────────


@dataclass
class _Volta:
    agora: datetime
    #: (dono, rota, usina) → a resposta (ou a exceção) desta volta: a mesma leitura serve a todas as regras do dono.
    lidos: dict = field(default_factory=dict)
    leituras: int = 0
    clientes: dict = field(default_factory=dict)
    #: regra → os valores lidos que NÃO passaram na condição (o registro da volta em que nada saiu)
    nao_valeu: dict = field(default_factory=dict)


def pegar_devidas(db: Session, agora: datetime) -> list[int]:
    """As regras que acordam agora, travadas para esta volta. A condição inteira fica no WHERE do UPDATE: duas voltas
    ao mesmo tempo (o deploy que sobe com o antigo ainda de pé) não pegam a mesma regra."""
    q = (update(Automacao)
         .where(Automacao.situacao.in_(("ligada", "ensaio")), Automacao.apagada_em.is_(None),
                or_(Automacao.proxima_em.is_(None), Automacao.proxima_em <= agora),
                or_(Automacao.rodando_ate.is_(None), Automacao.rodando_ate < agora))
         .values(rodando_ate=agora + TRAVA)
         .returning(Automacao.id)
         .execution_options(synchronize_session=False))
    ids = sorted(db.execute(q).scalars().all())
    db.commit()
    return ids


async def rodar_tique(db: Session, agora: datetime | None = None) -> dict:
    """Uma volta: pega as regras que acordam, avalia cada uma (uma que quebra não derruba as outras) e solta."""
    global ULTIMA_VOLTA
    agora = agora or _agora()
    volta = _Volta(agora=agora)
    ids = pegar_devidas(db, agora)
    for id_ in ids:
        regra = db.get(Automacao, id_)
        if regra is None:
            continue
        try:
            await _avaliar(db, regra, volta)
            regra.ultimo_erro = None
        except _Adiar:
            regra.proxima_em = agora + timedelta(seconds=VOLTA_S)
        except Exception as e:                             # noqa: BLE001 — uma regra quebrada não para as outras
            db.rollback()
            regra = db.get(Automacao, id_)
            log.exception("automacoes: a regra %s falhou", id_)
            await _registrar_erro(db, regra, agora, e)
            tipo = (regra.gatilho or {}).get("tipo")
            if tipo == "horario":                          # a de horário vai à próxima hora marcada: tentar a cada
                regra.proxima_em = proxima_execucao(regra.gatilho, agora)   # 5 min rodaria "a de hoje" de madrugada
            elif tipo == "uma_vez" and agora - (_utc(regra.proxima_em) or agora) > ATRASO_MAX:
                regra.situacao, regra.proxima_em = "concluida", None       # o lembrete que não sai em 1 h desiste
            else:
                regra.proxima_em = agora + timedelta(minutes=5)
        regra.rodando_ate = None
        regra.ultima_volta_em = agora
        db.commit()
    ULTIMA_VOLTA = agora
    return {"regras": len(ids), "leituras": volta.leituras}


async def _registrar_erro(db: Session, regra: Automacao, agora: datetime, e: Exception) -> None:
    import hashlib

    frase = (str(e) or type(e).__name__)[:300]
    regra.ultimo_erro = frase
    db.commit()
    dono = db.get(User, regra.user_id)
    if dono is not None:                                   # uma vez por erro por dia: o dono sabe que a regra não rodou
        marca = hashlib.sha1(frase.encode()).hexdigest()[:12]
        await _disparar(db, regra, dono, evento="erro", chave=f"erro:{agora.astimezone(BRT).date()}:{marca}",
                        texto=f"⚠️ A regra {regra.id} «{regra.nome}» deu erro: {frase}. Tento de novo em 5 min.",
                        agora=agora, rodape=False)


async def _avaliar(db: Session, regra: Automacao, volta: _Volta) -> None:
    dono = db.get(User, regra.user_id)
    if dono is None or not dono.ativo:
        mudar(db, regra, "pausada", volta.agora)
        return
    tipo = (regra.gatilho or {}).get("tipo")
    if tipo in ("horario", "uma_vez"):
        await _avaliar_horario(db, regra, dono, volta)
    elif tipo == "leitura":
        await _avaliar_leitura(db, regra, dono, volta)
        regra.proxima_em = volta.agora + timedelta(seconds=CADENCIA_S.get(regra.gatilho.get("grandeza"), VOLTA_S))
    elif tipo == "camera":
        await _avaliar_camera(db, regra, dono, volta)
        regra.proxima_em = volta.agora + timedelta(seconds=CADENCIA_S["camera"])
    else:
        raise RegraInvalida(f"gatilho desconhecido: {tipo}")


# ── escopo e leitura ────────────────────────────────────────────────────────


def usinas_da_regra(db: Session, regra: Automacao, dono: User) -> list[PlantLink]:
    """O escopo resolvido AGORA contra o que o dono vê: usina nova entra sozinha em "todas"; usina que ele perdeu sai."""
    from app.services.assistente_geracao import usinas_do_bot

    minhas = {u.id: u for u in usinas_do_bot(db, dono)}
    e = regra.escopo or {}
    if e.get("todas"):
        fora = set(e.get("menos") or [])
        return [u for i, u in minhas.items() if i not in fora]
    return [minhas[i] for i in e.get("usinas") or [] if i in minhas]


def _mw(db: Session, dono: User, volta: _Volta):
    from app.services.vinculos import SemConexao, cliente_meuwatt

    if "bot_meuwatt" not in dono.bot_ativo:
        raise _Cega("a parte de monitoramento do bot não está liberada para você (o gerente libera)")
    if dono.id not in volta.clientes:
        try:
            volta.clientes[dono.id] = cliente_meuwatt(db, dono.id, so_proprio=True)
        except SemConexao:
            raise _Cega("você não tem o token do meuWatt no Gestão Solar") from None
    return volta.clientes[dono.id]


async def _ler(db: Session, volta: _Volta, dono: User, rota: str, slug: str) -> Any:
    """Uma leitura do meuWatt, uma vez por volta para cada dono. O que falha falha para todas as regras dele."""
    chave = (dono.id, rota, slug)
    if chave not in volta.lidos:
        if volta.leituras >= MAX_LEITURAS_POR_VOLTA:
            raise _Adiar()
        mw = _mw(db, dono, volta)
        volta.leituras += 1
        db.commit()                                        # solta a conexão enquanto o meuWatt responde
        try:
            volta.lidos[chave] = await (mw.leituras(slug) if rota == "leituras" else mw.monitoramento_atual(slug))
        except httpx.HTTPError as e:
            volta.lidos[chave] = _Cega(f"o meuWatt não respondeu ({type(e).__name__})")
    r = volta.lidos[chave]
    if isinstance(r, Exception):
        raise r
    return r


@dataclass
class Amostra:
    """Uma leitura de um alvo (um relé, um trafo, a usina) nesta volta."""

    chave: str
    usina: PlantLink
    alvo: str
    #: True = fora do limite; False = dentro; None = sem dado fresco (o contador pausa)
    fora: bool | None
    quando: datetime | None = None
    #: fora da janela solar: sem dado não conta como cegueira (o coletor dorme)
    dormindo: bool = False
    motivo: str = ""
    valor: str = ""
    leitura: dict = field(default_factory=dict)
    #: o que está fora (os inversores parados): o aviso sai de novo quando aparece um novo
    itens: dict = field(default_factory=dict)
    #: por que não há dado (vai no aviso de cega)
    porque: str = ""


def _limite_de(gatilho: dict, padrao: float | None) -> float | None:
    try:
        return float(gatilho["limite"]) if gatilho.get("limite") is not None else padrao
    except (TypeError, ValueError):
        return padrao


async def _amostras_tensao(db: Session, volta: _Volta, regra: Automacao, dono: User, link: PlantLink) -> list[Amostra]:
    g = regra.gatilho
    dados = await _ler(db, volta, dono, "leituras", link.mw_plant_slug)
    mon = await _ler(db, volta, dono, "monitoramento", link.mw_plant_slug)
    sol = bool((mon or {}).get("in_solar_window"))
    reles = [r for r in (dados or {}).get("relays") or [] if _casa(g.get("alvo"), r.get("name"))]
    if not reles:
        return [Amostra(f"{link.id}:rele:{g.get('alvo')}", link, str(g.get("alvo") or "o relé"), None, dormindo=False,
                        porque=f"não acho o relé «{g.get('alvo')}» nas leituras de {link.nome}")]
    limite = _limite_de(g, TENSAO_PISO_V)
    op = g.get("operador") or "<"
    saida = []
    for r in reles:
        nome = str(r.get("name") or "relé")
        leit = {x.get("key"): x for x in r.get("readings") or [] if isinstance(x, dict)}
        # a fase marcada «já sei» na tela Leituras não conta (o relé do Skid 3 de Pirapozinho que não lê a fase A)
        fases = {f: leit.get(f"voltage_{f}") or {} for f in "abc"
                 if not ((leit.get(f"voltage_{f}") or {}).get("mark") or {}).get("ignored")}
        if not fases:
            continue
        quando = max((t for x in fases.values() if (t := _ts(x.get("last_valid_at")))), default=None)
        estados = {f: x.get("status") for f, x in fases.items()}
        valores = {f: x.get("value") for f, x in fases.items()}
        validos = all(estados[f] in ("ok", "zeroed") and isinstance(valores[f], (int, float)) for f in fases)
        fresco = quando is not None and volta.agora - quando <= CEGA["leituras"]
        a = Amostra(f"{link.id}:rele:{nome}", link, nome, None, quando=quando, dormindo=not sol,
                    leitura={"fases": {f: {"valor": valores[f], "estado": estados[f]} for f in fases},
                             "leitura_em": quando.isoformat() if quando else None})
        if not (validos and fresco):
            a.porque = "o relé não manda leitura válida (" + ", ".join(sorted({str(e) for e in estados.values()})) + ")"
            saida.append(a)
            continue
        ordem = "/".join(f.upper() for f in fases)
        a.valor = f"fases {ordem}: " + "/".join(_n(valores[f], 0) for f in fases) + " V"
        if op == ">":
            acima = [f.upper() for f in fases if valores[f] > limite]
            a.fora, a.motivo = bool(acima), f"fase {', '.join(acima)} acima de {_n(limite, 0)} V"
        else:
            zeradas = [f.upper() for f in fases if estados[f] == "zeroed"]
            sem = all(valores[f] < limite for f in fases)
            a.fora = sem or bool(zeradas)
            a.motivo = ("sem tensão" + (" nas três fases" if len(fases) == 3 else "") if sem
                        else f"fase {', '.join(zeradas)} zerada" if zeradas else "")
        saida.append(a)
    return saida


async def _amostras_temperatura(db: Session, volta: _Volta, regra: Automacao, dono: User,
                                link: PlantLink) -> list[Amostra]:
    g = regra.gatilho
    mon = await _ler(db, volta, dono, "monitoramento", link.mw_plant_slug)
    sol = bool((mon or {}).get("in_solar_window"))
    sensores = [t for t in (mon or {}).get("temp_sensors") or []
                if _casa(g.get("alvo"), t.get("transformer_name")) or _casa(g.get("alvo"), t.get("name"))]
    if not sensores:
        return [Amostra(f"{link.id}:trafo:{g.get('alvo')}", link, str(g.get("alvo") or "o trafo"), None,
                        porque=f"não acho as sondas de «{g.get('alvo')}» em {link.nome}")]
    op = g.get("operador") or ">"
    saida = []
    for t in sensores:
        nome = str(t.get("transformer_name") or t.get("name") or "trafo")
        sondas = {f"S{i}": t.get(f"temp_s{i}") for i in (1, 2, 3) if isinstance(t.get(f"temp_s{i}"), (int, float))}
        quando = _ts(t.get("last_read_at") or t.get("timestamp"))
        a = Amostra(f"{link.id}:trafo:{nome}", link, nome, None, quando=quando, dormindo=not sol,
                    leitura={"sondas": sondas, "leitura_em": quando.isoformat() if quando else None})
        if not sondas or quando is None or volta.agora - quando > CEGA["monitoramento"]:
            a.porque = "as sondas não mandam leitura nova"
            saida.append(a)
            continue
        limite = _limite_de(g, None)
        if limite is None:
            limite = _limite_registrado(t)
        if limite is None:
            a.porque = "a regra não tem o limite em °C"
            saida.append(a)
            continue
        maior_nome, maior = max(sondas.items(), key=lambda kv: kv[1])
        a.fora = maior > limite if op == ">" else maior < limite
        a.valor = f"{maior_nome} a {_n(maior, 1)} °C (" + ", ".join(f"{k} {_n(v, 1)}" for k, v in sondas.items()) + ")"
        a.motivo = f"{'acima' if op == '>' else 'abaixo'} de {_n(limite, 0)} °C"
        saida.append(a)
    return saida


def _limite_registrado(sensor: dict) -> float | None:
    """O limite de alarme cadastrado no meuWatt para o relé de temperatura, quando há."""
    lim = sensor.get("registered_thresholds")
    if isinstance(lim, dict):
        for k in ("alarm_c", "alarm", "alarme"):
            if isinstance(lim.get(k), (int, float)):
                return float(lim[k])
    for k in ("alarm_c", "alarm_threshold_c"):
        if isinstance(sensor.get(k), (int, float)):
            return float(sensor[k])
    return None


async def _amostras_parada(db: Session, volta: _Volta, regra: Automacao, dono: User, link: PlantLink) -> list[Amostra]:
    from app.services import avisos

    mon = await _ler(db, volta, dono, "monitoramento", link.mw_plant_slug)
    quando = _ts((mon or {}).get("data_at"))
    a = Amostra(f"{link.id}:usina", link, "a usina", None, quando=quando,
                dormindo=not bool((mon or {}).get("in_solar_window")))
    if quando is None or volta.agora - quando > CEGA["monitoramento"]:
        a.porque = "o monitoramento não manda dado novo"
        return [a]
    parados = avisos._parados(mon)                          # a régua do aviso de parada (20 min, 72 h, sem ignorado)
    if parados:
        if volta.leituras >= MAX_LEITURAS_POR_VOLTA:
            raise _Adiar()
        volta.leituras += 1
        parados = await avisos._so_as_materiais(_mw(db, dono, volta), link.mw_plant_slug, parados)
    a.fora = bool(parados)
    a.itens = {str(i.get("id") or i.get("serial_number")): str(i.get("down_since") or "") for i in parados}
    nomes = [str(i.get("name") or i.get("serial_number") or "inversor") for i in parados]
    desde = min((t for i in parados if (t := _ts(i.get("down_since")))), default=None)
    a.valor = (f"{len(nomes)} inversor{'es' if len(nomes) > 1 else ''} parado{'s' if len(nomes) > 1 else ''}: "
               + _lista(nomes) + (f" (desde {_hora(desde)})" if desde else "")) if nomes else "nenhum inversor parado"
    a.leitura = {"parados": {str(i.get("id") or i.get("serial_number")): {
        "nome": str(i.get("name") or i.get("serial_number") or "inversor"), "desde": str(i.get("down_since") or "")}
        for i in parados}, "leitura_em": quando.isoformat()}
    return [a]


def _lista(nomes: list[str], n: int = 8) -> str:
    return ", ".join(nomes[:n]) + (f" e mais {len(nomes) - n}" if len(nomes) > n else "")


_AMOSTRAS = {"tensao_rele": _amostras_tensao, "temperatura_trafo": _amostras_temperatura,
             "usina_parada": _amostras_parada}


# ── leitura com duração, cegueira e "voltou" ────────────────────────────────


async def _avaliar_leitura(db: Session, regra: Automacao, dono: User, volta: _Volta, teste: list | None = None) -> None:
    g = regra.gatilho
    leitor = _AMOSTRAS[g.get("grandeza")]
    usinas = [u for u in usinas_da_regra(db, regra, dono) if u.mw_plant_slug]
    alvos = dict((regra.estado or {}).get("alvos") or {})
    if not usinas:
        await _cegueira(db, regra, dono, volta, alvos, "regra", None, None,
                        "nenhuma usina desta regra está no seu recorte com monitoramento", dormindo=False, teste=teste)
    else:
        await _cegueira_resolvida(db, regra, dono, volta, alvos, "regra", None, teste)
    if not _condicoes_do_relogio(regra, volta.agora):
        _guardar_alvos(regra, alvos, teste)
        return
    duracao = timedelta(minutes=int(g.get("duracao_min") or 0))
    adiar = False
    for link in usinas:
        try:
            amostras = await leitor(db, volta, regra, dono, link)
        except _Adiar:                                     # passou do teto de leituras: o resto espera a volta seguinte
            adiar = True
            break
        except _Cega as c:
            await _cegueira(db, regra, dono, volta, alvos, f"{link.id}:*", link, None, str(c), dormindo=False,
                            teste=teste)
            continue
        await _cegueira_resolvida(db, regra, dono, volta, alvos, f"{link.id}:*", link, teste)
        for a in amostras:
            if teste is None:                              # desde quando a usina está acordada (o prazo da cegueira)
                st0 = dict(alvos.get(a.chave) or {})
                if a.dormindo:
                    st0["acordada_em"] = None
                elif not st0.get("acordada_em"):
                    st0["acordada_em"] = volta.agora.isoformat()
                alvos[a.chave] = st0
            if a.fora is None:
                if teste is not None:
                    teste.append(f"{link.nome} · {a.alvo}: sem leitura fresca ({a.porque or 'sem dado'}"
                                 f"{'; leitura das ' + _hora(a.quando) if a.quando else ''}).")
                    continue
                if not a.dormindo:
                    await _cegueira(db, regra, dono, volta, alvos, a.chave, link, a.quando, a.porque, a.dormindo)
                continue
            await _cegueira_resolvida(db, regra, dono, volta, alvos, a.chave, link, teste, a)
            if teste is not None:
                juizo = ("" if g.get("grandeza") == "usina_parada" else
                         f"; FORA do limite ({a.motivo})" if a.fora else "; dentro do limite")
                teste.append(f"{link.nome} · {a.alvo}: {a.valor}{juizo} (leitura das {_hora(a.quando)}).")
                continue
            st = dict(alvos.get(a.chave) or {})
            q = a.quando or volta.agora
            if a.fora:
                st["normal_desde"] = None
                desde = _ts(st.get("desde")) or q
                st["desde"] = desde.isoformat()
                if not st.get("episodio") and q - desde >= duracao:
                    ep = f"ep:{a.chave}:{desde.isoformat()}"
                    st["episodio"], st["avisados"] = ep, list(a.itens)
                    await _disparar(db, regra, dono, evento="disparo", chave=ep, link=link, agora=volta.agora,
                                    texto=_texto_fora(regra, a, desde, q), leitura=a.leitura)
                elif st.get("episodio") and set(a.itens) - set(st.get("avisados") or []):
                    novos = sorted(set(a.itens) - set(st.get("avisados") or []))
                    st["avisados"] = sorted(set(st.get("avisados") or []) | set(novos))
                    await _disparar(db, regra, dono, evento="disparo", chave=f"{st['episodio']}:+{','.join(novos)}"[:200],
                                    link=link, agora=volta.agora, texto=_texto_fora(regra, a, desde, q, mais=True),
                                    leitura=a.leitura)
            else:
                st["desde"] = None
                if st.get("episodio"):
                    normal = _ts(st.get("normal_desde")) or q
                    st["normal_desde"] = normal.isoformat()
                    if q - normal >= VOLTOU:
                        await _disparar(db, regra, dono, evento="voltou", chave=f"voltou:{st['episodio']}"[:200],
                                        link=link, agora=volta.agora, texto=_texto_voltou(regra, a, normal),
                                        leitura=a.leitura)
                        st["episodio"], st["normal_desde"], st["avisados"] = None, None, []
            alvos[a.chave] = st
    _guardar_alvos(regra, alvos, teste)
    if adiar:
        raise _Adiar()


def _guardar_alvos(regra: Automacao, alvos: dict, teste: list | None) -> None:
    """O estado dos alvos volta à regra SEM apagar o resto dele (a marca do ensaio que o disparo acabou de gravar)."""
    if teste is None:
        regra.estado = {**(regra.estado or {}), "alvos": alvos}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _condicoes_do_relogio(regra: Automacao, agora: datetime) -> bool:
    """As condições que não dependem de usina: entre duas horas, dia útil."""
    local = _utc(agora).astimezone(BRT)
    for c in regra.condicoes or []:
        if c.get("tipo") == "dia_util" and local.weekday() >= 5:
            return False
        if c.get("tipo") == "entre":
            de, ate = str(c.get("de") or "00:00"), str(c.get("ate") or "23:59")
            agora_hm = local.strftime("%H:%M")
            dentro = de <= agora_hm <= ate if de <= ate else (agora_hm >= de or agora_hm <= ate)
            if not dentro:
                return False
    return True


async def _cegueira(db: Session, regra: Automacao, dono: User, volta: _Volta, alvos: dict, chave: str,
                    link: PlantLink | None, ultima: datetime | None, porque: str, dormindo: bool,
                    teste: list | None = None) -> None:
    """Sem dado: o contador pausa; com sol (ou quando a causa não é o coletor dormir), passado o prazo, avisa uma vez."""
    if teste is not None:
        teste.append(f"{link.nome + ' · ' if link else ''}sem leitura: {porque}.")
        return
    st = dict(alvos.get(chave) or {})
    if dormindo:                                           # de noite o coletor dorme: o prazo recomeça de manhã
        if not st.get("cega"):
            st["sem_dado_desde"], st["acordada_em"] = None, None
            alvos[chave] = st
        return
    # O prazo conta da última leitura, mas nunca de antes de a usina acordar: ao nascer do sol o último dado é da
    # véspera, e contar dele diria "cega" toda manhã antes de o coletor voltar. Durante o dia, ~20 min depois da última
    # leitura. A frase diz a hora da última leitura que houve.
    if not st.get("acordada_em"):
        st["acordada_em"] = volta.agora.isoformat()
    acordada = _ts(st["acordada_em"])
    notou = max(ultima, acordada) if ultima else acordada
    st["sem_dado_desde"], st["porque"] = notou.isoformat(), porque
    prazo = CEGA["meuguarda"] if regra.gatilho.get("tipo") == "camera" else CEGA["leituras"]
    if not st.get("cega") and volta.agora - notou >= prazo:
        onde = f" de {link.nome}" if link else ""
        ultima_txt = f" desde {_hora(ultima)}" if ultima else f" há {_minutos(volta.agora - notou)} min"
        await _disparar(db, regra, dono, evento="cega", chave=f"cega:{chave}:{notou.isoformat()}"[:200], link=link,
                        agora=volta.agora, texto=(f"👁️ Regra {regra.id} «{regra.nome}»: não leio{onde}{ultima_txt} "
                                                  f"({porque}). A regra está cega até o dado voltar."
                                                  + (" Pode ser a comunicação ou falta de energia na usina."
                                                     if regra.gatilho.get("grandeza") == "tensao_rele" else "")))
        st["cega"] = True
    alvos[chave] = st


async def _cegueira_resolvida(db: Session, regra: Automacao, dono: User, volta: _Volta, alvos: dict, chave: str,
                              link: PlantLink | None, teste: list | None, amostra: Amostra | None = None) -> None:
    if teste is not None:
        return
    st = dict(alvos.get(chave) or {})
    if st.get("cega"):
        quando = amostra.quando if amostra else volta.agora
        await _disparar(db, regra, dono, evento="enxergou", chave=f"enxergou:{chave}:{st.get('sem_dado_desde')}"[:200],
                        link=link, agora=volta.agora,
                        texto=f"👁️ Regra {regra.id} «{regra.nome}»: voltei a ler{' ' + link.nome if link else ''} "
                              f"(leitura das {_hora(quando)}).")
    if st.get("cega") or st.get("sem_dado_desde"):
        st["cega"], st["sem_dado_desde"] = False, None
        alvos[chave] = st


def _texto_fora(regra: Automacao, a: Amostra, desde: datetime, q: datetime, mais: bool = False) -> str:
    gr = regra.gatilho.get("grandeza")
    ha = _minutos(q - desde)
    if gr == "usina_parada":
        return (f"🔴 {a.usina.nome}: {'mais um inversor parou. ' if mais else ''}{a.valor}. Leitura das {_hora(q)}.")
    simbolo = "⚡" if gr == "tensao_rele" else "🌡️"
    return (f"{simbolo} {a.usina.nome} · {a.alvo}: {a.motivo}{f' há {ha} min' if ha else ''} (desde {_hora(desde)}). "
            f"{_cap(a.valor)}; leitura das {_hora(q)}.")


def _texto_voltou(regra: Automacao, a: Amostra, normal: datetime) -> str:
    if regra.gatilho.get("grandeza") == "usina_parada":
        return f"✅ {a.usina.nome}: nenhum inversor parado desde {_hora(normal)} (10 min seguidos)."
    return f"✅ {a.usina.nome} · {a.alvo}: voltou ao normal desde {_hora(normal)} (10 min seguidos). {_cap(a.valor)}."


# ── gente na usina (meuGuarda) ──────────────────────────────────────────────


def _meuguarda(dono: User):
    from app.services import assistente_meuguarda as mg

    if not mg.permitidas(dono) or not mg.disponivel(dono):
        raise _Cega("as câmeras (meuGuarda) não estão liberadas para você")
    return mg.cliente(dono)


async def _os_abertas(db: Session, volta: _Volta, dono: User, link: PlantLink) -> list[dict] | None:
    """As OS abertas da usina no meuPlano, com o token do dono. None = não deu para conferir (sem token, meuPlano fora)."""
    from app.services.vinculos import SemConexao, cliente_meuplano

    if not link.mp_usina_id or "bot_meuplano" not in dono.bot_ativo:
        return None
    chave = (dono.id, "os", link.id)
    if chave not in volta.lidos:
        try:
            mp = cliente_meuplano(db, dono.id, so_proprio=True)
            db.commit()
            vistas: dict = {}
            for st in OS_ABERTA:
                for o in await mp.ordens_servico(link.mp_usina_id, st):
                    if isinstance(o, dict) and o.get("id") is not None:
                        vistas[o["id"]] = o
            volta.lidos[chave] = list(vistas.values())
        except (SemConexao, httpx.HTTPError):
            volta.lidos[chave] = None
    return volta.lidos[chave]


async def _avaliar_camera(db: Session, regra: Automacao, dono: User, volta: _Volta, teste: list | None = None) -> None:
    """Os eventos dos últimos 10 min (o agente pode entregar atrasado): a chave do aviso (por OS por dia, ou um a cada
    30 min por usina) é que impede repetir, então reler a mesma janela não avisa de novo."""
    alvos = dict((regra.estado or {}).get("alvos") or {})
    usinas = {u.id: u for u in usinas_da_regra(db, regra, dono)}
    tipos = set((regra.gatilho or {}).get("tipos") or GENTE)
    com_os = any(c.get("tipo") == "os_aberta" for c in regra.condicoes or [])
    desde = volta.agora - (timedelta(hours=24) if teste is not None else timedelta(minutes=10))
    try:
        mg = _meuguarda(dono)
        db.commit()
        if volta.leituras >= MAX_LEITURAS_POR_VOLTA:
            raise _Adiar()
        volta.leituras += 1
        lista_mg = await mg.usinas()
        eventos = await mg.alarmes_desde(desde.isoformat())
    except _Cega as c:
        await _cegueira(db, regra, dono, volta, alvos, "meuguarda", None, None, str(c), dormindo=False, teste=teste)
        _guardar_alvos(regra, alvos, teste)
        return
    except httpx.HTTPError as e:
        await _cegueira(db, regra, dono, volta, alvos, "meuguarda", None, None,
                        f"o meuGuarda não respondeu ({type(e).__name__})", dormindo=False, teste=teste)
        _guardar_alvos(regra, alvos, teste)
        return
    await _cegueira_resolvida(db, regra, dono, volta, alvos, "meuguarda", None, teste)
    gs_de_mg = {}
    for u in lista_mg or []:
        alvo = u.get("gs_usina_id")
        if alvo is None:                                   # sem o id do GS, pelo nome
            alvo = next((i for i, p in usinas.items() if _norm(p.nome) == _norm(u.get("nome"))), None)
        if alvo is not None:
            gs_de_mg[u.get("id")] = int(alvo)
    novos: dict[int, list[dict]] = {}
    for e in eventos or []:
        gs = gs_de_mg.get(e.get("usina_id"))
        if gs in usinas and e.get("tipo") in tipos:
            novos.setdefault(gs, []).append(e)
    if teste is not None:
        if not novos:
            teste.append("Nas últimas 24 h, nenhuma pessoa, veículo ou porta nas câmeras e centrais das usinas da regra.")
        for gs, evs in novos.items():
            oss = await _os_abertas(db, volta, dono, usinas[gs]) if com_os else []
            teste.append(f"{usinas[gs].nome}: {len(evs)} evento(s) de gente nas últimas 24 h (o último às "
                         f"{_hora(_ts(evs[0].get('aberto_em')))}); OS aberta agora: "
                         + ("não deu para conferir" if oss is None else _lista([_nome_os(o) for o in oss]) or "nenhuma"))
        return
    dia = volta.agora.astimezone(BRT).date().isoformat()
    for gs, evs in novos.items():
        link = usinas[gs]
        evs.sort(key=lambda e: str(e.get("aberto_em") or ""))
        e = evs[0]
        quando = _ts(e.get("aberto_em"))
        o_que = f"{_NOMES_GENTE.get(e.get('tipo'), e.get('tipo'))} na {e.get('camera') or 'câmera'}"
        if com_os:
            oss = await _os_abertas(db, volta, dono, link)
            if oss is None:
                await _disparar(db, regra, dono, evento="sem_dado", chave=f"semos:{link.id}:{dia}", link=link,
                                agora=volta.agora, texto=(f"Regra {regra.id} «{regra.nome}»: houve {o_que} em {link.nome} "
                                                          f"às {_hora(quando)}, mas não consegui conferir as OS no "
                                                          "meuPlano (sem o seu token de lá, ou ele não respondeu)."))
                continue
            for o in oss[:3]:
                await _disparar(db, regra, dono, evento="disparo", chave=f"cam:{link.id}:{o.get('id')}:{dia}", link=link,
                                agora=volta.agora, leitura={"evento": {k: e.get(k) for k in ("id", "tipo", "camera",
                                                                                            "aberto_em")}},
                                texto=(f"📷 {link.nome}: {o_que} às {_hora(quando)}, com a OS {o.get('id')} aberta "
                                       f"({_nome_os(o)})."))
        else:
            bloco = int(quando.timestamp() // 1800) if quando else 0     # no máximo um aviso a cada 30 min por usina
            await _disparar(db, regra, dono, evento="disparo", chave=f"cam:{link.id}:{bloco}", link=link,
                            agora=volta.agora, texto=f"📷 {link.nome}: {o_que} às {_hora(quando)}.",
                            leitura={"evento": {k: e.get(k) for k in ("id", "tipo", "camera", "aberto_em")}})
    _guardar_alvos(regra, alvos, teste)


def _nome_os(o: dict) -> str:
    from app.api.v1.manutencao import SITUACAO

    nome = o.get("name") or o.get("titulo") or o.get("title") or f"OS {o.get('id')}"
    st = SITUACAO.get(str(o.get("status") or ""), o.get("status"))
    return f"{nome}, {str(st).lower()}" if st else str(nome)


# ── horário e lembrete ──────────────────────────────────────────────────────


async def _avaliar_horario(db: Session, regra: Automacao, dono: User, volta: _Volta) -> None:
    g = regra.gatilho
    marcada = _utc(regra.proxima_em) or volta.agora
    atraso = volta.agora - marcada
    unica = g.get("tipo") == "uma_vez"
    seguinte = None if unica else proxima_execucao(g, max(marcada, volta.agora - timedelta(seconds=1)))
    if atraso > ATRASO_MAX and not unica:
        await _disparar(db, regra, dono, evento="perdida", chave=f"perdida:{marcada.isoformat()}", agora=volta.agora,
                        texto=(f"⚠️ A regra {regra.id} «{regra.nome}» era para {_hora(marcada)} e não rodou a tempo. "
                               f"A próxima é {_hora(seguinte, com_dia=True)}."))
    elif _condicoes_do_relogio(regra, volta.agora):
        texto = await texto_da_acao(db, regra, dono, volta, atrasada=marcada if atraso > timedelta(minutes=2) else None)
        if texto:
            await _disparar(db, regra, dono, evento="disparo", chave=f"h:{marcada.isoformat()}", agora=volta.agora,
                            texto=texto, rodape=not unica)
        else:                                              # nada saiu, e fica escrito por quê (nada sem registro)
            valores = "; ".join(volta.nao_valeu.get(regra.id) or []) or "a condição não valeu"
            db.add(AutomacaoDisparo(automacao_id=regra.id, user_id=dono.id, evento="nao_valeu",
                                    ensaio=regra.situacao == "ensaio", chave=f"nv:{marcada.isoformat()}",
                                    texto=f"A condição não valeu, nada foi mandado: {valores}.", status="simulada"))
            db.commit()
    if unica:
        regra.situacao = "concluida"
        regra.proxima_em = None
    else:
        regra.proxima_em = seguinte


async def texto_da_acao(db: Session, regra: Automacao, dono: User, volta: _Volta,
                        atrasada: datetime | None = None, teste: bool = False) -> str | None:
    """O texto da ação da regra de horário. None = a condição não deixou (nada sai). Sem dado na condição, o aviso diz."""
    a = regra.acao or {}
    tipo = a.get("tipo") or "mensagem"
    if tipo == "mensagem":
        texto = f"⏰ Lembrete: {a.get('texto') or regra.nome}"
        return texto + (f" (era para {_hora(atrasada)})" if atrasada else "")
    usinas = [u for u in usinas_da_regra(db, regra, dono) if u.mw_plant_slug]
    if not usinas:
        return (f"Regra {regra.id} «{regra.nome}»: nenhuma usina desta regra está no seu recorte com monitoramento, "
                "então não há o que mandar.")
    usinas, notas = await _usinas_que_passam(db, regra, dono, volta, usinas)
    if not usinas:
        return None if not notas else f"Regra {regra.id} «{regra.nome}»: " + " ".join(notas)
    if tipo == "resumo_geracao":
        corpo = await resumo_geracao(db, volta, dono, usinas)
    elif tipo == "ia":
        corpo = await _rodar_ia(db, regra, dono, usinas, teste=teste)
    else:
        raise RegraInvalida(f"ação desconhecida: {tipo}")
    return (corpo + ("\n\n" + " ".join(notas) if notas else "")
            + (f"\n\n(era para {_hora(atrasada)}; atrasou)" if atrasada else ""))


async def _usinas_que_passam(db: Session, regra: Automacao, dono: User, volta: _Volta,
                             usinas: list[PlantLink]) -> tuple[list[PlantLink], list[str]]:
    """As usinas em que a condição POR USINA vale (PR do dia, OS aberta). Sem dado, a usina fica de fora e a nota diz."""
    conds = [c for c in regra.condicoes or [] if c.get("tipo") in ("pr_dia", "os_aberta")]
    if not conds:
        return usinas, []
    passam, notas = [], []
    for u in usinas:
        ok = True
        for c in conds:
            if c["tipo"] == "pr_dia":
                try:
                    mon = await _ler(db, volta, dono, "monitoramento", u.mw_plant_slug)
                except _Cega as e:
                    notas.append(f"{u.nome}: não li o PR do dia ({e}).")
                    ok = False
                    break
                pr = (mon or {}).get("plant_pr_today")
                if not isinstance(pr, (int, float)):
                    notas.append(f"{u.nome}: sem PR hoje (o meuWatt não calcula sem estação ou com pouco dado).")
                    ok = False
                    break
                limite = float(c.get("limite") or 0)
                if not (pr * 100 < limite if (c.get("operador") or "<") == "<" else pr * 100 > limite):
                    volta.nao_valeu.setdefault(regra.id, []).append(
                        f"{u.nome}: PR {_n(pr * 100, 0)}% (limite {_n(limite, 0)}%)")
                    ok = False
                    break
            elif c["tipo"] == "os_aberta":
                oss = await _os_abertas(db, volta, dono, u)
                if not oss:
                    if oss is None:
                        notas.append(f"{u.nome}: não consegui conferir as OS no meuPlano.")
                    else:
                        volta.nao_valeu.setdefault(regra.id, []).append(f"{u.nome}: nenhuma OS aberta")
                    ok = False
                    break
        if ok:
            passam.append(u)
    return passam, notas


async def resumo_geracao(db: Session, volta: _Volta, dono: User, usinas: list[PlantLink]) -> str:
    """A função fixa: a geração de hoje de cada usina, sem IA, com o mesmo dado das telas e a hora dele."""
    from app.services import avisos

    linhas = []
    for u in usinas:
        try:
            mon = await _ler(db, volta, dono, "monitoramento", u.mw_plant_slug)
        except _Cega as e:
            linhas.append(f"• {u.nome}: sem dados ({e})")
            continue
        e = (mon or {}).get("energy_today_kwh")
        kwp = (mon or {}).get("capacity_kwp") or u.kwp
        pr = (mon or {}).get("plant_pr_today")
        quando = _ts((mon or {}).get("data_at"))
        partes = []
        if isinstance(e, (int, float)):
            partes.append(f"{_n(e, 0)} kWh")
            if isinstance(kwp, (int, float)) and kwp:
                partes.append(f"{_n(e / kwp, 2)} kWh/kWp")
        else:
            partes.append("sem dados de energia")
        if isinstance(pr, (int, float)):
            partes.append(f"PR {_n(pr * 100, 0)}%")
        parados = avisos._parados(mon)
        if parados:
            partes.append(f"{len(parados)} inversor{'es' if len(parados) > 1 else ''} parado{'s' if len(parados) > 1 else ''}")
        if quando is not None and volta.agora - quando > CEGA["monitoramento"]:
            partes.append(f"dado das {_hora(quando)}")
        linhas.append(f"• {u.nome}: " + " · ".join(partes))
    hoje = volta.agora.astimezone(BRT).strftime("%d/%m")
    return f"☀️ Geração de hoje ({hoje}, {_hora(volta.agora)}):\n" + "\n".join(linhas)


def _ia_hoje(db: Session, dono: User, agora: datetime) -> int:
    ids = [r.id for r in db.scalars(select(Automacao).where(Automacao.user_id == dono.id))
           if (r.acao or {}).get("tipo") == "ia"]
    if not ids:
        return 0
    inicio = datetime.combine(_utc(agora).astimezone(BRT).date(), dtime(0), tzinfo=BRT).astimezone(UTC)
    return int(db.scalar(select(func.count(AutomacaoDisparo.id)).where(
        AutomacaoDisparo.automacao_id.in_(ids), AutomacaoDisparo.em >= inicio,
        AutomacaoDisparo.evento.in_(("disparo", "teste")))) or 0)


AVISO_AUTOMACAO = ("\n\n[sistema] Esta mensagem é uma AUTOMAÇÃO que a própria pessoa agendou, não um pedido dela agora: "
                   "consulte as ferramentas de leitura e responda o pedido abaixo em até 12 linhas. Não proponha nenhuma "
                   "ação, não faça pergunta e não fale da automação.")


async def _rodar_ia(db: Session, regra: Automacao, dono: User, usinas: list[PlantLink], teste: bool = False) -> str:
    from app.services import assistente, assistente_geracao as ger

    if dono.perfil not in EQUIPE:
        raise RegraInvalida("a análise da IA nas automações é da equipe da O&M")
    if _ia_hoje(db, dono, _agora()) >= IA_POR_DIA:
        raise RegraInvalida(f"passou de {IA_POR_DIA} análises da IA hoje; volta amanhã")
    ctx = ger.Contexto(db=db, user=dono, telefone=dono.telefone or "", automacao=True)
    await ger.preparar(ctx)
    nomes = ", ".join(u.nome for u in usinas)
    pedido = f"{(regra.acao or {}).get('prompt') or regra.nome}\n\nUsinas: {nomes}."
    ctx.pedido = pedido
    texto = await assistente.responder(ctx, [{"role": "user", "content": pedido}], aviso=AVISO_AUTOMACAO)
    return f"🤖 {regra.nome}\n\n{assistente.para_whatsapp(texto)}"


# ── teste ("testa a regra") ─────────────────────────────────────────────────


async def testar(db: Session, regra: Automacao) -> str:
    """O que a regra faria AGORA, sem mandar nada nem mexer no estado dela (a pessoa vê antes de ligar)."""
    dono = db.get(User, regra.user_id)
    volta = _Volta(agora=_agora())
    tipo = (regra.gatilho or {}).get("tipo")
    try:
        if tipo in ("horario", "uma_vez"):
            texto = await texto_da_acao(db, regra, dono, volta, teste=True)
            saida = ("Agora sairia:\n\n" + texto) if texto else "Agora não sairia nada: a condição não vale."
        else:
            linhas: list[str] = []
            if tipo == "leitura":
                await _avaliar_leitura(db, regra, dono, volta, teste=linhas)
            else:
                await _avaliar_camera(db, regra, dono, volta, teste=linhas)
            saida = "Agora:\n" + "\n".join(f"• {ln}" for ln in linhas) if linhas else "Agora não há leitura para mostrar."
    except (_Cega, RegraInvalida) as e:
        saida = f"Não deu para testar: {e}."
    except _Adiar:
        saida = "O motor está ocupado com outras leituras: tente de novo em um minuto."
    db.add(AutomacaoDisparo(automacao_id=regra.id, user_id=dono.id, evento="teste", ensaio=regra.situacao == "ensaio",
                            chave=f"teste:{volta.agora.isoformat()}", texto=saida, status="simulada"))
    db.commit()
    return f"[teste da regra {regra.id}] {saida}"


# ── entrega ─────────────────────────────────────────────────────────────────


def na_janela(db: Session, user: User, agora: datetime | None = None) -> bool:
    """Texto livre no WhatsApp só até 23h50 depois da última mensagem DA PESSOA. O aviso automático não conta."""
    from app.models.conversa_whatsapp import RegistroBot

    if not user.telefone:
        return False
    ultima = db.scalar(select(func.max(RegistroBot.em)).where(RegistroBot.gs_user_id == user.id,
                                                             RegistroBot.resultado != "automacao"))
    return ultima is not None and (agora or _agora()) - _utc(ultima) < JANELA


async def _disparar(db: Session, regra: Automacao, dono: User, *, evento: str, chave: str, texto: str,
                    agora: datetime, link: PlantLink | None = None, leitura: dict | None = None,
                    rodape: bool = True) -> AutomacaoDisparo | None:
    """Grava o disparo (a única: o mesmo evento não sai duas vezes) e entrega. Em ensaio, só o 1º sai ao dono."""
    ensaio = regra.situacao == "ensaio"
    d = AutomacaoDisparo(automacao_id=regra.id, user_id=dono.id, plant_link_id=link.id if link else None,
                         evento=evento, ensaio=ensaio, chave=chave[:200], texto=texto, leitura=leitura,
                         status="pendente")
    db.add(d)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    saida = texto
    if rodape and evento in ("disparo", "voltou") and (regra.gatilho or {}).get("tipo") != "uma_vez":
        saida += f"\n\n_Regra {regra.id} · para pausar, diga «pausa a regra {regra.id}»._"
    if ensaio:
        if (regra.estado or {}).get("ensaio_mandado"):
            d.status = "simulada"
            db.commit()
            return d
        regra.estado = {**(regra.estado or {}), "ensaio_mandado": True}
        saida = (f"[ensaio] {saida}\n\nA regra {regra.id} está em ensaio: os próximos avisos ficam só no registro. "
                 f"Se ficou bom, diga «liga a regra {regra.id}».")
    await _entregar(db, regra, dono, d, saida, agora)
    return d


async def _entregar(db: Session, regra: Automacao, dono: User, d: AutomacaoDisparo, texto: str, agora: datetime) -> None:
    from app.services import avisos, push

    canais = list((regra.entrega or {}).get("canais") or ["whatsapp", "push"])
    saiu, erros = [], []
    if "whatsapp" in canais and na_janela(db, dono, agora):
        ok, erro = await _whatsapp(db, regra, dono, d, texto)
        (saiu if ok else erros).append("whatsapp" if ok else erro)
    tokens = avisos.tokens_do_usuario(db, dono)
    if tokens and ("push" in canais or not saiu):
        titulo = (f"{db.get(PlantLink, d.plant_link_id).nome} · " if d.plant_link_id else "") + regra.nome
        corpo = re.sub(r"[_*]", "", texto.split("\n\n_Regra")[0])
        try:
            r = await push.enviar(tokens, titulo[:80], corpo[:300], {"tipo": "automacao", "automacao_id": regra.id,
                                                                     "disparo_id": d.id})
            if r.invalidos:
                from app.models.permissao import Dispositivo
                db.execute(delete(Dispositivo).where(Dispositivo.token.in_(r.invalidos)))
            if r.enviados:
                saiu.append("push")
            elif r.erros:
                erros.append("push: " + "; ".join(r.erros)[:200])
        except Exception as e:                             # noqa: BLE001 — o Expo fora não derruba a volta
            erros.append(f"push: {type(e).__name__}")
    if saiu:
        d.status, d.canal, d.entregue_em = "enviada", "+".join(saiu), agora
    elif dono.telefone and not erros:
        d.status, d.canal = "adiada", "adiado"           # sai na próxima mensagem dele (até 24 h)
    else:
        d.status, d.canal = "falhou", "nenhum"
        d.erro = "; ".join(erros) or "sem celular no Gestão Solar e sem o aplicativo com aviso"
    db.commit()


async def _whatsapp(db: Session, regra: Automacao, dono: User, d: AutomacaoDisparo, texto: str) -> tuple[bool, str]:
    """Texto livre (dentro da janela), em pedaços de 3.900; a linha de envio guarda o id da Meta para o status voltar;
    o aviso entra na conversa (para a resposta dele ter contexto) e no Log do bot (resultado próprio)."""
    from app.clients import whatsapp as gw
    from app.models.notificacao import NotificacaoEnviada
    from app.services import assistente

    ok, wamid, erro = True, None, ""
    try:
        for i in range(0, len(texto), 3900):
            r = await gw.enviar_conteudo(telefone=dono.telefone, tipo="text", texto=texto[i:i + 3900],
                                         origem=f"automacao:{regra.id}")
            ok = ok and bool((r or {}).get("ok"))
            wamid = wamid or (r or {}).get("wamid")
            erro = erro or str((r or {}).get("erro") or "")
    except Exception as e:                                 # noqa: BLE001 — gateway fora: tenta o push
        ok, erro = False, f"whatsapp: {type(e).__name__}"
    n = NotificacaoEnviada(user_id=dono.id, tipo="automacao", chave=f"auto:{regra.id}:{d.id}",
                           plant_link_id=d.plant_link_id, canal="whatsapp", destino=dono.telefone,
                           status="enviada" if ok else "falhou", wamid=wamid, erro=None if ok else erro[:500],
                           status_em=_agora())
    db.add(n)
    db.commit()
    d.notificacao_id = n.id
    if ok:
        await assistente.aviso_na_conversa(db, dono, f"[aviso automático · regra {regra.id} «{regra.nome}»] {texto}")
    return ok, erro or "whatsapp: a Meta recusou"


async def entregar_adiadas(db: Session, user: User) -> int:
    """Na próxima mensagem da pessoa (a janela abriu): os avisos que esperaram saem ANTES da resposta, numa mensagem só,
    e entram na conversa. Os que passaram de 24 h vencem, e a mensagem diz quantos."""
    from app.clients import whatsapp as gw
    from app.services import assistente

    agora = _agora()
    esperando = list(db.scalars(select(AutomacaoDisparo).where(AutomacaoDisparo.user_id == user.id,
                                                               AutomacaoDisparo.status == "adiada")
                                .order_by(AutomacaoDisparo.id)).all())
    if not esperando or not user.telefone:
        return 0
    validos, vencidos = [], []
    for d in esperando:
        (validos if agora - _utc(d.em) <= ADIADA_VALE else vencidos).append(d)
    for d in vencidos:
        d.status = "venceu"
    partes = [f"({_hora(d.em, com_dia=True)}) {d.texto}" for d in validos]
    if vencidos:
        partes.append(f"Ficaram {len(vencidos)} aviso{'s' if len(vencidos) > 1 else ''} que venceram sem chegar "
                      f"(o mais antigo de {_hora(vencidos[0].em, com_dia=True)}): veja com «quais regras eu tenho».")
    texto = "📬 Avisos que esperaram você falar comigo:\n\n" + "\n\n".join(partes)
    try:
        ok = True
        for i in range(0, len(texto), 3900):
            r = await gw.enviar_conteudo(telefone=user.telefone, tipo="text", texto=texto[i:i + 3900],
                                         origem="automacao:adiadas")
            ok = ok and bool((r or {}).get("ok"))
    except Exception:                                      # noqa: BLE001
        ok = False
    for d in validos:
        d.status = "entregue" if ok else "adiada"
        d.canal = "whatsapp" if ok else d.canal
        d.entregue_em = agora if ok else None
    db.commit()
    if ok:
        await assistente.aviso_na_conversa(db, user, f"[avisos automáticos guardados] {texto}", travar=False)
    return len(validos)
