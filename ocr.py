"""OCR các vùng HUD bằng Tesseract (gọi tesseract.exe qua stdin, không cần pytesseract)."""
import os
import re
import unicodedata

import cv2
import numpy as np

import core

_CFG = {
    "round": ("7", "0123456789-"),
    "int":   ("7", "0123456789"),
    "level": ("7", None),            # "Lv. 7" / "Cấp 7" → lấy số
    "xp":    ("7", "0123456789/"),
    "name":  ("7", None),
    "block": ("6", None),
}


def prep(img, kind, variant=0):
    """Phóng to, lấy kênh sáng nhất (chữ HUD trắng/vàng trên nền tối), nhị phân hoá, nền trắng.
    variant 1, 2: cách xử lý khác để thử lại khi lần đầu đọc không ra số hợp lệ."""
    if img.size == 0:
        return None
    g = img.max(axis=2) if img.ndim == 3 else img
    target_h = 36 if kind == "block" else 72
    scale = 2.0 if kind == "block" else max(1.0, min(6.0, target_h / max(1, g.shape[0]) * 1.4))
    scale *= (1.0, 1.6, 0.7)[variant]
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if variant == 0:
        g = cv2.GaussianBlur(g, (3, 3), 0)
    if variant == 2:            # ngưỡng cố định theo độ sáng chữ, bỏ qua viền mờ
        thr = int(np.percentile(g, 99) * 0.6)
        _, b = cv2.threshold(g, thr, 255, cv2.THRESH_BINARY)
    else:
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([b[0], b[-1], b[:, 0], b[:, -1]])
    if border.mean() < 128:          # nền đen → đảo để nền trắng chữ đen
        b = 255 - b
    return cv2.copyMakeBorder(b, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)


def tesseract(img, psm="7", whitelist=None, lang="eng"):
    exe = core.find_bin("tesseract")
    ok, png = cv2.imencode(".png", img)
    if not ok:
        return ""
    cmd = [exe, "stdin", "stdout", "--psm", psm, "-l", lang]
    if os.path.isdir(core.TESSDATA_DIR) and any(f.endswith(".traineddata") for f in os.listdir(core.TESSDATA_DIR)):
        cmd += ["--tessdata-dir", core.TESSDATA_DIR]
    if whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
    r = core.run(cmd, input=png.tobytes())
    return r.stdout.decode("utf-8", "replace").strip()


def read(crop_img, kind, lang="eng", variant=0):
    """Trả về chuỗi đã OCR (thô) của 1 vùng."""
    if crop_img is None or crop_img.size == 0:
        return ""
    if kind != "block":
        g = crop_img.max(axis=2) if crop_img.ndim == 3 else crop_img
        if float(np.percentile(g, 99.5)) - float(np.percentile(g, 20)) < 55:
            return ""                # vùng gần như trống (không có chữ) → khỏi OCR, tránh đọc ra rác
    b = prep(crop_img, kind, variant)
    if b is None:
        return ""
    psm, wl = _CFG.get(kind, ("7", None))
    lang_used = lang if kind in ("name", "block", "level") else "eng"
    return tesseract(b, psm, wl, lang_used)


# ---------------------------------------------------------------- phân tích chuỗi
def parse_round(s):
    m = re.search(r"(\d)\s*-\s*(\d)", s or "")
    if not m:
        return None
    st, rd = int(m.group(1)), int(m.group(2))
    return f"{st}-{rd}" if 1 <= st <= 9 and 1 <= rd <= 7 else None


def parse_int(s, lo=0, hi=999):
    m = re.findall(r"\d+", s or "")
    if not m:
        return None
    v = int(m[-1]) if len(m[-1]) <= 3 else None
    return v if v is not None and lo <= v <= hi else None


def parse_xp(s):
    m = re.search(r"(\d+)\s*/\s*(\d+)", s or "")
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return f"{a}/{b}" if 0 <= a <= b <= 200 and b > 0 else None


def clean_name(s):
    s = (s or "").strip()
    s = re.sub(r"[^\w\s'’.&-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\d+", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .-'")
    return s if len(s) >= 2 else ""


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse(kind, raw):
    if kind == "round":
        return parse_round(raw)
    if kind == "int":
        return parse_int(raw, 0, 300)
    if kind == "level":
        return parse_int(raw, 1, 10)
    if kind == "xp":
        return parse_xp(raw)
    if kind == "name":
        return clean_name(raw)
    return [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]


def field_kind(key, ftype):
    return "level" if key == "level" else ftype


def read_field(frame_crop, key, ftype, lang="eng"):
    kind = field_kind(key, ftype)
    raw = read(frame_crop, kind, lang)
    val = parse(kind, raw)
    if kind in ("round", "int", "level", "xp"):
        for v in (1, 2):                      # đọc ra chữ nhưng không hợp lệ → thử cách xử lý khác
            if val is not None:
                break
            r2 = read(frame_crop, kind, lang, v)
            val2 = parse(kind, r2)
            if val2 is not None:
                raw, val = r2, val2
    return raw, val


def parse_players(lines, player_name=""):
    """['Tên 87', ...] → [{'name','hp'}]; đánh dấu 'me' nếu khớp tên người chơi."""
    out = []
    me = norm(player_name)
    for ln in lines:
        m = re.match(r"(.*?)[\s:|]*(\d{1,3})\s*$", ln)
        if not m:
            continue
        hp = int(m.group(2))
        if hp > 150:
            continue
        name = clean_name(m.group(1))
        out.append({"name": name, "hp": hp, "me": bool(me and name and me in norm(name))})
    return out


def parse_traits(lines):
    """['3 Blossom', 'Elderwood 2/4', ...] → [{'trait','count'}] (phỏng đoán, có thể thiếu)."""
    out = []
    for ln in lines:
        nums = re.findall(r"\d+", ln)
        name = clean_name(ln)
        if name and nums:
            out.append({"trait": name, "count": int(nums[0])})
    return out
