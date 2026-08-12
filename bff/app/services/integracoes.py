"""Lê a configuração das pontes e sabe testá-las.

O teste é o coração do painel: sem ele o gestor digita uma credencial e fica no escuro até
alguma tela do app falhar. Aqui ele descobre na hora — e com o motivo certo, porque
"credencial recusada", "endereço errado" e "servidor fora do ar" pedem correções diferentes.
"""

from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.meuplano import MeuPlanoClient
from app.clients.meuwatt import MeuWattClient
from app.core.cripto import SegredoInvalido, cifrar, decifrar
from app.models.integracao import EstadoTeste, Integracao, Produto


class ResultadoTeste:
    """O que o painel mostra depois de testar. `ok` decide a cor; `detalhe` explica."""

    def __init__(self, ok: bool, detalhe: str, usinas: int | None = None) -> None:
        self.ok = ok
        self.detalhe = detalhe
        self.usinas = usinas


def obter(db: Session, produto: Produto) -> Integracao | None:
    return db.scalar(select(Integracao).where(Integracao.produto == produto))


def listar(db: Session) -> dict[Produto, Integracao | None]:
    """Sempre devolve as duas chaves — a tela mostra o produto não configurado também."""
    existentes = {i.produto: i for i in db.scalars(select(Integracao)).all()}
    return {p: existentes.get(p) for p in Produto}


def salvar(
    db: Session,
    produto: Produto,
    base_url: str,
    usuario: str,
    senha: str | None,
) -> Integracao:
    """Cria ou atualiza. `senha=None` preserva a que já está gravada — é o que permite
    corrigir só o endereço sem redigitar a credencial."""
    integracao = obter(db, produto)

    if integracao is None:
        if not senha:
            raise ValueError("A senha é obrigatória ao configurar a integração pela primeira vez.")
        integracao = Integracao(produto=produto, base_url="", usuario_servico="", senha_cifrada="")
        db.add(integracao)

    integracao.base_url = base_url.rstrip("/")
    integracao.usuario_servico = usuario
    if senha:
        integracao.senha_cifrada = cifrar(senha)

    # Qualquer alteração invalida o teste anterior: a credencial pode ter mudado.
    integracao.estado = EstadoTeste.NUNCA
    integracao.testada_em = None
    integracao.detalhe_teste = None
    integracao.usinas_visiveis = None

    db.commit()
    db.refresh(integracao)
    return integracao


async def testar(db: Session, produto: Produto) -> ResultadoTeste:
    """Autentica de verdade contra o upstream e conta o que a conta de serviço enxerga.

    Contar usinas não é enfeite: uma credencial pode ser aceita e mesmo assim não ver
    nada, o que faria o app abrir vazio sem erro nenhum. É melhor descobrir aqui.
    """
    integracao = obter(db, produto)
    if integracao is None:
        return ResultadoTeste(False, "Integração ainda não configurada.")

    try:
        senha = decifrar(integracao.senha_cifrada)
    except SegredoInvalido as exc:
        return _registrar(db, integracao, ResultadoTeste(False, str(exc)))

    try:
        if produto is Produto.MEUWATT:
            cliente = MeuWattClient(base_url=integracao.base_url)
            dados = await cliente.autenticar(integracao.usuario_servico, senha)
            if not dados:
                return _registrar(
                    db, integracao, ResultadoTeste(False, "Credencial recusada pelo meuWatt.")
                )
            usinas = await cliente.usinas(token=dados["access_token"])
        else:
            cliente_mp = MeuPlanoClient(base_url=integracao.base_url)
            dados = await cliente_mp.autenticar(integracao.usuario_servico, senha)
            if not dados:
                return _registrar(
                    db, integracao, ResultadoTeste(False, "Credencial recusada pelo meuPlano.")
                )
            usinas = await cliente_mp.usinas(token=dados["access_token"])

    except httpx.ConnectError:
        return _registrar(
            db,
            integracao,
            ResultadoTeste(False, "Não foi possível alcançar o endereço. Confira a URL."),
        )
    except httpx.TimeoutException:
        return _registrar(
            db, integracao, ResultadoTeste(False, "O servidor não respondeu a tempo.")
        )
    except httpx.HTTPStatusError as exc:
        return _registrar(
            db,
            integracao,
            ResultadoTeste(False, f"O servidor respondeu {exc.response.status_code}."),
        )
    except Exception as exc:  # noqa: BLE001 — o painel precisa mostrar qualquer falha
        return _registrar(db, integracao, ResultadoTeste(False, f"{type(exc).__name__}: {exc}"))

    quantidade = len(usinas)
    if quantidade == 0:
        return _registrar(
            db,
            integracao,
            ResultadoTeste(
                False,
                "Credencial aceita, mas esta conta não enxerga nenhuma usina. "
                "Dê acesso a ela no produto de origem.",
                usinas=0,
            ),
        )

    return _registrar(
        db,
        integracao,
        ResultadoTeste(True, f"Conectado. {quantidade} usina(s) visíveis.", usinas=quantidade),
    )


def _registrar(db: Session, integracao: Integracao, resultado: ResultadoTeste) -> ResultadoTeste:
    integracao.estado = EstadoTeste.OK if resultado.ok else EstadoTeste.FALHOU
    integracao.testada_em = datetime.now(UTC)
    integracao.detalhe_teste = resultado.detalhe
    integracao.usinas_visiveis = resultado.usinas
    db.commit()
    return resultado


async def cliente_meuwatt(db: Session) -> MeuWattClient:
    """Cliente já autenticado com a credencial de serviço gravada."""
    integracao = obter(db, Produto.MEUWATT)
    if integracao is None or not integracao.ativa:
        raise RuntimeError("A ponte com o meuWatt não está configurada.")
    return MeuWattClient(
        base_url=integracao.base_url,
        usuario=integracao.usuario_servico,
        senha=decifrar(integracao.senha_cifrada),
    )


async def cliente_meuplano(db: Session) -> MeuPlanoClient:
    integracao = obter(db, Produto.MEUPLANO)
    if integracao is None or not integracao.ativa:
        raise RuntimeError("A ponte com o meuPlano não está configurada.")
    return MeuPlanoClient(
        base_url=integracao.base_url,
        usuario=integracao.usuario_servico,
        senha=decifrar(integracao.senha_cifrada),
    )
