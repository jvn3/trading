# Register two Windows Task Scheduler tasks:
#
#  1. "JayTrading-Launcher"  -- runs at user logon; starts the scheduler via WSL.
#  2. "JayTrading-Watchdog"  -- runs every 5 min; restarts scheduler if dead.
#
# Run this script once from an Administrator PowerShell prompt:
#   powershell -ExecutionPolicy Bypass -File .\deploy\install_windows_tasks.ps1
#
# Uninstall:
#   powershell -ExecutionPolicy Bypass -File .\deploy\install_windows_tasks.ps1 -Uninstall

param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = "K:\trading"
$WslProjectRoot = "/mnt/k/trading"

$TaskLauncher = "JayTrading-Launcher"
$TaskWatchdog = "JayTrading-Watchdog"

if ($Uninstall) {
    foreach ($name in @($TaskLauncher, $TaskWatchdog)) {
        try {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
            Write-Host "Removed $name"
        } catch {
            Write-Host "Task $name was not registered"
        }
    }
    exit 0
}

# Task actions run wsl.exe DIRECTLY with plain arguments. The old version
# went through `cmd.exe /c ... && ...` — cmd does not honor single quotes, so
# it split the command at `&&` and the task always exited with code 2.
# Both scripts cd to the repo root themselves, so no `cd` is needed here.
$launcherAction = New-ScheduledTaskAction -Execute "wsl.exe" `
    -Argument "-- bash $WslProjectRoot/deploy/start_scheduler.sh"
$watchdogAction = New-ScheduledTaskAction -Execute "wsl.exe" `
    -Argument "-- bash $WslProjectRoot/deploy/watchdog.sh"

# --- Launcher: fires at user logon (OPTIONAL — needs an elevated prompt).
# The watchdog alone covers startup within 5 minutes; if this registration
# fails without admin rights we warn and continue rather than abort.
$launcherTrigger = New-ScheduledTaskTrigger -AtLogOn
$launcherSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask `
        -TaskName $TaskLauncher `
        -Action $launcherAction `
        -Trigger $launcherTrigger `
        -Settings $launcherSettings `
        -Description "Launch jay-trading APScheduler via WSL at user logon" `
        -Force -ErrorAction Stop | Out-Null
    Write-Host "Registered $TaskLauncher"
} catch {
    Write-Host "WARNING: could not register $TaskLauncher ($_)."
    Write-Host "         Logon triggers need an elevated prompt; the watchdog covers startup anyway."
}

# --- Watchdog: every 5 min, all day, every day ---
# History: the original version used a -Once trigger and then assigned
# .DaysOfWeek on it, which (a) threw (MSFT_TaskTimeTrigger has no DaysOfWeek)
# so the task was never registered, and (b) even without the throw, a -Once
# trigger's repetition window only spans its single start day. Result: the
# scheduler died 2026-05-13 and nothing restarted it for 53 days.
#
# Correct pattern: a -Daily trigger, with the repetition block grafted from a
# throwaway -Once trigger (New-ScheduledTaskTrigger -Daily does not accept
# -RepetitionInterval directly on Windows PowerShell 5.1). Running the check
# 24/7 is intentional — it is cheap, and the heartbeat check in watchdog.sh
# also catches hung-but-alive schedulers.
$watchdogTrigger = New-ScheduledTaskTrigger -Daily -At "00:02"
$repetitionSource = New-ScheduledTaskTrigger `
    -Once `
    -At "00:02" `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 55)
$watchdogTrigger.Repetition = $repetitionSource.Repetition
$watchdogSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3)

Register-ScheduledTask `
    -TaskName $TaskWatchdog `
    -Action $watchdogAction `
    -Trigger $watchdogTrigger `
    -Settings $watchdogSettings `
    -Description "Respawn jay-trading APScheduler if it dies" `
    -Force | Out-Null
Write-Host "Registered $TaskWatchdog"

Write-Host ""
Write-Host "Installed. The watchdog starts the scheduler within 5 minutes if dead."
Write-Host "To start it right now:"
Write-Host "  schtasks /run /tn $TaskWatchdog"
Write-Host ""
Write-Host "Verify:"
Write-Host "  Get-ScheduledTask JayTrading-*"
