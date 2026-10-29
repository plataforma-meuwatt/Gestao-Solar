"""Cadastrar uma pessoa no Gestão Solar, no meuWatt e no meuPlano pelo bot (pedido do Renan, 29/10/2026:
"dê poderes ao bot para criar usuários, do jeito que estamos fazendo: criar, editar, gerar os tokens sem
expor, apenas fazendo os links").

O jeito é o que se fez à mão com o Diogo, a Camila e o Michel:

1. `procurar_pessoa` (leitura): procura nos três sistemas e devolve o que já existe. A IA diz isso à
   pessoa e pergunta o que falta (aproveitar qual conta, o perfil em cada sistema, o e-mail).
2. `cadastrar_pessoa` (ação, com o Sim): cria ou aproveita a conta em cada sistema, liga a do GS às
   outras, entra como a pessoa pelo login do Gestão Solar, emite o token DELA e o grava aqui. O token
   nunca sai do processo: não vai à IA, ao WhatsApp nem ao log.

Quem pode: só o gerente da O&M, e em cada produto vale a regra DE LÁ, com o token de quem pede (decisão
do Renan): o meuWatt aceita admin da plataforma ou admin O&M da empresa (e só a plataforma dá papel de
dono ou de admin O&M); o meuPlano exige "Gerenciar usuários" e a mesma empresa. Recusado lá, o bot diz o
porquê. Conta do GS de fora da empresa (de outra ou de nenhuma) não se aproveita: isso é da plataforma.
"""

import asyncio
import logging
import re
import unicodedata
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.core import apelido as apelidos
from app.core.telefone import TelefoneInvalido, exibir, normalizar
from app.models.integracao import Produto
from app.models.user import Perfil, User
from app.services import assistente_helper as helper

log = logging.getLogger(__name__)

NOME_DO_TOKEN = "Gestão Solar (bot do WhatsApp)"
PRAZO_S = 600
PERFIS_GS = {"gestor_empresa": (Perfil.GESTOR_EMPRESA, "gerente"), "tecnico": (Perfil.TECNICO, "técnico"),
             "cliente": (Perfil.CLIENTE, "dono de usina")}
PAPEIS_MW = {"system_admin": "admin O&M", "operator": "operador", "field_employee": "técnico de campo",
             "plant_owner": "dono"}
PAPEIS_MP = {"admin_sistema": "admin do sistema (todas as empresas)", "admin_tenant": "admin da empresa",
             "tecnico_campo": "técnico de campo", "operador": "operador", "leitura": "só leitura", "cliente": "cliente",
             "prestador": "prestador de serviço (terceiro)"}
#: Prestador de serviço (pedido do Renan, 29/10/2026: "prestador para a Splendor, que possa assumir tarefas dentro das
#: OS"): no meuPlano é o vínculo `terceiro` na organização, que dá a Permissão "Prestador (terceiro)" (executa as
#: tarefas das OS, sem financeiro, equipe, estoque e cadastro da empresa), com o vínculo PJ ("prestador" lá). O papel
#: global é o que o meuPlano dá a quem entra numa O&M sem papel da casa (`owners._default_global_role`).
PRESTADOR = {"member_role": "terceiro", "tipo_vinculo": "PJ"}
PARTES = {"meuwatt": "bot_meuwatt", "meuplano": "bot_meuplano", "helper": "bot_helper"}
SENHA_DO_GS = ("A senha de entrar no GS não vai por aqui: defina em oem-gs → Usuários → Senha. "
               "O bot já reconhece a pessoa pelo celular.")
#: O FORMULÁRIO de cadastro (WhatsApp Flow `gs_cadastro_pessoa`): o papel em cada sistema, com o título que cabe na
#: lista (até 20 letras). "Não cadastrar" primeiro. Admin do sistema do meuPlano fica fora: é da plataforma.
OPCOES_DO_FORMULARIO = {
    "meuplano": [("nao", "Não cadastrar"), ("prestador", "Prestador (terceiro)"), ("tecnico_campo", "Técnico de campo"),
                 ("operador", "Operador"), ("leitura", "Só leitura"), ("admin_tenant", "Admin da empresa"),
                 ("cliente", "Cliente")],
    "meuwatt": [("nao", "Não cadastrar"), ("field_employee", "Técnico de campo"), ("operator", "Operador"),
                ("system_admin", "Admin O&M"), ("plant_owner", "Dono")],
    "gs": [("nao", "Não cadastrar"), ("tecnico", "Técnico"), ("gestor_empresa", "Gerente da O&M"),
           ("cliente", "Dono de usina")],
}
NOMES_DOS_SISTEMAS = {"meuplano": "meuPlano", "meuwatt": "meuWatt", "gs": "Gestão Solar"}
FORMULARIO_FALHOU = ("Não consegui abrir o formulário de cadastro. Me diga o nome, o e-mail, o celular e o papel em "
                     "cada sistema (meuPlano, meuWatt, Gestão Solar).")
SENHA_DO_MP = ("Para entrar no meuPlano (site ou app), a pessoa cria a senha em «Esqueci a senha», com o código que "
               "chega no e-mail dela.")


def _so_gerente(user) -> str | None:
    if user.perfil != Perfil.GESTOR_EMPRESA or not user.empresa_id:
        return "Só o gerente da O&M cadastra pessoas pelo bot."
    return None


def _sem_acento(t: str | None) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def _digitos(t: str | None) -> str:
    return re.sub(r"\D", "", t or "")


def _casa(conta: dict, nome: str, email: str, telefone: str) -> bool:
    """Mesmo e-mail, mesmo celular (os 8 últimos dígitos: o DDD e o 9 mudam de um cadastro para outro) ou o NOME:
    um nome só casa com o PRIMEIRO nome da conta (ou o começo do e-mail); nome completo, com todas as palavras.
    ⛔ 29/10/2026: "Thiago Marquezini" (sem conta em lugar nenhum) casava com o Welinton THIAGO Jaques pelo nome do
    meio, e o bot perguntava se era a mesma pessoa."""
    e = (conta.get("email") or "").lower()
    if email and e == email:
        return True
    d = _digitos(telefone)[-8:]
    if len(d) == 8 and _digitos(conta.get("telefone"))[-8:] == d:
        return True
    palavras = _falado(nome).split()
    if not palavras or len(palavras[0]) < 3:
        return False
    da_conta = _falado(conta.get("nome")).split()
    do_email = set(re.split(r"[^a-z0-9]+", _falado(e.split("@")[0])))
    if len(palavras) == 1:
        return palavras[0] in da_conta[:1] or palavras[0] in do_email
    return all(p in da_conta or p in do_email for p in palavras)


def _falado(t: str | None) -> str:
    """O nome como se FALA: "tiago" acha o Thiago, "Mateus" o Matheus (sem isso o bot dizia que não existe e criava
    outra conta). Sem h mudo, ph = f, y = i, sem letra dobrada."""
    return re.sub(r"(.)\1", r"\1", _sem_acento(t).replace("ph", "f").replace("h", "").replace("y", "i"))


def _procura(contas: list[dict], nome: str, email: str, telefone: str) -> list[dict]:
    return [c for c in contas if _casa(c, nome, email, telefone)][:10]


def _motivo(e: Exception) -> str:
    from app.services.integracoes import detalhe_do_upstream
    if isinstance(e, httpx.HTTPStatusError):
        return str(detalhe_do_upstream(e.response) or f"respondeu {e.response.status_code}").rstrip(". ")
    if isinstance(e, HTTPException):
        return str(e.detail).rstrip(". ")
    if isinstance(e, httpx.HTTPError):
        return "não respondeu a tempo"
    return str(e).rstrip(". ") or type(e).__name__


def _clientes(db, user):
    """Os clientes do meuWatt e do meuPlano com o token PRÓPRIO de quem pede (None = não tem)."""
    from app.services.vinculos import SemConexao, cliente_meuplano, cliente_meuwatt
    saida = []
    for fabrica in (cliente_meuwatt, cliente_meuplano):
        try:
            saida.append(fabrica(db, user.id, so_proprio=True))
        except SemConexao:
            saida.append(None)
    db.commit()                                              # solta a conexão enquanto os produtos respondem
    return saida


# --------------------------------------------------------------------------- procurar
PROCURAR = {"type": "function", "function": {
    "name": "procurar_pessoa",
    "description": ("Só para CONTA DE ACESSO (alguém que vai entrar no GS, no meuWatt ou no meuPlano, inclusive o "
                    "prestador que vai executar tarefas das OS lá). Contato de usina (eletricista, prestador, quem "
                    "atende ou socorre, telefone de alguém) NÃO é conta: é do meuPlano (`manutencao`). "
                    "CONSULTA: procura a pessoa no Gestão Solar, no meuWatt e no meuPlano (pelo e-mail, pelo celular "
                    "e pelo nome) e devolve o que já existe em cada sistema, com o id de cada conta ('o Fulano tem "
                    "conta?'). Para CADASTRAR não use esta: `formulario_de_cadastro` já procura."),
    "parameters": {"type": "object", "properties": {
        "nome": {"type": "string"}, "email": {"type": "string"}, "telefone": {"type": "string"}}}}}


def _no_gs(db, empresa_id: int, nome: str, email: str, telefone: str) -> dict:
    from app.services import empresas, pessoas
    contas = db.scalars(select(User).where(empresas.contas_da_empresa(empresa_id),
                                           User.perfil.notin_(pessoas.DA_PLATAFORMA))).all()
    itens = [{"conta": u.id, "apelido": u.apelido, "nome": u.nome, "email": u.email, "telefone": exibir(u.telefone),
              "perfil": u.perfil.value, "ativo": u.ativo} for u in contas]
    saida: dict[str, Any] = {"na_sua_empresa": _procura(itens, nome, email, telefone)}
    de_fora = select(User).where(User.id.notin_([u.id for u in contas] or [-1]))
    fora = []
    if email and db.scalar(de_fora.where(User.email == email)):
        fora.append(f"o e-mail {email} já é de uma conta do GS fora da sua empresa")
    d = _digitos(telefone)[-8:]
    if len(d) == 8 and any(_digitos(u.telefone)[-8:] == d for u in db.scalars(de_fora.where(User.telefone.isnot(None)))):
        fora.append("o celular já é de uma conta do GS fora da sua empresa")
    if fora:
        saida["fora_da_sua_empresa"] = fora + ["essa conta não se aproveita pelo bot: só a plataforma a põe na sua empresa"]
    return saida


async def _no_meuwatt(mw, empresa, nome, email, telefone) -> dict:
    if mw is None:
        return {"erro": "sem o SEU token do meuWatt: não dá para procurar nem cadastrar lá"}
    try:
        todos, empresas = await asyncio.gather(mw.usuarios(apenas_ativos=False), mw.empresas_om())
    except httpx.HTTPError as e:
        return {"erro": f"o meuWatt recusou listar os usuários com o seu token: {_motivo(e)}"}
    listas = await asyncio.gather(*(mw.funcionarios(e["id"]) for e in empresas), return_exceptions=True)
    onde: dict[int, list[str]] = {}
    for e, lista in zip(empresas, listas):
        for f in lista if isinstance(lista, list) else []:
            if f.get("active", True):
                onde.setdefault(f.get("user_id"), []).append(
                    f"{e.get('name')}: {PAPEIS_MW.get(f.get('role'), f.get('role'))}")
    itens = [{"conta": u.get("id"), "nome": u.get("name"), "email": u.get("email"), "ativo": u.get("is_active"),
              "voce_administra": u.get("gerivel", True), "empresas": onde.get(u.get("id"), [])} for u in todos]
    return {"contas": _procura(itens, nome, email, telefone),
            "empresas": [{"empresa": e.get("id"), "nome": e.get("name")} for e in empresas],
            "empresa_da_sua_o_e_m": empresa.mw_enterprise_id, "papeis": PAPEIS_MW}


async def _no_meuplano(mp, empresa, nome, email, telefone) -> dict:
    if mp is None:
        return {"erro": "sem o SEU token do meuPlano: não dá para procurar nem cadastrar lá"}
    try:
        todos = await mp.usuarios_admin()
    except httpx.HTTPError as e:
        return {"erro": f"o meuPlano recusou listar os usuários com o seu token: {_motivo(e)}"}
    itens = [{"conta": u.get("id"), "nome": u.get("name"), "email": u.get("email"), "telefone": u.get("phone"),
              "papel": u.get("role"), "organizacoes": u.get("owner_ids") or [], "ativo": u.get("active")}
             for u in todos]
    return {"contas": _procura(itens, nome, email, telefone),
            "organizacao_da_sua_empresa": empresa.mp_tenant_id, "papeis": PAPEIS_MP}


async def procurar_pessoa(ctx, a: dict) -> dict:
    from app.models.empresa import Empresa
    from app.services import empresas
    if erro := _so_gerente(ctx.user):
        return {"erro": erro}
    nome, telefone = (a.get("nome") or "").strip(), a.get("telefone") or ""
    email = (a.get("email") or "").strip().lower()
    if not (nome or email or telefone):
        return {"erro": "Diga o nome, o e-mail ou o celular de quem procurar."}
    empresa = ctx.db.get(Empresa, empresas.empresa_exigida(ctx.user))
    gs = _no_gs(ctx.db, empresa.id, nome, email, telefone)
    mw, mp = _clientes(ctx.db, ctx.user)
    no_mw, no_mp = await asyncio.gather(_no_meuwatt(mw, empresa, nome, email, telefone),
                                        _no_meuplano(mp, empresa, nome, email, telefone))
    return {"gestao_solar": gs, "meuwatt": no_mw, "meuplano": no_mp,
            "instrucao": ("Diga à pessoa, sistema por sistema, o que já existe (com o id) e pergunte o que falta antes "
                          "de chamar cadastrar_pessoa: aproveitar qual conta ou criar, o perfil em cada sistema, o e-mail "
                          "e o celular. Não escolha por ela. Conta 'fora da sua empresa' no GS não se aproveita.")}


# --------------------------------------------------------------------------- cadastrar
CADASTRAR = {"type": "function", "function": {
    "name": "cadastrar_pessoa",
    "description": ("Cadastra uma pessoa nos sistemas que a pessoa pediu, depois de procurar_pessoa e de ela ter dito "
                    "o que fazer em cada um. Vira uma ação que ela confirma com Sim. Em cada sistema: passe o id da "
                    "conta a APROVEITAR ou deixe sem id para criar. Sistema sem papel = não mexer nele. Os tokens do "
                    "meuWatt e do meuPlano da pessoa são gerados e ligados no GS sozinhos, sem aparecer. Só no "
                    "meuPlano (sem gs_perfil) a pessoa não ganha conta no GS, token nem bot."),
    "parameters": {"type": "object", "required": ["nome"], "properties": {
        "nome": {"type": "string"},
        "email": {"type": "string", "description": "obrigatório para criar conta no meuWatt ou no meuPlano"},
        "telefone": {"type": "string", "description": "celular (é por ele que o bot reconhece a pessoa)"},
        "apelido": {"type": "string", "description": "login no GS; sem ele, sai do nome"},
        "gs_perfil": {"type": "string", "enum": list(PERFIS_GS),
                      "description": "sem ele, o GS não é tocado (meuWatt e bot precisam dele)"},
        "gs_conta": {"type": "integer", "description": "aproveitar esta conta do GS da sua empresa"},
        "mw_papel": {"type": "string", "enum": list(PAPEIS_MW)},
        "mw_conta": {"type": "integer", "description": "aproveitar esta conta do meuWatt"},
        "mw_empresa": {"type": "integer", "description": "a empresa do meuWatt; sem ela, a da sua O&M"},
        "mp_papel": {"type": "string", "enum": list(PAPEIS_MP),
                     "description": ("prestador = prestador de serviço da sua empresa (terceiro): assume e executa "
                                     "tarefas das OS, sem financeiro, equipe e estoque")},
        "mp_conta": {"type": "integer", "description": "aproveitar esta conta do meuPlano"},
        "bot": {"type": "array", "items": {"type": "string", "enum": list(PARTES)},
                "description": "partes do bot a ligar para a pessoa (sem senha de atuação)"}}}}}


async def cadastrar_pessoa(ctx, a: dict) -> dict:
    """Confere o que dá para conferir sem gravar e propõe; nada roda antes do Sim."""
    from app.models.empresa import Empresa
    from app.services import cadastro, empresas, pessoas
    if erro := _so_gerente(ctx.user):
        return {"erro": erro}
    db, user = ctx.db, ctx.user
    empresa = db.get(Empresa, empresas.empresa_exigida(user))
    nome = (a.get("nome") or "").strip()
    email = (a.get("email") or "").strip().lower() or None
    if len(nome) < 2:
        return {"erro": "Falta o nome da pessoa."}
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return {"erro": f"O e-mail {email} não parece válido: confira com a pessoa."}
    perfil = PERFIS_GS.get(a.get("gs_perfil") or "")
    if perfil is None and (a.get("gs_perfil") or a.get("gs_conta") or a.get("mw_papel") or a.get("bot")
                           or not a.get("mp_papel")):
        return {"erro": "Falta o perfil no GS: gerente, técnico ou dono de usina (só o cadastro no meuPlano dispensa)."}
    p: dict[str, Any] = {"nome": nome, "email": email, "perfil": a.get("gs_perfil") if perfil else None,
                         "empresa": empresa.id, "linhas": []}

    # GS: a conta aproveitada tem de ser da empresa e não da plataforma (a régua de `_conta_da_empresa`)
    conta = db.get(User, a["gs_conta"]) if a.get("gs_conta") else None
    if a.get("gs_conta") and (conta is None or conta.perfil in pessoas.DA_PLATAFORMA
                              or empresa.id not in empresas.empresas_da_conta(db, conta)):
        return {"erro": f"A conta {a['gs_conta']} do GS não é da sua empresa: só a plataforma a põe nela. "
                        "Ofereça criar uma conta nova."}
    try:
        if perfil is None:                                   # só meuPlano: o celular não vira conta do GS
            tel = normalizar(a.get("telefone"))
        else:
            tel = cadastro.celular_livre(db, a["telefone"], conta.id if conta else None) if a.get("telefone") else None
    except (HTTPException, TelefoneInvalido) as e:
        return {"erro": f"Celular: {getattr(e, 'detail', e)}"}
    p["telefone"], p["gs_conta"] = tel, conta.id if conta else None
    celular = f", celular {exibir(tel)}" if tel else ""
    if perfil is not None and conta is None:
        try:
            p["apelido"] = apelidos.normalizar(a.get("apelido") or apelidos.sugerir(nome))
        except apelidos.ApelidoInvalido as e:
            return {"erro": f"Apelido: {e}"}
        if db.scalar(select(User.id).where(User.apelido == p["apelido"])):
            return {"erro": f"O apelido {p['apelido']} já existe no GS: pergunte outro."}
        p["linhas"].append(f"GS: conta nova «{p['apelido']}» ({perfil[1]}){celular}")
    elif perfil is not None:
        p["apelido"] = conta.apelido
        p["linhas"].append(f"GS: aproveitar «{conta.apelido}» como {perfil[1]}{celular}")

    # meuWatt e meuPlano: com o token de QUEM PEDE; a régua de cada um vale na hora do Sim
    mw, mp = _clientes(db, user)
    if papel := a.get("mw_papel"):
        if papel not in PAPEIS_MW:
            return {"erro": f"Papel do meuWatt inválido: use {', '.join(PAPEIS_MW)}."}
        if mw is None:
            return {"erro": "Você não tem o seu token do meuWatt no GS: sem ele o bot não mexe no meuWatt."}
        eid = a.get("mw_empresa") or empresa.mw_enterprise_id
        if not eid:
            return {"erro": "Sua empresa não está ligada a uma empresa do meuWatt (oem-gs → Vínculos): diga em qual."}
        alvo_email = email
        if a.get("mw_conta"):
            try:
                achada = next((u for u in await mw.usuarios(apenas_ativos=False) if u.get("id") == a["mw_conta"]), None)
            except httpx.HTTPError as e:
                return {"erro": f"O meuWatt recusou listar os usuários com o seu token: {_motivo(e)}"}
            if achada is None or not achada.get("gerivel", True):
                return {"erro": f"A conta {a['mw_conta']} do meuWatt não está entre as que você administra lá."}
            alvo_email = achada.get("email")
        elif not email:
            return {"erro": "Para criar a conta no meuWatt falta o e-mail."}
        p["mw"] = {"papel": papel, "conta": a.get("mw_conta"), "empresa": eid, "email": alvo_email}
        qual = f"aproveitar a conta #{a['mw_conta']}" if a.get("mw_conta") else "conta nova"
        p["linhas"].append(f"meuWatt: {qual} ({alvo_email}) como {PAPEIS_MW[papel]} da empresa #{eid}")
    if papel := a.get("mp_papel"):
        if papel not in PAPEIS_MP:
            return {"erro": f"Papel do meuPlano inválido: use {', '.join(PAPEIS_MP)}."}
        if mp is None:
            return {"erro": "Você não tem o seu token do meuPlano no GS: sem ele o bot não mexe no meuPlano."}
        if not a.get("mp_conta") and not email:
            return {"erro": "Para criar a conta no meuPlano falta o e-mail."}
        if not empresa.mp_tenant_id:
            return {"erro": "Sua empresa não está ligada à organização dela no meuPlano (oem-gs → Vínculos)."}
        p["mp"] = {"papel": papel, "conta": a.get("mp_conta"), "organizacao": empresa.mp_tenant_id}
        qual = f"aproveitar a conta #{a['mp_conta']}" if a.get("mp_conta") else f"conta nova ({email})"
        extra = " da sua empresa: assume e executa tarefas das OS" if papel == "prestador" else ""
        p["linhas"].append(f"meuPlano: {qual} como {PAPEIS_MP[papel]}{extra}{celular if perfil is None else ''}")
    if perfil is not None and ("mw" in p or "mp" in p):
        p["linhas"].append("Tokens: gerados e ligados no GS, sem aparecer")
    if partes := [x for x in a.get("bot") or [] if x in PARTES]:
        if not (tel or (conta and conta.telefone)):
            return {"erro": "Para ligar o bot falta o celular da pessoa."}
        p["bot"] = partes
        p["linhas"].append(f"Bot: {', '.join(partes)} (sem senha de atuação)")

    async def executar(db, quem, telefone: str) -> str:
        return await _executar(db, quem, p)

    resumo = f"Cadastrar {nome}" + (f" ({email})" if email else "")
    return helper.propor(ctx, resumo, PRAZO_S, executar, p["linhas"], _senhas(p), parte=None, confirmacao="sim")


def _senhas(p: dict) -> list[str]:
    """Como a pessoa entra: a senha não sai por aqui, nem a do GS nem a do meuPlano."""
    return ([SENHA_DO_GS] if p["perfil"] and not p["gs_conta"] else []) \
        + ([SENHA_DO_MP] if "mp" in p and not p["mp"]["conta"] else [])


# --------------------------------------------------------------------------- executar (depois do Sim)
async def _executar(db, quem, p: dict) -> str:
    from app.core.security import gerar_hash_senha, gerar_senha_provisoria
    from app.services import cadastro, empresas
    if _so_gerente(quem) or empresas.empresa_exigida(quem) != p["empresa"]:
        return "❌ Só o gerente da O&M cadastra pessoas pelo bot. Nada foi feito."
    conta, feitas = None, []
    if p["perfil"]:
        try:
            # a senha provisória não sai daqui: quem entrega a de entrar é o gerente, no oem-gs
            hash_ = None if p["gs_conta"] else await asyncio.to_thread(gerar_hash_senha, gerar_senha_provisoria())
            conta = _conta_no_gs(db, quem, p, hash_)
        except Exception as e:                               # noqa: BLE001
            db.rollback()
            log.warning("cadastro: GS falhou: %s", type(e).__name__)
            return f"❌ Não consegui criar a conta no GS: {_motivo(e)}. Nada foi feito."
        feitas.append(f"✅ GS: «{conta.apelido}» ({PERFIS_GS[p['perfil']][1]})")
    falhou = False
    for chave, nome, passo in (("mp", "meuPlano", _meuplano), ("mw", "meuWatt", _meuwatt)):
        if chave in p:
            try:
                feitas.append(await passo(db, quem, conta, p[chave], p))
            except Exception as e:                           # noqa: BLE001
                falhou = True
                log.warning("cadastro: %s falhou: %s", nome, type(e).__name__)
                feitas.append(f"❌ {nome}: {_motivo(e)}")
    if p.get("bot"):
        db.refresh(conta)
        ligadas = []
        for parte in p["bot"]:
            try:
                cadastro.liberar_bot(conta, PARTES[parte], True)
                ligadas.append(parte)
            except HTTPException as e:
                falhou = True
                feitas.append(f"❌ Bot ({parte}): {str(e.detail).rstrip('. ')}")
        db.commit()
        if ligadas:
            feitas.append(f"✅ Bot ligado: {', '.join(ligadas)} (sem senha de atuação)")
    cabeca = f"⚠️ Cadastro de {p['nome']} feito EM PARTE:" if falhou else f"✅ Cadastro de {p['nome']} feito:"
    return "\n".join([cabeca, *(f"• {f}" for f in feitas), *_senhas(p)])


def _conta_no_gs(db, quem, p: dict, senha_hash: str | None) -> User:
    from app.services import cadastro, clientes
    perfil = PERFIS_GS[p["perfil"]][0]
    if p["gs_conta"]:
        conta = db.get(User, p["gs_conta"])
    else:
        conta = clientes.criar(db, nome=p["nome"], apelido=p["apelido"], email=p["email"], empresa=None,
                               criado_por=quem, senha_pronta=("", senha_hash)).usuario
        conta.empresa_id = p["empresa"]
    conta.perfil = perfil
    if p["telefone"] and conta.telefone != p["telefone"]:
        conta.telefone = cadastro.celular_livre(db, p["telefone"], conta.id)
        cadastro.adotar_mensagens(db, conta)
    if p["email"] and not conta.email:
        conta.email = p["email"]
    db.commit()
    return conta


async def _ligar_token(db, quem, conta, produto: Produto, cliente, sessao: str) -> str:
    """Emite o token da pessoa com a sessão DELA e o grava no GS. O valor não sai desta função."""
    from app.services import vinculos
    criado = await cliente.emitir_token(sessao, NOME_DO_TOKEN)
    r = await vinculos.conectar(db, conta, produto, criado["token"], por=quem)
    if not r.ok:
        await cliente.revogar_token(sessao, criado["id"])
        raise RuntimeError(f"o GS recusou o token ({r.detalhe}); ele foi revogado")
    return f"token ligado, {r.usinas_visiveis} usina(s) visíveis" if r.usinas_visiveis is not None else "token ligado"


async def _meuplano(db, quem, conta, mp_: dict, p: dict) -> str:
    from app.services import login_externo
    _, mp = _clientes(db, quem)
    prestador = mp_["papel"] == "prestador"
    if mp_["conta"]:
        alvo = mp_["conta"]
        atual = next((u for u in await mp.usuarios_admin() if u.get("id") == alvo), None)
        if atual is None:
            raise RuntimeError(f"a conta #{alvo} não está entre as que você administra lá")
        mudar: dict[str, Any] = {"owner_ids": sorted({*(atual.get("owner_ids") or []), mp_["organizacao"]})}
        if not prestador:                                    # o papel global de quem já existe fica (vale nas outras)
            mudar["role"] = mp_["papel"]
        if p["telefone"]:
            mudar["phone"] = exibir(p["telefone"])
        await mp.atualizar_usuario_admin(alvo, mudar)
        feito = f"conta #{alvo} como {PAPEIS_MP[mp_['papel']]}"
    else:
        novo = await mp.criar_usuario_admin({"email": p["email"], "name": p["nome"],
                                             "role": "leitura" if prestador else mp_["papel"],
                                             "phone": exibir(p["telefone"]) if p["telefone"] else None,
                                             "owner_ids": [mp_["organizacao"]]})
        alvo, feito = novo["id"], f"conta nova #{novo['id']} como {PAPEIS_MP[mp_['papel']]}"
    if prestador:
        try:
            await mp.vinculo_na_organizacao(mp_["organizacao"], alvo, PRESTADOR)
        except Exception as e:                               # noqa: BLE001
            raise RuntimeError(f"a conta #{alvo} está na sua empresa, mas o papel de prestador não entrou "
                               f"({_motivo(e)}): troque em Minha Empresa → Equipe") from e
    if conta is None:                                        # só meuPlano: sem conta no GS não há token a ligar
        return f"✅ meuPlano: {feito}"
    await mp.provisionar_identidade(alvo, login_externo.assinar(conta, Produto.MEUPLANO))
    sessao = await mp.entrar_pelo_gs(login_externo.assinar(conta, Produto.MEUPLANO))
    return f"✅ meuPlano: {feito}, {await _ligar_token(db, quem, conta, Produto.MEUPLANO, mp, sessao)}"


async def _meuwatt(db, quem, conta, mw_: dict, p: dict) -> str:
    from app.models.plant import PlantLink
    from app.services import login_externo
    slugs = set(db.scalars(select(PlantLink.mw_plant_slug).where(
        PlantLink.empresa_id == p["empresa"], PlantLink.ativo, PlantLink.mw_plant_slug.isnot(None))))
    mw, _ = _clientes(db, quem)
    prov = await mw.provisionar(str(conta.id), mw_["email"], conta.nome, vincular_existente=bool(mw_["conta"]))
    uid = prov["user_id"]
    if mw_["conta"] and uid != mw_["conta"]:
        raise RuntimeError(f"a conta do GS já estava ligada a outra conta do meuWatt (#{uid}); nada mudou lá")
    eid, papel = mw_["empresa"], mw_["papel"]
    ja = next((f for f in await mw.funcionarios(eid) if f.get("user_id") == uid), None)
    func = ja or await mw.por_na_empresa(eid, uid, papel)
    nota = ""
    if ja and ja.get("role") != papel:
        nota = f" (já era {PAPEIS_MW.get(ja.get('role'), ja.get('role'))} lá: o papel não foi trocado)"
    if func.get("role") != "system_admin":                  # técnico, operador e dono só veem por concessão
        await mw.conceder_usinas(eid, func["id"], [u["id"] for u in await mw.usinas() if u.get("slug") in slugs])
    sessao = await mw.entrar_pelo_gs(login_externo.assinar(conta, Produto.MEUWATT))
    try:
        ligado = await _ligar_token(db, quem, conta, Produto.MEUWATT, mw, sessao)
    finally:
        try:
            await mw.sair(sessao)
        except Exception:                                    # noqa: BLE001 (a sessão vence sozinha)
            log.info("cadastro: a sessão do meuWatt não fechou; vence sozinha")
    qual = "conta nova" if prov.get("criado") else f"conta #{uid}"
    return f"✅ meuWatt: {qual} como {PAPEIS_MW[papel]}{nota}, {ligado}"


# --------------------------------------------------------------------------- formulário de cadastro
FORMULARIO = {"type": "function", "function": {
    "name": "formulario_de_cadastro",
    "description": ("Para CADASTRAR alguém (conta de acesso, prestador): manda um FORMULÁRIO do WhatsApp com os campos "
                    "(nome, e-mail, celular e o papel no meuPlano, no meuWatt e no Gestão Solar), já com o que a pessoa "
                    "disse. Use no lugar de perguntar dado por dado. A resposta do formulário o sistema confere nos três "
                    "sistemas e já propõe o cadastro com o Sim."),
    "parameters": {"type": "object", "properties": {
        "nome": {"type": "string"}, "email": {"type": "string"}, "telefone": {"type": "string"},
        **{s: {"type": "string", "enum": [i for i, _ in ops], "description": f"o papel no {NOMES_DOS_SISTEMAS[s]}"}
           for s, ops in OPCOES_DO_FORMULARIO.items()}}}}}


async def formulario_de_cadastro(ctx, a: dict) -> dict:
    if erro := _so_gerente(ctx.user):
        return {"erro": erro}
    ctx.cadastro = {"nome": a.get("nome"), "email": a.get("email"), "celular": a.get("telefone"),
                    **{s: a[s] for s, ops in OPCOES_DO_FORMULARIO.items() if a.get(s) in dict(ops)}}
    return {"ok": ("O formulário vai logo depois da sua resposta. Diga em UMA frase curta que é para preencher e tocar "
                   "em Enviar; não peça os dados nem liste os campos.")}


async def pelo_formulario(ctx, d: dict) -> str:
    """O formulário de cadastro respondido: o SISTEMA procura nos três e, sem conta parecida, já propõe o cadastro (o
    Sim confirma). Sem a IA no meio (dono, 29/10/2026: ela perguntava de novo o que o formulário já dizia)."""
    papel = {s: (d.get(s) if d.get(s) in dict(ops) and d.get(s) != "nao" else None)
             for s, ops in OPCOES_DO_FORMULARIO.items()}
    if not any(papel.values()):
        return "Nada a cadastrar: no formulário, os três sistemas ficaram em «Não cadastrar»."
    ctx.ferramentas.append("procurar_pessoa")
    achado = await procurar_pessoa(ctx, {"nome": d.get("nome"), "email": d.get("email"), "telefone": d.get("celular")})
    if "erro" in achado:
        return f"❌ {achado['erro']}"
    existe = []
    for s, chave in (("gs", "gestao_solar"), ("meuplano", "meuplano"), ("meuwatt", "meuwatt")):
        if not papel[s]:
            continue
        lido = achado[chave]
        if "erro" in lido:
            return f"❌ {NOMES_DOS_SISTEMAS[s]}: {lido['erro']}."
        contas = lido.get("na_sua_empresa") if s == "gs" else lido.get("contas")
        existe += [f"{NOMES_DOS_SISTEMAS[s]}: {c.get('nome')} ({c.get('email') or 'sem e-mail'}, conta {c['conta']})"
                   for c in contas or []]
        existe += [f"{NOMES_DOS_SISTEMAS[s]}: {x}" for x in lido.get("fora_da_sua_empresa") or []]
    if existe:
        return (f"Antes de cadastrar {d.get('nome')}, já existe parecido:\n" + "\n".join(f"• {x}" for x in existe)
                + "\nÉ a mesma pessoa? Diga qual conta aproveitar ou «criar nova».")
    ctx.ferramentas.append("cadastrar_pessoa")
    r = await cadastrar_pessoa(ctx, {k: v for k, v in {
        "nome": d.get("nome"), "email": d.get("email"), "telefone": d.get("celular"), "gs_perfil": papel["gs"],
        "mp_papel": papel["meuplano"], "mw_papel": papel["meuwatt"]}.items() if v})
    if "erro" in r:
        return f"❌ Não deu para propor o cadastro: {r['erro']}"
    return f"Conferi no Gestão Solar, no meuWatt e no meuPlano: não há conta de {d.get('nome')}. Confira e toque em Sim."


FERRAMENTAS = {"procurar_pessoa": (procurar_pessoa, PROCURAR), "cadastrar_pessoa": (cadastrar_pessoa, CADASTRAR),
               "formulario_de_cadastro": (formulario_de_cadastro, FORMULARIO)}
