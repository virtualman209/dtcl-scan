"""Tạo cấu hình + file .reg cho menu chuột phải DTCLScan.

Python bản Microsoft Store bị Windows cách ly: ghi registry qua winreg sẽ vào
một bản sao riêng mà Explorer không thấy. Vì vậy script này chỉ IN nội dung
.reg ra stdout, còn register.bat dùng `reg import` (chạy ngoài Python) để ghi thật.

    python install.py --config   # lưu đường dẫn ffmpeg/tesseract vào config.json, in thông tin
    python install.py --reg      # in file .reg (UTF-16) để cài menu
    python install.py --unreg    # in file .reg để gỡ menu
    python install.py --check    # kiểm tra đủ thành phần chưa (exit code 1 nếu thiếu)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

ROOT = r"HKEY_CURRENT_USER\Software\Classes"
KEY = "DTCLScan"
APP = core.APP_DIR
SCRIPT = os.path.join(APP, "dtclscan.pyw")
ICON = os.path.join(APP, "dtclscan.ico")


def pythonw():
    p = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return p if os.path.isfile(p) else sys.executable


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def cmd(mode, arg="%1"):
    return f'"{pythonw()}" "{SCRIPT}" {mode}' + (f' "{arg}"' if arg else "")


def reg_text(install=True):
    out = ["Windows Registry Editor Version 5.00", ""]
    icon = f'"Icon"="{esc(ICON)}"' if os.path.isfile(ICON) else None
    items = [("analyze", "Phân tích trận ĐTCL", cmd("analyze")),
             ("calibrate", "Căn chỉnh vùng HUD…", cmd("calibrate")),
             ("update", "Kiểm tra cập nhật", cmd("update", None))]
    for ext in core.VIDEO_EXT:
        base = f"{ROOT}\\SystemFileAssociations\\{ext}"
        root = f"{base}\\shell\\{KEY}"
        out += [f"[-{root}]", ""]
        if not install:
            continue
        out += [f"[{root}]", '"MUIVerb"="DTCLScan"', '"SubCommands"=""', '"MultiSelectModel"="Player"']
        out += [icon, ""] if icon else [""]
        for n, (verb, label, command) in enumerate(items, 1):
            k = f"{root}\\shell\\{n:02d}{verb}"
            out += [f"[{k}]", f'"MUIVerb"="{esc(label)}"', '"MultiSelectModel"="Player"']
            out += [icon] if icon else []
            out += ["", f"[{k}\\command]", f'@="{esc(command)}"', ""]
    return "\r\n".join(out) + "\r\n"


def write_config():
    cfg = {}
    for b in ("ffmpeg", "ffprobe", "tesseract"):
        p = core.find_bin(b)
        if p:
            cfg[b] = os.path.abspath(p)
    with open(core.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("  Python    : " + pythonw())
    for b in ("ffmpeg", "ffprobe", "tesseract"):
        print(f"  {b:10}: " + (cfg.get(b) or "KHÔNG TÌM THẤY"))
    td = core.TESSDATA_DIR
    langs = sorted(f[:-12] for f in os.listdir(td) if f.endswith(".traineddata")) if os.path.isdir(td) else []
    print("  OCR lang  : " + (", ".join(langs) if langs else "dùng bộ ngôn ngữ đi kèm Tesseract"))
    if "ffmpeg" not in cfg or "ffprobe" not in cfg:
        print("\n!! Thiếu ffmpeg. Cài bằng:  winget install Gyan.FFmpeg   rồi chạy lại install.bat")
        print("   hoặc chép ffmpeg.exe, ffprobe.exe vào thư mục: " + os.path.join(APP, "bin"))
    if "tesseract" not in cfg:
        print("\n!! Thiếu Tesseract OCR. Cài bằng:  winget install UB-Mannheim.TesseractOCR   rồi chạy lại install.bat")
    elif "vie" not in langs:
        try:
            import ocr
            have_vie = "vie" in ocr.available_langs()
        except Exception:  # noqa: BLE001
            have_vie = False
        if not have_vie:
            print("\n!! Thiếu dữ liệu OCR tiếng Việt (vie.traineddata). Chạy lại install.bat để tải, hoặc chép vào: "
                  + td)


def check():
    miss = core.missing_bins()
    if "tesseract" not in miss:
        try:
            import ocr
            if "vie" not in ocr.available_langs():
                miss.append("tessdata-vie")         # thiếu dữ liệu tiếng Việt → tên tộc/hệ đọc kém
        except Exception:  # noqa: BLE001
            miss.append("tessdata-vie")
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        miss.append("opencv")
    print(" ".join(miss))
    return 1 if miss else 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--config"
    if arg == "--config":
        write_config()
    elif arg == "--check":
        sys.exit(check())
    elif arg == "--pythonw":
        print(pythonw())
    elif arg in ("--reg", "--unreg"):
        sys.stdout.buffer.write(reg_text(arg == "--reg").encode("utf-16"))   # có BOM
        sys.stdout.flush()
    else:
        sys.exit(__doc__)
