"""Ước lượng đội hình + sao từ LỊCH SỬ MUA (không cần AI).

Trong TFT: 3 bản cùng tướng ghép thành 2★, 9 bản thành 3★. Cộng dồn số lần mua mỗi tướng (đọc từ cửa hàng)
qua các vòng → danh sách tướng đang có kèm số sao dự đoán.

Giới hạn (ghi rõ cho người dùng):
- Không biết bạn BÁN tướng nào (chỉ thấy vàng tăng) → tướng đã bán vẫn bị tính.
- Tướng nhận từ băng chuyền / lõi / Wisp không qua cửa hàng → không tính.
- Lượt mua bị đọc sót → thiếu bản, sao có thể thấp hơn thật.
- Không biết tướng nào đang đứng TRÊN BÀN hay ngồi băng ghế chờ.
"""
import ocr

_NOT_UNIT = ("wisp", "tinhlinh")       # ô thứ 5 có thể là Wisp, không phải tướng


def stars_of(copies):
    return 3 if copies >= 9 else 2 if copies >= 3 else 1


def _clean(name):
    name = (name or "").replace("(không thấy vàng giảm)", "").strip()
    n = ocr.norm(name)
    if len(n) < 2 or any(w in n for w in _NOT_UNIT):
        return None, None
    return n, name


def estimate(rounds, events):
    """Ghi vào mỗi vòng: board_est (list), board_est_str (chuỗi), sold_maybe (đã có dấu hiệu bán tướng)."""
    copies, display = {}, {}
    sold = False
    for r in rounds:
        for name in r.get("bought", []):
            n, disp = _clean(name)
            if n:
                copies[n] = copies.get(n, 0) + 1
                display.setdefault(n, disp)
        evs = [e for e in events if e["round"] == r["round"] and r["start"] <= e["t"] < r["end"]]
        if any(e["type"] == "gain" for e in evs):     # vàng tăng giữa vòng mà không mua gì → có thể đã bán tướng
            sold = True
        est = sorted(({"name": display[n], "copies": c, "stars": stars_of(c)} for n, c in copies.items()),
                     key=lambda u: (-u["stars"], -u["copies"], u["name"]))
        r["board_est"] = est
        r["board_est_str"] = fmt(est)
        r["sold_maybe"] = sold
    return rounds


def fmt(est):
    return ", ".join(f"{u['name']} {'★' * u['stars']} ({u['copies']})" for u in est)


def final(rounds):
    for r in reversed(rounds):
        if r.get("board_est"):
            return {"round": r["round"], "units": r["board_est"], "sold_maybe": r.get("sold_maybe", False)}
    return None
