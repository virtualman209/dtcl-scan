# Tạo / xoá lối tắt DTCLScan trên Start Menu và Desktop.
param([string]$PythonW, [string]$AppDir, [switch]$Remove)
$places = @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))
foreach ($p in $places) {
    $lnk = Join-Path $p "DTCLScan.lnk"
    if ($Remove) { Remove-Item $lnk -ErrorAction SilentlyContinue; continue }
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $s.TargetPath = $PythonW
    $s.Arguments = '"' + (Join-Path $AppDir "dtclscan.pyw") + '"'
    $s.WorkingDirectory = $AppDir
    $s.IconLocation = (Join-Path $AppDir "dtclscan.ico") + ",0"
    $s.Description = "DTCLScan - bóc tách dữ liệu trận ĐTCL từ video"
    $s.Save()
}
