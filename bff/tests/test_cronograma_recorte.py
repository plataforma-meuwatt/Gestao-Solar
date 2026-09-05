"""O recorte de vigência do cronograma: repassado do meuPlano, nunca recalculado aqui.

O defeito que estes testes prendem tem nome e número. `previsto_ano`/`feitos_ano` contam a
matriz INTEIRA — os 12 meses do contrato, inclusive os que ainda não venceram — e respondem
"o que foi combinado". A tela, porém, pergunta outra coisa: **"está sendo feito?"**. Dividir
o cumprido por um ano que ainda não aconteceu produziu "13 de 270" (4,8 %) numa tela e
"41,9 %" na outra, para a MESMA usina, que não tinha uma única atividade atrasada.

A régua do recorte é a do Relatório de manutenção e mora no meuPlano, ao lado de quem já a
usa. Se este BFF refizesse a conta, nasceria a TERCEIRA resposta para a mesma pergunta — e o
produto passaria a se contradizer em três lugares em vez de dois. Por isso os testes abaixo
não conferem se a conta está *certa*: conferem que ela **não é feita aqui**. O upstream
manda 41,9; a rota devolve 41,9. O upstream muda para 12,5 — mesmo com os números vizinhos
que dariam outro percentual — e a rota devolve 12,5.

A segunda cerca é a REGRA 0: ausência é `None`, jamais `0`. Um "0 % cumprido" fabricado por
falta de campo é a acusação mais cara que este BFF poderia imprimir sozinho contra quem fez
o serviço.

Nada de rede: o meuPlano entra como fantasia.
"""

import pytest

from app.api.v1.manutencao import cronograma_da_usina
from app.core.security import gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess

#: Os 12 meses da matriz, a partir da âncora do contrato (março, não janeiro).
MESES = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08",
         "2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]

#: A classificação que o meuPlano manda por mês. Setembro é o corrente; o que veio antes
#: está fechado; o resto ainda não venceu e não se cobra.
MESES_ESTADO = [
    {"mes": m,
     "situacao": "fechado" if m < "2026-09" else ("corrente" if m == "2026-09" else "futuro"),
     "previsto": 3 if m < "2026-09" else 2,
     "cumprido": 2 if m < "2026-09" else 0}
    for m in MESES
]

#: A matriz do meuPlano já com o recorte pronto. O percentual do upstream é o do upstream:
#: o que a rota devolve tem de ser ele, e não um número refeito a partir dos vizinhos.
MATRIZ = {
    "status": "CONSOLIDATED",
    "version": 2,
    "month_labels": MESES,
    "rows": [
        {
            "plan_item_id": 77, "name": "Termografia", "type_code": "inversor",
            "screen_categoria": "ensaio", "periodicity_value": 4, "periodicity_unit": "ano",
            "expected_per_year": 4,
            "months": {"1": 1, "4": 1, "7": 1, "10": 1},
            "cell_status": {"1": "verde", "4": "verde_ressalva", "7": "vermelho", "10": "azul"},
        }
    ],
    "mes_referencia": "2026-09",
    "previsto_ate_hoje": 31,
    "cumprido_ate_hoje": 13,
    "pct_ate_hoje": 41.9,
    "previsto_no_contrato": 270,
    "meses_estado": MESES_ESTADO,
}

CONTRATOS = [
    {"id": 20, "numero": 200, "title": "O&M 2026", "start_date": "2026-03-01",
     "end_date": "2027-02-28", "vigente": True, "versao_consolidada": 2},
]


class ClienteFalso:
    """O meuPlano como fantasia: um contrato consolidado e a matriz que lhe derem."""

    def __init__(self, matriz):
        self.matriz = matriz

    async def vc_contratos(self, usina_id):
        return CONTRATOS

    async def vc_cronograma(self, usina_id, container_id):
        return self.matriz


@pytest.fixture
def dono(db):
    u = User(
        apelido="renan.marquezini",
        email="renan@exemplo.com.br",
        nome="Renan",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def porto(db, dono, usinas):
    alvo, _ribeirao = usinas
    db.add(UserPlantAccess(user_id=dono.id, plant_link_id=alvo.id))
    db.commit()
    return alvo


@pytest.fixture
def upstream(monkeypatch):
    """Devolve uma função que planta, no lugar do meuPlano, a matriz que o teste quiser."""

    def _plantar(matriz):
        async def _cliente(_db):
            return ClienteFalso(matriz)

        monkeypatch.setattr("app.api.v1.manutencao.integracoes.cliente_meuplano", _cliente)

    return _plantar


# ── o repasse ───────────────────────────────────────────────────────────────


async def test_o_percentual_do_upstream_chega_intacto(db, dono, porto, upstream):
    """Guarda: o BFF recalculando o percentual e devolvendo outro número.

    41,9 entra, 41,9 sai — junto com a janela e o denominador, sem os quais o percentual é
    metade da frase ("41,9 % de quê, até quando?").
    """
    upstream(MATRIZ)
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.pct_ate_hoje == 41.9
    assert saida.mes_referencia == "2026-09"
    assert saida.previsto_ate_hoje == 31
    assert saida.cumprido_ate_hoje == 13
    assert saida.previsto_no_contrato == 270


async def test_mudar_o_valor_no_upstream_muda_a_resposta(db, dono, porto, upstream):
    """Guarda: uma conta própria escondida atrás do campo — o defeito principal.

    Os números vizinhos continuam os mesmos (31 previstos, 13 cumpridos, que dariam ~41,9);
    só o percentual do upstream muda para 12,5. Uma rota que recalculasse ignoraria a troca
    e continuaria devolvendo 41,9. Este é o teste que prova que a conta tem UM dono.
    """
    upstream({**MATRIZ, "pct_ate_hoje": 12.5})
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.pct_ate_hoje == 12.5
    assert (saida.previsto_ate_hoje, saida.cumprido_ate_hoje) == (31, 13)


async def test_percentual_ausente_sai_nulo_e_nunca_zero(db, dono, porto, upstream):
    """Guarda: REGRA 0 — ausência virando 0 %.

    Cronograma sem recorte publicado tem de chegar à tela como travessão. Com `0.0` no
    lugar, o cliente leria "0 % cumprido" — uma acusação inventada nesta casa contra quem
    fez o serviço.
    """
    sem_recorte = {k: v for k, v in MATRIZ.items()
                   if k not in ("pct_ate_hoje", "previsto_ate_hoje", "cumprido_ate_hoje",
                                "previsto_no_contrato", "mes_referencia")}
    upstream(sem_recorte)
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.pct_ate_hoje is None
    assert saida.previsto_ate_hoje is None
    assert saida.cumprido_ate_hoje is None
    assert saida.previsto_no_contrato is None
    assert saida.mes_referencia is None


async def test_zero_do_upstream_continua_zero(db, dono, porto, upstream):
    """Guarda: o inverso do anterior — engolir um zero MEDIDO como se fosse ausência.

    "Nada cumprido ainda" é resposta legítima de um contrato que acabou de começar, e
    apagá-la para travessão esconderia justamente o mês que precisa de explicação.
    """
    upstream({**MATRIZ, "cumprido_ate_hoje": 0, "pct_ate_hoje": 0.0})
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.cumprido_ate_hoje == 0
    assert saida.pct_ate_hoje == 0.0


# ── os 12 meses classificados ───────────────────────────────────────────────


async def test_os_doze_meses_chegam_classificados(db, dono, porto, upstream):
    """Guarda: a tela deduzindo sozinha qual mês já venceu.

    São 12 entradas, na ordem da âncora do contrato, com o vocabulário fechado ·
    corrente · futuro. Sem elas a tela cobraria um mês que ainda nem chegou.
    """
    upstream(MATRIZ)
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert len(saida.meses_estado) == 12
    assert [m.mes for m in saida.meses_estado] == MESES
    assert {m.situacao for m in saida.meses_estado} <= {"fechado", "corrente", "futuro"}
    assert [m.situacao for m in saida.meses_estado].count("corrente") == 1
    setembro = next(m for m in saida.meses_estado if m.mes == "2026-09")
    assert (setembro.situacao, setembro.previsto, setembro.cumprido) == ("corrente", 2, 0)


async def test_sem_meses_estado_a_lista_fica_vazia(db, dono, porto, upstream):
    """Guarda: a classificação sendo inventada aqui quando o upstream cala.

    Lista vazia é "o meuPlano não disse" — a tela mostra a matriz sem a faixa de vigência,
    em vez de carimbar "futuro" em tudo por conta própria.
    """
    upstream({k: v for k, v in MATRIZ.items() if k != "meses_estado"})
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.meses_estado == []


async def test_situacao_desconhecida_viaja_crua(db, dono, porto, upstream):
    """Guarda: engolir um estado novo do meuPlano e deixar o mês sem classificação nenhuma.

    Se um dia existir "suspenso", ele chega à tela com esse nome. É o mesmo tratamento que
    `_situacao` já dá a um status de OS que ainda não conhecemos.
    """
    estados = [dict(m) for m in MESES_ESTADO]
    estados[0]["situacao"] = "suspenso"
    upstream({**MATRIZ, "meses_estado": estados})
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.meses_estado[0].situacao == "suspenso"


# ── o que NÃO podia mudar ───────────────────────────────────────────────────


async def test_previsto_e_feitos_do_ano_seguem_saindo_da_matriz(db, dono, porto, upstream):
    """Guarda: o recorte substituindo os totais do ano — que respondem outra pergunta.

    Os dois convivem de propósito: 4 previstos no ano por esta linha, ao lado dos 31
    previstos até hoje no contrato inteiro. Trocar um pelo outro apagaria justamente a
    distinção que reconcilia "270" com "31".
    """
    upstream(MATRIZ)
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.previsto_ano == 4
    # verde + verde_ressalva: o dispensado saiu da conta do mês por decisão registrada.
    assert saida.feitos_ano == 2
    assert saida.previsto_ate_hoje == 31 and saida.previsto_no_contrato == 270


async def test_lixo_no_lugar_do_numero_nao_vira_numero(db, dono, porto, upstream):
    """Guarda: `float(True)` virando 100 %, e texto virando exceção na cara do cliente.

    Campo trocado por engano lá em cima chega como nulo aqui — a tela mostra travessão em
    vez de um percentual fabricado, e a página não cai.
    """
    upstream({**MATRIZ, "pct_ate_hoje": True, "previsto_ate_hoje": "trinta e um",
              "meses_estado": [*MESES_ESTADO, {"situacao": "futuro"}, "isto nao e um mes"]})
    saida = await cronograma_da_usina(porto.id, None, db, dono)
    assert saida.pct_ate_hoje is None
    assert saida.previsto_ate_hoje is None
    # Os 12 legítimos ficam; o item sem `mes` e o que nem dicionário é são descartados.
    assert len(saida.meses_estado) == 12
