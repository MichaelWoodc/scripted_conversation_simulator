# Start a detached job; check dist/media/<edition>/generation.log and generation_status.json.
param([string]$Voice = 'af_heart', [double]$Speed = 1.0, [switch]$EmphasizedPunctuation)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$ttsPython = Join-Path $projectRoot '.conda-tts\python.exe'
if (-not (Test-Path -LiteralPath $ttsPython)) { throw 'Run .\bin\setup_tts.ps1 first.' }
if ($Voice -notmatch '^[ab][fm]_[a-z]+$') { throw 'Choose a voice ID from the notebook.' }
if ($Speed -lt 0.7 -or $Speed -gt 1.3) { throw 'Speed must be between 0.7 and 1.3.' }
$folderName = if ($EmphasizedPunctuation) { 'edited' } else { 'original' }
$outputFolder = Join-Path $projectRoot ('dist\media\' + $folderName)
New-Item -ItemType Directory -Path $outputFolder -Force | Out-Null
$pidFile = Join-Path $outputFolder 'generation.pid'
if (Test-Path -LiteralPath $pidFile) {
    $existingPid = [int](Get-Content -LiteralPath $pidFile)
    $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$existingPid"
    if ($existingProcess -and $existingProcess.CommandLine -match 'run_generation.py') {
        throw "Generation is already running (PID $existingPid)."
    }
}
$speedArgument = $Speed.ToString('0.00', [Globalization.CultureInfo]::InvariantCulture)
$runner = Join-Path $PSScriptRoot 'run_generation.py'
$jobArguments = @('-u', ('"' + $runner + '"'), '--voice', $Voice, '--speed', $speedArgument,
                  '--output', ('"' + $outputFolder + '"'))
if ($EmphasizedPunctuation) { $jobArguments += '--emphasized-punctuation' }
$job = Start-Process -FilePath $ttsPython -ArgumentList $jobArguments `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $outputFolder 'generation.log') `
    -RedirectStandardError (Join-Path $outputFolder 'generation-errors.log')
Set-Content -LiteralPath $pidFile -Value $job.Id
Write-Host "Generation started in the background (PID $($job.Id))."
Write-Host "Progress: $outputFolder\generation.log"
Write-Host "Status:   $outputFolder\generation_status.json"
