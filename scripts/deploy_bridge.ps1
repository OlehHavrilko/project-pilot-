#Requires -Version 5.1
<#
.SYNOPSIS
  Deploy, start, stop or inspect the Pilot Windows bridge.

.DESCRIPTION
  Copies win_bridge from WSL to %LOCALAPPDATA%\pilot-bridge\app, creates a
  Windows Python 3.12 virtual environment, installs dependencies and starts the
  bridge as a hidden background process with a PID file.

  The process is launched through wscript.exe so that it does not stay a child
  of the WSL interop process (otherwise wsl.exe waits for it forever).

  The shared token is read from %LOCALAPPDATA%\pilot-bridge\token.txt or from
  the PILOT_BRIDGE_TOKEN environment variable. Never pass the token on the
  command line in normal use.
#>
param(
    [ValidateSet("deploy", "start", "stop", "status")]
    [string]$Action = "deploy",
    [string]$SourcePath = "\\wsl.localhost\Ubuntu-24-04\home\olehwsl\pilot\win_bridge",
    [string]$InstallDir = "$env:LOCALAPPDATA\pilot-bridge",
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8765,
    [string]$AudioDevice = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$AppDir = Join-Path $InstallDir "app"
$VenvDir = Join-Path $InstallDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$TokenFile = Join-Path $InstallDir "token.txt"
$PidFile = Join-Path $InstallDir "bridge.pid"
$LogDir = Join-Path $InstallDir "logs"
$StdoutLog = Join-Path $LogDir "bridge.out.log"
$StderrLog = Join-Path $LogDir "bridge.err.log"

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Find-WindowsPython {
    if ($PythonExe) {
        if (-not (Test-Path $PythonExe)) { throw "PythonExe not found: $PythonExe" }
        return (Resolve-Path $PythonExe).Path
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    try {
        $found = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { return $found.Trim() }
    } catch { }
    throw "Windows Python 3.12 not found. Install it or pass -PythonExe."
}

function Get-BridgeToken {
    $token = $env:PILOT_BRIDGE_TOKEN
    if (-not $token -and (Test-Path $TokenFile)) {
        $token = (Get-Content -Path $TokenFile -Raw).Trim()
    }
    if (-not $token) {
        throw "Bridge token is not set. Put it into $TokenFile or set PILOT_BRIDGE_TOKEN."
    }
    if (-not (Test-Path $TokenFile)) {
        Set-Content -Path $TokenFile -Value $token -NoNewline
    }
    return $token
}

function Get-BridgeProcess {
    if (-not (Test-Path $PidFile)) { return $null }
    $processId = (Get-Content -Path $PidFile -Raw).Trim()
    if (-not $processId) { return $null }
    try {
        return Get-Process -Id ([int]$processId) -ErrorAction Stop
    } catch {
        return $null
    }
}

function Test-BridgeHealth([int]$TimeoutSeconds = 2) {
    $token = (Get-Content -Path $TokenFile -Raw).Trim()
    $uri = "http://${ListenHost}:${Port}/health"
    try {
        return Invoke-RestMethod -Uri $uri -TimeoutSec $TimeoutSeconds -Headers @{
            "X-Pilot-Token" = $token
        }
    } catch {
        return $null
    }
}

function Stop-Bridge {
    if (Test-Path $PidFile) {
        $processId = (Get-Content -Path $PidFile -Raw).Trim()
        if ($processId) { Stop-Process -Id ([int]$processId) -Force -ErrorAction SilentlyContinue }
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    }
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    $runners = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*run_bridge.py*" }
    foreach ($runner in $runners) {
        Stop-Process -Id $runner.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 400
}

function Start-Bridge {
    if (-not (Test-Path $VenvPython)) {
        throw "venv is missing; run -Action deploy first"
    }
    Stop-Bridge
    Ensure-Directory $LogDir
    $vbs = Join-Path $InstallDir "start_hidden.vbs"
    $audioArg = ""
    $audioEnv = ""
    if ($AudioDevice) {
        $audioArg = " --audio-device """ + $AudioDevice + """"
        $audioEnv = 'sh.Environment("PROCESS")("PILOT_AUDIO_DEVICE") = "' + $AudioDevice + '"'
    }
    $vbsContent = @'
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
token = Trim(fso.OpenTextFile("{0}", 1).ReadAll)
sh.Environment("PROCESS")("PILOT_BRIDGE_TOKEN") = token
sh.Environment("PROCESS")("PILOT_BRIDGE_LOG") = "{1}"
{2}
sh.CurrentDirectory = "{3}"
sh.Run """{4}"" run_bridge.py --host {5} --port {6}{7}", 0, False
'@ -f $TokenFile, $StdoutLog, $audioEnv, $AppDir, $VenvPython, $ListenHost, $Port, $audioArg
    Set-Content -Path $vbs -Value $vbsContent -Encoding ASCII
    $wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
    Start-Process -FilePath $wscript -ArgumentList @($vbs) -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-BridgeHealth -TimeoutSeconds 1) { break }
    }
    if (-not (Test-BridgeHealth -TimeoutSeconds 3)) {
        $logTail = ""
        if (Test-Path $StdoutLog) { $logTail = (Get-Content -Path $StdoutLog -Tail 20) -join "`n" }
        throw "bridge did not start. log: $logTail"
    }
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) { throw "bridge is not listening on port $Port" }
    Set-Content -Path $PidFile -Value $connection.OwningProcess -NoNewline
    return [pscustomobject]@{ Id = $connection.OwningProcess }
}

function Copy-BridgeSources {
    if (-not (Test-Path $SourcePath)) {
        throw "source not found: $SourcePath (is WSL running and the path correct?)"
    }
    Ensure-Directory $AppDir
    $robocopy = Join-Path $env:SystemRoot "System32\robocopy.exe"
    & $robocopy $SourcePath $AppDir /E /XD __pycache__ .venv tests /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }
}

Ensure-Directory $InstallDir

switch ($Action) {
    "deploy" {
        $null = Get-BridgeToken
        Copy-BridgeSources
        if (-not (Test-Path $VenvPython)) {
            $python = Find-WindowsPython
            Write-Host "creating venv with $python"
            & $python -m venv $VenvDir
            if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
        }
        $ErrorActionPreference = "Continue"
        & $VenvPython -c "import fastapi, uvicorn, pywinauto, mss, sounddevice" 2>$null | Out-Null
        $dependenciesInstalled = ($LASTEXITCODE -eq 0)
        if (-not $dependenciesInstalled) {
            Write-Host "installing bridge dependencies (first run may take a few minutes)"
            & $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $AppDir "requirements.txt")
            if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
        }
        $ErrorActionPreference = "Stop"
        $process = Start-Bridge
        $health = Test-BridgeHealth -TimeoutSeconds 3
        Write-Output ([ordered]@{
            ok = $true
            action = "deploy"
            pid = $process.Id
            url = "http://${ListenHost}:${Port}"
            health = $health
        } | ConvertTo-Json -Compress)
        exit 0
    }
    "start" {
        $null = Get-BridgeToken
        $process = Start-Bridge
        Write-Output ([ordered]@{
            ok = $true
            action = "start"
            pid = $process.Id
            url = "http://${ListenHost}:${Port}"
        } | ConvertTo-Json -Compress)
        exit 0
    }
    "stop" {
        Stop-Bridge
        Write-Output ([ordered]@{ ok = $true; action = "stop" } | ConvertTo-Json -Compress)
        exit 0
    }
    "status" {
        $null = Get-BridgeToken
        $process = Get-BridgeProcess
        $health = $null
        if ($process) { $health = Test-BridgeHealth -TimeoutSeconds 2 }
        Write-Output ([ordered]@{
            ok = [bool]$process
            action = "status"
            pid = if ($process) { $process.Id } else { $null }
            running = [bool]$process
            health = $health
            token_file = $TokenFile
        } | ConvertTo-Json -Compress)
        exit 0
    }
}
