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

    # meuWatt (mw-api)
    meuwatt_api_url: str = "https://api.meuwatt.com.br"
    meuwatt_service_email: str = ""
    meuwatt_service_password: str = ""
    meuwatt_web_url: str = "https://app.meuwatt.com.br"

    # meuPlano
    meuplano_api_url: str = "https://api.meuplano.com.br"
    meuplano_service_email: str = ""
    meuplano_service_password: str = ""

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
                ("MEUWATT_SERVICE_PASSWORD", self.meuwatt_service_password),
                ("MEUPLANO_SERVICE_PASSWORD", self.meuplano_service_password),
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
