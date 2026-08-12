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

    # A sessão do painel do gestor é curta de propósito: é a tela que guarda as
    # credenciais de serviço dos dois upstreams.
    gs_painel_sessao_horas: int = 8

    # Endereços dos upstreams. Servem de sugestão inicial no painel — o que vale é o que
    # o gestor grava em /painel, junto com a credencial de serviço. Credencial NÃO mora
    # mais em variável de ambiente: mudar uma exigiria redeploy, e o painel precisa que
    # ela seja editável e testável na hora.
    meuwatt_api_url: str = "https://api.meuwatt.com.br"
    meuwatt_web_url: str = "https://app.meuwatt.com.br"
    meuplano_api_url: str = "https://api.meuplano.com.br"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
