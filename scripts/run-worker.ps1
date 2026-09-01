param()

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$workerPath = [IO.Path]::GetFullPath((Join-Path $projectRoot "worker_server.py"))
$pythonPath = [IO.Path]::GetFullPath((Join-Path $projectRoot "venv\Scripts\python.exe"))
$stopperPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "stop-viralx-worker.ps1"))

foreach ($path in @($workerPath, $pythonPath, $stopperPath)) {
  if (-not $path.StartsWith($projectRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to start ViralX Worker outside the project directory."
  }
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Required Worker file is missing: $path"
  }
}

$env:VIRALX_ALLOWED_ORIGINS = "https://viralx.metrolabs.mobi"
$env:VIRALX_WORKER_HOST = "127.0.0.1"
$env:VIRALX_WORKER_PORT = "8000"
$env:VIRALX_MAX_CONCURRENT = "1"
$env:VIRALX_RATE_LIMIT_ANALYSES = "6"
$env:VIRALX_RATE_WINDOW_SECONDS = "3600"
$env:VIRALX_RETENTION_HOURS = "24"

& $stopperPath -ProjectRoot $projectRoot
Start-Sleep -Seconds 1
Set-Location -LiteralPath $projectRoot
& $pythonPath $workerPath
exit $LASTEXITCODE
