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
    "panel": ("7", None),            # 1 dòng trong bảng bán trong suốt (tộc/hệ, người chơi)
    "panelw": ("7", None),           # như panel nhưng giữ được nét chữ dày hơn
}


def whiteness(img):
    """Chữ HUD của TFT màu trắng / xám nhạt → cả 3 kênh màu đều cao. Lấy kênh NHỎ NHẤT để
    dải nền xanh / tím / xanh lá sau tên tướng, icon đồng vàng, khung vàng… đều tối đi, chỉ còn chữ sáng."""
    return img.min(axis=2) if img.ndim == 3 else img


def prep(img, kind, variant=0, scale=None):
    """Phóng to → giữ phần màu trắng → nhị phân hoá → chữ đen trên nền trắng (cho Tesseract).
    variant 1, 2: cách xử lý khác để thử lại khi lần đầu đọc không ra số hợp lệ."""
    if img is None or img.size == 0:
        return None
    g = whiteness(img)
    if scale is None:
        target_h = 36 if kind == "block" else 72
        scale = 2.5 if kind == "block" else max(1.0, min(6.0, target_h / max(1, g.shape[0]) * 1.4))
    scale *= (1.0, 1.6, 0.7)[variant]
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if variant == 0:
        g = cv2.GaussianBlur(g, (3, 3), 0)
    if kind in ("panel", "panelw", "block"):
        # bảng bán trong suốt đè lên cảnh game: nền trời / tường có thể còn sáng hơn chữ.
        # top-hat giữ lại nét mảnh sáng hơn xung quanh (chữ), xoá mảng sáng lớn (nền).
        k = int((11 if kind == "panelw" else 7) * scale) | 1
        g = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    otsu, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if kind in ("panel", "panelw", "block"):
        thr = max(otsu, 40 if variant == 0 else 60)
    elif variant == 2:
        thr = int(np.percentile(g, 99) * 0.6)
    else:
        thr = otsu
    _, b = cv2.threshold(g, thr, 255, cv2.THRESH_BINARY)
    b = drop_edge_blobs(b)                  # bỏ viền khung / vạch sáng chạm mép vùng cắt
    b = 255 - b                             # chữ (sáng) → đen, nền → trắng
    return cv2.copyMakeBorder(b, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)


def drop_edge_blobs(b):
    """Xoá vạch viền khung chạm mép vùng cắt (vạch dọc cao gần hết vùng, vạch ngang dài, mảng mỏng),
    nhưng GIỮ chữ số chạm mép (khi người dùng khoanh vùng sát chữ)."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    h, w = b.shape
    out = b.copy()
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (x == 0 or y == 0 or x + bw >= w or y + bh >= h):
            continue
        bar_v = bh >= 0.85 * h and bw <= 0.12 * w
        bar_h = bw >= 0.6 * w and bh <= 0.25 * h
        sliver = (x == 0 or x + bw >= w) and bw <= 0.03 * w
        if bar_v or bar_h or sliver:
            out[lab == i] = 0
    return out if out.any() else b


_LANGS = None


def available_langs():
    global _LANGS
    if _LANGS is None:
        td = core.TESSDATA_DIR
        own = {f[:-12] for f in os.listdir(td) if f.endswith(".traineddata")} if os.path.isdir(td) else set()
        if "eng" in own:
            _LANGS = own
        else:
            r = core.run([core.find_bin("tesseract"), "--list-langs"])
            _LANGS = {ln.strip() for ln in r.stdout.decode("utf-8", "replace").splitlines()[1:] if ln.strip()}
    return _LANGS


def pick_lang(lang):
    """'auto' → eng+vie nếu có dữ liệu tiếng Việt; bỏ ngôn ngữ chưa cài để Tesseract khỏi lỗi."""
    if not lang or lang == "auto":
        lang = "eng+vie"
    have = available_langs()
    parts = [p for p in lang.split("+") if p in have]
    return "+".join(parts) or "eng"


def tesseract(img, psm="7", whitelist=None, lang="eng"):
    exe = core.find_bin("tesseract")
    ok, png = cv2.imencode(".png", img)
    if not ok:
        return ""
    cmd = [exe, "stdin", "stdout", "--psm", psm, "-l", pick_lang(lang)]
    if os.path.isfile(os.path.join(core.TESSDATA_DIR, "eng.traineddata")):
        cmd += ["--tessdata-dir", core.TESSDATA_DIR]
    if whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
    r = core.run(cmd, input=png.tobytes())
    return r.stdout.decode("utf-8", "replace").strip()


def read(crop_img, kind, lang="eng", variant=0, scale=None):
    """Trả về chuỗi đã OCR (thô) của 1 vùng."""
    if crop_img is None or crop_img.size == 0:
        return ""
    if kind not in ("block", "panel", "panelw"):
        g = whiteness(crop_img)
        if float(np.percentile(g, 99.5)) < 120 or float(np.percentile(g, 99.5)) - float(np.percentile(g, 20)) < 50:
            return ""                # không có chữ trắng (ô trống) → khỏi OCR, tránh đọc ra rác
    b = prep(crop_img, kind, variant, scale)
    if b is None:
        return ""
    psm, wl = _CFG.get(kind, ("7", None))
    lang_used = lang if kind in ("name", "block", "level", "panel", "panelw") else "eng"
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
    if kind not in ("round", "int", "level", "xp"):
        return raw, val
    if not raw and val is None:
        g = whiteness(frame_crop)
        if float(np.percentile(g, 99.5)) < 120:
            return raw, val                   # vùng trống thật → khỏi thử thêm
    # Số: đọc thêm bằng cách xử lý khác, lấy theo đa số (Tesseract đôi khi rớt mất 1 chữ số, vd 34 → 4)
    reads = [(raw, val)]
    r1 = read(frame_crop, kind, lang, 1)
    reads.append((r1, parse(kind, r1)))
    if reads[0][1] != reads[1][1] or reads[0][1] is None:
        r2 = read(frame_crop, kind, lang, 2)
        reads.append((r2, parse(kind, r2)))
    vals = [v for _, v in reads if v is not None]
    if not vals:
        return raw, None
    best = max(vals, key=lambda v: (vals.count(v), len(str(v))))
    return next(r for r, v in reads if v == best), best


# ---------------------------------------------------------------- số máu (bảng người chơi)
# Số máu người khác chỉ cao ~8px ở 1080p và bị mờ khi nén → Tesseract đọc rất kém.
# Dùng nhận dạng từng chữ số bằng so khớp mẫu (digits.npz, sinh từ vài font sans đậm bằng tools/mk_digits.py).
_DIG = None
_GN = 32


def _glyph(m):
    ys, xs = np.where(m > 0)
    if len(xs) == 0:
        return None
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = m.shape
    nw = max(1, min(_GN, int(round(w * _GN / h))))
    r = cv2.resize(m, (nw, _GN), interpolation=cv2.INTER_AREA)
    c = np.zeros((_GN, _GN), np.float32)
    x0 = (_GN - nw) // 2
    c[:, x0:x0 + nw] = r
    return cv2.GaussianBlur(c, (3, 3), 0)


def _templates():
    global _DIG
    if _DIG is None:
        d = np.load(os.path.join(core.APP_DIR, "digits.npz"))
        t = d["t"].reshape(len(d["t"]), -1)
        t = t - t.mean(1, keepdims=True)
        t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-6
        _DIG = (t, d["l"])
    return _DIG


def classify_digit(mask):
    g = _glyph(mask)
    if g is None:
        return None, 0.0
    tf, tl = _templates()
    v = g.reshape(-1)
    v = v - v.mean()
    v /= np.linalg.norm(v) + 1e-6
    sc = tf @ v
    best = {}
    for s_, l_ in zip(sc, tl):
        best[int(l_)] = max(best.get(int(l_), -1.0), float(s_))
    lab = max(best, key=best.get)
    return lab, best[lab]


def _decode_digits(b, lab_info, min_h, scale):
    n, lab, st = lab_info
    H, W = b.shape
    comps = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if h < (min_h * scale if min_h else 0.2 * H) or h > 0.8 * H or h > 32 * scale or w > 0.5 * W \
                or w > 1.9 * h or y == 0 or y + h >= H:
            continue
        comps.append((x, y, w, h, i))
    if not comps:
        return "", []
    lines = []                                 # gom chữ số cùng dòng, chọn dòng nhiều số nhất / to nhất
    for c in sorted(comps, key=lambda c: c[1] + c[3] / 2):
        cy = c[1] + c[3] / 2
        for ln in lines:
            if abs(ln["cy"] - cy) < 0.4 * max(ln["h"], c[3]) and abs(ln["h"] - c[3]) < 0.35 * max(ln["h"], c[3]):
                ln["c"].append(c)
                break
        else:
            lines.append({"cy": cy, "h": c[3], "c": [c]})
    best = max(lines, key=lambda ln: (len(ln["c"]), ln["h"]))
    txt, conf = "", []
    for x, y, w, h, i in sorted(best["c"]):
        m = (lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255
        parts = (m[:, :w // 2], m[:, w // 2:]) if w > 0.85 * h else (m,)   # 2 chữ số dính nhau
        for part in parts:
            d, c = classify_digit(part)
            if d is not None:
                txt += str(d)
                conf.append(c)
    return txt, conf


def read_digits(img_bgr, scale=6, min_h=0):
    """Đọc 1 số nhỏ (chữ trắng trên nền tối) bằng so khớp mẫu từng chữ số, thử 3 mức ngưỡng
    (chữ dày/mảnh khác nhau) rồi lấy theo đa số. Trả (chuỗi, số, độ tin cậy)."""
    if img_bgr is None or img_bgr.size == 0:
        return "", None, 0.0
    g = cv2.resize(whiteness(img_bgr), None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    otsu, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    top = float(np.percentile(g, 99.5))
    votes = []
    for k in (0.2, 0.1, 0.0):
        _, b = cv2.threshold(g, otsu + (top - otsu) * k, 255, cv2.THRESH_BINARY)
        n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
        txt, conf = _decode_digits(b, (n, lab, st), min_h, scale)
        v = parse_int(txt, 0, 150) if txt else None
        if v is not None and len(txt) <= 3:
            votes.append((txt, v, min(conf)))
    if not votes:
        return "", None, 0.0
    vals = [v for _, v, _ in votes]
    best = max(vals, key=lambda v: (vals.count(v), -vals.index(v)))
    t, v, c = next(x for x in votes if x[1] == best)
    return t, v, c


def _dark_runs(mask, lo, close=4):
    m = mask.copy()
    i = 0
    while i < len(m):                       # lấp khoảng sáng ngắn (do chính chữ số) trong vùng tối
        if not m[i]:
            j = i
            while j < len(m) and not m[j]:
                j += 1
            if 0 < i and j < len(m) and j - i <= close:
                m[i:j] = True
            i = j
        else:
            i += 1
    out, y = [], 0
    while y < len(m):
        if m[y]:
            y0 = y
            while y < len(m) and m[y]:
                y += 1
            if y - y0 >= lo:
                out.append((y0, y))
        y += 1
    return out


def read_players(crop_img, lang="eng", player_name=""):
    """Cột số máu bên phải. Vùng cần khoanh: từ mép trái số máu TO của bạn tới mép phải ô máu nhỏ
    của người khác (không lấy tên, không lấy ảnh đại diện), từ người trên cùng tới người dưới cùng.
    Mỗi người khác có 1 ô tối nhỏ chứa số máu; dòng của bạn được phóng to, số máu to hơn, không có ô nhỏ.
    Trả về ([{'y','hp','me','conf'}], trạng thái)."""
    if crop_img is None or crop_img.size == 0:
        return [], "empty"
    H, W = crop_img.shape[:2]
    g = whiteness(crop_img).astype(np.float32)
    med = np.median(g[:, int(0.62 * W):int(0.88 * W)], axis=1)
    out = []

    def other(y0, y1):
        L = y1 - y0
        txt, v, c = read_digits(crop_img[max(0, y0 - 2):y0 + int(L * 0.6), int(0.58 * W):int(0.95 * W)])
        if v is not None and c >= 0.6:
            out.append({"y": int(y0), "hp": v, "me": False, "conf": round(c, 2), "raw": txt})

    for y0, y1 in _dark_runs(med < 75, 28):
        L = y1 - y0
        if L <= 62:
            other(y0, y1)
            continue
        # khối dài = dòng của bạn (phóng to), có thể dính với dòng ngay dưới
        top = min(L, 78)
        txt, v, c = read_digits(crop_img[y0:y0 + top, int(0.1 * W):int(0.58 * W)], scale=4, min_h=13)
        if v is not None and c >= 0.55:
            out.append({"y": int(y0), "hp": v, "me": True, "conf": round(c, 2), "raw": txt})
        if L - top >= 28:
            other(y1 - 44, y1)
    if len(out) < 2:
        return out, "unknown"
    return out, "ok"


def read_traits(crop_img, lang="eng", row_h=53):
    """Bảng tộc/hệ bên trái: mỗi dòng ~53px (ở khung 1080p): 'số  Tên' + dòng mốc '2 > 4 > 6'.
    Đọc nửa trên mỗi dòng (số + tên). Số đếm đôi khi bị mất, tên thường đọc được."""
    h = crop_img.shape[0]
    rows = max(1, int(round(h / row_h)))
    lines = []
    for i in range(rows):
        row = crop_img[int(i * h / rows):int(i * h / rows + h / rows * 0.62)]
        raw = read(row, "panelw", lang, scale=3.0)
        if raw and not re.match(r"\s*\d", raw):
            n = parse_int(read(row[:, :int(row.shape[1] * 0.2)], "int"), 1, 15)   # số đếm to bên trái
            if n:
                raw = f"{n} {raw}"
        if raw:
            lines.append(raw)
    return lines


def parse_traits(lines):
    """['4 Tan Pha', '2 > 4 > 6', '2 Hoa Nguc', ...] → [{'trait','count'}]."""
    out, seen = [], set()
    for ln in lines:
        m = re.search(r"(?:(\d{1,2})\s+)?([^\d/>|<]{3,})", ln)
        if not m:
            continue
        name = clean_name(m.group(2))
        if len(name) >= 4 and sum(c.isalpha() for c in name) >= 4 and name.lower() not in seen:
            seen.add(name.lower())
            out.append({"trait": name, "count": int(m.group(1)) if m.group(1) else None})
    return out
