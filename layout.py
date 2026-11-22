"""Vùng HUD cần đọc (toạ độ tương đối 0..1 theo khung hình) và hồ sơ (profile) lưu ra JSON.

Mỗi độ phân giải / tỉ lệ khung hình / kiểu HUD có thể cần một profile riêng.
Toạ độ mặc định chỉ là ước lượng cho HUD 16:9 — nên căn chỉnh lại bằng cửa sổ "Căn chỉnh vùng".
"""
import json
import os

import core

# key: (nhãn, kiểu, mô tả)
#   round  : "3-2"          int   : số          xp : "24/36"
#   name   : tên tướng 1 dòng      block : nhiều dòng (chỉ đọc ở khung hình chốt mỗi vòng)
FIELDS = {
    "round":   ("Vòng (3-2)", "round", "Chữ số vòng ở giữa phía trên màn hình"),
    "gold":    ("Vàng", "int", "Số vàng ở giữa, ngay trên cửa hàng"),
    "level":   ("Cấp", "int", "Chữ 'Lv. 7' / 'Cấp 7' bên trái, trên cửa hàng"),
    "xp":      ("Kinh nghiệm (24/36)", "xp", "Số XP dạng 24/36"),
    "shop1":   ("Cửa hàng ô 1 – tên tướng", "name", "Dòng tên tướng ở đáy thẻ tướng thứ 1"),
    "shop2":   ("Cửa hàng ô 2 – tên tướng", "name", ""),
    "shop3":   ("Cửa hàng ô 3 – tên tướng", "name", ""),
    "shop4":   ("Cửa hàng ô 4 – tên tướng", "name", ""),
    "shop5":   ("Cửa hàng ô 5 – tên tướng / Wisp", "name", "Ô ngoài cùng bên phải (có thể là Wisp)"),
    "traits":  ("Bảng tộc/hệ (trái)", "block", "Danh sách tộc/hệ đang kích hoạt bên trái"),
    "players": ("Cột máu người chơi (phải)", "block",
                "Khoanh hẹp từ số máu TO của bạn tới mép phải ô máu nhỏ, từ người trên cùng tới dưới cùng. "
                "Không lấy tên, ảnh đại diện."),
}
SAMPLE_FIELDS = ["round", "gold", "level", "xp", "shop1", "shop2", "shop3", "shop4", "shop5"]
BLOCK_FIELDS = ["traits", "players"]
SHOP = ["shop1", "shop2", "shop3", "shop4", "shop5"]


def _default_boxes():
    """HUD TFT 16:9 (đo từ client thật, quy về 1920x1080) → đổi sang tỉ lệ."""
    px = {
        "round": (758, 3, 824, 34),          # "3-5" (bỏ icon mỏ neo bên trái)
        "gold": (1014, 882, 1068, 915),      # "43" (bỏ icon đồng vàng)
        "level": (338, 880, 414, 914),       # "Cấp 7" … "Cấp 10" (đủ rộng cho 2 chữ số)
        "xp": (458, 880, 520, 913),          # "0/56"
        "traits": (100, 255, 258, 742),      # cột tộc/hệ bên trái (không lấy icon)
        "players": (1780, 158, 1856, 810),   # cột số máu: từ số máu to của bạn → hết ô máu nhỏ (không lấy tên, ảnh)
    }
    for i in range(5):                        # dòng tên tướng ở đáy 5 thẻ cửa hàng, cách nhau ~202.5px
        x = 549 + i * 202.5
        px[f"shop{i + 1}"] = (x, 1043, x + 150, 1073)
    return {k: [round(x1 / 1920, 4), round(y1 / 1080, 4), round(x2 / 1920, 4), round(y2 / 1080, 4)]
            for k, (x1, y1, x2, y2) in px.items()}


DEFAULT = {"name": "default_1080p", "calibrated": False, "aspect": "16:9", "boxes": _default_boxes()}


def list_profiles():
    """Không ghi profile mặc định ra đĩa: toạ độ mặc định luôn lấy từ code (bản cập nhật sửa toạ độ là có tác dụng)."""
    try:
        names = sorted(f[:-5] for f in os.listdir(core.PROFILE_DIR) if f.endswith(".json"))
    except OSError:
        names = []
    if DEFAULT["name"] not in names:
        names.insert(0, DEFAULT["name"])
    return names


def load(name):
    path = os.path.join(core.PROFILE_DIR, name + ".json")
    prof = json.loads(json.dumps(DEFAULT))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        prof.update({k: v for k, v in data.items() if k != "boxes"})
        # profile chưa được người dùng căn chỉnh (vd. default_1080p.json do bản cũ tự ghi ra) → dùng toạ độ
        # mặc định MỚI trong code, không kẹt toạ độ cũ sau khi cập nhật
        if data.get("calibrated"):
            prof["boxes"].update(data.get("boxes", {}))
            if data.get("schema", 1) < SCHEMA:
                _migrate(prof)
    except Exception:
        pass
    prof["name"] = name
    return prof


SCHEMA = 2
# Vùng mà ý nghĩa / cỡ đúng đã đổi so với bản cũ. Profile cũ (schema 1) khoanh RỘNG hơn mặc định
# (dính icon đồng vàng, cắt "Cấp 10", cột máu kèm tên + ảnh đại diện) → đọc sai. Nếu vùng cũ bao trùm
# phần lớn vùng mặc định mới thì thay bằng vùng mặc định mới (người dùng không phải căn lại).
_MIGRATE = ("gold", "level", "players")


def _overlap_ratio(inner, outer):
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = max(1e-9, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return ix * iy / area


def _migrate(prof):
    changed = []
    for k in _MIGRATE:
        d, u = DEFAULT["boxes"][k], prof["boxes"].get(k)
        if not u or u == d:
            continue
        if _overlap_ratio(d, u) >= 0.75:
            prof["boxes"][k] = list(d)
            changed.append(k)
    prof["migrated"] = changed
    prof["schema"] = SCHEMA
    return changed


def save(prof):
    prof["schema"] = SCHEMA
    os.makedirs(core.PROFILE_DIR, exist_ok=True)
    with open(os.path.join(core.PROFILE_DIR, prof["name"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=2)


def effective_height(prof, src_h):
    """Chiều cao HUD hiệu dụng: video 1080p nhưng quay cửa sổ game nhỏ (vùng 'players' khoanh nhỏ hơn mặc định)
    thì chữ số cũng nhỏ như video thấp hơn."""
    if not src_h:
        return src_h
    b, d = prof["boxes"].get("players"), DEFAULT["boxes"]["players"]
    try:
        ratio = (b[3] - b[1]) / (d[3] - d[1])
    except (TypeError, ZeroDivisionError, IndexError):
        ratio = 1.0
    return int(round(src_h * min(1.0, ratio)))


def crop(frame, box):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    x1, x2 = sorted((int(x1 * w), int(x2 * w)))
    y1, y2 = sorted((int(y1 * h), int(y2 * h)))
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, max(x2, x1 + 2)), min(h, max(y2, y1 + 2))
    return frame[y1:y2, x1:x2]
