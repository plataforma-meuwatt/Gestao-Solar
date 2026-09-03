"""Abrir UMA tarefa da OS — e a trava que impede ler a ficha de outro dono.

O dono, na OS 1016 (03/09/2026): *"tem as tarefas, porém elas não são clicáveis, são como
checklist. Eu preciso ABRIR as tarefas e ver as respostas delas, preciso gerar os PDFs
delas"*. As rotas nasceram daí.

O que estes testes protegem, em ordem de gravidade:

1. **A tarefa tem de ser DAQUELA OS.** Conferir só a ordem não basta: com um `so_id`
   legítimo e um `task_id` de outra ordem, a ficha de outro cliente sairia por aqui — e
   ninguém reclamaria, porque quem viu demais não sabe que viu.
2. **O PDF passa pelo mesmo portão.** Um caminho de arquivo que esqueça a checagem é um
   vazamento com laudo assinado dentro.
3. **A resposta é a mesma da lista.** A tela de detalhe usa o mesmo `_tarefa_out` dos itens
   da OS; dois formatos para a mesma tarefa viram duas verdades na leitura do dono.

Nada de rede: o cliente do meuPlano entra como fantasia.
"""

import pytest
from fastapi import HTTPException

from app.api.v1.manutencao import _tarefa_autorizada, _tarefa_out
from app.core.security import gerar_hash_senha
from app.models.plant import PlantLink
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


class ClienteFalso:
    """O meuPlano como fantasia: uma OS, uma tarefa dela e uma tarefa alheia."""

    def __init__(self, ordem, tarefas):
        self.ordem = ordem
        self.tarefas = tarefas
        self.pdf_pedido_para = None

    async def ordem_servico(self, so_id):
        if so_id != self.ordem["id"]:
            raise LookupError("não existe")
        return self.ordem

    async def tarefa(self, task_id):
        if task_id not in self.tarefas:
            raise LookupError("não existe")
        return self.tarefas[task_id]

    async def pdf_da_tarefa(self, task_id):
        self.pdf_pedido_para = task_id
        return b"%PDF-1.4 fingido"


@pytest.fixture
def cenario(db, dono, usinas, monkeypatch):
    """Usina do dono com a OS 1016; a tarefa 6940 é dela, a 999 é de outra ordem."""
    minha, _outra = usinas
    _conceder(db, dono, minha)
    ordem = {"id": 1016, "plant_id": minha.mp_usina_id, "name": "Preventiva agosto"}
    tarefas = {
        6940: {"id": 6940, "os_id": 1016, "name": "CFTV - Inspeção do Sistema",
               "status": "REALIZADA", "verdict_status": "APPROVED"},
        999: {"id": 999, "os_id": 2222, "name": "Ensaio de outra ordem",
              "status": "REALIZADA"},
    }
    cliente = ClienteFalso(ordem, tarefas)

    async def _cliente(_db):
        return cliente

    monkeypatch.setattr("app.api.v1.manutencao.integracoes.cliente_meuplano", _cliente)
    return cliente


@pytest.mark.asyncio
async def test_abre_a_tarefa_da_ordem(db, dono, cenario):
    _cliente, tarefa, link = await _tarefa_autorizada(db, dono, 1016, 6940)
    assert tarefa["id"] == 6940
    assert isinstance(link, PlantLink)


@pytest.mark.asyncio
async def test_tarefa_de_outra_ordem_nao_abre(db, dono, cenario):
    """404, não 403: confirmar a existência já seria contar demais."""
    with pytest.raises(HTTPException) as e:
        await _tarefa_autorizada(db, dono, 1016, 999)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_tarefa_inexistente_nao_abre(db, dono, cenario):
    with pytest.raises(HTTPException) as e:
        await _tarefa_autorizada(db, dono, 1016, 12345)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_ordem_de_outra_usina_nao_abre(db, dono, usinas, cenario):
    """A OS existe, mas é de usina que este dono não enxerga."""
    cenario.ordem = {**cenario.ordem, "plant_id": 987654}
    with pytest.raises(HTTPException) as e:
        await _tarefa_autorizada(db, dono, 1016, 6940)
    assert e.value.status_code == 404


def test_saida_da_tarefa_e_a_mesma_da_lista():
    """A tela de detalhe e o item da lista falam da mesma tarefa com o mesmo formato."""
    bruta = {"id": 6940, "os_id": 1016, "name": "CFTV - Inspeção do Sistema",
             "status": "REALIZADA", "verdict_status": "APPROVED",
             "plan_type_label": "CFTV", "equipment_path": "Skid 04 > Câmera 2"}
    out = _tarefa_out(bruta)
    assert out.id == 6940
    assert out.nome
    assert out.feita is True
    assert out.grupo == "CFTV"
    assert out.equipamento == "Skid 04 > Câmera 2"
