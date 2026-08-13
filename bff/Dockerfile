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
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8100}"]
