<#
.SYNOPSIS
    Cài Thermal Orchestrator vào %ProgramData% (cần một lần UAC).

.DESCRIPTION
    Host: copy server Python + launcher.
    Worker: copy NodeAgent đã publish.
    Trình hướng dẫn 4 bước theo docs/10 §5.
    Cấu hình agent được DPAPI LocalMachine và ACL Administrators/SYSTEM bảo vệ.
#>
[CmdletBinding()]
param(
    [ValidateSet("Host", "Worker", "Both")]
    [string]$Role = "Both",
    [string]$RepoRoot = "",
    [switch]$SkipWizard
)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ErrorActionPreference = "Stop"
$utf8Bom = New-Object System.Text.UTF8Encoding $true

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$InstallRoot = Join-Path $env:ProgramData "ThermalOrchestrator"
$Bin = Join-Path $InstallRoot "bin"
$Data = Join-Path $InstallRoot "data"
$Config = Join-Path $InstallRoot "config"
$Logs = Join-Path $InstallRoot "logs"
$Runtime = Join-Path $InstallRoot "runtime"
$Models = Join-Path $InstallRoot "models"

Write-Host ""
Write-Host "=== Thermal Orchestrator — Cài đặt ===" -ForegroundColor Cyan
Write-Host "  Dich: $InstallRoot"
Write-Host "  Can UAC mot lan de cai Host va Agent theo may"
Write-Host ""

foreach ($d in @($InstallRoot, $Bin, $Data, $Config, $Logs, $Runtime, $Models)) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

if ($Role -in @("Host", "Both")) {
    Write-Host "[1/3] Dong goi Host..." -ForegroundColor Yellow
    $serverSrc = Join-Path $RepoRoot "server"
    $hostDst = Join-Path $Bin "host"
    # H6: trước khi xóa host cũ — chuyển *.db / ESG sang data\ (không mất ledger)
    if (Test-Path -LiteralPath $hostDst) {
        $preserveNames = @(
            "telemetry.db", "esg_events.db", "model.pkl", "power_model.json")
        foreach ($name in $preserveNames) {
            $srcFile = Join-Path $hostDst $name
            if (Test-Path -LiteralPath $srcFile) {
                $destFile = Join-Path $Data $name
                Copy-Item -LiteralPath $srcFile -Destination $destFile -Force
                Write-Host "  GIU $name -> data\" -ForegroundColor Green
            }
        }
        Write-Host "  Canh bao: cai lai se thay bin\host (data\ da duoc bao ve)." -ForegroundColor Yellow
        Remove-Item -LiteralPath $hostDst -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $hostDst | Out-Null
    Get-ChildItem -LiteralPath $serverSrc -Force | Where-Object {
        $_.Name -notin @(
            ".venv", "__pycache__", "telemetry.db", "model.pkl",
            "settings.json", "weather_local.json", ".pytest_cache")
    } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName `
            -Destination (Join-Path $hostDst $_.Name) -Recurse -Force
    }
    $bat = "@echo off`r`ncd /d `"%~dp0`"`r`nset PYTHONUTF8=1`r`n" +
        "set THERMAL_DATA_DIR=$Data`r`n" +
        "if exist `".venv\Scripts\python.exe`" (`r`n" +
        "  `".venv\Scripts\python.exe`" server.py %*`r`n" +
        ") else (`r`n  python server.py %*`r`n)`r`n"
    [IO.File]::WriteAllText((Join-Path $hostDst "Start-Host.bat"), $bat)
    Write-Host "  Host -> $hostDst" -ForegroundColor Green
}

if ($Role -in @("Worker", "Both")) {
    Write-Host "[2/3] Dong goi Worker..." -ForegroundColor Yellow
    $pub = Join-Path $RepoRoot "publish\NodeAgent"
    if (-not (Test-Path -LiteralPath $pub)) {
        $pubScript = Join-Path $RepoRoot "scripts\publish_agent.ps1"
        if (Test-Path -LiteralPath $pubScript) {
            Write-Host "  Chay publish_agent.ps1..." -ForegroundColor Yellow
            & powershell -ExecutionPolicy Bypass -File $pubScript
        }
    }
    $workerDst = Join-Path $Bin "worker"
    if (Test-Path -LiteralPath $pub) {
        if (Test-Path -LiteralPath $workerDst) {
            Remove-Item -LiteralPath $workerDst -Recurse -Force
        }
        Copy-Item -LiteralPath $pub -Destination $workerDst -Recurse -Force
        Write-Host "  Worker -> $workerDst" -ForegroundColor Green
    } else {
        Write-Warning "Khong tim thay publish\NodeAgent"
    }
}

$probeSrc = Join-Path $RepoRoot "scripts\measure_power\power_probe.ps1"
if (Test-Path -LiteralPath $probeSrc) {
    Copy-Item -LiteralPath $probeSrc `
        -Destination (Join-Path $Bin "power_probe.ps1") -Force
}
foreach ($name in @("Uninstall.ps1", "FirstRun-Wizard.ps1")) {
    $src = Join-Path $PSScriptRoot $name
    if (Test-Path -LiteralPath $src) {
        $dst = if ($name -eq "Uninstall.ps1") {
            Join-Path $InstallRoot $name
        } else {
            Join-Path $Bin $name
        }
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}

$meta = @{
    installed_at = (Get-Date).ToString("s")
    role         = $Role
    version      = "G6"
    path         = $InstallRoot
} | ConvertTo-Json
[IO.File]::WriteAllText(
    (Join-Path $InstallRoot "install.json"), $meta, $utf8Bom)

Write-Host "[3/3] Xong cau truc thu muc." -ForegroundColor Green
Write-Host "  data\  — GIU khi go cai (mac dinh); chua esg_events khong tai tao duoc"
Write-Host ""

if (-not $SkipWizard) {
    $wiz = Join-Path $Bin "FirstRun-Wizard.ps1"
    if (Test-Path -LiteralPath $wiz) {
        & powershell -ExecutionPolicy Bypass -File $wiz `
            -InstallRoot $InstallRoot
    }
}

Write-Host "Cai xong. Go: $InstallRoot\Uninstall.ps1" -ForegroundColor Cyan
