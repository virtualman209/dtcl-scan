"""DTCLScan — bóc tách dữ liệu trận Đấu Trường Chân Lý (TFT) từ video quay màn hình.

Cách gọi:
    pythonw dtclscan.pyw                      # màn hình chính (kéo thả video vào)
    pythonw dtclscan.pyw analyze <video>      # mở màn hình chính với video đã chọn
    pythonw dtclscan.pyw calibrate <video>    # căn chỉnh vùng HUD trên video
    pythonw dtclscan.pyw update               # kiểm tra cập nhật
"""
import base64
import json
import os
import queue
import socket
import sys
import threading
import time
import traceback
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

import tkinter as tk  # noqa: E402
from tkinter import ttk, filedialog, messagebox, simpledialog  # noqa: E402

APP = "DTCLScan"
LOG = os.path.join(os.environ.get("TEMP") or __import__("tempfile").gettempdir(), "dtclscan.log")
PORT = 47873


# ============================================================ gom file từ nhiều lần gọi (Explorer)
def gather_paths(mode, paths):
    """Explorer gọi tool 1 lần cho MỖI file được chọn. Tiến trình đầu tiên mở cổng
    localhost, gom đường dẫn từ các tiến trình sau rồi mở 1 cửa sổ duy nhất."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        srv.bind(("127.0.0.1", PORT))
    except OSError:
        srv.close()
        for _ in range(40):  # gửi cho tiến trình chính rồi thoát
            try:
                with socket.create_connection(("127.0.0.1", PORT), timeout=1) as c:
                    c.sendall(json.dumps(paths).encode("utf-8"))
                return None
            except OSError:
                time.sleep(0.05)
        return paths
    srv.listen(64)
    srv.settimeout(0.1)
    got = list(paths)
    deadline = time.time() + 0.9
    while time.time() < deadline:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        with conn:
            buf = b""
            conn.settimeout(1)
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                got += json.loads(buf.decode("utf-8"))
            except Exception:
                pass
        deadline = time.time() + 0.5
    srv.close()
    seen, out = set(), []
    for p in got:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


# ============================================================ gọi giao diện từ luồng phụ
# Tkinter không an toàn khi gọi từ luồng khác: luồng phụ chỉ bỏ việc vào hàng đợi,
# luồng giao diện lấy ra chạy mỗi 40ms.
_UIQ = queue.Queue()


def ui_call(fn, delay_ms=0):
    _UIQ.put((time.time() + delay_ms / 1000.0, fn))


def start_ui_pump(root):
    pending = []

    def poll():
        try:
            while True:
                pending.append(_UIQ.get_nowait())
        except queue.Empty:
            pass
        now = time.time()
        for item in [p for p in pending if p[0] <= now]:
            pending.remove(item)
            try:
                item[1]()
            except tk.TclError:
                pass                     # cửa sổ đã đóng
            except Exception:  # noqa: BLE001
                root.report_callback_exception(*sys.exc_info())
        try:
            root.after(40, poll)
        except tk.TclError:
            pass
    poll()


# ============================================================ tiện ích giao diện
def setup_style(root):
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure("Big.TButton", padding=(16, 8), font=("Segoe UI", 11, "bold"))
    style.configure("Hint.TLabel", foreground="#666")
    root.option_add("*Font", ("Segoe UI", 10))


def center(win, w, h):
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w, h = min(w, sw), min(h, sh - 80)          # chừa thanh tiêu đề + taskbar Windows
    x = max(0, (sw - w) // 2)
    y = max(0, min((sh - h) // 3, sh - 80 - h))
    win.geometry(f"{w}x{h}+{x}+{y}")


def fit(win, w, h):
    """Đặt cỡ cửa sổ đủ chứa toàn bộ nội dung (font trên máy người dùng có thể to hơn dự tính), không quá màn hình."""
    win.update_idletasks()
    center(win, max(w, win.winfo_reqwidth()), max(h, win.winfo_reqheight()))


def write_log(text):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + text + "\n")
    except OSError:
        pass


def st_bool(key):
    v = core.get_settings().get(key, True)
    return v if isinstance(v, bool) else str(v).strip().lower() not in ("0", "false", "no", "")


def open_file(path):
    """Mở file bằng trình duyệt / chương trình mặc định (đường dẫn có dấu, khoảng trắng vẫn được)."""
    import pathlib
    try:
        if os.name == "nt":
            os.startfile(os.path.abspath(path))       # noqa: S606
        else:
            webbrowser.open(pathlib.Path(os.path.abspath(path)).as_uri())
    except Exception:  # noqa: BLE001
        webbrowser.open(pathlib.Path(os.path.abspath(path)).as_uri())


def reveal(path):
    if os.name == "nt":
        import subprocess
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def check_deps(parent=None):
    miss = core.missing_bins()
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        miss.append("opencv-python / numpy (pip)")
    if not miss:
        return True
    messagebox.showerror(APP, "Thiếu: " + ", ".join(miss) + "\n\nHãy chạy lại install.bat trong thư mục cài đặt.\n"
                         "(Hoặc chép ffmpeg.exe, ffprobe.exe vào thư mục 'bin'; cài Tesseract OCR.)", parent=parent)
    return False


def parse_time(text):
    text = (text or "").strip()
    if not text:
        return 0.0
    parts = text.replace(",", ".").split(":")
    v = 0.0
    for p in parts:
        v = v * 60 + float(p or 0)
    return v


def enable_drop(root):
    """Kéo thả file từ Explorer vào cửa sổ. Khi thả, gọi root._on_drop(list_paths)."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    set_long.restype = ctypes.c_void_p
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    WM_DROPFILES = 0x0233
    old = [None]

    def proc(hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            files = []
            try:
                n = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                for i in range(n):
                    ln = shell32.DragQueryFileW(wparam, i, None, 0)
                    buf = ctypes.create_unicode_buffer(ln + 1)
                    shell32.DragQueryFileW(wparam, i, buf, ln + 1)
                    files.append(buf.value)
            finally:
                shell32.DragFinish(wparam)
            cb = getattr(root, "_on_drop", None)
            if cb and files:
                root.after(0, lambda: cb(files))
            return 0
        return user32.CallWindowProcW(old[0], hwnd, msg, wparam, lparam)

    root.update_idletasks()
    hwnd = int(root.wm_frame(), 16)
    root._drop_proc = WNDPROC(proc)
    old[0] = set_long(hwnd, -4, ctypes.cast(root._drop_proc, ctypes.c_void_p))
    shell32.DragAcceptFiles(hwnd, True)


def expand_paths(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(os.path.join(p, f) for f in os.listdir(p) if core.is_video(f))
        elif os.path.isfile(p) and core.is_video(p):
            out.append(p)
    return out


def to_photo(img_bgr, max_w, max_h):
    """ảnh BGR (numpy) → tk.PhotoImage, thu nhỏ vừa khung. Trả (photo, scale)."""
    import cv2
    h, w = img_bgr.shape[:2]
    s = min(max_w / w, max_h / h, 1.0 if max(w, h) > 400 else 8.0)
    if s != 1.0:
        img_bgr = cv2.resize(img_bgr, (max(1, int(w * s)), max(1, int(h * s))),
                             interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_NEAREST)
    ok, png = cv2.imencode(".png", img_bgr)
    return tk.PhotoImage(data=base64.b64encode(png.tobytes()).decode("ascii")), s


# ============================================================ màn hình chính
class HomeWindow:
    def __init__(self, root, paths=()):
        import layout
        self.root = root
        self.layout = layout
        root.title(APP)
        center(root, 760, 700)
        self.files = expand_paths(paths)
        self._busy = False
        self._cancel = False
        st = core.get_settings()

        main = ttk.Frame(root, padding=14)
        main.pack(fill="both", expand=True)
        head = ttk.Frame(main)
        head.pack(fill="x")
        ttk.Label(head, text="DTCLScan", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(head, text="  bóc tách dữ liệu trận ĐTCL từ video", style="Hint.TLabel").pack(side="left", pady=(8, 0))

        self.zone = tk.Canvas(main, height=110, bg="#f7f9fc", highlightthickness=0, cursor="hand2")
        self.zone.pack(fill="x", pady=10)
        self.zone.bind("<Configure>", lambda e: self.draw_zone())
        self.zone.bind("<Button-1>", lambda e: self.pick())
        row = ttk.Frame(main)
        row.pack(fill="x")
        ttk.Button(row, text="+ Chọn video…", command=self.pick).pack(side="left")
        ttk.Button(row, text="Bỏ hết", command=self.clear).pack(side="left", padx=6)

        opt = ttk.LabelFrame(main, text="Tuỳ chọn", padding=10)
        opt.pack(fill="x", pady=10)
        ttk.Label(opt, text="Profile vùng HUD:").grid(row=0, column=0, sticky="w")
        self.profile = tk.StringVar(value=st["profile"])
        self.cb_prof = ttk.Combobox(opt, textvariable=self.profile, state="readonly", width=24,
                                    values=layout.list_profiles())
        self.cb_prof.grid(row=0, column=1, sticky="w", padx=6)
        self.cb_prof.bind("<<ComboboxSelected>>", lambda e: (core.set_settings(profile=self.profile.get()),
                                                             self.prof_hint()))
        ttk.Button(opt, text="Căn chỉnh vùng…", command=self.calibrate).grid(row=0, column=2, padx=4)
        self.lbl_prof = ttk.Label(opt, text="", style="Hint.TLabel")
        self.lbl_prof.grid(row=1, column=1, columnspan=3, sticky="w", padx=6)

        ttk.Label(opt, text="Số khung/giây đọc:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.fps = tk.StringVar(value=str(st["fps"]))
        ttk.Combobox(opt, textvariable=self.fps, values=["1", "2", "3", "4"], width=5, state="readonly"
                     ).grid(row=2, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(opt, text="2 là vừa · 3–4 chính xác hơn nhưng chậm hơn",
                  style="Hint.TLabel").grid(row=2, column=2, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(opt, text="Chỉ xử lý đoạn:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        seg = ttk.Frame(opt)
        seg.grid(row=3, column=1, columnspan=3, sticky="w", padx=6, pady=(8, 0))
        self.t_from, self.t_to = tk.StringVar(), tk.StringVar()
        ttk.Label(seg, text="từ").pack(side="left")
        ttk.Entry(seg, textvariable=self.t_from, width=8).pack(side="left", padx=4)
        ttk.Label(seg, text="đến").pack(side="left")
        ttk.Entry(seg, textvariable=self.t_to, width=8).pack(side="left", padx=4)
        ttk.Label(seg, text="(mm:ss, để trống = cả video)", style="Hint.TLabel").pack(side="left")

        self.v_key = tk.BooleanVar(value=st["keyframes"])
        self.v_aib = tk.BooleanVar(value=st["ai_board"])
        self.v_aic = tk.BooleanVar(value=st["ai_coach"])
        self.v_pack = tk.BooleanVar(value=st.get("chat_pack", True))
        chk = ttk.Frame(opt)
        chk.grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Checkbutton(chk, text="Lưu ảnh chốt mỗi vòng", variable=self.v_key).pack(side="left")
        ttk.Checkbutton(chk, text="Tạo gói gửi Claude chat (không cần API)", variable=self.v_pack
                        ).pack(side="left", padx=12)
        ttk.Button(chk, text="Cài đặt…", command=self.settings).pack(side="left", padx=4)
        chk2 = ttk.Frame(opt)
        chk2.grid(row=5, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(chk2, text="Nếu có API key:", style="Hint.TLabel").pack(side="left")
        ttk.Checkbutton(chk2, text="AI đọc bàn cờ", variable=self.v_aib).pack(side="left", padx=8)
        ttk.Checkbutton(chk2, text="AI nhận xét trận", variable=self.v_aic).pack(side="left")

        act = ttk.Frame(main)
        act.pack(fill="x")
        self.btn = ttk.Button(act, text="▶  Phân tích", style="Big.TButton", command=self.start)
        self.btn.pack(side="left")
        self.pvar = tk.DoubleVar()
        ttk.Progressbar(act, variable=self.pvar, maximum=100).pack(side="left", fill="x", expand=True, padx=10)
        self.plabel = ttk.Label(act, text="", width=18, anchor="e")
        self.plabel.pack(side="left")

        self.log = tk.Text(main, height=9, font=("Consolas", 9), bg="#fbfbfd", relief="flat", wrap="word")
        self.log.pack(fill="both", expand=True, pady=(10, 0))
        foot = ttk.Frame(main)
        foot.pack(fill="x", pady=(6, 0))
        ttk.Button(foot, text="Kiểm tra cập nhật", command=lambda: manual_update(self.root, keep=True)
                   ).pack(side="right")
        ttk.Label(foot, text="Mẹo: kéo thả video vào cửa sổ. Lần đầu hãy Căn chỉnh vùng cho đúng HUD của bạn.",
                  style="Hint.TLabel").pack(side="left")
        root._on_drop = self.drop
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.prof_hint()
        fit(root, 760, 700)

    # ----------------------------------------------------------- tiện ích
    def prof_hint(self):
        p = self.layout.load(self.profile.get())
        self.lbl_prof.config(text="✓ đã căn chỉnh" if p.get("calibrated") else
                             "⚠ chưa căn chỉnh — toạ độ đang là ước lượng, nên bấm Căn chỉnh vùng trước")

    def write(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def draw_zone(self):
        c = self.zone
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        c.create_rectangle(3, 3, w - 3, h - 3, outline="#9bb3d6", dash=(6, 4), width=2)
        if not self.files:
            c.create_text(w // 2, h // 2 - 10, text="Kéo thả video trận ĐTCL vào đây",
                          font=("Segoe UI", 13), fill="#4a6a99")
            c.create_text(w // 2, h // 2 + 16, text="hoặc bấm để chọn file", font=("Segoe UI", 9), fill="#888")
        else:
            names = [os.path.basename(f) for f in self.files]
            shown = names[:3] + ([f"… và {len(names) - 3} file khác"] if len(names) > 3 else [])
            c.create_text(w // 2, 18, text=f"{len(names)} video", font=("Segoe UI", 11, "bold"), fill="#2d4f80")
            c.create_text(w // 2, 38, text="\n".join(shown), anchor="n", font=("Segoe UI", 9), fill="#444",
                          justify="center")

    def drop(self, paths):
        self.files += [p for p in expand_paths(paths) if p not in self.files]
        self.draw_zone()

    def pick(self):
        fs = filedialog.askopenfilenames(parent=self.root, title="Chọn video trận ĐTCL",
                                         filetypes=[("Video", " ".join("*" + e for e in core.VIDEO_EXT)),
                                                    ("Tất cả", "*.*")])
        self.drop(list(fs))

    def clear(self):
        self.files = []
        self.draw_zone()

    def calibrate(self):
        f = self.files[0] if self.files else filedialog.askopenfilename(
            parent=self.root, title="Chọn 1 video để căn chỉnh vùng HUD",
            filetypes=[("Video", " ".join("*" + e for e in core.VIDEO_EXT))])
        if not f:
            return
        if f not in self.files:
            self.drop([f])
        try:
            CalibrateWindow(self.root, f, self.profile.get(), on_saved=self.profile_saved)
        except core.VideoError as e:
            messagebox.showerror(APP, str(e), parent=self.root)
        except Exception as e:  # noqa: BLE001
            write_log(traceback.format_exc())
            messagebox.showerror(APP, f"Không mở được cửa sổ Căn chỉnh vùng:\n{e}", parent=self.root)

    def profile_saved(self, name):
        self.cb_prof.config(values=self.layout.list_profiles())
        self.profile.set(name)
        core.set_settings(profile=name)
        self.prof_hint()

    def settings(self):
        SettingsDialog(self.root)

    # ----------------------------------------------------------- chạy
    def start(self):
        if self._busy:
            self._cancel = True
            self.btn.config(text="Đang huỷ…")
            return
        if not self.files:
            return self.pick()
        st = core.get_settings()
        if (self.v_aib.get() or self.v_aic.get()) and not st.get("api_key"):
            messagebox.showwarning(APP, "Bạn bật AI nhưng chưa nhập API key.\nBấm Cài đặt… để nhập, "
                                        "hoặc bỏ tick AI.", parent=self.root)
            return
        try:
            t0, t1 = parse_time(self.t_from.get()), parse_time(self.t_to.get())
        except ValueError:
            messagebox.showerror(APP, "Thời gian không hợp lệ (dùng mm:ss).", parent=self.root)
            return
        core.set_settings(profile=self.profile.get(), fps=int(self.fps.get()), keyframes=self.v_key.get(),
                          ai_board=self.v_aib.get(), ai_coach=self.v_aic.get(), chat_pack=self.v_pack.get())
        opts = dict(core.get_settings(), start=t0, end=t1)
        files = list(self.files)
        self._busy, self._cancel = True, False
        self.btn.config(text="■  Dừng")
        t_start = time.time()

        def log(s):
            ui_call(lambda: self.write(s))

        def work():
            import analyze
            reports, err, errors = [], None, []
            for k, f in enumerate(files):
                def prog(p, k=k):
                    tot = (k + p) / len(files)
                    el = time.time() - t_start
                    eta = f" ~{int(el / tot - el)}s" if tot > 0.03 else ""
                    ui_call(lambda: (self.pvar.set(tot * 100), self.plabel.config(text=f"{tot * 100:3.0f}%{eta}")))
                log(f"─── {os.path.basename(f)}")
                try:
                    reports.append(analyze.run_analysis(f, opts, prog, log, lambda: self._cancel))
                except core.Cancelled:
                    err = "cancel"
                    log("Đã huỷ.")
                    break
                except Exception as e:  # noqa: BLE001
                    msg = analyze.friendly_error(e)
                    log("LỖI: " + msg)
                    write_log(traceback.format_exc())
                    errors.append(f"{os.path.basename(f)}: {msg}")
            ui_call(lambda: self.done(reports, err, errors))
        threading.Thread(target=work, daemon=True).start()

    def done(self, reports, err, errors=()):
        self._busy = False
        self._cancel = False
        self.btn.config(text="▶  Phân tích")
        if err == "cancel":
            self.plabel.config(text="Đã huỷ")
            self.pvar.set(0)
            return
        if errors and not reports:
            self.plabel.config(text="Lỗi!")
            messagebox.showerror(APP, "\n\n".join(errors), parent=self.root)
            return
        self.plabel.config(text="Xong" if not errors else "Xong (có lỗi)")
        self.pvar.set(100)
        if errors:
            messagebox.showwarning(APP, f"{len(errors)} video bị lỗi:\n\n" + "\n\n".join(errors), parent=self.root)
        if not st_bool("ask_open"):
            return
        if reports and messagebox.askyesno(APP, f"Đã phân tích {len(reports)} video.\n\nMở báo cáo?\n\n"
                                                "Muốn Claude nhận xét: mở thư mục gui_claude, kéo các ảnh + "
                                                "nội dung cau_hoi.txt vào claude.ai.", parent=self.root):
            for r in reports:
                open_file(r)
                pack = os.path.join(os.path.dirname(r), "gui_claude", "cau_hoi.txt")
                if os.path.isfile(pack):
                    reveal(pack)

    def on_close(self):
        if self._busy and not messagebox.askyesno(APP, "Đang xử lý. Huỷ và thoát?", parent=self.root):
            return
        self._cancel = True
        self.root.destroy()


# ============================================================ cài đặt
class SettingsDialog:
    def __init__(self, root):
        st = core.get_settings()
        top = self.top = tk.Toplevel(root)
        top.title("Cài đặt DTCLScan")
        top.transient(root)
        center(top, 560, 290)
        f = ttk.Frame(top, padding=14)
        f.pack(fill="both", expand=True)
        self.vars = {}
        # "Tên trong game" đã bỏ: dòng máu của bạn được nhận ra nhờ số máu TO (không cần tên)
        rows = [("ocr_lang", "Ngôn ngữ OCR", "auto (eng+vie nếu có) · eng · eng+vie"),
                ("api_key", "Claude API key", "chỉ cần khi dùng AI · lấy ở console.anthropic.com"),
                ("model", "Model AI", "vd. claude-sonnet-5-5 (cân bằng) · claude-haiku-5-5 (rẻ hơn)")]
        for i, (k, label, hint) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=i * 2, column=0, sticky="w", pady=(6, 0))
            v = tk.StringVar(value=str(st.get(k, "")))
            ttk.Entry(f, textvariable=v, width=44, show="•" if k == "api_key" else "").grid(
                row=i * 2, column=1, sticky="we", padx=8, pady=(6, 0))
            ttk.Label(f, text=hint, style="Hint.TLabel").grid(row=i * 2 + 1, column=1, sticky="w", padx=8)
            self.vars[k] = v
        ttk.Label(f, text="API key chỉ lưu trong settings.json trên máy bạn. Mỗi ảnh gửi AI là 1 lượt gọi có tính phí.",
                  style="Hint.TLabel", wraplength=520).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))
        b = ttk.Frame(f)
        b.grid(row=10, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Lưu", command=self.save).pack(side="right")
        ttk.Button(b, text="Huỷ", command=top.destroy).pack(side="right", padx=6)
        fit(top, 560, 290)

    def save(self):
        core.set_settings(**{k: v.get().strip() for k, v in self.vars.items()})
        self.top.destroy()


def panel_text(key, crop, lang, src_h=None):
    import ocr
    if key == "traits":
        tr = ocr.parse_traits(ocr.read_traits(crop, lang))
        return ", ".join(f"{t['trait']} {t['count'] or '?'}" for t in tr) or ""
    pl, st = ocr.read_players(crop, lang, src_h=src_h)
    txt = ", ".join(("BẠN " if p["me"] else "") + str(p["hp"]) for p in pl)
    if st == "low_res":
        txt += (f"  (video {src_h}p — dưới 1080p: chữ số máu người khác quá nhỏ, không đọc được; "
                "chỉ đọc máu của bạn. Quay video 1080p để có máu người khác)")
    elif st == "uncertain":
        txt += "  (có dòng đọc sai thứ tự máu giảm dần nên đã bỏ — nên khoanh lại cho sát cột số máu)"
    elif st != "ok":
        txt += "  (ít dòng đọc được — bảng có thể đang hiện thống kê sát thương, hoặc vùng khoanh chưa đúng)"
    return txt


# ============================================================ căn chỉnh vùng HUD
class CalibrateWindow:
    CW, CH = 1200, 675          # kích thước canvas hiển thị khung hình

    def __init__(self, root, video, profile_name, on_saved=None):
        import layout
        self.L = layout
        self.on_saved = on_saved
        self.prof = layout.load(profile_name)
        self.info = core.probe(video)
        self.frame = None
        self.sel = "round"
        self.drag = None
        top = self.top = tk.Toplevel(root)
        top.title(f"Căn chỉnh vùng HUD — {os.path.basename(video)}  [profile: {self.prof['name']}]")
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        self.CW = max(560, min(1200, sw - 400, int((sh - 190) * 16 / 9)))     # vừa màn hình laptop
        self.CH = int(self.CW * 9 / 16)
        self.ZH = 140 if sh >= 900 else 60           # ô phóng to nhỏ lại trên màn hình laptop 768px
        center(top, self.CW + 360, min(sh - 60, max(self.CH + 90, 640)))

        left = ttk.Frame(top, padding=8)
        left.pack(side="left", fill="y")
        # nhóm nút + mẹo đặt cố định ở ĐÁY cột trái (pack trước): màn hình thấp thì phần ảnh phóng to bị thu,
        # không bao giờ mất nút
        ttk.Label(left, text="Mẹo: căn lúc đang chuẩn bị (thấy cửa hàng, số vàng). "
                             "Mỗi độ phân giải nên có 1 profile riêng.",
                  style="Hint.TLabel", wraplength=340).pack(side="bottom", anchor="w", pady=(4, 0))
        btns = ttk.Frame(left)
        btns.pack(side="bottom", fill="x")
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        ttk.Button(btns, text="Lưu", command=self.save).grid(row=0, column=0, sticky="we", padx=(0, 2), pady=2)
        ttk.Button(btns, text="Lưu thành profile mới…", command=self.save_as).grid(row=0, column=1, sticky="we",
                                                                                pady=2)
        ttk.Button(btns, text="Khôi phục toạ độ mặc định", command=self.reset).grid(row=1, column=0, columnspan=2,
                                                                                  sticky="we", pady=2)
        ttk.Button(left, text="Thử đọc tất cả vùng (OCR)", command=self.test_all).pack(side="bottom", fill="x",
                                                                                     pady=(6, 2))
        ttk.Label(left, text="1. Chọn vùng", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.lst = tk.Listbox(left, width=40, height=len(layout.FIELDS), activestyle="none", exportselection=False,
                              font=("Segoe UI", 10))
        self.lst.pack(fill="x")
        # kết quả "Thử đọc" dài (tộc/hệ, cột máu) → cuộn ngang; chọn mục để xem đầy đủ ở ô bên dưới
        xs = ttk.Scrollbar(left, orient="horizontal", command=self.lst.xview)
        xs.pack(fill="x")
        self.lst.config(xscrollcommand=xs.set)
        self.keys = list(layout.FIELDS)
        self.lst.bind("<<ListboxSelect>>", self.on_select)
        self.desc = ttk.Label(left, text="", style="Hint.TLabel", wraplength=340)
        self.desc.pack(anchor="w", pady=(2, 4))
        ttk.Label(left, text="2. Kéo chuột trên ảnh để khoanh · mũi tên: dịch 1px · Shift: đổi cỡ",
                  style="Hint.TLabel", wraplength=340).pack(anchor="w", pady=(0, 2))
        zh = self.ZH
        self._blank = tk.PhotoImage(width=1, height=1)       # có ảnh → width/height tính bằng pixel
        self.zoom = tk.Label(left, bg="#222", image=self._blank, width=300, height=zh)
        self.zoom.pack(fill="x")
        self.zoom2 = tk.Label(left, bg="#fff", image=self._blank, width=300, height=zh)
        self.zoom2.pack(fill="x", pady=(2, 0))
        self.ocr_lbl = tk.Label(left, text="", wraplength=330, font=("Consolas", 9), height=3, anchor="nw",
                                justify="left")
        self.ocr_lbl.pack(anchor="w", fill="x", pady=2)
        right = ttk.Frame(top, padding=8)
        right.pack(side="left", fill="both", expand=True)
        self.cv = tk.Canvas(right, width=self.CW, height=self.CH, bg="#111", highlightthickness=0, cursor="crosshair")
        self.cv.pack()
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=6)
        self.tvar = tk.DoubleVar(value=self.info["duration"] / 3)
        self.tlbl = ttk.Label(bar, text="", width=10)
        self.tlbl.pack(side="left")
        sc = ttk.Scale(bar, from_=0, to=max(1, self.info["duration"] - 0.5), variable=self.tvar,
                       command=lambda v: self.tlbl.config(text=core.fmt_time(float(v))))
        sc.pack(side="left", fill="x", expand=True)
        sc.bind("<ButtonRelease-1>", lambda e: self.load_frame())
        for txt, d in (("−10s", -10), ("−1s", -1), ("+1s", 1), ("+10s", 10)):
            ttk.Button(bar, text=txt, width=5, command=lambda d=d: self.seek(d)).pack(side="left", padx=2)

        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_motion)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        for k in ("Left", "Right", "Up", "Down"):
            top.bind(f"<{k}>", lambda e, k=k: self.nudge(k, False))
            top.bind(f"<Shift-{k}>", lambda e, k=k: self.nudge(k, True))
        self.refresh_list()
        self.lst.selection_set(0)
        self.on_select()
        fit(top, self.CW + 360, self.win_h())
        self.load_frame()

    def win_h(self):
        """Màn hình thấp: dùng hết chiều cao cho phép ngay từ đầu (mô tả từng mục dài ngắn khác nhau)."""
        sh = self.top.winfo_screenheight()
        return self.CH + 90 if sh >= 900 else max(self.CH + 90, sh - 80)

    # ----------------------------------------------------------- khung hình
    def seek(self, d):
        self.tvar.set(min(max(0, self.tvar.get() + d), self.info["duration"] - 0.5))
        self.load_frame()

    def load_frame(self):
        t = self.tvar.get()
        self.tlbl.config(text=core.fmt_time(t) + " …")

        def work():
            fr = core.grab_frame(self.info, t)
            ui_call(lambda: self.show_frame(fr, t))
        threading.Thread(target=work, daemon=True).start()

    def show_frame(self, fr, t):
        self.tlbl.config(text=core.fmt_time(t))
        if fr is None:
            if self.frame is None:
                self.cv.delete("all")
                self.cv.create_text(self.CW // 2, self.CH // 2, fill="#ddd", font=("Segoe UI", 12),
                                    text="Không lấy được khung hình ở thời điểm này — hãy kéo thanh thời gian.")
            return
        first = self.frame is None
        self.frame = fr
        self.photo, self.scale = to_photo(fr, self.CW, self.CH)
        self.fw, self.fh = fr.shape[1], fr.shape[0]
        self.redraw()
        self.update_zoom()
        if first:
            fit(self.top, self.CW + 360, self.win_h())     # ảnh phóng to đã có → đo lại cỡ cửa sổ

    def redraw(self):
        c = self.cv
        c.delete("all")
        if self.frame is None:
            return
        c.create_image(0, 0, image=self.photo, anchor="nw")
        dw, dh = self.fw * self.scale, self.fh * self.scale
        for k, box in self.prof["boxes"].items():
            x1, y1, x2, y2 = box[0] * dw, box[1] * dh, box[2] * dw, box[3] * dh
            on = k == self.sel
            col = "#ff3b3b" if on else "#ffd84a"
            c.create_rectangle(x1, y1, x2, y2, outline=col, width=3 if on else 1)
            c.create_text(x1 + 2, y1 - 2, text=k, anchor="sw", fill=col, font=("Segoe UI", 8, "bold"))

    # ----------------------------------------------------------- danh sách
    def refresh_list(self):
        sel = self.lst.curselection()
        self.lst.delete(0, "end")
        for k in self.keys:
            self.lst.insert("end", "  " + self.L.FIELDS[k][0])
        if sel:
            self.lst.selection_set(sel[0])

    def on_select(self, e=None):
        s = self.lst.curselection()
        if not s:
            return
        self.sel = self.keys[s[0]]
        self.desc.config(text=self.L.FIELDS[self.sel][2])
        self.redraw()
        self.update_zoom()

    # ----------------------------------------------------------- kéo chuột
    def on_press(self, e):
        self.drag = (e.x, e.y)

    def on_motion(self, e):
        if not self.drag:
            return
        self.redraw()
        self.cv.create_rectangle(self.drag[0], self.drag[1], e.x, e.y, outline="#3bff7a", width=2)

    def on_release(self, e):
        if not self.drag or self.frame is None:
            return
        x0, y0 = self.drag
        self.drag = None
        if abs(e.x - x0) < 4 or abs(e.y - y0) < 4:
            self.redraw()
            return
        dw, dh = self.fw * self.scale, self.fh * self.scale
        x1, x2 = sorted((x0, e.x))
        y1, y2 = sorted((y0, e.y))
        self.prof["boxes"][self.sel] = [round(max(0, x1) / dw, 4), round(max(0, y1) / dh, 4),
                                        round(min(dw, x2) / dw, 4), round(min(dh, y2) / dh, 4)]
        self.redraw()
        self.update_zoom()

    def nudge(self, key, resize):
        if self.frame is None:
            return
        b = self.prof["boxes"][self.sel]
        dx = {"Left": -1, "Right": 1}.get(key, 0) / self.fw
        dy = {"Up": -1, "Down": 1}.get(key, 0) / self.fh
        if resize:
            b[2], b[3] = b[2] + dx, b[3] + dy
        else:
            b[0], b[1], b[2], b[3] = b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy
        self.prof["boxes"][self.sel] = [round(v, 4) for v in b]
        self.redraw()
        self.update_zoom()

    # ----------------------------------------------------------- OCR thử
    def update_zoom(self):
        if self.frame is None:
            return
        import ocr
        c = self.L.crop(self.frame, self.prof["boxes"][self.sel])
        self.zphoto, _ = to_photo(c, 300, self.ZH)
        self.zoom.config(image=self.zphoto, width=300, height=self.ZH)
        kind = ocr.field_kind(self.sel, self.L.FIELDS[self.sel][1])
        b = ocr.prep(c, {"traits": "panelw", "players": "panel"}.get(self.sel, kind),
                     scale=3.0 if self.sel in ("traits", "players") else None)
        if b is not None:
            import cv2
            self.zphoto2, _ = to_photo(cv2.cvtColor(b, cv2.COLOR_GRAY2BGR), 300, self.ZH)
            self.zoom2.config(image=self.zphoto2, width=300, height=self.ZH)
        self.ocr_lbl.config(text="đang đọc…")
        frame, sel = self.frame, self.sel
        lang = core.get_settings().get("ocr_lang", "auto")

        def work():
            try:
                c = self.L.crop(frame, self.prof["boxes"][sel])
                if sel in ("traits", "players"):
                    txt = "→ " + panel_text(sel, c, lang, self.info.get("h"))
                else:
                    raw, val = ocr.read_field(c, sel, self.L.FIELDS[sel][1], lang)
                    txt = f"đọc thô: {raw!r}\n→ hiểu là: {val!r}"
            except Exception as ex:  # noqa: BLE001
                txt = f"lỗi OCR: {ex}"
            ui_call(lambda: self.ocr_lbl.config(text=txt) if self.sel == sel else None)
        threading.Thread(target=work, daemon=True).start()

    def test_all(self):
        if self.frame is None:
            return
        import ocr
        lang = core.get_settings().get("ocr_lang", "auto")
        frame = self.frame

        def work():
            res = {}
            for k in self.keys:
                try:
                    c = self.L.crop(frame, self.prof["boxes"][k])
                    if k in ("traits", "players"):
                        v = panel_text(k, c, lang, self.info.get("h"))
                    else:
                        _, v = ocr.read_field(c, k, self.L.FIELDS[k][1], lang)
                except Exception as ex:  # noqa: BLE001
                    v = f"lỗi: {ex}"
                if isinstance(v, list):
                    v = " | ".join(v[:6])
                res[k] = v
            ui_call(lambda: self.show_results(res))
        self.lst.delete(0, "end")
        self.lst.insert("end", "  đang đọc…")
        threading.Thread(target=work, daemon=True).start()

    def show_results(self, res):
        self.lst.delete(0, "end")
        for k in self.keys:
            v = res.get(k)
            mark = "✓" if v not in (None, "", []) else "✗"
            self.lst.insert("end", f"{mark} {self.L.FIELDS[k][0]}:  {v if v not in (None, '') else '—'}")
        self.lst.selection_set(self.keys.index(self.sel))

    # ----------------------------------------------------------- lưu
    def save(self):
        self.prof["calibrated"] = True
        if self.info.get("w"):
            self.prof["resolution"] = f"{self.info['w']}x{self.info['h']}"
        self.L.save(self.prof)
        if self.on_saved:
            self.on_saved(self.prof["name"])
        messagebox.showinfo(APP, f"Đã lưu profile '{self.prof['name']}'.", parent=self.top)

    def save_as(self):
        name = simpledialog.askstring(APP, "Tên profile mới (vd. 1440p, laptop_1080p):", parent=self.top)
        if not name:
            return
        name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip().replace(" ", "_")
        if not name:
            return
        self.prof["name"] = name
        self.top.title(self.top.title().split("[profile")[0] + f"[profile: {name}]")
        self.save()

    def reset(self):
        if messagebox.askyesno(APP, "Đưa tất cả vùng về toạ độ mặc định?", parent=self.top):
            self.prof["boxes"] = {k: list(v) for k, v in self.L.DEFAULT["boxes"].items()}
            self.redraw()
            self.update_zoom()


# ============================================================ cập nhật
def local_version():
    try:
        import updater
        return updater.local_version()
    except Exception:
        return "?"


def auto_update_check(root, get_busy=lambda: False):
    import updater

    def work():
        try:
            r = updater.check()
        except Exception:
            return
        if r:
            ui_call(lambda: prompt(r), 1500)

    def prompt(r):
        if get_busy():
            root.after(5000, lambda: prompt(r))
            return
        ver, notes = r
        ans = messagebox.askyesnocancel(
            f"{APP} — Có bản mới",
            f"Có phiên bản mới {ver} (đang dùng {updater.local_version()}).\n\n{notes}\n\n"
            "Cập nhật ngay?\n(Có = cập nhật · Không = nhắc lần sau · Huỷ = bỏ qua bản này)", parent=root)
        if ans is None:
            updater.skip(ver)
        elif ans:
            threading.Thread(target=lambda: do_update(root), daemon=True).start()
    threading.Thread(target=work, daemon=True).start()


def do_update(root, then_quit=False):
    import updater
    try:
        v = updater.apply_update()
        msg = (f"Đã cập nhật lên bản {v}.\nBản mới có hiệu lực từ lần mở tiếp theo.", None)
    except Exception as e:  # noqa: BLE001
        msg = (None, f"Cập nhật thất bại:\n{e}")

    def show():
        if msg[0]:
            messagebox.showinfo(APP, msg[0], parent=root)
        else:
            messagebox.showerror(APP, msg[1], parent=root)
        if then_quit:
            root.destroy()
    ui_call(show)


def manual_update(root, keep=False):
    import updater
    if not keep:
        root.withdraw()
    try:
        r = updater.check(force=True)
    except Exception as e:  # noqa: BLE001
        messagebox.showerror(APP, f"Không kết nối được GitHub:\n{e}", parent=root)
        return None if keep else root.destroy()
    if not r:
        messagebox.showinfo(APP, f"Bạn đang dùng bản mới nhất ({updater.local_version()}).", parent=root)
        return None if keep else root.destroy()
    ver, notes = r
    if messagebox.askyesno(APP, f"Có bản mới {ver} (đang dùng {updater.local_version()}).\n\n{notes}\n\n"
                                "Cập nhật ngay?", parent=root):
        threading.Thread(target=lambda: do_update(root, then_quit=not keep), daemon=True).start()
    elif not keep:
        root.destroy()


# ============================================================ main
def main():
    args = sys.argv[1:]
    mode = args[0] if args else "home"
    paths = args[1:]
    if mode not in ("home", "analyze", "calibrate", "update"):
        mode, paths = "home", args
    if mode == "analyze":
        paths = gather_paths(mode, paths)      # Explorer gọi 1 lần / file → gom lại 1 cửa sổ
        if paths is None:
            return

    root = tk.Tk()
    setup_style(root)

    def on_tk_error(exc, val, tb):
        write_log("".join(traceback.format_exception(exc, val, tb)))
        try:
            messagebox.showerror(APP, f"Có lỗi xảy ra:\n{val}\n\nChi tiết đã ghi vào:\n{LOG}", parent=root)
        except Exception:
            pass
    root.report_callback_exception = on_tk_error
    start_ui_pump(root)
    try:
        root.iconbitmap(default=os.path.join(core.APP_DIR, "dtclscan.ico"))
    except Exception:
        pass
    if mode == "update":
        manual_update(root)
        root.mainloop()
        return
    if not check_deps(root):
        return
    win = HomeWindow(root, paths)
    root._win = win
    root.title(root.title() + f"  (v{local_version()})")
    if mode == "calibrate" and win.files:
        root.after(200, win.calibrate)
    try:
        enable_drop(root)
    except Exception:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("enable_drop: " + traceback.format_exc())
    auto_update_check(root, lambda: getattr(getattr(root, "_win", None), "_busy", False))
    root.lift()
    root.attributes("-topmost", True)
    root.after(300, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as _e:  # noqa: BLE001
        write_log(traceback.format_exc())
        try:
            messagebox.showerror(APP, f"DTCLScan gặp lỗi và phải đóng:\n{_e}\n\nChi tiết đã ghi vào:\n{LOG}")
        except Exception:
            pass
