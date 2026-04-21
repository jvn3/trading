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

# Command that launches the scheduler in the background via WSL's default distro.
$LaunchCommand = "wsl.exe -- bash -lc 'cd $WslProjectRoot && bash deploy/start_scheduler.sh &'"
$WatchdogCommand = "wsl.exe -- bash -lc 'cd $WslProjectRoot && bash deploy/watchdog.sh'"

# --- Launcher: fires at user logon ---
$launcherAction  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $LaunchCommand"
$launcherTrigger = New-ScheduledTaskTrigger -AtLogOn
$launcherSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskLauncher `
    -Action $launcherAction `
    -Trigger $launcherTrigger `
    -Settings $launcherSettings `
    -Description "Launch jay-trading APScheduler via WSL at user logon" `
    -Force | Out-Null
Write-Host "Registered $TaskLauncher"

# --- Watchdog: every 5 min between 08:00 and 17:00 local time, Mon-Fri ---
# (Scheduler process lives outside those hours too for overnight jobs, but we
# only need active restarts during market+ingest hours.)
$watchdogAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $WatchdogCommand"
$watchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At ((Get-Date).Date.AddHours(8)) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Hours 9)
$watchdogTrigger.DaysOfWeek = "Monday, Tuesday, Wednesday, Thursday, Friday"
$watchdogSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

Register-ScheduledTask `
    -TaskName $TaskWatchdog `
    -Action $watchdogAction `
    -Trigger $watchdogTrigger `
    -Settings $watchdogSettings `
    -Description "Respawn jay-trading APScheduler if it dies" `
    -Force | Out-Null
Write-Host "Registered $TaskWatchdog"

Write-Host ""
Write-Host "Installed. The launcher will start the scheduler next time you log in."
Write-Host "To start it now without logging out:"
Write-Host "  $LaunchCommand"
Write-Host ""
Write-Host "Verify:"
Write-Host "  Get-ScheduledTask JayTrading-*"
