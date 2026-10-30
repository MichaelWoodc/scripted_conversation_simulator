$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start_tts.ps1') -Notebook 'answer_review.ipynb'
