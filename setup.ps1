# Cài DTCLScan chỉ bằng 1 lệnh (PowerShell):
#   irm https://raw.githubusercontent.com/virtualman209/dtcl-scan/main/setup.ps1 | iex
$ErrorActionPreference = "Stop"
$repo = "virtualman209/dtcl-scan"
$dest = Join-Path $env:LOCALAPPDATA "DTCLScan"
$zip  = Join-Path $env:TEMP "DTCLScan.zip"
$tmp  = Join-Path $env:TEMP "DTCLScan_setup"
$keep = @("config.json", "settings.json", "profiles", "tessdata", "champions.txt", "bin")

Write-Host "Đang tải DTCLScan từ GitHub..." -ForegroundColor Cyan
Invoke-WebRequest "https://codeload.github.com/$repo/zip/refs/heads/main" -OutFile $zip -UseBasicParsing
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive $zip $tmp -Force
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1
New-Item -ItemType Directory -Force $dest | Out-Null
Get-ChildItem $src.FullName -Force | Where-Object {
    -not ((Test-Path (Join-Path $dest $_.Name)) -and ($keep -contains $_.Name))
} | ForEach-Object { Copy-Item $_.FullName $dest -Recurse -Force }
Remove-Item $zip, $tmp -Recurse -Force

Write-Host "Đã chép vào $dest" -ForegroundColor Green
Start-Process -FilePath (Join-Path $dest "install.bat") -WorkingDirectory $dest -Wait
