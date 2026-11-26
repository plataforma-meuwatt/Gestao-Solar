"""Os dados básicos da usina moram no GS (Plano Casa GS, 24/11/2026: "Nome, endereço e coordenada moram no GS. Editou em
qualquer sistema, a mudança vai ao GS e o GS repassa aos outros, com histórico: quem mudou, de qual sistema, o antes e o
depois"; "Usina criada em qualquer sistema registra no GS. Se parecer uma que já existe (nome e distância), fica 'a
confirmar' e o gerente da O&M decide").

- `alterar`: grava só o que mudou, campo a campo, com uma linha de histórico por campo (`gs_usinas_historico`), e marca
  `atualizado_em` (os sistemas releem com `alteradas_desde`). A coordenada vai sempre em par.
- O kWp da usina ligada ao meuWatt vem de lá (o dono, 26/11/2026): no meuWatt a potência é a soma das strings
  cadastradas e é ela que entra na taxa de desempenho. `alterar` recusa o kWp diferente nessa usina (só o próprio
  meuWatt o manda) e `kwp_do_meuwatt` grava o de lá, na conferência diária (`services/conferencia.py`).
- `parecidas`: as usinas da empresa que podem ser a mesma: o nome igual depois de tirar acento, "UFV" e pontuação, um
  contido no outro, ou parecido (difflib ≥ 0,85); ou a menos de 1,5 km. Quem decide é o gerente, nunca esta função.
"""
import difflib
import math
import re
import unicodedata
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.plant import HistoricoDaUsina, PlantLink
from app.models.user import User

#: os campos que os sistemas leem e editam, com o teto de cada texto
TEXTOS = {"nome": 255, "endereco": 300, "cidade": 120, "uf": 2}
NUMEROS = ("latitude", "longitude", "kwp")
CAMPOS = (*TEXTOS, *NUMEROS)
ROTULO = {"nome": "Nome", "endereco": "Endereço", "cidade": "Cidade", "uf": "UF", "latitude": "Latitude",
          "longitude": "Longitude", "kwp": "Potência (kWp)", "mw_plant_slug": "Usina no meuWatt",
          "mp_usina_id": "Usina no meuPlano", "tv_codigo": "Mapa no TermoVision", "criada": "Criada",
          "ativo": "No aplicativo", "mw_micro_plant_id": "Usina no portal do fabricante", "proprietaria": "Proprietária",
          "no_do_dispositivo": "Nó do meuPlano no equipamento"}


def formatar(campo: str, texto: str | None) -> str | None:
    """O valor guardado no histórico como a tela mostra: número em pt-BR e sim/não em palavras."""
    if texto is None:
        return None
    if campo == "ativo":
        return {"True": "ligada", "False": "desligada"}.get(texto, texto)
    if campo in NUMEROS:
        try:
            n = float(texto)
        except ValueError:
            return texto
        casas = 7 if campo in ("latitude", "longitude") else 2
        bruto = f"{n:,.{casas}f}" if campo == "kwp" else f"{n:.{casas}f}"
        bruto = bruto.rstrip("0").rstrip(".") if "." in bruto else bruto
        return bruto.replace(",", "§").replace(".", ",").replace("§", ".")
    return texto
PERTO_KM = 1.5
#: a diferença de kWp que conta como outro número (abaixo disso é arredondamento)
FOLGA_KWP = 0.01
KWP_E_DO_MEUWATT = ("O kWp desta usina vem do meuWatt, calculado pelas strings cadastradas lá: mude as strings no "
                    "meuWatt. Nada foi alterado.")


class DadoInvalido(ValueError):
    """O valor não serve: a frase vai à tela de quem mandou."""


def _limpo(campo: str, valor):
    if campo in TEXTOS:
        texto = re.sub(r"\s+", " ", str(valor)).strip() if valor is not None else ""
        if campo == "nome" and not texto:
            raise DadoInvalido("A usina precisa de um nome.")
        if campo == "uf":
            texto = texto.upper()
            if texto and not re.fullmatch(r"[A-Z]{2}", texto):
                raise DadoInvalido("A UF tem duas letras (ex.: SP).")
        if len(texto) > TEXTOS[campo]:
            raise DadoInvalido(f"{ROTULO[campo]}: no máximo {TEXTOS[campo]} caracteres.")
        return texto or None
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise DadoInvalido(f"{ROTULO[campo]}: tem de ser um número.") from None
    if not math.isfinite(numero):
        raise DadoInvalido(f"{ROTULO[campo]}: tem de ser um número.")
    limite = {"latitude": 90, "longitude": 180}.get(campo)
    if limite is not None and not -limite <= numero <= limite:
        raise DadoInvalido(f"{ROTULO[campo]}: entre -{limite} e {limite}.")
    if campo == "kwp" and numero < 0:
        raise DadoInvalido("A potência não pode ser negativa.")
    return numero


def _texto(valor) -> str | None:
    return None if valor is None else str(valor)[:400]


def historico(db: Session, link: PlantLink, campo: str, antes, depois, *, por: User | None, sistema: str,
              motivo: str = "") -> None:
    db.add(HistoricoDaUsina(plant_link_id=link.id, campo=campo, antes=_texto(antes), depois=_texto(depois),
                            por_id=por.id if por is not None else None, sistema=sistema, motivo=(motivo or "")[:200]))


def alterar(db: Session, link: PlantLink, mudancas: dict, *, por: User | None, sistema: str, motivo: str = ""
            ) -> list[str]:
    """Aplica `mudancas` (só os campos de `CAMPOS`); devolve os que mudaram. Não confirma: quem chama dá o commit."""
    novos = {c: _limpo(c, v) for c, v in mudancas.items() if c in CAMPOS}
    if ("latitude" in novos) != ("longitude" in novos):
        raise DadoInvalido("A coordenada vai inteira: latitude e longitude juntas.")
    if "latitude" in novos and (novos["latitude"] is None) != (novos["longitude"] is None):
        raise DadoInvalido("A coordenada vai inteira: latitude e longitude juntas.")
    # o kWp da usina ligada ao meuWatt é o de lá: o mesmo número passa (a tela que devolve o que leu), outro recusa o
    # pedido INTEIRO, antes de gravar qualquer campo (quem pediu não fica achando que a potência mudou)
    if "kwp" in novos and link.mw_plant_slug and sistema != "meuwatt":
        if _outro_kwp(link.kwp, novos["kwp"]):
            raise DadoInvalido(KWP_E_DO_MEUWATT)
        del novos["kwp"]
    feitos = []
    for campo, valor in novos.items():
        antes = getattr(link, campo)
        if antes == valor:
            continue
        setattr(link, campo, valor)
        historico(db, link, campo, antes, valor, por=por, sistema=sistema, motivo=motivo)
        feitos.append(campo)
    if feitos:
        link.atualizado_em = datetime.now(UTC)
    return feitos


def _outro_kwp(guardado: float | None, novo: float | None) -> bool:
    if guardado is None or novo is None:
        return guardado is not novo
    return abs(guardado - novo) > FOLGA_KWP


def kwp_do_meuwatt(db: Session, link: PlantLink, valor) -> bool:
    """Guarda no GS o kWp que o meuWatt calcula para a usina ligada a ele, com a linha no histórico em nome do meuWatt
    (sem pessoa). Sem número positivo de lá (ausente, zero, usina sem strings), o guardado fica como está. Devolve se
    mudou. Não confirma."""
    if not link.mw_plant_slug or isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return False
    valor = float(valor)
    if not math.isfinite(valor) or valor <= 0 or not _outro_kwp(link.kwp, valor):
        return False
    historico(db, link, "kwp", link.kwp, valor, por=None, sistema="meuwatt",
              motivo="calculado pelas strings cadastradas lá")
    link.kwp = valor
    link.atualizado_em = datetime.now(UTC)
    return True


def criar(db: Session, *, empresa: int, dados: dict, campo: str, ref, por: User | None, sistema: str,
          motivo: str = "") -> PlantLink:
    """A usina nova no GS, já ligada ao sistema de onde veio (`campo` = o id de lá), com a linha "criada" no
    histórico. Não confirma."""
    # a que só existe no TermoVision nasce FORA do aplicativo (a REGRA 0: usina sem monitoramento e sem manutenção
    # abriria no app com as abas vazias); o gerente a liga quando ela ganhar o meuWatt ou o meuPlano
    link = PlantLink(empresa_id=empresa, ativo=campo != "tv_codigo", atualizado_em=datetime.now(UTC),
                     **{c: dados.get(c) for c in CAMPOS}, **{campo: ref})
    db.add(link)
    db.flush()
    historico(db, link, "criada", None, f"{ROTULO.get(campo, campo)}: {ref}", por=por, sistema=sistema, motivo=motivo)
    return link


def _nome(texto: str | None) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    palavras = [p for p in re.split(r"[^a-z0-9]+", sem_acento) if p and p not in {"ufv", "usina", "de", "da", "do"}]
    return " ".join(palavras)


def distancia_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = (tuple(map(math.radians, p)) for p in (a, b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def parecidas(db: Session, empresa_id: int, nome: str, latitude: float | None = None,
              longitude: float | None = None) -> list[dict]:
    """As usinas da empresa que podem ser esta (o gerente confirma), as mais parecidas primeiro."""
    alvo = _nome(nome)
    achadas = []
    for u in db.scalars(select(PlantLink).where(PlantLink.empresa_id == empresa_id)).all():
        outro = _nome(u.nome)
        # o número no nome separa usinas ("Monte Sião 6" e "Monte Sião 7", "Stuqui UFV 1" e "UFV 4"): com número dos
        # dois lados e diferente, o nome não as aproxima (a distância ainda pode)
        numeros = (set(re.findall(r"\d+", alvo)), set(re.findall(r"\d+", outro)))
        outro_numero = all(numeros) and numeros[0] != numeros[1]
        # a mesma palavra marcante e o mesmo número ("Bady 2 (Solarorto)" e "Bady Bassit 2")
        mesma_e_numero = (all(numeros) and numeros[0] == numeros[1]
                          and bool({p for p in alvo.split() if len(p) >= 4 and not p.isdigit()}
                                   & {p for p in outro.split() if len(p) >= 4 and not p.isdigit()}))
        por_nome = bool(alvo and outro) and not outro_numero and (
            alvo == outro or (min(len(alvo), len(outro)) >= 4 and (alvo in outro or outro in alvo))
            or mesma_e_numero or difflib.SequenceMatcher(None, alvo, outro).ratio() >= 0.85)
        km = (distancia_km((latitude, longitude), (u.latitude, u.longitude))
              if None not in (latitude, longitude, u.latitude, u.longitude) else None)
        if por_nome or (km is not None and km <= PERTO_KM):
            achadas.append({"gs": u.id, "nome": u.nome, "ativo": u.ativo,
                            "distancia_km": round(km, 2) if km is not None else None,
                            "pelo_nome": por_nome})
    return sorted(achadas, key=lambda x: (not x["pelo_nome"], x["distancia_km"] if x["distancia_km"] is not None else 1e9))


if __name__ == "__main__":                                 # a régua do "parecida", sem banco
    assert _nome("UFV Ouro Fino") == _nome("ouro fino") == "ouro fino"
    assert _nome("Tietê") == "tiete"
    assert formatar("kwp", "1250.0") == "1.250" and formatar("latitude", "-21.751") == "-21,751"
    assert formatar("ativo", "False") == "desligada" and formatar("nome", "X") == "X"
    assert round(distancia_km((-21.7, -48.8), (-21.7, -48.8)), 3) == 0
    assert 110 < distancia_km((0, 0), (1, 0)) < 112
    print("ok")
