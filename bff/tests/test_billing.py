"""A situação da fatura é derivada, nunca gravada — então é o único lugar do modelo com
regra de verdade, e é o que este teste cobre."""

from datetime import date

from app.models.billing import Invoice, SituacaoFatura


def _fatura(vencimento: date, pago_em: date | None = None) -> Invoice:
    return Invoice(competencia="2026-08", valor=1200, vencimento=vencimento, pago_em=pago_em)


def test_pago_vence_tudo():
    # Pago depois do vencimento continua pago — não é "vencido".
    f = _fatura(date(2026, 8, 5), pago_em=date(2026, 8, 20))
    assert f.situacao(hoje=date(2026, 8, 30)) is SituacaoFatura.PAGO


def test_vencido():
    f = _fatura(date(2026, 8, 5))
    assert f.situacao(hoje=date(2026, 8, 6)) is SituacaoFatura.VENCIDO


def test_a_vencer_na_janela_de_sete_dias():
    f = _fatura(date(2026, 8, 15))
    assert f.situacao(hoje=date(2026, 8, 10)) is SituacaoFatura.A_VENCER


def test_em_aberto_antes_da_janela():
    f = _fatura(date(2026, 8, 30))
    assert f.situacao(hoje=date(2026, 8, 10)) is SituacaoFatura.EM_ABERTO


def test_vence_hoje_ainda_e_a_vencer():
    # Limite: no dia do vencimento o cliente ainda pode pagar.
    f = _fatura(date(2026, 8, 10))
    assert f.situacao(hoje=date(2026, 8, 10)) is SituacaoFatura.A_VENCER
