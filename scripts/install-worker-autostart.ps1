param(
  [switch]$Remove
)

$ErrorActionPreference = "Stop"
$taskName = "ViralX Home Worker"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$runnerPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "run-worker.ps1"))

if (-not $runnerPath.StartsWith($projectRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Refusing to register a Worker outside the ViralX project directory."
}

if ($Remove) {
  $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed scheduled task: $taskName"
  } else {
    Write-Host "Scheduled task is already absent: $taskName"
  }
  exit 0
}

if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) {
  throw "Worker runner is missing: $runnerPath"
}

$powerShellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$action = New-ScheduledTaskAction `
  -Execute $powerShellPath `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runnerPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 5 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
  -UserId "$env:USERDOMAIN\$env:USERNAME" `
  -LogonType Interactive `
  -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal

Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
Write-Host "Registered scheduled task: $taskName"
Write-Host "ViralX Worker will start at the next Windows sign-in and restart after unexpected exits."
