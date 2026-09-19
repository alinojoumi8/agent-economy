param([string]$RunId)
$ErrorActionPreference = 'Stop'
if (-not $RunId) {
    $RunId = (Get-Content -LiteralPath "$PSScriptRoot/data/control-plane/hermes-city.json" -Raw | ConvertFrom-Json).run_id
}
if ($RunId -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid run ID.' }
$cohort = Join-Path $PSScriptRoot "data/control-plane/hermes-cohort/$RunId"
Set-Content -LiteralPath "$cohort/STOP" -Value 'Stop requested by local operator'
# Finish any in-flight agent call, retaining queued actions and sessions.
if (Test-Path -LiteralPath "$cohort/operator-process.json") {
    $saved = Get-Content -LiteralPath "$cohort/operator-process.json" -Raw | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($saved.pid)" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -like "*hermes_citizens.py*--run-id $RunId*") {
        Write-Output 'Waiting for the current citizen calls to save...'
        Wait-Process -Id $saved.pid -Timeout 300 -ErrorAction Stop
    }
}
$state = Invoke-RestMethod 'http://127.0.0.1:8000/api/run/status' -TimeoutSec 5
if ($state.run_id -ne $RunId) { throw 'A different world is running; it was left untouched.' }
if ($state.running -or $state.active_tick) { throw 'The world is mid-tick. Pause it at a completed day before closing the server.' }
if (Test-Path -LiteralPath "$cohort/server-process.json") {
    $saved = Get-Content -LiteralPath "$cohort/server-process.json" -Raw | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($saved.pid)" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -like "*run.py*--resume $RunId*") {
        Stop-Process -Id $saved.pid
        Write-Output "Saved city $RunId stopped at day $($state.tick). Start-Hermes-City.ps1 resumes it."
    } else { throw 'The saved server PID is no longer this city; no unrelated process was stopped.' }
} else { Write-Output 'Citizens are stopped. Server was started separately and remains available for viewing.' }
