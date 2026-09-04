"""A ficha ABRE, mesmo quando o item não é um julgamento.

O caso real (04/09/2026): a manutenção mensal dos inversores de Porto Ferreira — vinte
equipamentos — nunca abria no aplicativo. Não era lentidão nem permissão: o meuPlano devolvia
`aprovado: "Aprovado"` e `aprovado: "Não feito"` em itens de torque e de serviço, porque o PDF
imprime uma coluna só e ali cabe tanto o julgamento quanto o ESTADO. Como o schema declarava
`bool | None`, o Pydantic recusava a resposta inteira — vinte e um erros de validação — e a
tela ficava sem nada.

O que estes testes protegem:

1. **Texto no lugar de sim/não não derruba a ficha.** É o defeito que aconteceu.
2. **"Não feito" continua sendo "não feito"** — não vira "reprovado". Achatar em booleano
   acusaria o técnico de ter feito mal o que ele registrou não ter feito.
3. **Campo novo do upstream não quebra a tela.** A ficha é leitura: perder uma coluna é muito
   melhor que perder a página.
"""

import pytest

from app.api.v1.manutencao import FichaOut, _apontar_fotos_para_ca


def _ficha(**linha_extra):
    linha = {"ponto": "—", "valor": "1", "aprovado": None, "situacao": None}
    linha.update(linha_extra)
    return {
        "id": 6710,
        "nome": "O&M-Inversor-Mensal — 08/2026",
        "coletiva": True,
        "equipamentos": [
            {
                "equipamento": "Inversor 1.1",
                "medicoes": [{"nome": "Torqueamento", "unidade": None, "linhas": [linha]}],
                "checklist": [],
                "fotos": [],
            }
        ],
        "fotos": 0,
    }


def test_rotulo_de_estado_nao_derruba_a_ficha():
    """Era isto que impedia a ficha de abrir: um texto onde se esperava sim/não."""
    out = FichaOut.model_validate(_ficha(aprovado=True, situacao="Aprovado"))
    linha = out.equipamentos[0].medicoes[0].linhas[0]
    assert linha.aprovado is True
    assert linha.situacao == "Aprovado"


def test_nao_feito_nao_vira_reprovado():
    out = FichaOut.model_validate(_ficha(aprovado=None, situacao="Não feito"))
    linha = out.equipamentos[0].medicoes[0].linhas[0]
    assert linha.aprovado is None, "estado não é julgamento"
    assert linha.situacao == "Não feito"


def test_campo_novo_do_upstream_e_ignorado():
    """A ficha é leitura: uma coluna a mais não pode custar a página inteira."""
    bruta = _ficha()
    bruta["equipamentos"][0]["medicoes"][0]["linhas"][0]["coluna_que_ainda_nao_existe"] = 42
    bruta["campo_novo_no_topo"] = {"qualquer": "coisa"}
    out = FichaOut.model_validate(bruta)
    assert out.equipamentos[0].medicoes[0].linhas[0].valor == "1"


def test_fotos_recebem_o_endereco_desta_casa():
    """O aplicativo só tem sessão no BFF: endereço do upstream chegaria sem credencial."""
    bruta = _ficha()
    bruta["equipamentos"][0]["fotos"] = [
        {"id": 37, "legenda": None, "url": "/tasks/6710/fotos/37",
         "thumb_url": "/tasks/6710/fotos/37?variante=thumb"}
    ]
    bruta["equipamentos"][0]["checklist"] = [
        {"nome": "Inspeção", "perguntas": [
            {"pergunta": "Existem sinais de avaria?", "resposta": "Não", "problema": False,
             "observacao": None,
             "fotos": [{"id": 38, "legenda": None, "url": "/tasks/6710/fotos/38",
                        "thumb_url": "/tasks/6710/fotos/38?variante=thumb"}]},
        ]}
    ]
    _apontar_fotos_para_ca(bruta, 1016, 6710)
    out = FichaOut.model_validate(bruta)

    da_sessao = out.equipamentos[0].fotos[0]
    da_resposta = out.equipamentos[0].checklist[0].perguntas[0].fotos[0]
    for f in (da_sessao, da_resposta):
        assert f.url.startswith("/api/v1/manutencao/ordens/1016/tarefas/6710/fotos/")
        assert "variante=thumb" in f.thumb_url
    assert da_resposta.url.endswith("/38"), "a foto da resposta também é reescrita"


@pytest.mark.parametrize("valor", [True, False, None])
def test_julgamento_de_verdade_continua_booleano(valor):
    out = FichaOut.model_validate(_ficha(aprovado=valor))
    assert out.equipamentos[0].medicoes[0].linhas[0].aprovado is valor
