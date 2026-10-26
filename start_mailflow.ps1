$ErrorActionPreference = "Stop"

$pythonCommand = Get-Command python -ErrorAction Stop
$pythonPath = $pythonCommand.Source
$projectDirectory = $PSScriptRoot

$webProcess = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList @("app.py") `
    -WorkingDirectory $projectDirectory `
    -PassThru

try {
    $schedulerProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @("app.py", "--scheduler") `
        -WorkingDirectory $projectDirectory `
        -PassThru
}
catch {
    Stop-Process -Id $webProcess.Id -ErrorAction SilentlyContinue
    throw
}

Write-Host "MailFlow web app started (PID $($webProcess.Id))."
Write-Host "MailFlow scheduler started (PID $($schedulerProcess.Id))."
Write-Host "Keep both processes running. Stop them with:"
Write-Host "  Stop-Process -Id $($webProcess.Id), $($schedulerProcess.Id)"
