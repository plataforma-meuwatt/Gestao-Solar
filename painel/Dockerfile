# Serviço do PAINEL — o front web do gestor.
#
# Um dos dois serviços do Gestão Solar no Railway; o outro é a API (`bff/Dockerfile`). O
# aplicativo do dono da usina (`app/`) não é serviço web: vai para as lojas via EAS.
#
# Contexto de build: a pasta `painel/`. No Railway, Root Directory = `painel`.

# ── build ───────────────────────────────────────────────────────────────────
FROM node:22-alpine AS build

WORKDIR /painel

# O manifesto antes do código: enquanto as dependências não mudam, esta camada é
# reaproveitada e o build salta o `npm ci` inteiro.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# `tsc -b && vite build`: o build falha se os tipos falharem. É deliberado — um erro de
# tipo que passa para produção vira tela branca, e o lugar de descobri-lo é aqui.
RUN npm run build


# ── runtime ─────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# `envsubst`, usado pelo entrypoint para resolver a porta no template do nginx.
RUN apk add --no-cache gettext

COPY --from=build /painel/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/painel.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# A imagem não sabe a porta nem o endereço da API — os dois chegam como variável de
# ambiente e são resolvidos na subida. Ver `entrypoint.sh`.
ENTRYPOINT ["/entrypoint.sh"]
