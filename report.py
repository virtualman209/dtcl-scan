"""Xuất report.html dễ đọc từ match.json."""
import html
import os

TYPE_VI = {"round_start": "Vòng mới", "level_up": "Lên cấp", "buy_xp": "Mua XP", "reroll": "Roll",
           "buy": "Mua tướng", "income": "Nhận vàng", "gain": "Được vàng", "spend": "Tiêu vàng",
           "free_roll": "Roll miễn phí"}

CSS = """body{font:14px/1.5 'Segoe UI',system-ui,sans-serif;margin:0;background:#f4f6fa;color:#1d2433}
main{max-width:1180px;margin:0 auto;padding:24px}h1{margin:0 0 4px;font-size:24px}
.sub{color:#667}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.card{background:#fff;border-radius:10px;padding:12px 14px;box-shadow:0 1px 3px #0001}
.card b{display:block;font-size:20px}.card span{color:#667;font-size:12px}
.warn{background:#fff4e0;border-left:4px solid #e8a33d;padding:10px 14px;border-radius:6px;margin:8px 0}
table{border-collapse:collapse;width:100%;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px #0001}
th,td{padding:7px 9px;border-bottom:1px solid #eef0f4;text-align:left;vertical-align:top}
th{background:#2d3a55;color:#fff;font-weight:600;position:sticky;top:0}td.n{text-align:right;font-variant-numeric:tabular-nums}
img.k{width:220px;border-radius:6px;cursor:zoom-in;display:block}details{margin-top:4px}summary{cursor:pointer;color:#3b5ba5}
.ev{font-size:12px;color:#444}.ev i{color:#889;font-style:normal}.ai{font-size:12px;color:#234}
.notes{background:#fff;border-radius:10px;padding:14px 18px;white-space:pre-wrap;box-shadow:0 1px 3px #0001}
svg{background:#fff;border-radius:10px;box-shadow:0 1px 3px #0001}h2{margin-top:28px}"""


def e(x):
    return html.escape("" if x is None else str(x))


def gold_chart(rounds):
    pts = [(i, r["gold_end"]) for i, r in enumerate(rounds) if r.get("gold_end") is not None]
    if len(pts) < 2:
        return ""
    W, H, P = 1130, 170, 30
    mx = max(10, max(v for _, v in pts))
    n = max(1, len(rounds) - 1)
    xy = [(P + i * (W - 2 * P) / n, H - P - v * (H - 2 * P) / mx) for i, v in pts]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    grid = "".join(f'<line x1="{P}" x2="{W - P}" y1="{H - P - g * (H - 2 * P) / mx:.1f}" '
                   f'y2="{H - P - g * (H - 2 * P) / mx:.1f}" stroke="#e5e8ef"/>'
                   f'<text x="4" y="{H - P - g * (H - 2 * P) / mx + 4:.1f}" font-size="10" fill="#889">{g}</text>'
                   for g in range(0, mx + 1, 10))
    labels = "".join(f'<text x="{P + i * (W - 2 * P) / n:.1f}" y="{H - 8}" font-size="10" fill="#667" '
                     f'text-anchor="middle">{e(r["round"])}</text>'
                     for i, r in enumerate(rounds) if i % max(1, len(rounds) // 20) == 0)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#3b6fd8"><title>{e(rounds[i]["round"])}: '
                   f'{v} vàng</title></circle>' for (x, y), (i, v) in zip(xy, pts))
    return (f'<h2>Vàng cuối mỗi vòng</h2><svg viewBox="0 0 {W} {H}" width="100%">{grid}'
            f'<polyline points="{line}" fill="none" stroke="#3b6fd8" stroke-width="2"/>{dots}{labels}</svg>')


def board_html(r):
    a = r.get("ai")
    if a:
        units = []
        for u in a.get("board") or []:
            s = f"<b>{e(u.get('champion'))}</b>{'★' * int(u.get('star') or 1)}"
            if u.get("items"):
                s += " <i>(" + e(", ".join(u["items"])) + ")</i>"
            units.append(s)
        tr = ", ".join(f"{e(t.get('trait'))} {e(t.get('count'))}" for t in a.get("traits") or [])
        return f'<div class="ai">{" · ".join(units) or "—"}<br><span class="sub">{tr}</span></div>'
    if r.get("ai_error"):
        return f'<div class="ai">AI lỗi: {e(r["ai_error"])}</div>'
    tr = ", ".join(f"{e(t['trait'])} {t['count']}" for t in r.get("traits") or [])
    return f'<div class="ai sub">{tr}</div>' if tr else ""


def write(out_dir, m):
    s = m["summary"]
    lv = ", ".join(f"{k[2:]} @ {v}" for k, v in s.get("level_timing", {}).items()) or "—"
    cards = [("Vòng cuối thấy được", s.get("last_round")), ("Cấp cuối", s.get("final_level")),
             ("Tổng vàng tiêu", s.get("total_spent")), ("Số lần roll", s.get("total_rolls")),
             ("Lần mua XP", s.get("total_xp_buys")), ("Tướng đã mua", s.get("units_bought")),
             ("Vàng cao nhất", s.get("max_gold"))]
    parts = [f"<!DOCTYPE html><html lang='vi'><head><meta charset='utf-8'><title>DTCLScan – "
             f"{e(os.path.basename(m['video']))}</title><style>{CSS}</style></head><body><main>",
             f"<h1>Phân tích trận ĐTCL</h1><div class='sub'>{e(os.path.basename(m['video']))} · "
             f"{m['resolution'][0]}x{m['resolution'][1]} · profile <b>{e(m['profile'])}</b> · "
             f"{e(m['generated'])}</div>"]
    for w in m.get("warnings", []):
        parts.append(f"<div class='warn'>⚠ {e(w)}</div>")
    if not m.get("profile_calibrated"):
        parts.append("<div class='warn'>Profile chưa được căn chỉnh cho video của bạn — số liệu có thể sai. "
                     "Mở DTCLScan → <b>Căn chỉnh vùng…</b></div>")
    parts.append("<div class='cards'>" + "".join(f"<div class='card'><span>{e(a)}</span><b>{e(b) if b is not None else '—'}</b></div>"
                                                for a, b in cards) + "</div>")
    parts.append(f"<div class='sub'>Lên cấp: {e(lv)} · Tỉ lệ đọc OCR: "
                 + ", ".join(f"{e(k)} {v}%" for k, v in m["read_rate_percent"].items()) + "</div>")
    cp = m.get("chat_pack")
    if cp and not m.get("ai_notes"):
        parts.append(f"<div class='warn' style='background:#e8f1ff;border-color:#3b6fd8'>Muốn Claude nhận xét trận "
                     f"(không cần API): mở thư mục <b>gui_claude</b>, kéo {cp['images']} ảnh vào claude.ai rồi dán "
                     f"nội dung <b>cau_hoi.txt</b>.</div>")
    if m.get("ai_notes"):
        parts.append(f"<h2>Nhận xét của AI</h2><div class='notes'>{e(m['ai_notes'])}</div>")
    parts.append(gold_chart(m["rounds"]))
    parts.append("<h2>Từng vòng</h2><table><tr><th>Vòng</th><th>Lúc</th><th>Cấp</th><th>XP</th><th>Máu (hạng)</th>"
                 "<th>Vàng đầu→cuối</th><th>Tiêu</th><th>Roll</th><th>Mua XP</th><th>Mua tướng / sự kiện</th>"
                 "<th>Ảnh chốt</th></tr>")
    for r in m["rounds"]:
        evs = [x for x in m["events"] if x["round"] == r["round"] and r["start"] <= x["t"] < r["end"]
               and x["type"] != "round_start"]
        evh = "".join(f"<div class='ev'><i>{e(x['time'])}</i> {e(TYPE_VI.get(x['type'], x['type']))}: "
                      f"{e(x['detail'])}{(' (' + str(x['gold']) + 'g)') if x.get('gold') else ''}</div>"
                      for x in evs)
        img = (f"<a href='{e(r['keyframe'])}' target='_blank'><img class='k' loading='lazy' "
               f"src='{e(r['keyframe'])}'></a>") if r.get("keyframe") else ""
        bought = ", ".join(r["bought"])
        parts.append(
            f"<tr><td><b>{e(r['round'])}</b></td><td>{e(r['time'])}</td><td class='n'>{e(r.get('level'))}</td>"
            f"<td class='n'>{e(r.get('xp'))}</td><td class='n'>{e(r.get('hp'))}{(' (#' + str(r['rank_hp']) + ')') if r.get('rank_hp') else ''}</td>"
            f"<td class='n'>{e(r.get('gold_start'))} → {e(r.get('gold_end'))}</td><td class='n'>{r['spent']}</td>"
            f"<td class='n'>{r['rolls']}</td><td class='n'>{r['xp_buys']}</td>"
            f"<td>{e(bought) or '—'}{board_html(r)}"
            + (f"<details><summary>{len(evs)} sự kiện</summary>{evh}</details>" if evs else "")
            + f"</td><td>{img}</td></tr>")
    parts.append("</table><p class='sub'>Dữ liệu đầy đủ: rounds.csv, events.csv, samples.csv, match.json "
                 "(cùng thư mục). Số liệu do OCR đọc tự động nên có thể lệch vài chỗ. Máu đọc từ cột máu bên phải; hạng là ước lượng theo máu.</p></main></body></html>")
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path
