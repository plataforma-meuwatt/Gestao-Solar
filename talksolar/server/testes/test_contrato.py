# -*- coding: utf-8 -*-
"""Talk Solar — o contrato, testado de ponta a ponta.

    python testes/test_contrato.py

Roda num SQLite em memória com um SISTEMA FALSO no lugar do meuPlano: o teste levanta os três
endpoints do contrato (identidade, busca, label) e um receptor de webhook. É assim que se prova
que a integração funciona **sem depender de nenhum sistema estar no ar** — e é o mesmo roteiro
que o próximo programador vai seguir para o meuWatt.

O que se prova:
  1. A sessão é EMPRESTADA: token do sistema vira sessão daqui; token recusado lá = 401 aqui.
  2. Sistema fora do ar responde 502 (e não 500): a culpa fica com quem é.
  3. Canal do alvo é IDEMPOTENTE; alvo inexistente é 404.
  4. Mensagem com anexo nasce junto do arquivo, e o inválido é recusado ANTES de gravar.
  5. Citação guarda o rótulo CONGELADO e responde à pergunta inversa.
  6. Visibilidade: canal privado alheio é 404 (nunca 403); sistemas diferentes não se veem.
  7. Webhook sai ASSINADO, o receptor confere, e a falha é REENVIADA.
  8. Webhook de volta vira mensagem de sistema — e assinatura errada é recusada.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///./teste_talksolar.db")
os.environ.setdefault("TALK_JWT_SECRET", "teste-nao-vale-em-producao")
os.environ.setdefault("TALK_STORAGE", "local")
os.environ.setdefault("TALK_STORAGE_DIR", str(Path(__file__).resolve().parent / "_arquivos"))
os.environ["TALK_SEM_WORKER"] = "1"          # o worker é chamado à mão, para o teste ser exato

from fastapi.testclient import TestClient     # noqa: E402

from app import webhooks                      # noqa: E402
from app.config import SessionLocal, engine   # noqa: E402
from app.main import app as api               # noqa: E402
from app.models import App, Base, Entrega     # noqa: E402

ok = 0
falhas: list[str] = []
RECEBIDOS: list[dict] = []
SEGREDO = "segredo-do-sistema-falso"
FALHAR_WEBHOOK = {"vezes": 0}


def checar(nome: str, cond: bool, detalhe: str = "") -> None:
    global ok
    if cond:
        ok += 1
        print(f"  OK   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome} {detalhe}")


# ---------------------------------------------------------------- o SISTEMA FALSO
class Sistema(BaseHTTPRequestHandler):
    """Implementa o contrato de docs/API.md §4 e §5 — é o molde do que cada sistema faz."""

    def _responder(self, codigo: int, corpo: dict) -> None:
        dados = json.dumps(corpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_POST(self):  # noqa: N802
        tamanho = int(self.headers.get("Content-Length") or 0)
        cru = self.rfile.read(tamanho)
        corpo = json.loads(cru or b"{}")

        if self.path == "/identidade":
            # o segredo autentica a Talk Solar chamando o sistema
            if self.headers.get("X-Talk-Secret") != SEGREDO:
                return self._responder(401, {"detail": "segredo errado"})
            if corpo.get("token") != "token-bom":
                return self._responder(401, {"detail": "token inválido"})
            return self._responder(200, {"externo_id": "179", "nome": "Renan",
                                         "email": "renan@exemplo.com", "ativo": True})

        if self.path == "/refs/buscar":
            return self._responder(200, {"itens": [
                {"tipo": "usina", "id": "238", "label": "UFV Porto Ferreira",
                 "url": "https://sistema/usinas/238"}]})

        if self.path == "/refs/label":
            saida = []
            for a in corpo.get("alvos", []):
                if str(a.get("id")) == "238":
                    saida.append({"tipo": "usina", "id": "238",
                                  "label": "UFV Porto Ferreira",
                                  "url": "https://sistema/usinas/238"})
            return self._responder(200, {"itens": saida})

        if self.path == "/webhook":
            # o receptor CONFERE a assinatura antes de ler o corpo — é o exemplo a copiar
            esperada = "sha256=" + hmac.new(SEGREDO.encode(), cru, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(esperada, self.headers.get("X-Talk-Assinatura", "")):
                return self._responder(401, {"detail": "assinatura inválida"})
            if FALHAR_WEBHOOK["vezes"] > 0:
                FALHAR_WEBHOOK["vezes"] -= 1
                return self._responder(500, {"detail": "de propósito"})
            RECEBIDOS.append({"evento": self.headers.get("X-Talk-Evento"), "corpo": corpo,
                              "entrega": self.headers.get("X-Talk-Entrega")})
            return self._responder(200, {"ok": True})

        self._responder(404, {"detail": "nao existe"})

    def log_message(self, *a):    # silêncio: o log do teste é o do teste
        pass


def subir_sistema() -> tuple[HTTPServer, str]:
    srv = HTTPServer(("127.0.0.1", 0), Sistema)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def png(largura=900, altura=600) -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (largura, altura), (200, 120, 60)).save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:  # noqa: C901
    Path(os.environ["TALK_STORAGE_DIR"]).mkdir(parents=True, exist_ok=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    srv, base = subir_sistema()
    c = TestClient(api)
    db = SessionLocal()
    try:
        db.add(App(slug="sistemafalso", nome="Sistema Falso", secret=SEGREDO,
                   identidade_url=f"{base}/identidade",
                   refs_busca_url=f"{base}/refs/buscar",
                   refs_label_url=f"{base}/refs/label",
                   webhook_url=f"{base}/webhook"))
        db.commit()

        # ---------------------------------------------------- 1) sessão emprestada
        r = c.post("/v1/sessao", json={"app": "sistemafalso", "token": "token-ruim"})
        checar("token recusado pelo sistema = 401 aqui", r.status_code == 401, str(r.status_code))
        r = c.post("/v1/sessao", json={"app": "naoexiste", "token": "x"})
        checar("sistema não integrado = 404 (e diz quais existem)",
               r.status_code == 404 and "sistemafalso" in r.text, r.text[:100])
        r = c.post("/v1/sessao", json={"app": "sistemafalso", "token": "token-bom",
                                       "dispositivo": "PC de teste"})
        checar(">> sessão emprestada do sistema (200)", r.status_code == 200, r.text[:140])
        sessao = r.json()
        checar("  ...e o usuário virou espelho, com o id EXTERNO",
               sessao["usuario"]["externo_id"] == "179", str(sessao["usuario"]))
        c.headers.update({"Authorization": f"Bearer {sessao['token']}"})

        r = c.post("/v1/sessao/refresh", json={"refresh": sessao["refresh"]})
        checar("renovar devolve token novo (o app fica aberto o dia inteiro)",
               r.status_code == 200 and r.json().get("token"), r.text[:120])

        # ---------------------------------------------------- 2) sistema fora do ar
        app_row = db.query(App).filter(App.slug == "sistemafalso").first()
        antes = app_row.identidade_url
        app_row.identidade_url = "http://127.0.0.1:9/identidade"   # porta morta
        db.commit()
        r = c.post("/v1/sessao", json={"app": "sistemafalso", "token": "token-bom"})
        checar(">> sistema fora do ar = 502, dizendo de quem é a culpa",
               r.status_code == 502 and "não respondeu" in r.text, f"{r.status_code} {r.text[:90]}")
        app_row.identidade_url = antes
        db.commit()

        # ---------------------------------------------------- 3) canal do alvo
        r = c.post("/v1/canais/do-alvo", json={"tipo": "usina", "id": "238"})
        checar("canal do alvo abre (200)", r.status_code == 200, r.text[:140])
        canal = r.json()
        checar("  ...com o rótulo vindo do SISTEMA",
               canal["alvo"]["label"] == "UFV Porto Ferreira", str(canal)[:140])
        r2 = c.post("/v1/canais/do-alvo", json={"tipo": "usina", "id": "238"})
        checar(">> dois cliques abrem o MESMO canal (idempotente)",
               r2.json()["id"] == canal["id"], f"{canal['id']} x {r2.json().get('id')}")
        r = c.post("/v1/canais/do-alvo", json={"tipo": "usina", "id": "999"})
        checar("alvo que o sistema não conhece = 404", r.status_code == 404, str(r.status_code))

        # ---------------------------------------------------- 4) anexos
        r = c.post(f"/v1/canais/{canal['id']}/mensagens/anexos",
                   files=[("arquivos", ("campo.png", png(), "image/png"))],
                   data={"conteudo": ""})
        checar(">> mensagem só com foto (sem texto) é aceita (201)", r.status_code == 201,
               r.text[:160])
        msg = r.json()
        anexo = (msg.get("anexos") or [{}])[0]
        checar("  ...com miniatura e dimensões lidas do arquivo",
               anexo.get("largura") == 900 and anexo.get("thumb_url"), str(anexo)[:160])
        n_antes = db.query(Entrega).count()
        r = c.post(f"/v1/canais/{canal['id']}/mensagens/anexos",
                   files=[("arquivos", ("v.exe", b"MZ", "application/x-msdownload"))],
                   data={"conteudo": "toma"})
        checar("arquivo de tipo não suportado = 400", r.status_code == 400, r.text[:120])

        # ---------------------------------------------------- 5) citação
        r = c.post(f"/v1/canais/{canal['id']}/mensagens", json={
            "conteudo": "olha o inversor 3",
            "refs": [{"tipo": "usina", "id": "238"},
                     {"tipo": "usina", "id": "999"}]})       # 999 o sistema não conhece
        checar("mensagem com citação (201)", r.status_code == 201, r.text[:140])
        m2 = r.json()
        checar(">> citou 1 alvo — o inexistente não virou link quebrado",
               len(m2["refs"]) == 1, str(m2["refs"])[:140])
        checar("  ...com o rótulo CONGELADO do sistema",
               m2["refs"][0]["label"] == "UFV Porto Ferreira", str(m2["refs"])[:140])
        r = c.get("/v1/refs/usina/238/mensagens")
        checar(">> a pergunta inversa responde", r.status_code == 200
               and any(x["id"] == m2["id"] for x in r.json()), r.text[:140])
        r = c.get("/v1/refs/buscar", params={"q": "porto"})
        checar("a busca de alvos repassa ao sistema",
               r.status_code == 200 and r.json() and r.json()[0]["tipo"] == "usina", r.text[:140])

        # ---------------------------------------------------- 6) visibilidade
        db.add(App(slug="outro", nome="Outro Sistema", secret="x",
                   identidade_url=f"{base}/identidade"))
        db.commit()
        from app.models import Canal as CanalM, Usuario as UsuarioM
        outro_app = db.query(App).filter(App.slug == "outro").first()
        alheio = UsuarioM(app_id=outro_app.id, externo_id="1", nome="Alheio")
        db.add(alheio); db.flush()
        canal_alheio = CanalM(app_id=outro_app.id, tipo="publico", nome="Do outro sistema")
        db.add(canal_alheio); db.commit()
        r = c.get(f"/v1/canais/{canal_alheio.id}/mensagens")
        checar(">> canal de OUTRO sistema = 404 (sistemas não se enxergam)",
               r.status_code == 404, str(r.status_code))
        privado = CanalM(app_id=db.query(App).filter(App.slug == "sistemafalso").first().id,
                         tipo="privado", nome="Privado alheio")
        db.add(privado); db.commit()
        r = c.get(f"/v1/canais/{privado.id}/mensagens")
        checar("canal PRIVADO em que não estou = 404 (nunca 403)", r.status_code == 404,
               str(r.status_code))
        r = c.get("/v1/canais")
        checar("  ...e ele não aparece na minha lista",
               all(x["id"] != privado.id for x in r.json()), str(r.json())[:140])

        # ---------------------------------------------------- 7) webhook sai assinado
        checar("as mensagens enfileiraram avisos", db.query(Entrega).count() > n_antes,
               f"{db.query(Entrega).count()}")
        webhooks.rodada()
        checar(">> o webhook chegou ao sistema, com assinatura conferida",
               any(x["evento"] == "mensagem.criada" for x in RECEBIDOS),
               str([x['evento'] for x in RECEBIDOS])[:140])
        recebido = next(x for x in RECEBIDOS if x["evento"] == "mensagem.criada")
        checar("  ...com o alvo do canal e o id EXTERNO do autor",
               recebido["corpo"]["canal"]["alvo"]["id"] == "238"
               and recebido["corpo"]["mensagem"]["autor"]["externo_id"] == "179",
               str(recebido["corpo"])[:160])
        checar("  ...e com o id da entrega (é por ele que o outro lado fica idempotente)",
               bool(recebido["entrega"]))
        pendentes = db.query(Entrega).filter(Entrega.estado == "pendente").count()
        checar("  ...e nada ficou pendente", pendentes == 0, f"{pendentes} pendente(s)")

        # o REENVIO
        FALHAR_WEBHOOK["vezes"] = 1
        c.post(f"/v1/canais/{canal['id']}/mensagens", json={"conteudo": "vai falhar uma vez"})
        webhooks.rodada()
        e = db.query(Entrega).order_by(Entrega.id.desc()).first()
        db.refresh(e)
        checar(">> falha no webhook vira REENVIO agendado (não desiste calado)",
               e.estado == "pendente" and e.tentativas == 1 and e.proxima_em is not None,
               f"{e.estado}/{e.tentativas}")
        e.proxima_em = e.criada_em            # adianta o relógio para não esperar 30 s
        db.commit()
        webhooks.rodada()
        db.refresh(e)
        checar("  ...e o reenvio entrega", e.estado == "entregue", f"{e.estado} {e.resposta}")

        # ---------------------------------------------------- 8) webhook de volta
        corpo = json.dumps({"evento": "alvo.mudou", "alvo": {"tipo": "usina", "id": "238"},
                            "texto": "OS fechada por Renan"}).encode()
        assinatura = "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
        r = c.post("/v1/webhooks/sistemafalso", content=corpo,
                   headers={"X-Talk-Assinatura": "sha256=errada"})
        checar("webhook de volta com assinatura ERRADA = 401", r.status_code == 401,
               str(r.status_code))
        r = c.post("/v1/webhooks/sistemafalso", content=corpo,
                   headers={"X-Talk-Assinatura": assinatura})
        checar(">> webhook de volta vira mensagem DE SISTEMA na conversa do alvo",
               r.status_code == 200 and r.json().get("postado"), r.text[:140])
        r = c.get(f"/v1/canais/{canal['id']}/mensagens")
        do_sistema = [m for m in r.json() if m.get("do_sistema")]
        checar("  ...e ela aparece marcada como do sistema, sem autor",
               len(do_sistema) == 1 and do_sistema[0]["autor"]["id"] is None,
               str(do_sistema)[:140])

        # ---------------------------------------------------- saúde
        r = c.get("/saude")
        checar("/saude diz o que falta configurar (não só 'ok')",
               r.status_code == 200 and isinstance(r.json().get("pendencias_de_config"), list),
               r.text[:140])
    finally:
        db.close()
        srv.shutdown()
        import shutil
        shutil.rmtree(os.environ["TALK_STORAGE_DIR"], ignore_errors=True)
        # o SQLite fica TRAVADO enquanto o pool tiver conexao aberta: sem o dispose, o arquivo
        # de teste sobra na pasta a cada rodada (residuo de teste e proibido)
        engine.dispose()
        Path("./teste_talksolar.db").unlink(missing_ok=True)

    print(f"\n{ok} OK / {len(falhas)} falha(s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
