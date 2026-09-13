<#
.SYNOPSIS
    Schedules the Automated Market Data Pipeline to run daily using Windows Task Scheduler.
.DESCRIPTION
    Creates a Scheduled Task named 'AutomatedMarketDataPipeline' that triggers main.py every day at 6:00 PM.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
#>

$TaskName = "AutomatedMarketDataPipeline"
$PythonPath = (Get-Command python).Source
$ScriptDir = Split-Path -Parent $PSScriptRoot
$MainScript = Join-Path $ScriptDir "main.py"
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$MainScript`"" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -Daily -At 6:00PM
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Write-Host "Creating Windows Scheduled Task: $TaskName" -ForegroundColor Cyan
Write-Host "Trigger: Daily at 6:00 PM"
Write-Host "Target: $PythonPath $MainScript"

# Register or update task
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Daily Automated Financial ETL Pipeline" -Force

Write-Host "Task '$TaskName' registered successfully!" -ForegroundColor Green
