@echo off
cd /d "%~dp0"
python install.py --unreg > "%TEMP%\dtclscan_unmenu.reg"
reg import "%TEMP%\dtclscan_unmenu.reg"
del "%TEMP%\dtclscan_unmenu.reg" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\shortcut.ps1" -Remove
echo Da go DTCLScan khoi menu chuot phai, Start Menu va Desktop.
echo (Muon xoa han: xoa thu muc %CD%)
pause
