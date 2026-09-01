param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
$resolvedRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
$venvPython = [IO.Path]::GetFullPath((Join-Path $resolvedRoot "venv\Scripts\python.exe"))
$processes = @(Get-CimInstance Win32_Process)
$byPid = @{}
foreach ($process in $processes) {
  $byPid[[int]$process.ProcessId] = $process
}

$workers = @(
  foreach ($process in $processes) {
    $commandLine = [string]$process.CommandLine
    if ($commandLine -notmatch '(?i)(^|[\\/\s"])worker_server\.py(["\s]|$)') {
      continue
    }

    $executable = [string]$process.ExecutablePath
    $parent = $byPid[[int]$process.ParentProcessId]
    $parentExecutable = if ($parent) { [string]$parent.ExecutablePath } else { "" }
    $ownedByProject = $executable -ieq $venvPython -or $parentExecutable -ieq $venvPython
    if ($ownedByProject) {
      $process
    }
  }
)

# Stop the base-interpreter child first, then its venv launcher. This prevents a
# stale launcher from keeping an old Worker alive after a routine restart.
$workers |
  Sort-Object @{ Expression = { if ([string]$_.ExecutablePath -ieq $venvPython) { 1 } else { 0 } } } |
  ForEach-Object {
    Write-Host "Replacing existing ViralX Worker process $($_.ProcessId)..."
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

