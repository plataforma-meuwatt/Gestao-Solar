#!/bin/bash
# Testa o bot do WhatsApp contra a IA REAL, com o código DESTA pasta (ver rodar.py). Exemplos:
#   testes-ia/testar.sh "Qual a senha do cadeado de tiete" "geração de ibitinga ontem"
#   testes-ia/testar.sh --inteira "qual os ta em aberto hoje"
#   testes-ia/testar.sh --banco [--vezes 3]        # antes de publicar mudança no prompt ou nas ferramentas
#   testes-ia/testar.sh --colher                   # casos reais do Log do bot que ainda não estão no banco
#   --como <apelido>                               # outra conta do GS (padrão: renan.marquezini)
# A chave da IA e o banco ficam no contêiner da API na KingHost: o código vai até lá (num tar, numa pasta temporária
# que some no fim) e roda com as variáveis de lá. Nenhum segredo sai do contêiner.
set -euo pipefail
RAIZ=$(cd "$(dirname "$0")/.." && pwd)
API=xdvig6kzxa8etla4noobfdx7
ARGS=$(python3 -c 'import sys,json,base64; print(base64.b64encode(json.dumps(sys.argv[1:]).encode()).decode())' "$@")
BOOT='import sys,io,tarfile,tempfile,shutil,atexit,runpy
d=tempfile.mkdtemp(); atexit.register(shutil.rmtree,d,True)
tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractall(d,filter="data")
sys.path.insert(0,d+"/bff"); sys.argv=[d+"/testes-ia/rodar.py"]+sys.argv[1:]
runpy.run_path(sys.argv[0],run_name="__main__")'
tar -C "$RAIZ" --exclude=__pycache__ -czf - bff/app testes-ia/rodar.py testes-ia/banco.json |
  ssh -o BatchMode=yes -i /root/.ssh/kinghost_ed25519 root@177.153.20.214 \
    "c=\$(docker ps -q -f name=$API | head -1); docker exec -i \$c python -c '$BOOT' $ARGS"
