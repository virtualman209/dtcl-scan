@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Cai dat DTCLScan

rem ---- 1. Python
python -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [!] Chua co Python. Dang cai Python 3 qua winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    echo.
    echo Cai Python xong. Hay DONG cua so nay va chay lai install.bat.
    pause
    exit /b
)

rem ---- 2. Thu vien Python (numpy, opencv)
python -c "import cv2, numpy" >nul 2>nul
if errorlevel 1 (
    echo [*] Dang cai thu vien numpy + opencv...
    python -m pip install --user --upgrade --disable-pip-version-check numpy opencv-python-headless
)

rem ---- 3. ffmpeg
if exist "bin\ffmpeg.exe" goto :tess
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [!] Chua co ffmpeg. Dang cai ffmpeg qua winget...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
)

:tess
rem ---- 4. Tesseract OCR
python -c "import core,sys; sys.exit(0 if core.find_bin('tesseract') else 1)" >nul 2>nul
if errorlevel 1 (
    echo [!] Chua co Tesseract OCR. Dang cai qua winget ^(co the hien hop thoai xin quyen^)...
    winget install -e --id UB-Mannheim.TesseractOCR --accept-source-agreements --accept-package-agreements
)

rem ---- 5. Du lieu ngon ngu OCR (tieng Anh + tieng Viet)
if not exist "tessdata" mkdir tessdata
for %%L in (eng vie) do (
    if not exist "tessdata\%%L.traineddata" (
        echo [*] Tai du lieu OCR: %%L
        powershell -NoProfile -Command "try { Invoke-WebRequest 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/%%L.traineddata' -OutFile 'tessdata\%%L.traineddata' -UseBasicParsing } catch { Write-Host 'Tai that bai:' $_ }"
    )
)

:install
call register.bat
echo.
python install.py --check >nul 2>nul
if errorlevel 1 (
    echo [!] Van con thieu thanh phan ^(xem dong KHONG TIM THAY o tren^).
    echo     Neu vua cai ffmpeg / Tesseract, hay DONG cua so nay va chay lai install.bat.
) else (
    echo Xong! Mo DTCLScan tu Start Menu / Desktop, hoac chuot phai vao file video ^> DTCLScan.
)
echo Lan dau dung: bam "Can chinh vung..." de khoanh dung vi tri vang / vong / cua hang tren video cua ban.
pause
