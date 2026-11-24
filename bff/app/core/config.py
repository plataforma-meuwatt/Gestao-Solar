"""Configuração do BFF, lida do ambiente.

Nada aqui tem valor padrão de segredo: `GS_JWT_SECRET` e as senhas de serviço vêm do .env
e o app se recusa a subir em produção sem elas (ver `Settings.validar_producao`).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco. Em dev, SQLite local evita exigir Postgres para rodar os testes.
    database_url: str = "sqlite:///./gestao_solar.db"

    # JWT que o BFF emite para o app.
    gs_jwt_secret: str = "dev-inseguro-trocar"
    gs_jwt_expira_horas: int = 24 * 30

    # Chave Fernet dos segredos guardados (senha das contas de serviço, tokens dos
    # clientes). Sem ela o painel não consegue gravar integração nenhuma.
    gs_encryption_key: str = ""

    # Chave PRIVADA (RS256, PEM) com que o Gestão Solar assina quem ele diz que é.
    #
    # Os produtos guardam só a pública. Três consequências que pagam o incômodo de gerar
    # um par de chaves: um vazamento da configuração do meuWatt não permite forjar login
    # de ninguém, não há segredo compartilhado para alguém colar no repositório errado, e
    # a verificação é local — o login lá não fica dependendo desta API estar no ar.
    #
    # Vazia, o Gestão Solar continua conectando e lendo os produtos normalmente; o que não
    # acontece é habilitar o "Entrar com Gestão Solar", e o painel diz isso em vez de
    # falhar calado.
    gs_sso_private_key: str = ""

    #: Quem esta instalação afirma ser, dentro da asserção. Os produtos conferem contra o
    #: que têm configurado: divergir aqui é login recusado, não aceito em silêncio.
    gs_sso_issuer: str = "gestao-solar"

    # De quantos em quantos MINUTOS o próprio BFF roda o motor de notificações. `0`
    # desliga (é o padrão, e é o que os testes usam).
    #
    # Existe porque não havia agendador nenhum: o motor tinha as duas portas de disparo —
    # a do cron e a do botão do painel — e ninguém as chamava, então nenhum aviso saía
    # sozinho. Rodar aqui dentro não pede serviço novo, credencial nem cron externo, e é
    # seguro porque o disparo é IDEMPOTENTE: a trava é `gs_notificacoes_enviadas`, único
    # por `user_id + chave`. Duas réplicas do BFF no ar fazem trabalho repetido, nunca
    # aviso repetido.
    gs_motor_minutos: int = 0

    # A sessão do painel do gestor é curta de propósito: é a tela que guarda as
    # credenciais de serviço dos dois upstreams.
    gs_painel_sessao_horas: int = 8

    # De onde o navegador pode chamar esta API. Separadas por vírgula.
    #
    # Existe porque o painel é um serviço próprio, num domínio próprio: toda chamada dele
    # é origem cruzada, e sem esta lista o navegador as barra antes de saírem. Uma lista
    # explícita, e não `*`: as respostas daqui carregam sessão de gestor, e liberar
    # qualquer origem deixaria qualquer página aberta no mesmo navegador falar com a API
    # em nome de quem estivesse logado.
    gs_cors_origens: str = ""

    @property
    def cors_origens(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.gs_cors_origens.split(",") if o.strip()]

    # Endereços dos upstreams. Servem de sugestão inicial no painel — o que vale é o que
    # o gestor grava em /painel, junto com a credencial de serviço. Credencial NÃO mora
    # mais em variável de ambiente: mudar uma exigiria redeploy, e o painel precisa que
    # ela seja editável e testável na hora.
    meuwatt_api_url: str = "https://api.meuwatt.com.br"
    #: O módulo de análise do meuWatt (o GÊMEO DIGITAL): o mesmo token da pessoa, outro endereço. Só a equipe da
    #: plataforma passa lá — o módulo confere o token no `/auth/me` do meuWatt.
    meuwatt_analise_url: str = "https://analise.meuwatt.com.br"
    meuwatt_web_url: str = "https://app.meuwatt.com.br"
    #: O R2 do meuWatt (bucket do orto das usinas): o GS assina o GET da imagem do voo direto, sem depender do mw-api
    #: (pedido do dono, 21/11/2026). Vazio = o mapa diz que o voo não carregou.
    meuwatt_r2_endpoint: str = ""
    meuwatt_r2_bucket: str = ""
    meuwatt_r2_access_key_id: str = ""
    meuwatt_r2_secret_access_key: str = ""
    #: O meuGuarda (CFTV das usinas, da família GS): câmeras e alarmes pelo bot. Sem token: o bot manda a sessão do GS
    #: da própria pessoa, e o meuGuarda a confere no `/eu` daqui (`clients/meuguarda.py`). Vazio = o bot não oferece.
    #: Pela rede interna do Docker (apelido fixo no Coolify, como o gateway): o DNS do sslip.io já calou o bot uma vez.
    meuguarda_api_url: str = "http://meuguarda-api:8000"
    #: O SITE do meuGuarda (o link "Mudar permissões no meuGuarda" da tela Usuários e o botão "meuGuarda" dos portões).
    meuguarda_web_url: str = "https://meuguarda.gestao.solar"
    #: O SITE do TermoVision (o botão "TermoVision" dos portões: a entrada pelo Gestão Solar fica em `/entrar.html`).
    termovision_web_url: str = "https://termovision.gestao.solar"
    #: a API do TermoVision que o bot chama ("Processar <usina>", provisionar a conta)
    termovision_api_url: str = "https://app.termovision.tech"
    #: o endereço público desta API (o TermoVision só avisa a hosts que ele conhece)
    gs_api_publica: str = "https://api.gestao.solar"
    #: o IP público dos servidores da KingHost e a rede interna: o que o meuGuarda e o TermoVision repassam SEM a chave
    #: (antes de adotá-la) tem um teto de senhas erradas por IP mais alto, para 30 erros de estranhos pela tela deles não
    #: trancarem todo mundo. A KingHost também roda outros projetos: confiança de verdade só com a chave do sistema.
    ips_da_casa: str = "177.153.20.214"
    #: o teto por IP desse repasse sem chave. 0 = sem teto por IP (só o limite por login e lugar), que é o TRANSITÓRIO:
    #: com teto, 120 erros de estranhos pela tela do meuGuarda trancariam todo mundo de lá. Vira 30 quando os dois sistemas
    #: mandarem a chave (variável TETO_IP_CASA_SEM_CHAVE)
    teto_ip_casa_sem_chave: int = 0
    #: O SITE do meuPlano, que não é o endereço da API dele. Usado para mandar o cliente
    #: direto para lá, já logado, a partir do portal. `meuplano.meuwatt.com.br` morreu com o
    #: Railway (23/10/2026: o DNS ainda aponta para lá, "Application not found").
    meuplano_web_url: str = "https://app.meuplano.solar"
    #: O PORTAL do GS (o cliente; o mapa único mora nele): a foto do mapa que o bot manda abre a página daqui.
    portal_web_url: str = "https://gestao.solar"
    # `api.meuplano.com.br` não resolve — o domínio nunca foi apontado. O host real é o do
    # Railway, e deixar o padrão errado fazia a primeira conexão falhar com "não foi
    # possível alcançar o endereço" antes mesmo de o gestor ter chance de suspeitar da URL.
    meuplano_api_url: str = "https://api.meuplano.solar"

    # ── gateway de WhatsApp ─────────────────────────────────────────────────
    # O serviço que fala com a Meta (`whatsapp/`). O BFF não conhece o token da Meta: ele
    # repassa ao gateway, que cifra e guarda. Vazio = a tela de administração do WhatsApp
    # diz que o gateway não está configurado neste ambiente, em vez de falhar no meio.
    whatsapp_gateway_url: str = ""
    #: O endereço PÚBLICO do gateway — o do webhook cadastrado na Meta. A API fala com o
    #: gateway pela rede interna (`whatsapp_gateway_url`); a Meta, de fora, só pelo público.
    #: Vazio = o mesmo de `whatsapp_gateway_url`.
    whatsapp_gateway_url_publica: str = ""
    #: A chave da porta interna, a MESMA dos dois lados. É ela que separa o BFF do resto do
    #: mundo na hora de mandar mensagem — e o gateway do resto do mundo na hora de avisar.
    whatsapp_chave_interna: str = ""

    # ── o meuGuarda lê as posições das câmeras no mapa único (`api/v1/interno_meuguarda.py`) ──
    #: A chave própria do meuGuarda (a mesma lá). Vazia = a porta recusa tudo (503).
    meuguarda_chave_interna: str = ""
    #: a chave do servidor do TermoVision quando ele repassa o login de uma pessoa (`X-Chave-Interna` com
    #: `X-Sistema: termovision`); a do meuGuarda é a `meuguarda_chave_interna`
    termovision_chave_interna: str = ""
    #: as do meuWatt e do meuPlano (`X-Sistema: meuwatt|meuplano`), para a porta dos sistemas (`interno_sistemas.py`):
    #: as usinas e a renovação da pessoa e o passe do TermoVision para o mapa embutido
    meuwatt_chave_interna: str = ""
    meuplano_chave_interna: str = ""

    # ── o helper (mw-modbus-helper) pelo assistente ─────────────────────────
    #: A porta do bot do helper (contrato `docs/bot.md` do helper): pelo túnel SSH reverso,
    #: `http://10.0.1.1:18080`, só de dentro da rede `coolify`. Vazio = o assistente não
    #: oferece o helper, e liberar a parte do helper é recusado com o motivo.
    helper_bot_url: str = ""
    helper_bot_chamador: str = "gestao-solar"
    #: A chave do chamador `gestao-solar` (a mesma do `MW_BOT_CALLERS_FILE` do helper).
    helper_bot_chave: str = ""

    # ── assistente do WhatsApp ──────────────────────────────────────────────
    #: DeepSeek (API compatível com a da OpenAI). Vazia = o assistente responde que está
    #: desligado, em vez de ficar mudo.
    deepseek_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"

    environment: str = "development"

    @property
    def producao(self) -> bool:
        return self.environment.lower() == "production"

    def validar_producao(self) -> None:
        """Falha alto em produção quando falta segredo — melhor não subir do que subir
        assinando token com a chave de desenvolvimento."""
        if not self.producao:
            return
        faltando = [
            nome
            for nome, valor in (
                ("GS_JWT_SECRET", self.gs_jwt_secret),
                ("GS_ENCRYPTION_KEY", self.gs_encryption_key),
            )
            if not valor or valor == "dev-inseguro-trocar"
        ]
        if faltando:
            raise RuntimeError(
                "Variáveis obrigatórias ausentes em produção: " + ", ".join(faltando)
            )
        # cada porta interna com a SUA chave: quem guarda a do WhatsApp (o gateway) não pode ler as câmeras
        if self.meuguarda_chave_interna and self.meuguarda_chave_interna == self.whatsapp_chave_interna:
            raise RuntimeError("MEUGUARDA_CHAVE_INTERNA não pode ser igual à WHATSAPP_CHAVE_INTERNA.")
        # e cada sistema com a sua: a chave de um não fala pelo outro
        chaves = [c for c in (self.whatsapp_chave_interna, self.meuguarda_chave_interna, self.termovision_chave_interna,
                              self.meuwatt_chave_interna, self.meuplano_chave_interna) if c]
        if len(chaves) != len(set(chaves)):
            raise RuntimeError("Duas portas internas com a mesma chave: cada sistema tem a sua (*_CHAVE_INTERNA).")

        # Sem origem liberada, a API sobe saudável e o painel abre numa tela em branco com
        # um erro de CORS no console — a falha mais cara de diagnosticar do conjunto,
        # porque nada no servidor acusa. Melhor não subir.
        if not self.cors_origens:
            raise RuntimeError(
                "GS_CORS_ORIGENS está vazia. Informe o endereço do painel "
                "(ex.: https://painel.exemplo.com.br), senão o navegador barra todas as "
                "chamadas dele a esta API."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
