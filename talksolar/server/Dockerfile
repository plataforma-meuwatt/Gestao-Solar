# Serviço da Talk Solar — o mensageiro.
#
# Serviço PRÓPRIO no Railway, que sobe e cai sem afetar o BFF, o painel ou o portal. É a
# decisão central do projeto: a Talk Solar não importa uma linha de ninguém e conversa com
# os sistemas só por HTTP. Se ela cair, o meuPlano e o meuWatt continuam inteiros.
#
# Contexto de build: a pasta `talksolar/server/`. No Railway, Root Directory =
# `talksolar/server` E `railwayConfigFile = talksolar/server/railway.json` — este segundo é
# relativo à RAIZ do repositório, ao contrário do `dockerfilePath`. Sem ele o builder cai no
# Railpack e ignora a configuração, e a falha não é um deploy vermelho: é um serviço que
# sobe errado.
#
# Nasceu com NIXPACKS porque veio do repositório do meuPlano. Aqui os três serviços usam
# Dockerfile, e a uniformidade não é estética — é o que faz "por que o build daquele é
# diferente?" nunca ser uma pergunta às três da manhã.

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

# Roda como usuário sem privilégio. Um processo que atende a internet não tem por que poder
# escrever no próprio sistema de arquivos da imagem.
RUN useradd --create-home --uid 10001 talksolar && chown -R talksolar:talksolar /app
USER talksolar

# A migration roda no start, e não no build: no build não há banco alcançável, e é aqui que
# as variáveis do serviço existem. `alembic upgrade head` é idempotente, e as tabelas têm
# prefixo `ts_` — rodar num banco que já é do Gestão Solar não toca em nada que não seja
# dela.
#
# O `sh -c` existe para expandir `$PORT`, que o Railway injeta e muda a cada deploy. O
# `exec` antes do uvicorn é o que importa, e era o que faltava no `startCommand` herdado:
# sem ele o shell continua sendo o processo principal, engole o SIGTERM do deploy e o
# uvicorn é morto sem encerrar o que estava atendendo — requisição em voo cortada a cada
# publicação, e numa conversa em tempo real isso é mensagem que some no meio do caminho.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8110}"]
