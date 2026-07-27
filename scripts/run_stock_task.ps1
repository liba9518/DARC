param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("binance-contract", "binance-contract-long", "binance-contract-short")]
    [string]$Mode,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogDirectory = Join-Path $ProjectRoot "logs\scheduled"
$LogFile = Join-Path $LogDirectory "$Mode.log"

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
Set-Location -LiteralPath $ProjectRoot

$side = switch ($Mode) {
    "binance-contract" { "both" }
    "binance-contract-long" { "long" }
    "binance-contract-short" { "short" }
}

$arguments = @(
    "scripts\push_binance_long_signals.py",
    "--side",
    $side,
    "--no-push-empty"
)
if ($DryRun) {
    $arguments += "--dry-run"
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] START $Mode" | Out-File -FilePath $LogFile -Append -Encoding utf8

try {
    & $Python @arguments 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw "Python exited with code $LASTEXITCODE"
    }
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] SUCCESS $Mode" | Out-File -FilePath $LogFile -Append -Encoding utf8
}
catch {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] FAILED $Mode - $($_.Exception.Message)" | Out-File -FilePath $LogFile -Append -Encoding utf8
    exit 1
}
