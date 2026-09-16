"""Configuração do gateway, lida do ambiente.

**O pacote se chama `gateway`, e não `app`.** O BFF exporta `PYTHONPATH` apontando para a
pasta dele, e dois pacotes `app` na mesma máquina se atropelam — os testes de um passam a
importar o módulo do outro, e o erro chega disfarçado de "cannot import name". A lição é do
Talk Solar, e custou uma tarde.

**As credenciais da Meta NÃO moram aqui.** Token, número, segredo do app e token de
verificação são cadastrados na tela de administração do WhatsApp, no painel, e vivem
cifrados no banco (`services/credenciais.py`). O motivo é o mesmo que fez as pontes com o
meuWatt e o meuPlano saírem do `.env`: quem configura é o gestor, e ele precisa TESTAR —
digitar, ver se responde, corrigir. Com segredo em variável de ambiente, cada tentativa
custa um redeploy.

O que sobra no ambiente é o que o serviço precisa para SUBIR e para saber em quem confiar:
o banco, a chave que cifra os segredos e a chave da porta interna.

**Duas URLs de banco, de propósito.** Em execução o gateway fala pelo modo transação (6543),
em que a conexão volta ao pool a cada transação; o Alembic precisa do modo sessão (5432),
porque mantém estado entre comandos. Usar a mesma URL para os dois é o caminho para o
`EMAXCONNSESSION` que já derrubou o relatório do BFF.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── banco ───────────────────────────────────────────────────────────────
    #: Em execução: modo TRANSAÇÃO do pooler (porta 6543). SQLite em dev/testes.
    database_url: str = "sqlite:///./gateway.db"
    #: Só para o Alembic: modo SESSÃO (porta 5432). Vazia = usa a de execução.
    database_url_migracao: str = ""

    # ── segredos guardados ──────────────────────────────────────────────────
    #: Fernet, a mesma ideia do `GS_ENCRYPTION_KEY` do BFF. Sem ela o gateway sobe, mas a
    #: tela não consegue gravar credencial nenhuma — e diz isso, em vez de gravar em claro.
    gateway_encryption_key: str = ""

    # ── porta interna ───────────────────────────────────────────────────────
    #: Segredo do cabeçalho `X-Chave-Interna`, que separa o BFF do resto do mundo. É por ela
    #: que a tela do painel grava as credenciais e pede envio.
    whatsapp_chave_interna: str = ""
    #: Para onde o gateway avisa que chegou mensagem. Vazio = não avisa ninguém, e a
    #: varredura para de tentar (estado legítimo enquanto o motor não existe).
    bff_url: str = ""

    #: Versão da Graph. Fica no ambiente porque é decisão de OPERAÇÃO, não credencial: subir
    #: de versão é um deploy consciente, não um campo que alguém muda na tela sem querer.
    graph_api_version: str = "v25.0"

    environment: str = "development"

    @property
    def producao(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_api_version}"

    def validar_producao(self) -> None:
        """Falha alto em produção quando falta o que protege o serviço.

        Sem a chave interna, qualquer um pediria envio; sem a chave de cifragem, o token da
        Meta iria para o banco em texto. Melhor não subir.
        """
        if not self.producao:
            return
        faltando = [
            nome
            for nome, valor in (
                ("WHATSAPP_CHAVE_INTERNA", self.whatsapp_chave_interna),
                ("GATEWAY_ENCRYPTION_KEY", self.gateway_encryption_key),
            )
            if not valor
        ]
        if faltando:
            raise RuntimeError(
                "Variáveis obrigatórias ausentes em produção: " + ", ".join(faltando)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
