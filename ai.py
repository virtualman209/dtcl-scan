"""Tuỳ chọn: dùng Claude API (cần API key của bạn) để
  - nhận diện bàn cờ / băng ghế / trang bị trong ảnh chốt mỗi vòng
  - viết nhận xét cả trận từ bảng dữ liệu
Mỗi ảnh là 1 lượt gọi API (tính phí theo tài khoản Anthropic của bạn).
"""
import base64
import json
import re
import urllib.error
import urllib.request

import cv2

import core

API_URL = "https://api.anthropic.com/v1/messages"

BOARD_PROMPT = """Đây là ảnh chụp màn hình game Teamfight Tactics (Đấu Trường Chân Lý), vòng {round}.
Hãy đọc ảnh và trả về DUY NHẤT một JSON (không giải thích) theo mẫu:
{{"board":[{{"champion":"tên tướng","star":1,"items":["tên trang bị"]}}],
  "bench":[{{"champion":"...","star":1}}],
  "traits":[{{"trait":"tên tộc/hệ","count":3}}],
  "shop":["tên 5 ô cửa hàng (ghi 'Wisp: tên' nếu là Wisp, '' nếu ô trống)"],
  "gold":null,"level":null,"hp":null,
  "notes":"1 câu ngắn nếu có gì đáng chú ý (ví dụ đang ở băng chuyền / vòng quái)"}}
Chỉ ghi những gì nhìn thấy rõ; không chắc thì bỏ qua hoặc để null. Tên tướng giữ nguyên như hiển thị trong game."""

COACH_PROMPT = """Bạn là huấn luyện viên Đấu Trường Chân Lý (TFT). Dưới đây là dữ liệu một trận được trích tự động
từ video (OCR, có thể sai vài chỗ). Mỗi dòng là 1 vòng: vòng | cấp | XP | máu | vàng đầu→cuối | tiêu | roll | mua XP | tướng đã mua | bàn cờ (nếu có).

{table}

Hãy nhận xét bằng tiếng Việt, ngắn gọn, cho người chơi còn yếu:
1. Nhịp lên cấp và quản lý vàng (có giữ lãi không, roll lúc nào, có tiêu hoang không).
2. Đội hình hướng tới và có chuyển hướng hợp lý không.
3. 3 điều cụ thể nên sửa ở trận sau, nêu rõ vòng nào.
Nếu dữ liệu thiếu hoặc mâu thuẫn thì nói thẳng, đừng bịa."""


def _call(content, opts, max_tokens=1500):
    body = {"model": opts.get("model") or "claude-sonnet-5-5", "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "x-api-key": opts["api_key"].strip(), "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Claude API trả lỗi HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"Không kết nối được Claude API (kiểm tra mạng): {e}") from None
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _jpeg_b64(path, max_w=1568):
    img = core.imread(path)
    if img is None:
        raise RuntimeError("Không mở được ảnh " + path)
    if img.shape[1] > max_w:
        img = cv2.resize(img, (max_w, int(img.shape[0] * max_w / img.shape[1])), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf.tobytes()).decode("ascii")


def read_board(path, rnd, opts):
    text = _call([{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                               "data": _jpeg_b64(path)}},
                  {"type": "text", "text": BOARD_PROMPT.format(round=rnd.get("round", "?"))}], opts)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("AI không trả JSON")
    return json.loads(m.group(0))


def _board_str(r):
    a = r.get("ai") or {}
    units = []
    for u in a.get("board") or []:
        s = f"{u.get('champion', '?')}{'★' * int(u.get('star') or 1)}"
        if u.get("items"):
            s += "[" + ",".join(u["items"]) + "]"
        units.append(s)
    return " ".join(units)


def coach(rounds, events, opts):
    rows = []
    for r in rounds:
        rows.append(" | ".join(str(x) for x in (
            r["round"], r.get("level") or "?", r.get("xp") or "?", r.get("hp") if r.get("hp") is not None else "?",
            f"{r.get('gold_start')}→{r.get('gold_end')}", r["spent"], r["rolls"], r["xp_buys"],
            ", ".join(r["bought"]) or "-", _board_str(r) or "-")))
    return _call([{"type": "text", "text": COACH_PROMPT.format(table="\n".join(rows))}], opts, 2000)
