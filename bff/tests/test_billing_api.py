"""As mensalidades pelo HTTP: quem enxerga o quê, e que cor o resumo ganha.

O risco aqui é diferente do das usinas. Uma usina vazada mostra geração; uma fatura
vazada mostra **valor de contrato** — quanto o vizinho paga, e portanto o tamanho do
desconto que ele conseguiu. Por isso o teste de escopo vem primeiro.

O segundo risco é o resumo mentir por otimismo: três parcelas pagas e uma vencida têm de
resultar em "vencido", nunca em "em dia".
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.main import app
from app.models.billing import Invoice, Produto, Subscription
from app.models.user import Perfil, User

HOJE = date.today()


@pytest.fixture
def cliente_http(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _dono(db, apelido: str) -> User:
    u = User(
        apelido=apelido,
        nome=f"Dono {apelido}",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


def _assina(db, usuario: User, produto: Produto = Produto.MEUWATT, valor=1200) -> Subscription:
    s = Subscription(
        user_id=usuario.id,
        produto=produto,
        valor_mensal=valor,
        dia_vencimento=5,
        inicio=date(2026, 1, 1),
    )
    db.add(s)
    db.commit()
    return s


def _fatura(db, assinatura: Subscription, competencia: str, vencimento: date, pago_em=None):
    f = Invoice(
        subscription_id=assinatura.id,
        competencia=competencia,
        valor=assinatura.valor_mensal,
        vencimento=vencimento,
        pago_em=pago_em,
    )
    db.add(f)
    db.commit()
    return f


def _como(cliente, usuario):
    token, _ = criar_token(usuario.id)
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente


# ── escopo ──────────────────────────────────────────────────────────────────


def test_sem_token_nao_abre(cliente_http):
    assert cliente_http.get("/api/v1/billing").status_code in (401, 403)


def test_ve_apenas_as_proprias_assinaturas(cliente_http, db):
    eu, outro = _dono(db, "eu"), _dono(db, "outro")
    _assina(db, eu, Produto.MEUWATT, valor=1200)
    _assina(db, outro, Produto.MEUPLANO, valor=9999)

    r = _como(cliente_http, eu).get("/api/v1/billing")

    assert r.status_code == 200
    corpo = r.json()
    assert [a["produto"] for a in corpo["assinaturas"]] == ["meuwatt"]
    assert corpo["total_mensal"] == 1200
    assert "9999" not in r.text, "o valor do contrato alheio não pode aparecer"


def test_fatura_de_outro_cliente_responde_404(cliente_http, db):
    eu, outro = _dono(db, "eu"), _dono(db, "outro")
    dele = _fatura(db, _assina(db, outro), "2026-08", HOJE)

    r = _como(cliente_http, eu).get(f"/api/v1/billing/invoices/{dele.id}")

    assert r.status_code == 404


def test_fatura_inexistente_responde_igual_a_alheia(cliente_http, db):
    eu, outro = _dono(db, "eu"), _dono(db, "outro")
    dele = _fatura(db, _assina(db, outro), "2026-08", HOJE)

    cliente = _como(cliente_http, eu)
    alheia = cliente.get(f"/api/v1/billing/invoices/{dele.id}")
    fantasma = cliente.get("/api/v1/billing/invoices/999999")

    assert alheia.status_code == fantasma.status_code
    assert alheia.json()["detail"] == fantasma.json()["detail"]


def test_propria_fatura_abre(cliente_http, db):
    eu = _dono(db, "eu")
    minha = _fatura(db, _assina(db, eu), "2026-08", HOJE)

    r = _como(cliente_http, eu).get(f"/api/v1/billing/invoices/{minha.id}")

    assert r.status_code == 200
    assert r.json()["id"] == minha.id


# ── o resumo ────────────────────────────────────────────────────────────────


def test_conta_sem_assinatura_explica_em_vez_de_ficar_vazia(cliente_http, db):
    r = _como(cliente_http, _dono(db, "novo")).get("/api/v1/billing")

    assert r.status_code == 200
    assert r.json()["assinaturas"] == []
    assert "Nenhuma assinatura" in r.json()["resumo"]


def test_uma_vencida_manda_no_resumo_mesmo_com_outras_pagas(cliente_http, db):
    """A regressão que importa: o resumo não pode arredondar para o otimismo."""
    eu = _dono(db, "eu")
    a = _assina(db, eu)
    _fatura(db, a, "2026-06", HOJE - timedelta(days=70), pago_em=HOJE - timedelta(days=70))
    _fatura(db, a, "2026-07", HOJE - timedelta(days=40), pago_em=HOJE - timedelta(days=40))
    _fatura(db, a, "2026-08", HOJE - timedelta(days=10))  # vencida

    corpo = _como(cliente_http, eu).get("/api/v1/billing").json()

    assert corpo["situacao"] == "vencido"
    assert corpo["tom"] == "parado"
    assert corpo["total_vencido"] == 1200


def test_dias_de_atraso_acompanham_a_vencida(cliente_http, db):
    eu = _dono(db, "eu")
    _fatura(db, _assina(db, eu), "2026-08", HOJE - timedelta(days=12))

    corpo = _como(cliente_http, eu).get("/api/v1/billing").json()
    vencida = next(f for f in corpo["historico"] if f["situacao"] == "vencido")

    assert vencida["dias_atraso"] == 12


def test_tudo_pago_fica_em_dia(cliente_http, db):
    eu = _dono(db, "eu")
    a = _assina(db, eu)
    _fatura(db, a, "2026-07", HOJE - timedelta(days=40), pago_em=HOJE - timedelta(days=41))

    corpo = _como(cliente_http, eu).get("/api/v1/billing").json()

    assert corpo["situacao"] == "em_dia"
    assert corpo["tom"] == "ok"
    assert corpo["total_vencido"] == 0


def test_todo_tom_da_fatura_existe_nos_tokens_do_aplicativo():
    """Mesma régua das usinas: o nome do tom é chave de `tons` em tokens.ts. Um nome que
    não existe lá não pinta cor errada — não pinta cor nenhuma."""
    import re
    from pathlib import Path

    from app.api.v1.billing import TOM_DA_SITUACAO

    tokens = Path(__file__).resolve().parents[2] / "app" / "src" / "theme" / "tokens.ts"
    bloco = re.search(r"export const tons = \{(.*?)\n\}", tokens.read_text("utf-8"), re.S)
    conhecidos = set(re.findall(r"^\s*(\w+):", bloco.group(1), re.M))

    faltando = set(TOM_DA_SITUACAO.values()) - conhecidos
    assert not faltando, f"tons sem cor no app: {sorted(faltando)}"
