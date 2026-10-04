"""Quem recebe aviso de usina parada, e o que o aviso diz.

O caminho tem três filtros, e os três são obrigatórios:

1. **Permissão concedida** — o gestor marcou `notificacao.usina_parada` para
   aquela pessoa. Sem isso, ninguém recebe nada.
2. **Escopo de usina** — a pessoa só é avisada das usinas que o gestor liberou
   para ela. Avisar sobre uma usina que ela não pode nem abrir seria vazamento:
   o nome da usina de outro cliente chegaria na tela de bloqueio do celular.
3. **Aparelho registrado** — alguém pode ter a permissão e nunca ter aberto o
   app no celular, ou ter negado o aviso no Android. Sem token não há entrega.

**Idempotência é responsabilidade de quem chama.** Este módulo envia o que lhe
pedirem; chamá-lo duas vezes para a mesma parada manda dois avisos. O controle
de "já avisei sobre esta parada" fica no chamador, que é quem sabe a janela de
tempo — e é por isso que `paradas_por_usuario` devolve a chave de cada parada.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.plants import usinas_do_usuario
from app.models.integracao import Produto
from app.models.permissao import Dispositivo
from app.models.plant import PlantLink
from app.models.user import User
from app.core.datas import hora_brt
from app.services import integracoes, permissoes, vinculos
from app.services.vocabulario_mw import causa_em_portugues

CATEGORIA = "notificacao"
SUBCATEGORIA = "usina_parada"


@dataclass
class AvisoDeParada:
    usuario: User
    usina: PlantLink
    #: Nome do inversor parado, como o meuWatt o chama. Na MICRO usina é o nome da
    #: estação no portal do fabricante, que é a unidade que aquele portal reporta.
    inversor: str
    #: `slot-N` — identifica a posição física, que sobrevive à troca do aparelho.
    #: Vazio na micro usina: o portal do fabricante não expõe posição, e inventar uma
    #: faria o toque na notificação abrir uma tela de equipamento que não existe.
    equipamento_id: str
    #: Chave estável desta parada, para o chamador não avisar duas vezes.
    chave: str
    #: O que o portal chamou o motivo ("equipamento fora"). Só na micro usina.
    motivo: str | None = None
    #: A causa que o detector do meuWatt deu, quando deu. Vira o CORPO do aviso
    #: agrupado: é o que a pessoa procura antes de decidir se vai à usina.
    causa: str | None = None
    #: Desde quando está parado, em hora de Brasília (`HH:MM`). Vai no corpo porque a
    #: primeira coisa que a equipe faz ao receber é conferir na tela — e sem a hora ela
    #: compara com o estado de AGORA, que pode já ter voltado.
    desde: str | None = None


#: Quanto tempo a parada precisa estar ABERTA para virar aviso.
#:
#: Sem isto o aviso saía na primeira volta em que o detector marcasse `down` — dez
#: minutos depois do início —, sem saber se aquilo ia durar sete minutos ou três horas.
#: Medido em Pirapozinho, 04/10/2026, com as paradas que o próprio detector registrou:
#:
#: | leva  | duração     | perda por inversor | o que era          |
#: |-------|-------------|--------------------|--------------------|
#: | 10:41 | 32 a 38 min | 20 a 26 kWh        | parada de verdade  |
#: | 11:38 | 7 a 16 min  | 0,01 a 0,10 kWh    | oscilação          |
#:
#: As duas viraram notificação, e a segunda foi a que a equipe em campo não reconheceu —
#: quando foram olhar, já tinha resolvido sozinha. Com vinte minutos de espera a primeira
#: ainda avisa (na volta seguinte) e a segunda não avisa nenhuma vez.
#:
#: **Esperar não é calar.** O custo é um atraso de no máximo uma volta no aviso
#: verdadeiro; o custo de não esperar é o alarme falso, que faz desligar a notificação
#: inteira — e aí o aviso verdadeiro da semana seguinte não chega em ninguém.
PERSISTENCIA_MINUTOS = 20

#: Parada mais velha que isto não gera aviso.
#:
#: Ao ligar o aviso pela primeira vez — ou ao conectar o meuWatt — a carteira pode ter
#: paradas abertas há semanas, e despejá-las todas na primeira volta é enxurrada de
#: notícia velha. Foi o que o dono recebeu em 30/09/2026. A régua é a mesma do meuPlano,
#: que já tinha pago esse preço.
JANELA_HORAS = 72


def _vale_avisar(inv: dict[str, Any]) -> bool:
    """A parada já persistiu o bastante, e ainda é notícia?

    Três perguntas, nesta ordem, e cada uma já custou um aviso errado:

    * **sem `down_since`, não se avisa.** Não dá para afirmar que persistiu o que não se
      sabe quando começou, e é esse mesmo campo que identifica a parada na memória — sem
      ele a chave já degrada para a data do dia. Em todas as paradas medidas no meuWatt o
      campo veio preenchido;
    * **jovem demais** não avisa: ver `PERSISTENCIA_MINUTOS`;
    * **velha demais** não avisa: ver `JANELA_HORAS`.
    """
    aberta = _aberta_ha(inv)
    if aberta is None:
        return False
    return timedelta(minutes=PERSISTENCIA_MINUTOS) <= aberta <= timedelta(hours=JANELA_HORAS)


def _aberta_ha(inv: dict[str, Any]) -> timedelta | None:
    """Há quanto tempo esta parada está aberta — ou `None` quando não se sabe."""
    quando = inv.get("down_since")
    if not quando:
        return None
    try:
        inicio = datetime.fromisoformat(str(quando).replace("Z", "+00:00"))
    except ValueError:
        return None
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=UTC)
    return datetime.now(UTC) - inicio


def _parados(monitoramento: Any) -> list[dict[str, Any]]:
    """Inversores em falha material, pela mesma régua das telas.

    `down` é o detector do mw-api afirmando parada aberta, e vence o `status`, que
    pode ainda dizer `normal`. Inversor ignorado pelo operador fica de fora: silenciá-lo
    foi decisão de quem opera, e acordar o dono de madrugada por causa dele seria
    discutir com essa decisão.
    """
    if not isinstance(monitoramento, dict):
        return []
    saida = []
    for inv in monitoramento.get("inverters") or []:
        if not isinstance(inv, dict) or inv.get("ignored"):
            continue
        estado = str(inv.get("status") or "").strip().lower()
        # `bedtime` é a usina dormindo — noite não é parada.
        if estado == "bedtime":
            continue
        # Parada jovem ou velha demais não entra: ver `_vale_avisar`.
        if (inv.get("down") is True or estado == "fault") and _vale_avisar(inv):
            saida.append(inv)
    return saida


async def paradas_por_usuario(db: Session) -> list[AvisoDeParada]:
    """Todos os avisos que caberiam agora, um por (pessoa, inversor parado).

    Consulta o monitoramento UMA vez por usina, mesmo quando dez pessoas têm acesso
    a ela: a leitura é a mesma, e repeti-la por pessoa multiplicaria a carga no
    meuWatt pelo número de clientes.
    """
    pessoas = permissoes.usuarios_com_permissao(db, CATEGORIA, SUBCATEGORIA)
    if not pessoas:
        return []

    # Escopo de cada pessoa, e o conjunto de usinas que precisamos consultar.
    escopos: dict[int, list[PlantLink]] = {p.id: usinas_do_usuario(db, p) for p in pessoas}
    alvos: dict[int, PlantLink] = {
        u.id: u for lista in escopos.values() for u in lista if u.mw_plant_slug
    }
    micro: dict[int, PlantLink] = {
        u.id: u for lista in escopos.values() for u in lista if u.so_micro
    }
    if not alvos and not micro:
        return []

    # Cada usina é lida com o token de ALGUÉM que tem acesso a ela — e uma vez só.
    #
    # Não existe mais credencial de serviço: quem lê o meuWatt é sempre uma pessoa. Mas a
    # propriedade que esta função protege continua valendo, e é a razão de ela existir
    # assim: a leitura de uma usina é a MESMA para todo mundo que a enxerga, então repeti-la
    # por pessoa multiplicaria a carga no meuWatt pelo número de clientes sem trazer um dado
    # novo. Basta um leitor por usina, e ele tem de ser alguém que legitimamente a vê.
    #
    # Usina cujos donos ainda não conectaram o meuWatt fica de fora, sem aviso. É o certo:
    # não temos como saber o estado dela, e calar é melhor do que inventar.
    leitor_da_usina: dict[int, int] = {}
    for pessoa in pessoas:
        if vinculos.obter(db, pessoa.id, Produto.MEUWATT) is None:
            continue
        for u in escopos.get(pessoa.id, []):
            leitor_da_usina.setdefault(u.id, pessoa.id)

    clientes: dict[int, Any] = {}
    estado: dict[int, list[dict[str, Any]]] = {}
    for link in alvos.values():
        dono = leitor_da_usina.get(link.id)
        if dono is None:
            continue
        try:
            if dono not in clientes:
                clientes[dono] = vinculos.cliente_meuwatt(db, dono)
            resposta = await clientes[dono].monitoramento_atual(link.mw_plant_slug)
        except Exception:  # noqa: BLE001
            # Usina fora do ar não gera aviso e não derruba as outras. Silêncio aqui é
            # correto: "não consegui ler" não é "parou".
            continue
        estado[link.id] = _parados(resposta)

    # ── as MICRO usinas, que o laço acima não alcança ──────────────────────────
    #
    # Elas não têm `mw_plant_slug`: quem as mede é o portal do fabricante (Solis,
    # Canadian, TSUN), e o meuWatt as expõe pelo MICRO. Ficavam de fora deste coletor, e
    # o dono de uma usina que só existe lá nunca recebia aviso de parada — enquanto o app
    # mostrava a potência dela na lista, vinda da mesma origem.
    #
    # **A leitura é com credencial de SERVIÇO, e essa é a exceção do MICRO:** ele não é
    # escopado por usina no meuWatt, só administrador o lê, então nenhum token de cliente
    # o enxerga. É a mesma exceção que `motor._coletar_parada_micro` já declara.
    paradas_micro: dict[int, list[dict[str, Any]]] = {}
    if micro:
        try:
            servico = await integracoes.cliente_meuwatt(db)
            alertas = await servico.micro_alertas()
        except Exception:  # noqa: BLE001 — MICRO fora não derruba o aviso das outras
            alertas = []
        por_micro_id: dict[int, list[PlantLink]] = {}
        for u in micro.values():
            por_micro_id.setdefault(u.mw_micro_plant_id, []).append(u)
        for alerta in alertas:
            for u in por_micro_id.get(alerta.get("plant_id"), []):
                paradas_micro.setdefault(u.id, []).append(alerta)

    avisos: list[AvisoDeParada] = []
    for pessoa in pessoas:
        for link in escopos[pessoa.id]:
            for alerta in paradas_micro.get(link.id, []):
                episodio = alerta.get("key") or alerta.get("id")
                if episodio is None:
                    continue
                avisos.append(
                    AvisoDeParada(
                        usuario=pessoa,
                        usina=link,
                        inversor=str(alerta.get("station_name") or "Estação"),
                        equipamento_id="",
                        # A chave do EPISÓDIO no meuWatt é estável: a mesma parada não
                        # avisa duas vezes, e uma nova, depois de resolvida, avisa.
                        chave=f"{link.id}:{episodio}",
                        motivo=str(alerta.get("kind_label") or "parada").lower(),
                    )
                )
            for inv in estado.get(link.id, []):
                equipamento_id = str(inv.get("id") or "")
                nome = str(inv.get("name") or inv.get("serial_number") or "Inversor")
                avisos.append(
                    AvisoDeParada(
                        usuario=pessoa,
                        usina=link,
                        inversor=nome,
                        equipamento_id=equipamento_id,
                        # `down_since` entra na chave: o mesmo inversor parando de novo
                        # depois de voltar é um evento NOVO e merece aviso novo.
                        chave=f"{link.id}:{equipamento_id}:{inv.get('down_since') or ''}",
                        # Traduzida já aqui: o código cru do detector
                        # ("zero_active_power") foi o corpo da notificação que o dono
                        # recebeu em 30/09/2026.
                        causa=causa_em_portugues(inv.get("down_cause")),
                        desde=hora_brt(inv.get("down_since")),
                    )
                )
    return avisos


def tokens_do_usuario(db: Session, usuario: User) -> list[str]:
    return list(
        db.scalars(select(Dispositivo.token).where(Dispositivo.user_id == usuario.id)).all()
    )


def texto_do_grupo(grupo: list[AvisoDeParada]) -> tuple[str, str, dict[str, Any]]:
    """UM aviso para todas as paradas da MESMA usina na mesma volta.

    Cinco inversores do mesmo skid caem juntos — é um evento, não cinco. Em 30/09/2026 o
    dono recebeu vinte toques seguidos, um por inversor de Porto Ferreira, e comparou com
    o meuPlano, que mandou um só: "20 inversores pararam". Ele tem razão, e a régua
    replicada aqui é a de lá (`meuPlano/backend/app/services/meuacesso/paradas_notify.py`):

    - **o título conta**, porque é o que aparece na tela bloqueada e é a diferença entre
      "um inversor" e "a usina inteira";
    - **o corpo traz a causa** quando o detector a tem; senão os nomes, que é o que a
      pessoa procura ao chegar na usina. Três cabem na tarja; o resto vira contagem;
    - **o toque leva ao lugar certo**: com UM parado, à tela daquele equipamento; com
      vários, à usina — uma tela de equipamento não responde "quais são os outros".

    A trava de repetição continua sendo POR PARADA (`gs_avisos_enviados`, uma linha por
    chave): agrupar é só a entrega. Um sexto inversor que cair depois gera aviso novo, e
    os cinco já avisados não voltam nele.
    """
    primeiro = grupo[0]
    usina = primeiro.usina
    n = len(grupo)
    nomes = [a.inversor for a in grupo]

    if usina.so_micro:
        # O portal do fabricante reporta ESTAÇÃO, não inversor, e não tem `slot-N`.
        titulo = f"{usina.nome} · parada" if n == 1 else f"{usina.nome}: {n} estações pararam"
        corpo = (
            f"{nomes[0]}: {primeiro.motivo or 'parada'}. Toque para ver a usina."
            if n == 1
            else _lista(nomes, n)
        )
    elif n == 1:
        titulo = f"{usina.nome} · inversor parado"
        corpo = f"{nomes[0]} parou de gerar{_desde(primeiro)}. Toque para ver o equipamento."
    else:
        titulo = f"{usina.nome}: {n} inversores pararam"
        causa = next((a.causa for a in grupo if a.causa), None)
        # A hora vem SEMPRE, com causa ou sem: a primeira coisa que a equipe faz ao
        # receber é abrir a tela, e lá ela vê o estado de AGORA — que pode já ter
        # voltado. Sem "desde quando", ela conclui que o aviso estava errado.
        corpo = f"{causa or _lista(nomes, n)}{_desde(primeiro)}."

    return (
        titulo,
        corpo,
        {
            "tipo": "usina_parada",
            "usina_id": usina.id,
            # Com vários, o toque vai para a USINA: a tela de um equipamento não diz
            # quais são os outros, que é a pergunta de quem acabou de ser avisado.
            "equipamento_id": primeiro.equipamento_id if n == 1 else "",
            "quantidade": n,
        },
    )


def _desde(aviso: AvisoDeParada) -> str:
    """" desde 08:41", ou nada quando não se sabe."""
    return f" desde {aviso.desde}" if aviso.desde and aviso.desde != "—" else ""


def _lista(nomes: list[str], n: int) -> str:
    """Três nomes cabem na tarja da notificação; o resto vira contagem."""
    return ", ".join(nomes[:3]) + (f" e outros {n - 3}" if n > 3 else "")


def texto_do_aviso(aviso: AvisoDeParada) -> tuple[str, str, dict[str, Any]]:
    """Título, corpo e a carga que o toque na notificação usa para abrir a tela certa.

    O nome da usina vai no TÍTULO porque é o que aparece na tela bloqueada quando o
    sistema corta o texto — quem tem sete usinas precisa saber qual antes de decidir
    se levanta da cama.
    """
    if aviso.usina.so_micro:
        # Sem "inversor" e sem equipamento: o portal do fabricante reporta a ESTAÇÃO, e
        # mandar tocar num equipamento que não existe abriria uma tela vazia.
        titulo = f"{aviso.usina.nome} · parada"
        corpo = f"{aviso.inversor}: {aviso.motivo or 'parada'}. Toque para ver a usina."
    else:
        titulo = f"{aviso.usina.nome} · inversor parado"
        corpo = f"{aviso.inversor} parou de gerar. Toque para ver o equipamento."
    dados = {
        "tipo": "usina_parada",
        "usina_id": aviso.usina.id,
        "equipamento_id": aviso.equipamento_id,
    }
    return titulo, corpo, dados
