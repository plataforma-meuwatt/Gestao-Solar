"""A conferência diária (docs/USINA_NASCE_NO_GS.md, fase 5): o GS é o cadastro mestre, e a usina que existe no meuWatt
ou no meuPlano de uma empresa sem estar no GS não some calada. Ela entra na fila "A confirmar" do oem-gs (a mesma do
registro dos sistemas), com as parecidas, e o gerente diz se é a mesma, outra ou descarta. As proprietárias novas do
meuPlano entram pela importação, que só preenche. Lê com a conta DA EMPRESA: cada uma vê o que é dela."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.empresa import Empresa
from app.models.plant import PlantLink, UsinaAConfirmar
from app.services import dados_da_usina, integracoes, proprietarias

log = logging.getLogger("gs.conferencia")


def _dados(nome, cidade, uf, endereco, lat, lng, kwp) -> dict | None:
    try:
        return {c: dados_da_usina._limpo(c, v) for c, v in dict(
            nome=nome, cidade=cidade, uf=uf, endereco=endereco, latitude=lat, longitude=lng, kwp=kwp).items()}
    except dados_da_usina.DadoInvalido:
        return None


async def _de_la(db: Session, empresa_id: int) -> list[tuple[str, str, dict]]:
    """(sistema, referência, dados) de cada usina que a conta da empresa vê nos dois produtos. Produto mudo = nada."""
    saida = []
    try:
        mw = await integracoes.cliente_meuwatt(db, empresa_id)
        cru = await mw._get("/plants")
        for p in cru if isinstance(cru, list) else (cru or {}).get("items") or []:
            if p.get("slug") and (d := _dados(p.get("name"), p.get("city"), p.get("state"), None, p.get("latitude"),
                                                p.get("longitude"), p.get("total_capacity_kwp"))):
                saida.append(("meuwatt", str(p["slug"]), d))
    except Exception as e:                                 # noqa: BLE001
        log.info("conferência %s: meuWatt sem leitura (%s)", empresa_id, type(e).__name__)
    try:
        mp = await integracoes.cliente_meuplano(db, empresa_id)
        for u in await mp.usinas():
            if str(u.get("id", "")).isdigit() and (d := _dados(u.get("name"), u.get("city"), u.get("uf"),
                                                               u.get("address"), u.get("latitude"),
                                                               u.get("longitude"), u.get("potencia_kwp"))):
                saida.append(("meuplano", str(u["id"]), d))
    except Exception as e:                                 # noqa: BLE001
        log.info("conferência %s: meuPlano sem leitura (%s)", empresa_id, type(e).__name__)
    return saida


async def conferir(db: Session, empresa_id: int) -> list[str]:
    """Põe na fila "A confirmar" as usinas de lá que não estão no GS (nem já esperando ou decididas). Devolve os nomes
    que entraram. Confirma."""
    ligadas = {("meuwatt", s) for (s,) in db.execute(select(PlantLink.mw_plant_slug)) if s} | {
        ("meuplano", str(i)) for (i,) in db.execute(select(PlantLink.mp_usina_id)) if i}
    na_fila = {(s, r) for s, r in db.execute(select(UsinaAConfirmar.sistema, UsinaAConfirmar.referencia)
                                             .where(UsinaAConfirmar.empresa_id == empresa_id))}
    entraram = []
    for sistema, ref, d in await _de_la(db, empresa_id):
        if (sistema, ref) in ligadas or (sistema, ref) in na_fila:
            continue
        db.add(UsinaAConfirmar(empresa_id=empresa_id, sistema=sistema, referencia=ref, dados=d,
                               parecidas=dados_da_usina.parecidas(db, empresa_id, d["nome"], d["latitude"],
                                                                  d["longitude"])))
        na_fila.add((sistema, ref))
        entraram.append(f"{d['nome']} ({sistema})")
    try:
        entraram += [f"proprietária: {f}" for f in await proprietarias.importar_do_meuplano(db, empresa_id, por=None)]
    except Exception as e:                                 # noqa: BLE001
        log.info("conferência %s: proprietárias sem leitura (%s)", empresa_id, type(e).__name__)
    db.commit()
    return entraram


async def conferir_todas(db: Session) -> dict[int, list[str]]:
    return {e: await conferir(db, e) for e in db.scalars(select(Empresa.id).where(Empresa.ativa)).all()}
