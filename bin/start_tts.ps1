param([string]$Notebook = 'answers_tts.ipynb')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$ttsPython = Join-Path $projectRoot '.conda-tts\python.exe'
if (-not (Test-Path -LiteralPath $ttsPython)) { throw 'Run .\bin\setup_tts.ps1 first.' }
$notebookPath = if ([IO.Path]::IsPathRooted($Notebook)) { $Notebook } else { Join-Path $projectRoot ('notebooks\' + $Notebook) }
if (-not (Test-Path -LiteralPath $notebookPath)) { throw "Notebook not found: $notebookPath" }
& $ttsPython -m jupyterlab --ServerApp.root_dir=$projectRoot $notebookPath

