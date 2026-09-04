# Serviço do PORTAL — o site do CLIENTE (o dono da usina).
#
# Terceiro serviço do Gestão Solar no Railway (`appgestao`): a API (`bff/Dockerfile`) e o
# painel do gestor (`painel/Dockerfile`) são os outros dois. O portal não compartilha código
# nem sessão com o painel: são públicos diferentes, em domínios diferentes.
#
# Contexto de build: a pasta `portal/`. No Railway, Root Directory = `portal` e
# `railwayConfigFile = portal/railway.json` — sem o arquivo de config o builder cai no
# Railpack, ignora este Dockerfile e o `entrypoint.sh` nunca escreve o `config.js`.

# ── build ───────────────────────────────────────────────────────────────────
FROM node:22-alpine AS build

WORKDIR /portal

# O manifesto antes do código: enquanto as dependências não mudam, esta camada é
# reaproveitada e o build salta o `npm ci` inteiro.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# `npm run build` = `tsc --noEmit` + regra 0 + `vite build`: o build falha se os tipos
# falharem ou se alguma tela tiver zero inventado. O lugar de descobrir é aqui, não no
# navegador do cliente.
RUN npm run build


# ── runtime ─────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# `envsubst`, usado pelo entrypoint para resolver a porta no template do nginx.
RUN apk add --no-cache gettext

COPY --from=build /portal/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/portal.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# A imagem não sabe a porta nem o endereço da API — os dois chegam como variável de
# ambiente e são resolvidos na subida. Ver `entrypoint.sh`.
ENTRYPOINT ["/entrypoint.sh"]
