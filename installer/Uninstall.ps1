<#
.SYNOPSIS
    Gỡ Thermal Orchestrator sạch. HỎI TRƯỚC khi xóa data/ (mặc định GIỮ).

.DESCRIPTION
    esg_events trong data\ không tái tạo được — mặc định giữ lại.
    Ca M8: gỡ sạch, hỏi trước khi xóa dữ liệu ESG.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = "",
    [switch]$KeepData,
    [switch]$RemoveData,
    # Bắt buộc kèm -RemoveData để xóa data\ (xác nhận kép — ca M8)
    [switch]$ConfirmRemoveData,
    [switch]$NonInteractive
)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ErrorActionPreference = "Continue"

if (-not $InstallRoot) {
    $InstallRoot = Join-Path $env:ProgramData "ThermalOrchestrator"
}

if (-not (Test-Path -LiteralPath $InstallRoot)) {
    Write-Host "Khong tim thay cai dat tai $InstallRoot" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "=== Go cai Thermal Orchestrator ===" -ForegroundColor Cyan
Write-Host "  Thu muc: $InstallRoot"
Write-Host ""

# 1. Thu hồi / dừng tiến trình
Write-Host "[1] Dung tien trinh..." 
Get-Process -Name "NodeAgent","cloudflared","python" -ErrorAction SilentlyContinue |
    Where-Object {
        try {
            $_.Path -and $_.Path.StartsWith($InstallRoot,
                [StringComparison]::OrdinalIgnoreCase)
        } catch { $false }
    } | ForEach-Object {
        Write-Host "  Stop $($_.ProcessName) pid=$($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }

# 2. Quyết định data/
$dataDir = Join-Path $InstallRoot "data"
$keep = $true
if ($KeepData) {
    $keep = $true
} elseif ($RemoveData) {
    # Xác nhận kép: -RemoveData một mình KHÔNG đủ
    if ($ConfirmRemoveData) {
        $keep = $false
    } elseif ($NonInteractive) {
        Write-Host "Tu choi xoa data\: can -RemoveData -ConfirmRemoveData" `
            -ForegroundColor Yellow
        $keep = $true
    } else {
        Write-Host ""
        Write-Host "Ban da chi -RemoveData. Xac nhan lan 2:" -ForegroundColor Yellow
        Write-Host "Nhat ky ESG KHONG tai tao duoc neu xoa."
        $ans = Read-Host "Go dung 'DELETE-ESG' de xoa data\ (Enter = giu)"
        if ($ans -eq "DELETE-ESG") {
            $keep = $false
        } else {
            $keep = $true
            Write-Host "  Giu data\." -ForegroundColor Green
        }
    }
} elseif (-not $NonInteractive) {
    Write-Host ""
    Write-Host "Thu muc data\ co the chua telemetry.db / esg_events." -ForegroundColor Yellow
    Write-Host "Nhat ky ESG KHONG tai tao duoc neu xoa."
    Write-Host "Mac dinh: GIU LAI data\."
    Write-Host "Xac nhan kep: go dung 'DELETE-ESG' de xoa (Enter = giu)."
    $ans = Read-Host "Xac nhan"
    if ($ans -eq "DELETE-ESG") {
        $keep = $false
    } else {
        $keep = $true
        Write-Host "  Giu data\." -ForegroundColor Green
    }
}

# 3. Xóa quy tắc tường lửa host (neu co)
Write-Host "[2] Go quy tac tuong lua (neu co quyen)..."
try {
    Remove-NetFirewallRule -DisplayName "Thermal PoC server (TCP 8000)" `
        -ErrorAction SilentlyContinue
} catch { }

# 4. Xóa thư mục
Write-Host "[3] Xoa tep cai dat..."
$preserve = Join-Path $env:ProgramData "ThermalOrchestrator-data-backup"
if ($keep -and (Test-Path -LiteralPath $dataDir)) {
    if (Test-Path -LiteralPath $preserve) {
        Remove-Item -LiteralPath $preserve -Recurse -Force -ErrorAction SilentlyContinue
    }
    Move-Item -LiteralPath $dataDir -Destination $preserve -Force
    Write-Host "  Da GIU data\ tai: $preserve" -ForegroundColor Green
}

Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue

if (-not $keep) {
    Write-Host "  Da XOA data\ theo yeu cau." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Go cai xong." -ForegroundColor Cyan
if ($keep) {
    Write-Host "Du lieu ESG con o: $preserve"
}
Write-Host ""
