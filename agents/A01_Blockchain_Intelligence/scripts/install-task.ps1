<#
.SYNOPSIS
    Register a recurring background ingest for A01.

.DESCRIPTION
    Creates a Windows scheduled task that captures recent blocks on an
    interval, so storage keeps up with the chain without anyone running a
    command.

    Three decisions worth knowing about:

    * **Runs only when you are logged on.** A task that runs regardless would
      need stored credentials, and A01 does not need them: it reads public
      chains and writes to a local file. Asking for a password to do that
      would be a worse trade than the convenience is worth.

    * **Bounded logging.** A job firing every ten minutes forever produces an
      unbounded log. The wrapper rotates it, because the failure mode of a
      forgotten scheduled task is a full disk months later.

    * **Ingest is bounded per run.** `-Blocks` caps the work. Falling behind is
      recoverable — the next run resumes from the checkpoint — whereas an
      unbounded catch-up is indistinguishable from a hang.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install-task.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install-task.ps1 -Minutes 30 -Chain polygon
#>

[CmdletBinding()]
param(
    [int]    $Minutes  = 10,
    [string] $Chain    = "ethereum",
    [int]    $Blocks   = 25,
    [string] $Database = "",
    [string] $TaskName = "A01 Blockchain Intelligence Ingest",
    [switch] $NoTokens
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentDir  = (Resolve-Path (Join-Path $scriptDir "..")).Path

if (-not $Database) { $Database = Join-Path $agentDir "data\a01.db" }

Write-Host ""
Write-Host "A01 scheduled ingest" -ForegroundColor Cyan
Write-Host "  agent    : $agentDir"
Write-Host "  database : $Database"
Write-Host "  interval : every $Minutes minute(s)"
Write-Host "  chain    : $Chain ($Blocks blocks per run)"
Write-Host ""

# -- Resolve the interpreter -------------------------------------------------
# Same order as a01.bat, and it has to be: a task registered with a different
# interpreter than the one you tested with fails silently every ten minutes.
# Resolved now and baked into the task, because a scheduled task runs with a
# different PATH than an interactive shell.

function Get-DotenvValue {
    <#
        Read one key out of the nearest .env, mirroring config/dotenv.py.

        A venv is not always an ancestor of the agent -- this checkout's lives
        in a separate tree entirely -- so an upward search for .venv cannot
        find it. The same file that holds the provider keys names the
        interpreter.
    #>
    param([string] $Name, [string] $From)

    $directory = $From
    for ($level = 0; $level -le 3 -and $directory; $level++) {
        foreach ($file in @(".env.local", ".env")) {
            $path = Join-Path $directory $file
            if (Test-Path $path) {
                foreach ($line in Get-Content $path) {
                    $trimmed = $line.Trim()
                    if ($trimmed -match "^\s*#" -or $trimmed -notmatch "=") { continue }
                    $key, $value = $trimmed -split "=", 2
                    if ($key.Trim() -eq $Name) {
                        return $value.Trim().Trim('"').Trim("'")
                    }
                }
            }
        }
        $directory = Split-Path -Parent $directory
    }
    return $null
}

$python = $null
foreach ($candidate in @(
    $env:A01_PYTHON,
    (Get-DotenvValue -Name "A01_PYTHON" -From $agentDir),
    (Join-Path $agentDir ".venv\Scripts\python.exe"),
    (Join-Path $agentDir "..\.venv\Scripts\python.exe"),
    (Join-Path $agentDir "..\..\.venv\Scripts\python.exe"),
    (Join-Path $agentDir "..\..\..\.venv\Scripts\python.exe")
)) {
    if ($candidate -and (Test-Path $candidate)) {
        $python = (Resolve-Path $candidate).Path
        break
    }
}

if (-not $python) {
    Write-Error @"
No Python interpreter found.

Looked for A01_PYTHON in the environment, then in a .env beside the agent or
up to three levels above it, then for a .venv in those same directories.

Set it in the .env that already holds your provider keys:

    A01_PYTHON=C:\path\to\python.exe

or export it for this session:

    `$env:A01_PYTHON = 'C:\path\to\python.exe'
"@
    exit 1
}
Write-Host "  python   : $python"

# -- Verify before scheduling ------------------------------------------------
# Registering a task that has never worked produces silent failures every ten
# minutes. One run now is cheaper than discovering that from an empty database.
Write-Host ""
Write-Host "Verifying the agent runs before scheduling it..." -ForegroundColor Yellow
Push-Location $agentDir
try {
    & $python -m cli doctor | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "doctor failed; fix that before scheduling. Run: `"$python`" -m cli doctor"
        exit 1
    }
} finally {
    Pop-Location
}
Write-Host "  doctor   : ok" -ForegroundColor Green

# -- The wrapper the task actually runs --------------------------------------
$logDir     = Join-Path $agentDir "logs"
$logFile    = Join-Path $logDir "ingest.log"
$wrapper    = Join-Path $scriptDir "_scheduled-ingest.ps1"
$tokensFlag = if ($NoTokens) { "" } else { "--tokens" }

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$wrapperBody = @"
# Generated by install-task.ps1. Edit install-task.ps1 and re-run instead.
`$ErrorActionPreference = 'Continue'
Set-Location '$agentDir'

# Rotate before writing. A job on a ten-minute timer runs ~52,000 times a
# year, and an unbounded log is how a forgotten task fills a disk.
`$log = '$logFile'
if ((Test-Path `$log) -and ((Get-Item `$log).Length -gt 5MB)) {
    Move-Item `$log "`$log.1" -Force
}

"[`$(Get-Date -Format o)] ingest start" | Add-Content `$log
& '$python' -m cli ingest --db '$Database' --chain '$Chain' --blocks $Blocks $tokensFlag 2>&1 |
    Add-Content `$log
"[`$(Get-Date -Format o)] ingest exit `$LASTEXITCODE" | Add-Content `$log
"@

Set-Content -Path $wrapper -Value $wrapperBody -Encoding UTF8
Write-Host "  wrapper  : $wrapper"
Write-Host "  log      : $logFile (rotates at 5 MB)"

# -- Register ----------------------------------------------------------------
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapper`"" `
    -WorkingDirectory $agentDir

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $Minutes)

# StopIfGoingOnBatteries off: a laptop on battery is still a laptop that should
# keep its chain data current, and the job is a few HTTP calls.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host ""
    Write-Host "Replacing the existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Capture recent blocks into A01's system of record. Read-only: holds no keys, signs nothing." `
    | Out-Null

Write-Host ""
Write-Host "Registered." -ForegroundColor Green
Write-Host ""
Write-Host "  Run it now      : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Watch the log   : Get-Content '$logFile' -Wait -Tail 20"
Write-Host "  Remove it       : powershell -ExecutionPolicy Bypass -File `"$scriptDir\uninstall-task.ps1`""
Write-Host ""
Write-Host "  Note: runs only while you are logged on. Running regardless would"
Write-Host "  need stored credentials, which a read-only agent should not ask for."
Write-Host ""
