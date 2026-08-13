# Sobe o Gestão Solar para desenvolvimento.
#
# São três aplicações independentes — a mesma separação que existe em produção, onde o
# back e o front são dois serviços no Railway e o aplicativo vai para as lojas:
#
#     .\dev.ps1            back (API) + front (painel)
#     .\dev.ps1 -App       back + front + o aplicativo (Expo)
#     .\dev.ps1 -Instalar  refaz a instalação (venv, npm, migrations) e sobe
#
# Cada parte abre na própria janela do PowerShell, com o nome no título — assim dá para
# ver o log de cada uma e reiniciar uma sem derrubar as outras.
#
# Em desenvolvimento o painel fala com a API por proxy do Vite (mesma origem), e não por
# CORS: assim o caminho exercitado aqui é o mesmo de produção — sempre `/api/painel/...`.

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

Abrir 'Gestao Solar — FRONT (painel)' (Join-Path $raiz 'painel') 'npm run dev'

if ($App) {
    Abrir 'Gestao Solar — APLICATIVO (Expo)' (Join-Path $raiz 'app') 'npm start'
}

$ip = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } |
       Select-Object -First 1).IPv4Address.IPAddress

Write-Host @"

  BACK  (API)     http://localhost:8100     Swagger em /docs
  FRONT (painel)  http://localhost:5180     entra com apelido e senha
"@ -ForegroundColor Green

if ($App) {
    Write-Host "  APLICATIVO leia o QR code na janela do Expo (celular na mesma rede: $ip)`n" -ForegroundColor Green
} else {
    Write-Host "  Para subir o aplicativo também: .\dev.ps1 -App`n" -ForegroundColor DarkGray
}
