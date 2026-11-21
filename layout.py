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
                "Khoanh hẹp: từ mép trái số máu TO của bạn tới mép phải ô máu nhỏ của người khác. "
                "KHÔNG lấy tên, KHÔNG lấy ảnh đại diện. Từ người trên cùng tới người dưới cùng."),
}
SAMPLE_FIELDS = ["round", "gold", "level", "xp", "shop1", "shop2", "shop3", "shop4", "shop5"]
BLOCK_FIELDS = ["traits", "players"]
SHOP = ["shop1", "shop2", "shop3", "shop4", "shop5"]


def _default_boxes():
    """HUD TFT 16:9 (đo từ client thật, quy về 1920x1080) → đổi sang tỉ lệ."""
    px = {
        "round": (758, 3, 824, 34),          # "3-5" (bỏ icon mỏ neo bên trái)
        "gold": (1014, 882, 1068, 915),      # "43" (bỏ icon đồng vàng)
        "level": (338, 880, 404, 914),       # "Cấp 7"
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
    os.makedirs(core.PROFILE_DIR, exist_ok=True)
    names = sorted(f[:-5] for f in os.listdir(core.PROFILE_DIR) if f.endswith(".json"))
    if DEFAULT["name"] not in names:
        save(DEFAULT)
        names.insert(0, DEFAULT["name"])
    return names


def load(name):
    path = os.path.join(core.PROFILE_DIR, name + ".json")
    prof = json.loads(json.dumps(DEFAULT))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        prof.update({k: v for k, v in data.items() if k != "boxes"})
        prof["boxes"].update(data.get("boxes", {}))
    except Exception:
        pass
    prof["name"] = name
    return prof


def save(prof):
    os.makedirs(core.PROFILE_DIR, exist_ok=True)
    with open(os.path.join(core.PROFILE_DIR, prof["name"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=2)


def crop(frame, box):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    x1, x2 = sorted((int(x1 * w), int(x2 * w)))
    y1, y2 = sorted((int(y1 * h), int(y2 * h)))
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, max(x2, x1 + 2)), min(h, max(y2, y1 + 2))
    return frame[y1:y2, x1:x2]
