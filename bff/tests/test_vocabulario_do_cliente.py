"""O cliente nunca lê o nome do produto que está por trás.

O dono pediu o portal com uma frase que decide isto: *"em vez de o cliente acessar meuWatt
e meuPlano, ele vai acessar o Gestão Solar e vai ter tudo o que precisa"*. Um portal só —
e quem entra nele não deve descobrir, por uma mensagem de erro, que existem dois outros
sistemas com nome próprio. O nome também não ajuda: o cliente não tem conta neles nem a
quem cobrar por eles; o que ele precisa saber é qual SERVIÇO está indisponível.

O caso real que trouxe esta regra para cá: na integração do portal (04/09/2026), a tela de
Ordens registrou que uma usina sem vínculo respondia *"Esta usina não está ligada ao
meuPlano."* — e o portal mostra a frase do servidor como ela vem, de propósito, porque
reescrever motivo de erro na tela esconde a causa. Quer dizer: quem conserta é o BFF, e
uma regra que só vive no revisor volta na primeira rota nova.

A régua:

- rotas do CLIENTE (`/api/v1/*`) — a ponte é nomeada pelo serviço: "monitoramento",
  "manutenção" (constantes `MONITORAMENTO` e `MANUTENCAO` em `manutencao.py`);
- rotas do GESTOR (`/api/painel/*`) — os nomes ficam, e devem ficar: o diagnóstico existe
  justamente para dizer em QUAL produto falta o vínculo.

Este teste lê o texto que vai para a resposta, não o código-fonte inteiro: comentários não
existem na árvore sintática, e docstrings são descartadas de propósito. Explicar de onde
vem o dado é obrigação de quem mantém o arquivo — o que não pode é a explicação viajar
para a tela.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

V1 = Path(__file__).resolve().parents[1] / "app" / "api" / "v1"

#: Só o painel do gestor. Todo o resto de `app/api/v1` é lido por cliente.
DO_GESTOR = {"painel.py", "painel_clientes.py"}

#: A exceção, com o motivo — não uma lista para onde empurrar o que der trabalho.
#:
#: `billing.py` emite a FATURA do cliente, e ali `produto_nome` é a linha da cobrança. O
#: nome na fatura tem de ser o mesmo do contrato que ele assinou: trocar por "Monitoramento"
#: deixaria o cliente sem conseguir conciliar o que paga com o que contratou — e o campo
#: vizinho `fornece` já diz, na língua dele, o que aquilo entrega ("Monitoramento da
#: geração"). Renomear produto em fatura é decisão comercial, não de tela.
COM_MOTIVO = {"billing.py"}

PRODUTOS = ("meuwatt", "meuplano")


def _modulos_do_cliente() -> list[Path]:
    fora = DO_GESTOR | COM_MOTIVO | {"__init__.py"}
    return sorted(p for p in V1.glob("*.py") if p.name not in fora)


def _docstrings(arvore: ast.AST) -> set[int]:
    """Os `id()` dos nós de texto que são documentação, e não resposta."""
    ids: set[int] = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            corpo = getattr(no, "body", None)
            if corpo and isinstance(corpo[0], ast.Expr) and isinstance(corpo[0].value, ast.Constant):
                if isinstance(corpo[0].value.value, str):
                    ids.add(id(corpo[0].value))
    return ids


def _textos_que_saem(arquivo: Path) -> list[tuple[int, str]]:
    """Todo texto do módulo que pode chegar à resposta: literais e pedaços de f-string."""
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    docs = _docstrings(arvore)
    achados: list[tuple[int, str]] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Constant) and isinstance(no.value, str) and id(no) not in docs:
            achados.append((no.lineno, no.value))
    return achados


@pytest.mark.parametrize("arquivo", _modulos_do_cliente(), ids=lambda p: p.name)
def test_o_cliente_nunca_le_o_nome_do_produto(arquivo: Path) -> None:
    culpados = [
        f"{arquivo.name}:{linha}  {texto[:90]}"
        for linha, texto in _textos_que_saem(arquivo)
        if any(p in texto.lower() for p in PRODUTOS)
    ]
    assert not culpados, (
        "Texto de resposta nomeando o produto de origem numa rota de cliente:\n  "
        + "\n  ".join(culpados)
        + "\n\nUse o nome do SERVIÇO (MONITORAMENTO / MANUTENCAO, em manutencao.py). "
        "Se a explicação for para quem mantém o código, ela é comentário ou docstring."
    )


def test_o_painel_do_gestor_continua_nomeando_os_produtos() -> None:
    """A régua acima não pode ter apagado o diagnóstico do gestor.

    Sem este teste, "tirar o nome do produto" viraria uma limpeza geral e o painel — cuja
    única função naquela tela é dizer em qual produto falta o vínculo — ficaria dizendo
    "algum sistema não respondeu", que não conserta nada.
    """
    nomeiam = {
        arquivo.name
        for arquivo in (V1 / n for n in DO_GESTOR)
        for _, texto in _textos_que_saem(arquivo)
        if any(p in texto.lower() for p in PRODUTOS)
    }
    assert nomeiam == DO_GESTOR, f"O painel deixou de nomear os produtos: falta {DO_GESTOR - nomeiam}"


def test_o_teste_reprova_quando_o_nome_volta(tmp_path: Path) -> None:
    """Prova que a guarda acima morde — um gate que nunca reprova não guarda nada."""
    falso = tmp_path / "rota_nova.py"
    falso.write_text(
        '"""Docstring pode falar de meuPlano à vontade."""\n'
        "# comentário sobre o meuWatt também\n"
        'def f():\n'
        '    raise HTTPException(404, "Esta usina não está ligada ao meuPlano.")\n',
        encoding="utf-8",
    )
    achados = [t for _, t in _textos_que_saem(falso) if any(p in t.lower() for p in PRODUTOS)]
    assert achados == ["Esta usina não está ligada ao meuPlano."]
