"""O cadastro: o GS é a base de todos, e o meuPlano é um vínculo (decisão do dono, 23/10/2026).

Ligada ao meuPlano, a pessoa tem UMA base: editar aqui grava lá ANTES (recusa lá = nada muda
aqui), e o que mudar lá chega aqui. Sem vínculo, o cadastro é só daqui.
"""

import httpx
import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.user import Perfil, User
from app.services import cadastro


class _MP:
    def __init__(self, pessoas, recusa=False):
        self.pessoas, self.recusa, self.gravado = pessoas, recusa, []

    async def usuarios_admin(self):
        return self.pessoas

    async def atualizar_usuario_admin(self, uid, dados):
        if self.recusa:
            req = httpx.Request("PATCH", "http://mp/x")
            raise httpx.HTTPStatusError("403", request=req, response=httpx.Response(403, request=req,
                                        json={"detail": "sem permissão de usuários"}))
        self.gravado.append((uid, dados))
        for p in self.pessoas:
            if p["id"] == uid:
                p.update({"name": dados.get("name", p["name"]), "phone": dados.get("phone", p.get("phone"))})
        return {}


@pytest.fixture
def cenario(db, monkeypatch):
    emp = Empresa(nome="O&M")
    db.add(emp)
    db.commit()
    conta = User(apelido="ana", email="ana@x.com", nome="Ana", perfil=Perfil.CLIENTE, empresa_id=emp.id)
    db.add(conta)
    db.commit()
    mp = _MP([{"id": 7, "name": "Ana Souza", "email": "ana@empresa.com", "phone": "16 99999-8888", "active": True}])

    async def _mp(db_, empresa_id):
        return mp

    monkeypatch.setattr(cadastro, "_mp", _mp)
    return db, emp, conta, mp


async def test_ligar_puxa_nome_email_e_celular_do_meuplano(cenario):
    db, emp, conta, mp = cenario
    assert await cadastro.ligar(db, conta, emp.id, 7) == []
    assert (conta.nome, conta.email, conta.telefone) == ("Ana Souza", "ana@empresa.com", "+5516999998888")
    assert cadastro.vinculo_meuplano(db, conta.id).token_cifrado is None   # ligar não é token


async def test_editar_grava_no_meuplano_antes_e_recusa_la_nao_muda_nada_aqui(cenario):
    db, emp, conta, mp = cenario
    await cadastro.ligar(db, conta, emp.id, 7)
    await cadastro.gravar(db, conta, emp.id, nome="Ana S.", telefone="(16) 98888-7777")
    assert mp.gravado == [(7, {"name": "Ana S.", "phone": "(16) 9 8888-7777"})]
    assert (conta.nome, conta.telefone) == ("Ana S.", "+5516988887777")

    mp.recusa = True
    with pytest.raises(HTTPException) as e:
        await cadastro.gravar(db, conta, emp.id, nome="Outra")
    assert e.value.status_code == 424 and conta.nome == "Ana S."


async def test_o_que_muda_no_meuplano_chega_aqui(cenario):
    db, emp, conta, mp = cenario
    await cadastro.ligar(db, conta, emp.id, 7)
    mp.pessoas[0]["phone"] = "(16) 97777-6666"
    assert await cadastro.sincronizar(db, emp.id) == 1
    assert conta.telefone == "+5516977776666"


async def test_sem_vinculo_o_cadastro_e_so_daqui(cenario):
    db, emp, conta, mp = cenario
    await cadastro.gravar(db, conta, emp.id, nome="Ana do Zero", telefone="(11) 91234-5678")
    assert mp.gravado == [] and conta.telefone == "+5511912345678"
