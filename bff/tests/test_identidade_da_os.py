"""A mesma OS tem UM nome e UM número em todo o portal — e nada de código de banco na tela.

Três defeitos que a verificação do portal pegou lado a lado, todos com a mesma raiz: cada
tela traduzia (ou não traduzia) por conta própria, e o campo mais importante estava com o
nome errado no contrato.

1. **"OS #665" era o número do CONTRATO.** `OrdemOut.numero` vinha de `container_numero`,
   que o meuPlano documenta como "nº do contrato/sinistro/garantia/pendência". O drawer da
   pendência imprimia "OS #665" enquanto a lista chamava a MESMA ordem de "OS 1016", e o
   cabeçalho do relatório imprimia "CONTRATO #665" — a mesma string, dois significados.
   Toda OS do contrato 665 virava "OS #665". O campo agora se chama `contrato_numero`, e a
   OS se identifica pelo `id`, que é o único número que ela tem no meuPlano.

2. **"SERVICOS_ADICIONAIS" com underscore na cara do cliente.** A tela de Ordens traduzia
   com uma função própria; a de Relatórios imprimia o código cru. A tradução desceu para
   cá, onde já mora o vocabulário de `situacao`/`status`, e as duas telas passaram a ler o
   mesmo texto pronto.

3. **"6/MONTH", "1/YEAR", "INSPECAO", "ensaio".** O cronograma mostrava periodicidade em
   inglês e categoria em duas caixas diferentes, num portal de cliente corporativo
   brasileiro. Mesma cura: traduzir uma vez, aqui.
"""

from app.api.v1.manutencao import (
    OrdemOut,
    _categoria_da_linha,
    _classificacao,
    _ordem_out,
    _periodicidade,
)
from app.models.plant import PlantLink


def _link() -> PlantLink:
    return PlantLink(id=7, nome="Porto Ferreira", mp_usina_id=1, mw_plant_slug="porto-ferreira")


# ── identidade ──────────────────────────────────────────────────────────────


def test_o_numero_do_contrato_nao_se_apresenta_como_numero_da_os() -> None:
    """O caso real: a OS 1016 do contrato 665. O número do contrato continua acessível,
    com o nome certo — quem quiser mostrar "OS" tem só o `id`."""
    saida = _ordem_out(
        {"id": 1016, "container_numero": 665, "container_title": "O&M 2026",
         "status": "EM_EXECUCAO", "task_count": 17, "task_realized_count": 17},
        _link(),
    )
    assert saida.id == 1016
    assert saida.contrato_numero == 665
    # O campo antigo não pode ressuscitar com o significado errado.
    assert "numero" not in OrdemOut.model_fields


def test_a_os_sem_nome_proprio_herda_o_titulo_do_contrato() -> None:
    """A OS 969 tem `name` e `objetivo` NULOS no banco. Na lista ela aparecia como
    "Instalação da Comunicação" (título do contêiner) e no relatório como "OS 969" —
    porque o agregado do relatório não mandava `container_title`. Agora manda, e a cascata
    é a mesma nas duas telas."""
    saida = _ordem_out(
        {"id": 969, "name": None, "objetivo": None,
         "container_title": "Instalação da Comunicação", "container_numero": 665,
         "status": "APROVADA"},
        _link(),
    )
    assert saida.objetivo == "Instalação da Comunicação"


def test_sem_nome_em_lugar_nenhum_a_os_ainda_se_identifica() -> None:
    """Última ponta da cascata: nunca uma linha em branco."""
    saida = _ordem_out({"id": 42, "status": "ABERTA"}, _link())
    assert saida.objetivo == "OS 42"
    assert saida.contrato_numero is None


# ── classificação ───────────────────────────────────────────────────────────


def test_a_classificacao_sai_traduzida_com_o_codigo_ao_lado() -> None:
    saida = _ordem_out(
        {"id": 969, "classification": "SERVICOS_ADICIONAIS", "status": "APROVADA"}, _link()
    )
    assert saida.classificacao == "Serviços adicionais"
    assert saida.classificacao_codigo == "SERVICOS_ADICIONAIS"   # auditoria mantida
    assert "_" not in saida.classificacao


def test_classificacao_desconhecida_nunca_vira_codigo_cru_na_tela() -> None:
    rotulo, codigo, tom = _classificacao("MANUTENCAO_ESPECIAL")
    assert rotulo == "Manutencao especial"
    assert codigo == "MANUTENCAO_ESPECIAL"
    assert tom == "semDados"


def test_classificacao_ausente_nao_inventa_rotulo() -> None:
    assert _classificacao(None) == (None, None, "semDados")


def test_o_tom_da_classificacao_vem_do_servidor() -> None:
    assert _classificacao("CORRETIVA")[2] == "alerta"
    assert _classificacao("PREVENTIVA")[2] == "ok"


# ── vocabulário do cronograma ───────────────────────────────────────────────


def test_periodicidade_em_ingles_vira_portugues() -> None:
    """Os três casos vistos na tela: "6/MONTH", "1/YEAR" e "3/MONTH"."""
    assert _periodicidade(6, "MONTH") == "Semestral"
    assert _periodicidade(1, "YEAR") == "Anual"
    assert _periodicidade(3, "MONTH") == "Trimestral"


def test_periodicidade_sem_nome_proprio_ainda_se_le() -> None:
    assert _periodicidade(5, "MONTH") == "A cada 5 meses"
    assert _periodicidade(1, "MONTH") == "Mensal"


def test_periodicidade_ausente_nao_vira_texto() -> None:
    assert _periodicidade(None, None) is None
    assert _periodicidade(4, "") is None


def test_categoria_da_linha_sai_em_portugues_nas_duas_caixas() -> None:
    """O meuPlano manda a categoria da TELA em minúsculo e a natureza do CHECKLIST em
    maiúsculo — dois vocabulários no mesmo cronograma."""
    assert _categoria_da_linha({"screen_categoria": "ensaio"})[0] == "Ensaio"
    assert _categoria_da_linha({"checklist_natureza": "INSPECAO"})[0] == "Inspeção"
    assert _categoria_da_linha({"screen_categoria": "SERVICO"})[0] == "Serviço"


def test_categoria_desconhecida_nao_chega_crua_e_guarda_o_codigo() -> None:
    rotulo, codigo = _categoria_da_linha({"screen_categoria": "TESTE_ESPECIAL"})
    assert rotulo == "Teste especial"
    assert codigo == "TESTE_ESPECIAL"


def test_categoria_ausente_e_nula() -> None:
    assert _categoria_da_linha({}) == (None, None)


def test_periodicidade_vale_nos_dois_vocabularios_do_upstream() -> None:
    """O modelo do meuPlano diz `DAY|WEEK|MONTH|YEAR`, mas há linha gravada em português.
    Sem o alias, "4/ano" saía "A cada 4 ano" — plural errado na tela do cliente."""
    assert _periodicidade(4, "ano") == "A cada 4 anos"
    assert _periodicidade(6, "mes") == "Semestral"
    assert _periodicidade(1, "mês") == "Mensal"
