param(
  [string]$TaskNamePrefix = "WorldCupFeishu",
  [string]$PowerShellExe = "powershell.exe"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

$taskSpecs = @(
  @{ Name = "$TaskNamePrefix-0000"; Time = "00:00" },
  @{ Name = "$TaskNamePrefix-0800"; Time = "08:00" },
  @{ Name = "$TaskNamePrefix-1600"; Time = "16:00" }
)

foreach ($task in $taskSpecs) {
  $command = "Set-Location -LiteralPath '$repoRoot'; npm.cmd run feishu:auto-push"
  $action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$command`""
  $trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($task.Time, "HH:mm", $null))
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew

  Register-ScheduledTask `
    -TaskName $task.Name `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Auto push World Cup upcoming strategy at Beijing batch $($task.Time)" `
    -Force | Out-Null

  Write-Host "Registered $($task.Name) at $($task.Time)"
}

Write-Host "All three Beijing batch tasks are registered."
