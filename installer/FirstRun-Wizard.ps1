<#
.SYNOPSIS
    Trình hướng dẫn 4 bước lần đầu (docs/10 §5).

.DESCRIPTION
    Bước 1: Host hay Worker
    Bước 2: Host → bootstrap API; Worker → config.json agent
    Bước 3: (placeholder) tải thành phần
    Bước 4: Kiểm tra cảm biến + power_probe → báo ESG tầng

    Web trên Host ≠ chia sẻ CPU. Đóng góp tải cần NodeAgent.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = "",
    [string]$HostBaseUrl = "http://127.0.0.1:8000"
)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ErrorActionPreference = "Continue"
$utf8Bom = New-Object System.Text.UTF8Encoding $true

if (-not $InstallRoot) {
    $InstallRoot = Join-Path $env:ProgramData "ThermalOrchestrator"
}
$Bin = Join-Path $InstallRoot "bin"
$Config = Join-Path $InstallRoot "config"
New-Item -ItemType Directory -Force -Path $Config | Out-Null

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Thermal Orchestrator — Lan dau"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Vai tro (doc ky):" -ForegroundColor DarkYellow
Write-Host "  • Chi mo web tren Host = quan tri + gui cau hoi;"
Write-Host "    cau tra loi chay tren worker online hoac LLM local host."
Write-Host "  • Muon may nay dong gop tinh toan = cai/chay NodeAgent"
Write-Host "    (quyen Admin luc chay de doc cam bien)."
Write-Host "  • Muon lam chu phong = che do Host — khong can Room Directory."
Write-Host ""

# —— Bước 1 ——
Write-Host "Buoc 1  Ban muon lam gi?" -ForegroundColor Yellow
Write-Host "  [1] Mo phong moi (may nay lam chu / Host)"
Write-Host "  [2] Vao phong co san (Worker — can NodeAgent)"
$choice = Read-Host "Chon 1 hoac 2"
$isHost = ($choice -ne "2")

# —— Bước 2 ——
Write-Host ""
Write-Host "Buoc 2  Cau hinh" -ForegroundColor Yellow
$room = @{}
$hostProc = $null

function ConvertFrom-SecurePlain {
    param([Security.SecureString]$Secure)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

if ($isHost) {
    $room.name = Read-Host "Ten phong (vd: Phong 4F)"
    $secWorker = Read-Host "Mat khau worker (>=8; tunnel can >=12)" -AsSecureString
    $secAdmin = Read-Host "Mat khau admin (khac mat khau worker)" -AsSecureString
    $room.password = ConvertFrom-SecurePlain $secWorker
    $room.admin_password = ConvertFrom-SecurePlain $secAdmin
    $secWorker = $null
    $secAdmin = $null
    if ($room.password.Length -lt 8 -or $room.admin_password.Length -lt 8) {
        Write-Host "Mat khau phai >=8 ky tu." -ForegroundColor Red
        exit 1
    }
    if ($room.password -eq $room.admin_password) {
        Write-Host "Worker va admin phai khac nhau." -ForegroundColor Red
        exit 1
    }
    $room.site_id = Read-Host "Khu vuc / site_id (mac dinh hanoi-office-4f)"
    if (-not $room.site_id) { $room.site_id = "hanoi-office-4f" }
    $room.threshold_c = 75
    $room.role = "host"

    $hostDir = Join-Path $Bin "host"
    $startBat = Join-Path $hostDir "Start-Host.bat"
    Write-Host "  Khoi dong Host (--bootstrap-open)..." -ForegroundColor Yellow
    if (Test-Path -LiteralPath $startBat) {
        $hostProc = Start-Process -FilePath $startBat `
            -ArgumentList "--bootstrap-open" `
            -WorkingDirectory $hostDir `
            -PassThru -WindowStyle Minimized
    } else {
        Write-Host "  Khong thay Start-Host.bat — chay thu cong:" -ForegroundColor Yellow
        Write-Host "    cd server; python server.py --bootstrap-open"
    }

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $ping = Invoke-WebRequest -Uri "$HostBaseUrl/" -UseBasicParsing `
                -TimeoutSec 2 -ErrorAction Stop
            $ready = $true
            break
        } catch { }
    }
    if (-not $ready) {
        Write-Host "  Host chua phan hoi tai $HostBaseUrl" -ForegroundColor Red
        Write-Host "  Mo Start-Host.bat --bootstrap-open roi chay lai wizard."
    } else {
        $payload = @{
            display_name     = $room.name
            worker_password  = $room.password
            admin_password   = $room.admin_password
            site_id          = $room.site_id
            threshold_c      = $room.threshold_c
            regenerate_code  = $true
        } | ConvertTo-Json
        try {
            $resp = Invoke-RestMethod -Method Post `
                -Uri "$HostBaseUrl/api/room/bootstrap" `
                -ContentType "application/json; charset=utf-8" `
                -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))
            $room.room_code = $resp.room.code
            $room.invite = $resp.room.invite_lan
            Write-Host "  Phong: $($room.room_code)" -ForegroundColor Green
            Write-Host "  Link moi LAN: $($room.invite)" -ForegroundColor Green
            Write-Host "  Gui mat khau RIENG voi link (khong chung tin nhan)." -ForegroundColor Yellow
            Write-Host "  Dashboard: $HostBaseUrl/  (dang nhap bang mat khau admin)"
        } catch {
            Write-Host "  Bootstrap that bai: $_" -ForegroundColor Red
        }
        # Xoa plaintext khoi bien sau khi POST
        $room.password = $null
        $room.admin_password = $null
        $payload = $null
    }
} else {
    $room.invite = Read-Host "Dan link moi (LAN hoac tunnel)"
    $secWorker = Read-Host "Mat khau phong (worker)" -AsSecureString
    $room.password = ConvertFrom-SecurePlain $secWorker
    $secWorker = $null
    $room.node_name = Read-Host "Ten may (vd: Node-A)"
    $room.role = "worker"
    $room.room_code = "THERMAL-LOCAL"
    if ($room.invite -match '[?&]code=([A-Za-z0-9\-]+)') {
        $room.room_code = $Matches[1]
    }
    $workerDir = Join-Path $Bin "worker"
    $serverUrl = $room.invite
    if ($serverUrl -match '^(https?://[^/]+)') {
        $serverUrl = $Matches[1]
    }
    $cfg = @{
        nodeName  = $room.node_name
        serverUrl = $serverUrl
        roomCode  = $room.room_code
        password  = $room.password
    } | ConvertTo-Json -Compress
    $agentExe = Join-Path $workerDir "NodeAgent.exe"
    $agentConfig = Join-Path $env:ProgramData `
        "ThermalOrchestrator\agent\config.json"
    if (-not (Test-Path -LiteralPath $agentExe)) {
        Write-Host "  Khong thay NodeAgent.exe de bao ve cau hinh." -ForegroundColor Red
        exit 1
    }
    $cfg | & $agentExe --protect-config $agentConfig
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Khong ghi duoc cau hinh duoc bao ve." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    $room.password = $null
    $cfg = $null
    Write-Host "  Da ghi cau hinh worker DPAPI theo may" -ForegroundColor Green
    Write-Host "  Chi mo web KHONG du de may nay cho muon CPU — can NodeAgent." `
        -ForegroundColor Yellow
}

# Khong ghi mat khau vao room.json (docs/06) — chi metadata
$roomPublic = @{
    role         = $room.role
    name         = $room.name
    site_id      = $room.site_id
    invite       = $room.invite
    node_name    = $room.node_name
    room_code    = $room.room_code
    password_set = $true
    threshold_c  = $room.threshold_c
}
[IO.File]::WriteAllText(
    (Join-Path $Config "room.json"),
    ($roomPublic | ConvertTo-Json -Depth 5), $utf8Bom)

# —— Bước 3 ——
Write-Host ""
Write-Host "Buoc 3  Thanh phan" -ForegroundColor Yellow
Write-Host "  [OK] Runtime suy luan   — tai khi worker join (hash ADR-005)"
Write-Host "  [OK] Mo hinh ngon ngu   — theo catalog phong"
Write-Host "  [..] Kiem tra cam bien  — buoc 4"

# —— Bước 4 ——
Write-Host ""
Write-Host "Buoc 4  Kiem tra (power_probe + cam bien)" -ForegroundColor Yellow
$probe = Join-Path $Bin "power_probe.ps1"
$agentExe = Join-Path $Bin "worker\NodeAgent.exe"
$esgTier = "chua xac dinh"
$probeResult = $null

if (Test-Path -LiteralPath $probe) {
    if (Test-Path -LiteralPath $agentExe) {
        $raw = & powershell -ExecutionPolicy Bypass -File $probe -Json `
            -AgentPath $agentExe 2>$null
    } else {
        $raw = & powershell -ExecutionPolicy Bypass -File $probe -Json 2>$null
    }
    try {
        $probeResult = $raw | ConvertFrom-Json
    } catch {
        $probeResult = $null
    }
}

if ($probeResult) {
    $best = [string]$probeResult.best_source
    Write-Host "  Nguon cong suat tot nhat: $best"
    Write-Host "  $($probeResult.conclusion)"
    switch ($best) {
        "sensor" {
            $esgTier = "Tang 1 (DO THAT) — doc duoc cong suat cam bien"
            Write-Host "  [OK] ESG: $esgTier" -ForegroundColor Green
        }
        "battery" {
            $esgTier = "Tang 2 (SUY RA) — pin / mo hinh, khong phai cam bien CPU"
            Write-Host "  [!!] ESG: $esgTier" -ForegroundColor Yellow
        }
        "none" {
            $esgTier = "Tang 2 (SUY RA) — bat buoc hieu chuan; KHONG vao Tang 1"
            Write-Host "  [!!] ESG: $esgTier" -ForegroundColor Yellow
        }
        default {
            $esgTier = "Chua ket luan — chay lai power_probe voi quyen Administrator"
            Write-Host "  [??] ESG: $esgTier" -ForegroundColor DarkYellow
        }
    }
} else {
    Write-Host "  Khong chay duoc power_probe — bo qua, chay thu cong sau." -ForegroundColor DarkYellow
    $esgTier = "chua do — chay bin\power_probe.ps1"
}

if (Test-Path -LiteralPath $agentExe) {
    Write-Host "  Thu NodeAgent --test-sensors (can Admin)..."
    try {
        & $agentExe --test-sensors 2>&1 | ForEach-Object { Write-Host "    $_" }
    } catch {
        Write-Host "  Cam bien: khong doc duoc (can Administrator luc CHAY)." -ForegroundColor Yellow
    }
}

$summary = @{
    finished_at = (Get-Date).ToString("s")
    role        = $room.role
    esg_tier    = $esgTier
    best_source = if ($probeResult) { $probeResult.best_source } else { "unknown" }
    room_code   = $room.room_code
}
[IO.File]::WriteAllText(
    (Join-Path $Config "first_run.json"),
    ($summary | ConvertTo-Json), $utf8Bom)

Write-Host ""
Write-Host "Hoan tat huong dan. ESG may nay: $esgTier" -ForegroundColor Cyan
if ($isHost) {
    Write-Host "Host dang chay (neu bootstrap thanh cong). Dashboard: $HostBaseUrl/"
    Write-Host "Chi mo web = quan tri/chat — khong thay the NodeAgent tren may worker."
} else {
    Write-Host "Worker: chay NodeAgent.exe bang quyen Administrator"
}
Write-Host ""
