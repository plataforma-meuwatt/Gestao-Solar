"""Sugere quais usinas dos dois sistemas são a mesma.

**Sugere — não decide.** Um casamento errado mistura a geração de uma usina com a
manutenção de outra, e ninguém percebe até alguém questionar um relatório. Por isso a
saída daqui é sempre uma lista ordenada de candidatos com o motivo de cada pontuação, para
uma pessoa confirmar.

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
