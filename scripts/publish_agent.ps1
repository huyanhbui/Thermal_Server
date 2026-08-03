$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $repoRoot "agent")
$output = Join-Path $repoRoot "publish\NodeAgent"
if (Test-Path -LiteralPath $output) {
    Remove-Item -LiteralPath $output -Recurse -Force
}
dotnet publish -c Release -r win-x64 --self-contained -p:PublishSingleFile=true `
    -o $output
if (Test-Path -LiteralPath (Join-Path $output "config.json")) {
    Remove-Item -LiteralPath (Join-Path $output "config.json") -Force
}
Pop-Location
