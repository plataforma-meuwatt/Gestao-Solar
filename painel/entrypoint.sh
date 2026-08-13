#!/bin/sh
# Resolve, na subida do contêiner, as duas coisas que só se sabem em tempo de execução:
# a porta em que o nginx escuta e o endereço da API.
#
# Fazer isto aqui — e não no build — é o que permite ao mesmo artefato servir qualquer
# ambiente. Promover de homologação para produção passa a ser trocar uma variável, e não
# reconstruir; o que subiu é exatamente o que foi testado.

set -e

: "${PORT:=80}"
: "${API_URL:=}"

if [ -z "$API_URL" ]; then
    # Sem endereço, o painel chamaria a si mesmo e receberia o próprio index.html no lugar
    # do JSON — o erro apareceria como "Unexpected token '<'" no console, longe da causa.
    # Melhor não subir do que subir quebrado de um jeito difícil de diagnosticar.
    echo "ERRO: API_URL não definida." >&2
    echo "      O painel não sabe onde está a API. Defina-a no serviço, apontando para o" >&2
    echo "      endereço público do back (ex.: https://gestao-solar-api.up.railway.app)." >&2
    exit 1
fi

# Sem barra no fim: o cliente HTTP concatena '/api/painel', e '//api' quebra o roteamento.
API_URL=$(printf '%s' "$API_URL" | sed 's:/*$::')

echo "painel: API em ${API_URL}, escutando na porta ${PORT}"

cat > /usr/share/nginx/html/config.js <<EOF
// Gerado na subida do contêiner. Não editar — ver painel/entrypoint.sh.
window.__GS_API__ = '${API_URL}'
EOF

# `envsubst` limitado a \$PORT: sem a lista, ele engoliria as variáveis do próprio nginx
# (\$uri, \$host) e o arquivo sairia com elas vazias.
envsubst '${PORT}' < /etc/nginx/templates/painel.conf.template > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
