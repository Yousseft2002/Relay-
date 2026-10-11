<#
  Registers a Windows scheduled task that runs `relay tick` on a timer overnight.
  Works in Windows PowerShell 5.1 and PowerShell 7.

  Example:
    powershell -ExecutionPolicy Bypass -File .\night-shift.ps1 -RepoDir "C:\code\materialos"

  Remove it later with:
    Unregister-ScheduledTask -TaskName "Relay Night Shift" -Confirm:$false
#>
param(
    [Parameter(Mandatory = $true)][string]$RepoDir,
    [int]$EveryMinutes = 30,
    [string]$Start = "22:00",
    [int]$Hours = 9,
    [string]$TaskName = "Relay Night Shift"
)

$ErrorActionPreference = "Stop"

$config = Join-Path $RepoDir "relay.toml"
if (-not (Test-Path $config)) { throw "No relay.toml in $RepoDir" }

$stateDir = Join-Path $RepoDir ".relay\state"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$log = Join-Path $stateDir "night-shift.log"

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction Stop }

# cmd /c lets us append each tick's report to a log file.
$command = "`"$($py.Source)`" -m relay --config `"$config`" tick >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command" -WorkingDirectory $RepoDir

$trigger = New-ScheduledTaskTrigger -Daily -At $Start
$repeat = New-ScheduledTaskTrigger -Once -At $Start `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours $Hours)
$trigger.Repetition = $repeat.Repetition

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Runs relay tick every $EveryMinutes min from $Start for $Hours h" -Force | Out-Null

Write-Host "Registered '$TaskName': every $EveryMinutes min from $Start for $Hours hours."
Write-Host "Log: $log"
Write-Host "Pause anytime with:  py -m relay --config `"$config`" pause"
