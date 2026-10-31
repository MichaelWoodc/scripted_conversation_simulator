$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$requests = [Console]::In.ReadToEnd() | ConvertFrom-Json
$questionSynth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $questionSynth.SelectVoice('Microsoft Zira Desktop')
    $questionSynth.Rate = 0
    $done = 0
    foreach ($request in $requests) {
        $partial = $request.path + '.partial.wav'
        $questionSynth.SetOutputToWaveFile($partial)
        $questionSynth.Speak($request.text)
        $questionSynth.SetOutputToNull()
        Move-Item -LiteralPath $partial -Destination $request.path -Force
        $done++
        Write-Output "Question audio $done/$($requests.Count)"
    }
} finally {
    $questionSynth.Dispose()
}
