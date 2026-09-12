# Sobe o Gestão Solar para desenvolvimento.
#
# São aplicações independentes — a mesma separação que existe em produção, onde cada pasta
# é um serviço no Railway e o aplicativo vai para as lojas:
#
#     .\dev.ps1            back (API) + painel (gestor) + portal (cliente)
#     .\dev.ps1 -App       + o aplicativo (Expo)
#     .\dev.ps1 -Instalar  refaz a instalação (venv, npm, migrations) e sobe
#
# O PORTAL sobe por padrão desde 04/09/2026. Antes ele não subia — e foi assim que uma
# frente inteira do repositório passou meses invisível: quem seguia o caminho normal via
# back e painel, e concluía que o portal não fazia parte do sistema.
#
# O TALK SOLAR é opt-in, e a razão é outra: ele tem banco e `.env` PRÓPRIOS. Subi-lo por
# padrão daria um erro de conexão na largada, todo dia, para quem só quer mexer no Gestão
# Solar — e erro que aparece sempre é erro que ninguém mais lê.
#
# Cada parte abre na própria janela do PowerShell, com o nome no título — assim dá para
# ver o log de cada uma e reiniciar uma sem derrubar as outras.
#
# Em desenvolvimento os fronts falam com a API por proxy do Vite (mesma origem), e não por
# CORS: assim o caminho exercitado aqui é o mesmo de produção.
#
# As portas não se repetem, e cada uma tem dono (a tabela está no CLAUDE.md, § "Como
# rodar"): 8100 back · 5180 painel · 5181 portal · 8081 Metro do Expo.
#
# ⚠ ESTE ARQUIVO PRECISA DO BOM DE UTF-8, e não é preciosismo: o Windows PowerShell 5.1 lê
# .ps1 sem BOM como cp1252, e aí os bytes de `—` (E2 80 94) terminam em 0x94, que em cp1252
# é `”` — aspa que o parser aceita como FECHA-ASPAS. Um travessão dentro de uma string
# quebra o script inteiro, e o erro aponta o `if` de cima, longe da causa. Com o BOM, os
# acentos e o travessão são lidos certo em qualquer string. Salvou como UTF-8 puro? Volte
# o BOM antes de commitar.

param(
    [switch]$App,
    [switch]$Instalar
)

$ErrorActionPreference = 'Stop'
$raiz = $PSScriptRoot
$python = Join-Path $raiz 'bff\venv\Scripts\python.exe'

function Abrir($titulo, $pasta, $comando) {
    # `-NoExit` mantém a janela viva depois do comando: se o servidor cair na largada, o
    # erro fica na tela em vez de a janela sumir antes de alguém conseguir ler.
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-Command',
        "`$host.UI.RawUI.WindowTitle='$titulo'; Set-Location '$pasta'; $comando"
    )
}

# ---------------------------------------------------------------- instalação

if ($Instalar -or -not (Test-Path $python)) {
    Write-Host "`n> Preparando o backend (bff)…" -ForegroundColor Cyan
    if (-not (Test-Path $python)) { python -m venv (Join-Path $raiz 'bff\venv') }
    & $python -m pip install --upgrade pip --quiet
    & $python -m pip install -r (Join-Path $raiz 'bff\requirements.txt') --quiet

    Write-Host "> Aplicando as migrations no banco…" -ForegroundColor Cyan
    Push-Location (Join-Path $raiz 'bff')
    $env:PYTHONPATH = Join-Path $raiz 'bff'
    & $python -m alembic upgrade head
    Pop-Location
}

if ($Instalar -or -not (Test-Path (Join-Path $raiz 'painel\node_modules'))) {
    Write-Host "> Preparando o painel…" -ForegroundColor Cyan
    Push-Location (Join-Path $raiz 'painel'); npm install; Pop-Location
}

if ($Instalar -or -not (Test-Path (Join-Path $raiz 'portal\node_modules'))) {
    Write-Host "> Preparando o portal…" -ForegroundColor Cyan
    Push-Location (Join-Path $raiz 'portal'); npm install; Pop-Location
}

if (($Instalar -or $App) -and -not (Test-Path (Join-Path $raiz 'app\node_modules'))) {
    Write-Host "> Preparando o aplicativo…" -ForegroundColor Cyan
    Push-Location (Join-Path $raiz 'app'); npm install; Pop-Location
}

# -------------------------------------------------------------------- subida

Write-Host "`n> Subindo…" -ForegroundColor Cyan

# `--host 0.0.0.0` e não o padrão 127.0.0.1: o celular com Expo Go precisa alcançar o BFF
# pela rede local, e no padrão ele só aceitaria conexão da própria máquina.
Abrir 'Gestao Solar — BACK (API)' (Join-Path $raiz 'bff') `
    "`$env:PYTHONPATH='$raiz\bff'; .\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8100"

Abrir 'Gestao Solar — PAINEL (gestor)' (Join-Path $raiz 'painel') 'npm run dev'
Abrir 'Gestao Solar — PORTAL (cliente)' (Join-Path $raiz 'portal') 'npm run dev'

if ($App) {
    Abrir 'Gestao Solar — APLICATIVO (Expo)' (Join-Path $raiz 'app') 'npm start'
}

$ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } |
       Select-Object -First 1).IPv4Address.IPAddress

Write-Host @"

  BACK   (API)      http://localhost:8100     Swagger em /docs
  PAINEL (gestor)   http://localhost:5180     entra com apelido e senha
  PORTAL (cliente)  http://localhost:5181     a mesma conta do aplicativo
"@ -ForegroundColor Green

if ($App) {
    Write-Host "  APLICATIVO leia o QR code na janela do Expo (celular na mesma rede: $ip)" -ForegroundColor Green
} else {
    Write-Host "  Para subir o aplicativo também: .\dev.ps1 -App" -ForegroundColor DarkGray
}

