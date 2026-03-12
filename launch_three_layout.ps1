param(
    [string]$RepoPath = "",
    [int]$DefaultPingMs = 0,
    [double]$DefaultPacketLossPercent = 0,
    [int]$Debug1PingMs = 0,
    [double]$Debug1PacketLossPercent = 0,
    [int]$Debug2PingMs = 0,
    [double]$Debug2PacketLossPercent = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoPath) {
    $RepoPath = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$appPath = Join-Path $RepoPath "src\app.py"
if (-not (Test-Path -LiteralPath $appPath)) {
    throw "Could not find app entrypoint: $appPath"
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonArgsPrefix = @()
if ($null -eq $pythonCommand) {
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $pyCommand) {
        throw "Python launcher not found. Install python or py in PATH."
    }
    Write-Host "python not found; using py -3" -ForegroundColor Yellow
    $pythonExe = $pyCommand.Source
    $pythonArgsPrefix = @("-3")
}
else {
    $pythonExe = $pythonCommand.Source
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class NativeWin {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    public const int SW_RESTORE = 9;
}
"@

function Start-DmtInstance {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$Profile = "",
        [hashtable]$ExtraEnv = @{},
        [string]$LogDir = ""
    )

    $oldProfile = $env:DMT_SAVE_PROFILE
    $envBackup = @{}
    foreach ($key in $ExtraEnv.Keys) {
        $envBackup[$key] = [Environment]::GetEnvironmentVariable([string]$key, "Process")
    }

    if ($Profile) {
        $env:DMT_SAVE_PROFILE = $Profile
        Write-Host "Launching $Label with DMT_SAVE_PROFILE=$Profile"
    }
    else {
        Remove-Item Env:\DMT_SAVE_PROFILE -ErrorAction SilentlyContinue
        Write-Host "Launching $Label with default profile"
    }

    $args = @()
    $args += $pythonArgsPrefix
    $args += "src/app.py"

    foreach ($key in $ExtraEnv.Keys) {
        $value = [string]$ExtraEnv[$key]
        [Environment]::SetEnvironmentVariable([string]$key, $value, "Process")
        Write-Host "  env $key=$value"
    }

    $timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss_fff")
    $stdoutPath = ""
    $stderrPath = ""
    if ($LogDir) {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        $stdoutPath = Join-Path $LogDir "$($Label)_$timestamp.stdout.log"
        $stderrPath = Join-Path $LogDir "$($Label)_$timestamp.stderr.log"
    }

    $process = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList $args `
        -WorkingDirectory $RepoPath `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    foreach ($key in $ExtraEnv.Keys) {
        [Environment]::SetEnvironmentVariable([string]$key, $envBackup[$key], "Process")
    }

    if ($null -ne $oldProfile) {
        $env:DMT_SAVE_PROFILE = $oldProfile
    }
    else {
        Remove-Item Env:\DMT_SAVE_PROFILE -ErrorAction SilentlyContinue
    }

    if ($stdoutPath -or $stderrPath) {
        Write-Host "  logs: stdout=$stdoutPath"
        Write-Host "        stderr=$stderrPath"
    }

    return $process
}

function New-InstanceEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$RunId,
        [int]$PingMs = 0,
        [double]$PacketLossPercent = 0
    )

    if ($PingMs -lt 0) {
        throw "Ping must be >= 0 for $Label."
    }
    if ($PacketLossPercent -lt 0 -or $PacketLossPercent -gt 100) {
        throw "Packet loss percent must be between 0 and 100 for $Label."
    }

    $env = @{
        DMT_ONLINE_DEBUG_LOG = "1"
        DMT_ONLINE_DEBUG_LABEL = $Label
        DMT_ONLINE_DEBUG_RUN = $RunId
        DMT_ONLINE_DEBUG_LOG_DIR = $onlineSyncLogDir
    }
    if ($PingMs -gt 0) {
        $env["DMT_ONLINE_SIMULATED_PING_MS"] = [string]$PingMs
    }
    if ($PacketLossPercent -gt 0) {
        $env["DMT_ONLINE_SIMULATED_PACKET_LOSS_PERCENT"] = [string]$PacketLossPercent
    }
    return $env
}

function Wait-ForMainWindow {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            throw "Process exited before creating a window: PID $($Process.Id)"
        }
        $Process.Refresh()
        if ($Process.MainWindowHandle -ne 0) {
            return $Process.MainWindowHandle
        }
        Start-Sleep -Milliseconds 200
    }

    throw "Timed out waiting for window from PID $($Process.Id)"
}

$launcherLogDir = Join-Path $RepoPath "debug\launcher_logs"
$onlineSyncLogDir = Join-Path $RepoPath "debug\online_sync_logs"
$runId = (Get-Date).ToString("yyyyMMdd_HHmmss")

$defaultProcess = Start-DmtInstance `
    -Label "Default" `
    -LogDir $launcherLogDir `
    -ExtraEnv (New-InstanceEnv -Label "Default" -RunId $runId -PingMs $DefaultPingMs -PacketLossPercent $DefaultPacketLossPercent)
Start-Sleep -Milliseconds 450
$debugTopProcess = Start-DmtInstance `
    -Label "DebugTopLeft" `
    -Profile "DEBUG1" `
    -LogDir $launcherLogDir `
    -ExtraEnv (New-InstanceEnv -Label "DebugTopLeft" -RunId $runId -PingMs $Debug1PingMs -PacketLossPercent $Debug1PacketLossPercent)
Start-Sleep -Milliseconds 450
$debugBottomProcess = Start-DmtInstance `
    -Label "DebugBottomLeft" `
    -Profile "DEBUG2" `
    -LogDir $launcherLogDir `
    -ExtraEnv (New-InstanceEnv -Label "DebugBottomLeft" -RunId $runId -PingMs $Debug2PingMs -PacketLossPercent $Debug2PacketLossPercent)

$workArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$halfWidth = [int][Math]::Floor($workArea.Width / 2)
$halfHeight = [int][Math]::Floor($workArea.Height / 2)

$layouts = @(
    @{
        Name = "Default"
        Process = $defaultProcess
        X = $workArea.Left + $halfWidth
        Y = $workArea.Top
        W = $workArea.Width - $halfWidth
        H = $workArea.Height
    },
    @{
        Name = "DebugTopLeft"
        Process = $debugTopProcess
        X = $workArea.Left
        Y = $workArea.Top
        W = $halfWidth
        H = $halfHeight
    },
    @{
        Name = "DebugBottomLeft"
        Process = $debugBottomProcess
        X = $workArea.Left
        Y = $workArea.Top + $halfHeight
        W = $halfWidth
        H = $workArea.Height - $halfHeight
    }
)

foreach ($layout in $layouts) {
    $hWnd = Wait-ForMainWindow -Process $layout.Process
    [NativeWin]::ShowWindowAsync($hWnd, [NativeWin]::SW_RESTORE) | Out-Null
    $moved = [NativeWin]::MoveWindow($hWnd, $layout.X, $layout.Y, $layout.W, $layout.H, $true)
    if (-not $moved) {
        Write-Warning "Failed to move $($layout.Name) window (PID $($layout.Process.Id))."
    }
}

Write-Host "Done. Windows arranged: right=Default, left-top=DEBUG1, left-bottom=DEBUG2."
Write-Host "Online sync logs: $onlineSyncLogDir"
Write-Host "Run id: $runId"
Write-Host "Transport debug params:"
Write-Host "  Default: ping=${DefaultPingMs}ms loss=${DefaultPacketLossPercent}%"
Write-Host "  DEBUG1:  ping=${Debug1PingMs}ms loss=${Debug1PacketLossPercent}%"
Write-Host "  DEBUG2:  ping=${Debug2PingMs}ms loss=${Debug2PacketLossPercent}%"
