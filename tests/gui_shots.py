"""Kiểm thử giao diện (TC9) dưới Xvfb: mở màn hình chính, Cài đặt, Căn chỉnh vùng, bấm "Thử đọc tất cả vùng"
trên video dựng từ hud_3-5_a, chụp màn hình và kiểm tra không bị cắt chữ/nút.

    xvfb-run -a -s "-screen 0 1366x768x24" python3 tests/gui_shots.py [thư_mục_ảnh]

Cần Python có tkinter. Thoát mã 0 nếu đạt, 1 nếu có lỗi (in lý do). Ảnh lưu vào _review/x_shots/ (mặc định).
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import core  # noqa: E402

OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "_review", "x_shots")
os.makedirs(OUT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="dtcl gui ")
# không đụng settings / profiles thật của người dùng
core.SETTINGS_PATH = os.path.join(TMP, "settings.json")
core.PROFILE_DIR = os.path.join(TMP, "profiles")

loader = importlib.machinery.SourceFileLoader("dtclscan_app", os.path.join(ROOT, "dtclscan.pyw"))
spec = importlib.util.spec_from_loader("dtclscan_app", loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)
tk = app.tk

problems = []


def make_video():
    path = os.path.join(TMP, "trận thử.mp4")
    img = os.path.join(ROOT, "tests", "fixtures", "real", "hud_3-5_a.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", "10", "-framerate", "5", "-i", img,
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", path], check=True)
    return path


def pump(root, sec):
    """Chờ `sec` giây trong khi vòng lặp giao diện vẫn chạy (gọi từ luồng kịch bản)."""
    time.sleep(sec)


def on_ui(root, fn):
    """Chạy fn trên luồng giao diện, chờ kết quả."""
    import threading
    box, ev = [], threading.Event()

    def run():
        try:
            box.append((True, fn()))
        except Exception as e:  # noqa: BLE001
            box.append((False, e))
        ev.set()
    app.ui_call(run)
    ev.wait(60)
    if not box:
        raise RuntimeError("giao diện không phản hồi")
    ok, v = box[0]
    if not ok:
        raise v
    return v


def shot(name):
    p = os.path.join(OUT, name)
    subprocess.run(["import", "-window", "root", p], check=False)
    return p


def check_fit(win, label):
    """Nội dung không bị cắt: kích thước yêu cầu của mọi widget con nằm trong cửa sổ, cửa sổ nằm trong màn hình."""
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    if x < 0 or y < 0 or x + w > sw or y + h > sh:
        problems.append(f"{label}: cửa sổ {w}x{h}+{x}+{y} tràn màn hình {sw}x{sh}")
    rw, rh = win.winfo_reqwidth(), win.winfo_reqheight()
    if rw > w + 2 or rh > h + 2:
        problems.append(f"{label}: nội dung cần {rw}x{rh} nhưng cửa sổ chỉ {w}x{h} (bị cắt)")

    def walk(wd):
        for c in wd.winfo_children():
            if isinstance(c, tk.Toplevel):
                continue
            if c.winfo_ismapped():
                cx, cy = c.winfo_rootx() - x, c.winfo_rooty() - y
                cw, ch = c.winfo_width(), c.winfo_height()
                if cx + cw > w + 2 or cy + ch > h + 2:
                    try:
                        txt = c.cget("text")
                    except Exception:
                        txt = c.winfo_class()
                    problems.append(f"{label}: widget '{txt}' ({c.winfo_class()}) nằm ngoài cửa sổ")
                if c.winfo_class() in ("TButton", "TLabel", "TCheckbutton") and cw < c.winfo_reqwidth() - 2:
                    problems.append(f"{label}: '{c.cget('text')}' bị cắt chữ ({cw} < {c.winfo_reqwidth()})")
            walk(c)
    walk(win)


def script(root, video, result):
    try:
        core.set_settings(ask_open=False)          # không hỏi "Mở báo cáo?" (sẽ chặn kịch bản)
        on_ui(root, lambda: setattr(root, "_win", app.HomeWindow(root, [video])))
        win = root._win
        pump(root, 1.5)
        on_ui(root, lambda: check_fit(root, "Màn hình chính"))
        shot("01_man_hinh_chinh.png")

        # Phân tích từ giao diện (video 10 giây), rồi thử Huỷ giữa chừng
        on_ui(root, win.start)
        t0 = time.time()
        while time.time() - t0 < 300:
            pump(root, 0.5)
            if not on_ui(root, lambda: win._busy):
                break
        state = on_ui(root, lambda: win.plabel.cget("text"))
        log = on_ui(root, lambda: win.log.get("1.0", "end"))
        shot("01b_phan_tich_xong.png")
        if state != "Xong" or "Traceback" in log:
            problems.append(f"Phân tích từ giao diện: trạng thái {state!r}, log: {log[-300:]!r}")
        on_ui(root, win.start)
        pump(root, 1.0)
        on_ui(root, win.start)                    # bấm "■ Dừng"
        t0 = time.time()
        while time.time() - t0 < 120:
            pump(root, 0.3)
            if not on_ui(root, lambda: win._busy):
                break
        state = on_ui(root, lambda: win.plabel.cget("text"))
        if state not in ("Đã huỷ", "Xong"):
            problems.append(f"Huỷ từ giao diện: trạng thái {state!r}")
        print("Huỷ giữa chừng ->", state)

        dlg = on_ui(root, lambda: app.SettingsDialog(root))
        pump(root, 1.0)
        on_ui(root, lambda: check_fit(dlg.top, "Cài đặt"))
        shot("02_cai_dat.png")
        on_ui(root, dlg.top.destroy)

        cal = on_ui(root, lambda: app.CalibrateWindow(root, video, "default_1080p"))
        t0 = time.time()
        while cal.frame is None and time.time() - t0 < 30:
            pump(root, 0.3)
        pump(root, 3.0)
        if cal.frame is None:
            problems.append("Căn chỉnh vùng: không tải được khung hình")
        on_ui(root, lambda: check_fit(cal.top, "Căn chỉnh vùng"))
        shot("03_can_chinh.png")
        on_ui(root, cal.test_all)
        t0 = time.time()
        items = []
        while time.time() - t0 < 180:
            pump(root, 0.5)
            items = on_ui(root, lambda: list(cal.lst.get(0, "end")))
            if items and "đang đọc" not in items[0]:
                break
        pump(root, 0.5)
        shot("04_thu_doc_tat_ca.png")
        result["items"] = items
        result["keys"] = list(cal.keys)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        problems.append(f"kịch bản lỗi: {e}")
    finally:
        app.ui_call(root.destroy)


def main():
    import threading
    video = make_video()
    root = tk.Tk()
    app.setup_style(root)
    app.start_ui_pump(root)
    result = {}
    threading.Thread(target=script, args=(root, video, result), daemon=True).start()
    root.mainloop()
    items = result.get("items", [])
    keys = result.get("keys", [])
    with open(os.path.join(OUT, "thu_doc.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    want = {"round": "3-5", "gold": "43", "level": "7", "xp": "0/56", "shop1": "Kha'Zix", "shop2": "Teemo",
            "shop3": "Cassiopeia", "shop5": "Mâm Non"}
    import ocr
    if len(items) == len(keys) and keys:
        for k, v in want.items():
            line = items[keys.index(k)]
            got = line.split(":", 1)[-1].strip()
            if ocr.norm(got) != ocr.norm(v):
                problems.append(f"Thử đọc: {k} = {got!r}, cần {v!r}")
        line4 = items[keys.index("shop4")]
        if not line4.startswith("✗"):
            problems.append(f"Thử đọc: ô cửa hàng 4 trống nhưng đọc ra {line4!r}")
    else:
        problems.append("Thử đọc: không có kết quả")
    shutil.rmtree(TMP, ignore_errors=True)
    print("Ảnh chụp:", OUT)
    print("\n".join(items))
    if problems:
        print("\nLỖI GIAO DIỆN:\n  " + "\n  ".join(problems))
        return 1
    print("GUI OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
