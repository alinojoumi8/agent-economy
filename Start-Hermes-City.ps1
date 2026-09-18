param(
    [string]$RunId,
    [ValidateRange(1,30)][int]$Days = 3,
    [switch]$ViewOnly
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $RunId) {
    $active = Join-Path $PSScriptRoot 'data/control-plane/hermes-city.json'
    if (-not (Test-Path -LiteralPath $active)) { throw 'Choose a saved world with -RunId.' }
    $RunId = (Get-Content -LiteralPath $active -Raw | ConvertFrom-Json).run_id
}
if ($RunId -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid run ID.' }
$database = Join-Path $PSScriptRoot "data/runs/$RunId.db"
if (-not (Test-Path -LiteralPath $database)) { throw "Saved world missing: $database. Refusing to start fresh." }
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$cohort = Join-Path $PSScriptRoot "data/control-plane/hermes-cohort/$RunId"
New-Item -ItemType Directory -Path $cohort -Force | Out-Null
$base = 'http://127.0.0.1:8000'
$state = $null
try { $state = Invoke-RestMethod "$base/api/run/status" -TimeoutSec 3 } catch {}
if (-not $state) {
    $server = Start-Process -FilePath $python -ArgumentList @('run.py','--config','runs/hermes-local.yaml','--resume',$RunId,'--serve','--host','127.0.0.1','--port','8000') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$cohort/server.out.log" -RedirectStandardError "$cohort/server.err.log" -PassThru
    @{pid=$server.Id; run_id=$RunId} | ConvertTo-Json | Set-Content -LiteralPath "$cohort/server-process.json"
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        try { $state = Invoke-RestMethod "$base/api/run/status" -TimeoutSec 3; break } catch {}
        if ($server.HasExited) { throw "Server failed. Read $cohort/server.err.log" }
    }
}
if (-not $state -or $state.run_id -ne $RunId) { throw 'Port 8000 is not serving the requested saved world.' }
@{run_id=$RunId} | ConvertTo-Json | Set-Content -LiteralPath "$PSScriptRoot/data/control-plane/hermes-city.json"
if (-not $ViewOnly) {
    if (-not (Test-Path -LiteralPath "$cohort/manifest.json")) { throw 'Run scripts/hermes_citizens.py --setup first.' }
    if (Test-Path -LiteralPath "$cohort/operator-process.json") {
        $saved = Get-Content -LiteralPath "$cohort/operator-process.json" -Raw | ConvertFrom-Json
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$($saved.pid)" -ErrorAction SilentlyContinue
        if ($existing -and $existing.CommandLine -like "*hermes_citizens.py*--run-id $RunId*") {
            Write-Output 'The citizens are already working.'
            Write-Output "$base/runs/$RunId/people"
            return
        }
    }
    if (Test-Path -LiteralPath "$cohort/STOP") { Remove-Item -LiteralPath "$cohort/STOP" }
    $operator = Start-Process -FilePath $python -ArgumentList @('scripts/hermes_citizens.py','--run-id',$RunId,'--days',$Days) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$cohort/operator.out.log" -RedirectStandardError "$cohort/operator.err.log" -PassThru
    @{pid=$operator.Id; run_id=$RunId} | ConvertTo-Json | Set-Content -LiteralPath "$cohort/operator-process.json"
    Write-Output "Resumed $RunId at day $($state.tick). Hermes will work for up to $Days more days."
} else { Write-Output "Opened saved world $RunId at day $($state.tick)." }
Write-Output "$base/runs/$RunId/people"
