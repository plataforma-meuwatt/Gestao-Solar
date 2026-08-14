"""Mensalidades do dono da usina.

Este é o único módulo do BFF que não agrega ninguém: assinatura de produto não existe no
meuWatt nem no meuPlano, e nasce aqui. O `financeiro` do meuPlano é contas a pagar
interno, e o `client/financeiro` cobra contrato de O&M — nenhum dos dois responde "o
cliente está em dia com o Gestão Solar?".

Duas regras de desenho que não devem ser desfeitas:

**A situação é derivada, nunca gravada.** `Invoice.situacao()` calcula a partir de
`pago_em` e `vencimento` a cada leitura. Guardar em coluna criaria o clássico: a parcela
vira "vencida" à meia-noite e ninguém roda o job que atualiza a coluna, então a tela mente
até alguém reclamar.

**O aplicativo informa, não recebe.** Não há gateway; a baixa é do gestor, no painel. Por
isso toda rota aqui é de leitura, e a tela diz de quem é a ação — sem isso o dono fica
procurando o botão de pagar que não existe.
"""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.datas import hoje as hoje_na_usina
from app.core.db import get_db
from app.core.security import usuario_atual
from app.models.billing import Invoice, SituacaoFatura, Subscription
from app.models.user import User

router = APIRouter(prefix="/api/v1", tags=["app · financeiro"])


NOME_DO_PRODUTO = {"meuwatt": "meuWatt", "meuplano": "meuPlano"}
#: O que o cliente está pagando, na língua dele — não "assinatura meuwatt".
O_QUE_FORNECE = {"meuwatt": "Monitoramento da geração", "meuplano": "Manutenção e O&M"}

#: `pago` · `a_vencer` · `em_aberto` · `vencido` → chaves de `tons` em tokens.ts.
TOM_DA_SITUACAO = {
    SituacaoFatura.PAGO: "ok",
    SituacaoFatura.A_VENCER: "alerta",
    SituacaoFatura.EM_ABERTO: "semDados",
    SituacaoFatura.VENCIDO: "parado",
}


def _reais(valor: Decimal | float | None) -> float:
    """`Numeric` volta como `Decimal`, que o JSON não serializa. A conversão é aqui, num
    lugar só, e não espalhada por cada campo de cada resposta."""
    return float(valor or 0)


class FaturaOut(BaseModel):
    id: int
    produto: str
    produto_nome: str
    competencia: str  # YYYY-MM
    valor: float
    vencimento: date
    pago_em: date | None = None
    situacao: str
    tom: str
    #: Preenchido só quando há atraso — a tela usa para dizer "vencida há 12 dias".
    dias_atraso: int | None = None
    comprovante_url: str | None = None


class AssinaturaOut(BaseModel):
    id: int
    produto: str
    produto_nome: str
    fornece: str
    valor_mensal: float
    dia_vencimento: int
    ativo: bool
    competencia_atual: FaturaOut | None = None


class FinanceiroOut(BaseModel):
    #: `em_dia` · `a_vencer` · `vencido` — o resumo que decide a cor do card do topo.
    situacao: str
    tom: str
    resumo: str

    assinaturas: list[AssinaturaOut]
    historico: list[FaturaOut]

    #: Soma das assinaturas ativas: o que ele paga por mês.
    total_mensal: float
    #: Soma do que está vencido. Zero quando em dia.
    total_vencido: float
    proximo_vencimento: date | None = None

    #: Quem resolve. Fica no contrato e não na tela porque é regra de negócio, e mudaria
    #: junto com o produto — não com o aplicativo.
    rodape: str = (
        "A baixa das mensalidades é feita pela administração. "
        "Este aplicativo informa a situação, não recebe pagamento."
    )


def _fatura_out(f: Invoice, produto: str, hoje: date) -> FaturaOut:
    situacao = f.situacao(hoje)
    atraso = (hoje - f.vencimento).days if situacao is SituacaoFatura.VENCIDO else None
    return FaturaOut(
        id=f.id,
        produto=produto,
        produto_nome=NOME_DO_PRODUTO.get(produto, produto),
        competencia=f.competencia,
        valor=_reais(f.valor),
        vencimento=f.vencimento,
        pago_em=f.pago_em,
        situacao=situacao.value,
        tom=TOM_DA_SITUACAO[situacao],
        dias_atraso=atraso,
        comprovante_url=f.comprovante_url,
    )


def _assinaturas_do_usuario(db: Session, usuario: User) -> list[Subscription]:
    return list(
        db.scalars(
            select(Subscription)
            .options(selectinload(Subscription.faturas))
            .where(Subscription.user_id == usuario.id)
            .order_by(Subscription.produto)
        ).all()
    )


@router.get("/billing", response_model=FinanceiroOut)
def meu_financeiro(
    db: Session = Depends(get_db), usuario: User = Depends(usuario_atual)
) -> FinanceiroOut:
    """A situação das mensalidades desta pessoa.

    O que o dono quer saber, nesta ordem: devo alguma coisa, quanto e quando vence. O
    resumo do topo responde as três antes de ele rolar a tela.
    """
    hoje = hoje_na_usina()
    assinaturas = _assinaturas_do_usuario(db, usuario)

    if not assinaturas:
        return FinanceiroOut(
            situacao="em_dia",
            tom="semDados",
            resumo="Nenhuma assinatura cadastrada para esta conta.",
            assinaturas=[],
            historico=[],
            total_mensal=0,
            total_vencido=0,
        )

    saida: list[AssinaturaOut] = []
    historico: list[FaturaOut] = []
    vencidas: list[FaturaOut] = []
    proximos: list[date] = []

    competencia_de_hoje = hoje.strftime("%Y-%m")

    for a in assinaturas:
        produto = a.produto.value if hasattr(a.produto, "value") else str(a.produto)
        faturas = sorted(a.faturas, key=lambda f: f.competencia, reverse=True)

        atual = next((f for f in faturas if f.competencia == competencia_de_hoje), None)
        atual_out = _fatura_out(atual, produto, hoje) if atual else None

        for f in faturas:
            fo = _fatura_out(f, produto, hoje)
            historico.append(fo)
            if fo.situacao == SituacaoFatura.VENCIDO.value:
                vencidas.append(fo)
            elif fo.pago_em is None:
                proximos.append(fo.vencimento)

        saida.append(
            AssinaturaOut(
                id=a.id,
                produto=produto,
                produto_nome=NOME_DO_PRODUTO.get(produto, produto),
                fornece=O_QUE_FORNECE.get(produto, ""),
                valor_mensal=_reais(a.valor_mensal),
                dia_vencimento=a.dia_vencimento,
                ativo=a.ativo,
                competencia_atual=atual_out,
            )
        )

    historico.sort(key=lambda f: (f.competencia, f.produto), reverse=True)
    total_mensal = sum(a.valor_mensal for a in saida if a.ativo)
    total_vencido = sum(f.valor for f in vencidas)

    # A pior situação manda no card: uma parcela vencida importa mais do que três pagas.
    if vencidas:
        situacao, tom = "vencido", "parado"
        n = len(vencidas)
        resumo = (
            f"{n} mensalidade{'s' if n > 1 else ''} vencida{'s' if n > 1 else ''}"
            f" · R$ {total_vencido:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
    elif any(
        a.competencia_atual and a.competencia_atual.situacao == SituacaoFatura.A_VENCER.value
        for a in saida
    ):
        situacao, tom = "a_vencer", "alerta"
        resumo = "Você tem mensalidade a vencer nos próximos dias."
    else:
        situacao, tom = "em_dia", "ok"
        resumo = "Tudo em dia."

    return FinanceiroOut(
        situacao=situacao,
        tom=tom,
        resumo=resumo,
        assinaturas=saida,
        historico=historico[:24],  # dois anos; além disso a tela vira arquivo, não resumo
        total_mensal=total_mensal,
        total_vencido=total_vencido,
        proximo_vencimento=min(proximos) if proximos else None,
    )


@router.get("/billing/invoices/{invoice_id}", response_model=FaturaOut)
def minha_fatura(
    invoice_id: int,
    db: Session = Depends(get_db),
    usuario: User = Depends(usuario_atual),
) -> FaturaOut:
    """Detalhe de uma mensalidade.

    O `join` com `Subscription` não é otimização: é a autorização. Sem ele, trocar o
    número na URL mostraria a fatura de outro cliente — e fatura carrega valor, e valor
    diz o tamanho do contrato do vizinho.
    """
    fatura = db.scalars(
        select(Invoice)
        .join(Subscription, Subscription.id == Invoice.subscription_id)
        .where(Invoice.id == invoice_id, Subscription.user_id == usuario.id)
    ).first()

    if fatura is None:
        # 404 e não 403, como nas usinas: negar não pode confirmar que existe.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mensalidade não encontrada.")

    produto = fatura.assinatura.produto
    return _fatura_out(fatura, produto.value if hasattr(produto, "value") else str(produto), hoje_na_usina())
