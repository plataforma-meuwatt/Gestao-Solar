"""As áreas do painel: quem abre o quê, e as travas que sustentam a régua.

Os testes chamam a guarda `exige_area` diretamente, com a sessão e o usuário no lugar das
dependências do FastAPI — é o mesmo código que roda na requisição, sem subir servidor.
"""

import pytest
from fastapi import HTTPException

from app.core.security import exige_area
from app.models.acesso_painel import AcessoPainel
from app.services import areas_painel


def _abre(db, usuario, chave: str) -> bool:
    """Roda a guarda de verdade. `True` = passou, `False` = 403."""
    try:
        exige_area(chave)(gestor=usuario, db=db)
        return True
    except HTTPException as exc:
        assert exc.status_code == 403
        return False


def test_administrador_abre_tudo_sem_linha_no_banco(db, administrador):
    """A trava que impede o painel de se trancar: o administrador não depende de
    concessão. Revogar tudo por engano não pode deixar ninguém do lado de fora."""
    assert areas_painel.concedidas(db, administrador) == set()
    assert areas_painel.efetivas(db, administrador) == areas_painel.CHAVES
    for area in areas_painel.CATALOGO:
        assert _abre(db, administrador, area.chave)


def test_atendimento_nasce_sem_nada(db, atendente):
    """Ausência de linha é ausência de acesso — não há área que "todo mundo tem"."""
    assert areas_painel.efetivas(db, atendente) == set()
    assert not _abre(db, atendente, "whatsapp")
    assert not _abre(db, atendente, "clientes")


def test_area_concedida_abre_so_ela(db, atendente, administrador):
    areas_painel.definir(db, atendente, {"clientes", "diagnostico"}, administrador)
    db.commit()

    assert _abre(db, atendente, "clientes")
    assert _abre(db, atendente, "diagnostico")
    # O caso do pedido: outro gestor opera clientes e NÃO mexe no WhatsApp da empresa.
    assert not _abre(db, atendente, "whatsapp")
    assert not _abre(db, atendente, "conexoes")


def test_definir_revoga_o_que_nao_veio(db, atendente, administrador):
    """A tela manda o estado das caixinhas, não um acréscimo: desmarcar tem de apagar."""
    areas_painel.definir(db, atendente, {"clientes", "whatsapp"}, administrador)
    db.commit()
    areas_painel.definir(db, atendente, {"clientes"}, administrador)
    db.commit()

    assert areas_painel.concedidas(db, atendente) == {"clientes"}
    assert not _abre(db, atendente, "whatsapp")


def test_conceder_duas_vezes_nao_duplica(db, atendente, administrador):
    areas_painel.definir(db, atendente, {"usinas"}, administrador)
    db.commit()
    areas_painel.definir(db, atendente, {"usinas"}, administrador)
    db.commit()

    linhas = db.query(AcessoPainel).filter(AcessoPainel.user_id == atendente.id).all()
    assert len(linhas) == 1
    assert linhas[0].concedido_por == administrador.id


def test_area_fora_do_catalogo_e_recusada(db, atendente, administrador):
    """Gravar calado deixaria a caixinha ligada na tela e a pessoa tomando 403 — a pior
    combinação possível."""
    with pytest.raises(ValueError, match="desconhecida"):
        areas_painel.definir(db, atendente, {"clientes", "financeiro"}, administrador)


def test_linha_orfa_no_banco_nao_abre_nada(db, atendente):
    """O banco aceita um texto que o catálogo não conhece; a checagem não."""
    db.add(AcessoPainel(user_id=atendente.id, area="tela-que-nao-existe"))
    db.commit()
    assert areas_painel.efetivas(db, atendente) == set()


def test_usuarios_do_sistema_nao_e_area_concedivel(db):
    """A trava do item 3 de `areas_painel`: conceder "mexer em quem administra" a quem não
    administra é conceder tudo — a pessoa se promove a administrador no primeiro clique.
    Se alguém adicionar essa área ao catálogo, este teste é quem avisa."""
    assert "usuarios" not in areas_painel.CHAVES
    assert "equipe" not in areas_painel.CHAVES


def test_guarda_com_area_inventada_estoura_na_importacao():
    """Uma área digitada errada numa rota seria uma porta que ninguém abre, nem o
    administrador — e o sintoma chegaria como "a tela sumiu para todo mundo"."""
    with pytest.raises(ValueError, match="Área desconhecida"):
        exige_area("whatsap")
