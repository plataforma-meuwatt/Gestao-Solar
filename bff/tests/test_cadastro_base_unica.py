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
    # A empresa casada com a organização dela no meuPlano (`owners.id` 3): é dela que se puxa.
    emp = Empresa(nome="O&M", mp_tenant_id=3)
    db.add(emp)
    db.commit()
    conta = User(apelido="ana", email="ana@x.com", nome="Ana", perfil=Perfil.CLIENTE, empresa_id=emp.id)
    db.add(conta)
    db.commit()
    mp = _MP([
        {"id": 7, "name": "Ana Souza", "email": "ana@empresa.com", "phone": "16 99999-8888",
         "active": True, "owner_ids": [3]},
        # De OUTRA organização: o token de admin do sistema lá devolve todo mundo.
        {"id": 9, "name": "Bia de Fora", "email": "bia@outra.com", "phone": "11 98888-1111",
         "active": True, "owner_ids": [5]},
    ])

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


async def test_puxar_do_meuplano_traz_so_a_organizacao_da_empresa(cenario):
    """Auditoria de 23/10/2026: com o token de admin do sistema, o meuPlano devolve as
    pessoas de TODAS as organizações (29 de 8), e o gerente da Splendor lia nome, e-mail e
    celular de gente de outra carteira. Agora só vem quem é da organização da empresa."""
    db, emp, conta, mp = cenario
    assert [p["id"] for p in await cadastro.pessoas_do_meuplano(db, emp.id)] == [7]
    with pytest.raises(HTTPException) as e:
        await cadastro.ligar(db, conta, emp.id, 9)
    assert e.value.status_code == 404


async def test_sem_a_organizacao_casada_nao_se_puxa_ninguem(cenario):
    """Fecha em vez de vazar: empresa sem a organização dela no meuPlano não lista pessoa
    nenhuma — e diz onde casar (Vínculos)."""
    db, emp, conta, mp = cenario
    emp.mp_tenant_id = None
    db.commit()
    with pytest.raises(HTTPException) as e:
        await cadastro.pessoas_do_meuplano(db, emp.id)
    assert e.value.status_code == 424 and "Vínculos" in e.value.detail


async def test_o_celular_do_adm_passa_pela_mesma_trava_e_grava_no_meuplano(cenario):
    """Auditoria de 24/10/2026: a central de notificações do adm gravava o celular direto —
    sem conferir se o número já era de outra conta (o bot deixava de reconhecer as duas) e
    sem gravar no meuPlano. Agora é o mesmo caminho do oem-gs."""
    from app.api.v1.painel_notificacoes import ContatoIn, salvar_contato

    db, emp, conta, mp = cenario
    await cadastro.ligar(db, conta, emp.id, 7)
    dono_do_numero = User(apelido="renan", nome="Renan", perfil=Perfil.GESTOR_EMPRESA, empresa_id=emp.id,
                          telefone="+5517997377626")
    db.add(dono_do_numero)
    db.commit()
    admin = User(apelido="adm", nome="Adm", perfil=Perfil.ADMINISTRADOR)

    with pytest.raises(HTTPException) as e:
        await salvar_contato(conta.id, ContatoIn(telefone="(17) 99737-7626"), db=db, gestor=admin)
    assert e.value.status_code == 409

    await salvar_contato(conta.id, ContatoIn(telefone="(16) 98888-1234"), db=db, gestor=admin)
    assert conta.telefone == "+5516988881234"
    assert mp.gravado[-1] == (7, {"phone": "(16) 9 8888-1234"})


async def test_sugere_ligar_quem_tem_o_mesmo_email_na_organizacao(cenario):
    db, emp, conta, mp = cenario
    conta.email = "ana@empresa.com"
    db.commit()
    sugestoes = cadastro.sugestoes(db, emp.id, mp.pessoas, [conta])
    assert sugestoes[conta.id]["id"] == 7
    # Ligada, não sugere mais; e quem é de OUTRA organização nunca é sugerido.
    await cadastro.ligar(db, conta, emp.id, 7)
    assert cadastro.sugestoes(db, emp.id, mp.pessoas, [conta]) == {}
    conta2 = User(apelido="bia", email="bia@outra.com", nome="Bia", perfil=Perfil.CLIENTE, empresa_id=emp.id)
    db.add(conta2)
    db.commit()
    assert cadastro.sugestoes(db, emp.id, mp.pessoas, [conta2]) == {}


async def test_o_nome_da_ficha_do_adm_grava_no_meuplano_tambem(cenario):
    """O mesmo furo do celular, no nome: a ficha do adm gravava direto, e a sincronização
    seguinte desfazia a edição de quem é ligado ao meuPlano."""
    from app.api.v1.painel_clientes import ClientePatch, editar_cliente

    db, emp, conta, mp = cenario
    await cadastro.ligar(db, conta, emp.id, 7)
    await editar_cliente(conta.id, ClientePatch(nome="Ana Souza Lima"), db=db, _=None)
    assert conta.nome == "Ana Souza Lima" and mp.gravado[-1] == (7, {"name": "Ana Souza Lima"})


def test_tirar_o_token_do_meuplano_nao_desliga_o_cadastro(cenario):
    from app.api.v1.empresa import desconectar_conta_do_cliente
    from app.models.integracao import Produto
    from app.models.user import VinculoProduto

    db, emp, conta, mp = cenario
    db.add(VinculoProduto(gs_user_id=conta.id, produto="meuplano", usuario_remoto_id="7",
                          usuario_remoto_nome="Ana Souza", token_cifrado="x", token_prefixo="mp_pat_x"))
    db.commit()
    gerente = User(apelido="ger", nome="Ger", perfil=Perfil.GESTOR_EMPRESA, empresa_id=emp.id)
    db.add(gerente)
    db.commit()
    desconectar_conta_do_cliente(conta.id, Produto.MEUPLANO, db=db, gerente=gerente)
    v = cadastro.vinculo_meuplano(db, conta.id)
    assert v is not None and v.usuario_remoto_id == "7" and v.token_cifrado is None


async def test_o_numero_que_ganha_conta_leva_as_mensagens_de_antes(db):
    """As 17 mensagens do celular do Kewyn ficavam como número solto no Log do bot."""
    from app.models.conversa_whatsapp import RegistroBot
    from app.models.empresa import Empresa
    from app.models.user import Perfil, User
    from app.services import cadastro

    emp = Empresa(nome="Splendor O&M")
    db.add(emp)
    db.commit()
    kewyn = User(apelido="kewyn", nome="Kewyn", perfil=Perfil.GESTOR_EMPRESA, empresa_id=emp.id)
    db.add_all([kewyn, RegistroBot(telefone="+5517997367733", resultado="sem_conta", pergunta="oi"),
                RegistroBot(telefone="+5517990000000", resultado="sem_conta", pergunta="outro")])
    db.commit()
    await cadastro.gravar(db, kewyn, emp.id, telefone="(17) 99736-7733")
    db.commit()
    dele = db.query(RegistroBot).filter_by(telefone="+5517997367733").one()
    assert (dele.gs_user_id, dele.empresa_id) == (kewyn.id, emp.id)
    assert db.query(RegistroBot).filter_by(telefone="+5517990000000").one().gs_user_id is None
