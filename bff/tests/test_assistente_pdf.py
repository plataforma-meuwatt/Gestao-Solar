"""PDF encaminhado ao bot e ASSINADO com o certificado digital da pessoa. Pedido do Renan (11/11/2026): "eu recebo um
PDF, encaminho e falo assina. Aí ele assina com o meu certificado digital". Antes o bot respondia "pelo WhatsApp eu
ainda não abro arquivos". A confirmação é o PIN de assinatura (escolha do dono depois da revisão adversarial): quem
trocasse o celular da conta no oem-gs não assina por ela.
"""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from app.models.conversa_whatsapp import ConversaWhatsapp, RegistroBot
from app.services import assistente
from app.services import assistente_geracao as ger
from app.services import assistente_helper as h
from app.services import assistente_pdf as pdf
from app.services import vinculos
from tests.test_assistente_whatsapp import _conta, bot_local  # noqa: F401 (bot_local é fixture)


def _erro(codigo, detalhe=""):
    req = httpx.Request("POST", "http://meuplano")
    return httpx.HTTPStatusError(str(codigo), request=req, response=httpx.Response(codigo, json={"detail": detalhe},
                                                                                   request=req))


PIN = "482913"


class _MeuPlano:
    def __init__(self):
        self.configurado, self.pin_configurado, self.recusa, self.assinados, self.erros = True, True, None, [], 0
        self.recusa_em = None                              # só o PDF com este conteúdo é recusado

    async def meu_certificado(self):
        return {"configurado": self.configurado, "pin_configurado": self.pin_configurado}

    async def assistente_chat(self, token, mensagens):
        return 1

    async def assistente_run(self, token, run_id):
        return {"status": "DONE", "type": "message", "text": "Não achei documento para mandar."}

    async def assinar_pdf(self, conteudo, nome, pin):
        if self.recusa and (self.recusa_em is None or self.recusa_em in conteudo):
            raise _erro(400, self.recusa)
        if pin != PIN:
            self.erros += 1
            raise _erro(400, f"PIN de assinatura errado (restam {5 - self.erros} tentativa(s)).")
        self.assinados.append((conteudo, nome))
        return b"ASSINADO " + conteudo, nome.removesuffix(".pdf") + " (assinado).pdf"


@pytest.fixture
def cenario(db, bot_local, monkeypatch):
    """A IA de mentira: "assina" (na legenda ou depois) vira `assinar_pdf`; o PDF sozinho, ela pergunta."""
    mp = _MeuPlano()
    monkeypatch.setattr(vinculos, "cliente_meuplano", lambda db_, uid, so_proprio=False: mp)
    arquivos = []

    async def _baixar(mid):
        return f"%PDF-{mid}".encode(), "application/pdf"

    async def _enviar(**k):
        if k.get("tipo") == "document":
            arquivos.append((k["filename"], k["arquivo"]))
        return await enviar_do_bot(**k)

    async def _nada(*a, **k):
        return None

    async def _llm(msgs, ferramentas=None, obrigatoria=False, **k):
        ultima = msgs[-1]
        if ultima["role"] == "tool":
            return {"content": json.loads(ultima["content"]).get("erro") or "Certo."}
        bot_local.llm.append(ultima["content"])
        n = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i]["role"] != "user"), -1)
        if any("assina" in m["content"].lower() for m in msgs[n + 1:]):   # o pedido: as mensagens seguidas dela
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "assinar_pdf", "arguments": "{}"}}]}
        return {"content": "É para assinar com o seu certificado?"}

    enviar_do_bot = assistente.whatsapp.enviar_conteudo
    monkeypatch.setattr(assistente.whatsapp, "enviar_conteudo", _enviar)
    monkeypatch.setattr(assistente.whatsapp, "baixar_midia", _baixar)
    monkeypatch.setattr(assistente, "_llm", _llm)
    monkeypatch.setattr(ger, "preparar", _nada)
    pdf._RECEBIDOS.clear()
    pdf._ESPERANDO.clear()
    return SimpleNamespace(mp=mp, arquivos=arquivos, bot=bot_local)


def _pessoa(db):
    return _conta(db, "renan", "+5517997377626")


def _pdf(p, n, nome="Contrato Cliente.pdf", legenda=""):
    return {"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "document", "texto": None,
            "midia": {"mime": "application/pdf", "nome": nome, "legenda": legenda}}


def _texto(p, n, texto):
    return {"id": n, "telefone": p.telefone, "wa_id": "1", "tipo": "text", "texto": texto}


@pytest.mark.parametrize("texto_antes", [False, True])
async def test_encaminhou_o_pdf_falou_assina_e_mandou_o_pin(db, cenario, monkeypatch, texto_antes):
    p = _pessoa(db)
    monkeypatch.setattr(assistente, "ESPERA_FOTO_S", 2)     # o PDF sem legenda espera o "assina" que vem logo depois
    monkeypatch.setattr(assistente, "ESPERA_TEXTO_S", 2)    # e o "assina" escrito antes espera o PDF
    msgs = [_pdf(p, 1), _texto(p, 2, "assina")]
    await asyncio.gather(*(assistente.atender(m) for m in (msgs[::-1] if texto_antes else msgs)))
    assert len(cenario.bot.llm) == 1                        # uma resposta só, para as duas mensagens
    assert pdf._ESPERANDO[p.id].resumo == "Assinar com o seu certificado digital o PDF: «Contrato Cliente.pdf»"
    assert "mande o seu PIN de assinatura" in cenario.bot.enviados[-1] and cenario.mp.assinados == []
    await assistente.atender(_texto(p, 3, PIN))
    assert cenario.mp.assinados == [(b"%PDF-1", "Contrato Cliente.pdf")]
    assert cenario.arquivos == [("Contrato Cliente (assinado).pdf", b"ASSINADO %PDF-1")]
    assert cenario.bot.enviados[-1] == ("✅ Assinado com o seu certificado digital (vai aqui no chat): "
                                        "«Contrato Cliente (assinado).pdf»")
    assert pdf.recebidos(p.telefone) == [] and p.id not in pdf._ESPERANDO
    # o PIN não foi à IA, não ficou no log, na conversa guardada nem no gateway
    assert all(PIN not in str(x) for x in cenario.bot.llm)
    assert db.query(RegistroBot).order_by(RegistroBot.id.desc()).first().pergunta == pdf.PIN
    assert all(PIN not in (r.pergunta or "") for r in db.query(RegistroBot))
    conv = db.query(ConversaWhatsapp).filter(ConversaWhatsapp.telefone == p.telefone).first()
    assert PIN not in (conv.mensagens if conv else "")
    assert 3 in cenario.bot.ocultadas and pdf.PIN in cenario.bot.textos_ocultados


async def test_o_pin_nao_conta_como_erro_da_senha_de_atuacao(db, cenario, monkeypatch):
    p = _pessoa(db)
    p.senha_atuacao_hash = "outra"
    db.commit()
    monkeypatch.setattr(h, "conferir_senha", lambda d, guardado: False)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, PIN))
    assert cenario.mp.assinados and p.id not in h._ERROS and p.id not in h._BLOQUEIO


async def test_pin_errado_pede_de_novo_e_o_certo_assina(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, "482914"))
    assert cenario.bot.enviados[-1] == "❌ PIN de assinatura errado (restam 4 tentativa(s)). Mande o PIN de novo."
    assert p.id in pdf._ESPERANDO and cenario.mp.assinados == []
    await assistente.atender(_texto(p, 3, PIN))
    assert cenario.bot.enviados[-1].startswith("✅ Assinado")


async def test_outra_mensagem_cancela_a_assinatura(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, "deixa pra lá"))
    assert p.id not in pdf._ESPERANDO and pdf.CANCELADA in cenario.bot.enviados[-1]
    await assistente.atender(_texto(p, 3, PIN))           # o PIN depois não assina nada
    assert cenario.mp.assinados == []


async def test_o_pdf_sozinho_pergunta_e_o_assina_seguinte_vale_para_ele(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, "Aditivo.pdf"))
    assert cenario.bot.enviados == ["É para assinar com o seu certificado?"] and p.id not in pdf._ESPERANDO
    assert cenario.bot.llm == ["[📄 PDF recebido: «Aditivo.pdf»]"]
    await assistente.atender(_texto(p, 2, "assina"))
    assert pdf._ESPERANDO[p.id].resumo == "Assinar com o seu certificado digital o PDF: «Aditivo.pdf»"


async def test_o_assina_vale_so_para_o_pdf_que_veio_com_ele(db, cenario):
    """O PDF mandado antes para outra coisa não entra (revisão adversarial de 11/11/2026)."""
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, "Aditivo.pdf"))                     # o bot perguntou; ela não respondeu
    await assistente.atender(_texto(p, 2, "deixa, depois eu vejo"))
    await assistente.atender(_pdf(p, 3, "Proposta.pdf", legenda="assina"))
    assert cenario.bot.llm[-1] == "[📄 PDF recebido: «Proposta.pdf»] assina"
    assert pdf._ESPERANDO[p.id].resumo == "Assinar com o seu certificado digital o PDF: «Proposta.pdf»"
    ctx = ger.Contexto(db=db, user=p, telefone=p.telefone, pedido="assina todos")   # os outros só com "todos"
    pdf.cancelar(p.id)                                    # outra mensagem: a espera de antes caiu
    await pdf.assinar_pdf(ctx, {"todos": True})
    assert pdf._ESPERANDO[p.id].resumo == "Assinar com o seu certificado digital 2 PDFs: «Aditivo.pdf», «Proposta.pdf»"


async def test_a_versao_nova_com_o_mesmo_nome_nao_leva_a_antiga(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, "Contrato.pdf"))                    # a versão 1, sem pedido
    await assistente.atender(_texto(p, 2, "ok"))
    await assistente.atender(_pdf(p, 3, "Contrato.pdf", legenda="assina"))  # a corrigida
    assert [x["id"] for x in pdf._ESPERANDO[p.id].pdfs] == [3]
    await assistente.atender(_texto(p, 4, PIN))
    assert cenario.mp.assinados == [(b"%PDF-3", "Contrato.pdf")]


async def test_sem_certificado_ou_sem_pin_diz_onde_criar_e_nada_espera(db, cenario):
    p = _pessoa(db)
    cenario.mp.configurado = False
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    assert p.id not in pdf._ESPERANDO and "Minha conta" in cenario.bot.enviados[-1]
    cenario.mp.configurado, cenario.mp.pin_configurado = True, False
    await assistente.atender(_pdf(p, 2, legenda="assina"))
    assert p.id not in pdf._ESPERANDO and "PIN de assinatura" in cenario.bot.enviados[-1]


async def test_a_recusa_do_meuplano_chega_inteira_e_o_pdf_fica_para_tentar_de_novo(db, cenario):
    p = _pessoa(db)
    cenario.mp.recusa = "Seu certificado digital venceu em 01/11/2026: cadastre o novo em Minha conta."
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, PIN))
    assert cenario.bot.enviados[-1] == ("❌ Seu certificado digital venceu em 01/11/2026: cadastre o novo em Minha "
                                        "conta. Nada foi assinado.")
    assert cenario.arquivos == [] and len(pdf.recebidos(p.telefone)) == 1 and p.id not in pdf._ESPERANDO


async def test_o_assina_com_pdf_recebido_nao_vira_assinatura_de_os_no_meuplano(db, cenario):
    p = _pessoa(db)
    pdf.guardar(p.telefone, _pdf(p, 1))
    ctx = ger.Contexto(db=db, user=p, telefone=p.telefone, historico=[],
                       pedido="[📄 PDF recebido: «Contrato Cliente.pdf»]\nassina os dois PDFs que mandei")
    for pergunta in ("assina o PDF que mandei", "assina os dois PDFs que mandei", "assinar o contrato"):
        r = await assistente.manutencao(ctx, {"pergunta": pergunta})   # "os" é artigo, não OS
        assert "assinar_pdf" in r.get("erro", ""), (pergunta, r)
    assert p.id not in h.PENDENTES and p.id not in pdf._ESPERANDO
    # o PDF sozinho, o bot perguntou, ela disse "assina": o PDF é do pedido anterior
    ctx.historico = [{"role": "user", "content": "[📄 PDF recebido: «Contrato Cliente.pdf»]"},
                     {"role": "assistant", "content": "É para assinar?"}]
    ctx.pedido = "assina"
    assert "assinar_pdf" in (await assistente.manutencao(ctx, {"pergunta": "assina"})).get("erro", "")
    # sem PDF, o documento assinado do meuPlano vai ao meuPlano (que o entrega sem assinar; o bot pede o PIN)
    ctx.historico, ctx.pedido = [], "me manda o laudo de termografia de Ibitinga assinado"
    assert "texto" in await assistente.manutencao(ctx, {"pergunta": ctx.pedido})
    # o PDF da OS também, mesmo com um PDF recebido junto
    ctx.pedido = "[📄 PDF recebido: «Contrato Cliente.pdf»]\nme manda o PDF da OS 1638 assinado"
    r = await assistente.manutencao(ctx, {"pergunta": "me manda o PDF da OS 1638 assinado"})
    assert r == {"texto": "Não achei documento para mandar."} and p.id not in h.PENDENTES


def test_so_quem_tem_o_meuplano_liberado_recebe_a_ferramenta(db):
    com = _conta(db, "com", "+5517990000001")
    sem = _conta(db, "sem", "+5517990000002")
    sem.bot_meuplano = False
    db.commit()
    assert "assinar_pdf" in assistente.permitidas(com) and "assinar_pdf" not in assistente.permitidas(sem)


async def test_o_numero_numa_frase_some_e_a_frase_segue_como_pedido(db, cenario):
    """"meu pin é 482913" ou "cancela, me diz a geração da UC 40028922": o número que pode ser o PIN some (gateway,
    IA, log), a assinatura é cancelada e a frase segue como pedido — nada se perde (revisões de 11/11/2026)."""
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, "meu pin é 482913 ok"))
    assert cenario.bot.llm[-1] == f"meu pin é {h.OCULTO} ok" and PIN not in str(cenario.bot.llm)
    assert not assistente._pede_assinatura(cenario.bot.llm[-1])   # o marcador neutro não vira pedido de assinatura
    assert 2 in cenario.bot.ocultadas and pdf.CANCELADA in cenario.bot.enviados[-1]
    pdf.cancelar(p.id)
    await assistente.atender(_pdf(p, 3, legenda="assina"))
    await assistente.atender(_texto(p, 4, "4️⃣8️⃣2️⃣9️⃣1️⃣3️⃣ cancela, me diz a geração da UC 40028922"))
    assert "UC 40028922" in cenario.bot.llm[-1] and "cancela, me diz a geração" in cenario.bot.llm[-1]   # a UC segue
    assert "4️⃣" not in cenario.bot.llm[-1], "o PIN em dígitos de emoji foi à IA"
    assert PIN not in str(cenario.bot.llm) and cenario.mp.assinados == []
    assert all(PIN not in (r.pergunta or "") for r in db.query(RegistroBot))


async def test_a_uc_segue_normal_e_fora_da_zona_nada_muda(db, cenario):
    """Na zona do PIN só o número de 6 dígitos (o tamanho do PIN) some: a UC vai à IA. Passada a zona, nada muda."""
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, PIN))
    await assistente.atender(_texto(p, 3, "40028922"))            # 8 números: não é o PIN
    assert cenario.bot.llm[-1] == "40028922"
    await assistente.atender(_texto(p, 4, "qual a geração da UC 40028922?"))
    assert cenario.bot.llm[-1] == "qual a geração da UC 40028922?"
    pdf._ZONA_ATE[p.id] = 0                                        # 5 h depois
    await assistente.atender(_texto(p, 5, "582913"))
    assert cenario.bot.llm[-1] == "582913"


async def test_o_pin_mandado_antes_do_pedido_aparecer_nao_vale(db, cenario):
    p = _pessoa(db)
    await asyncio.gather(assistente.atender(_pdf(p, 1, legenda="assina")), assistente.atender(_texto(p, 2, PIN)))
    assert "antes de o pedido de assinatura chegar" in cenario.bot.enviados[-1] and cenario.mp.assinados == []
    await assistente.atender(_texto(p, 3, PIN))
    assert cenario.mp.assinados


async def test_o_pin_atrasado_depois_da_espera_nao_vai_a_ia_nem_a_senha_de_atuacao(db, cenario, monkeypatch):
    p = _pessoa(db)
    p.senha_atuacao_hash = "outra"
    db.commit()
    monkeypatch.setattr(h, "conferir_senha", lambda d, guardado: False)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, PIN))
    llm = list(cenario.bot.llm)
    await assistente.atender(_texto(p, 3, PIN))             # mandou de novo, achando que não tinha ido
    assert cenario.bot.enviados[-1].startswith("Não há assinatura esperando o PIN") and 3 in cenario.bot.ocultadas
    assert cenario.bot.llm == llm and p.id not in h._ERROS


async def test_um_pdf_recusado_nao_desiste_dos_outros(db, cenario):
    p = _pessoa(db)
    cenario.mp.recusa, cenario.mp.recusa_em = "Esse arquivo não é um PDF", b"%PDF-1"
    await assistente.atender(_pdf(p, 1, "A.pdf"))
    await assistente.atender(_pdf(p, 2, "B.pdf", legenda="assina os dois"))
    ctx = ger.Contexto(db=db, user=p, telefone=p.telefone, pedido="assina todos")
    pdf.cancelar(p.id)                                    # outra mensagem: a espera de antes caiu
    await pdf.assinar_pdf(ctx, {"todos": True})
    pdf.pedido_saiu(p.id, True, lambda: datetime.now(UTC))
    await assistente.atender(_texto(p, 3, PIN))
    assert cenario.mp.assinados == [(b"%PDF-2", "B.pdf")]
    assert cenario.bot.enviados[-1].startswith("⚠️ Assinei 1 de 2") and "não é um PDF" in cenario.bot.enviados[-1]


async def test_com_a_assinatura_esperando_o_pin_nenhuma_outra_acao_arma(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    ctx = ger.Contexto(db=db, user=p, telefone=p.telefone, pedido="desliga o inversor 3")

    async def executar(db_, u, t):
        return "feito"

    r = h.propor(ctx, "Desligar o inversor 3", 60, executar)
    assert "assinatura esperando o PIN" in r["erro"] and p.id not in h.PENDENTES


async def test_outra_ferramenta_armada_enquanto_o_meuplano_respondia_vence(db, cenario, monkeypatch):
    """As ferramentas de uma mensagem rodam juntas: a proposta que a outra armou durante o `await` não é apagada."""
    p = _pessoa(db)
    pdf.guardar(p.telefone, _pdf(p, 1))
    ctx = ger.Contexto(db=db, user=p, telefone=p.telefone, pedido="[📄 PDF recebido: «Contrato Cliente.pdf»] assina")
    antes = cenario.mp.meu_certificado

    async def _arma_no_meio():
        ctx.proposta = object()                           # a outra ferramenta, no meio do caminho
        return await antes()

    monkeypatch.setattr(cenario.mp, "meu_certificado", _arma_no_meio)
    r = await pdf.assinar_pdf(ctx, {})
    assert "Uma ação por vez" in r["erro"] and p.id not in pdf._ESPERANDO


async def test_o_pin_depois_de_aqui_esta_meu_pin_ainda_some(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, "aqui está meu pin"))
    llm = list(cenario.bot.llm)
    await assistente.atender(_texto(p, 3, PIN))
    assert cenario.bot.llm == llm and 3 in cenario.bot.ocultadas and PIN not in str(cenario.bot.llm)
    await assistente.atender(_texto(p, 4, "ok"))
    await assistente.atender(_texto(p, 5, "o pin é 482913"))          # a frase com o PIN, ainda na zona
    assert PIN not in str(cenario.bot.llm)
    conv = db.query(ConversaWhatsapp).filter(ConversaWhatsapp.telefone == p.telefone).first()
    assert PIN not in (conv.mensagens if conv else "")


async def test_a_espera_vencida_nao_mascara_nem_avisa_a_conversa_de_horas_depois(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    pdf._ESPERANDO[p.id].expira = 0                       # venceu calada
    await assistente.atender(_texto(p, 2, "qual a geração da UC 40028922 em outubro?"))
    assert cenario.bot.llm[-1] == "qual a geração da UC 40028922 em outubro?"
    assert pdf.CANCELADA not in cenario.bot.enviados[-1] and p.id not in pdf._ESPERANDO
    await assistente.atender(_texto(p, 3, "meu pin é 482913"))       # o PIN numa frase, 30 s depois do prazo
    assert PIN not in str(cenario.bot.llm)


async def test_o_aviso_da_assinatura_cancelada_nao_some_na_juncao(db, cenario, monkeypatch):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    monkeypatch.setattr(assistente, "ESPERA_TEXTO_S", 2)
    await asyncio.gather(assistente.atender(_texto(p, 2, "espera")),
                         assistente.atender(_texto(p, 3, "qual a geração de hoje?")))
    assert any(pdf.CANCELADA in (t or "") for t in cenario.bot.enviados[1:])


async def test_parte_desligada_no_meio_o_pin_nao_segue_adiante(db, cenario):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    p.bot_meuplano = False
    db.commit()
    llm = list(cenario.bot.llm)
    await assistente.atender(_texto(p, 2, PIN))
    assert "desligada" in cenario.bot.enviados[-1] and 2 in cenario.bot.ocultadas and cenario.bot.llm == llm
    await assistente.atender(_texto(p, 3, "40028922"))           # sem a parte, sem zona: o número não é engolido
    assert "desligada" not in cenario.bot.enviados[-1]


def test_sem_assinatura_nao_e_pedido_de_assinatura():
    for frase in ("me manda o PDF da OS 1638 sem assinatura", "o PDF da OS 1638, não precisa assinar",
                  "manda a OS 1638 sem a assinatura", "Manda o PDF da OS 1638, não precisa assinar não",
                  "Me manda o PDF da OS 1638 sem assinatura, não precisa",
                  "Manda o PDF da OS 1638 sem assinatura, ainda não foi aprovada",
                  "O PDF da OS 1638 não precisa ser assinado não"):
        assert not assistente._pede_assinatura(frase), frase
    assert assistente._pede_assinatura("me manda o PDF da OS 1638 assinado")
    for frase in ("me manda a OS 1638, sem assinatura não vale", "o cliente não aceita sem assinatura: manda a OS 1638",
                  "a OS 1638 sem assinatura não serve, me manda ela",
                  "não precisa assinar de novo, só manda a OS 1638 assinada", "me manda a OS 1638, sem assinatura não dá",
                  "sem assinatura o cliente recusa, me manda a OS 1638",
                  "a OS 1638 sem assinatura não é aceita, manda ela",
                  "me manda a OS 1638, sem assinatura não tem validade", "sem assinatura não vai servir, me manda a OS 1638",
                  "a OS 1638 sem assinatura não presta, manda ela", "sem assinatura fica sem validade, manda a OS 1638"):
        assert assistente._pede_assinatura(frase), frase


async def test_o_pin_na_legenda_ou_no_audio_dentro_da_zona_some(db, cenario, monkeypatch):
    """A legenda do PDF/da foto e a transcrição do áudio viram texto DEPOIS do gancho: a regra da zona vale para elas
    também (7ª revisão de 11/11/2026)."""
    from app.services import assistente_fotos as fotos

    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, PIN))                     # assinou: a zona segue por 10 min
    await assistente.atender(_pdf(p, 3, "Outro.pdf", legenda="assina, o pin é 482913"))
    await assistente.atender({"id": 4, "telefone": p.telefone, "wa_id": "1", "tipo": "image", "texto": None,
                              "midia": {"mime": "image/jpeg", "legenda": "pin 482913"}})
    assert all(f["legenda"] != "pin 482913" for f in fotos.recebidas(p.telefone))   # nem vira a descrição da foto

    async def _ouvir(db_, u, ev):
        return "meu pin é 482913", None

    monkeypatch.setattr(assistente, "_ouvir", _ouvir)
    await assistente.atender({"id": 5, "telefone": p.telefone, "wa_id": "1", "tipo": "audio", "texto": None})
    assert PIN not in str(cenario.bot.llm) and all(PIN not in (t or "") for t in cenario.bot.enviados)   # nem no eco
    conv = db.query(ConversaWhatsapp).filter(ConversaWhatsapp.telefone == p.telefone).first()
    assert PIN not in (conv.mensagens if conv else "")
    assert all(PIN not in (r.pergunta or "") for r in db.query(RegistroBot))


async def test_com_acao_esperando_o_sim_o_pin_atrasado_tambem_some(db, cenario):
    """A exceção é só para a ação do helper que espera a SENHA DE ATUAÇÃO; a do meuPlano espera o Sim."""
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, PIN))
    ctx = ger.Contexto(db=db, user=p, telefone=p.telefone, pedido="crie a OS")

    async def executar(db_, u, t):
        return "feito"

    h.propor(ctx, "Criar a OS", 60, executar, confirmacao="sim")
    h.mostrada(p.id)
    llm = list(cenario.bot.llm)
    await assistente.atender(_texto(p, 3, PIN))
    assert cenario.bot.llm == llm and 3 in cenario.bot.ocultadas


async def test_na_zona_o_pdf_com_numero_no_nome_ainda_se_assina(db, cenario):
    """O nome do PDF («NF 482917.pdf») não é o PIN: só a legenda passa pela máscara da zona."""
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, PIN))                     # na zona
    await assistente.atender(_pdf(p, 3, "NF 482917.pdf", legenda="assina"))
    assert pdf._ESPERANDO[p.id].resumo == "Assinar com o seu certificado digital o PDF: «NF 482917.pdf»"


async def test_na_zona_a_senha_de_atuacao_dita_no_audio_segue_para_a_acao(db, cenario, monkeypatch):
    p = _pessoa(db)
    await assistente.atender(_pdf(p, 1, legenda="assina"))
    await assistente.atender(_texto(p, 2, PIN))                     # na zona
    ctx = ger.Contexto(db=db, user=p, telefone=p.telefone, pedido="desliga o inversor 3")
    p.senha_atuacao_hash = "x"
    db.commit()

    async def executar(db_, u, t):
        return "✅ desligado"

    h.propor(ctx, "Desligar o inversor 3", 60, executar)          # espera a SENHA de atuação
    assert pdf.sem_o_pin(p.id, "4 8 2 9 1 4") == "4 8 2 9 1 4"      # dita em voz alta: é dela, não some
    assert pdf.sem_o_pin(p.id, "meu pin é 482914") != "meu pin é 482914"   # numa frase, some
