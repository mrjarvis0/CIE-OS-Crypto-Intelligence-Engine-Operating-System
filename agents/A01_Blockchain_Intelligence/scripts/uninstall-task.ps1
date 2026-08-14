<#
.SYNOPSIS
    Remove A01's scheduled ingest.

.DESCRIPTION
    Unregisters the task and deletes the generated wrapper.

    **Logs and the database are left alone.** Removing a schedule is a decision
    about whether A01 keeps *collecting*; deleting what it already collected is
    a different decision, and conflating them means an operator pausing a job
    loses their history. Pass -Purge to remove the log as well; the database is
    never touched by this script.
#>

[CmdletBinding()]
param(
    [string] $TaskName = "A01 Blockchain Intelligence Ingest",
    [switch] $Purge
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentDir  = (Resolve-Path (Join-Path $scriptDir "..")).Path
$wrapper   = Join-Path $scriptDir "_scheduled-ingest.ps1"
$logFile   = Join-Path $agentDir "logs\ingest.log"

Write-Host ""

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered: $TaskName" -ForegroundColor Green
} else {
    # Not an error. Running this twice, or on a machine where it was never
    # installed, should be quiet rather than alarming.
    Write-Host "No task named '$TaskName' was registered." -ForegroundColor Yellow
}

if (Test-Path $wrapper) {
    Remove-Item $wrapper -Force
    Write-Host "Removed the generated wrapper."
}

if ($Purge) {
    foreach ($path in @($logFile, "$logFile.1")) {
        if (Test-Path $path) {
            Remove-Item $path -Force
            Write-Host "Removed $path"
        }
    }
} elseif (Test-Path $logFile) {
    Write-Host ""
    Write-Host "Kept the log at $logFile (pass -Purge to remove it)."
}

Write-Host ""
Write-Host "The database was not touched. Captured history survives removing"
Write-Host "the schedule, because pausing collection and discarding what was"
Write-Host "already collected are different decisions."
Write-Host ""
