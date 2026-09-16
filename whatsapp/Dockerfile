# Serviço do gateway de WhatsApp.
#
# Terceiro serviço Python do Gestão Solar no Railway, ao lado do BFF (`bff/`) e do painel
# (`painel/`). Contexto de build: a pasta `whatsapp/`. No Railway, Root Directory = `whatsapp`.
#
# Este contêiner não serve tela e não fala com navegador: quem o chama é a Meta (webhook) e o
# BFF (porta interna, por chave em cabeçalho). Não há CORS aqui de propósito.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 gateway && chown -R gateway:gateway /app
USER gateway

# A migration roda no start, como no BFF: no build não há banco alcançável. Ela usa a URL de
# MIGRAÇÃO (modo sessão, 5432); o servidor sobe com a de execução (modo transação, 6543).
#
# `exec` antes do uvicorn: sem ele o shell fica como processo principal, engole o SIGTERM do
# deploy e a requisição em voo é cortada — no webhook, isso é entrega perdida da Meta.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn gateway.main:app --host 0.0.0.0 --port ${PORT:-8120}"]
