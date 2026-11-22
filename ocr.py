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
        # khung chữ U / chữ L (viền ô) chạm mép: trải rộng nhưng rất "rỗng" (nét mảnh)
        frame = bw >= 0.6 * w and bh >= 0.6 * h and area < 0.2 * bw * bh
        if bar_v or bar_h or sliver or frame:
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


def has_text(crop_img, lo=120):
    """Vùng có chữ trắng không (ô cửa hàng trống / HUD đang ẩn → không).
    Số XP / cấp hiển thị màu xám nhạt hơn tên tướng → dùng ngưỡng thấp hơn (lo=90)."""
    g = whiteness(crop_img)
    hi = float(np.percentile(g, 99.5))
    return hi >= lo and hi - float(np.percentile(g, 20)) >= min(50, lo - 40)


_NUM_KINDS = ("round", "int", "level", "xp")


def read(crop_img, kind, lang="eng", variant=0, scale=None, with_conf=False):
    """Trả về chuỗi đã OCR (thô) của 1 vùng (with_conf=True → (chuỗi, độ tin cậy 0..100))."""
    empty = ("", 0.0) if with_conf else ""
    if crop_img is None or crop_img.size == 0:
        return empty
    if kind not in ("block", "panel", "panelw") and not has_text(crop_img, 90 if kind in _NUM_KINDS else 120):
        return empty                 # không có chữ trắng (ô trống) → khỏi OCR, tránh đọc ra rác
    b = prep(crop_img, kind, variant, scale)
    if b is None:
        return empty
    psm, wl = _CFG.get(kind, ("7", None))
    lang_used = lang if kind in ("name", "block", "level", "panel", "panelw") else "eng"
    if with_conf:
        return tesseract_conf(b, psm, lang_used, wl)
    return tesseract(b, psm, wl, lang_used)


# ---------------------------------------------------------------- phân tích chuỗi
def parse_round(s):
    m = re.search(r"(\d)\s*-\s*(\d)", s or "")
    if not m:
        m = re.fullmatch(r"\D*(\d)(\d)\D*", s or "")      # mất dấu gạch: '35' → 3-5
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
    s = (s or "").replace("_", " ").strip()
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
    if kind == "name":
        # tên tướng: đọc 1 lần; nếu Tesseract không chắc (video nén làm chữ dính nét) thì đọc thêm
        # bằng cách xử lý khác và lấy bản có độ tin cậy cao nhất
        raw, cf = read(frame_crop, kind, lang, 0, with_conf=True)
        if raw and cf >= 80:
            return raw, parse(kind, raw)
        if not raw and not has_text(frame_crop):
            return raw, parse(kind, raw)
        best = (raw, cf if clean_name(raw) else -1.0)
        for v in (2, 1):
            r, c = read(frame_crop, kind, lang, v, with_conf=True)
            if clean_name(r) and c > best[1]:
                best = (r, c)
            if best[1] >= 80:
                break
        return best[0], parse(kind, best[0])
    if kind not in ("round", "int", "level", "xp"):
        raw = read(frame_crop, kind, lang)
        return raw, parse(kind, raw)
    if not has_text(frame_crop, 90):
        return "", None                       # vùng trống thật → khỏi OCR
    # Số: Tesseract hay đọc sai số in đậm (vd 0/56 → /6, 3-5 → 35). Đọc 2–3 lần với cách xử lý khác nhau
    # (ưu tiên nét mảnh — variant 2), lấy theo đa số; hoà thì lấy lần đọc trước.
    reads = []
    for variant, mul in _NUM_ATTEMPTS:
        sc = _auto_scale(frame_crop, kind) * mul
        r = read(frame_crop, kind, lang, variant, scale=sc)
        reads.append((r, parse(kind, r)))
        vals = [v for _, v in reads if v is not None]
        if len(reads) >= 2 and len(vals) == len(reads) and len(set(map(str, vals))) == 1:
            break                             # 2 lần đầu khớp nhau → khỏi đọc thêm
    vals = [v for _, v in reads if v is not None]
    if not vals:
        return reads[0][0], None
    best = max(vals, key=lambda v: (vals.count(v), -vals.index(v)))
    return next(r for r, v in reads if v == best), best


_NUM_ATTEMPTS = ((2, 1.0), (2, 1.5), (0, 1.0), (1, 0.6))


def _auto_scale(img, kind):
    h = img.shape[0]
    return max(1.0, min(6.0, 72 / max(1, h) * 1.4))


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


def _decode_digits(b, lab_info, min_h, scale, right=False):
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
    comps = sorted(best["c"])
    if right:
        # chỉ lấy cụm chữ số sát nhau nằm bên PHẢI nhất (ô máu nằm sát ảnh đại diện; mảnh chữ tên
        # người chơi lọt vào vùng khi khoanh lệch thì nằm bên trái, cách xa hơn)
        groups = [[comps[0]]]
        for c in comps[1:]:
            p = groups[-1][-1]
            if c[0] - (p[0] + p[2]) <= 0.8 * max(c[3], p[3]):
                groups[-1].append(c)
            else:
                groups.append([c])
        comps = groups[-1]
    txt, conf = "", []
    for x, y, w, h, i in comps:
        m = (lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255
        parts = (m[:, :w // 2], m[:, w // 2:]) if w > 0.85 * h else (m,)   # 2 chữ số dính nhau
        for part in parts:
            d, c = classify_digit(part)
            if d is not None:
                txt += str(d)
                conf.append(c)
    return txt, conf


def read_digits(img_bgr, scale=6, min_h=0, right=False):
    """Đọc 1 số nhỏ (chữ trắng trên nền tối) bằng so khớp mẫu từng chữ số, thử 3 mức ngưỡng
    (chữ dày/mảnh khác nhau) rồi lấy theo đa số. Trả (chuỗi, số, độ tin cậy)."""
    if img_bgr is None or img_bgr.size == 0:
        return "", None, 0.0
    g = cv2.resize(whiteness(img_bgr), None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    otsu, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    top = float(np.percentile(g, 99.5))
    votes = []
    for k in (0.3, 0.2, 0.1, 0.0):
        _, b = cv2.threshold(g, otsu + (top - otsu) * k, 255, cv2.THRESH_BINARY)
        n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
        txt, conf = _decode_digits(b, (n, lab, st), min_h, scale, right)
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


# tham số đã dò trên ảnh thật + biến thể (xem tests/test_robust.py); đổi thì chạy lại test
PL_CFG = {"cols": (0.62, 0.88), "pct": 50, "dark": 75, "x0": 0.58, "right": False, "close": 8}


# Video gốc thấp hơn mức này: chữ số máu người khác (~8px ở 1080p) chỉ còn 5–7px → đọc sai mà vẫn đúng thứ tự
# giảm dần (đo trên ảnh thật thu 720p / 900p: 3–5 số sai). Khi đó chỉ trả máu của bạn.
MIN_SRC_H_OTHERS = 1000


def read_players(crop_img, lang="eng", player_name="", src_h=None):
    """Cột số máu bên phải. Vùng cần khoanh: từ mép trái số máu TO của bạn tới mép phải ô máu nhỏ
    của người khác (không lấy tên, không lấy ảnh đại diện), từ người trên cùng tới người dưới cùng.
    Mỗi người khác có 1 ô tối nhỏ chứa số máu; dòng của bạn được phóng to, số máu to hơn, không có ô nhỏ.
    Bảng TFT luôn xếp theo máu giảm dần → dòng nào phá thứ tự là đọc sai: bỏ đi và hạ trạng thái.
    src_h: chiều cao video GỐC (trước khi phóng về 1920); dưới MIN_SRC_H_OTHERS → 'low_res', bỏ máu người khác.
    Trả về ([{'y','hp','me','conf'}], trạng thái): 'ok' | 'uncertain' (có dòng bị loại) | 'low_res' | 'unknown' | 'empty'."""
    if crop_img is None or crop_img.size == 0:
        return [], "empty"
    H, W = crop_img.shape[:2]
    # tỉ lệ cỡ HUD so với vùng mặc định (652px cao ở khung 1920): quay cửa sổ game nhỏ → vùng khoanh nhỏ hơn,
    # mọi kích thước dòng / chữ số nhỏ theo
    k = min(1.0, max(0.4, H / 652.0)) if H > 200 else 1.0
    g = whiteness(crop_img).astype(np.float32)
    c0, c1 = PL_CFG["cols"]
    # dòng = dải ô tối (trung vị độ trắng theo hàng ngang thấp)
    prof = np.percentile(g[:, int(c0 * W):max(int(c0 * W) + 1, int(c1 * W))], PL_CFG["pct"], axis=1)
    out = []
    x_other = int(PL_CFG["x0"] * W)

    def other(y0, y1):
        L = y1 - y0
        # ô máu nằm trong dải tối; video thật dải tối ngắn hơn (chữ số ở nửa dưới) → lấy trọn dải
        # thường chữ số nằm nửa trên dải tối; video thật đôi khi dải tối ngắn hơn và chữ số ở nửa dưới
        # → đọc nửa trên trước, không chắc thì đọc trọn dải
        txt, v, c = read_digits(crop_img[max(0, y0 - 2):y0 + int(L * 0.6), x_other:W], right=PL_CFG["right"])
        if v is None or c < 0.65:
            txt, v, c = read_digits(crop_img[max(0, y0 - 2):min(H, y1 + 2), x_other:W], right=PL_CFG["right"])
        if v is not None and c >= 0.65:
            out.append({"y": int(y0), "hp": v, "me": False, "conf": round(c, 2), "raw": txt})

    # ngưỡng "tối" thích nghi: nền cảnh game có thể tối (video thật) hoặc sáng (bầu trời) → so với nền
    bg = float(np.percentile(prof, 70))
    dark = PL_CFG["dark"] if bg >= 100 else max(28.0, bg * 0.7)
    runs = _dark_runs(prof < dark, int(18 * k), max(3, int(round(PL_CFG["close"] * k))))
    for y0, y1 in runs:
        L = y1 - y0
        if L < 20 * k:
            continue
        if L <= 62 * k:
            other(y0, y1)
            continue
        # khối dài = dòng của bạn (phóng to), có thể dính với dòng ngay dưới
        top = min(L, int(78 * k))
        txt, v, c = read_digits(crop_img[y0:y0 + top, int(0.1 * W):int(0.58 * W)], scale=4 / k, min_h=13 * k)
        if v is not None and c >= 0.75:
            out.append({"y": int(y0), "hp": v, "me": True, "conf": round(c, 2), "raw": txt})
        if L - top >= 28 * k:
            other(y1 - int(44 * k), y1)
    if not any(r["me"] for r in out):
        me = _find_big_hp(crop_img, k)
        if me:
            # bỏ dòng "người khác" trùng chỗ với số máu to (ô lục giác của bạn bị nhận nhầm là ô máu nhỏ)
            out = [r for r in out if abs(r["y"] - me["y"]) > 30 * k]
            out.append(me)
    out.sort(key=lambda r: r["y"])
    if src_h and src_h < MIN_SRC_H_OTHERS:
        return [r for r in out if r["me"]], "low_res"
    out, dropped = _keep_descending(out)
    # cần thấy ít nhất 3 dòng (bạn + 2 người) mới coi là đang hiện bảng máu; ít hơn thường là
    # bảng đang hiện thứ khác (thống kê sát thương…) hoặc vùng khoanh chưa đúng
    if len(out) < 3:
        return out, "unknown"
    if dropped:
        return out, "uncertain"
    return out, "ok"


def _find_big_hp(crop_img, k=1.0):
    """Số máu TO của bạn (cao ~16–24px ở 1080p) ở nửa trái cột máu: tìm các chữ số sáng cao, gom 1 dòng, đọc."""
    H, W = crop_img.shape[:2]
    x0, x1 = int(0.1 * W), int(0.6 * W)
    g = whiteness(crop_img[:, x0:x1])
    _, b = cv2.threshold(g, 150, 255, cv2.THRESH_BINARY)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    cands = [st[i] for i in range(1, n) if 13 * k <= st[i][3] <= 32 * k and st[i][2] <= 1.3 * st[i][3]
             and st[i][4] >= 0.15 * st[i][2] * st[i][3]]
    if not cands:
        return None
    best = None
    for c in cands:                           # gom các chữ số cùng dòng, cùng cỡ
        grp = [d for d in cands if abs((d[1] + d[3] / 2) - (c[1] + c[3] / 2)) < 0.4 * c[3]
               and abs(d[3] - c[3]) < 0.3 * c[3]]
        if best is None or (len(grp), c[3]) > (len(best), best[0][3]):
            best = grp
    ya = max(0, min(d[1] for d in best) - int(5 * k))
    yb = min(H, max(d[1] + d[3] for d in best) + int(5 * k))
    txt, v, c = read_digits(crop_img[ya:yb, x0:x1], scale=4 / k, min_h=13 * k)
    if v is None or c < 0.75:
        return None
    return {"y": int(ya), "hp": v, "me": True, "conf": round(c, 2), "raw": txt}


def _keep_descending(rows):
    """Giữ dãy con dài nhất có máu không tăng (từ trên xuống), ưu tiên giữ dòng của bạn và dòng tin cậy cao.
    Trả (các dòng giữ lại, số dòng bị loại)."""
    n = len(rows)
    if n < 2:
        return rows, 0

    def w(r):      # dòng của bạn (số to, rõ) đáng tin hơn; số 1 chữ số hay là mảnh vỡ → hơi kém tin
        return 1 + (2 if r["me"] else 0) + r["conf"] - (0.3 if r["hp"] < 10 else 0)
    best = [(w(r), -1) for r in rows]
    for i in range(n):
        for j in range(i):
            if rows[j]["hp"] >= rows[i]["hp"]:
                sc = best[j][0] + w(rows[i])
                if sc > best[i][0]:
                    best[i] = (sc, j)
    i = max(range(n), key=lambda k: best[k][0])
    keep = []
    while i >= 0:
        keep.append(i)
        i = best[i][1]
    keep = sorted(keep)
    return [rows[k] for k in keep], n - len(keep)


_TSV_OK = None


def _ensure_tsv_config():
    """Chế độ 'tsv' của Tesseract cần file tessdata/configs/tsv. Thư mục tessdata riêng của DTCLScan
    (install.bat chỉ tải eng/vie.traineddata) KHÔNG có file đó → mọi lần đọc kèm độ tin cậy ra RỖNG
    (lỗi 1.4.0 trên Windows: không đọc được tên tướng / tộc hệ). Tự tạo file cấu hình nếu thiếu."""
    global _TSV_OK
    if _TSV_OK is not None:
        return _TSV_OK
    _TSV_OK = True
    if os.path.isfile(os.path.join(core.TESSDATA_DIR, "eng.traineddata")):
        cfg = os.path.join(core.TESSDATA_DIR, "configs", "tsv")
        if not os.path.isfile(cfg):
            try:
                os.makedirs(os.path.dirname(cfg), exist_ok=True)
                with open(cfg, "w", encoding="ascii") as f:
                    f.write("tessedit_create_tsv 1\n")
            except OSError:
                _TSV_OK = False
    return _TSV_OK


def tesseract_conf(img, psm="7", lang="eng", whitelist=None):
    """Như tesseract() nhưng trả (chuỗi, độ tin cậy trung bình 0..100) — dùng để chọn cách xử lý ảnh tốt nhất.
    Nếu chế độ tsv không dùng được thì vẫn trả chữ (độ tin cậy giả định 50) thay vì rỗng."""
    if not _ensure_tsv_config():
        return tesseract(img, psm, whitelist, lang), 50.0
    exe = core.find_bin("tesseract")
    ok, png = cv2.imencode(".png", img)
    if not ok:
        return "", 0.0
    cmd = [exe, "stdin", "stdout", "--psm", psm, "-l", pick_lang(lang)]
    if os.path.isfile(os.path.join(core.TESSDATA_DIR, "eng.traineddata")):
        cmd += ["--tessdata-dir", core.TESSDATA_DIR]
    if whitelist:
        cmd += ["-c", f"tessedit_char_whitelist={whitelist}"]
    r = core.run(cmd + ["tsv"], input=png.tobytes())
    words, confs = [], []
    for ln in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
        p = ln.split("\t")
        if len(p) >= 12 and p[11].strip():
            try:
                c = float(p[10])
            except ValueError:
                continue
            words.append(p[11].strip())
            confs.append(c)
    if not words and r.returncode != 0:       # tsv lỗi (thiếu cấu hình…) → đọc thường, không bỏ trống
        return tesseract(img, psm, whitelist, lang), 50.0
    return " ".join(words), (float(np.mean(confs)) if confs else 0.0)


def _prep_line(img, scale, k):
    """1 dòng chữ trắng/xám trên bảng bán trong suốt: top-hat (xoá nền sáng diện rộng) → Otsu."""
    g = cv2.resize(whiteness(img), None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    kk = int(k * scale) | 1
    t = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk)))
    _, b = cv2.threshold(t, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    b = drop_edge_blobs(b)
    return cv2.copyMakeBorder(255 - b, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)


def _trait_lang(lang):
    return "vie" if "vie" in available_langs() else lang


def _strip_stray(txt):
    """Bỏ ký tự lẻ (vạch khung, đốm sáng) ở đầu/cuối dòng: '_ Hỏa Ngục |' → 'Hỏa Ngục'."""
    toks = [t for t in re.split(r"\s+", clean_name(txt)) if t]
    while len(toks) > 1 and len(toks[-1]) == 1:
        toks.pop()
    while len(toks) > 1 and len(toks[0]) == 1:
        toks.pop(0)
    return " ".join(toks)


def trait_anchors(crop_img):
    """Tìm chữ số đếm (to, bên trái mỗi dòng tộc/hệ) → [(y_giữa, x, w, h, số)].
    Mỗi dòng của bảng tộc/hệ có đúng 1 số đếm, nên số đếm cũng là mốc để tìm dòng."""
    H, W = crop_img.shape[:2]
    g = whiteness(crop_img)
    strip = g[:, :max(4, int(0.3 * W))]
    th = cv2.morphologyEx(strip, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
    _, b = cv2.threshold(th, 45, 255, cv2.THRESH_BINARY)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    cands = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if not (10 <= h <= 22 and w <= h and a >= 15) or y == 0 or y + h >= H:
            continue
        d, c = classify_digit((lab[y:y + h, x:x + w] == i).astype(np.uint8) * 255)
        if d is not None and c >= 0.75:
            cands.append([y + h / 2.0, int(x), int(w), int(h), d, c])
    if not cands:
        return []
    # Cột số đếm = cột chữ số TO nằm TRÁI nhất. (Chữ số mốc '1 / 2' nhỏ hơn; chữ cái đầu tên tộc/hệ
    # nằm bên phải — không được chọn theo "cột đông nhất" vì đầu trận nhiều dòng mức 1 làm cột mốc đông hơn.)
    # chiều cao tham chiếu: chiều cao lớn nhất mà ít nhất 2 chữ số cùng có (bỏ 1 mảnh icon / khung lẻ cao bất thường)
    hs = [c[3] for c in cands]
    max_h = max((h for h in hs if sum(1 for o in hs if abs(o - h) <= 1) >= 2), default=max(hs))
    tall = [c for c in cands if 0.85 * max_h <= c[3] <= 1.2 * max_h and c[2] >= 0.4 * c[3]]
    if not tall:
        return []
    need = min(2, len(tall))
    col = min((c[1] for c in tall if sum(1 for o in tall if abs(o[1] - c[1]) <= 4) >= need),
              default=min(c[1] for c in tall))
    rows = []
    for c in sorted(cands, key=lambda c: c[0]):
        if abs(c[1] - col) > 5 or not (0.85 * max_h <= c[3] <= 1.2 * max_h):
            continue
        # chữ số thứ 2 ngay bên phải (vd. 10, 12)
        for c2 in cands:
            if c2 is not c and abs(c2[0] - c[0]) < 4 and 0 <= c2[1] - (c[1] + c[2]) <= 6:
                c = [c[0], c[1], c2[1] + c2[2] - c[1], c[3], c[4] * 10 + c2[4], min(c[5], c2[5])]
        if rows and abs(rows[-1][0] - c[0]) < 25:
            if c[5] > rows[-1][5]:
                rows[-1] = c
            continue
        rows.append(c)
    return [(cy, x, w, h, d) for cy, x, w, h, d, _ in rows]


def read_traits(crop_img, lang="eng", row_h=53):
    """Bảng tộc/hệ bên trái: mỗi dòng ~53px (ở khung 1080p): số đếm to bên trái + tên ở dòng trên
    + mốc '2 > 4 > 6' ở dòng dưới. Trả về các dòng dạng '4 Tân Phá'."""
    if crop_img is None or crop_img.size == 0:
        return []
    anchors = trait_anchors(crop_img)
    if len(anchors) < 1:
        return _read_traits_grid(crop_img, lang, row_h)
    H, W = crop_img.shape[:2]
    tl = _trait_lang(lang)
    lines = []
    for cy, x, w, h, d in anchors:
        y0, y1 = max(0, int(cy - 21)), min(H, int(cy + 3))
        x0 = min(W - 4, x + w + 5)
        img = crop_img[y0:y1, x0:]
        best = ("", -1.0)
        for scale, k in ((3.0, 7), (4.0, 11)):
            txt, cf = tesseract_conf(_prep_line(img, scale, k), "7", tl)
            txt = _strip_stray(txt)
            if txt and cf > best[1]:
                best = (txt, cf)
        if best[0]:
            lines.append(f"{d} {best[0]}")
    return lines


def _read_traits_grid(crop_img, lang="eng", row_h=53):
    """Cách cũ (khi không tìm thấy số đếm): chia đều theo chiều cao dòng."""
    h = crop_img.shape[0]
    rows = max(1, int(round(h / row_h)))
    lines = []
    for i in range(rows):
        row = crop_img[int(i * h / rows):int(i * h / rows + h / rows * 0.62)]
        if row.size == 0 or not has_text(row, 90):
            continue
        raw = read(row, "panelw", lang, scale=3.0)
        if sum(c.isalpha() for c in raw) < 3:
            continue
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
