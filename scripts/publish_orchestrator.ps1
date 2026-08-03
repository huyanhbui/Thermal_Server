<#
.SYNOPSIS
    Tạo ThermalOrchestrator.exe Windows x64 một file.

.DESCRIPTION
    EXE chứa Host, NodeAgent và Python runtime đã chuẩn bị; không chứa model GGUF.
    PythonRuntimeDir phải là runtime di động đã có các dependency server (không dùng
    venv chỉ trỏ về Python cài trên máy build).
#>
[CmdletBinding()]
param(
    [string]$Version = "dev",
    [Parameter(Mandatory)]
    [string]$PythonRuntimeDir,
    [string]$OutputDirectory = ""
)

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repoRoot "publish\ThermalOrchestrator"
}
$runtimePython = Join-Path $PythonRuntimeDir "python.exe"
if (-not (Test-Path -LiteralPath $runtimePython)) {
    throw "PythonRuntimeDir phải chứa python.exe: $PythonRuntimeDir"
}
& $runtimePython -c "import fastapi, uvicorn"
if ($LASTEXITCODE -ne 0) {
    throw "PythonRuntimeDir thiếu fastapi hoặc uvicorn cần cho Host."
}

$agentPublish = Join-Path $repoRoot "publish\NodeAgent"
& powershell -ExecutionPolicy Bypass -File `
    (Join-Path $repoRoot "scripts\publish_agent.ps1")
if ($LASTEXITCODE -ne 0) { throw "Không publish được NodeAgent." }

$stage = Join-Path ([IO.Path]::GetTempPath()) `
    ("thermal-package-" + [Guid]::NewGuid().ToString("N"))
$zip = Join-Path ([IO.Path]::GetTempPath()) `
    ("thermal-payload-" + [Guid]::NewGuid().ToString("N") + ".zip")
try {
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    $hostDir = Join-Path $stage "host"
    $agent = Join-Path $stage "agent"
    $runtime = Join-Path $stage "runtime\python"
    New-Item -ItemType Directory -Force -Path $hostDir, $agent, $runtime | Out-Null

    Get-ChildItem -LiteralPath (Join-Path $repoRoot "server") -Force |
        Where-Object { $_.Name -notin @(
            ".venv", "__pycache__", ".pytest_cache", "data", "tests",
            "telemetry.db", "telemetry.db-wal", "telemetry.db-shm", "room.json",
            "settings.json", "server.log", "model.pkl") } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $hostDir $_.Name) `
                -Recurse -Force
        }
    Get-ChildItem -LiteralPath $agentPublish -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $agent -Recurse -Force
    }
    Get-ChildItem -LiteralPath $PythonRuntimeDir -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $runtime -Recurse -Force
    }
    # Python embeddable ignores CWD. Add the sibling Host explicitly so the
    # bundled server can import its modules without a Python install on target.
    $pthFile = Join-Path $runtime "python311._pth"
    if (Test-Path -LiteralPath $pthFile) {
        $pthLines = @(Get-Content -LiteralPath $pthFile | Where-Object {
            $_.Trim() -ne "import site"
        })
        if ($pthLines -notcontains "..\..\host") {
            $pthLines += "..\..\host"
        }
        $pthLines += "import site"
        [IO.File]::WriteAllLines($pthFile, [string[]]$pthLines,
            [Text.UTF8Encoding]::new($false))
    }

    $startHost = "@echo off`r`nset PYTHONUTF8=1`r`n" +
        "set THERMAL_DATA_DIR=%ProgramData%\ThermalOrchestrator\shared`r`n" +
        "cd /d `"%~dp0host`"`r`n" +
        "`"%~dp0runtime\python\python.exe`" server.py %*`r`n"
    [IO.File]::WriteAllText((Join-Path $stage "Start-Host.cmd"), $startHost,
        [Text.UTF8Encoding]::new($false))
    @{ version = $Version; model_bundled = $false; created_at = (Get-Date).ToString("o") } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage "payload-manifest.json") `
            -Encoding utf8

    $payloadItems = Get-ChildItem -LiteralPath $stage -Force |
        Select-Object -ExpandProperty FullName
    Compress-Archive -LiteralPath $payloadItems -DestinationPath $zip -Force
    if (Test-Path -LiteralPath $OutputDirectory) {
        Remove-Item -LiteralPath $OutputDirectory -Recurse -Force
    }
    dotnet publish (Join-Path $repoRoot "installer\Bootstrapper\ThermalOrchestrator.Bootstrapper.csproj") `
        -c Release -o $OutputDirectory -p:PayloadZip=$zip
    if ($LASTEXITCODE -ne 0) { throw "Không publish được bootstrapper." }
    # PDB không cần cho bộ cài một-file; giữ thư mục phát hành đúng một artifact.
    $symbolFile = Join-Path $OutputDirectory "ThermalOrchestrator.pdb"
    if (Test-Path -LiteralPath $symbolFile) {
        Remove-Item -LiteralPath $symbolFile -Force
    }
    Write-Host "Đã tạo $OutputDirectory\ThermalOrchestrator.exe" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
}
