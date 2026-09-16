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
    meuwatt_web_url: str = "https://app.meuwatt.com.br"
    #: O SITE do meuPlano, que não é o endereço da API dele. Usado para mandar o cliente
    #: direto para lá, já logado, a partir do portal.
    meuplano_web_url: str = "https://meuplano.meuwatt.com.br"
    # `api.meuplano.com.br` não resolve — o domínio nunca foi apontado. O host real é o do
    # Railway, e deixar o padrão errado fazia a primeira conexão falhar com "não foi
    # possível alcançar o endereço" antes mesmo de o gestor ter chance de suspeitar da URL.
    meuplano_api_url: str = "https://meuplano.up.railway.app"

    # ── gateway de WhatsApp ─────────────────────────────────────────────────
    # O serviço que fala com a Meta (`whatsapp/`). O BFF não conhece o token da Meta: ele
    # repassa ao gateway, que cifra e guarda. Vazio = a tela de administração do WhatsApp
    # diz que o gateway não está configurado neste ambiente, em vez de falhar no meio.
    whatsapp_gateway_url: str = ""
    #: A chave da porta interna, a MESMA dos dois lados. É ela que separa o BFF do resto do
    #: mundo na hora de mandar mensagem — e o gateway do resto do mundo na hora de avisar.
    whatsapp_chave_interna: str = ""

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
