"""PDF recebido pelo WhatsApp e ASSINADO com o certificado digital da pessoa (pedido do Renan, 11/11/2026: "eu recebo
um PDF, encaminho e falo assina. Aí ele assina com o meu certificado digital, porque meu certificado tá na plataforma").

O PDF fica guardado aqui (o id da mensagem no gateway), como as fotos. A IA lê «[📄 PDF recebido: «x.pdf»]» e, pedida a
assinatura, chama `assinar_pdf`: o sistema confere no meuPlano o certificado e o PIN de assinatura da pessoa e pede o
PIN ("Assinar com o seu certificado digital o PDF «x.pdf». Mande o seu PIN…"). O PIN é a confirmação: só o dono do
certificado o cria, no meuPlano, com a senha do certificado — quem trocasse o celular da conta dele no oem-gs não
assinaria por ele (revisão adversarial de 11/11/2026; o dono escolheu o PIN). A mensagem do PIN é tratada ANTES de
tudo no turno (`receber_pin`): não vai à IA, ao log, à conversa guardada nem fica no gateway. Com ele, o PDF sai do
gateway, vai ao meuPlano com o token DELA (`POST /auth/me/certificado/assinar`, que confere o PIN: 5 erros bloqueiam)
e volta assinado no chat. O meuPlano não guarda o PDF; no log de lá fica quem assinou, quando e o hash dos arquivos.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

import httpx

from app.clients import whatsapp
from app.core.datas import hora_brt
from app.services import assistente_helper as helper

log = logging.getLogger(__name__)

#: Os PDFs de cada número ainda não assinados: id da mensagem no gateway, nome, legenda, quando chegou.
#: ponytail: em memória, como as fotos; o deploy esquece, e a pessoa encaminha de novo.
_RECEBIDOS: dict[str, list[dict]] = {}
VALIDADE_S = 30 * 60
TETO = 10
#: Quanto o pedido de assinatura espera o PIN.
PRAZO_S = 600
PIN = "[PIN de assinatura]"
CANCELADA = "(A assinatura que esperava o seu PIN foi cancelada. Se ainda quiser, peça de novo.)"


#: A ZONA DO PIN vai do pedido do PIN até 10 min depois de a espera acabar (assinou, cancelou, bloqueou ou venceu):
#: nela, todo número de 6 dígitos (o tamanho do PIN) some antes da IA, do log e do gateway — sozinho ou numa frase.
#: Fora dela, nada muda. Uma regra só: as janelas de antes, cada uma com a sua exceção, deixavam o PIN passar por uma
#: fresta a cada revisão (11/11/2026).
JANELA_S = 10 * 60


@dataclass
class Espera:
    #: `{"id", "nome"}` (o PDF guardado no gateway) ou `{"bytes", "nome"}` (o documento que o meuPlano gerou).
    pdfs: list[dict]
    expira: float
    resumo: str
    #: Quando o pedido do PIN saiu (relógio daqui, hora do banco), como `helper.Pendente`: PIN de antes não vale.
    mostrada_em: tuple[float, datetime] | None = None


#: O pedido de assinatura de cada pessoa (id da conta) esperando o PIN — um por vez, em memória como `helper.PENDENTES`.
#: ponytail: um deploy esquece a espera; a janela de `_ZONA_ATE` também, e o PIN atrasado vai ao fluxo comum.
_ESPERANDO: dict[int, Espera] = {}
#: Até quando vai a zona do PIN de cada pessoa (relógio daqui).
_ZONA_ATE: dict[int, float] = {}
#: A espera que caiu numa mensagem JUNTADA à seguinte: o aviso sai na resposta que junta as duas.
_AVISAR: set[int] = set()


def e_pdf(evento: dict) -> bool:
    m = evento.get("midia") or {}
    return evento.get("tipo") == "document" and (
        str(m.get("mime") or "").startswith("application/pdf") or str(m.get("nome") or "").lower().endswith(".pdf"))


def _nome(evento: dict) -> str:
    return str((evento.get("midia") or {}).get("nome") or "").strip() or "documento.pdf"


def recebidos(telefone: str) -> list[dict]:
    agora = monotonic()
    return [p for p in _RECEBIDOS.get(telefone, []) if agora - p["em"] < VALIDADE_S]


def guardar(telefone: str, evento: dict) -> None:
    """Na CHEGADA, antes da fila do número: o "assina" que vem logo depois já acha o PDF."""
    agora = monotonic()
    for velho in [t for t, ps in _RECEBIDOS.items() if not ps or agora - ps[-1]["em"] >= VALIDADE_S]:
        del _RECEBIDOS[velho]
    _RECEBIDOS[telefone] = [*recebidos(telefone), {"id": evento.get("id"), "nome": _nome(evento), "em": agora}][-TETO:]


def sem_legenda(evento: dict) -> bool:
    return not str((evento.get("midia") or {}).get("legenda") or "").strip()


def mensagem(evento: dict) -> str:
    """O que a IA lê no lugar do PDF (ela não o lê), com a legenda ("assina") quando veio junto."""
    legenda = str((evento.get("midia") or {}).get("legenda") or "").strip()
    return f"[📄 PDF recebido: «{_nome(evento)}»]" + (f" {legenda}" if legenda else "")


_MARCA = re.compile(r"\[📄 PDF recebido: «([^»]+)»\]")


def do_pedido(ctx) -> Counter:
    """Os PDFs do pedido de agora (nome → quantos) — ou, se ele não tem nenhum, os do pedido anterior da pessoa (o PDF
    sozinho, o bot perguntou "é para assinar?", ela disse "assina")."""
    nomes = Counter(_MARCA.findall(ctx.pedido or ""))
    if nomes:
        return nomes
    bloco: list[str] = []
    for m in reversed(ctx.historico or []):
        if m.get("role") == "user":
            bloco.append(str(m.get("content") or ""))
        elif bloco:
            break
    return Counter(_MARCA.findall("\n".join(bloco)))


def _os_mais_novos(pdfs: list[dict], quantos: Counter) -> list[dict]:
    """De cada nome, os N recebidos por último: a versão corrigida com o mesmo nome não leva junto a antiga."""
    resta, escolhidos = Counter(quantos), []
    for p in reversed(pdfs):
        if resta[p["nome"]] > 0:
            escolhidos.append(p)
            resta[p["nome"]] -= 1
    return escolhidos[::-1]


def _tirar(telefone: str, mensagem_id: Any) -> None:
    _RECEBIDOS[telefone] = [p for p in _RECEBIDOS.get(telefone, []) if p["id"] != mensagem_id]


FERRAMENTA = {"type": "function", "function": {
    "name": "assinar_pdf",
    "description": ("Assina com o CERTIFICADO DIGITAL da pessoa (o que ela cadastrou no meuPlano) o PDF que ela mandou "
                    "ou encaminhou por aqui — a mensagem dela aparece como «[📄 PDF recebido: «nome»]» — e devolve o PDF "
                    "assinado neste chat. Use quando ela pedir para assinar o PDF que mandou (\"assina\", \"assina pra "
                    "mim\", \"pode assinar\"). O sistema pede o PIN de assinatura dela e assina quando ela o mandar. Sem "
                    "`arquivo` nem `todos`, assina o(s) PDF(s) deste pedido; com `arquivo`, só o daquele nome; com "
                    "`todos`, todos os que ela mandou e ainda não foram assinados. Só para o PDF que ELA mandou aqui: "
                    "documento gerado pelo meuPlano (OS, tarefa, relatório) tem as ferramentas dele."),
    "parameters": {"type": "object", "properties": {
        "arquivo": {"type": "string", "description": "parte do nome do PDF, quando ela pediu um que mandou antes"},
        "todos": {"type": "boolean", "description": "true só quando ela pediu para assinar TODOS os PDFs que mandou"}}}}}


async def assinar_pdf(ctx, a: dict) -> dict:
    pdfs = recebidos(ctx.telefone)
    if not pdfs:
        return {"erro": "Não há PDF recebido para assinar (cada um fica guardado 30 min). Peça que a pessoa mande ou "
                        "encaminhe o PDF de novo."}
    if qual := str(a.get("arquivo") or "").strip().lower():
        escolhidos = [p for p in pdfs if qual in p["nome"].lower()]
        if not escolhidos:
            return {"erro": f"Nenhum PDF recebido tem «{a['arquivo']}» no nome. Os recebidos: "
                            + ", ".join(f"«{p['nome']}»" for p in pdfs)}
        pdfs = _os_mais_novos(escolhidos, Counter({p["nome"]: 1 for p in escolhidos}))
    elif not a.get("todos"):
        # o "assina" vale para o PDF que veio com ele, não para o mandado antes para outra coisa (revisão de 11/11/2026)
        pdfs = _os_mais_novos(pdfs, do_pedido(ctx))
        if not pdfs:
            return {"erro": "Não sei qual PDF assinar: pergunte qual (pelo nome) ou se são todos os que ela mandou. "
                            "Os recebidos: " + ", ".join(f"«{p['nome']}»" for p in recebidos(ctx.telefone))}
    return await pedir_pin(ctx, pdfs)


async def pedir_pin(ctx, pdfs: list[dict]) -> dict:
    """A porta ÚNICA de assinar pelo WhatsApp: o PDF encaminhado (`assinar_pdf`) e o documento do meuPlano pedido
    assinado (`assistente._assinatura_com_pin`). Confere o certificado e o PIN no meuPlano e deixa a espera armada."""
    from app.services.vinculos import SemConexao, cliente_meuplano
    if ctx.proposta is not None:
        return {"erro": "Uma ação por vez: já há uma esperando a confirmação da pessoa nesta mensagem. Fale só dela."}
    try:
        mp = cliente_meuplano(ctx.db, ctx.user.id, so_proprio=True)
    except SemConexao as e:
        return {"erro": f"Manutenção indisponível: {e}"}
    ctx.db.commit()                                       # solta a conexão enquanto o meuPlano responde
    try:
        cert = await mp.meu_certificado()
    except httpx.HTTPError:
        return {"erro": "Não consegui conferir no meuPlano se a pessoa tem certificado digital. Nada foi assinado."}
    if not cert.get("configurado"):
        return {"erro": "A pessoa não tem certificado digital cadastrado no meuPlano: ela sobe o arquivo .pfx (com a "
                        "senha) em Minha conta, no site do meuPlano, e depois pede de novo. Nada foi assinado."}
    if not cert.get("pin_configurado"):
        return {"erro": "A pessoa ainda não criou o PIN de assinatura: ela cria em Minha conta → Certificado digital, no "
                        "site do meuPlano (pede a senha do certificado), e depois pede de novo. Nada foi assinado."}
    if ctx.proposta is not None or esperando(ctx.user.id):
        # outra ferramenta desta mesma mensagem armou algo enquanto o meuPlano respondia (elas rodam juntas)
        return {"erro": "Uma ação por vez: já há uma esperando a confirmação da pessoa nesta mensagem. Fale só dela "
                        "(para assinar vários PDFs de uma vez, use `todos`)."}
    nomes = ", ".join(f"«{p['nome']}»" for p in pdfs)
    resumo = f"Assinar com o seu certificado digital {'o PDF' if len(pdfs) == 1 else f'{len(pdfs)} PDFs'}: {nomes}"
    helper.desarmar(ctx.user.id, "[assinar PDF]")          # uma ação por vez: a que esperava o Sim ou a senha sai
    _ESPERANDO[ctx.user.id] = Espera(pdfs, monotonic() + PRAZO_S, resumo)
    _ZONA_ATE[ctx.user.id] = monotonic() + PRAZO_S + JANELA_S
    limite = hora_brt((datetime.now(UTC) + timedelta(seconds=PRAZO_S)).isoformat())
    # o texto que a pessoa lê é do SISTEMA, não da IA
    ctx.rodape.append(f"✍️ {resumo}\n🔐 Para assinar, mande o seu PIN de assinatura (6 números), numa mensagem só "
                      f"dele, até as {limite}. Qualquer outra mensagem cancela.")
    return {"pin_pedido": resumo,
            "instrucao": ("NADA foi assinado ainda. O SISTEMA acrescenta ao fim da sua resposta o resumo e o pedido do "
                          "PIN de assinatura: escreva no máximo uma linha, não repita o resumo, não peça o PIN nem "
                          "senha e nunca diga que assinou.")}


def esperando(user_id: int) -> bool:
    """Há uma assinatura esperando o PIN, e ainda no prazo."""
    e = _ESPERANDO.get(user_id)
    return e is not None and monotonic() <= e.expira


def interessa(user_id: int) -> bool:
    """A mensagem está na zona do PIN e passa por `receber_pin`."""
    return monotonic() < _ZONA_ATE.get(user_id, 0)


def _encerrar(user_id: int) -> None:
    """A espera acaba; a zona do PIN vai até `JANELA_S` depois (o PIN que chega atrasado ainda some)."""
    _ESPERANDO.pop(user_id, None)
    _ZONA_ATE[user_id] = monotonic() + JANELA_S


def cancelar(user_id: int) -> None:
    _encerrar(user_id)


def lembrar_cancelada(user_id: int) -> None:
    _AVISAR.add(user_id)


def tirar_aviso(user_id: int) -> bool:
    if user_id in _AVISAR:
        _AVISAR.discard(user_id)
        return True
    return False


def pedido_saiu(user_id: int, saiu: bool, agora) -> None:
    """A resposta com o pedido do PIN saiu (`agora()`: a hora do banco) — ou não saiu, e nada fica esperando."""
    espera = _ESPERANDO.get(user_id)
    if espera is None or espera.mostrada_em is not None:
        return
    if saiu:
        espera.mostrada_em = (monotonic(), agora())
    else:
        _ESPERANDO.pop(user_id, None)


def _sem_o_pin(texto: str) -> str | None:
    """A frase com todo número de 6 dígitos que pode ser o PIN ("meu pin é 482913", "4️⃣8️⃣2️⃣9️⃣1️⃣3️⃣", "482 913")
    trocado pelo marcador neutro do bot — `None` se não há nenhum. O marcador não fala em PIN nem assinatura: na frase,
    faria dela um pedido de assinatura. A UC e o protocolo (7 ou mais dígitos) seguem."""
    marcas = [m.span() for m in _MARCA.finditer(texto or "")]   # o nome do PDF ("NF 482917.pdf") não é o PIN
    trechos = [(a, b, helper.OCULTO) for a, b, d in helper.candidatos_a_senha(texto or "")
               if len(d) == 6 and not any(i <= a and b <= f for i, f in marcas)]
    return helper.mascarar(texto, helper.Analise(trechos=trechos)) if trechos else None


def sem_o_pin(user_id: int, texto: str) -> str:
    """O texto que só existe DEPOIS do gancho (a legenda do PDF ou da foto, a transcrição do áudio), com o número de
    6 dígitos escondido quando a pessoa está na zona do PIN; fora dela, como veio."""
    if not texto or not interessa(user_id):
        return texto
    pendente = helper.PENDENTES.get(user_id)
    if pendente is not None and pendente.confirmacao == "senha" and helper.digitos_da_senha(texto):
        return texto                                      # a senha de atuação dita em voz alta é da ação do helper
    return _sem_o_pin(texto) or texto


async def receber_pin(db, user, telefone: str, evento: dict, texto: str, ocultar,
                      mandada_em: datetime | None = None, ativo: bool = True) -> tuple[str, bool] | str | None:
    """A mensagem na zona do PIN:
    - `(resposta, escondida)`: tratada aqui (o PIN, ou o número que chegou atrasado);
    - `str`: a frase com o número de 6 dígitos escondido — o turno segue com ela;
    - `None`: o turno segue com a mensagem como veio.
    Uma mensagem que não é o PIN derruba a espera que valia. `ocultar()` tira a mensagem do gateway: chamado ASSIM que
    ela é reconhecida como o PIN, antes de assinar. `ativo=False`: a parte do meuPlano foi desligada no meio."""
    valendo = esperando(user.id)
    if not valendo:
        _ESPERANDO.pop(user.id, None)                     # a que venceu calada sai
    numero = helper.digitos_da_senha(texto)
    if not ativo:
        _ESPERANDO.pop(user.id, None)
        _ZONA_ATE.pop(user.id, None)                      # sem a parte, sem zona: os números seguintes são de outra coisa
        if numero and valendo:
            await ocultar()
            return "A assinatura pelo bot foi desligada enquanto esperava o seu PIN. Nada foi assinado.", True
        return _sem_o_pin(texto)
    if valendo and evento.get("tipo") in ("audio", "voice"):
        return "Mande o PIN digitado (6 números), numa mensagem só dele. Por áudio, não.", False
    if numero is None:
        if valendo:
            _encerrar(user.id)                            # a mensagem que não é o PIN derruba a espera
        return _sem_o_pin(texto)
    if not valendo:
        # o número sozinho depois da espera (venceu, já assinou, caiu): é o PIN atrasado — some e não vai à IA nem à
        # senha de atuação. Com uma ação do helper esperando a senha dela, é dela.
        pendente = helper.PENDENTES.get(user.id)
        if len(numero) == 6 and not (pendente is not None and pendente.confirmacao == "senha"):
            _ESPERANDO.pop(user.id, None)
            await ocultar()
            return ("Não há assinatura esperando o PIN agora (o pedido venceu ou já foi feito). Nada foi assinado. Se "
                    "quiser, peça de novo."), True
        return None
    espera = _ESPERANDO[user.id]
    await ocultar()
    if len(numero) != 6:
        return "O PIN de assinatura tem 6 números. Mande de novo, numa mensagem só dele.", True
    if helper._antes_do_resumo(espera, evento.get("_chegou"), mandada_em):
        return ("Esse PIN foi mandado antes de o pedido de assinatura chegar. Leia o resumo acima e, se for isso mesmo, "
                "mande o PIN de novo. Nada foi assinado."), True
    resposta, seguir = await _assinar(db, user, telefone, espera.pdfs, numero)
    if not seguir:
        _encerrar(user.id)
    return resposta, True


#: A recusa do meuPlano que vale para TODOS os PDFs do pedido (o PIN, o certificado); as outras são do arquivo.
_RECUSA_GERAL = re.compile(r"(?i)\bPIN\b|certificado")


async def _assinar(db, user, telefone: str, pdfs: list[dict], pin: str) -> tuple[str, bool]:
    """Assina cada PDF com o PIN. Devolve a resposta e se a espera continua (PIN errado com tentativas sobrando)."""
    from app.services.integracoes import detalhe_do_upstream
    from app.services.vinculos import SemConexao, cliente_meuplano
    try:
        mp = cliente_meuplano(db, user.id, so_proprio=True)
    except SemConexao as e:
        return f"❌ Não assinado: {e}", False
    db.commit()
    feitos, falhas = [], []
    for p in pdfs:
        try:
            conteudo = p["bytes"] if "bytes" in p else (await whatsapp.baixar_midia(p["id"]))[0]
            assinado, nome = await mp.assinar_pdf(conteudo, p["nome"], pin)
        except whatsapp.GatewayIndisponivel:
            falhas.append(f"«{p['nome']}»: não consegui baixar do WhatsApp (encaminhe de novo)")
            continue
        except httpx.HTTPStatusError as e:
            st = e.response.status_code
            motivo = str(detalhe_do_upstream(e.response) or st).rstrip(". ")
            if st < 500 and (st in (403, 404, 429) or _RECUSA_GERAL.search(motivo)):
                # o PIN ou o certificado: vale para todos — o que já foi assinado fica, o resto não se tenta
                de_novo = st == 400 and "restam" in motivo and not feitos
                if not feitos:
                    return (f"❌ {motivo}." + (" Mande o PIN de novo." if de_novo else " Nada foi assinado.")), de_novo
                falhas.append(f"os outros: {motivo}")
                break
            falhas.append(f"«{p['nome']}»: {motivo}")
            continue
        except httpx.HTTPError:
            falhas.append(f"«{p['nome']}»: o meuPlano não respondeu a tempo")
            continue
        try:
            r = await whatsapp.enviar_conteudo(telefone=telefone, tipo="document", arquivo=assinado,
                                               filename=nome, mime="application/pdf", texto=f"✍️ {nome}")
        except whatsapp.GatewayIndisponivel:
            r = None
        if not (r and r.get("ok")):
            falhas.append(f"«{p['nome']}»: assinei, mas o WhatsApp não entregou o arquivo (peça de novo)")
            continue
        feitos.append(nome)
        if "id" in p:
            _tirar(telefone, p["id"])
    motivos = "".join(f"\n• {m}" for m in falhas)
    if not feitos:
        return f"❌ Nenhum PDF foi assinado:{motivos}", False
    prontos = ", ".join(f"«{n}»" for n in feitos)
    if falhas:
        return f"⚠️ Assinei {len(feitos)} de {len(pdfs)} com o seu certificado (vão aqui no chat): {prontos}{motivos}", False
    return f"✅ Assinado com o seu certificado digital (vai aqui no chat): {prontos}", False
