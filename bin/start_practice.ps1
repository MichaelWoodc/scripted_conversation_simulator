param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$practicePython = Join-Path $projectRoot '.conda-tts\python.exe'
if (-not (Test-Path -LiteralPath $practicePython)) { $practicePython = (Get-Command python).Source }
& $practicePython -u (Join-Path $PSScriptRoot 'server.py') --port $Port
