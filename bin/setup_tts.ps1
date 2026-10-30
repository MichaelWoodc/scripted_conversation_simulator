param([switch]$SkipModelDownload, [switch]$TextOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$ttsEnv = Join-Path $projectRoot '.conda-tts'
$ttsPython = Join-Path $ttsEnv 'python.exe'
function Assert-Success([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}
if (-not (Test-Path -LiteralPath $ttsPython)) {
    if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
        throw 'Run this script from Anaconda PowerShell Prompt, where conda is available.'
    }
    conda create --prefix $ttsEnv python=3.11 pip -y --override-channels -c conda-forge
    Assert-Success 'Environment creation'
}
$torchIndex = if ($TextOnly) { 'https://download.pytorch.org/whl/cpu' } else { 'https://download.pytorch.org/whl/cu126' }
& $ttsPython -m pip install torch==2.7.1 --index-url $torchIndex
Assert-Success 'PyTorch installation'
& $ttsPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-tts.txt')
Assert-Success 'TTS and Jupyter installation'
if (-not $TextOnly) {
    & $ttsPython -m spacy download en_core_web_sm
    Assert-Success 'English language model installation'
}
& $ttsPython -m ipykernel install --user --name redata-tts --display-name 'Answers TTS (CUDA)'
Assert-Success 'Jupyter kernel registration'
if (-not $TextOnly) {
    & $ttsPython -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; print('CUDA ready:', torch.cuda.get_device_name(0)); print('PyTorch:', torch.__version__, 'runtime:', torch.version.cuda); print((torch.ones(16, device='cuda') * 2).sum().item())"
    Assert-Success 'CUDA verification'
}
if (-not $SkipModelDownload -and -not $TextOnly) {
    & $ttsPython (Join-Path $PSScriptRoot 'answer_tts.py') --warmup
    Assert-Success 'Model download and voice warmup'
}
Write-Host "Ready. Start the notebook with .\bin\start_tts.ps1"
if ($TextOnly) { Write-Host 'Text-only mode: edits and exports work without a GPU. Audio previews require CUDA.' }

