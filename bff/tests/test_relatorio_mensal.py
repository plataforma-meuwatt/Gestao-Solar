"""O relatório MENSAL liberado do meuPlano atravessando a ponte.

Outro documento e outro fluxo que o relatório sob demanda: este é o FECHAMENTO do mês —
um mês só, congelado, liberado por alguém, com texto humano. O que estes testes guardam,
em ordem de gravidade:

1. **O `rid` é um número que vem do cliente, e o corte de lá não é de carteira.** O corte do
   meuPlano nesta porta é de STATUS (só o liberado atravessa); o token da ponte é da
   organização gestora e enxerga TODAS as usinas — medido em 06/09/2026, pedir a lista de
   uma usina que não é deste cliente responde 200, não 403. Sem `_relatorio_autorizado`,
   trocar um dígito na URL abriria o relatório de outro dono. Dois testes, com dois ids.
2. **O que não é do cliente não sai.** `aprovado_por` é nome de funcionário da executora;
   `aprovado_em`/`apurado_em` respondem "quando os números foram calculados", que não é "de
   quando é este documento"; `texto` contradiz o próprio `dados` (medido no rid 14: 25
   fichas contra 57) e vive dentro do PDF, congelado e assinado; `tempo_em_campo` é métrica
   interna que o próprio catálogo do meuPlano diz não sair no documento do cliente. A
   asserção é NEGATIVA e por nome, sobre o JSON serializado.
3. **Vazio nasce com frase.** A rota de lá não distingue "não existe" de "existe e não foi
   liberado" — e faz certo. Quem distingue é este lado, que sabe qual mês foi pedido. Uma
   tela vazia e muda se lê como defeito, e hoje ela é o estado NORMAL de seis das sete
   usinas desta carteira (só Porto Ferreira tem documento liberado).
4. **Um selo só para a mesma atividade.** A linha de checklist saía "Checklist" no relatório
   e "Inspeção" no cronograma, porque o agregado congelado manda a ESPÉCIE e o cronograma ao
   vivo manda a NATUREZA. Dois selos para uma atividade em duas telas do mesmo portal é a
   lição mais cara deste projeto.
5. **Dois PDFs não têm o mesmo nome.** O do mensal e o do sob demanda caem na mesma pasta de
   Downloads, e dois arquivos homônimos é como a pergunta "qual é o certo?" começa.
6. **Nada é recalculado.** O detalhe passa o `dados` congelado pelo MESMO `traduzir` do
   relatório sob demanda — não existe uma segunda tradução.

Nada de rede: o meuPlano entra como fantasia, na FORMA REAL de `_liberado_out`
(`id`, `usina_id`, `competencia`, `tipo`, `liberado_em`, `aprovado_em`, `aprovado_por`,
`apurado_em` e, no detalhe, `dados`/`texto`/`secoes`).
"""

from datetime import date

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import relatorio as mod
from app.api.v1.manutencao import _categoria_da_linha
from app.api.v1.relatorio import (
    _aviso_do_vazio,
    _categoria_do_relatorio,
    pdf_do_relatorio_mensal,
    relatorio_mensal,
    relatorios_mensais,
)
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess


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


def _conceder(db, usuario, usina):
    db.add(UserPlantAccess(user_id=usuario.id, plant_link_id=usina.id))
    db.commit()


def _erro_http(status: int, corpo: object) -> httpx.HTTPStatusError:
    pedido = httpx.Request("GET", "https://meuplano.exemplo/x")
    resposta = httpx.Response(status, json=corpo, request=pedido)
    return httpx.HTTPStatusError("erro", request=pedido, response=resposta)


#: O `dados` congelado, na forma de `relatorio_manutencao.montar`. A linha de CHECKLIST está
#: aqui de propósito: é a que saía com dois selos.
DADOS = {
    "cabecalho": {
        "usina_id": 1,
        "usina": "UFV PORTO FERREIRA",
        "cliente": "Eninsa",
        "executora": "Splendor O&M",
        "contrato": {"id": 698, "numero": 1203, "titulo": "O&M 2026",
                     "start_date": "2026-03-01", "end_date": "2027-02-28"},
        "periodo": {"de": "2026-08", "ate": "2026-08"},
        "gerado_em": "2026-09-01T04:10:00",
    },
    "cronograma": {
        "versao": 1, "consolidated_at": "2026-03-02T10:00:00", "status": "CONSOLIDATED",
        "previsto": 13, "feito": 13, "dispensado": 0, "atrasado": 0,
        "no_prazo": 0, "sem_ativo": 0, "pct_cumprido": 100.0,
        "linhas": [
            {"plan_item_id": 5, "nome": "Termografia", "categoria": "ensaio",
             "previsto": 6, "feito": 6},
            # A espécie crua do congelado — sem `checklist_natureza`, que só o cronograma
            # ao vivo carrega.
            {"plan_item_id": 9, "nome": "Inspeção do cercamento", "categoria": "checklist",
             "previsto": 7, "feito": 7},
        ],
    },
    "cronograma_motivo": None,
    "dispensas": [],
    "ordens": [],
    "em_curso": [
        {"id": 1016, "name": "Manutenção preventiva do mês de agosto",
         "classification": "PREVENTIVA", "status": "EM_EXECUCAO",
         "task_count": 17, "task_realized_count": 17, "tarefas": []},
    ],
    "pareceres": {"aprovados": 56, "com_ressalva": 1, "reprovados": 0, "sem_parecer": 0,
                  "ordens_consideradas": 0, "ordens_em_curso_fora": 1},
    "problemas": {"total": 8, "por_criticidade": {"alto": 3, "baixo": 2, "nulo": 3},
                  "por_os": []},
    "pendencias": {
        "abertas": [{"id": 501, "numero": 8801, "titulo": "Status do DJ MT",
                     "status": "ABERTO", "priority": "media", "criticidade": "baixa"}],
        "concluidas": [],
    },
    "fotos_total": 102,
    # Métrica interna que o próprio catálogo do meuPlano diz não sair no documento do
    # cliente — chega no `dados` e não pode atravessar.
    "tempo_em_campo": {"minutos": 565, "horas": 9.4, "medido": True, "motivo": None},
}

#: A linha do MESMO checklist como o cronograma AO VIVO a manda — com a natureza.
LINHA_AO_VIVO = {"screen_categoria": None, "checklist_natureza": "INSPECAO"}


def _card(rid: int, usina_mp: int, tipo: str, competencia: str = "2026-08") -> dict:
    """Um item de `_liberado_out`, com os campos internos que NÃO podem atravessar."""
    return {
        "id": rid, "usina_id": usina_mp, "competencia": competencia, "tipo": tipo,
        "liberado_em": "2026-09-05T18:30:00",
        "aprovado_em": "2026-09-05T15:00:00",
        "aprovado_por": "Paulo Renan Nunes Marquezini",
        "apurado_em": "2026-09-01T04:10:00",
    }


def _detalhe(rid: int, usina_mp: int, tipo: str) -> dict:
    d = _card(rid, usina_mp, tipo)
    d["dados"] = DADOS
    d["texto"] = "Todas as 25 fichas executadas foram aprovadas."
    d["secoes"] = ["conformidade", "ordens"]
    return d


class ClienteFalso:
    """O meuPlano como fantasia. Grava o que foi pedido — a prova de que nada foi chamado."""

    def __init__(self, lista=None, detalhes=None, pdf=b"%PDF-1.4 fingido", erro=None):
        #: Porto Ferreira (mp 1) tem os dois; o rid 78 é da usina mp 2, de OUTRO cliente.
        self.lista = lista if lista is not None else [
            _card(14, 1, "tecnico"), _card(61, 1, "executivo"),
            _card(90, 1, "tecnico", "2026-07"),
        ]
        self.detalhes = detalhes if detalhes is not None else {
            14: _detalhe(14, 1, "tecnico"),
            61: _detalhe(61, 1, "executivo"),
            78: _detalhe(78, 2, "tecnico"),
        }
        self.pdf = pdf
        self.erro = erro
        self.pedidos: list[tuple] = []

    async def vc_relatorios_mensais(self, usina_id, competencia=None, tipo=None):
        self.pedidos.append(("lista", usina_id, competencia, tipo))
        if self.erro:
            raise self.erro
        itens = [i for i in self.lista if i["usina_id"] == usina_id]
        if competencia:
            itens = [i for i in itens if i["competencia"] == competencia]
        if tipo:
            itens = [i for i in itens if i["tipo"] == tipo]
        return itens

    async def vc_relatorio_mensal(self, rid):
        self.pedidos.append(("detalhe", rid))
        if self.erro:
            raise self.erro
        if rid not in self.detalhes:
            raise _erro_http(404, {"detail": "Relatório não encontrado"})
        return self.detalhes[rid]

    async def vc_relatorio_mensal_pdf(self, rid):
        self.pedidos.append(("pdf", rid))
        if self.erro:
            raise self.erro
        return self.pdf


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    """O dono enxerga Porto Ferreira (mp 1); Ribeirão Bonito (mp 2) é de outro cliente."""
    minha, _outra = usinas
    _conceder(db, dono, minha)
    cliente = ClienteFalso()

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.relatorio.integracoes.cliente_meuplano", _cliente)
    monkeypatch.setattr(mod, "hoje_na_usina", lambda: date(2026, 9, 6))
    return cliente


# ── a cerca: o rid vem do cliente ───────────────────────────────────────────


async def test_usina_alheia_e_404_e_nao_vai_ao_upstream(db, dono, usinas, cenario):
    """Guarda: a lista aceitando `usina_id` de outro dono.

    O corte do meuPlano nesta porta é de STATUS, não de carteira — o token da ponte é da
    gestora. Quem recorta é `_link_do_escopo`, e antes de qualquer ida.
    """
    _minha, outra = usinas
    with pytest.raises(HTTPException) as e:
        await relatorios_mensais(outra.id, None, None, db, dono)
    assert e.value.status_code == 404
    assert cenario.pedidos == []


async def test_relatorio_de_usina_fora_do_vinculo_e_404(db, dono, usinas, cenario):
    """Guarda: `_relatorio_autorizado` ausente — trocar um dígito abriria o documento alheio.

    O rid 14 é da usina desta pessoa e abre; o 78 existe, está liberado e o upstream o
    devolve de bom grado — é DESTE lado que ele tem de morrer.
    """
    meu = await relatorio_mensal(14, db, dono)
    assert meu.id == 14
    with pytest.raises(HTTPException) as e:
        await relatorio_mensal(78, db, dono)
    assert e.value.status_code == 404
    assert e.value.detail == "Relatório não encontrado."


async def test_pdf_de_usina_fora_do_vinculo_nao_chega_a_ser_gerado(db, dono, usinas, cenario):
    """Guarda: o PDF pulando a cerca. A prova é que `vc_relatorio_mensal_pdf` não foi pedido."""
    with pytest.raises(HTTPException) as e:
        await pdf_do_relatorio_mensal(78, db, dono)
    assert e.value.status_code == 404
    assert ("pdf", 78) not in cenario.pedidos


async def test_rid_inexistente_no_upstream_vira_404(db, dono, usinas, cenario):
    with pytest.raises(HTTPException) as e:
        await relatorio_mensal(9999, db, dono)
    assert e.value.status_code == 404


# ── o que não é do cliente não sai ──────────────────────────────────────────


@pytest.fixture
def cliente_http(db):
    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "proibido",
    ["aprovado_por", "aprovado_em", "apurado_em", "texto", "tempo_em_campo"],
)
async def test_campos_internos_nao_atravessam(db, dono, usinas, cenario, cliente_http, proibido):
    """Guarda: repassar o `_liberado_out` cru para a tela.

    `aprovado_por` entregaria o organograma da executora e criaria endereço para cobrança
    pessoal; as duas datas fazem o leitor não saber qual responde "de quando é isto";
    `texto` contradiz o próprio `dados` do mesmo relatório; `tempo_em_campo` é a métrica
    que o meuPlano declara não sair no documento do cliente. A asserção é sobre o JSON
    inteiro — um campo aninhado também condena.
    """
    token, _ = criar_token(dono.id)
    r = cliente_http.get(
        "/api/v1/manutencao/relatorios-mensais/14",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert proibido not in r.text


async def test_a_lista_tambem_nao_leva_o_nome_de_quem_aprovou(
    db, dono, usinas, cenario, cliente_http
):
    token, _ = criar_token(dono.id)
    minha, _ = usinas
    r = cliente_http.get(
        f"/api/v1/manutencao/relatorios-mensais?usina_id={minha.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert "aprovado_por" not in r.text and "Marquezini" not in r.text
    # A única data do card, e é a da entrega.
    assert r.json()["itens"][0]["liberado_em"] == "2026-09-05T18:30:00"


# ── vazio com frase ─────────────────────────────────────────────────────────


async def test_lista_vazia_nasce_com_aviso_dizendo_o_mes(db, dono, usinas, cenario):
    """Guarda: a tela vazia e muda, que se lê como defeito.

    É o estado de seis das sete usinas desta carteira: medido em 06/09/2026, só Porto
    Ferreira tem documento liberado — nas outras, os relatórios de agosto existem e seguem
    em rascunho, que é conversa interna.
    """
    minha, _ = usinas
    saida = await relatorios_mensais(minha.id, "2026-05", None, db, dono)
    assert saida.itens == []
    assert saida.aviso == (
        "O fechamento de mai/2026 ainda não foi liberado pela equipe de manutenção."
    )


def test_o_aviso_nomeia_a_especie_quando_o_tipo_foi_pedido():
    assert "relatório executivo" in _aviso_do_vazio("2026-08", "executivo")
    assert "relatório técnico" in _aviso_do_vazio(None, "tecnico")
    assert "fechamento" in _aviso_do_vazio(None, None)


async def test_lista_com_itens_nao_inventa_aviso(db, dono, usinas, cenario):
    minha, _ = usinas
    saida = await relatorios_mensais(minha.id, None, None, db, dono)
    assert saida.aviso is None and len(saida.itens) == 3


async def test_competencia_malformada_e_400_antes_do_upstream(db, dono, usinas, cenario):
    minha, _ = usinas
    with pytest.raises(HTTPException) as e:
        await relatorios_mensais(minha.id, "2026/08", None, db, dono)
    assert e.value.status_code == 400 and "YYYY-MM" in e.value.detail
    assert cenario.pedidos == []


# ── ordem, tradução e selo ──────────────────────────────────────────────────


async def test_executivo_antes_do_tecnico_e_mes_recente_primeiro(db, dono, usinas, cenario):
    """Guarda: ordenar com uma chave só e `reverse`, que inverteria o tipo junto do mês.

    A diretoria é o destino declarado do executivo; a ordem é a MESMA do aplicativo, senão
    "qual eu leio primeiro?" teria duas respostas no mesmo produto.
    """
    minha, _ = usinas
    saida = await relatorios_mensais(minha.id, None, None, db, dono)
    assert [(i.competencia, i.tipo) for i in saida.itens] == [
        ("2026-08", "executivo"), ("2026-08", "tecnico"), ("2026-07", "tecnico"),
    ]


async def test_o_detalhe_traduz_o_congelado_sem_recalcular(db, dono, usinas, cenario):
    """Guarda: uma segunda tradução (ou uma segunda conta) sobre o `dados` congelado.

    Os números saem como o meuPlano os congelou — 13/13, 100 %, 56+1 pareceres, 8 problemas,
    102 fotos —, e o contrato vem de DENTRO do `dados`, sem uma segunda ida que descreveria
    um documento congelado com um contrato lido hoje.
    """
    saida = await relatorio_mensal(14, db, dono)
    assert saida.competencia == "2026-08" and saida.tipo == "tecnico"
    conteudo = saida.conteudo
    assert conteudo.cronograma is not None
    assert (conteudo.cronograma.previstas, conteudo.cronograma.executadas) == (13, 13)
    assert conteudo.cronograma.pct_cumprido == 100.0
    assert (conteudo.pareceres.aprovados, conteudo.pareceres.com_ressalva) == (56, 1)
    assert conteudo.problemas.total == 8 and conteudo.fotos == 102
    assert conteudo.contrato is not None and conteudo.contrato.id == 698
    assert conteudo.periodo.de == "2026-08" and conteudo.periodo.ate == "2026-08"


async def test_a_linha_de_checklist_tem_o_MESMO_selo_das_duas_telas(db, dono, usinas, cenario):
    """Guarda: dois selos para a mesma atividade em duas telas do mesmo portal.

    O agregado congelado manda a ESPÉCIE ('checklist'); o cronograma ao vivo manda a
    NATUREZA ('INSPECAO'). Sem a ponte, a mesma linha saía "Checklist" no relatório e
    "Inspeção" no cronograma — e ninguém saberia que é a mesma coisa.
    """
    ao_vivo = _categoria_da_linha(LINHA_AO_VIVO)[0]
    assert _categoria_do_relatorio({"categoria": "checklist"}) == ao_vivo
    saida = await relatorio_mensal(14, db, dono)
    linhas = {linha.nome: linha.categoria for linha in saida.conteudo.cronograma.linhas}
    assert linhas["Inspeção do cercamento"] == ao_vivo
    # E o ensaio continua ensaio — a ponte não achata as outras espécies.
    assert linhas["Termografia"] == _categoria_da_linha({"screen_categoria": "ensaio"})[0]


def test_a_natureza_declarada_manda_sobre_o_padrao():
    """Uma limpeza continua limpeza: o default só vale quando a natureza não chega."""
    assert _categoria_do_relatorio(
        {"categoria": "checklist", "checklist_natureza": "LIMPEZA"}
    ) == _categoria_da_linha({"checklist_natureza": "LIMPEZA"})[0]


# ── PDF ─────────────────────────────────────────────────────────────────────


async def test_o_pdf_tem_nome_proprio_e_nao_colide_com_o_sob_demanda(
    db, dono, usinas, cenario, cliente_http
):
    """Guarda: os dois PDFs caindo na pasta de Downloads com o mesmo nome.

    São dois documentos (um congelado e entregue, outro recalculado ao abrir); dois arquivos
    homônimos é como a pergunta "qual é o certo?" começa.
    """
    token, _ = criar_token(dono.id)
    r = cliente_http.get(
        "/api/v1/manutencao/relatorios-mensais/14/pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200 and r.content == b"%PDF-1.4 fingido"
    disposicao = r.headers["content-disposition"]
    assert disposicao.startswith("inline; ")
    assert "Relatorio-mensal-tecnico-Porto-Ferreira-2026-08.pdf" in disposicao
    assert "Relatorio-manutencao" not in disposicao
    # O cabeçalho é latin-1 no Starlette: nome cru com acento estoura antes do CORS.
    disposicao.encode("latin-1")


async def test_pdf_vazio_e_502_com_frase(db, dono, usinas, monkeypatch):
    """Guarda: um arquivo de zero byte que o navegador abre em branco."""
    minha, _ = usinas
    _conceder(db, dono, minha)
    cliente = ClienteFalso(pdf=b"")

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.relatorio.integracoes.cliente_meuplano", _cliente)
    with pytest.raises(HTTPException) as e:
        await pdf_do_relatorio_mensal(14, db, dono)
    assert e.value.status_code == 502 and "vazio" in e.value.detail


async def test_liberado_sem_corpo_nao_vira_frase_de_cronograma(db, dono, usinas, monkeypatch):
    """Guarda: dizer "cronograma não publicado" para um documento que veio sem números.

    Seriam duas coisas diferentes com a mesma frase, e o cliente procuraria o problema no
    lugar errado.
    """
    minha, _ = usinas
    _conceder(db, dono, minha)
    sem_corpo = {**_card(14, 1, "tecnico"), "dados": None, "texto": None, "secoes": None}
    cliente = ClienteFalso(detalhes={14: sem_corpo})

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.relatorio.integracoes.cliente_meuplano", _cliente)
    with pytest.raises(HTTPException) as e:
        await relatorio_mensal(14, db, dono)
    assert e.value.status_code == 502 and "sem os números" in e.value.detail


# ── a porta é uma só ────────────────────────────────────────────────────────


async def test_a_ponte_so_chama_a_porta_do_cliente(db, dono, usinas, cenario):
    """Guarda: alguém "completar" o índice pela rota interna do meuPlano.

    O corte ('enviado' e 'expedido' — nem o degrau chamado "aprovado" passa) é de lá e é
    incondicional. Este lado não conhece outra porta: se conhecesse, teria de reimplementar
    a régua, e a versão errada entregaria ao cliente um documento que ninguém liberou.
    """
    minha, _ = usinas
    await relatorios_mensais(minha.id, None, None, db, dono)
    await relatorio_mensal(14, db, dono)
    await pdf_do_relatorio_mensal(14, db, dono)
    assert {p[0] for p in cenario.pedidos} == {"lista", "detalhe", "pdf"}
    metodos = dir(cenario)
    assert not [m for m in metodos if m.startswith("relatorios") or m == "relatorio"]


async def test_sem_sessao_e_401_nas_tres(cliente_http):
    """O par que prova o deploy: as rotas novas recusam sem token."""
    assert cliente_http.get(
        "/api/v1/manutencao/relatorios-mensais?usina_id=1"
    ).status_code == 401
    assert cliente_http.get("/api/v1/manutencao/relatorios-mensais/14").status_code == 401
    assert cliente_http.get("/api/v1/manutencao/relatorios-mensais/14/pdf").status_code == 401


async def test_upstream_fora_do_ar_nao_vira_500(db, dono, usinas, monkeypatch):
    minha, _ = usinas
    _conceder(db, dono, minha)
    cliente = ClienteFalso(erro=httpx.ConnectError("sem rota para o host"))

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.relatorio.integracoes.cliente_meuplano", _cliente)
    with pytest.raises(HTTPException) as e:
        await relatorios_mensais(minha.id, None, None, db, dono)
    assert e.value.status_code == 502
