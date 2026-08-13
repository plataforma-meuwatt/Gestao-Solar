"""O inventário de usinas dos dois sistemas, e quais delas são a mesma.

Duas responsabilidades, e a distinção importa:

**1. Inventariar.** `montar` junta os dois lados numa lista só de usinas do Gestão Solar.
Uma usina pode existir nos dois sistemas, só no meuWatt, ou só no meuPlano — e as três
situações precisam aparecer. A versão anterior deste arquivo percorria apenas o meuWatt e
procurava par no meuPlano, o que tornava **invisível toda usina que só existe no meuPlano**:
com 16 lá e 6 aqui, dez sumiam da tela sem aviso nenhum. Manutenção sem monitoramento é um
caso normal de negócio, não uma anomalia.

**2. Sugerir o par — não decidir.** Um casamento errado mistura a geração de uma usina com
a manutenção de outra, e ninguém percebe até alguém questionar um relatório. Por isso a
saída é sempre uma lista ordenada de candidatos com o motivo de cada pontuação, para uma
pessoa confirmar.

Três pistas, em ordem de confiança:

1. **CNPJ + número da UC** — quando existirem nos dois lados, é prova, não pista. Ainda não
   existem em nenhum dos dois cadastros (ver docs/DECISAO_IDENTIDADE.md); o código já está
   pronto para quando existirem.
2. **Distância geográfica** — coordenadas iguais são forte indício. Mas duas usinas do
   mesmo cliente ficam a 200 m uma da outra, então isso sozinho não fecha.
3. **Nome e potência** — as mais fracas. "Porto Ferreira", "UFV Porto Ferreira" e
   "Porto Ferreira I" saem de pessoas diferentes em momentos diferentes.
"""

from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from typing import Any


@dataclass
class Candidato:
    mp_usina_id: int
    nome: str
    pontos: float
    motivos: list[str] = field(default_factory=list)


@dataclass
class Sugestao:
    mw_slug: str
    mw_nome: str
    candidatos: list[Candidato]


def _distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine. Precisão de metros é irrelevante aqui — o que importa é distinguir
    'mesma usina' de 'outra cidade'."""
    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _normalizar(texto: str) -> str:
    """Tira acento, caixa e o vocabulário que todo mundo escreve diferente."""
    import unicodedata

    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    for ruido in ("ufv ", "usina ", "solar ", " i", " ii", " iii", "-", "_"):
        t = t.replace(ruido, " ")
    return " ".join(t.split())


def _semelhanca_nome(a: str, b: str) -> float:
    """Proporção de palavras em comum. Simples de propósito: um algoritmo mais esperto
    daria uma falsa sensação de precisão sobre dado que é digitado à mão."""
    pa, pb = set(_normalizar(a).split()), set(_normalizar(b).split())
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def _numero(valor: Any) -> float | None:
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def sugerir(
    usinas_mw: list[dict[str, Any]],
    usinas_mp: list[dict[str, Any]],
    limite: int = 3,
) -> list[Sugestao]:
    """Para cada usina do meuWatt, os melhores candidatos do meuPlano.

    A pontuação não é probabilidade — é ordenação. Serve para pôr o par provável no topo
    da lista, não para decidir sozinha.
    """
    sugestoes: list[Sugestao] = []

    for mw in usinas_mw:
        nome_mw = mw.get("name") or mw.get("nome") or ""
        lat_mw, lon_mw = _numero(mw.get("latitude")), _numero(mw.get("longitude"))
        kwp_mw = _numero(mw.get("capacity_kwp"))
        cnpj_mw = (mw.get("cnpj") or "").strip()
        uc_mw = (mw.get("uc_numero") or "").strip()

        candidatos: list[Candidato] = []

        for mp in usinas_mp:
            nome_mp = mp.get("name") or mp.get("nome") or ""
            pontos = 0.0
            motivos: list[str] = []

            # 1. Prova documental — quando existir, domina o resto.
            cnpj_mp = (mp.get("cnpj") or "").strip()
            uc_mp = (mp.get("uc_numero") or "").strip()
            if cnpj_mw and cnpj_mw == cnpj_mp:
                pontos += 100
                motivos.append("mesmo CNPJ")
            if uc_mw and uc_mw == uc_mp:
                pontos += 100
                motivos.append("mesma UC")

            # 2. Distância.
            lat_mp, lon_mp = _numero(mp.get("latitude")), _numero(mp.get("longitude"))
            if None not in (lat_mw, lon_mw, lat_mp, lon_mp):
                km = _distancia_km(lat_mw, lon_mw, lat_mp, lon_mp)  # type: ignore[arg-type]
                if km < 0.5:
                    pontos += 40
                    motivos.append("mesmas coordenadas")
                elif km < 5:
                    pontos += 20
                    motivos.append(f"a {km:.1f} km")

            # 3. Nome.
            sem = _semelhanca_nome(nome_mw, nome_mp)
            if sem >= 0.99:
                pontos += 30
                motivos.append("nome idêntico")
            elif sem >= 0.5:
                pontos += 15 * sem
                motivos.append("nome parecido")

            # 4. Potência — desempate, nunca argumento sozinho.
            kwp_mp = _numero(mp.get("potencia_kwp"))
            if kwp_mw and kwp_mp and kwp_mw > 0:
                if abs(kwp_mw - kwp_mp) / kwp_mw < 0.02:
                    pontos += 10
                    motivos.append("mesma potência")

            if pontos > 0:
                candidatos.append(
                    Candidato(
                        mp_usina_id=int(mp.get("id", 0)),
                        nome=nome_mp,
                        pontos=round(pontos, 1),
                        motivos=motivos,
                    )
                )

        candidatos.sort(key=lambda c: c.pontos, reverse=True)
        sugestoes.append(
            Sugestao(
                mw_slug=mw.get("slug") or "",
                mw_nome=nome_mw,
                candidatos=candidatos[:limite],
            )
        )

    return sugestoes


# ── inventário ──────────────────────────────────────────────────────────────


def nome_de(usina: dict[str, Any]) -> str:
    """Os dois produtos escrevem o nome em chaves diferentes."""
    return usina.get("name") or usina.get("nome") or ""


@dataclass
class Linha:
    """Uma usina do Gestão Solar, com o que se sabe dela de cada lado.

    `plant_link_id` nulo significa que ela ainda não existe aqui — foi vista num dos
    produtos e nunca foi trazida para dentro. É o estado inicial de tudo, e a diferença
    entre "não está no app" e "não existe" é justamente essa.
    """

    #: Identificador estável para a tela. `mw:slug`, `mp:12` ou `link:3`.
    chave: str
    nome: str
    plant_link_id: int | None = None
    mw_slug: str | None = None
    mw_nome: str | None = None
    mp_usina_id: int | None = None
    mp_nome: str | None = None
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    #: Existe aqui **e** está ligada. Só uma usina no app pode ser concedida a um cliente.
    no_app: bool = False
    #: Candidatas do meuPlano para esta usina do meuWatt, da mais provável para a menos.
    candidatos: list[Candidato] = field(default_factory=list)
    #: O caminho inverso: para uma usina só do meuPlano, qual usina do meuWatt parece ser
    #: a mesma. Sem isto, `Ibitinga` apareceria duas vezes na tela — uma em cada grupo —
    #: sem nada indicando que provavelmente são a mesma coisa, e o gestor teria de cruzar
    #: os dois grupos a olho. Continuam duas linhas de propósito: o sistema não *sabe* que
    #: são a mesma, e esconder uma delas seria decidir no lugar de quem decide.
    par_provavel_mw: str | None = None
    par_provavel_nome: str | None = None
    par_provavel_motivos: list[str] = field(default_factory=list)

    @property
    def origem(self) -> str:
        if self.mw_slug and self.mp_usina_id:
            return "ambos"
        return "meuwatt" if self.mw_slug else "meuplano"


def montar(
    usinas_mw: list[dict[str, Any]],
    usinas_mp: list[dict[str, Any]],
    links: list[Any],
    limite: int = 3,
) -> list[Linha]:
    """A lista completa: o que já existe aqui, mais o que ainda só existe lá.

    A ordem de montagem é o cuidado principal — cada usina precisa aparecer **uma vez só**.
    Primeiro os vínculos já gravados (que são a verdade deste sistema), depois o que sobrou
    de cada produto. Sem isso, uma usina casada apareceria três vezes: uma como vínculo,
    uma como "só meuWatt" e uma como "só meuPlano".

    `links` são os `PlantLink`; o parâmetro é solto (`Any`) para este módulo continuar sem
    saber de banco — ele é testado com objetos simples.
    """
    por_slug = {u.get("slug"): u for u in usinas_mw if u.get("slug")}
    por_id = {int(u["id"]): u for u in usinas_mp if u.get("id") is not None}

    sugestoes = {s.mw_slug: s.candidatos for s in sugerir(usinas_mw, usinas_mp, limite)}

    linhas: list[Linha] = []
    slugs_usados: set[str] = set()
    ids_usados: set[int] = set()

    # 1. O que este sistema já conhece.
    for link in links:
        mw = por_slug.get(link.mw_plant_slug) if link.mw_plant_slug else None
        mp = por_id.get(link.mp_usina_id) if link.mp_usina_id else None
        if link.mw_plant_slug:
            slugs_usados.add(link.mw_plant_slug)
        if link.mp_usina_id:
            ids_usados.add(link.mp_usina_id)

        linhas.append(
            Linha(
                chave=f"link:{link.id}",
                nome=link.nome,
                plant_link_id=link.id,
                mw_slug=link.mw_plant_slug,
                # O nome do produto quando ele responde; senão, o guardado. Uma usina
                # apagada lá continua legível aqui em vez de virar uma linha sem nome.
                mw_nome=nome_de(mw) if mw else (link.nome if link.mw_plant_slug else None),
                mp_usina_id=link.mp_usina_id,
                mp_nome=nome_de(mp) if mp else (link.nome if link.mp_usina_id else None),
                cidade=link.cidade,
                uf=link.uf,
                kwp=link.kwp,
                no_app=bool(link.ativo),
                # Uma usina já casada não precisa de sugestão; uma só-meuWatt ainda precisa.
                candidatos=[] if link.mp_usina_id else sugestoes.get(link.mw_plant_slug, []),
            )
        )

    # 2. O que só existe no meuWatt.
    for slug, u in por_slug.items():
        if slug in slugs_usados:
            continue
        linhas.append(
            Linha(
                chave=f"mw:{slug}",
                nome=nome_de(u),
                mw_slug=slug,
                mw_nome=nome_de(u),
                cidade=u.get("city"),
                uf=u.get("state"),
                kwp=u.get("capacity_kwp") or u.get("total_capacity_kwp"),
                candidatos=sugestoes.get(slug, []),
            )
        )

    # O caminho inverso da sugestão: de cada usina do meuPlano ainda solta, para a usina do
    # meuWatt que parece ser a mesma. Só entre as que continuam sem par dos dois lados —
    # apontar para uma usina do meuWatt já casada seria sugerir um conflito.
    #: mp_usina_id → (slug, nome, pontos, motivos) da melhor usina do meuWatt para ela.
    inverso: dict[int, tuple[str, str, float, list[str]]] = {}
    for linha_mw in linhas:
        if linha_mw.origem != "meuwatt" or not linha_mw.mw_slug:
            continue
        for c in linha_mw.candidatos:
            if c.mp_usina_id in ids_usados:
                continue
            anterior = inverso.get(c.mp_usina_id)
            # Uma usina do meuPlano pode ser candidata de duas do meuWatt. Fica com a de
            # maior pontuação — a mesma regra que ordena a lista de candidatos.
            if anterior is None or c.pontos > anterior[2]:
                inverso[c.mp_usina_id] = (linha_mw.mw_slug, linha_mw.nome, c.pontos, c.motivos)

    # 3. O que só existe no meuPlano — o grupo que a versão anterior não mostrava.
    for id_mp, u in por_id.items():
        if id_mp in ids_usados:
            continue
        par = inverso.get(id_mp)
        linhas.append(
            Linha(
                chave=f"mp:{id_mp}",
                nome=nome_de(u),
                mp_usina_id=id_mp,
                mp_nome=nome_de(u),
                cidade=u.get("city") or u.get("cidade"),
                uf=u.get("uf") or u.get("state"),
                kwp=u.get("potencia_kwp") or u.get("capacity_kwp"),
                par_provavel_mw=par[0] if par else None,
                par_provavel_nome=par[1] if par else None,
                par_provavel_motivos=list(par[3]) if par else [],
            )
        )

    # No app primeiro, depois as casadas, depois por nome: o que exige decisão sobe.
    linhas.sort(key=lambda l: (not l.no_app, l.origem != "ambos", l.nome.lower()))
    return linhas
