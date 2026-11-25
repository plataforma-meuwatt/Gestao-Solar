"""Os ITENS do mapa da usina, para o TermoVision pôr, mover e tirar (fase 2 do mapa novo; o Renan, 25/11/2026: "preciso
conseguir arrastar os inversores e transformadores para a planta" e "marcar a subestação e a posição dos relés em planta,
dentro da sub"). Contrato em `docs/CONTRATO_SISTEMAS.md`.

A posição continua no mapa do meuWatt, o mesmo que o GS e o meuPlano usam: aqui só se junta o que EXISTE na usina
(`GET /plants/{slug}/mapa/equipamentos`: os trafos, as vagas com as strings e os relés de proteção) com o que está
desenhado (`GET /plants/{slug}/mapa`), e cada item ganha um ref estável. Ler é de quem vê a usina na lista do GS (pela
sessão do passe); pôr, mover e tirar é da O&M e da plataforma, gravado com o token DA PESSOA (o papel de operação, lá,
decide), levando o "antes": o meuWatt confere numa transação e devolve 409 se outra pessoa mexeu depois. A mesma
geometria de novo é 200 sem mudar: é isso que torna o pedido repetido inofensivo."""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.interno_sistemas import _NAO, _O_E_M, codigo, pessoa, sistema, usina_da_pessoa
from app.core.db import get_db
from app.services import pessoas

router = APIRouter(prefix="/api/v1/interno", tags=["interno · itens do mapa"])

#: a forma de cada tipo de item no mapa (GeoJSON em [lon, lat])
FORMAS = {"subestacao": ("Polygon",), "rele": ("Point",), "transformador": ("Point",), "inversor": ("Point",),
          "string": ("Polygon", "LineString")}
#: o `origem` do objeto que o GS cria por um item (único por usina no meuWatt: dois pedidos juntos não fazem dois)
ORIGEM = "gs-item:"
OUTRA_PESSOA = "Outra pessoa mexeu neste item depois que você o viu: releia o mapa."
#: o `relay_kind` do meuWatt (a régua de Leituras e da Comunicação) em palavras
TIPO_DO_RELE = {"protection": "relé de proteção", "thermal": "relé de temperatura", "gateway": "caixa de I/O"}


class ItemIn(BaseModel):
    geometria: dict
    #: a geometria que a tela viu (nula: o item estava fora do mapa)
    antes: dict | None = None
    #: só para a subestação nova (`novo:<uuid>`)
    tipo: str | None = None
    nome: str | None = Field(None, max_length=120)


class SaidaIn(BaseModel):
    antes: dict | None = None


def _ref_do_objeto(o: dict) -> str:
    """O ref de um objeto desenhado: o que a tela criou (`novo:`), o do equipamento ligado, senão `obj:<id>`."""
    origem = o.get("origem") or ""
    if origem.startswith(ORIGEM + "novo:"):
        return origem.removeprefix(ORIGEM)
    t = o.get("tipo")
    if t == "transformador" and o.get("transformer_id"):
        return f"trafo:{o['transformer_id']}"
    if t == "inversor" and o.get("slot_id"):
        return f"inv:{o['slot_id']}"
    if t == "string" and o.get("slot_id") and o.get("string_number"):
        return f"str:{o['slot_id']}:{o['string_number']}"
    if t == "rele" and o.get("relay_id"):
        return f"rele:{o['relay_id']}"
    return f"obj:{o['id']}"


def _item(ref: str, tipo: str, nome: str, pai: str | None, detalhe: str | None, o: dict | None,
          ligacao: dict) -> dict:
    o = o or {}
    return {"ref": ref, "tipo": tipo, "nome": nome, "pai": pai, "detalhe": detalhe, "geometria": o.get("geometria"),
            "meuwatt": {"objeto": o.get("id"), **ligacao},
            "alterado_por": (o.get("atualizado_por") or {}).get("nome"), "alterado_em": o.get("atualizado_em")}


def itens(equipamentos: dict, objetos: list) -> list[dict]:
    """Os itens da usina: cada equipamento (desenhado ou não) e o que está desenhado sem equipamento na lista (a
    subestação, a string do as-built ainda não ligada), que fica para mover ou tirar."""
    desenhados: dict[str, dict] = {}
    soltos: list[dict] = []
    for o in objetos:
        if not isinstance(o, dict) or o.get("id") is None or o.get("tipo") not in FORMAS:
            continue
        ref = _ref_do_objeto(o)
        if ref.startswith(("obj:", "novo:")) or ref in desenhados:
            soltos.append(o)
        else:
            desenhados[ref] = o
    out: list[dict] = []
    trafos: dict = {}
    for t in equipamentos.get("transformadores") or []:
        trafos[t["id"]] = t.get("nome") or f"Trafo {t['id']}"
        kva = t.get("kva")
        out.append(_item(f"trafo:{t['id']}", "transformador", trafos[t["id"]], None,
                         f"{kva:,.0f} kVA".replace(",", ".") if isinstance(kva, (int, float)) else None,
                         desenhados.pop(f"trafo:{t['id']}", None), {"transformer_id": t["id"]}))
    for v in equipamentos.get("vagas") or []:
        s, rotulo, inv = v["slot_id"], v.get("rotulo") or f"Vaga {v['slot_id']}", v.get("inversor") or {}
        out.append(_item(f"inv:{s}", "inversor", rotulo,
                         f"trafo:{v['transformer_id']}" if v.get("transformer_id") in trafos else None,
                         " · ".join(str(x) for x in (inv.get("modelo"), inv.get("sn")) if x) or None,
                         desenhados.pop(f"inv:{s}", None), {"slot_id": s}))
        for n in v.get("strings") or []:
            out.append(_item(f"str:{s}:{n}", "string", f"String {n}", f"inv:{s}", rotulo,
                             desenhados.pop(f"str:{s}:{n}", None), {"slot_id": s, "string_number": n}))
    for r in equipamentos.get("reles") or []:
        tid = r.get("transformer_id")
        detalhe = " · ".join(x for x in (TIPO_DO_RELE.get(r.get("relay_kind")), trafos.get(tid) or "Geral") if x)
        out.append(_item(f"rele:{r['relay_id']}", "rele", r.get("nome") or f"Relé {r['relay_id']}",
                         f"trafo:{tid}" if tid in trafos else None, detalhe,
                         desenhados.pop(f"rele:{r['relay_id']}", None), {"relay_id": r["relay_id"]}))
    for o in [*desenhados.values(), *soltos]:            # desenhado sem o equipamento na lista
        ref = _ref_do_objeto(o)
        ref = ref if ref.startswith("novo:") else f"obj:{o['id']}"
        out.append(_item(ref, o["tipo"], o.get("nome") or f"Desenho {o['id']}", None,
                         None if ref.startswith("novo:") else "desenhado sem ligação a um equipamento", o, {}))
    return out


def _da_porta(db: Session, request: Request, gs: int, o_que: str = ""):
    """A pessoa (pela sessão do passe do TermoVision) e a usina, se ela a vê na lista do GS; e se ela edita o mapa."""
    if sistema(request) != "termovision":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Os itens do mapa são do TermoVision.")
    u = pessoa(db, request, "termovision", o_que=o_que)
    link = usina_da_pessoa(db, u, gs, request.headers.get("x-empresa-gs"))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NAO)
    if not link.mw_plant_slug:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta usina não está ligada ao meuWatt, onde mora o mapa do GS.")
    return u, link, u.perfil in _O_E_M or u.perfil in pessoas.DA_PLATAFORMA


async def _ler(mw, slug: str) -> list[dict]:
    """Sem a leitura do meuWatt é erro (502), nunca uma lista vazia que parece certa."""
    eq, mapa = await asyncio.gather(mw.mapa_equipamentos(slug), mw.mapa(slug), return_exceptions=True)
    if isinstance(mapa, BaseException) or not isinstance(mapa, dict) or not isinstance(mapa.get("objetos"), list):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "O mapa do GS não pôde ser lido agora (o meuWatt não respondeu).")
    if isinstance(eq, BaseException) or not isinstance(eq, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Os equipamentos da usina não vieram do meuWatt agora.")
    return itens(eq, mapa["objetos"])


@router.get("/usinas/{gs}/mapa/itens")
async def listar_itens(gs: int, request: Request, db: Session = Depends(get_db)) -> dict:
    from app.services.vinculos import SemConexao, cliente_meuwatt

    u, link, pode = _da_porta(db, request, gs, f"os itens do mapa da usina {codigo(gs)}")
    try:
        mw = cliente_meuwatt(db, u.id)                    # ler: a conta dela, senão a da empresa (a régua do portal)
    except SemConexao as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"O mapa do GS não pôde ser lido: {exc}") from exc
    slug = link.mw_plant_slug
    db.commit()                                           # solta a conexão enquanto o meuWatt responde
    return {"pode_editar": pode, "lido_em": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(timespec="seconds"),
            "itens": await _ler(mw, slug)}


def _quem_edita(db: Session, request: Request, gs: int):
    from app.services.vinculos import SemConexao, cliente_meuwatt

    u, link, pode = _da_porta(db, request, gs)
    if not pode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Só a O&M da usina põe, move e tira itens do mapa.")
    try:
        mw = cliente_meuwatt(db, u.id, so_proprio=True)   # gravar: o token DELA (o papel de operação, lá, decide)
    except SemConexao as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Sem a sua conexão com o meuWatt: {exc}") from exc
    slug = link.mw_plant_slug
    db.commit()
    return mw, slug


async def _conflito(mw, slug: str, ref: str) -> JSONResponse:
    atual = next((i for i in await _ler(mw, slug) if i["ref"] == ref), None)
    return JSONResponse({"detail": OUTRA_PESSOA, "item": atual}, status_code=status.HTTP_409_CONFLICT)


def _recusa(exc: httpx.HTTPError) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 403:
        return HTTPException(status.HTTP_403_FORBIDDEN, "O seu papel nesta usina no meuWatt não mexe no mapa (só a operação).")
    if isinstance(exc, httpx.HTTPStatusError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, f"O meuWatt recusou ({exc.response.status_code}).")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "O meuWatt não respondeu: o item PODE ter mudado. Releia o mapa.")


@router.put("/usinas/{gs}/mapa/itens/{ref}")
async def por_item(gs: int, ref: str, body: ItemIn, request: Request, db: Session = Depends(get_db)):
    """Põe ou move o item. A subestação nova vem com `novo:<uuid>`, `tipo` e `nome`; mandar de novo não cria outra."""
    from app.api.v1.mapa import _geometria

    mw, slug = _quem_edita(db, request, gs)
    geometria = _geometria(body.geometria)
    atual = next((i for i in await _ler(mw, slug) if i["ref"] == ref), None)
    if atual is None:
        if not ref.startswith("novo:"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item desconhecido nesta usina.")
        if body.tipo != "subestacao" or not (body.nome or "").strip() or len(ref) > 120:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "O item novo é uma subestação: mande tipo \"subestacao\" e o nome.")
        atual = _item(ref, "subestacao", body.nome.strip(), None, None, None, {})
    if geometria["type"] not in FORMAS[atual["tipo"]]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{atual['tipo']} vai no mapa como {' ou '.join(FORMAS[atual['tipo']])}.")
    objeto = atual["meuwatt"]["objeto"]
    try:
        if objeto is None:
            if body.antes is not None:                   # a tela o viu no mapa, e alguém o tirou depois
                return await _conflito(mw, slug, ref)
            ligacao = {k: v for k, v in atual["meuwatt"].items() if k != "objeto"}
            await mw.mapa_criar(slug, {"tipo": atual["tipo"], "nome": atual["nome"], "geometria": geometria,
                                       "origem": ORIGEM + ref, **ligacao})
        elif body.antes is None and atual["geometria"] not in (None, geometria):
            return await _conflito(mw, slug, ref)        # a tela o viu fora do mapa, e alguém o pôs depois
        else:
            await mw.mapa_alterar(slug, objeto, {"geometria": geometria, "antes": body.antes})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            return await _conflito(mw, slug, ref)
        raise _recusa(exc) from exc
    except httpx.HTTPError as exc:
        raise _recusa(exc) from exc
    return {"item": next((i for i in await _ler(mw, slug) if i["ref"] == ref), None)}


@router.delete("/usinas/{gs}/mapa/itens/{ref}")
async def tirar_item(gs: int, ref: str, request: Request, body: SaidaIn | None = None, db: Session = Depends(get_db)):
    """Tira o item do mapa: o equipamento volta para a lista sem posição; a subestação criada pela tela sai da lista."""
    mw, slug = _quem_edita(db, request, gs)
    atual = next((i for i in await _ler(mw, slug) if i["ref"] == ref), None)
    if atual is None:
        if ref.startswith(("novo:", "obj:")):            # já tirado: o pedido repetido não é erro
            return {"item": None}
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item desconhecido nesta usina.")
    if atual["meuwatt"]["objeto"] is None:
        return {"item": atual}                           # já estava fora do mapa
    try:
        await mw.mapa_apagar(slug, atual["meuwatt"]["objeto"], antes=(body.antes if body else None))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            return await _conflito(mw, slug, ref)
        if exc.response.status_code != 404:              # 404: outra pessoa já o tirou
            raise _recusa(exc) from exc
    except httpx.HTTPError as exc:
        raise _recusa(exc) from exc
    return {"item": next((i for i in await _ler(mw, slug) if i["ref"] == ref), None)}
