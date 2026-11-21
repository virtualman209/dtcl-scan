"""DTCLScan core: tìm ffmpeg/tesseract, đọc khung hình video (không phụ thuộc GUI)."""
import glob
import json
import os
import shutil
import subprocess

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
PROFILE_DIR = os.path.join(APP_DIR, "profiles")
TESSDATA_DIR = os.path.join(APP_DIR, "tessdata")
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".avi", ".ts", ".flv", ".webm", ".wmv", ".m4v")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
WORK_W = 1920          # mọi khung hình được đưa về rộng 1920 trước khi cắt vùng


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- binaries
def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def find_bin(name):
    """ffmpeg / ffprobe / tesseract: config.json -> bin\\ -> PATH -> vị trí cài mặc định."""
    exe = name + (".exe" if os.name == "nt" else "")
    cfg = _load_json(CONFIG_PATH).get(name)
    if cfg and os.path.isfile(cfg):
        return cfg
    for p in (os.path.join(APP_DIR, "bin", exe), os.path.join(APP_DIR, exe)):
        if os.path.isfile(p):
            return p
    p = shutil.which(name)
    if p:
        return p
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        cands = [os.path.join(local, "Microsoft", "WinGet", "Links", exe)]
        if name == "tesseract":
            cands += [os.path.join(pf, "Tesseract-OCR", exe),
                      os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Tesseract-OCR", exe),
                      os.path.join(local, "Programs", "Tesseract-OCR", exe)]
        else:
            cands += glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages",
                                            "*FFmpeg*", "**", "bin", exe), recursive=True)
            cands += [os.path.join(pf, "ffmpeg", "bin", exe), r"C:\ffmpeg\bin\\" + exe]
        for c in cands:
            if c and os.path.isfile(c):
                return c
    return None


def missing_bins():
    return [b for b in ("ffmpeg", "ffprobe", "tesseract") if not find_bin(b)]


def run(cmd, **kw):
    if not cmd or not cmd[0]:
        raise RuntimeError("Không tìm thấy chương trình cần thiết (ffmpeg / ffprobe / Tesseract). "
                           "Hãy chạy lại install.bat.")
    return subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW, **kw)


class VideoError(RuntimeError):
    """Lỗi video (hỏng / không phải video / 0 giây) — thông báo đã là tiếng Việt, hiện thẳng cho người dùng."""


# cv2.imread / cv2.imwrite không mở được đường dẫn có dấu tiếng Việt trên Windows → đi qua bộ nhớ.
def imread(path):
    import cv2
    import numpy as np
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite(path, img, params=()):
    import cv2
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img, list(params))
    if not ok:
        return False
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return True


# ---------------------------------------------------------------- settings
DEFAULT_SETTINGS = {"profile": "default_1080p", "fps": 2, "keyframes": True, "ai_board": False,
                    "ai_coach": False, "chat_pack": True, "api_key": "", "model": "claude-sonnet-5-5",
                    "player_name": "", "ocr_lang": "auto", "ask_open": True}


def get_settings():
    st = dict(DEFAULT_SETTINGS)
    st.update(_load_json(SETTINGS_PATH))
    return st


def set_settings(**kw):
    st = get_settings()
    st.update(kw)
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- helpers
def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXT


def fmt_time(t):
    t = max(0, int(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def probe(path):
    """duration, w, h, fps. Lỗi → VideoError (thông báo tiếng Việt)."""
    name = os.path.basename(path)
    if not os.path.isfile(path):
        raise VideoError(f"Không tìm thấy file video:\n{path}")
    if os.path.getsize(path) == 0:
        raise VideoError(f"File «{name}» rỗng (0 byte) — không phải video.")
    r = run([find_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format",
             "-show_streams", "-select_streams", "v:0", path])
    try:
        data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        data = {}
    info = {"path": path, "duration": 0.0, "w": 0, "h": 0, "fps": 30.0}
    try:
        info["duration"] = float(data.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        pass
    for s in data.get("streams", []):
        info["w"], info["h"] = int(s.get("width") or 0), int(s.get("height") or 0)
        try:
            n, d = s.get("avg_frame_rate", "30/1").split("/")
            info["fps"] = float(n) / float(d) if float(d) and float(n) else 30.0
        except Exception:
            pass
        if not info["duration"]:
            try:
                info["duration"] = float(s.get("duration") or 0)
            except (TypeError, ValueError):
                pass
        break
    if not info["w"] or not info["h"]:
        detail = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise VideoError(f"Không đọc được video «{name}»: file bị hỏng, rỗng (0 giây) hoặc không phải video."
                         + (f"\n(chi tiết: {detail[-1][:200]})" if detail else ""))
    if 0 < info["duration"] < 0.5:
        raise VideoError(f"Video «{name}» chỉ dài {info['duration']:.2f} giây (gần như 0 giây) — "
                         "quá ngắn để phân tích.")
    return info


def work_size(info):
    w = WORK_W
    h = int(round(info["h"] * WORK_W / info["w"] / 2)) * 2
    return w, h


def iter_frames(info, fps, cancel=None, start=0.0, end=None, errors=None):
    """Sinh (t, ảnh BGR rộng 1920) theo `fps` khung/giây, ffmpeg giải mã + giảm khung.
    errors: list (tuỳ chọn) — nhận các dòng lỗi ffmpeg in ra (để báo lỗi khi video hỏng)."""
    import tempfile
    import numpy as np
    w, h = work_size(info)
    args = [find_bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", info["path"]]
    if end:
        args += ["-t", f"{max(0.1, end - start):.3f}"]
    args += ["-an", "-sn", "-vf", f"fps={fps},scale={w}:{h}:flags=bicubic",
             "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    if not args[0]:
        raise RuntimeError("Không tìm thấy ffmpeg. Hãy chạy lại install.bat.")
    # stderr ghi ra file tạm (nếu để PIPE mà không đọc, video hỏng in nhiều lỗi sẽ làm ffmpeg treo)
    err = tempfile.TemporaryFile()
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err,
                            creationflags=CREATE_NO_WINDOW, bufsize=w * h * 3)
    size = w * h * 3
    i = 0
    try:
        while True:
            if cancel and cancel():
                raise Cancelled()
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        proc.kill()
        proc.wait()
        if errors is not None:
            try:
                err.seek(0)
                errors += err.read().decode("utf-8", "replace").strip().splitlines()[-5:]
            except Exception:
                pass
        err.close()


def grab_frame(info, t):
    """Lấy 1 khung hình tại giây t (ảnh BGR rộng 1920)."""
    import numpy as np
    w, h = work_size(info)
    for tt in dict.fromkeys((max(0.0, t), max(0.0, t - 2), 0.0)):     # quá cuối video → lùi lại
        r = run([find_bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
                 "-ss", f"{tt:.3f}", "-i", info["path"], "-frames:v", "1", "-an",
                 "-vf", f"scale={w}:{h}", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"])
        if len(r.stdout) >= w * h * 3:
            return np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3).copy()
    return None
