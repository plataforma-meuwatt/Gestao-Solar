"""As proprietárias, as donas das usinas, no GS (Plano Casa GS, R11). Ver `models/empresa.Proprietaria`.

Quem mexe é o gerente da O&M que a atende (o recorte é a empresa da sessão), e a plataforma lê. A importação traz do
meuPlano as organizações PROPRIETARIAS que a conta da empresa enxerga, a dona de cada usina e de quem cada dono de
usina é, sem desfazer o que já estiver gravado aqui.
"""
import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.empresa import Proprietaria
from app.models.plant import PlantLink
from app.models.user import Perfil, User


class RegraDaProprietaria(ValueError):
    """A frase vai à tela."""


def da_empresa(db: Session, empresa_id: int) -> list[Proprietaria]:
    return list(db.scalars(select(Proprietaria).where(Proprietaria.empresa_id == empresa_id)
                           .order_by(Proprietaria.nome)).all())


def da_empresa_ou_none(db: Session, empresa_id: int, proprietaria_id: int) -> Proprietaria | None:
    p = db.get(Proprietaria, proprietaria_id)
    return p if p is not None and p.empresa_id == empresa_id else None


def _nome(texto: str | None) -> str:
    nome = re.sub(r"\s+", " ", texto or "").strip()
    if len(nome) < 2:
        raise RegraDaProprietaria("A proprietária precisa de um nome.")
    if len(nome) > 255:
        raise RegraDaProprietaria("O nome tem no máximo 255 caracteres.")
    return nome


def _documento(texto: str | None) -> str | None:
    digitos = re.sub(r"\D", "", texto or "")
    if not digitos:
        return None
    if len(digitos) not in (11, 14):
        raise RegraDaProprietaria("O documento é um CPF (11 números) ou um CNPJ (14).")
    return digitos


def salvar(db: Session, empresa_id: int, *, nome: str | None, documento: str | None = None,
           ativa: bool | None = None, proprietaria: Proprietaria | None = None) -> Proprietaria:
    """Cria (sem `proprietaria`) ou muda. Nome único dentro da O&M. Não confirma."""
    p = proprietaria or Proprietaria(empresa_id=empresa_id)
    if nome is not None or proprietaria is None:
        novo = _nome(nome)
        outra = db.scalar(select(Proprietaria.id).where(Proprietaria.empresa_id == empresa_id,
                                                        func.lower(Proprietaria.nome) == novo.lower(),
                                                        Proprietaria.id != (p.id or -1)))
        if outra is not None:
            raise RegraDaProprietaria(f"Já existe a proprietária {novo} nesta empresa.")
        p.nome = novo
    if documento is not None:
        p.documento = _documento(documento)
    if ativa is not None:
        p.ativa = ativa
    if proprietaria is None:
        db.add(p)
    db.flush()
    return p


def definir_usinas(db: Session, p: Proprietaria, usina_ids: list[int], *, por: User | None, sistema: str = "gs"
                   ) -> list[str]:
    """A dona destas usinas passa a ser `p` (e deixa de ser das que saíram da lista). Só usinas da O&M dela.
    Devolve os nomes das que mudaram. Não confirma."""
    from app.services import dados_da_usina
    da_om = {u.id: u for u in db.scalars(select(PlantLink).where(PlantLink.empresa_id == p.empresa_id))}
    fora = [i for i in usina_ids if i not in da_om]
    if fora:
        raise RegraDaProprietaria("Só as usinas desta empresa entram na proprietária.")
    mudaram = []
    for u in da_om.values():
        quer = u.id in set(usina_ids)
        if quer and u.proprietaria_id != p.id:
            antes = db.get(Proprietaria, u.proprietaria_id).nome if u.proprietaria_id else None
            u.proprietaria_id = p.id
        elif not quer and u.proprietaria_id == p.id:
            antes = p.nome
            u.proprietaria_id = None
        else:
            continue
        dados_da_usina.historico(db, u, "proprietaria", antes, p.nome if quer else None, por=por, sistema=sistema)
        u.atualizado_em = datetime.now(UTC)
        mudaram.append(u.nome)
    return mudaram


def definir_pessoas(db: Session, p: Proprietaria, user_ids: list[int], *, empresa_contas: set[int]) -> list[str]:
    """Os donos de usina desta proprietária: só contas de cliente da O&M (`empresa_contas`). Não confirma."""
    contas = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids or [-1])))}
    ruins = [i for i in user_ids if i not in contas or i not in empresa_contas
             or contas[i].perfil is not Perfil.CLIENTE]
    if ruins:
        raise RegraDaProprietaria("Só donos de usina desta empresa entram na proprietária.")
    mudaram = []
    for u in db.scalars(select(User).where(User.proprietaria_id == p.id)):
        if u.id not in contas:
            sair_das_usinas(db, u, u.proprietaria_id)
            u.proprietaria_id = None
            mudaram.append(u.nome)
    for u in contas.values():
        if u.proprietaria_id != p.id:
            if u.proprietaria_id is not None:              # vinha de OUTRA proprietária: sai das usinas de lá
                sair_das_usinas(db, u, u.proprietaria_id)
            u.proprietaria_id = p.id
            mudaram.append(u.nome)
    return mudaram


def sair_das_usinas(db: Session, u: User, proprietaria_id: int) -> int:
    """Quem sai de uma proprietária sai das usinas dela: ficar com elas deixava a usina com dois donos de fora um do
    outro, e salvar a concessão de qualquer um dos dois passava a falhar. Não confirma."""
    from app.models.user import UserPlantAccess
    from app.services import notificacoes
    usinas = select(PlantLink.id).where(PlantLink.proprietaria_id == proprietaria_id)
    tiradas = list(db.scalars(select(UserPlantAccess).where(UserPlantAccess.user_id == u.id,
                                                            UserPlantAccess.plant_link_id.in_(usinas))))
    for a in tiradas:
        db.delete(a)
    notificacoes.limpar_usinas(db, u.id, [a.plant_link_id for a in tiradas])
    return len(tiradas)


def dar_usinas(db: Session, p: Proprietaria) -> list[tuple[User, int]]:
    """Cada pessoa da proprietária passa a receber TODAS as usinas dela (soma às que já recebe; nada sai). É a
    concessão de sempre (`clientes.definir_usinas`), então o que o dono vê continua num lugar só. Confere TODAS as
    pessoas antes de gravar a primeira (cada concessão confirma: um conflito no meio deixava as de antes gravadas), e
    só mexe nas usinas desta empresa (a pessoa que também é de outra O&M fica com as de lá como estão)."""
    from sqlalchemy import or_

    from app.models.user import UserPlantAccess
    from app.services import clientes
    usinas = [u.id for u in db.scalars(select(PlantLink).where(PlantLink.proprietaria_id == p.id))]
    pessoas = list(db.scalars(select(User).where(User.proprietaria_id == p.id, User.ativo).order_by(User.id)))
    conflitos = []
    for pessoa in pessoas:
        donos = clientes._donos_por_usina(db, exceto=pessoa.id, proprietaria=p.id)
        conflitos += [f"“{db.get(PlantLink, pid).nome}” já é de {donos[pid]}" for pid in usinas if pid in donos]
    if conflitos:
        raise clientes.RegraDeNegocio("Cada usina pertence a um dono só (ou às pessoas da proprietária dela). "
                                      + "; ".join(sorted(set(conflitos))) + ". Nada foi concedido.")
    feitas = []
    for pessoa in pessoas:
        daqui = set(db.scalars(select(UserPlantAccess.plant_link_id).join(
            PlantLink, PlantLink.id == UserPlantAccess.plant_link_id).where(
            UserPlantAccess.user_id == pessoa.id,
            or_(PlantLink.empresa_id == p.empresa_id, PlantLink.empresa_id.is_(None)))))
        novas = set(usinas) - daqui
        if novas:
            clientes.definir_usinas(db, pessoa, sorted(daqui | novas), empresa_id=p.empresa_id)
        feitas.append((pessoa, len(novas)))
    return feitas


async def importar_do_meuplano(db: Session, empresa_id: int, *, por: User | None) -> list[str]:
    """As PROPRIETARIAS do meuPlano que a conta da empresa enxerga, a dona de cada usina daqui ligada ao meuPlano e de
    quem cada dono de usina é. Só preenche: proprietária que já existe (pelo `mp_owner_id`) não é renomeada, a usina
    que já tem dona fica com ela e a pessoa que já tem proprietária também. Devolve o que fez, em frases. Não
    confirma."""
    from app.services import integracoes
    cliente = await integracoes.cliente_meuplano(db, empresa_id)
    donas = await cliente._get("/api/v1/meuacesso/owners/", kind="PROPRIETARIA")
    donas = donas if isinstance(donas, list) else (donas or {}).get("items") or []
    feito = []
    por_mp: dict[int, Proprietaria] = {p.mp_owner_id: p for p in da_empresa(db, empresa_id) if p.mp_owner_id}
    for d in donas:
        if not isinstance(d, dict) or not str(d.get("id", "")).isdigit():
            continue
        mp_id = int(d["id"])
        if mp_id in por_mp:
            continue
        ja_de_outra = db.scalar(select(Proprietaria).where(Proprietaria.mp_owner_id == mp_id))
        if ja_de_outra is not None:                    # é cliente de outra O&M aqui: não se duplica nem se nomeia
            feito.append(f"Organização {mp_id} do meuPlano: já é cliente de outra O&M no GS (não foi trazida)")
            continue
        nome = _nome(d.get("name") or d.get("nome") or f"Organização {mp_id} do meuPlano")
        existente = db.scalar(select(Proprietaria).where(Proprietaria.empresa_id == empresa_id,
                                                         func.lower(Proprietaria.nome) == nome.lower()))
        if existente is not None and existente.mp_owner_id is None:
            existente.mp_owner_id = mp_id                # a de mesmo nome cadastrada à mão: liga
            por_mp[mp_id] = existente
            feito.append(f"{nome}: ligada à organização {mp_id} do meuPlano")
            continue
        try:
            doc = _documento(d.get("document") or d.get("documento"))
        except RegraDaProprietaria:
            doc = None
        p = Proprietaria(empresa_id=empresa_id, nome=nome, documento=doc, mp_owner_id=mp_id)
        db.add(p)
        db.flush()
        por_mp[mp_id] = p
        feito.append(f"{nome}: criada (organização {mp_id} do meuPlano)")
    # a dona de cada usina: o `owner_id` da usina no meuPlano
    usinas_mp = {int(u["id"]): u for u in await cliente.usinas() if isinstance(u, dict) and str(u.get("id", "")).isdigit()}
    from app.services import dados_da_usina
    for link in db.scalars(select(PlantLink).where(PlantLink.empresa_id == empresa_id, PlantLink.mp_usina_id.isnot(None))):
        u = usinas_mp.get(link.mp_usina_id) or {}
        # a dona é o vínculo PROPRIETARIA da usina lá (`usina_owners`, devolvido em `proprietaria_owner_id`, nulo quando
        # a usina não tem dona); o `owner_id` é o campo antigo (pode ser a prestadora) e só vale num meuPlano que ainda
        # não manda a chave nova
        dona = por_mp.get(u["proprietaria_owner_id"] if "proprietaria_owner_id" in u else u.get("owner_id"))
        if dona is None or link.proprietaria_id is not None:
            continue
        link.proprietaria_id = dona.id
        dados_da_usina.historico(db, link, "proprietaria", None, dona.nome, por=por, sistema="meuplano",
                                 motivo="importado do meuPlano")
        link.atualizado_em = datetime.now(UTC)
        feito.append(f"{link.nome}: dona {dona.nome}")
    # de quem cada dono de usina é: a organização da conta dele no meuPlano
    from app.models.user import VinculoProduto
    pessoas_mp = {int(u["id"]): u for u in await cliente.usuarios_admin() if isinstance(u, dict)
                  and str(u.get("id", "")).isdigit()}
    donos = db.execute(select(User, VinculoProduto.usuario_remoto_id).join(
        VinculoProduto, VinculoProduto.gs_user_id == User.id).where(
        VinculoProduto.produto == "meuplano", User.perfil == Perfil.CLIENTE, User.proprietaria_id.is_(None),
        User.empresa_id == empresa_id)).all()   # só quem é DE ORIGEM desta empresa: o cadastro é de quem cuida dele
    for pessoa, remoto in donos:
        if not str(remoto or "").isdigit():
            continue
        organizacoes = [por_mp[o] for o in (pessoas_mp.get(int(remoto)) or {}).get("owner_ids") or [] if o in por_mp]
        if len(organizacoes) == 1:                     # de duas proprietárias: quem diz é o gerente
            pessoa.proprietaria_id = organizacoes[0].id
            feito.append(f"{pessoa.nome}: de {organizacoes[0].nome}")
    return feito
