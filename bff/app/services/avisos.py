"""Quem recebe aviso de usina parada, e o que o aviso diz.

O caminho tem três filtros, e os três são obrigatórios:

1. **Permissão concedida** — o gestor marcou `notificacao.usina_parada` para
   aquela pessoa. Sem isso, ninguém recebe nada.
2. **Escopo de usina** — a pessoa só é avisada das usinas que o gestor liberou
   para ela. Avisar sobre uma usina que ela não pode nem abrir seria vazamento:
   o nome da usina de outro cliente chegaria na tela de bloqueio do celular.
3. **Aparelho registrado** — alguém pode ter a permissão e nunca ter aberto o
   app no celular, ou ter negado o aviso no Android. Sem token não há entrega.

**Idempotência é responsabilidade de quem chama.** Este módulo envia o que lhe
pedirem; chamá-lo duas vezes para a mesma parada manda dois avisos. O controle
de "já avisei sobre esta parada" fica no chamador, que é quem sabe a janela de
tempo — e é por isso que `paradas_por_usuario` devolve a chave de cada parada.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.plants import usinas_do_usuario
from app.models.integracao import Produto
from app.models.permissao import Dispositivo
from app.models.plant import PlantLink
from app.models.user import User
from app.services import permissoes, vinculos

CATEGORIA = "notificacao"
SUBCATEGORIA = "usina_parada"


@dataclass
class AvisoDeParada:
    usuario: User
    usina: PlantLink
    #: Nome do inversor parado, como o meuWatt o chama.
    inversor: str
    #: `slot-N` — identifica a posição física, que sobrevive à troca do aparelho.
    equipamento_id: str
    #: Chave estável desta parada, para o chamador não avisar duas vezes.
    chave: str


def _parados(monitoramento: Any) -> list[dict[str, Any]]:
    """Inversores em falha material, pela mesma régua das telas.

    `down` é o detector do mw-api afirmando parada aberta, e vence o `status`, que
    pode ainda dizer `normal`. Inversor ignorado pelo operador fica de fora: silenciá-lo
    foi decisão de quem opera, e acordar o dono de madrugada por causa dele seria
    discutir com essa decisão.
    """
    if not isinstance(monitoramento, dict):
        return []
    saida = []
    for inv in monitoramento.get("inverters") or []:
        if not isinstance(inv, dict) or inv.get("ignored"):
            continue
        estado = str(inv.get("status") or "").strip().lower()
        # `bedtime` é a usina dormindo — noite não é parada.
        if estado == "bedtime":
            continue
        if inv.get("down") is True or estado == "fault":
            saida.append(inv)
    return saida


async def paradas_por_usuario(db: Session) -> list[AvisoDeParada]:
    """Todos os avisos que caberiam agora, um por (pessoa, inversor parado).

    Consulta o monitoramento UMA vez por usina, mesmo quando dez pessoas têm acesso
    a ela: a leitura é a mesma, e repeti-la por pessoa multiplicaria a carga no
    meuWatt pelo número de clientes.
    """
    pessoas = permissoes.usuarios_com_permissao(db, CATEGORIA, SUBCATEGORIA)
    if not pessoas:
        return []

    # Escopo de cada pessoa, e o conjunto de usinas que precisamos consultar.
    escopos: dict[int, list[PlantLink]] = {p.id: usinas_do_usuario(db, p) for p in pessoas}
    alvos: dict[int, PlantLink] = {
        u.id: u for lista in escopos.values() for u in lista if u.mw_plant_slug
    }
    if not alvos:
        return []

    # Cada usina é lida com o token de ALGUÉM que tem acesso a ela — e uma vez só.
    #
    # Não existe mais credencial de serviço: quem lê o meuWatt é sempre uma pessoa. Mas a
    # propriedade que esta função protege continua valendo, e é a razão de ela existir
    # assim: a leitura de uma usina é a MESMA para todo mundo que a enxerga, então repeti-la
    # por pessoa multiplicaria a carga no meuWatt pelo número de clientes sem trazer um dado
    # novo. Basta um leitor por usina, e ele tem de ser alguém que legitimamente a vê.
    #
    # Usina cujos donos ainda não conectaram o meuWatt fica de fora, sem aviso. É o certo:
    # não temos como saber o estado dela, e calar é melhor do que inventar.
    leitor_da_usina: dict[int, int] = {}
    for pessoa in pessoas:
        if vinculos.obter(db, pessoa.id, Produto.MEUWATT) is None:
            continue
        for u in escopos.get(pessoa.id, []):
            leitor_da_usina.setdefault(u.id, pessoa.id)

    clientes: dict[int, Any] = {}
    estado: dict[int, list[dict[str, Any]]] = {}
    for link in alvos.values():
        dono = leitor_da_usina.get(link.id)
        if dono is None:
            continue
        try:
            if dono not in clientes:
                clientes[dono] = vinculos.cliente_meuwatt(db, dono)
            resposta = await clientes[dono].monitoramento_atual(link.mw_plant_slug)
        except Exception:  # noqa: BLE001
            # Usina fora do ar não gera aviso e não derruba as outras. Silêncio aqui é
            # correto: "não consegui ler" não é "parou".
            continue
        estado[link.id] = _parados(resposta)

    avisos: list[AvisoDeParada] = []
    for pessoa in pessoas:
        for link in escopos[pessoa.id]:
            for inv in estado.get(link.id, []):
                equipamento_id = str(inv.get("id") or "")
                nome = str(inv.get("name") or inv.get("serial_number") or "Inversor")
                avisos.append(
                    AvisoDeParada(
                        usuario=pessoa,
                        usina=link,
                        inversor=nome,
                        equipamento_id=equipamento_id,
                        # `down_since` entra na chave: o mesmo inversor parando de novo
                        # depois de voltar é um evento NOVO e merece aviso novo.
                        chave=f"{link.id}:{equipamento_id}:{inv.get('down_since') or ''}",
                    )
                )
    return avisos


def tokens_do_usuario(db: Session, usuario: User) -> list[str]:
    return list(
        db.scalars(select(Dispositivo.token).where(Dispositivo.user_id == usuario.id)).all()
    )


def texto_do_aviso(aviso: AvisoDeParada) -> tuple[str, str, dict[str, Any]]:
    """Título, corpo e a carga que o toque na notificação usa para abrir a tela certa.

    O nome da usina vai no TÍTULO porque é o que aparece na tela bloqueada quando o
    sistema corta o texto — quem tem sete usinas precisa saber qual antes de decidir
    se levanta da cama.
    """
    titulo = f"{aviso.usina.nome} · inversor parado"
    corpo = f"{aviso.inversor} parou de gerar. Toque para ver o equipamento."
    dados = {
        "tipo": "usina_parada",
        "usina_id": aviso.usina.id,
        "equipamento_id": aviso.equipamento_id,
    }
    return titulo, corpo, dados
