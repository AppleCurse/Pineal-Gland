# =============================================================================
# DijitalVarlik — Master Launcher
# Tum servisleri tek komutla baslatir ve saglik kontrolu yapar
#
# Kullanim:
#   .\start_all.ps1
# =============================================================================

$ErrorActionPreference = "SilentlyContinue"
$ROOT = $PSScriptRoot
$VENV_AGENT = "$ROOT\agent_core\.venv\Scripts\python.exe"
$VENV_COCKPIT = "$ROOT\cockpit\.venv\Scripts\python.exe"
$VENV_LITELLM = "$ROOT\deploy\litellm\.venv\Scripts\python.exe"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  DIJITALVARLIK — MASTER LAUNCHER" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

# ---------- Port kontrol fonksiyonu ----------
function Test-Port([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return ($null -ne $conn)
}

# ---------- HTTP saglik kontrol ----------
function Test-Health([string]$url) {
    try {
        $r = Invoke-RestMethod $url -TimeoutSec 5 -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

# ---------- Servis baslatma ----------
function Start-Service([string]$name, [int]$port, [string]$python, [string]$script, [string]$workdir) {
    if (Test-Port $port) {
        Write-Host "[CALISYOR] $name (port $port)" -ForegroundColor Green
        return
    }
    Write-Host "[BASLATILIYOR] $name -> port $port ..." -ForegroundColor Yellow
    if (!(Test-Path $python)) {
        Write-Host "[HATA] Python bulunamadi: $python" -ForegroundColor Red
        return
    }
    Start-Process -FilePath $python -ArgumentList $script `
        -WorkingDirectory $workdir `
        -WindowStyle Hidden -PassThru | Out-Null
}

# ---- LiteLLM Gateway (port 4000) ----
$litellmDir = "$ROOT\deploy\litellm"
$litellmConfig = "$litellmDir\config.yaml"
if (!(Test-Port 4000)) {
    Write-Host "[BASLATILIYOR] LiteLLM Gateway -> port 4000 ..." -ForegroundColor Yellow
    if (Test-Path "$litellmDir\.venv\Scripts\litellm.exe") {
        Start-Process -FilePath "$litellmDir\.venv\Scripts\litellm.exe" `
            -ArgumentList "--config `"$litellmConfig`" --port 4000" `
            -WorkingDirectory $litellmDir `
            -WindowStyle Hidden | Out-Null
    } elseif (Test-Path $VENV_LITELLM) {
        Start-Process -FilePath $VENV_LITELLM `
            -ArgumentList "-m litellm --config `"$litellmConfig`" --port 4000" `
            -WorkingDirectory $litellmDir `
            -WindowStyle Hidden | Out-Null
    } else {
        Write-Host "[ATLANDI] LiteLLM venv bulunamadi" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "[CALISYOR] LiteLLM Gateway (port 4000)" -ForegroundColor Green
}

# ---- ElizaOS / Eliza Server (port 3000) ----
Start-Service -name "ElizaOS" -port 3000 `
    -python $VENV_COCKPIT `
    -script "$ROOT\cockpit\third_party\eliza_server.py" `
    -workdir "$ROOT\cockpit"

# ---- Cockpit UI (port 5050) ----
Start-Service -name "Cockpit UI" -port 5050 `
    -python $VENV_COCKPIT `
    -script "$ROOT\cockpit\main.py" `
    -workdir "$ROOT\cockpit"

# ---- agent_core Orchestrator (port 5060) ----
Start-Service -name "agent_core" -port 5060 `
    -python $VENV_AGENT `
    -script "$ROOT\agent_core\agent_core.py" `
    -workdir "$ROOT\agent_core"

# ---- deer-flow (port 8001) ----
$deerflowDir = "$ROOT\deer-flow"
if (Test-Path $deerflowDir) {
    $deerPython = "$deerflowDir\.venv\Scripts\python.exe"
    Start-Service -name "deer-flow" -port 8001 `
        -python $deerPython `
        -script "-m uvicorn src.server.app:app --host 0.0.0.0 --port 8001" `
        -workdir $deerflowDir
} else {
    Write-Host "[ATLANDI] deer-flow dizini bulunamadi" -ForegroundColor DarkYellow
}

# ---------- 20 saniye bekle ----------
Write-Host ""
Write-Host "Servisler baslatildi. 20 saniye bekleniyor..." -ForegroundColor Cyan
for ($i = 20; $i -gt 0; $i--) {
    Write-Progress -Activity "Baslama bekleniyor" -Status "$i saniye kaldi" -PercentComplete ((20-$i)*5)
    Start-Sleep 1
}
Write-Progress -Completed -Activity "Hazir"

# ---------- Saglik Kontrolu ----------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SAGLIK KONTROLU" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

$ports = @(3000, 4000, 5050, 5060, 8001)
foreach ($p in $ports) {
    $status = if (Test-Port $p) { "DINLIYOR" } else { "KAPALI" }
    $color  = if ($status -eq "DINLIYOR") { "Green" } else { "Red" }
    Write-Host "  Port $p : $status" -ForegroundColor $color
}

Write-Host ""
Write-Host "agent_core /health:" -ForegroundColor Cyan
try {
    $h = Invoke-RestMethod http://localhost:5060/health -TimeoutSec 8
    Write-Host "  status : $($h.status)" -ForegroundColor Green
    Write-Host "  eliza  : $($h.services.eliza)" -ForegroundColor $(if ($h.services.eliza) {"Green"} else {"Red"})
    Write-Host "  deerflow: $($h.services.deerflow)" -ForegroundColor $(if ($h.services.deerflow) {"Green"} else {"Yellow"})
    Write-Host "  agent_zero: $($h.services.agent_zero)" -ForegroundColor $(if ($h.services.agent_zero) {"Green"} else {"Yellow"})
} catch {
    Write-Host "  [HATA] agent_core yanit vermiyor: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "Cockpit: http://localhost:5050" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
