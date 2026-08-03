<#
.SYNOPSIS
    Dò các nguồn đo công suất khả dụng trên máy Windows này.

.DESCRIPTION
    Trả lời câu hỏi: "máy này có đọc được số watt không, và bằng đường nào?"
    Đây là bước đầu tiên của quy trình ESG Tầng 1 (docs/07-esg-3-tang.md):
    nếu không đo được công suất thật thì mọi con số J/token đều là ước lượng.

    Script CHỈ ĐỌC. Không cài gì, không sửa gì, không cần quyền Administrator
    (trừ phần kiểm tra LibreHardwareMonitor, sẽ tự bỏ qua nếu thiếu quyền).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\measure_power\power_probe.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\measure_power\power_probe.ps1 -Json

.NOTES
    Tài liệu: docs/08-do-cong-suat.md
#>
[CmdletBinding()]
param(
    # Xuất JSON thay vì bảng cho người đọc (dùng khi gọi từ script khác)
    [switch]$Json,
    # Đường dẫn tới NodeAgent.exe đã publish, để thử đọc cảm biến phần cứng
    [string]$AgentPath = ""
)

# PowerShell 5.1 mặc định ghi console bằng codepage hệ thống -> mất dấu tiếng Việt.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ErrorActionPreference = 'Continue'

$result = [ordered]@{
    probed_at    = (Get-Date).ToString('s')
    machine      = [ordered]@{}
    sources      = @()
    best_source  = 'none'
    conclusion   = ''
}

function Write-Section($title) {
    if (-not $Json) {
        Write-Host ''
        Write-Host ("=" * 68) -ForegroundColor DarkGray
        Write-Host "  $title" -ForegroundColor Cyan
        Write-Host ("=" * 68) -ForegroundColor DarkGray
    }
}

function Write-Item($label, $value, $color = 'Gray') {
    if (-not $Json) {
        Write-Host ("  {0,-32} " -f "$label :") -NoNewline
        Write-Host $value -ForegroundColor $color
    }
}

function Add-Source($name, $available, $unit, $note, $quality) {
    # quality: 'direct' (đo thật) | 'derived' (suy ra) | 'none'
    $script:result.sources += [ordered]@{
        name      = $name
        available = $available
        unit      = $unit
        quality   = $quality
        note      = $note
    }
    if (-not $Json) {
        $mark  = if ($available) { '[CO ]' } else { '[----]' }
        $color = if ($available) { 'Green' } else { 'DarkGray' }
        Write-Host ("  {0} {1,-28} {2}" -f $mark, $name, $note) -ForegroundColor $color
    }
}

# ─────────────────────────────────────────────────────────────────────
# 1. Thông tin máy
# ─────────────────────────────────────────────────────────────────────
Write-Section "1. Thông tin máy"

try {
    $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $cs  = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop

    # PCSystemType: 1=Desktop, 2=Mobile(laptop), 3=Workstation, 4=Enterprise Server
    $isLaptop = ($cs.PCSystemType -eq 2)

    $result.machine = [ordered]@{
        cpu_name     = $cpu.Name.Trim()
        vendor       = $cpu.Manufacturer
        cores        = $cpu.NumberOfCores
        threads      = $cpu.NumberOfLogicalProcessors
        base_mhz     = $cpu.MaxClockSpeed
        ram_gb       = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
        is_laptop    = $isLaptop
        os           = (Get-CimInstance Win32_OperatingSystem).Caption
    }

    Write-Item 'CPU'          $result.machine.cpu_name  'White'
    Write-Item 'Hãng'         $result.machine.vendor
    Write-Item 'Nhân / luồng' "$($result.machine.cores) / $($result.machine.threads)"
    Write-Item 'Xung cơ bản'  "$($result.machine.base_mhz) MHz"
    Write-Item 'RAM'          "$($result.machine.ram_gb) GB"
    Write-Item 'Loại máy'     $(if ($isLaptop) { 'Laptop' } else { 'Desktop / máy bàn' })
    Write-Item 'Hệ điều hành' $result.machine.os
}
catch {
    Write-Item 'Lỗi đọc thông tin máy' $_.Exception.Message 'Red'
}

# ─────────────────────────────────────────────────────────────────────
# 2. Pin — nguồn đo công suất TOÀN MÁY chính xác nhất khi có
# ─────────────────────────────────────────────────────────────────────
Write-Section "2. Pin (đo công suất toàn máy)"

$batteryOk   = $false
$batteryNote = 'Không có pin (máy bàn)'

try {
    $bs = Get-CimInstance -Namespace 'root\WMI' -ClassName 'BatteryStatus' -ErrorAction Stop |
          Select-Object -First 1
    if ($null -ne $bs) {
        $onAC     = [bool]$bs.PowerOnline
        $charging = [bool]$bs.Charging
        $rateMw   = [int]$bs.DischargeRate

        Write-Item 'Đang cắm sạc'   $(if ($onAC) { 'Có' } else { 'Không' })
        Write-Item 'Đang nạp'       $(if ($charging) { 'Có' } else { 'Không' })
        Write-Item 'Tốc độ xả'      "$rateMw mW"

        if ($rateMw -gt 0) {
            $batteryOk   = $true
            $batteryNote = "Đang xả {0:N1} W - dùng được ngay" -f ($rateMw / 1000.0)
        }
        elseif ($onAC) {
            $batteryNote = 'Có pin nhưng đang cắm sạc -> rút sạc để đo được toàn máy'
        }
        else {
            $batteryNote = 'Có pin nhưng DischargeRate = 0 (firmware không báo)'
        }
    }
}
catch {
    try {
        $b = Get-CimInstance Win32_Battery -ErrorAction Stop | Select-Object -First 1
        if ($null -ne $b) { $batteryNote = 'Có pin nhưng không đọc được tốc độ xả qua WMI' }
    } catch { }
}

Add-Source 'Pin (BatteryStatus WMI)' $batteryOk 'W' $batteryNote 'direct'

if ($batteryOk -and -not $Json) {
    Write-Host ''
    Write-Host '  Lưu ý: pin đo công suất TOÀN MÁY (gồm màn hình, ổ đĩa, mạng),' -ForegroundColor Yellow
    Write-Host '  không riêng CPU. Vẫn hữu ích: J/token quan tâm điện tiêu thụ thật' -ForegroundColor Yellow
    Write-Host '  của cả máy, không chỉ của con chip.' -ForegroundColor Yellow
}

# ─────────────────────────────────────────────────────────────────────
# 3. LibreHardwareMonitor qua NodeAgent — nguồn của hệ thống hiện tại
# ─────────────────────────────────────────────────────────────────────
Write-Section "3. Cảm biến phần cứng (LibreHardwareMonitor)"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$agentCandidates = @()
if ($AgentPath) { $agentCandidates += $AgentPath }
$agentCandidates += @(
    (Join-Path $repoRoot 'publish\NodeAgent\NodeAgent.exe'),
    (Join-Path $repoRoot 'agent\bin\Release\net8.0\NodeAgent.exe'),
    (Join-Path $repoRoot 'agent\bin\Debug\net8.0\NodeAgent.exe')
)

$agentExe = $agentCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
$sensorPowerOk = $false
$sensorUntested = $true     # phân biệt "đã thử và không có" với "chưa thử được"
$sensorNote    = 'CHƯA KIỂM TRA - chưa build NodeAgent.exe, chạy scripts\publish_agent.ps1 trước'

if ($agentExe) {
    Write-Item 'Tìm thấy agent' $agentExe
    $isAdmin = ([Security.Principal.WindowsPrincipal] `
                [Security.Principal.WindowsIdentity]::GetCurrent()
               ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if (-not $isAdmin) {
        $sensorNote = 'CHƯA KIỂM TRA - cần chạy PowerShell với quyền Administrator'
        Write-Item 'Quyền Administrator' 'KHÔNG - bỏ qua bước này' 'Yellow'
    }
    else {
        $sensorUntested = $false
        try {
            $out = & $agentExe --test-sensors 2>&1 | Out-String
            if (-not $Json) {
                Write-Host ''
                ($out -split "`n") | ForEach-Object { if ($_.Trim()) { Write-Host "    $($_.TrimEnd())" -ForegroundColor DarkGray } }
            }
            # Dòng có dạng:  Power:    28.4 W
            if ($out -match 'Power:\s*([\d\.]+)') {
                $sensorPowerOk = $true
                $sensorNote    = "Đọc được $($Matches[1]) W từ cảm biến CPU package"
            }
            elseif ($out -match 'Power:\s*n/a') {
                $sensorNote = 'Cảm biến trả n/a - CPU/mainboard không phơi bày package power'
            }
        }
        catch {
            $sensorNote = "Lỗi chạy agent: $($_.Exception.Message)"
        }
    }
}

Add-Source 'LibreHardwareMonitor' $sensorPowerOk 'W' $sensorNote 'direct'

# ─────────────────────────────────────────────────────────────────────
# 4. Công cụ của hãng
# ─────────────────────────────────────────────────────────────────────
Write-Section "4. Công cụ của hãng chip"

$ipgPaths = @(
    'C:\Program Files\Intel\Power Gadget 3.6\PowerLog3.0.exe',
    'C:\Program Files\Intel\Power Gadget 3.5\PowerLog3.0.exe',
    'C:\Program Files\Intel\Power Gadget\PowerLog3.0.exe'
)
$ipg = $ipgPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
Add-Source 'Intel Power Gadget' ([bool]$ipg) 'W' `
    $(if ($ipg) { $ipg } else { 'Chưa cài (Intel đã ngừng phát hành - chỉ dùng nếu đã có sẵn)' }) 'direct'

$hwinfo = Test-Path -LiteralPath 'C:\Program Files\HWiNFO64\HWiNFO64.EXE'
Add-Source 'HWiNFO64' $hwinfo 'W' `
    $(if ($hwinfo) { 'Đã cài - có thể bật Shared Memory Support để đọc' } else { 'Chưa cài' }) 'direct'

# ─────────────────────────────────────────────────────────────────────
# 5. Đường dự phòng luôn có
# ─────────────────────────────────────────────────────────────────────
Write-Section "5. Đường dự phòng"

Add-Source 'Đồng hồ điện rời' $true 'W' `
    'Luôn dùng được. Chính xác nhất. Cần đọc thủ công - xem docs/08 §5' 'direct'

Add-Source 'Mô hình P(util, temp)' $true 'W' `
    'power_baseline.py + power_model_fit.py. Cần hiệu chuẩn một lần bằng nguồn ở trên' 'derived'

# ─────────────────────────────────────────────────────────────────────
# 6. Kết luận
# ─────────────────────────────────────────────────────────────────────
Write-Section "6. Kết luận"

$result.sensor_untested = $sensorUntested

if ($sensorPowerOk) {
    $result.best_source = 'sensor_lhm'
    $result.conclusion  = 'Máy đọc được công suất CPU qua LibreHardwareMonitor. ' +
                          'Job chạy trên máy này ĐỦ ĐIỀU KIỆN vào ESG Tầng 1 (đo thật). ' +
                          'Vẫn nên chạy power_baseline.py để có p_idle/p_max cho công thức chấm điểm.'
}
elseif ($sensorUntested) {
    $result.best_source = 'unknown'
    $vendorHint = ''
    if ($result.machine.vendor -match 'Intel')     { $vendorHint = 'CPU Intel đời Core thế hệ 6 trở lên thường phơi bày package power qua RAPL, nên khả năng đọc được là cao. ' }
    elseif ($result.machine.vendor -match 'AMD')   { $vendorHint = 'CPU AMD Ryzen thường phơi bày package power qua SMU, nhưng độ phủ kém đồng đều hơn Intel. ' }
    $result.conclusion  = 'CHƯA KẾT LUẬN ĐƯỢC. Chưa kiểm tra được LibreHardwareMonitor - đó là ' +
                          'nguồn có khả năng nhất trên máy này, không phải nguồn đã bị loại. ' +
                          $vendorHint +
                          'Hãy build agent (scripts\publish_agent.ps1) rồi chạy lại script này ' +
                          'VỚI QUYỀN ADMINISTRATOR trước khi kết luận bất cứ điều gì về ESG Tầng 1.'
}
elseif ($batteryOk) {
    $result.best_source = 'battery'
    $result.conclusion  = 'Không đọc được công suất CPU, nhưng đo được công suất toàn máy qua pin ' +
                          '(khi rút sạc). Dùng đường này để hiệu chuẩn mô hình P(util, temp), ' +
                          'sau đó job vào ESG Tầng 2 (suy ra).'
}
else {
    $result.best_source = 'none'
    $result.conclusion  = 'Máy này KHÔNG có nguồn đo công suất tự động (đã kiểm tra cảm biến, ' +
                          'không có pin). Bắt buộc hiệu chuẩn một lần bằng đồng hồ điện rời ' +
                          '(docs/08 §5), rồi dùng mô hình P(util, temp). ' +
                          'Job vào ESG Tầng 2, KHÔNG vào Tầng 1.'
}

if ($Json) {
    $result | ConvertTo-Json -Depth 6
}
else {
    Write-Host ''
    Write-Host "  Nguồn tốt nhất: " -NoNewline
    $bsColor = switch ($result.best_source) {
        'none'    { 'Red' }
        'unknown' { 'Yellow' }
        default   { 'Green' }
    }
    Write-Host $result.best_source -ForegroundColor $bsColor
    Write-Host ''
    # Bẻ dòng kết luận cho dễ đọc trên console hẹp
    $words = $result.conclusion -split ' '
    $line  = '  '
    foreach ($w in $words) {
        if (($line.Length + $w.Length) -gt 70) { Write-Host $line; $line = '  ' }
        $line += "$w "
    }
    if ($line.Trim()) { Write-Host $line }

    Write-Host ''
    Write-Host '  Bước tiếp theo:' -ForegroundColor Cyan
    Write-Host '    python scripts\measure_power\power_baseline.py --help'
    Write-Host '    (xem docs\08-do-cong-suat.md để biết quy trình đầy đủ)'
    Write-Host ''
}
