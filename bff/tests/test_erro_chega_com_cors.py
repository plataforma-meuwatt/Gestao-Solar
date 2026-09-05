"""Erro do servidor chega ao navegador COMO erro do servidor.

O caso real: o "Ficha em PDF" da OS estourava `UnicodeEncodeError` ao montar o cabeçalho.
A exceção subia até o `ServerErrorMiddleware`, que fica ACIMA do CORS, e a resposta saía
sem `Access-Control-Allow-Origin` — o navegador a classificava como falha de rede e o
portal exibia "Sem conexão com o servidor.". O defeito era nosso e a tela mandava o
cliente corporativo culpar a própria internet.

O nome do arquivo já foi corrigido na raiz (ver `test_manutencao_tarefa.py`); isto aqui é
a rede de segurança para o PRÓXIMO defeito: qualquer erro não previsto tem de chegar como
500 com corpo e com os cabeçalhos de origem cruzada.
"""

from fastapi.testclient import TestClient

from app.main import app

ORIGEM = "http://localhost:5181"


@app.get("/api/v1/_teste_de_erro", include_in_schema=False)
def _rota_que_quebra() -> dict[str, str]:
    raise RuntimeError("defeito qualquer do servidor")


def test_erro_nao_previsto_e_500_com_corpo_e_com_cors():
    with TestClient(app, raise_server_exceptions=False) as http:
        r = http.get("/api/v1/_teste_de_erro", headers={"Origin": ORIGEM})

    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == ORIGEM
    detalhe = r.json()["detail"]
    # A frase acusa o servidor, não a rede de quem está lendo.
    assert "servidor" in detalhe.lower()
    assert "conexão" not in detalhe.lower()
    # E carrega um código para casar a tela com a linha do log.
    assert "informe o código" in detalhe


def test_o_traceback_nao_sai_na_resposta():
    """Quem lê é o cliente do cliente: mensagem, nunca pilha."""
    with TestClient(app, raise_server_exceptions=False) as http:
        r = http.get("/api/v1/_teste_de_erro", headers={"Origin": ORIGEM})

    corpo = r.text
    assert "RuntimeError" not in corpo
    assert "Traceback" not in corpo
