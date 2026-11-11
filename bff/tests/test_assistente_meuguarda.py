"""As câmeras e os alarmes das usinas (meuGuarda) no bot do WhatsApp (pedido do dono, 11/11/2026: "integrar já, criar
rotina de teste e ligar para todos"). Especificação: `/root/DEVV/CFTV/docs/bot-gs.md`.

A parte `bot_meuguarda` não pede token: o meuGuarda confere a sessão do GS da própria pessoa.
"""
import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.user import Perfil, User, VinculoProduto
from app.services import cadastro


def _conta(db, apelido="tecnico.um", perfil=Perfil.TECNICO, telefone="+5517997371111", **bot):
    emp = db.query(Empresa).filter_by(nome="O&M das câmeras").one_or_none() or Empresa(nome="O&M das câmeras")
    db.add(emp)
    db.commit()
    u = User(apelido=apelido, nome=apelido.title(), perfil=perfil, telefone=telefone, empresa_id=emp.id, **bot)
    db.add(u)
    db.commit()
    return u


def test_a_parte_das_cameras_liga_sem_token_e_so_com_celular(db):
    conta = _conta(db)
    cadastro.liberar_bot(conta, "bot_meuguarda", True)
    assert conta.bot_ativo == {"bot_meuguarda"} and conta.bot_liberado
    # a do meuPlano continua pedindo o token dela
    with pytest.raises(HTTPException):
        cadastro.liberar_bot(conta, "bot_meuplano", True)

    sem_celular = _conta(db, "sem.celular", telefone=None)
    with pytest.raises(HTTPException) as e:
        cadastro.liberar_bot(sem_celular, "bot_meuguarda", True)
    assert "celular" in e.value.detail


async def test_apagar_o_celular_desliga_as_cameras_junto(db):
    conta = _conta(db, bot_meuguarda=True)
    await cadastro.gravar(db, conta, conta.empresa_id, telefone="")
    assert not conta.bot_meuguarda and conta.bot_ativo == set()


async def test_o_gerente_liga_e_desliga_pela_tela_bot_do_whatsapp(db):
    from app.api.v1 import empresa as rotas

    gerente = _conta(db, "gerente.um", Perfil.GESTOR_EMPRESA, "+5517997372222")
    tecnico = _conta(db, bot_meuguarda=True)
    db.add(VinculoProduto(gs_user_id=tecnico.id, produto="meuwatt", usuario_remoto_id="1", token_cifrado="x"))
    db.commit()
    out = await rotas.editar_conta_da_empresa(tecnico.id, rotas.ContaPatch(bot_meuguarda=False), db, gerente)
    assert out.bot_meuguarda is False and not db.get(User, tecnico.id).bot_meuguarda
