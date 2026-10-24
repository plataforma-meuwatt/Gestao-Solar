"""O cadastro da pessoa — o Gestão Solar é a BASE de todos, e o meuPlano é um vínculo.

Decisão do dono (23/10/2026):

- **Quem tem conta no meuPlano** fica LIGADO à pessoa de lá (`gs_vinculos_produto`, produto
  meuplano, `usuario_remoto_id`). Nome, e-mail e celular viram UMA base: editar aqui grava lá
  (`gravar`), e o que mudar lá chega aqui (`sincronizar`).
- **Quem só tem meuWatt** (comum — o cadastro do meuWatt não tem telefone) ou nada: cadastrado
  do zero aqui. Não há o que sincronizar.

Ligar sem token NÃO dá login no meuPlano: o "Entrar com Gestão Solar" de lá só aceita quem
foi registrado pelo fluxo do token (`login_externo.habilitar`). Aqui é só o cadastro.

A credencial que lê e grava no meuPlano é a DA EMPRESA (o gerente opera as pessoas dela), e
precisa da permissão de usuários lá — sem ela, a frase do meuPlano chega ao gerente.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.telefone import TelefoneInvalido, e_celular, exibir, normalizar
from app.models.integracao import Produto
from app.core.tokens_produto import NOME
from app.models.user import BOT_TOKEN, User, VinculoProduto

log = logging.getLogger("gs.cadastro")


async def _mp(db: Session, empresa_id: int):
    from app.services import integracoes
    try:
        return await integracoes.cliente_meuplano(db, empresa_id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_424_FAILED_DEPENDENCY, str(exc)) from None


def _falha_do_meuplano(exc: Exception) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detalhe = (exc.response.json() or {}).get("detail")
        except ValueError:
            detalhe = None
        if exc.response.status_code in (401, 403):
            return HTTPException(status.HTTP_424_FAILED_DEPENDENCY, detalhe or (
                "A conta da sua empresa no meuPlano não pode administrar usuários lá. "
                "Use o token de quem tem essa permissão em Conexões."))
        return HTTPException(status.HTTP_502_BAD_GATEWAY, f"O meuPlano recusou: {detalhe or exc.response.status_code}")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "Não foi possível falar com o meuPlano.")


def vinculo_meuplano(db: Session, conta_id: int) -> VinculoProduto | None:
    return db.scalar(select(VinculoProduto).where(
        VinculoProduto.gs_user_id == conta_id, VinculoProduto.produto == Produto.MEUPLANO.value))


def celular_livre(db: Session, valor: str | None, conta_id: int | None) -> str | None:
    """Normaliza e confere que o celular não é de outra conta ATIVA — em QUALQUER empresa.
    Um número com dois donos deixaria o assistente sem saber com quem está falando."""
    try:
        tel = normalizar(valor)
    except TelefoneInvalido as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if tel is None:
        return None
    if not e_celular(tel):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe um CELULAR (o WhatsApp não chega em fixo).")
    q = select(User.id).where(User.telefone == tel, User.ativo)
    if conta_id is not None:
        q = q.where(User.id != conta_id)
    if db.scalar(q) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este celular já está em outra conta do Gestão Solar.")
    return tel


def liberar_bot(conta: User, campo: str, valor: bool) -> None:
    """Liga/desliga uma parte do assistente. LIGAR exige o celular e o token PRÓPRIO da pessoa
    naquele produto (regra do dono, 23/10/2026). Manter ligada não reconfere: o que ficou sem
    token já está parado (`User.bot_ativo`), e reconferir travaria salvar o resto do cadastro."""
    if valor and not getattr(conta, campo):
        from app.services import assistente_helper

        if campo == "bot_helper" and not assistente_helper.configurado():
            # Sem a porta do helper configurada neste servidor, liberar prometeria uma
            # resposta que não vem.
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "O helper ainda não está ligado neste servidor (falta a porta do "
                                "bot do helper). Fale com quem administra a plataforma.")
        if not conta.telefone:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Cadastre o celular antes de liberar o bot do WhatsApp.")
        produto = BOT_TOKEN[campo]
        if not conta.tem_token(produto):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Cole o token do {NOME[Produto(produto)]} desta pessoa antes de liberar: "
                                "o assistente só responde com o token dela.")
    setattr(conta, campo, valor)


# --------------------------------------------------------------------------- leitura
def _organizacao(db: Session, empresa_id: int) -> int:
    """A organização (`owners.id`) desta empresa no meuPlano — casada em oem-gs → Vínculos.

    Sem ela não se lista ninguém: o token de quem é admin do SISTEMA lá devolve as pessoas
    de TODAS as organizações (29 de 8 empresas, medido em 23/10/2026), e o gerente desta
    empresa leria nome, e-mail e celular de gente de outra carteira. Fecha, em vez de vazar.
    """
    from app.models.empresa import Empresa

    empresa = db.get(Empresa, empresa_id)
    if empresa is None or empresa.mp_tenant_id is None:
        raise HTTPException(
            status.HTTP_424_FAILED_DEPENDENCY,
            "Ligue esta empresa à organização dela no meuPlano (Vínculos) antes de puxar "
            "pessoas de lá — sem isso viriam pessoas de outras empresas.",
        )
    return empresa.mp_tenant_id


def _da_organizacao(pessoas: list[dict[str, Any]], organizacao: int) -> list[dict[str, Any]]:
    return [p for p in pessoas if organizacao in (p.get("owner_ids") or [])]


async def pessoas_do_meuplano(db: Session, empresa_id: int) -> list[dict[str, Any]]:
    """As pessoas da ORGANIZAÇÃO desta empresa no meuPlano, e a quem cada uma já está ligada aqui."""
    organizacao = _organizacao(db, empresa_id)
    mp = await _mp(db, empresa_id)
    try:
        pessoas = _da_organizacao(await mp.usuarios_admin(), organizacao)
    except Exception as exc:                               # noqa: BLE001
        raise _falha_do_meuplano(exc) from None
    ligadas = dict(db.execute(
        select(VinculoProduto.usuario_remoto_id, User.apelido)
        .join(User, User.id == VinculoProduto.gs_user_id)
        .where(VinculoProduto.produto == Produto.MEUPLANO.value, User.empresa_id == empresa_id)).all())
    return [{"id": p.get("id"), "nome": p.get("name") or p.get("username") or p.get("email"),
             "email": p.get("email"), "telefone": p.get("phone"), "ativo": p.get("active", True),
             "ligada_a": ligadas.get(str(p.get("id")))} for p in pessoas]


# --------------------------------------------------------------------------- vínculo
def _aplicar_da_pessoa(db: Session, conta: User, p: dict[str, Any]) -> list[str]:
    """Traz nome/e-mail/celular do meuPlano para cá. Devolve o que NÃO pôde vir (e por quê)."""
    avisos: list[str] = []
    if p.get("name"):
        conta.nome = p["name"]
    if p.get("email"):
        conta.email = p["email"]
    if p.get("phone"):
        try:
            conta.telefone = celular_livre(db, p["phone"], conta.id)
            adotar_mensagens(db, conta)
        except HTTPException as exc:
            avisos.append(f"Celular do meuPlano não veio: {exc.detail}")
    return avisos


def adotar_mensagens(db: Session, conta: User) -> None:
    """O número ganhou conta: as mensagens que ele mandou ao bot ANTES (sem cadastro) passam a
    ser desta pessoa no Log do bot — e aparecem no oem da empresa dela. As 17 do celular do
    Kewyn ficavam como número solto (avaliação de 24/10/2026)."""
    from sqlalchemy import update

    from app.models.conversa_whatsapp import RegistroBot

    if conta.telefone:
        db.execute(update(RegistroBot)
                   .where(RegistroBot.telefone == conta.telefone, RegistroBot.gs_user_id.is_(None))
                   .values(gs_user_id=conta.id, empresa_id=conta.empresa_id))


async def ligar(db: Session, conta: User, empresa_id: int, mp_user_id: int) -> list[str]:
    """Liga a conta daqui à pessoa do meuPlano e puxa o cadastro de lá."""
    organizacao = _organizacao(db, empresa_id)
    try:
        pessoas = _da_organizacao(await (await _mp(db, empresa_id)).usuarios_admin(), organizacao)
    except HTTPException:
        raise
    except Exception as exc:                               # noqa: BLE001
        raise _falha_do_meuplano(exc) from None
    pessoa = next((p for p in pessoas if p.get("id") == mp_user_id), None)
    if pessoa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Essa pessoa não está na organização da sua empresa no meuPlano.")
    ja = db.scalar(select(User.apelido).join(VinculoProduto, VinculoProduto.gs_user_id == User.id).where(
        VinculoProduto.produto == Produto.MEUPLANO.value, VinculoProduto.usuario_remoto_id == str(mp_user_id),
        User.id != conta.id))
    if ja:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Essa pessoa do meuPlano já está ligada a '{ja}'.")
    v = vinculo_meuplano(db, conta.id)
    if v is not None and v.token_cifrado and v.usuario_remoto_id != str(mp_user_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "O token desta conta é de OUTRA pessoa no meuPlano. Remova o token antes de ligar.")
    if v is None:
        v = VinculoProduto(gs_user_id=conta.id, produto=Produto.MEUPLANO.value, usuario_remoto_id=str(mp_user_id))
        db.add(v)
    v.usuario_remoto_id = str(mp_user_id)
    v.usuario_remoto_email = pessoa.get("email")
    v.usuario_remoto_nome = pessoa.get("name")
    avisos = _aplicar_da_pessoa(db, conta, pessoa)
    db.commit()
    return avisos


def desligar(db: Session, conta: User) -> None:
    v = vinculo_meuplano(db, conta.id)
    if v is None:
        return
    if v.token_cifrado:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Esta conta tem o token do meuPlano: remova o token (botão Token) para desligar.")
    db.delete(v)
    db.commit()


# --------------------------------------------------------------------------- escrita
async def gravar(db: Session, conta: User, empresa_id: int, *, nome: str | None = None,
                 email: str | None = None, telefone: str | None = None) -> None:
    """Muda o cadastro. Ligada ao meuPlano: grava LÁ primeiro — se o meuPlano recusar, nada
    muda aqui, e as duas bases continuam iguais."""
    novo_tel = celular_livre(db, telefone, conta.id) if telefone is not None else conta.telefone
    v = vinculo_meuplano(db, conta.id)
    if v is not None:
        corpo = {k: val for k, val in (("name", nome), ("email", email)) if val is not None}
        if telefone is not None:
            corpo["phone"] = exibir(novo_tel) or ""
        if corpo:
            try:
                await (await _mp(db, empresa_id)).atualizar_usuario_admin(int(v.usuario_remoto_id), corpo)
            except HTTPException:
                raise
            except Exception as exc:                       # noqa: BLE001
                raise _falha_do_meuplano(exc) from None
    if nome is not None:
        conta.nome = nome
    if email is not None:
        conta.email = email or None
    if telefone is not None:
        conta.telefone = novo_tel
        adotar_mensagens(db, conta)
        if novo_tel is None:
            conta.bot_meuplano = conta.bot_meuwatt = conta.bot_helper = False


async def todas_as_pessoas(db: Session, empresa_id: int) -> list[dict[str, Any]] | None:
    """As pessoas que a credencial da empresa enxerga no meuPlano, numa ida só — ou `None`
    sem o meuPlano (melhor esforço: a tela mostra o que está guardado)."""
    try:
        return await (await _mp(db, empresa_id)).usuarios_admin()
    except Exception:                                      # noqa: BLE001
        log.warning("cadastro: ler as pessoas do meuPlano falhou (empresa %s)", empresa_id, exc_info=True)
        return None


def sugestoes(db: Session, empresa_id: int, pessoas: list[dict[str, Any]] | None,
              contas: list[User]) -> dict[int, dict[str, Any]]:
    """Conta daqui ainda SEM ligação ao meuPlano cujo e-mail é o de uma pessoa da organização
    da empresa lá, ainda livre: `{conta_id: pessoa}`. É o "ligar" sugerido — a auditoria de
    24/10/2026 achou Camila e kewyn no meuPlano, com celular, e "só do Gestão Solar" aqui."""
    from app.models.empresa import Empresa

    empresa = db.get(Empresa, empresa_id)
    if not pessoas or empresa is None or empresa.mp_tenant_id is None:
        return {}
    ligadas = set(db.scalars(select(VinculoProduto.usuario_remoto_id).where(
        VinculoProduto.produto == Produto.MEUPLANO.value)).all())
    contas_ligadas = set(db.scalars(select(VinculoProduto.gs_user_id).where(
        VinculoProduto.produto == Produto.MEUPLANO.value)).all())
    por_email = {
        (p.get("email") or "").strip().lower(): p
        for p in _da_organizacao(pessoas, empresa.mp_tenant_id)
        if p.get("email") and str(p.get("id")) not in ligadas
    }
    return {
        c.id: por_email[c.email.strip().lower()]
        for c in contas
        if c.id not in contas_ligadas and c.email and c.email.strip().lower() in por_email
    }


async def sincronizar(db: Session, empresa_id: int, pessoas: list[dict[str, Any]] | None = None) -> int:
    """O que mudou no meuPlano chega aqui (nome, e-mail, celular das contas LIGADAS). Melhor
    esforço: sem o meuPlano, a tela mostra o que está guardado. Devolve quantas mudaram.
    `pessoas`: a lista já lida (para a tela não ir duas vezes ao meuPlano)."""
    ligadas = db.execute(
        select(User, VinculoProduto.usuario_remoto_id).join(VinculoProduto, VinculoProduto.gs_user_id == User.id)
        .where(VinculoProduto.produto == Produto.MEUPLANO.value, User.empresa_id == empresa_id)).all()
    if not ligadas:
        return 0
    if pessoas is None:
        pessoas = await todas_as_pessoas(db, empresa_id)
        if pessoas is None:
            return 0
    pessoas = {str(p.get("id")): p for p in pessoas}
    mudou = 0
    for conta, remoto in ligadas:
        p = pessoas.get(remoto)
        if p is None:
            continue
        antes = (conta.nome, conta.email, conta.telefone)
        for aviso in _aplicar_da_pessoa(db, conta, p):
            log.info("cadastro: %s — %s", conta.apelido, aviso)
        mudou += antes != (conta.nome, conta.email, conta.telefone)
    if mudou:
        db.commit()
    return mudou
