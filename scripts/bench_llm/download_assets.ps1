#Requires -Version 5.1
<#
.SYNOPSIS
    Tai llama-server (pin tag) + GGUF Q4_K_M; verify SHA256 tu models.json.

.DESCRIPTION
    File .ps1 can BOM UTF-8. Script nay dung ASCII trong chuoi in de tranh
    loi codepage PowerShell 5.1; noi dung tieng Viet day du nam o README.md.

.PARAMETER BuildOnnx
    Thu convert ONNX INT4 bang onnxruntime_genai.models.builder (cham).

.PARAMETER Models
    Danh sach id cach nhau boi dau phay, hoac 'all'.
#>
param(
    [switch]$BuildOnnx,
    [string]$Models = "all"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Assets = Join-Path $Root "assets"
$ModelsJson = Join-Path $Root "models.json"

function Assert-Sha256 {
    param([string]$Path, [string]$Expected, [string]$Label)
    if (-not $Expected) {
        throw "Missing sha256 in catalog for $Label"
    }
    $got = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    $exp = $Expected.ToLowerInvariant()
    if ($got -ne $exp) {
        throw "SHA256 mismatch ($Label): expected $exp got $got"
    }
    Write-Host "[BENCH] SHA256 OK: $Label"
}

New-Item -ItemType Directory -Force -Path $Assets | Out-Null
$catalog = Get-Content -LiteralPath $ModelsJson -Encoding UTF8 | ConvertFrom-Json

# --- llama.cpp ---
$tag = $catalog.llama_cpp.tag
$asset = $catalog.llama_cpp.asset
$url = $catalog.llama_cpp.url
$zipPath = Join-Path $Assets $asset
$dest = Join-Path $Assets ("llama-" + $tag)
$exeName = $catalog.llama_cpp.exe_name

if (-not (Test-Path -LiteralPath $zipPath)) {
    Write-Host "[BENCH] Downloading $asset ..."
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
}
Assert-Sha256 -Path $zipPath -Expected $catalog.llama_cpp.zip_sha256 -Label $asset

$exePath = Join-Path $dest $exeName
if (-not (Test-Path -LiteralPath $exePath)) {
    Write-Host "[BENCH] Extracting to $dest ..."
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $dest -Force
} else {
    Write-Host "[BENCH] llama-server already present."
}
Assert-Sha256 -Path $exePath -Expected $catalog.llama_cpp.exe_sha256 -Label $exeName
$impl = Join-Path $dest $catalog.llama_cpp.impl_dll
if (Test-Path -LiteralPath $impl) {
    Assert-Sha256 -Path $impl -Expected $catalog.llama_cpp.impl_dll_sha256 -Label $catalog.llama_cpp.impl_dll
}

# --- GGUF ---
$modelIds = @()
if ($Models -eq "all") {
    $modelIds = @($catalog.models.PSObject.Properties.Name)
} else {
    $modelIds = $Models.Split(",") | ForEach-Object { $_.Trim() }
}

$ggufDir = Join-Path $Assets "gguf"
New-Item -ItemType Directory -Force -Path $ggufDir | Out-Null

foreach ($id in $modelIds) {
    $m = $catalog.models.$id
    if (-not $m) { Write-Warning "Unknown model id: $id"; continue }
    $fn = $m.gguf.filename
    $out = Join-Path $ggufDir $fn
    if (-not ((Test-Path -LiteralPath $out) -and ((Get-Item -LiteralPath $out).Length -gt 1MB))) {
        Write-Host "[BENCH] Downloading GGUF $fn ..."
        Invoke-WebRequest -Uri $m.gguf.url -OutFile $out -UseBasicParsing
    }
    Assert-Sha256 -Path $out -Expected $m.gguf.sha256 -Label $fn
}

if ($BuildOnnx) {
    Write-Host "[BENCH] Building ONNX INT4 (requires onnxruntime-genai) ..."
    foreach ($id in $modelIds) {
        $m = $catalog.models.$id
        $outDir = Join-Path $Assets (Join-Path "onnx" $id)
        if (Test-Path -LiteralPath (Join-Path $outDir "genai_config.json")) {
            Write-Host "[BENCH] ONNX ok: $id"
            continue
        }
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        $hf = $m.onnx.hf_id
        python -m onnxruntime_genai.models.builder `
            -m $hf -o $outDir -p int4 -e cpu `
            --extra_options int4_accuracy_level=4
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "ONNX convert failed for $id — mark N/A in bench."
        }
    }
}

Write-Host "[BENCH] Done. Assets under $Assets"
