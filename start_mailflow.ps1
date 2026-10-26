$ErrorActionPreference = "Stop"

$projectDirectory = $PSScriptRoot
$venvPython = Join-Path $projectDirectory ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $pythonPath = $venvPython
}
else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = $pythonCommand.Source
}

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

    Start-Sleep -Seconds 2
    $webProcess.Refresh()
    $schedulerProcess.Refresh()
    if ($webProcess.HasExited) {
        throw "The web app exited during startup (exit code $($webProcess.ExitCode))."
    }
    if ($schedulerProcess.HasExited) {
        throw "The scheduler exited during startup (exit code $($schedulerProcess.ExitCode))."
    }
}
catch {
    Stop-Process -Id $webProcess.Id -ErrorAction SilentlyContinue
    if ($schedulerProcess) {
        Stop-Process -Id $schedulerProcess.Id -ErrorAction SilentlyContinue
    }
    throw
}

Write-Host "MailFlow web app started (PID $($webProcess.Id))."
Write-Host "MailFlow scheduler started (PID $($schedulerProcess.Id))."
Write-Host "Keep both processes running. Stop them with:"
Write-Host "  Stop-Process -Id $($webProcess.Id), $($schedulerProcess.Id)"
