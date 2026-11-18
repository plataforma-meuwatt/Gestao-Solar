# Serviço da API — o BFF.
#
# Um dos dois serviços do Gestão Solar no Railway; o outro é o painel
# (`painel/Dockerfile`). O aplicativo do dono da usina (`app/`) não é serviço web: vai para
# as lojas via EAS.
#
# Este contêiner não serve tela nenhuma. Quem consome esta API é o painel, de outro
# domínio, e o aplicativo, do celular — daí o CORS por `GS_CORS_ORIGENS` em `app/main.py`.
#
# Contexto de build: a pasta `bff/`. No Railway, Root Directory = `bff`.

FROM python:3.12-slim

# Sem .pyc e sem buffer: o log precisa sair na hora, não quando o buffer encher — um
# processo que morre com log preso não deixa rastro do motivo.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# O Chromium do Playwright (a foto do mapa único que o bot manda; o motor de PDF da Fase 5 também roda nele), numa camada
# própria ANTES das dependências: mudar o requirements.txt não baixa o navegador de novo. A versão é a do requirements
# (tests/test_dockerfile.py confere). Fica numa pasta de todos (o app roda como gestaosolar) e só sobe quando alguém pede
# a foto. O tini é o processo 1: recolhe os processos do Chromium que sobrarem (o uvicorn não recolhe).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir playwright==1.55.0 \
    && playwright install --with-deps --only-shell chromium && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*
# As dependências antes do código: enquanto `requirements.txt` não muda, esta camada é
# reaproveitada e o deploy salta a instalação inteira.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Roda como usuário sem privilégio. Um processo que atende a internet não tem por que
# poder escrever no próprio sistema de arquivos da imagem.
RUN useradd --create-home --uid 10001 gestaosolar && chown -R gestaosolar:gestaosolar /app
USER gestaosolar

# A migration roda no start, e não no build: no build não há banco alcançável, e é aqui que
# as variáveis do serviço existem. `alembic upgrade head` é idempotente — sem migration
# nova, não faz nada.
#
# O `sh -c` existe para expandir `$PORT`, que o Railway injeta e muda a cada deploy. O
# `exec` antes do uvicorn é o que importa: sem ele o shell continua sendo o processo
# principal, engole o SIGTERM do deploy e o uvicorn é morto sem encerrar o que estava
# atendendo — requisição em voo cortada a cada publicação.
#
# Migração que FALHA não derruba a API (avaliação de 24/10/2026): com o healthcheck do Coolify
# desligado, o contêiner morreria em laço e o aplicativo, o portal, os painéis e o bot iriam junto.
# Ela sobe com o banco como está e o log grita "MIGRACAO FALHOU" (como no meuPlano, 91393817).
ENTRYPOINT ["tini", "--"]
CMD ["sh", "-c", "alembic upgrade head || echo 'MIGRACAO FALHOU: a API sobe com o banco como esta. Rode alembic upgrade head e confira o log acima.' >&2; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8100}"]
