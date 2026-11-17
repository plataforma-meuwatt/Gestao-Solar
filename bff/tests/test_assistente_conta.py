"""A conta de energia mandada pelo WhatsApp: lida, provada e gravada no meuWatt com o Sim (pedido do Renan, 17/11/2026).

As contas de verdade têm dado pessoal e ficam fora do repositório: aqui a conta é um PDF desenhado no molde da Elektro
(os rótulos e os números da tabela como textos separados na mesma altura, o "Seu código" do boleto, a linha faturada
com a injetada negativa), e a IA é falsa, com a resposta que a de verdade deu para a conta real de Tietê."""

import io
from types import SimpleNamespace

import httpx
from datetime import date

import pytest

from app.services import assistente
from app.services import assistente_conta as conta
from app.services import assistente_helper as h
from app.services import assistente_pdf as pdf
from app.services import vinculos
from tests.test_assistente_whatsapp import _conta

TEL = "+5517997001122"
UC = "3.601.916.045-43"


def _pdf_elektro(fp="64806") -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig = plt.figure(figsize=(8.27, 11.69))

        def t(x, y, s):
            fig.text(x, y, s, fontsize=7, family="DejaVu Sans")
        t(0.05, 0.97, "DANFE: DOCUMENTO AUXILIAR DA NOTA FISCAL DE ENERGIA ELETRICA ELETRONICA - Elektro Redes S.A.")
        t(0.05, 0.955, "ASSOCIACAO DE CONSUMIDORES DE ENERGIA SUSTENTAVEL ACES - R Ary Antenor de Souza, 321 - Campinas")
        t(0.40, 0.94, UC)
        t(0.05, 0.92, "Outubro/2026")
        t(0.30, 0.92, "R$8.092,71")
        t(0.55, 0.92, "26/11/2026")
        for x, txt in ((0.05, "31/08/2026"), (0.30, "30/09/2026"), (0.50, "30"), (0.70, "01/11/2026")):
            t(x, 0.90, txt)                               # na Elektro os rótulos das datas são desenho, não texto
        t(0.05, 0.88, "HORÁRIA VERDE / TRIFASICO")
        for y, cols in ((0.62, ("ENERGIA INJETADA", "22270", "25359", "21", "")),
                        (0.60, ("ENERGIA INJETADA PT", "750", "1014", ".21", "55")),
                        (0.58, ("ENERGIA INJETADA FP", "22263", "25349", "21", fp))):
            for x, s in zip((0.05, 0.40, 0.50, 0.60, 0.75), cols):
                t(x, y, s)
        t(0.05, 0.40, "ENERGIA INJETADA PT TE 10/2026 GDI-I   kWh   -55")
        t(0.05, 0.10, "109/03472840-9   FAT-01-202610666609289.93   26/11/2026   R$ 8.092,71")
        b = io.BytesIO()
        fig.savefig(b, format="pdf")
        plt.close(fig)
    return b.getvalue()


#: O que a IA de verdade devolveu para a conta real de Tietê (com a UC errada: o "Seu código" do boleto).
LIDA = {"distribuidora": "Elektro", "uc": "109/03472840-9", "titular": "ASSOCIACAO DE CONSUMIDORES DE ENERGIA",
        "referencia": "Outubro/2026", "leitura_anterior": "31/08/2026", "leitura_atual": "30/09/2026",
        "mes_da_energia": "09/2026", "modalidade": "HORÁRIA VERDE / TRIFASICO", "valor_a_pagar": "R$8.092,71",
        "vencimento": "26/11/2026", "injetada": [
            {"posto": "ponta", "rotulo": "ENERGIA INJETADA PT", "kwh": "55", "leitura_anterior": "750",
             "leitura_atual": "1014", "constante": ".21", "pagina": 1},
            {"posto": "fora ponta", "rotulo": "ENERGIA INJETADA FP", "kwh": "64806", "leitura_anterior": "22263",
             "leitura_atual": "25349", "constante": "21", "pagina": 1}]}
CONTAS = [{"id": 258, "transformer_id": 53, "year": 2026, "month": 9, "billed_mwh": 64.86, "installation_number": UC,
           "tariff": None, "titular": None, "pdf_file_id": 1, "no_bill": False},
          {"id": 259, "transformer_id": 54, "year": 2026, "month": 9, "billed_mwh": None,
           "installation_number": "3.601.919.045-10", "tariff": None, "titular": None, "pdf_file_id": None}]


def test_o_numero_e_lido_como_a_conta_imprime():
    assert conta.numero("143.500") == 143500 and conta.numero("1.400") == 1400     # milhar (CEMIG)
    assert conta.numero(".42") == 0.42 and conta.numero("1.68") == 1.68           # constantes da Elektro
    assert conta.numero("208782") == 208782 and conta.numero("18.451,80") == 18451.8
    assert conta.numero("R$ 1") is None and conta.numero("") is None


def test_o_mes_e_o_do_meio_do_periodo_de_leitura():
    # a Elektro "Outubro/2026" lê de 31/08 a 30/09: setembro, como as contas que já estão no meuWatt
    assert conta.periodo({"leitura_anterior": "31/08/2026", "leitura_atual": "30/09/2026"}) == ((2026, 9), None)
    # a que lê no dia 1º (31/08 a 01/10) também é setembro: pela leitura atual, cairia em outubro (avaliação de 17/11)
    assert conta.periodo({"leitura_anterior": "31/08/2026", "leitura_atual": "01/10/2026"}) == ((2026, 9), None)
    # a CEMIG imprime "31/08" sem o ano; a virada do ano também
    assert conta.periodo({"leitura_anterior": "31/08", "leitura_atual": "30/09/2026"}) == ((2026, 9), None)
    assert conta.periodo({"leitura_anterior": "01/12/2025", "leitura_atual": "02/01"}) == ((2025, 12), None)
    # o vencimento no lugar da leitura atual: 87 dias não é o período de uma conta
    mes, problema = conta.periodo({"leitura_anterior": "31/08/2026", "leitura_atual": "26/11/2026"})
    assert mes is None and "87 dias" in problema
    assert conta.periodo({"leitura_atual": "30/09/2026"})[0] is None


def _leitura(fp="64806", dados=None) -> conta.Leitura:
    conteudo = _pdf_elektro(fp)
    doc = conta.abrir(conteudo, [])
    return conta.Leitura("fatura.pdf", conteudo, doc, dados or LIDA)


def test_as_linhas_juntam_o_rotulo_e_os_numeros_da_tabela():
    l = _leitura()
    assert l.doc.digital
    textos = [x.texto for x in l.doc.linhas]
    # na Elektro o texto corrido solta os rótulos de um lado e os números do outro: a IA não sabia de quem era o 64806
    assert "ENERGIA INJETADA FP   22263   25349   21   64806" in textos


def test_a_uc_e_a_do_meuwatt_impressa_na_conta_e_nao_o_codigo_do_boleto():
    l = _leitura()
    slug, c = conta.achar_uc({"tiete": CONTAS}, l.doc, l.dados["uc"])
    assert (slug, c["transformer_id"], c["installation_number"]) == ("tiete", 53, UC)
    # sem a UC no meuWatt, nada casa (a IA sozinha não decide a UC de uma conta digital)
    assert conta.achar_uc({"tiete": CONTAS[1:]}, l.doc, l.dados["uc"]) is None


def _conferida(fp="64806", dados=None) -> conta.Leitura:
    l = _leitura(fp, dados)
    l.usina, (_, c) = {"slug": "tiete", "nome": "Tietê", "id": 9377}, conta.achar_uc({"tiete": CONTAS}, l.doc, UC)
    l.uc, l.trafo = c["installation_number"], {"id": c["transformer_id"], "nome": "TR-01"}
    conta.conferir(l, CONTAS, {53: "TR-01"})
    return l


def test_conferir_soma_a_injetada_medida_e_confere_o_medidor():
    l = _conferida()
    # 55 + 64806 kWh, nunca a linha faturada de -55; o mesmo número que está no meuWatt (64,86)
    assert (l.total_kwh, l.mwh, l.mes, l.avisos, l.notas) == (64861, 64.861, (2026, 9), [], [])
    assert [p["medidor"] for p in l.postos] == [True, True]                       # (1014-750)×0,21 ≈ 55
    assert l.pronta and l.atual["id"] == 258
    png = conta.prova(l)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_numero_que_nao_esta_na_linha_do_rotulo_nao_deixa_salvar():
    dados = {**LIDA, "injetada": [{**LIDA["injetada"][1], "kwh": "64860"}]}     # a IA errou um dígito
    l = _conferida(dados=dados)
    assert not l.pronta and any("64860" in a for a in l.avisos)


def test_conta_digitalizada_e_lida_pela_imagem_e_o_medidor_decide():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (620, 877), "white").save(b, "PDF")                         # só imagem, como a REIMPRESSÃO da CEMIG
    doc = conta.abrir(b.getvalue(), [])
    assert not doc.digital
    errada = {**LIDA, "uc": UC, "injetada": [{**LIDA["injetada"][1], "kwh": "64000"}]}  # o medidor dá 64806
    l = conta.Leitura("scan.pdf", b.getvalue(), doc, errada)
    l.usina, l.uc, l.trafo = {"slug": "tiete", "nome": "Tietê"}, UC, {"id": 53, "nome": "TR-01"}
    conta.conferir(l, CONTAS, {53: "TR-01"})
    assert not l.pronta and any("medidor" in a for a in l.avisos)                 # sem texto, a conta do medidor barra
    assert conta.prova(l)[:4] == b"\x89PNG"


# --------------------------------------------------------------------------- a ferramenta, de ponta a ponta
class _MeuWatt:
    def __init__(self, papel="admin"):
        self.papel, self.salvas, self.emitido, self.falha = papel, [], None, None
        self.contas = {"tiete": [dict(c) for c in CONTAS], "pereiras": []}

    async def contas_de_energia(self, slug, ano=None):
        return [dict(c) for c in self.contas.get(slug, [])]

    async def usina(self, slug):
        return {"transformers": [{"id": 53, "name": "TR-01"}, {"id": 54, "name": "TR-02"}, {"id": 55, "name": "TR-03"}]}

    async def quem_sou_eu(self):
        return {"is_platform_admin": self.papel == "admin",
                "plant_roles": [{"plant_id": 9377, "slug": "tiete", "role": self.papel}]}

    async def salvar_conta(self, slug, corpo):
        """Como o upsert de lá: UC × mês, troca os campos; o PDF vira a versão 2."""
        if self.falha:
            raise self.falha
        self.salvas.append((slug, corpo))
        c = next((c for c in self.contas[slug] if (c["transformer_id"], c["year"], c["month"])
                  == (corpo["transformer_id"], corpo["year"], corpo["month"])), None)
        if c is None:
            c = {"id": 999, "transformer_id": corpo["transformer_id"], "year": corpo["year"], "month": corpo["month"]}
            self.contas[slug].append(c)
        c.update(billed_mwh=corpo["billed_mwh"], pdf_file_id=2)
        return dict(c)

    async def ssu_totais_mensais(self, slug, ano):
        return {}

    async def balanco_energia(self, slug, ini, fim, fabricante=True):
        """O balanço do meuWatt no mês: o medidor do TR-01 × a conta que está lá AGORA (a prova relê depois de gravar)."""
        self.balanco = (slug, ini, fim, fabricante)
        conta = next((c.get("billed_mwh") for c in self.contas.get(slug, []) if c["transformer_id"] == 53
                      and (c["year"], c["month"]) == (ini.year, ini.month)), None)
        return {"skids": [{"skid": "TR-01", "medidor_kwh": 64850.0, "conta_kwh": None if conta is None else conta * 1000,
                           "medidor_menos_conta_pct": -0.02, "conciliacao": "Conciliado", "falta_dado": None}]}

    async def relatorio_existente(self, slug, periodo, de):
        return self.emitido


@pytest.fixture
def conta_no_bot(db, monkeypatch):
    p = _conta(db, "renan", TEL)
    mw = _MeuWatt()
    enviados = []

    async def baixar(mensagem_id):
        return _pdf_elektro(), "application/pdf"

    async def enviar(**k):
        enviados.append(k)
        return {"ok": True}

    async def llm(mensagens, ferramentas, obrigatoria=False, nenhuma=False, teto_s=None):
        import json
        assert teto_s and "ENERGIA INJETADA FP   22263" in mensagens[0]["content"]  # a IA lê as linhas remontadas
        return {"content": "```json\n" + json.dumps(LIDA) + "\n```"}

    monkeypatch.setattr(conta.whatsapp, "baixar_midia", baixar)
    monkeypatch.setattr(conta.whatsapp, "enviar_conteudo", enviar)
    monkeypatch.setattr(assistente, "_llm", llm)
    monkeypatch.setattr(vinculos, "cliente_meuwatt", lambda *_a, **_k: mw)
    pdf._RECEBIDOS.pop(TEL, None)
    pdf.guardar(TEL, {"id": 11, "tipo": "document", "midia": {"nome": "fatura.pdf", "mime": "application/pdf"}})
    h.PENDENTES.pop(p.id, None)
    usinas = {"tiete": {"nome": "Tietê", "slug": "tiete", "id": 9377},
              "pereiras": {"nome": "Pereiras", "slug": "pereiras", "id": 9373}}
    ctx = SimpleNamespace(telefone=TEL, db=db, user=p, proposta=None, mw=mw, usinas=usinas, mw_falha=None, segredos=[],
                          enviados=[], ferramentas=[], historico=[],
                          pedido="[📄 PDF recebido: «fatura.pdf»] conta de energia de Tietê, lança no meuWatt")
    yield SimpleNamespace(p=p, mw=mw, enviados=enviados, ctx=ctx)
    h.PENDENTES.pop(p.id, None)
    pdf._RECEBIDOS.pop(TEL, None)


async def test_a_ferramenta_manda_a_prova_e_o_sim_grava_e_diz_o_relatorio(db, conta_no_bot):
    t = conta_no_bot
    r = await conta.conta_de_energia(t.ctx, {"usina": "Tietê"})
    assert r["prova_enviada_no_chat"] and t.enviados[0]["tipo"] == "image"        # a prova ANTES do Sim
    assert r["contas"][0]["energia_injetada_mwh"] == 64.861 and r["contas"][0]["uc"] == UC
    pendente = h.PENDENTES[t.p.id]
    assert pendente.confirmacao == "sim" and "Tietê" in pendente.resumo
    assert any("TR-01 · UC 3.601.916.045-43 · set/2026: 64,861 MWh (hoje: 64,860)" in d for d in pendente.detalhes)
    assert t.mw.salvas == []                                                       # nada antes do Sim
    texto = await pendente.executar(db, t.p, TEL)
    slug, corpo = t.mw.salvas[0]
    # o upsert de lá troca TODOS os campos: vai o que a conta já tinha; titular e tarifa nunca vêm da IA (ninguém os
    # conferiu, e não estavam no resumo que a pessoa confirmou)
    assert (slug, corpo["transformer_id"], corpo["year"], corpo["month"], corpo["billed_mwh"]) == ("tiete", 53, 2026, 9,
                                                                                                    64.861)
    assert (corpo["installation_number"], corpo["tariff"], corpo["titular"]) == (UC, None, None)
    assert corpo["pdf_filename"] == "fatura.pdf" and corpo["pdf_base64"] and "pdf_password" not in corpo
    assert "64,860 → 64,861 MWh (PDF anexado como nova versão)" in texto
    # a prova de que gravou certo (o dono: "quando eu enviar quero que ele me prove que ele fez certo"): relida do
    # meuWatt e o medidor × a conta da UC no mês, pelo balanço do meuWatt (sem a Huawei, que só atrasaria)
    assert "🔎 Prova, relendo do meuWatt:" in texto and "✅ TR-01 · set/2026: o meuWatt tem 64,861 MWh" in texto
    assert "⚖️ TR-01 · set/2026: medidor 64,850 × conta 64,861 MWh (-0,02%): Conciliado" in texto
    assert t.mw.balanco[1:] == (date(2026, 9, 1), date(2026, 9, 30), False)
    # o relatório lê as contas do meuWatt: a resposta diz o que ele mostra agora, e que faltam as outras UCs
    assert "conta de energia 64,9 MWh (1 de 3 UCs; falta TR-02, TR-03)" in texto
    assert "sem medição na fronteira" in texto


async def test_quem_nao_administra_a_usina_ve_a_prova_mas_nao_salva(db, conta_no_bot):
    t = conta_no_bot
    t.mw.papel = "plant_owner"                                                     # lá o dono só manda o PDF
    r = await conta.conta_de_energia(t.ctx, {"usina": "Tietê"})
    assert r["prova_enviada_no_chat"] and "administrador da usina" in r["instrucao"]
    assert t.p.id not in h.PENDENTES


async def test_a_uc_de_outra_usina_diz_de_qual_e(db, conta_no_bot):
    t = conta_no_bot
    r = await conta.conta_de_energia(t.ctx, {"usina": "Pereiras"})
    assert t.p.id not in h.PENDENTES
    assert any("é de Tietê, não de Pereiras" in a for a in r["contas"][0]["avisos"])


async def test_sem_pdf_recebido_pede_para_mandar(db, conta_no_bot):
    pdf._RECEBIDOS.pop(TEL, None)
    r = await conta.conta_de_energia(conta_no_bot.ctx, {"usina": "Tietê"})
    assert "Não há PDF recebido para ler" in r["erro"]


async def test_a_conta_nova_do_mes_vai_com_o_pdf_e_a_uc(db, conta_no_bot):
    t = conta_no_bot
    t.mw.contas["tiete"] = [c for c in t.mw.contas["tiete"] if c["id"] != 258] + [
        {**CONTAS[0], "id": 200, "month": 8}]                                        # setembro ainda sem conta
    await conta.conta_de_energia(t.ctx, {"usina": "Tietê"})
    await h.PENDENTES[t.p.id].executar(db, t.p, TEL)
    slug, corpo = t.mw.salvas[0]
    assert (slug, corpo["transformer_id"], corpo["year"], corpo["month"], corpo["billed_mwh"],
            corpo["installation_number"], corpo["pdf_filename"]) == ("tiete", 53, 2026, 9, 64.861, UC, "fatura.pdf")
    assert corpo["pdf_base64"] and "pdf_password" not in corpo


def test_quebrar_nunca_corta_o_texto():
    from PIL import Image, ImageDraw
    g = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    f = conta._fonte(20)
    longo = "NEOENERGIA ELEKTRO - FATURA (45824614) (UC 362286704546) senha_sem_espacos_muito_grande_mesmo.pdf"
    linhas = conta._quebrar(g, longo, f, 300)
    assert "".join(linhas).replace(" ", "") == longo.replace(" ", "")              # nada some
    assert all(g.textlength(x, font=f) <= 300 for x in linhas)


def test_a_rota_de_gravar_a_conta_esta_no_catalogo_e_nao_e_sondada():
    from app.services import sonda
    rotas = {r.chave: r for r in sonda.MEUWATT}
    assert rotas["mw.bill_salvar"].sonda is False
    # a trava de 30/09 continua: o PDF e a senha da fatura não têm rota no cliente (o salvar leva o PDF em base64)
    assert not {"mw.bill_pdf", "mw.bill_senha"} & set(rotas)


def test_gravar_conta_e_so_do_gestor(db):
    """O dono, 17/11/2026: "jamais o cliente pode enviar algo, eu gestor sim"."""
    from app.models.user import Perfil
    p = _conta(db, "ana", "+5517997001133")
    assert "conta_de_energia" not in assistente.permitidas(p)                  # dono de usina: não manda conta
    p.perfil = Perfil.GESTOR_EMPRESA
    assert "conta_de_energia" in assistente.permitidas(p)
    p.bot_meuwatt = False
    assert "conta_de_energia" not in assistente.permitidas(p)


async def test_erro_do_meuwatt_ao_listar_vira_frase(db, conta_no_bot):
    async def falha(slug, ano=None):
        req = httpx.Request("GET", "http://mw")
        raise httpx.HTTPStatusError("403", request=req, response=httpx.Response(403, request=req))
    conta_no_bot.mw.contas_de_energia = falha
    r = await conta.conta_de_energia(conta_no_bot.ctx, {"usina": "Tietê"})
    assert "403" in r["erro"]


def test_data_da_leitura_que_nao_esta_impressa_nao_deixa_salvar():
    # é o período que diz em que mês a conta entra: as duas datas têm de estar impressas
    l = _conferida(dados={**LIDA, "leitura_anterior": "30/08/2026"})
    assert l.mes == (2026, 9) and not l.pronta and any("30/08/2026" in a for a in l.avisos)


def test_a_coluna_errada_na_linha_certa_nao_salva():
    # o 21 está impresso na linha da injetada FP (é a constante): só a leitura do medidor desmente (o "Faturado" da CEMIG)
    l = _conferida(dados={**LIDA, "injetada": [LIDA["injetada"][0], {**LIDA["injetada"][1], "kwh": "21"}]})
    assert not l.pronta and any("medidor não dá 21" in a for a in l.avisos)


def test_sem_a_leitura_do_medidor_nao_salva():
    sem = {k: v for k, v in LIDA["injetada"][1].items() if k not in ("leitura_anterior", "leitura_atual", "constante")}
    l = _conferida(dados={**LIDA, "injetada": [LIDA["injetada"][0], sem]})
    assert not l.pronta and any("leitura do medidor" in a for a in l.avisos)


def test_posto_repetido_nao_dobra_a_soma():
    fp = LIDA["injetada"][1]
    l = _conferida(dados={**LIDA, "injetada": [fp, {**fp, "posto": "único"}]})
    assert not l.pronta and any("repete" in a for a in l.avisos)


def test_rotulo_vazio_nao_aceita_numero_fora_da_linha_de_injetada():
    # sem rótulo, a linha ainda tem de ser de energia injetada; e a leitura 1014 não fecha com o medidor
    l = _conferida(dados={**LIDA, "injetada": [{**LIDA["injetada"][0], "rotulo": "", "kwh": "1014"}]})
    assert not l.pronta


async def test_duas_contas_da_mesma_uc_e_mes_nao_salvam(db, conta_no_bot):
    t = conta_no_bot
    pdf.guardar(TEL, {"id": 12, "tipo": "document", "midia": {"nome": "fatura (1).pdf", "mime": "application/pdf"}})
    r = await conta.conta_de_energia(t.ctx, {"usina": "Tietê", "todos": True})
    assert "mesma UC" in r["instrucao"] and t.p.id not in h.PENDENTES


def test_salva_confirma_a_acao_de_salvar():
    resumo = "Salvar no meuWatt a conta de energia de Tietê (set/2026), com o PDF"
    assert all(h.e_sim(t, resumo) for t in ("Salva", "Sim, salva", "Pode salvar", "salve"))   # "Salva" cancelava
    assert not h.e_sim("Salva?", resumo) and not h.e_sim("Pode apagar", resumo)


async def test_relatorio_ja_emitido_diz_que_o_pdf_fica_com_o_valor_antigo(db, conta_no_bot):
    t = conta_no_bot
    t.mw.emitido = {"id": 53, "files": []}
    await conta.conta_de_energia(t.ctx, {"usina": "Tietê"})
    pendente = h.PENDENTES[t.p.id]
    assert any("set/2026 já foi emitido" in a for a in pendente.avisos)
    texto = await pendente.executar(db, t.p, TEL)
    assert "já tinha sido emitido" in texto


async def test_meuwatt_sem_resposta_diz_que_pode_ter_salvo(db, conta_no_bot):
    t = conta_no_bot
    await conta.conta_de_energia(t.ctx, {"usina": "Tietê"})
    t.mw.falha = httpx.ReadTimeout("lento")
    texto = await h.PENDENTES[t.p.id].executar(db, t.p, TEL)
    assert "PODE ter sido salva" in texto and "Nada foi salvo" not in texto


def _pdf_cemig() -> bytes:
    """O molde do demonstrativo da CEMIG: as leituras "kWh" (energia ATIVA) e "kWh Injet." por segmento, a injetada
    "Registrado" com o "Faturado" na mesma linha, e a constante no quadro de constantes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig = plt.figure(figsize=(8.27, 11.69))
        linhas = [(0.95, ("CEMIG DISTRIBUIÇÃO S.A. - DEMONSTRATIVO DE GRANDEZAS FATURADAS - CONSORCIO DE GERACAO MG",)),
                  (0.93, ("N.º da Unidade Consumidora:", "12.050.453.018-97", "Período de Medição", "01/09/2026", "à",
                          "30/09/2026")),
                  (0.80, ("kWh", "8", "11", "1", "1", "0", "0")),
                  (0.78, ("kWh Injet.", "850", "1.055", "2", "4", "0", "0")),
                  (0.60, ("HFP/Único", "Energia Injetada", "143.500", "2.100")),
                  (0.58, ("HP", "Energia Injetada", "1.400")),
                  (0.40, ("kWh", "700")),
                  (0.20, ("Observações da distribuidora sobre o sistema de compensação de energia elétrica da unidade",))]
        for y, cols in linhas:
            for n, txt in enumerate(cols):
                fig.text(0.05 + n * 0.13, y, txt, fontsize=7, family="DejaVu Sans")
        b = io.BytesIO()
        fig.savefig(b, format="pdf")
        plt.close(fig)
    return b.getvalue()


CEMIG = {"distribuidora": "CEMIG", "uc": "12.050.453.018-97", "leitura_anterior": "01/09/2026",
         "leitura_atual": "30/09/2026", "injetada": [
             {"posto": "HFP/único", "rotulo": "Energia Injetada", "kwh": "143.500", "leitura_anterior": "850",
              "leitura_atual": "1.055", "constante": "700", "pagina": 1},
             {"posto": "HP", "rotulo": "Energia Injetada", "kwh": "1.400", "leitura_anterior": "2", "leitura_atual": "4",
              "constante": "700", "pagina": 1}]}
CONTAS_OF = [{"id": 250, "transformer_id": 44, "year": 2026, "month": 9, "billed_mwh": 143.5,
              "installation_number": "12.050.453.018-97", "tariff": None, "titular": None, "pdf_file_id": 1}]


def _cemig(dados) -> conta.Leitura:
    conteudo = _pdf_cemig()
    l = conta.Leitura("cemig.pdf", conteudo, conta.abrir(conteudo, []), dados)
    l.usina, l.uc, l.trafo = {"slug": "of", "nome": "Ouro Fino"}, "12.050.453.018-97", {"id": 44, "nome": "TR-02"}
    conta.conferir(l, CONTAS_OF, {44: "TR-02"})
    return l


def test_cemig_soma_hfp_e_hp_pelas_leituras_de_injetada():
    l = _cemig(CEMIG)
    assert l.doc.digital and l.pronta and l.mwh == 144.9 and l.mes == (2026, 9)   # o meuWatt tem 143,5 (sem o HP)


def test_o_faturado_com_as_leituras_da_energia_ativa_nao_salva():
    # (11 − 8) × 700 = 2.100 fecha com o "Faturado" impresso na linha da injetada: só que essas leituras são da ATIVA
    ataque = {**CEMIG, "injetada": [{**CEMIG["injetada"][0], "kwh": "2.100", "leitura_anterior": "8",
                                     "leitura_atual": "11"}, CEMIG["injetada"][1]]}
    l = _cemig(ataque)
    assert not l.pronta and any("lado a lado numa linha de energia injetada" in a for a in l.avisos)


def test_o_hp_esquecido_nao_passa():
    l = _cemig({**CEMIG, "injetada": CEMIG["injetada"][:1]})                        # 143,5: o erro que está no meuWatt
    assert not l.pronta and any("2 → 4" in a for a in l.avisos)


def test_as_datas_deslocadas_da_elektro_nao_passam():
    # "31/08/2026 30/09/2026 30 01/11/2026": o par deslocado também tem 32 dias, mas não está lado a lado
    l = _conferida(dados={**LIDA, "leitura_anterior": "30/09/2026", "leitura_atual": "01/11/2026"})
    assert not l.pronta and any("lado a lado" in a for a in l.avisos)


def test_o_registro_total_da_elektro_pega_o_posto_esquecido():
    assert _conferida().pronta                                                     # (25359 − 22270) × 21 ≈ 55 + 64806
    l = _conferida(dados={**LIDA, "injetada": LIDA["injetada"][1:]})               # sem a ponta
    assert not l.pronta and any("registro total" in a for a in l.avisos)


def test_duas_contas_pedem_as_duas_e_um_alvo_so_pergunta_de_novo():
    resumo = "Salvar no meuWatt 2 conta(s) de energia de Tietê (set/2026), com o PDF"
    itens = ["TR-01 · UC 3.601.916.045-43 · set/2026: 64,861 MWh (hoje: 64,860)",
             "TR-02 · UC 3.601.919.045-10 · set/2026: 134,650 MWh (nova)"]
    assert h.e_sim("Salva as duas", resumo, itens) and h.e_sim("Sim", resumo, itens)
    assert not h.e_sim("Salva o TR-01", resumo, itens)                            # gravava as duas


async def test_mudanca_grande_no_valor_ganha_aviso(db, conta_no_bot):
    t = conta_no_bot
    t.mw.contas["tiete"][0]["billed_mwh"] = 30.0
    await conta.conta_de_energia(t.ctx, {"usina": "Tietê"})
    assert any("muda 116%" in a for a in h.PENDENTES[t.p.id].avisos)


def test_o_mes_da_energia_e_o_da_referencia_ou_o_anterior():
    assert conta._referencia("Outubro/2026") == (2026, 10) and conta._referencia("SET/2026") == (2026, 9)
    assert _conferida().pronta                                                     # "Outubro/2026", energia de setembro
    # a conta digitalizada com as datas deslizadas para a próxima leitura (novembro numa conta de outubro) não passa
    l = _conferida(dados={**LIDA, "referencia": "Agosto/2026"})
    assert not l.pronta and any("referência" in a for a in l.avisos)
