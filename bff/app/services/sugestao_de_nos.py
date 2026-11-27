"""Qual nó do meuPlano é qual dispositivo do índice: a SUGESTÃO (fase 3, 2ª fatia, 27/11/2026).

O meuPlano não tem os inversores nem os transformadores casados com o meuWatt, e os nomes não batem ("TR-01" e "INV12"
no meuWatt; "Trafo do Skid 1" / `TR-S1` e "Inversor S1-01" / `INV-S1-01` no meuPlano). As quantidades batem. Então o GS
propõe o par e diz POR QUÊ, e quem confirma é o gerente, no oem-gs › Usinas › Equipamentos. A sugestão nunca se aplica
sozinha.

- Só são candidatos os nós `transformador_potencia` (para o transformador) e `inversor` (para o inversor). O
  transformador auxiliar, o inversor híbrido e o abrigo de inversor ficam de fora.
- Transformadores: pelo NÚMERO ("TR-01" e "TR-S1") quando os dois lados têm os mesmos números; senão pela ORDEM; com
  quantidades diferentes, nada.
- Inversores: só dentro de um transformador cujo nó se sabe (confirmado, ou sugerido aqui). Os candidatos são os nós
  de inversor debaixo do mesmo lugar do nó do transformador (o skid). O par sai pelo número, senão pela ordem (os
  dispositivos pelo número do GS; os nós pela ordem da árvore e pelo código).
- O par já confirmado sai dos dois lados antes de sugerir o resto.

Tudo aqui é função pura (sem banco e sem rede): recebe os dispositivos e os nós como dicionários.
"""
import re

#: o tipo de nó do meuPlano que pode ser cada tipo de dispositivo
TIPO_DO_NO = {"transformador": "transformador_potencia", "inversor": "inversor"}
#: os tipos de nó que a pessoa pode escolher para cada tipo de dispositivo, no oem-gs › Usinas › Equipamentos. O relé, a
#: estação e o medidor da fronteira (28/11/2026) não têm sugestão: os nomes não batem, o meuPlano tem nó repetido e
#: solto, e o índice não diz se o relé é de proteção ou de temperatura. A pessoa liga os poucos que são, uma vez. Os
#: nomes dos tipos são os do meuPlano (`mapa_usina.TIPOS_DO_OBJETO` de lá usa os mesmos para a estação).
TIPOS_DO_NO = {**{tipo: (no,) for tipo, no in TIPO_DO_NO.items()},
               "rele": ("rele_protecao", "rele_temperatura"),
               "estacao": ("estação solarimétrica", "piranometro", "datalogger"),
               "medidor_ssu": ("medidor_energia",),
               "gateway": ("gateway",)}
BASE = {"numero": "pelo número", "ordem": "pela ordem"}


def numero(*textos: str | None) -> int | None:
    """O último número do primeiro texto que tem número ("TR-01" → 1; "INV-S1-01" → 1; "Skid 2" → 2)."""
    for texto in textos:
        achados = re.findall(r"\d+", texto or "")
        if achados:
            return int(achados[-1])
    return None


def candidatos(nos: list[dict], tipo: str) -> list[dict]:
    """Os nós que podem ser um dispositivo daquele tipo, na ordem da árvore (e pelo código)."""
    alvo = TIPOS_DO_NO.get(tipo, ())
    return sorted((n for n in nos if n.get("type_code") in alvo),
                  key=lambda n: (n.get("display_order") or 0, str(n.get("code") or ""), n["id"]))


def _numero_do_no(no: dict) -> int | None:
    return numero(no.get("code"), no.get("display_name"), no.get("path"))


def casar(dispositivos: list[dict], nos: list[dict]) -> dict[int, tuple[int, str]]:
    """Os pares `{gd: (node_id, base)}` entre dispositivos e nós do MESMO grupo. Pelo número quando cada lado tem um
    número por item, sem repetir, e os dois conjuntos são iguais; senão pela ordem. Quantidades diferentes: nada."""
    if not dispositivos or len(dispositivos) != len(nos):
        return {}
    dos_d = {numero(d["nome"]): d for d in dispositivos}
    dos_n = {_numero_do_no(n): n for n in nos}
    if None not in dos_d and None not in dos_n and len(dos_d) == len(dispositivos) and len(dos_n) == len(nos) \
            and set(dos_d) == set(dos_n):
        return {d["gd"]: (dos_n[k]["id"], "numero") for k, d in dos_d.items()}
    return {d["gd"]: (n["id"], "ordem") for d, n in zip(sorted(dispositivos, key=lambda d: d["gd"]), nos)}


def _debaixo_de(nos: list[dict], raiz: int | None) -> set[int]:
    """Os ids dos nós debaixo de `raiz` (a própria não conta). Sem raiz (o nó no topo da árvore), todos."""
    if raiz is None:
        return {n["id"] for n in nos}
    filhos: dict[int | None, list[int]] = {}
    for n in nos:
        filhos.setdefault(n.get("parent_id"), []).append(n["id"])
    achados, fila = set(), [raiz]
    while fila:
        for f in filhos.get(fila.pop(), []):
            if f not in achados:
                achados.add(f)
                fila.append(f)
    return achados


def sugerir(dispositivos: list[dict], nos: list[dict]) -> dict[int, dict]:
    """`{gd: {"node_id", "base", "motivo"}}` para os dispositivos ATIVOS ainda sem nó. `dispositivos`: `{gd, tipo, nome,
    pai, ativo, node_id}`; `nos`: os nós da usina como o meuPlano os lista (`id, parent_id, type_code, code,
    display_name, path, display_order`)."""
    por_id = {n["id"]: n for n in nos}
    usados = {d["node_id"] for d in dispositivos if d["node_id"] is not None}
    saida: dict[int, dict] = {}

    def propor(grupo: list[dict], do_grupo: list[dict], onde: str = "") -> None:
        livres_d = [d for d in grupo if d["node_id"] is None]
        livres_n = [n for n in do_grupo if n["id"] not in usados]
        for gd, (no, base) in casar(livres_d, livres_n).items():
            saida[gd] = {"node_id": no, "base": base, "motivo": f"{BASE[base]}{onde}"}

    ativos = [d for d in dispositivos if d["ativo"]]
    trafos = [d for d in ativos if d["tipo"] == "transformador"]
    nos_de_trafo, nos_de_inversor = candidatos(nos, "transformador"), candidatos(nos, "inversor")
    propor(trafos, nos_de_trafo)
    for t in trafos:
        no_do_trafo = por_id.get(t["node_id"] if t["node_id"] is not None else (saida.get(t["gd"]) or {}).get("node_id"))
        if no_do_trafo is None:                            # sem o nó do transformador, não há grupo onde procurar
            continue
        propor([d for d in ativos if d["tipo"] == "inversor" and d["pai"] == t["gd"]],
               _inversores_do_trafo(nos, por_id, no_do_trafo, nos_de_trafo, nos_de_inversor),
               f", entre os inversores de {t['nome']}")
    return saida


def _inversores_do_trafo(nos: list[dict], por_id: dict[int, dict], no_do_trafo: dict, nos_de_trafo: list[dict],
                         nos_de_inversor: list[dict]) -> list[dict]:
    """Os nós de inversor do mesmo lugar do nó do transformador: sobe a árvore a partir dele até o primeiro lugar que
    tem inversor debaixo (o skid). Se esse lugar tem OUTRO transformador debaixo, o grupo não é só dele: nada."""
    lugar = no_do_trafo.get("parent_id")
    while True:
        debaixo = _debaixo_de(nos, lugar)
        achados = [n for n in nos_de_inversor if n["id"] in debaixo]
        if achados or lugar is None:
            outro = any(n["id"] in debaixo and n["id"] != no_do_trafo["id"] for n in nos_de_trafo)
            return [] if outro else achados
        lugar = (por_id.get(lugar) or {}).get("parent_id")


if __name__ == "__main__":                                 # a régua, sem banco
    assert numero("TR-01") == 1 and numero("INV-S1-01") == 1 and numero(None, "Skid 2") == 2 and numero("Trafo") is None
    print("ok")
