# =====================================================================
# TUM SERVISLERI BASLAT  (native process'ler, Docker yok)
#   LiteLLM :4000 | deer-flow :8001 | agent-zero :5000 | agent_core :5060 | cockpit :5050
# Kullanim: powershell -ExecutionPolicy Bypass -File deploy\start_all.ps1
# =====================================================================

$ErrorActionPreference = "Continue"
$ws = $PSScriptRoot | Split-Path -Parent

function Start-Service {
    param([string]$Name, [string]$FilePath, [string[]]$ArgList, [string]$WorkDir, [hashtable]$Env = @{}, [string]$LogTag)
    $port = $null
    # zaten aciksa atla
    if ($ArgList -match "--port (\d+)") { $port = [int]$Matches[1] }
    elseif ($Name -eq "agent-zero") { $port = 5000 }
    elseif ($Name -eq "litellm-gateway") { $port = 4000 }
    elseif ($Name -eq "deer-flow") { $port = 8001 }
    elseif ($Name -eq "agent_core") { $port = 5060 }
    if ($port) {
        $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($c) { Write-Host "[$Name] zaten calisiyor (port $port)"; return }
    }
    # env degiskenlerini gecici olarak oturumda ayarla (PS5.1 uyumlu) sonra geri yukle
    $saved = @{}
    foreach ($k in $Env.Keys) {
        $saved[$k] = [System.Environment]::GetEnvironmentVariable($k, "Process")
        [System.Environment]::SetEnvironmentVariable($k, $Env[$k], "Process")
    }
    try {
        Start-Process -FilePath $FilePath -ArgumentList $ArgList -WorkingDirectory $WorkDir `
            -WindowStyle Hidden -RedirectStandardOutput "$WorkDir\$LogTag.out.log" `
            -RedirectStandardError "$WorkDir\$LogTag.err.log"
        Write-Host "[$Name] baslatildi: $FilePath $ArgList"
    } finally {
        foreach ($k in $Env.Keys) {
            if ($null -eq $saved[$k]) { [System.Environment]::SetEnvironmentVariable($k, $null, "Process") }
            else { [System.Environment]::SetEnvironmentVariable($k, $saved[$k], "Process") }
        }
    }
}

$litellmEnv = @{}
Get-Content "$ws\deploy\litellm\.env" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $litellmEnv[$Matches[1]] = $Matches[2] }
}

# 1) LiteLLM gateway :4000
Start-Service -Name "litellm-gateway" -FilePath "$ws\deploy\litellm\.venv\Scripts\litellm.exe" `
    -ArgList @("--config","config.yaml","--port","4000") -WorkDir "$ws\deploy\litellm" `
    -Env $litellmEnv -LogTag "gateway"

# 2) deer-flow backend :8001
$df = "$ws\cockpit\third_party\deer-flow\backend"
Start-Service -Name "deer-flow" -FilePath "$df\.venv\Scripts\python.exe" `
    -ArgList @("-m","uvicorn","app.gateway.app:app","--port","8001") -WorkDir $df `
    -Env @{
        DEER_FLOW_AUTH_DISABLED = "1"
        DEER_FLOW_CONFIG_PATH   = "$df\config.yaml"
        LITELLM_MASTER_KEY      = $litellmEnv["LITELLM_MASTER_KEY"]
    } -LogTag "gw"

# 3) agent-zero :5000
$az = "$ws\cockpit\third_party\agent-zero"
Start-Service -Name "agent-zero" -FilePath "$az\.venv\Scripts\python.exe" `
    -ArgList @("run_ui.py") -WorkDir $az -Env @{} -LogTag "az"

# 4) ElizaOS persona servisi :3000
Start-Service -Name "eliza" -FilePath "$ws\agent_core\.venv\Scripts\python.exe" `
    -ArgList @("$ws\cockpit\third_party\eliza_server.py") -WorkDir "$ws\cockpit\third_party" -Env @{} -LogTag "eliza"

# 5) agent_core orchestrator :5060
Start-Service -Name "agent_core" -FilePath "$ws\agent_core\.venv\Scripts\python.exe" `
    -ArgList @("agent_core.py") -WorkDir "$ws\agent_core" -Env @{} -LogTag "core"

Start-Sleep -Seconds 20
Write-Host "`n=== SERVIS DURUMU ==="
foreach ($port in @(4000, 8001, 5000, 3000, 5060)) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) { Write-Host "  port $port -> ACIK (PID $($c.OwningProcess))" }
    else { Write-Host "  port $port -> KAPALI" }
}


