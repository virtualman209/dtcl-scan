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


def _text_lines(crop_img, lang, scale=3.0, min_area=60):
    """Nhị phân hoá cả bảng, xoá đốm nhiễu, tự dò từng dòng chữ theo chiều ngang rồi OCR từng dòng."""
    b = prep(crop_img, "panel", 0, scale)
    if b is None:
        return []
    mask = (b == 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area or h > 40 * scale or w > crop_img.shape[1] * scale * 0.8:
            mask[lab == i] = 0                      # đốm nhỏ, mảng to bất thường → bỏ
    prof = mask.sum(axis=1)
    bands, y = [], 0
    while y < len(prof):
        if prof[y] > 0:
            y0 = y
            while y < len(prof) and (prof[y] > 0 or (y + 4 < len(prof) and prof[y:y + 5].any())):
                y += 1
            if 5 * scale <= y - y0 <= 40 * scale and prof[y0:y].sum() > 60 * scale:
                bands.append((y0, y))
        y += 1
    out = []
    for y0, y1 in bands:
        img = 255 - mask[max(0, y0 - 6):y1 + 6] * 255
        img = cv2.copyMakeBorder(img.astype(np.uint8), 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        raw = tesseract(img, "7", None, lang)
        if raw:
            out.append((int(y0 / scale), raw, img))
    return out


def _right_number(line_img):
    """Số máu nằm ở cụm chữ ngoài cùng bên phải của dòng → cắt riêng cụm đó, đọc chỉ-chữ-số."""
    ink = (line_img < 128).any(axis=0)
    xs = np.where(ink)[0]
    if len(xs) == 0:
        return None
    rows = np.where((line_img < 128).any(axis=1))[0]
    text_h = (rows[-1] - rows[0]) if len(rows) else 30
    gaps = np.where(np.diff(xs) > max(18, text_h * 0.9))[0]   # khoảng trống giữa tên và số
    x0 = xs[gaps[-1] + 1] if len(gaps) else xs[0]
    part = line_img[:, max(0, x0 - 6):xs[-1] + 7]
    part = cv2.copyMakeBorder(part, 0, 0, 10, 10, cv2.BORDER_CONSTANT, value=255)
    txt = tesseract(part, "7", "0123456789", "eng")
    v = parse_int(txt, 0, 150)
    return v


def read_players(crop_img, lang="eng", player_name=""):
    """Bảng người chơi bên phải: mỗi dòng 'Tên  máu'. Dòng của bạn chỉ hiện số máu to, không có tên
    (hoặc khớp 'Tên trong game' trong Cài đặt) → đánh dấu 'me'.
    Nếu bảng đang hiện thống kê sát thương (số dạng 1.831) thì trả về 'damage'.
    Lưu ý: số máu của người khác rất nhỏ, video nén mạnh có thể đọc sai."""
    out = []
    me_n = norm(player_name)
    lines = _text_lines(crop_img, lang)
    if sum(1 for _, raw, _ in lines if re.search(r"\d[.,]\d{3}", raw)) >= 2:
        return [], "damage"
    for y, raw, img in lines:
        name = clean_name(re.sub(r"\d+", " ", raw))
        hp = _right_number(img)
        if hp is None:
            nums = [int(x) for x in re.findall(r"\d{1,3}", raw) if int(x) <= 150]
            hp = nums[-1] if nums else None
        if hp is None:
            continue
        is_me = (me_n in norm(name)) if (me_n and len(name) >= 3) else len(name) < 3
        if is_me and any(p["me"] for p in out):
            is_me = False
        out.append({"y": y, "name": name, "hp": hp, "me": bool(is_me), "raw": raw})
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
