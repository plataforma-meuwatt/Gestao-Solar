"""Três defeitos medidos em produção na rota que sustenta a aba de Relatórios.

Cada bloco guarda um deles, e nenhum é hipotético — todos foram medidos contra a conta do
dono (usuário 2, 7 usinas) em 05/09/2026, e os números daqui são os números de lá.

**1. O eixo do mês era o campo errado.** A lista vem ordenada por `publicado_em`, que é a
data do ENVIO. Os fechamentos 35 (Porto Ferreira) e 36 (Pereiras) cobrem **agosto** e
foram publicados em **05/09**: uma tela que agrupasse pelo campo com que a lista vem
ordenada poria o fechamento de agosto na gaveta de setembro, e o cliente não acharia o
relatório do mês que foi procurar. O mês é o do período coberto, sai de `de`, e a régua
mora no servidor — num `@computed_field`, para que não exista maneira de a competência
discordar do `de` do mesmo documento.

**2. O peso do arquivo era jogado fora.** O upstream manda `files[].size_bytes` e o
`ArquivoOut` o descartava. As três peças publicadas hoje pesam 43.238 B, 2.604.352 B e
2.686.172 B — sessenta vezes de diferença — e o `Content-Length` do download bate com o
número declarado. Sem ele, quem está no 3G toca no PDF sem saber se são dois segundos ou
dois minutos.

**3. Não havia como perguntar "mudou?".** Sem `ETag`, o cache em disco do app ou baixa
tudo de novo ou mostra o velho. Quatro dos seis documentos desta conta são de junho: a
revalidação tinha de custar 304 e zero byte, e passou a custar.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import documents
from app.api.v1.documents import ArquivoOut, DocumentoOut, meus_documentos
from app.core.db import get_db
from app.core.security import criar_token, gerar_hash_senha
from app.models.user import Perfil, User, UserPlantAccess


class _PortalFalso:
    """O `/reports/portal` do meuWatt, com a FORMA medida em produção.

    Os documentos 35 e 36 são os reais, com os `size_bytes` reais. O 18 é o caso
    igualmente real do fechamento publicado com `files` vazio — quatro dos seis do acervo
    de hoje estão assim, e ele não pode virar erro nem sumir da lista.
    """

    async def portal_relatorios(self):
        return {
            "reports": [
                {
                    "id": 35,
                    "name": "Fechamento agosto",
                    "plant_slug": "porto-ferreira",
                    "period": "MENSAL",
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-31",
                    # Publicado em SETEMBRO, cobrindo AGOSTO. É este par que o teste guarda.
                    "sent_at": "2026-09-05T12:56:09.914048Z",
                    "files": [
                        {"kind": "geracao", "filename": "g.pdf", "size_bytes": 2686172},
                        {"kind": "paradas", "filename": "p.pdf", "size_bytes": 2604352},
                    ],
                },
                {
                    "id": 36,
                    "name": "Fechamento agosto",
                    "plant_slug": "ribeirao-bonito",
                    "period": "MENSAL",
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-31",
                    "sent_at": "2026-09-05T12:56:07.999069Z",
                    "files": [
                        {"kind": "resumo", "filename": "Resumo.pdf", "size_bytes": 43238}
                    ],
                },
                {
                    "id": 18,
                    "name": "Fechamento maio",
                    "plant_slug": "porto-ferreira",
                    "period": "MENSAL",
                    "date_from": "2026-05-01",
                    "date_to": "2026-05-31",
                    "sent_at": "2026-06-15T13:42:18.269326Z",
                    "files": [],
                },
                # Usina de outro cliente: nunca sai daqui. O corte por slug é a barreira, e
                # nada desta leva pode tê-lo afrouxado.
                {
                    "id": 9,
                    "name": "Fechamento março",
                    "plant_slug": "usina-de-outro-cliente",
                    "period": "MENSAL",
                    "date_from": "2026-03-01",
                    "date_to": "2026-03-31",
                    "sent_at": "2026-04-30T03:14:30.560731Z",
                    "files": [{"kind": "geracao", "filename": "x.pdf", "size_bytes": 99}],
                },
            ]
        }


@pytest.fixture
def dono(db, usinas, monkeypatch):
    u = User(
        apelido="dono",
        email="dono@exemplo.com.br",
        nome="Dono",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(u)
    db.commit()
    for usina in usinas:
        db.add(UserPlantAccess(user_id=u.id, plant_link_id=usina.id))
    db.commit()

    async def _cliente(_db):
        return _PortalFalso()

    monkeypatch.setattr("app.api.v1.documents.integracoes.cliente_meuwatt", _cliente)
    return u


@pytest.fixture
def http(db, dono):
    """Só o router de documentos — um router alheio quebrado no meio de uma edição não
    pode derrubar este arquivo. Mesma postura do `test_documents_seguranca.py`."""
    aplicacao = FastAPI()
    aplicacao.include_router(documents.router)
    aplicacao.dependency_overrides[get_db] = lambda: db
    cliente = TestClient(aplicacao)
    token, _ = criar_token(dono.id)
    cliente.headers["Authorization"] = f"Bearer {token}"
    return cliente


# ── 1. a competência sai de `de`, nunca de `publicado_em` ────────────────────


async def test_agosto_publicado_em_setembro_e_de_agosto(db, dono):
    """O DEFEITO: agrupar por `publicado_em` poria o fechamento de agosto em setembro.

    É o caso real dos documentos 35 e 36 — os dois únicos com arquivo no acervo de hoje.
    Se a competência voltar a sair da data de envio, este teste acusa a troca de gaveta.
    """
    saida = await meus_documentos(None, db, dono)
    trinta_e_cinco = next(d for d in saida.documentos if d.id == 35)

    assert trinta_e_cinco.competencia == "2026-08"
    # A prova de que não é o mês do envio: o envio foi em setembro.
    assert trinta_e_cinco.publicado_em.strftime("%Y-%m") == "2026-09"
    assert trinta_e_cinco.competencia != trinta_e_cinco.publicado_em.strftime("%Y-%m")


async def test_a_competencia_nao_pode_discordar_do_de(db, dono):
    """A régua é derivada, e por isso é única: não há um segundo lugar onde alguém possa
    escrever uma competência que contradiga o período coberto do mesmo documento."""
    saida = await meus_documentos(None, db, dono)
    for d in saida.documentos:
        if d.competencia is not None:
            assert d.competencia == d.de.strftime("%Y-%m"), (
                f"documento {d.id} diz competência {d.competencia} e cobre desde {d.de}"
            )


def test_o_primeiro_dia_do_mes_nao_escorrega_para_o_anterior():
    """A armadilha de fuso, escrita como teste.

    `de` chega como `YYYY-MM-DD` e o dia 1 é o caso perigoso: em quem constrói um
    instante UTC a partir da data, 01/08 vira 31/07 às 21 h no Brasil e o documento muda
    de mês. Aqui a competência sai de um `date`, sem hora e sem fuso — e é isso que este
    teste prende.
    """
    d = DocumentoOut(
        id=1,
        nome="x",
        usina="y",
        periodo="MENSAL",
        de="2026-08-01",
        ate="2026-08-31",
        publicado_em="2026-09-05T12:00:00",
    )
    assert d.competencia == "2026-08"
    assert d.ano is None


def test_o_anual_responde_por_ano_e_nao_por_mes():
    """O ANUAL cobre doze meses: dar-lhe competência o trancaria na gaveta de janeiro e o
    esconderia dos outros onze. Exatamente um dos dois campos é preenchido, sempre — é
    assim que a tela do ano distingue a espécie sem ler o rótulo de `periodo`."""
    anual = DocumentoOut(
        id=2,
        nome="Fechamento 2026",
        usina="y",
        periodo="ANUAL",
        de="2026-01-01",
        ate="2026-12-31",
        publicado_em="2027-01-10T12:00:00",
    )
    assert anual.competencia is None
    assert anual.ano == 2026


def test_a_semana_a_cavalo_de_dois_meses_ancora_no_comeco():
    """29/jun a 5/jul pertence a dois meses. A âncora é o começo do período coberto —
    decisão declarada, não acidente: o fim daria julho para uma semana que é de junho."""
    semanal = DocumentoOut(
        id=3,
        nome="Semana",
        usina="y",
        periodo="SEMANAL",
        de="2026-06-29",
        ate="2026-07-05",
        publicado_em="2026-07-06T12:00:00",
    )
    assert semanal.competencia == "2026-06"


# ── 2. o peso do arquivo, que o upstream manda e daqui era jogado fora ───────


async def test_o_peso_das_pecas_e_o_que_o_monitoramento_declara(db, dono):
    """Os números são os medidos em produção, e batem com o `Content-Length` do download
    das mesmas peças: 2.686.172, 2.604.352 e 43.238."""
    saida = await meus_documentos(None, db, dono)
    pesos = {
        (d.id, a.tipo): a.bytes for d in saida.documentos for a in d.arquivos
    }
    assert pesos[(35, "geracao")] == 2686172
    assert pesos[(35, "paradas")] == 2604352
    assert pesos[(36, "resumo")] == 43238


@pytest.mark.parametrize("ausente", [None, "", "nao-e-numero", {}])
def test_peso_ausente_e_nulo_jamais_zero(ausente):
    """Zero é uma resposta — "arquivo vazio" —, e a tela a desenharia como tal. Ausência é
    travessão. É a mesma disciplina do `bytes` do pacote de fichas."""
    a = ArquivoOut(tipo="geracao", nome="g.pdf", bytes=None)
    assert a.bytes is None

    from app.api.v1.documents import _inteiro

    assert _inteiro(ausente) is None
    assert _inteiro(0) == 0, "zero DECLARADO pelo upstream continua sendo zero"


def test_booleano_nao_vira_peso():
    """Em Python `True` vira `1` sem reclamar: um campo trocado por engano lá em cima
    viraria um arquivo de 1 byte em vez de um travessão honesto."""
    from app.api.v1.documents import _inteiro

    assert _inteiro(True) is None
    assert _inteiro(False) is None


async def test_fechamento_sem_arquivo_continua_chegando(db, dono):
    """Quatro dos seis documentos desta conta têm `files` vazio. Nada desta leva pode
    fazê-los sumir da lista nem virar erro: "publicado sem arquivo" é um estado do acervo
    que a tela precisa poder contar."""
    saida = await meus_documentos(None, db, dono)
    sem_arquivo = next(d for d in saida.documentos if d.id == 18)
    assert sem_arquivo.arquivos == []
    assert sem_arquivo.competencia == "2026-05"


# ── 3. o ETag, que é o que muda a vida de quem está no carro ─────────────────


def test_a_lista_traz_etag_e_a_revisita_custa_304_sem_corpo(http):
    """O DEFEITO: sem ETag o app ou baixa tudo ou mostra o velho, nunca revalida."""
    primeira = http.get("/api/v1/documents")
    assert primeira.status_code == 200
    etag = primeira.headers.get("etag")
    assert etag, "a lista voltou a sair sem etiqueta — não há como perguntar 'mudou?'"
    assert primeira.headers.get("cache-control") == "private, no-cache"

    segunda = http.get("/api/v1/documents", headers={"If-None-Match": etag})

    assert segunda.status_code == 304
    assert segunda.content == b"", "o 304 veio com corpo — a economia era o ponto"
    # RFC 9110 §15.4.5: quem revalidou precisa continuar com a etiqueta para amanhã.
    assert segunda.headers.get("etag") == etag


def test_etiqueta_estavel_entre_chamadas_iguais(http):
    """Se a etiqueta mudasse a cada chamada, o 304 nunca aconteceria e ninguém notaria —
    a tela continuaria certa e só a rede continuaria cara."""
    a = http.get("/api/v1/documents").headers["etag"]
    b = http.get("/api/v1/documents").headers["etag"]
    assert a == b


def test_etiqueta_muda_quando_o_acervo_muda(http, monkeypatch):
    """A outra metade: revalidar com uma etiqueta velha tem de trazer o corpo novo. Uma
    etiqueta que não acompanha o conteúdo é pior que nenhuma — congela a tela do cliente
    no acervo de ontem."""
    antiga = http.get("/api/v1/documents").headers["etag"]

    class _PortalComMaisUm(_PortalFalso):
        async def portal_relatorios(self):
            corpo = await super().portal_relatorios()
            corpo["reports"][0]["files"][0]["size_bytes"] = 999  # o peso mudou lá em cima
            return corpo

    async def _cliente(_db):
        return _PortalComMaisUm()

    monkeypatch.setattr("app.api.v1.documents.integracoes.cliente_meuwatt", _cliente)

    depois = http.get("/api/v1/documents", headers={"If-None-Match": antiga})

    assert depois.status_code == 200, "etiqueta velha revalidou contra acervo novo"
    assert depois.headers["etag"] != antiga


def test_a_etiqueta_e_por_recorte_e_nao_serve_para_outra_usina(http, usinas):
    """`?usina_id=` devolve outro conteúdo, logo outra etiqueta. Se as duas coincidissem,
    trocar de usina na tela devolveria 304 e a lista da usina anterior."""
    a, _b = usinas
    inteira = http.get("/api/v1/documents").headers["etag"]
    recortada = http.get("/api/v1/documents", params={"usina_id": a.id}).headers["etag"]
    assert inteira != recortada

    r = http.get(
        "/api/v1/documents", params={"usina_id": a.id}, headers={"If-None-Match": inteira}
    )
    assert r.status_code == 200


@pytest.mark.parametrize("formato", ['W/{etag}', '{etag}, "outra"', "*"])
def test_if_none_match_fraco_e_em_lista_tambem_revalida(http, formato):
    """`If-None-Match` é uma LISTA e pode vir com o prefixo fraco `W/`, posto por proxies.
    Comparar a string crua com `==` faria a revalidação falhar em silêncio."""
    etag = http.get("/api/v1/documents").headers["etag"]

    r = http.get("/api/v1/documents", headers={"If-None-Match": formato.format(etag=etag)})

    assert r.status_code == 304


def test_etiqueta_de_outro_cliente_nao_serve(http, db, usinas):
    """A etiqueta é do CORPO, e o corpo é recortado por pessoa. Uma etiqueta obtida com
    outro escopo não pode render 304 aqui — seria o cliente ficando com a lista alheia
    por revalidação."""
    outro = User(
        apelido="outro",
        email="outro@exemplo.com.br",
        nome="Outro",
        perfil=Perfil.CLIENTE,
        senha_hash=gerar_hash_senha("cliente-1234"),
    )
    db.add(outro)
    db.commit()
    db.add(UserPlantAccess(user_id=outro.id, plant_link_id=usinas[0].id))
    db.commit()

    token, _ = criar_token(outro.id)
    dele = http.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token}"}
    ).headers["etag"]

    meu = http.get("/api/v1/documents")
    assert meu.headers["etag"] != dele
    assert http.get("/api/v1/documents", headers={"If-None-Match": dele}).status_code == 200


def test_o_aviso_tambem_revalida(http, db, usinas, monkeypatch):
    """"O monitoramento continua fora do ar" também é uma resposta, e também não precisa
    de corpo novo. Sem isto, justamente o caso degradado seria o mais caro em rede."""

    async def _quebrado(_db):
        raise RuntimeError("timeout")

    monkeypatch.setattr("app.api.v1.documents.integracoes.cliente_meuwatt", _quebrado)

    primeira = http.get("/api/v1/documents")
    assert primeira.status_code == 200
    assert primeira.json()["aviso"]
    etag = primeira.headers["etag"]

    assert http.get(
        "/api/v1/documents", headers={"If-None-Match": etag}
    ).status_code == 304


# ── o que NÃO pode ter mudado ────────────────────────────────────────────────


async def test_o_corte_por_escopo_continua_de_pe(db, dono):
    """A usina do outro cliente está no portal falso de propósito: nada desta leva —
    nem os campos novos, nem o ETag — pode ter afrouxado a barreira que é a razão de
    existir deste módulo."""
    saida = await meus_documentos(None, db, dono)
    assert {d.id for d in saida.documentos} == {35, 36, 18}
    assert all(d.plant_id is not None for d in saida.documentos)


async def test_a_ordem_continua_sendo_a_da_publicacao(db, dono):
    """A competência é um EIXO NOVO, não uma reordenação. A lista continua chegando com o
    que foi publicado por último em primeiro — quem quer o acervo por mês agrupa por
    `competencia`, e as duas coisas não se confundem."""
    saida = await meus_documentos(None, db, dono)
    assert [d.id for d in saida.documentos] == [35, 36, 18]
    assert all(isinstance(d.publicado_em, datetime) for d in saida.documentos)


async def test_o_download_continua_refazendo_a_autorizacao(db, dono, monkeypatch):
    """`arquivo_do_documento` chama `meus_documentos` como FUNÇÃO, sem pedido HTTP. Os
    parâmetros novos de revalidação não podem ter quebrado essa chamada — se quebrarem, a
    segunda tranca do download cai junto."""
    from fastapi import HTTPException

    from app.api.v1.documents import arquivo_do_documento

    class _SemDownload(_PortalFalso):
        async def arquivo_relatorio(self, report_id, kind):
            raise AssertionError("não devia ter ido ao upstream")

    async def _cliente(_db):
        return _SemDownload()

    monkeypatch.setattr("app.api.v1.documents.integracoes.cliente_meuwatt", _cliente)

    # O 9 é do outro cliente: 404 sem tocar o meuWatt.
    with pytest.raises(HTTPException) as e:
        await arquivo_do_documento(9, "geracao", db, dono)
    assert e.value.status_code == 404
