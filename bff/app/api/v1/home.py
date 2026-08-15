"""A primeira tela do aplicativo.

É a que abre quando o dono toca no ícone, e por isso é a que decide se ele confia no que
vê. Até aqui ela mostrava números escritos à mão — potência, meta do mês, inversores
parados numa usina que o cliente talvez nem tenha. Nada disso vinha de servidor nenhum.

O princípio aqui é o oposto do que estava: **nenhum número aparece sem origem**. Onde o
dado não existe, o campo vem nulo e a tela omite o bloco — uma tela mais curta e honesta
vale mais do que uma completa e inventada.

Tudo o que este módulo devolve é agregado do que já está no ar (`/api/v1/plants` e
`/api/v1/billing`), somando o que já foi buscado em vez de reconsultar os upstreams.
"""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.billing import _assinaturas_do_usuario
from app.api.v1.plants import UsinaOut, listar_usinas
from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.billing import SituacaoFatura
from app.models.user import User

router = APIRouter(prefix="/api/v1", tags=["app · início"])


class AtencaoOut(BaseModel):
    """O que está pedindo olho agora. Nulo quando não há nada — e aí a tela não desenha
    faixa nenhuma, em vez de inventar um problema."""

    tom: str
    titulo: str
    detalhe: str | None = None
    #: Para onde levar o toque: a usina em questão.
    plant_id: int | None = None


class ResumoFinanceiroOut(BaseModel):
    situacao: str
    tom: str
    resumo: str
    proximo_vencimento: date | None = None
    total: float | None = None


class InicioOut(BaseModel):
    saudacao: str
    primeiro_nome: str
    atualizado_em: datetime

    #: Agora, somado das usinas que responderam. Nulo = nenhuma respondeu.
    potencia_agora_kw: float | None = None
    capacidade_total_kwp: float | None = None
    pct_capacidade: int | None = None
    energia_hoje_kwh: float | None = None

    usinas: int
    usinas_com_dado: int

    atencao: AtencaoOut | None = None
    financeiro: ResumoFinanceiroOut | None = None

    #: Por que algum número não veio. A tela mostra como faixa discreta.
    aviso: str | None = None


def _saudacao(agora: datetime) -> str:
    """Bom dia / boa tarde / boa noite pelo horário de Brasília.

    A hora do servidor é UTC; sem o deslocamento, um acesso às 21h no Brasil seria saudado
    com "bom dia" — pequeno, mas é a primeira frase que a pessoa lê.
    """
    hora = (agora.hour - 3) % 24
    if 5 <= hora < 12:
        return "Bom dia"
    if 12 <= hora < 18:
        return "Boa tarde"
    return "Boa noite"


def _atencao(usinas: list[UsinaOut]) -> AtencaoOut | None:
    """A pior situação entre as usinas, ou nada.

    Uma faixa vermelha que não corresponde a problema real é pior do que nenhuma faixa: da
    segunda vez que o dono abrir e não encontrar nada de errado, ele para de olhar.
    """
    paradas = [u for u in usinas if u.tom == "parado"]
    if paradas:
        u = paradas[0]
        resto = f" e mais {len(paradas) - 1}" if len(paradas) > 1 else ""
        return AtencaoOut(
            tom="parado",
            titulo=f"{u.nome}{resto} com problema",
            detalhe=u.situacao,
            plant_id=u.id,
        )

    sem_dado = [u for u in usinas if u.tom == "semDados" and u.situacao == "Sem comunicação"]
    if sem_dado:
        n = len(sem_dado)
        return AtencaoOut(
            tom="semDados",
            titulo=f"{n} usina{'s' if n > 1 else ''} sem comunicação",
            detalhe="Os números podem estar desatualizados.",
            plant_id=sem_dado[0].id,
        )

    alertas = [u for u in usinas if u.tom == "alerta"]
    if alertas:
        u = alertas[0]
        return AtencaoOut(tom="alerta", titulo=u.nome, detalhe=u.situacao, plant_id=u.id)

    return None


@router.get("/home", response_model=InicioOut)
async def inicio(
    db: Session = Depends(get_db), usuario: User = Depends(usuario_atual)
) -> InicioOut:
    """O resumo do dia, agregado do que já existe.

    Chama `listar_usinas` em vez de refazer as consultas: o número do topo tem de ser
    exatamente a soma do que a aba Usinas mostra. Calculados em dois lugares, os dois
    divergiriam no dia em que alguém mudasse um deles — e a tela mais visível do
    aplicativo passaria a se contradizer.
    """
    agora = datetime.now(UTC)
    lista = await listar_usinas(db=db, usuario=usuario)

    capacidade = round(sum(u.capacidade_kwp or 0 for u in lista.usinas), 2) or None
    # Mesma base do card de cada usina: a capacidade impressa. Calculado de outro jeito, o
    # topo do Início discordaria da aba Usinas sobre o mesmo conjunto de usinas.
    pct = None
    if lista.potencia_agora_kw is not None and capacidade:
        pct = max(0, min(100, round(lista.potencia_agora_kw / capacidade * 100)))

    financeiro = None
    assinaturas = _assinaturas_do_usuario(db, usuario)
    if assinaturas:
        hoje = hoje_na_usina()
        abertas = [
            f
            for a in assinaturas
            for f in a.faturas
            if f.situacao(hoje) is not SituacaoFatura.PAGO
        ]
        vencidas = [f for f in abertas if f.situacao(hoje) is SituacaoFatura.VENCIDO]
        if vencidas:
            financeiro = ResumoFinanceiroOut(
                situacao="vencido",
                tom="parado",
                resumo=f"{len(vencidas)} mensalidade(s) vencida(s)",
                proximo_vencimento=min(f.vencimento for f in vencidas),
                total=float(sum(f.valor for f in vencidas)),
            )
        elif abertas:
            proxima = min(abertas, key=lambda f: f.vencimento)
            financeiro = ResumoFinanceiroOut(
                situacao="em_dia",
                tom="ok",
                resumo="Em dia",
                proximo_vencimento=proxima.vencimento,
                total=float(proxima.valor),
            )
        else:
            financeiro = ResumoFinanceiroOut(situacao="em_dia", tom="ok", resumo="Em dia")

    nome = (usuario.nome or usuario.apelido or "").strip()
    return InicioOut(
        saudacao=_saudacao(agora),
        primeiro_nome=nome.split(" ")[0] if nome else "",
        # O horário do DADO, não o da resposta: é ele que a tela carimba no selo.
        atualizado_em=lista.medido_em or lista.atualizado_em,
        potencia_agora_kw=lista.potencia_agora_kw,
        capacidade_total_kwp=capacidade,
        pct_capacidade=pct,
        energia_hoje_kwh=lista.energia_hoje_kwh,
        usinas=len(lista.usinas),
        usinas_com_dado=sum(1 for u in lista.usinas if u.potencia_kw is not None),
        atencao=_atencao(lista.usinas),
        financeiro=financeiro,
        aviso=lista.aviso,
    )
