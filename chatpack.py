"""Gói gửi Claude chat (không cần API): ghép ảnh chốt các vòng thành vài ảnh lưới
+ 1 file chữ có sẵn câu hỏi và bảng số liệu. Kéo cả thư mục vào claude.ai là xong."""
import os

import cv2
import numpy as np

PROMPT = """Mình là người chơi Đấu Trường Chân Lý (TFT) còn yếu. Dưới đây là dữ liệu 1 trận mình chơi, \
được trích tự động từ video (OCR, có thể sai vài chỗ). Các ảnh đính kèm là ảnh chụp giai đoạn chuẩn bị \
của từng vòng (mỗi ảnh ghép 4 vòng, có ghi số vòng ở góc).

Hãy:
1. Đọc đội hình của mình qua các vòng (tướng, sao, trang bị nếu nhìn rõ).
2. Nhận xét nhịp lên cấp, quản lý vàng (giữ lãi, roll lúc nào, có tiêu hoang không).
3. Đội hình hướng tới và có chuyển hướng hợp lý không.
4. 3 điều cụ thể nên sửa ở trận sau, nêu rõ vòng nào.
Chỗ nào dữ liệu thiếu hoặc mâu thuẫn thì nói thẳng, đừng đoán bừa.

Tổng kết: {summary}

Bảng từng vòng: vòng | lúc | cấp | XP | máu | vàng đầu→cuối | tiêu | roll | mua XP | tướng đã mua | tộc/hệ đọc được
{table}
"""


def _table(rounds):
    rows = []
    for r in rounds:
        tr = ", ".join(f"{t['trait']} {t['count']}" for t in r.get("traits") or []) or "-"
        rows.append(" | ".join(str(x) for x in (
            r["round"], r.get("time", ""), r.get("level") or "?", r.get("xp") or "?",
            (f"{r['hp']} (#{r['rank_hp']})" if r.get("rank_hp") else r.get("hp")) if r.get("hp") is not None else "?", f"{r.get('gold_start')}→{r.get('gold_end')}",
            r["spent"], r["rolls"], r["xp_buys"], ", ".join(r["bought"]) or "-", tr)))
    return "\n".join(rows)


def write(out_dir, rounds, summary, per_image=4, cell_w=960):
    pack = os.path.join(out_dir, "gui_claude")
    os.makedirs(pack, exist_ok=True)
    for f in os.listdir(pack):
        if f.startswith("anh_") and f.endswith(".jpg"):
            os.remove(os.path.join(pack, f))
    shots = [r for r in rounds if r.get("keyframe")]
    cols = 2
    n_img = 0
    for i in range(0, len(shots), per_image):
        cells = []
        for r in shots[i:i + per_image]:
            img = cv2.imread(os.path.join(out_dir, r["keyframe"]))
            if img is None:
                continue
            img = cv2.resize(img, (cell_w, int(img.shape[0] * cell_w / img.shape[1])), interpolation=cv2.INTER_AREA)
            label = f"Vong {r['round']}"
            cv2.rectangle(img, (0, 0), (190, 46), (0, 0, 0), -1)
            cv2.putText(img, label, (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (80, 220, 255), 2, cv2.LINE_AA)
            cells.append(img)
        if not cells:
            continue
        h = cells[0].shape[0]
        while len(cells) % cols:
            cells.append(np.zeros_like(cells[0]))
        rows = [np.hstack([c if c.shape[0] == h else cv2.resize(c, (cell_w, h)) for c in cells[k:k + cols]])
                for k in range(0, len(cells), cols)]
        n_img += 1
        cv2.imwrite(os.path.join(pack, f"anh_{n_img:02d}.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
    s = summary or {}
    summ = (f"vòng cuối {s.get('last_round')}, cấp cuối {s.get('final_level')}, "
            f"lên cấp: {', '.join(f'{k[2:]}@{v}' for k, v in (s.get('level_timing') or {}).items()) or '?'}, "
            f"tổng roll {s.get('total_rolls')}, mua XP {s.get('total_xp_buys')}, tiêu {s.get('total_spent')} vàng")
    with open(os.path.join(pack, "cau_hoi.txt"), "w", encoding="utf-8") as f:
        f.write(PROMPT.format(summary=summ, table=_table(rounds)))
    return pack, n_img
