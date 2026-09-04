"""O erro do meuPlano tem de chegar ao dono DIZENDO o que houve.

Nasceu de um caso real (04/09/2026). O dono tentou abrir o PDF de uma tarefa no aplicativo e
leu: *"O meuPlano não conseguiu gerar este PDF agora. Tente mais tarde."* — em toda falha, e
não importava qual. A rota do PDF fazia `except Exception` e devolvia 502 para tudo, então um
403 de permissão, um 413 de arquivo grande demais e um tempo esgotado chegavam com a MESMA
frase, que ainda por cima acusava o gerador de PDF de um defeito que ele não tinha.

O que estes testes protegem:

1. **403 e 404 passam com o status e a frase do upstream.** São coisas que o usuário precisa
   ler literalmente; traduzi-las em 502 esconde a única informação útil.
2. **413 chega inteiro.** A mensagem já diz o tamanho e o teto — é o que responde "e agora?".
3. **401 do upstream NÃO vira 401 nosso.** O token de serviço é da ponte, não do dono da
   usina: repassar deslogaria o usuário por causa de uma credencial que não é dele.
4. **Tempo esgotado é 504.** É o único caso em que "tente de novo" é conselho de verdade.
"""

import httpx
import pytest

from app.api.v1.manutencao import _detalhe_da_resposta, _erro_do_upstream


def _erro_http(status: int, corpo: object) -> httpx.HTTPStatusError:
    pedido = httpx.Request("GET", "https://meuplano.exemplo/api/v1/meuacesso/tasks/1/pdf/view")
    resposta = httpx.Response(status, json=corpo, request=pedido)
    return httpx.HTTPStatusError("erro", request=pedido, response=resposta)


@pytest.mark.parametrize("status", [403, 404, 413])
def test_status_do_usuario_passa_com_a_frase_do_upstream(status):
    exc = _erro_http(status, {"detail": "O arquivo tem 60.0 MB e o armazenamento aceita 50 MB."})
    saida = _erro_do_upstream(exc, "Não deu para gerar o PDF desta tarefa")
    assert saida.status_code == status
    assert saida.detail == "O arquivo tem 60.0 MB e o armazenamento aceita 50 MB."


def test_sem_detalhe_a_frase_diz_o_status():
    saida = _erro_do_upstream(_erro_http(403, {}), "Não deu para gerar o PDF desta tarefa")
    assert saida.status_code == 403
    assert "403" in saida.detail


def test_401_do_upstream_nao_desloga_o_dono():
    """O token é da PONTE. Devolver 401 faria o aplicativo mandar o usuário para o login."""
    saida = _erro_do_upstream(_erro_http(401, {"detail": "Token inválido"}), "Ao ler a ficha")
    assert saida.status_code == 502
    assert "sessão" in saida.detail


def test_500_do_upstream_vira_502_mas_leva_o_motivo():
    saida = _erro_do_upstream(_erro_http(500, {"detail": "Erro interno."}), "Ao gerar o PDF")
    assert saida.status_code == 502
    assert "Erro interno." in saida.detail


def test_tempo_esgotado_e_504():
    saida = _erro_do_upstream(httpx.ReadTimeout("demorou"), "Não deu para gerar o PDF desta tarefa")
    assert saida.status_code == 504
    assert "demorou" in saida.detail


def test_falha_que_nao_e_http_continua_502():
    saida = _erro_do_upstream(RuntimeError("conexão recusada"), "Ao ler a ficha")
    assert saida.status_code == 502
    assert "conexão recusada" in saida.detail


def test_detail_em_lista_do_422_vira_frase():
    """O FastAPI responde 422 com uma LISTA de objetos; concatenada, ela ainda informa."""
    pedido = httpx.Request("GET", "https://meuplano.exemplo/x")
    resposta = httpx.Response(422, json={"detail": [{"msg": "Field required", "loc": ["query", "mes"]}]},
                              request=pedido)
    assert _detalhe_da_resposta(resposta) == "Field required"


def test_corpo_que_nao_e_json_vira_texto_curto():
    pedido = httpx.Request("GET", "https://meuplano.exemplo/x")
    resposta = httpx.Response(502, text="<html>Bad Gateway</html>", request=pedido)
    assert _detalhe_da_resposta(resposta) == "<html>Bad Gateway</html>"
