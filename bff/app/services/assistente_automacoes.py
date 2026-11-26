"""As ferramentas do bot para as AUTOMAÇÕES e a MEMÓRIA (Plano Assistente GS, 26/11/2026).

O dono: "a ideia é o usuário conseguir usar o bot como assistente para as usinas, onde o bot vai ter memória e
instruções (...) lembrar das coisas, criar lembrete". Criar é uma frase: a IA passa só o que a pessoa disse, o sistema
acha a usina e o equipamento (lendo o meuWatt com o token DELA), escolhe os padrões e propõe em uma linha, com o Sim.
Falta um dado essencial: uma pergunta, com as opções. Datas e horas: a IA passa as palavras (dia, hora, daqui a N
minutos) e quem conta é o servidor (regra da casa: conta de prazo nunca é do modelo).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

import httpx

from app.core.datas import BRT, agora
from app.models.automacao import Automacao
from app.services import automacoes as auto
from app.services import assistente_geracao as ger
from app.services import memoria as mem
from app.services.assistente_geracao import Recusa

_DIAS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6}


def _f(nome: str, descricao: str, props: dict, obrigatorios: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": nome, "description": descricao, "parameters": {
        "type": "object", "properties": props, **({"required": obrigatorios} if obrigatorios else {})}}}


# ── datas e horas, pelo servidor ────────────────────────────────────────────


def _hora(texto: Any) -> dtime | None:
    s = str(texto or "").strip().lower().replace("h", ":").rstrip(":")
    if s in ("meio-dia", "meio dia", "meiodia"):
        return dtime(12, 0)
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", s)
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        return None
    return dtime(int(m.group(1)), int(m.group(2) or 0))


def _dia(texto: Any, hoje: date) -> date:
    s = re.sub(r"[\s-]+", "_", str(texto or "hoje").strip().lower()).replace("ã", "a").replace("á", "a")
    if s in ("", "hoje"):
        return hoje
    if s == "amanha":
        return hoje + timedelta(days=1)
    if s in ("depois_de_amanha",):
        return hoje + timedelta(days=2)
    if s[:3] in _DIAS:
        alvo = _DIAS[s[:3]]
        return hoje + timedelta(days=(alvo - hoje.weekday()) % 7 or 7)
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise Recusa("Não entendi o dia: pergunte (hoje, amanhã, um dia da semana ou a data).") from None


def quando_do_lembrete(a: dict, agora_brt: datetime | None = None) -> datetime:
    """O instante do lembrete, em Brasília, contado pelo servidor."""
    agora_brt = agora_brt or agora()
    if a.get("daqui_a_min"):
        try:
            return agora_brt + timedelta(minutes=int(a["daqui_a_min"]))
        except (TypeError, ValueError):
            raise Recusa("Não entendi daqui a quanto tempo: pergunte.") from None
    hora = _hora(a.get("hora"))
    if hora is None:
        raise Recusa("A que horas? Pergunte (ex.: 12:00).")
    quando = datetime.combine(_dia(a.get("dia"), agora_brt.date()), hora, tzinfo=BRT)
    if quando <= agora_brt:
        raise Recusa(f"{quando:%d/%m às %H:%M} já passou: pergunte se é amanhã ou outro dia.")
    return quando


def _dias_da_semana(lista: Any) -> list[int] | None:
    if not lista or "todos" in lista:
        return None
    if "uteis" in lista:
        return [0, 1, 2, 3, 4]
    ds = sorted({_DIAS[d[:3]] for d in lista if str(d)[:3] in _DIAS})
    return ds or None


# ── usinas e equipamentos ───────────────────────────────────────────────────


def _links(ctx, com_monitoramento: bool = False) -> list:
    return [u for u in ger.usinas_do_bot(ctx.db, ctx.user) if u.mw_plant_slug or not com_monitoramento]


def _uma_usina(links: list, nome: str | None):
    escolhida = ger.escolher_usina([{"nome": u.nome, "slug": str(u.id), "id": u.id} for u in links], nome)
    return next(u for u in links if u.id == escolhida["id"])


def _escopo(ctx, a: dict, com_monitoramento: bool) -> tuple[dict, str, list]:
    """(o escopo, como ele se diz, as usinas). Sem usina dita: todas as dela (a nova entra sozinha)."""
    links = _links(ctx, com_monitoramento)
    if not links:
        raise Recusa("Não há usina " + ("com monitoramento " if com_monitoramento else "")
                     + "liberada para você no Gestão Solar.")
    if a.get("usinas"):
        escolhidas = {u.id: u for u in (_uma_usina(links, n) for n in a["usinas"])}
        nomes = ", ".join(u.nome for u in escolhidas.values())
        return {"usinas": list(escolhidas)}, nomes, list(escolhidas.values())
    menos = {u.id: u for u in (_uma_usina(links, n) for n in a.get("menos") or [])}
    resto = [u for u in links if u.id not in menos]
    if not resto:
        raise Recusa("Tirando essas, não sobra nenhuma usina: pergunte quais.")
    dito = (f"todas as suas usinas ({len(resto)})" if not menos else
            f"todas as suas usinas menos {', '.join(u.nome for u in menos.values())} ({len(resto)})")
    return {"todas": True, "menos": list(menos)}, dito, resto


async def _rele(ctx, link, alvo: str | None) -> str:
    """O relé pelo nome que a pessoa disse, lido agora no meuWatt (a tela Leituras, com o token dela)."""
    try:
        dados = await ctx.mw.leituras(link.mw_plant_slug)
    except httpx.HTTPError:
        raise Recusa("O meuWatt não respondeu agora para listar os relés: tente de novo em instantes.") from None
    nomes = [str(r.get("name")) for r in (dados or {}).get("relays") or [] if r.get("name")]
    if not nomes:
        raise Recusa(f"O meuWatt não tem relé de proteção com leitura em {link.nome}.")
    casam = [n for n in nomes if auto._casa(alvo, n)] if alvo else []
    if len(casam) == 1:
        return casam[0]
    if not alvo and len(nomes) == 1:
        return nomes[0]
    raise Recusa(f"Qual relé de {link.nome}? " + ", ".join(nomes) + ". Pergunte (uma pergunta só).")


async def _trafo(ctx, link, alvo: str | None) -> tuple[str, float | None]:
    try:
        mon = await ctx.mw.monitoramento_atual(link.mw_plant_slug)
    except httpx.HTTPError:
        raise Recusa("O meuWatt não respondeu agora para listar os trafos: tente de novo em instantes.") from None
    sensores = (mon or {}).get("temp_sensors") or []
    nomes = {str(t.get("transformer_name") or t.get("name")): t for t in sensores if t.get("transformer_name") or t.get("name")}
    if not nomes:
        raise Recusa(f"O meuWatt não tem sonda de temperatura de trafo em {link.nome}.")
    casam = [n for n in nomes if auto._casa(alvo, n) or auto._casa(alvo, nomes[n].get("name"))] if alvo else []
    if len(casam) == 1 or (not alvo and len(nomes) == 1):
        nome = casam[0] if casam else next(iter(nomes))
        return nome, auto._limite_registrado(nomes[nome])
    raise Recusa(f"Qual trafo de {link.nome}? " + ", ".join(nomes) + ". Pergunte (uma pergunta só).")


def _como_chega(ctx) -> str:
    from app.services import avisos

    if avisos.tokens_do_usuario(ctx.db, ctx.user):
        return ("Chega no aplicativo do Gestão Solar e, se você tiver falado comigo nas últimas 24 h, também aqui no "
                "WhatsApp.")
    return ("Chega aqui no WhatsApp se você tiver falado comigo nas últimas 24 h; senão, espera a sua próxima mensagem "
            "(até 24 h). Para receber sempre, ligue os avisos no aplicativo do Gestão Solar.")


# ── criar ───────────────────────────────────────────────────────────────────


FERRAMENTA_CRIAR = _f(
    "criar_automacao",
    "Cria uma AUTOMAÇÃO do Gestão Solar para esta pessoa (é daqui, não do meuPlano): um LEMBRETE ('me lembra de ver a "
    "geração amanhã ao meio-dia'), uma regra de HORÁRIO que repete ('todo dia às 19h me manda o resumo da geração'; "
    "'às 18h30, se o PR de Ibitinga ficar abaixo de 70, analisa'), uma regra de LEITURA ('me avisa se a tensão do relé "
    "de Pirapozinho acabar por mais de 10 min', 'se a temperatura do TR-02 de Pereiras passar de 90 °C', 'me avisa de "
    "parada em todas as usinas menos Tietê') ou de GENTE NA USINA ('se entrar alguém em Pirapozinho com OS aberta, me "
    "avisa'). Passe SÓ o que a pessoa disse; datas e horas como ela falou (dia, hora, daqui_a_min): quem conta é o "
    "sistema. O sistema acha o equipamento, escolhe o resto e mostra o resumo com o Sim.",
    {"tipo": {"type": "string", "enum": ["lembrete", "horario", "leitura", "gente_na_usina"]},
     "texto": {"type": "string", "description": "lembrete: do que lembrar; ação de IA: o que analisar"},
     "dia": {"type": "string", "description": "lembrete: hoje, amanha, depois_de_amanha, AAAA-MM-DD ou o dia da semana "
                                              "(seg..dom)"},
     "hora": {"type": "string", "description": "HH:MM, 24 h, hora de Brasília"},
     "daqui_a_min": {"type": "integer", "description": "lembrete relativo: 'daqui a 2 horas' = 120"},
     "dias": {"type": "array", "items": {"type": "string", "enum": ["todos", "uteis", "seg", "ter", "qua", "qui", "sex",
                                                                    "sab", "dom"]},
              "description": "horário: em que dias (sem dizer: todos)"},
     "usinas": {"type": "array", "items": {"type": "string"}, "description": "as usinas como a pessoa disse; sem dizer: "
                                                                             "todas as dela"},
     "menos": {"type": "array", "items": {"type": "string"}, "description": "'todas menos X': as que ficam de fora"},
     "grandeza": {"type": "string", "enum": ["tensao_rele", "temperatura_trafo", "usina_parada"]},
     "alvo": {"type": "string", "description": "o relé ou o trafo como a pessoa disse ('Skid 1', 'TR-02', 'Geral')"},
     "operador": {"type": "string", "enum": ["abaixo", "acima"]},
     "limite": {"type": "number", "description": "V na tensão, °C na temperatura (só se a pessoa disse)"},
     "duracao_min": {"type": "integer", "description": "'por mais de 10 min' = 10"},
     "acao": {"type": "string", "enum": ["mensagem", "resumo_geracao", "ia"],
              "description": "resumo_geracao = o resumo da geração de hoje, sem IA; ia = a IA analisa"},
     "pr_abaixo_de": {"type": "number", "description": "condição: só se o PR do dia ficar abaixo deste % (ex.: 70)"},
     "so_com_os_aberta": {"type": "boolean", "description": "gente na usina: só avisa com OS aberta (padrão: sim)"},
     "canais": {"type": "array", "items": {"type": "string", "enum": ["whatsapp", "push"]}},
     "nome": {"type": "string", "description": "um nome curto, se a pessoa deu"}},
    ["tipo"])


async def _montar(ctx, a: dict) -> dict:
    """A regra pronta para gravar: nome, gatilho, condições, escopo, ação, entrega, situação e o resumo em uma linha."""
    tipo = a.get("tipo")
    canais = [c for c in a.get("canais") or [] if c in ("whatsapp", "push")]
    condicoes: list[dict] = []
    escopo: dict = {}
    situacao = "ligada"
    if tipo == "lembrete":
        texto = (a.get("texto") or "").strip()
        if not texto:
            raise Recusa("Lembrar de quê? Pergunte.")
        quando = quando_do_lembrete(a)
        gatilho = {"tipo": "uma_vez", "em": quando.isoformat()}
        acao = {"tipo": "ia", "prompt": texto} if a.get("acao") == "ia" else {"tipo": "mensagem", "texto": texto}
        nome = a.get("nome") or f"Lembrete: {texto[:70]}"
        resumo = f"Lembrete em {quando:%d/%m} às {quando:%H:%M}: «{texto}»"
        canais = canais or ["whatsapp", "push"]
    elif tipo == "horario":
        hora = _hora(a.get("hora"))
        if hora is None and a.get("pr_abaixo_de") is not None:
            hora = dtime(18, 30)                           # o PR do dia: às 18:30 o dia solar fechou
        if hora is None:
            raise Recusa("A que horas? Pergunte (ex.: 19:00).")
        dias = _dias_da_semana(a.get("dias"))
        gatilho = {"tipo": "horario", "hora": hora.strftime("%H:%M"), "dias": dias}
        texto = (a.get("texto") or "").strip()
        tipo_acao = a.get("acao") or ("mensagem" if texto and a.get("pr_abaixo_de") is None else "resumo_geracao")
        if a.get("pr_abaixo_de") is not None:
            condicoes.append({"tipo": "pr_dia", "operador": "<", "limite": float(a["pr_abaixo_de"])})
        if tipo_acao == "mensagem":
            if not texto:
                raise Recusa("Mandar o quê nesse horário? Pergunte.")
            acao, o_que, dito = {"tipo": "mensagem", "texto": texto}, f"«{texto}»", ""
        else:
            escopo, dito, _ = _escopo(ctx, a, com_monitoramento=True)
            if "bot_meuwatt" not in ctx.user.bot_ativo:
                raise Recusa("O monitoramento (meuWatt) do bot não está liberado para você: o gerente da O&M libera.")
            if tipo_acao == "ia":
                acao = {"tipo": "ia", "prompt": texto or "Resuma a geração de hoje e o que chamou atenção."}
                o_que = "a análise da IA" + (f" («{texto}»)" if texto else "")
                situacao = "ensaio"
            else:
                acao, o_que = {"tipo": "resumo_geracao"}, "o resumo da geração"
        rel = auto._dias_em_palavras(gatilho)
        cond = f", se o PR do dia ficar abaixo de {auto._n(a['pr_abaixo_de'], 0)}%" if a.get("pr_abaixo_de") is not None else ""
        nome = a.get("nome") or (f"{'Análise da IA' if acao['tipo'] == 'ia' else 'Resumo da geração' if acao['tipo'] == 'resumo_geracao' else 'Mensagem'} "
                                 f"às {gatilho['hora']}")
        resumo = f"{rel.capitalize()} às {gatilho['hora']}{cond}: {o_que}" + (f" de {dito}" if dito else "")
        canais = canais or ["whatsapp", "push"]
    elif tipo == "leitura":
        if "bot_meuwatt" not in ctx.user.bot_ativo or ctx.mw is None:
            raise Recusa("O monitoramento (meuWatt) do bot não está liberado para você, ou falta o seu token de lá: o "
                         "gerente da O&M libera.")
        gr = a.get("grandeza")
        if gr not in auto.GRANDEZAS:
            raise Recusa("Avisar de quê? Tensão do relé, temperatura do trafo ou usina parada: pergunte.")
        situacao = "ensaio"
        canais = canais or ["whatsapp", "push"]
        if gr == "usina_parada":
            escopo, dito, _ = _escopo(ctx, a, com_monitoramento=True)
            gatilho = {"tipo": "leitura", "grandeza": gr, "duracao_min": int(a.get("duracao_min") or 0)}
            nome = a.get("nome") or ("Usina parada" + (f" (menos {', '.join(a['menos'])})" if a.get("menos") else ""))
            resumo = (f"Usina parada (a mesma régua do aviso de parada do aplicativo) em {dito}. Com esta regra ligada, "
                      "ela substitui o aviso de parada antigo para você")
        else:
            links = _links(ctx, com_monitoramento=True)
            link = _uma_usina(links, (a.get("usinas") or [None])[0])
            op = {"abaixo": "<", "acima": ">"}.get(a.get("operador") or "", "<" if gr == "tensao_rele" else ">")
            duracao = int(a.get("duracao_min") or (10 if gr == "tensao_rele" else 5))
            limite = a.get("limite")
            if gr == "tensao_rele":
                alvo = await _rele(ctx, link, a.get("alvo"))
                limite = float(limite) if limite is not None else auto.TENSAO_PISO_V
                como = (f"sem tensão (as fases abaixo de {auto._n(limite, 0)} V) ou com uma fase zerada" if op == "<"
                        else f"com uma fase acima de {auto._n(limite, 0)} V")
                nome = a.get("nome") or f"Tensão do {alvo} ({link.nome})"
            else:
                alvo, registrado = await _trafo(ctx, link, a.get("alvo"))
                if limite is None:
                    limite = registrado
                if limite is None:
                    raise Recusa(f"{'Acima' if op == '>' else 'Abaixo'} de quantos graus? Pergunte.")
                limite = float(limite)
                como = f"{'acima' if op == '>' else 'abaixo'} de {auto._n(limite, 0)} °C (a maior das sondas)"
                nome = a.get("nome") or f"Temperatura do {alvo} ({link.nome})"
            gatilho = {"tipo": "leitura", "grandeza": gr, "alvo": alvo, "operador": op, "limite": limite,
                       "duracao_min": duracao}
            escopo = {"usinas": [link.id]}
            resumo = f"{link.nome} · {alvo}: avisar quando ficar {como} por {duracao} min, e quando voltar ao normal"
        acao = {"tipo": "mensagem"}
    elif tipo == "gente_na_usina":
        from app.services import assistente_meuguarda as mg

        if not mg.permitidas(ctx.user):
            raise Recusa("As câmeras (meuGuarda) não estão liberadas para você: o gerente da O&M libera.")
        com_os = a.get("so_com_os_aberta") is not False
        if com_os and "bot_meuplano" not in ctx.user.bot_ativo:
            raise Recusa("Para conferir a OS aberta, a parte de manutenção (meuPlano) do bot precisa estar liberada para "
                         "você: o gerente da O&M libera.")
        escopo, dito, _ = _escopo(ctx, a, com_monitoramento=False)
        gatilho = {"tipo": "camera", "tipos": list(auto.GENTE)}
        if com_os:
            condicoes.append({"tipo": "os_aberta"})
        acao = {"tipo": "mensagem"}
        nome = a.get("nome") or ("Gente na usina" + (" com OS aberta" if com_os else ""))
        resumo = (f"Gente na usina (câmera ou central do meuGuarda) em {dito}"
                  + (": avisar quando houver OS aberta, uma vez por OS por dia" if com_os
                     else ": avisar, no máximo uma vez a cada 30 min por usina"))
        situacao = "ensaio"
        canais = canais or ["whatsapp", "push"]
    else:
        raise Recusa("Que tipo de automação? Lembrete, horário, leitura ou gente na usina: pergunte.")
    if acao.get("tipo") == "ia":
        situacao = "ensaio"
    return {"nome": nome, "gatilho": gatilho, "condicoes": condicoes, "escopo": escopo, "acao": acao,
            "entrega": {"canais": canais}, "situacao": situacao, "resumo": resumo}


async def criar_automacao(ctx, a: dict) -> dict:
    from app.services import assistente_helper as helper

    plano = await _montar(ctx, a)
    if len(auto.ativas(ctx.db, ctx.user.id)) >= auto.MAX_REGRAS:
        raise Recusa(f"Você já tem {auto.MAX_REGRAS} regras: peça para apagar alguma antes.")
    ensaio = plano["situacao"] == "ensaio"
    como_chega = _como_chega(ctx)
    pedido = ctx.pedido or None

    async def executar(db, user, telefone: str) -> str:
        try:
            regra = auto.criar(db, user, nome=plano["nome"], gatilho=plano["gatilho"], acao=plano["acao"],
                               condicoes=plano["condicoes"], escopo=plano["escopo"], entrega=plano["entrega"],
                               situacao=plano["situacao"], texto_original=pedido)
        except auto.RegraInvalida as e:
            return f"❌ Não criei: {e}"
        fim = (f" Nasce em ENSAIO: o 1º aviso chega marcado [ensaio]; se ficar bom, diga «liga a regra {regra.id}»."
               if ensaio else "")
        return f"✅ Regra {regra.id} criada: {plano['resumo']}.{fim} {como_chega}"

    return helper.propor(ctx, f"Criar a regra «{plano['nome']}»: {plano['resumo']}", 600, executar,
                         [("Nasce em ensaio (o 1º aviso sai marcado [ensaio])." if ensaio else ""), como_chega],
                         parte=None, confirmacao="sim")


# ── listar e mexer ──────────────────────────────────────────────────────────


FERRAMENTA_LISTAR = _f(
    "minhas_automacoes",
    "As automações (regras e lembretes) desta pessoa no Gestão Solar: número, nome, quando age, situação (ligada, "
    "ensaio, pausada), a próxima vez, o último aviso e se está cega (sem dado). 'Quais regras eu tenho?', 'meus "
    "lembretes', 'o que você vai me avisar?'.",
    {})


def _cega(regra: Automacao) -> str | None:
    for chave, st in ((regra.estado or {}).get("alvos") or {}).items():
        if st.get("cega"):
            return f"cega desde {auto._hora(auto._ts(st.get('sem_dado_desde')))} ({st.get('porque') or 'sem dado'})"
    return None


async def minhas_automacoes(ctx, a: dict) -> dict:
    regras = auto.ativas(ctx.db, ctx.user.id)
    if not regras:
        return {"regras": [], "nota": "Esta pessoa não tem automação. Diga que ela pode pedir, por exemplo: «me lembra "
                                      "de ver a geração amanhã ao meio-dia» ou «todo dia às 19h me manda o resumo da "
                                      "geração»."}
    saida = []
    for r in regras:
        d = auto.ultimo_disparo(ctx.db, r)
        item = {"numero": r.id, "nome": r.nome, "quando": auto.descrever(r), "situacao": r.situacao}
        if (onde := auto.onde(ctx.db, r)):
            item["onde"] = onde
        if r.situacao in ("ligada", "ensaio") and (r.gatilho or {}).get("tipo") in ("horario", "uma_vez") and r.proxima_em:
            item["proxima"] = auto._hora(auto._utc(r.proxima_em), com_dia=True)
        if d is not None:
            item["ultimo_aviso"] = f"{auto._hora(auto._utc(d.em), com_dia=True)} ({d.evento}, {d.status})"
        if (c := _cega(r)):
            item["cega"] = c
        if r.situacao == "ensaio":
            item["ensaio_segurados"] = auto.segurados(ctx.db, r)
        if r.ultimo_erro:
            item["ultimo_erro"] = r.ultimo_erro
        saida.append(item)
    return {"regras": saida, "como_mexer": "«pausa a regra N», «liga a regra N», «apaga a regra N», «testa a regra N»."}


FERRAMENTA_MEXER = _f(
    "mexer_automacao",
    "Mexe numa automação DESTA pessoa: ligar (sai do ensaio e passa a avisar de verdade), pausar, ensaio, apagar ou "
    "testar (mostra o que ela faria AGORA, sem mandar nada). Ligar e apagar pedem o Sim.",
    {"qual": {"type": "string", "description": "o número da regra (ou um pedaço do nome)"},
     "acao": {"type": "string", "enum": ["ligar", "pausar", "ensaio", "apagar", "testar"]}},
    ["qual", "acao"])


async def mexer_automacao(ctx, a: dict) -> dict:
    from app.services import assistente_helper as helper

    try:
        regra = auto.achar(ctx.db, ctx.user, a.get("qual"))
    except auto.RegraInvalida as e:
        raise Recusa(str(e)) from None
    acao = a.get("acao")
    rid, nome = regra.id, regra.nome
    if acao == "testar":
        return {"teste": await auto.testar(ctx.db, regra),
                "instrucao": "Mostre o teste à pessoa como está (é o que a regra faria agora; nada foi mandado)."}
    if acao in ("pausar", "ensaio"):
        try:
            auto.mudar(ctx.db, regra, "pausada" if acao == "pausar" else "ensaio")
        except auto.RegraInvalida as e:
            raise Recusa(str(e)) from None
        return {"feito": f"Regra {rid} «{nome}» " + ("pausada: não avisa até você dizer «liga a regra %d»." % rid
                                                     if acao == "pausar" else "em ensaio: o 1º aviso sai marcado [ensaio].")}
    if acao == "ligar":
        como = _como_chega(ctx)
        if (regra.gatilho or {}).get("tipo") == "uma_vez" and (auto._utc(regra.proxima_em) or auto._agora()) <= auto._agora():
            raise Recusa("Esse lembrete já passou da hora: não há o que ligar. Diga que ela peça um lembrete novo.")

        async def executar(db, user, telefone: str) -> str:
            r = db.get(Automacao, rid)
            if r is None or r.apagada_em is not None:
                return "❌ Essa regra não existe mais."
            try:
                auto.mudar(db, r, "ligada")
            except auto.RegraInvalida as e:
                return f"❌ Não liguei: {e}"
            return f"✅ Regra {rid} «{nome}» ligada: os avisos passam a sair de verdade. {como}"

        return helper.propor(ctx, f"Ligar a regra {rid} «{nome}» ({auto.descrever(regra)})", 600, executar, [como],
                             parte=None, confirmacao="sim")
    if acao == "apagar":
        async def executar(db, user, telefone: str) -> str:
            r = db.get(Automacao, rid)
            if r is None or r.apagada_em is not None:
                return "Essa regra já não existia."
            auto.apagar(db, r)
            return f"🗑️ Regra {rid} «{nome}» apagada."

        return helper.propor(ctx, f"Apagar a regra {rid} «{nome}»", 600, executar, [], parte=None, confirmacao="sim")
    raise Recusa("Ligar, pausar, ensaio, apagar ou testar? Pergunte.")


# ── memória ─────────────────────────────────────────────────────────────────


FERRAMENTA_MEMORIA = _f(
    "memoria",
    "A MEMÓRIA desta pessoa no bot (só dela): gravar o que ela pediu para você lembrar ('lembre que PF é Porto "
    "Ferreira', 'sempre me responda em uma linha', 'me chame de Renan', 'guarda que eu prefiro em MWh'), listar ('o "
    "que você lembra de mim?') e esquecer ('esquece o 2', 'esquece tudo'). NÃO é memória: registrar o dia de trabalho "
    "('anota que o Diogo trabalhou…' → manutencao), o que é da usina (string, problema, procedimento → a ferramenta do "
    "sistema dono) e senha (nunca se guarda).",
    {"acao": {"type": "string", "enum": ["gravar", "listar", "esquecer", "esquecer_tudo"]},
     "tipo": {"type": "string", "enum": ["instrucao", "vocabulario", "anotacao"],
              "description": "instrucao = como responder; vocabulario = um apelido ou sigla; anotacao = o resto"},
     "texto": {"type": "string", "description": "gravar: a frase, nas palavras dela"},
     "qual": {"type": "string", "description": "esquecer: o número da lista ou um pedaço do texto"}},
    ["acao"])

#: Instrução que tenta mudar as regras do sistema não vira memória (a memória entra no prompt de todas as mensagens).
_REGRA_DO_SISTEMA = re.compile(
    r"(?:n[aã]o|nunca)\s+(?:precisa\w*|pe[cç]a\w*|pedir|pergunt\w*|confirm\w*)\b"
    r"|sem\s+(?:me\s+)?(?:pedir|perguntar|confirm\w*|o\s+sim)\b|\bignor\w*|\bexecut\w*\s+(?:direto|sem)\b"
    r"|\b(?:ferramenta|permiss\w*|recorte|token|prompt|regras?\s+do\s+sistema)\b|usinas?\s+de\s+outr"
    r"|outra\s+pessoa|outro\s+usu[aá]rio|\bvoc[eê]\s+(?:pode|deve)\s+(?:sempre\s+)?(?:executar|fazer|apagar|ligar|desligar)",
    re.I)


async def memoria(ctx, a: dict) -> dict:
    from app.services import assistente_helper as helper

    acao = a.get("acao")
    try:
        if acao == "gravar":
            texto = a.get("texto") or ""
            if _REGRA_DO_SISTEMA.search(texto):
                return {"recusado": "Isso eu não guardo: são regras do sistema (confirmação, senha, ferramentas e o que "
                                    "cada um vê não mudam por pedido)."}
            item, novo = mem.gravar(ctx.db, ctx.user, a.get("tipo"), texto)
            rotulo = mem.TIPOS.get(item["tipo"], item["tipo"])
            return {"feito": (f"Anotei ({rotulo}): {item['texto']}" if novo else f"Já estava anotado: {item['texto']}"),
                    "instrucao": "Responda em uma linha com o «feito» acima, sem acrescentar nada."}
        if acao == "listar":
            itens = mem.listar(ctx.db, ctx.user)
            if not itens:
                return {"memoria": [], "nota": "A memória está vazia: diga que ela pode pedir «lembre que …»."}
            return {"memoria": [f"{i['n']}. ({mem.TIPOS.get(i['tipo'], i['tipo'])}) {i['texto']}" for i in itens],
                    "como_esquecer": "«esquece o N» ou «esquece tudo»."}
        if acao == "esquecer":
            feito = mem.esquecer(ctx.db, ctx.user, a.get("qual"))
            return {"feito": f"Esqueci: {feito[0]}"}
        if acao == "esquecer_tudo":
            n = len(mem.listar(ctx.db, ctx.user))
            if not n:
                return {"feito": "A memória já estava vazia."}

            async def executar(db, user, telefone: str) -> str:
                return f"🧹 Esqueci tudo ({mem.esquecer_tudo(db, user)} itens)."

            return helper.propor(ctx, f"Esquecer tudo o que guardei de você ({n} itens)", 600, executar, [],
                                 parte=None, confirmacao="sim")
    except mem.MemoriaRecusada as e:
        return {"recusado": str(e)}
    raise Recusa("Gravar, listar ou esquecer? Pergunte.")


FERRAMENTAS = {
    "criar_automacao": (criar_automacao, FERRAMENTA_CRIAR),
    "minhas_automacoes": (minhas_automacoes, FERRAMENTA_LISTAR),
    "mexer_automacao": (mexer_automacao, FERRAMENTA_MEXER),
    "memoria": (memoria, FERRAMENTA_MEMORIA),
}

#: O que a IA de uma automação NÃO recebe (ela só lê: nem cria regra nem mexe na memória).
SO_NA_CONVERSA = frozenset(FERRAMENTAS)

PROMPT = """- AUTOMAÇÃO e LEMBRETE são do Gestão Solar (não do meuPlano): "me lembra de…", "me avisa se/quando…", "todo dia às…",
  "se a tensão/temperatura… passar…", "se entrar alguém na usina…" → `criar_automacao` (as palavras dela; dia, hora e
  "daqui a" quem conta é o sistema). "Quais regras eu tenho", "pausa/liga/apaga/testa a regra N" → `minhas_automacoes`
  e `mexer_automacao`. Só "cria um lembrete NO MEUPLANO" (ou de uma OS ou tarefa de lá) vai à `manutencao`.
- MEMÓRIA: "lembre que…", "guarda que eu…", "sempre me responda…", "me chame de…", "o que você lembra de mim",
  "esquece…" → `memoria`. Não é memória: o dia de trabalho ("anota que o Diogo trabalhou…" → `manutencao`), o que é
  da usina (string, problema, procedimento → a ferramenta do sistema dono) e senha (nunca).
- "[aviso automático · regra N …]" na conversa foi o sistema que mandou, por uma regra da pessoa: se ela responder
  sobre ele ("abre uma OS para isso"), use-o como contexto e consulte de novo antes de afirmar."""
