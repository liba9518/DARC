param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("cn-preopen", "us-preopen", "cn-review", "us-review", "cn-intraday", "us-intraday")]
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

$arguments = switch ($Mode) {
    "cn-preopen" { @("scripts\push_daily_strategy_cards.py", "--market", "cn") }
    "us-preopen" { @("scripts\push_daily_strategy_cards.py", "--market", "us") }
    "cn-review" { @("scripts\push_post_close_review.py", "--market", "cn") }
    "us-review" { @("scripts\push_post_close_review.py", "--market", "us") }
    "cn-intraday" { @("scripts\push_intraday_monitor.py", "--market", "cn") }
    "us-intraday" { @("scripts\push_intraday_monitor.py", "--market", "us") }
}
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
