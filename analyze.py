"""Bóc tách dữ liệu trận ĐTCL từ video.

    python analyze.py <video> [--profile default_1080p] [--fps 2] [--from 0] [--to 0]

Kết quả nằm trong thư mục  <tên video>_dtcl\\  cạnh video:
    samples.csv   giá trị đọc được theo từng mốc thời gian (vòng, vàng, cấp, XP, cửa hàng)
    events.csv    sự kiện suy ra: lên cấp, mua XP, roll, mua tướng, nhận vàng…
    rounds.csv    tổng kết từng vòng (vàng đầu/cuối, tiêu bao nhiêu, roll mấy lần, mua gì…)
    match.json    toàn bộ dữ liệu (dùng cho AI / script khác)
    report.html   báo cáo dễ đọc, có ảnh chốt mỗi vòng
    keyframes\\   ảnh chốt mỗi vòng (bàn cờ + cửa hàng)
"""
import csv
import difflib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import layout  # noqa: E402
import ocr  # noqa: E402

SAME = object()
REREAD_SEC = 8.0


def round_key(r):
    a, b = r.split("-")
    return int(a) * 10 + int(b)


# ============================================================ 1. đọc video
def sample_video(info, prof, fps, lang, on_progress, cancel, log, start=0.0, end=None, errors=None):
    boxes = prof["boxes"]
    workers = max(2, min(12, (os.cpu_count() or 4)))
    pool = ThreadPoolExecutor(workers)
    last_small, recheck, last_read, entries, outstanding = {}, {}, {}, [], []
    end_t = end or info["duration"]
    span = max(1.0, end_t - start)
    t_last_log = 0
    try:
        for t, frame in core.iter_frames(info, fps, cancel, start, end, errors):
            e = {"t": round(t, 2)}
            for key in layout.SAMPLE_FIELDS:
                c = layout.crop(frame, boxes[key])
                small = cv2.resize(c.max(axis=2), (48, 12), interpolation=cv2.INTER_AREA).astype(np.int16)
                prev = last_small.get(key)
                if prev is not None and np.abs(small - prev).mean() < 2.0 and not recheck.get(key) \
                        and (key in layout.SHOP or t - last_read.get(key, -1e9) < REREAD_SEC):
                    e[key] = SAME
                    continue
                last_read[key] = t     # số: hình không đổi vẫn đọc lại mỗi REREAD_SEC giây → lần đọc sai không "dính" mãi
                # loại lần đọc: 'new' = hình vừa đổi; 'recheck' = khung ngay sau khi đổi (gần như cùng hình);
                # 'reread' = đọc lại định kỳ trên hình KHÔNG đổi. OCR trên cùng 1 hình gần như tất định, nên chỉ
                # 'new' và 'reread' (cách nhau >= REREAD_SEC) mới tính là bằng chứng độc lập.
                changed = prev is None or np.abs(small - prev).mean() >= 2.0
                e[key + "_kind"] = "new" if changed else ("recheck" if recheck.get(key) else "reread")
                # vừa đổi → khung sau đọc lại 1 lần nữa dù trông giống (khung chuyển cảnh / nén có thể đọc sai)
                recheck[key] = changed
                last_small[key] = small
                ftype = layout.FIELDS[key][1]
                fut = pool.submit(ocr.read_field, c.copy(), key, ftype, lang)
                e[key] = fut
                outstanding.append(fut)
            entries.append(e)
            while len(outstanding) > workers * 6:
                outstanding.pop(0).result()
            if cancel and cancel():
                raise core.Cancelled()
            on_progress(0.85 * min(1.0, (t - start) / span))
            if t - t_last_log >= 60:
                t_last_log = t
                log(f"  đã đọc tới {core.fmt_time(t)} / {core.fmt_time(end_t)}")
        for f in outstanding:
            f.result()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

    samples, prev = [], {}
    for e in entries:
        s = {"t": e["t"]}
        for key in layout.SAMPLE_FIELDS:
            v = e[key]
            if v is SAME:
                s[key], s[key + "_raw"] = prev.get(key), prev.get(key + "_raw", "")
                s[key + "_kind"] = "same"          # chép lại lần đọc trước, không phải 1 lần OCR mới
            else:
                raw, val = v.result()
                s[key], s[key + "_raw"] = val, raw
                s[key + "_kind"] = e.get(key + "_kind", "new")
                prev[key], prev[key + "_raw"] = val, raw
        samples.append(s)
    return samples


# ============================================================ 2. làm sạch
def load_known_names():
    path = os.path.join(core.APP_DIR, "champions.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        return []


def snap_shop_names(samples, fps):
    """Gom tên OCR lỗi về tên đúng: dùng champions.txt + các tên xuất hiện nhiều lần trong video."""
    known = load_known_names()
    known_n = {ocr.norm(k): k for k in known}
    cnt = Counter(s[k] for s in samples for k in layout.SHOP if s.get(k))
    vocab = [n for n, c in cnt.items() if c >= max(3, fps * 2)]
    # tên đọc sai nhưng lặp lại vài lần (vd 'Maiphite' 6 lần cạnh 'Malphite' 120 lần) → gộp về tên phổ biến
    ncnt = Counter()
    for n, c in cnt.items():
        ncnt[ocr.norm(n)] += c
    vocab_n = {}
    for v in sorted(vocab, key=lambda v: -cnt[v]):
        nv = ocr.norm(v)
        if nv in vocab_n:
            continue
        m = [k for k in difflib.get_close_matches(nv, list(vocab_n), 3, 0.75) if ncnt[k] >= 4 * ncnt[nv]]
        if not m:
            vocab_n[nv] = v
    cache = {}

    def snap(name):
        if not name:
            return name
        if name in cache:
            return cache[name]
        n = ocr.norm(name)
        res = name
        if known_n:
            m = difflib.get_close_matches(n, list(known_n), 1, 0.6)
            res = known_n[m[0]] if m else name
        elif n in vocab_n:
            res = vocab_n[n]                   # cùng tên, khác hoa/thường hoặc dấu → 1 cách viết
        else:
            m = difflib.get_close_matches(n, list(vocab_n), 1, 0.75)
            res = vocab_n[m[0]] if m else name
        cache[name] = res
        return res

    for s in samples:
        for k in layout.SHOP:
            s[k] = snap(s.get(k))


EVIDENCE = ("new", "reread")


def stabilize(vals, confirm=2, kinds=None, plausible=None):
    """Chỉ nhận giá trị mới khi nó lặp lại `confirm` mẫu liên tiếp (như bản 1.4 vòng 2), rồi ghi lùi về mẫu đầu
    tiên lệch khỏi giá trị cũ (vòng / vàng / XP đổi cùng một mốc).
    kinds[i]: 'new' (hình vừa đổi) | 'recheck' (khung ngay sau, gần như cùng hình) | 'reread' (đọc lại định kỳ trên
    hình KHÔNG đổi) | 'same' (chép lại, không OCR). Chỉ 'new' và 'reread' tính là bằng chứng độc lập.
    Cần >= 2 bằng chứng độc lập khi:
      - bước đổi không hợp lý theo plausible(cur, cand) (nhảy vòng, đi lùi, cấp +3…);
      - hoàn tác về giá trị ngay trước (chỉ vòng / cấp);
      - giá trị mới lần đầu xuất hiện ở lần đọc lại định kỳ: hình không đổi mà số đổi → hoà 1–1 với lần đọc trước,
        chờ lần đọc độc lập kế tiếp phân xử.
    Chỉ hoàn tác mới ghi đè ngược cả đoạn giá trị hiện tại, và chỉ khi đoạn đó mới có 1 bằng chứng."""
    n_all = len(vals)
    kinds = kinds or ["new"] * n_all
    out = []
    cur, cur_start, cur_ev, prev_val, pend_start, pend_kind = None, 0, 0, None, None, None
    cand, n, cand_start, ev, cand_kind = None, 0, 0, 0, None
    for i, v in enumerate(vals):
        k = kinds[i]
        if v is None:
            out.append(cur)
            continue
        if v == cur:
            cand, n, pend_start = None, 0, None
            cur_ev += k in EVIDENCE
            out.append(cur)
            continue
        if pend_start is None:
            pend_start, pend_kind = i, k
        if v == cand:
            n += 1
            ev += k in EVIDENCE
        else:
            cand, n, cand_start, ev, cand_kind = v, 1, i, int(k in EVIDENCE), k
        undo = plausible is not None and cur is not None and cand == prev_val
        ok = cur is None or plausible is None or plausible(cur, cand)
        strict = (cur is not None and (not ok or undo or cand_kind == "reread"))
        if n >= confirm and (not strict or ev >= 2):
            overwrite = undo and cur_ev <= 1
            # ghi lùi tới chỗ HÌNH bắt đầu đổi (đoạn chờ mở đầu bằng 1 lần đọc 'new', vd. khung đổi đọc nhầm 3-7);
            # đoạn chờ mở đầu bằng lần đọc lại trên hình cũ (đọc nhầm, bị loại) thì không kéo giá trị mới về trước
            if overwrite:
                start = cur_start
            elif cur is None or pend_kind not in ("new", "recheck"):
                start = cand_start
            else:
                start = pend_start
            for x in range(start, i):
                out[x] = cand
            prev_val = None if undo else cur
            cur, cur_start, cur_ev = cand, start, ev
            cand, n, pend_start = None, 0, None
        out.append(cur)
    return out


def next_round_ok(cur, cand):
    """Vòng chỉ tiến tới vòng kế tiếp trong stage, hoặc vòng đầu của stage sau."""
    try:
        s1, r1 = map(int, cur.split("-"))
        s2, r2 = map(int, cand.split("-"))
    except (ValueError, AttributeError):
        return False
    return (s2 == s1 and r2 == r1 + 1) or (s2 == s1 + 1 and r2 == 1)


def level_step_ok(cur, cand):
    return 1 <= cand - cur <= 2


def clean(samples, fps):
    snap_shop_names(samples, fps)
    conf = 2 if fps <= 3 else 3

    def kd(k):
        return [s.get(k + "_kind", "new") for s in samples]
    series = {
        "round": stabilize([s["round"] for s in samples], conf, kd("round"), next_round_ok),
        "gold": stabilize([s["gold"] for s in samples], conf, kd("gold")),
        "level": stabilize([s["level"] for s in samples], conf, kd("level"), level_step_ok),
        "xp": stabilize([s["xp"] for s in samples], conf, kd("xp")),
    }
    shop = []
    for s in samples:
        names = tuple(s.get(k) or "" for k in layout.SHOP)
        shop.append(None if not any(names) else names)     # cả 5 ô trống = cửa hàng đang ẩn
    rank = {"new": 3, "reread": 2, "recheck": 1, "same": 0}
    shop_kinds = [max((s.get(k + "_kind", "new") for k in layout.SHOP), key=rank.get) for s in samples]
    series["shop"] = stabilize(shop, conf, shop_kinds)
    series["gold"] = drop_gold_blips(series, samples, fps)
    return series


def drop_gold_blips(S, samples, fps, max_sec=2 * REREAD_SEC + 1, gap_sec=1.5):
    """Vàng nhảy LÊN rồi tụt xuống trong <= max_sec giây mà cửa hàng / XP / cấp không đổi gì từ sau lúc vọt lên
    tới gap_sec sau lúc tụt xuống → đọc sai (vd. 10 đọc thành 16 suốt vài giây ở video nén).
    Cửa sổ rộng để không xoá nhầm roll / mua thật khi tên tướng trong cửa hàng hiện trễ hơn số vàng (hoạt ảnh lật thẻ)."""
    g = list(S["gold"])
    n = len(g)
    segs, i = [], 0
    while i < n:
        j = i
        while j + 1 < n and g[j + 1] == g[i]:
            j += 1
        segs.append((i, j))
        i = j + 1
    for k in range(1, len(segs) - 1):
        (_, a1), (b0, b1), (c0, _) = segs[k - 1], segs[k], segs[k + 1]
        va, vb, vc = g[a1], g[b0], g[c0]
        if None in (va, vb, vc) or not (vb > vc and vb > va):
            continue
        if samples[b1]["t"] - samples[b0]["t"] + 1.0 / fps > max_sec:
            continue
        # thứ khác đổi SAU lúc vàng vọt lên (tới gap_sec sau lúc vàng tụt) → có thể là roll / mua thật mà cửa hàng
        # hiện tên mới trễ. (Đổi đúng lúc vàng vọt lên — vd. cửa hàng làm mới đầu vòng — thì không tính.)
        gap = int(round(gap_sec * fps))
        hi = min(n - 1, c0 + gap)
        if any(S[key][x] != S[key][b0] for key in ("shop", "xp", "level") for x in range(b0 + 1, hi + 1)):
            continue
        for x in range(b0, b1 + 1):
            g[x] = vc
    return g


def quality(samples):
    n = max(1, len(samples))
    q = {}
    for k in ("round", "gold", "level", "xp"):
        q[k] = round(100 * sum(1 for s in samples if s.get(k) is not None) / n, 1)
    q["shop"] = round(100 * sum(1 for s in samples if any(s.get(x) for x in layout.SHOP)) / n, 1)
    return q


# ============================================================ 3. sự kiện
def derive_events(samples, S, fps):
    n = len(samples)
    gap = 2 if fps <= 3 else 3
    changes = [i for i in range(1, n) if any(S[k][i] != S[k][i - 1] for k in ("round", "gold", "level", "xp", "shop"))]
    groups, cur = [], []
    for i in changes:
        if cur and i - cur[-1] > gap:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)

    def known_before(key, i):
        for j in range(i - 1, -1, -1):
            if S[key][j] is not None:
                return S[key][j]
        return None

    events = []
    for g in groups:
        a, b = g[0], min(n - 1, g[-1])
        t = samples[a]["t"]
        rnd = S["round"][b] or S["round"][a]
        r0, r1 = known_before("round", a), S["round"][b]
        g0, g1 = known_before("gold", a), S["gold"][b]
        l0, l1 = known_before("level", a), S["level"][b]
        x0, x1 = known_before("xp", a), S["xp"][b]
        sh0, sh1 = known_before("shop", a), S["shop"][b]
        new_round = r0 != r1 and r1 is not None
        ev = lambda kind, detail="", gold=None: events.append(  # noqa: E731
            {"t": t, "time": core.fmt_time(t), "round": rnd, "type": kind, "gold": gold, "detail": detail,
             "gold_after": g1})

        if new_round:
            ev("round_start", f"{r0 or '?'} → {r1}")
        if l0 and l1 and l1 > l0:
            ev("level_up", f"Lên cấp {l1}" + (f" (từ {l0})" if l0 else ""))
        delta = (g1 - g0) if (g0 is not None and g1 is not None) else 0
        replaced, bought = 0, []
        if sh0 and sh1:
            for x, y in zip(sh0, sh1):
                if x != y:
                    if y:
                        replaced += 1          # ô đổi sang tướng khác → dấu hiệu roll
                    elif x:
                        bought.append(x)       # ô có tướng → trống → đã mua
        rolled = replaced >= 3
        xp_changed = (x0 != x1 and x0 is not None and x1 is not None) or (l0 and l1 and l1 > l0)

        if new_round:
            if delta > 0:
                ev("income", f"Nhận vàng đầu vòng (+{delta})", delta)
            elif delta < 0:
                ev("spend", f"Tiêu {-delta} vàng lúc đổi vòng", delta)
            continue

        if delta < 0:
            rem = -delta
            if xp_changed and rem >= 4 and not bought:
                k = 1 if rolled else max(1, rem // 4)
                ev("buy_xp", f"Mua XP x{k}", -4 * k)
                rem -= 4 * k
            if rolled and rem >= 2:
                k = 1 if bought else max(1, rem // 2)
                ev("reroll", f"Roll x{k}", -2 * k)
                rem -= 2 * k
            if bought:
                per, extra = (divmod(rem, len(bought)) if rem > 0 else (0, 0))
                for j, name in enumerate(bought):
                    ev("buy", name, -(per + (extra if j == 0 else 0)) or None)
                rem = 0
            if rem > 0:
                ev("spend", f"Tiêu {rem} vàng (không rõ: mua tướng / Wisp / khác)", -rem)
        elif delta > 0:
            ev("gain", f"+{delta} vàng (bán tướng / lãi / Wisp…)", delta)
        else:
            if bought:
                for name in bought:
                    ev("buy", name + " (không thấy vàng giảm)")
            elif rolled:
                ev("free_roll", "Cửa hàng đổi mà không mất vàng (roll miễn phí?)")
    return events


# ============================================================ 4. tổng kết vòng
def summarize_rounds(samples, S, events, duration):
    rounds, n = [], len(samples)
    i = 0
    while i < n:
        r = S["round"][i]
        j = i
        while j + 1 < n and S["round"][j + 1] == r:
            j += 1
        if r is not None:
            golds = [S["gold"][k] for k in range(i, j + 1) if S["gold"][k] is not None]
            t0 = samples[i]["t"]
            t1 = samples[j + 1]["t"] if j + 1 < n else duration
            evs = [e for e in events if t0 <= e["t"] < t1 and e["round"] == r]
            rounds.append({
                "round": r, "start": t0, "end": t1, "time": core.fmt_time(t0),
                "duration": round(t1 - t0, 1),
                "gold_start": golds[0] if golds else None, "gold_end": golds[-1] if golds else None,
                "gold_max": max(golds) if golds else None,
                "spent": -sum(e["gold"] for e in evs if e["gold"] and e["gold"] < 0),
                "rolls": sum(int(e["detail"].split("x")[-1]) for e in evs if e["type"] == "reroll"),
                "xp_buys": sum(int(e["detail"].split("x")[-1]) for e in evs if e["type"] == "buy_xp"),
                "bought": [e["detail"] for e in evs if e["type"] == "buy"],
                "level": next((S["level"][k] for k in range(j, i - 1, -1) if S["level"][k]), None),
                "xp": next((S["xp"][k] for k in range(j, i - 1, -1) if S["xp"][k]), None),
                "level_up": [e["detail"] for e in evs if e["type"] == "level_up"],
            })
        i = j + 1
    # gộp các đoạn trùng vòng (OCR mất vòng giữa chừng)
    merged = []
    for r in rounds:
        if merged and merged[-1]["round"] == r["round"]:
            m = merged[-1]
            m["end"], m["duration"] = r["end"], round(r["end"] - m["start"], 1)
            m["gold_end"] = r["gold_end"] if r["gold_end"] is not None else m["gold_end"]
            for k in ("spent", "rolls", "xp_buys"):
                m[k] += r[k]
            m["bought"] += r["bought"]
            m["level_up"] += r["level_up"]
            m["level"], m["xp"] = r["level"] or m["level"], r["xp"] or m["xp"]
        else:
            merged.append(r)
    return merged


# ============================================================ 5. ảnh chốt mỗi vòng
def keyframes(info, prof, rounds, out_dir, lang, player_name, on_progress, cancel):
    kdir = os.path.join(out_dir, "keyframes")
    os.makedirs(kdir, exist_ok=True)
    for f in os.listdir(kdir):                     # chạy lại → xoá ảnh chốt của lần trước
        if f.lower().endswith(".jpg"):
            try:
                os.remove(os.path.join(kdir, f))
            except OSError:
                pass
    for idx, r in enumerate(rounds):
        if cancel and cancel():
            raise core.Cancelled()
        t = r["start"] + min(24.0, max(1.0, r["duration"] * 0.6))
        # 1 lần gọi ffmpeg lấy vài khung quanh t (cách nhau 2 giây): khung gần t nhất làm ảnh chốt,
        # các khung còn lại để bỏ phiếu số máu (video nén làm chữ số nhỏ nhoè)
        t0 = max(r["start"], t - 4.0)
        t1 = max(t0 + 0.1, min(t + 4.1, r["end"] - 0.3, info["duration"] or t + 4.1))
        near = [(tt, f) for tt, f in core.iter_frames(info, 0.5, cancel, t0, t1)]
        if near:
            t, frame = min(near, key=lambda x: abs(x[0] - t))
            extra = [f for tt, f in near if f is not frame]
        else:
            frame, extra = core.grab_frame(info, t), []
        if frame is None:
            continue
        name = f"{idx + 1:02d}_vong_{r['round']}.jpg"
        core.imwrite(os.path.join(kdir, name), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        r["keyframe"] = "keyframes/" + name
        r["keyframe_t"] = round(t, 1)
        r["traits_raw"] = ocr.read_traits(layout.crop(frame, prof["boxes"]["traits"]), lang)
        r["traits"] = ocr.parse_traits(r["traits_raw"])
        r["players"], r["players_panel"] = read_players_vote([frame] + extra, prof, lang, player_name,
                                                             layout.effective_height(prof, info["h"]))
        me = [p for p in r["players"] if p["me"]]
        r["hp"] = me[0]["hp"] if me else None
        r["hp_others"] = [p["hp"] for p in r["players"] if not p["me"]]
        if r["hp"] is not None and r["players_panel"] == "ok":
            r["rank_hp"] = 1 + sum(1 for h in r["hp_others"] if h > r["hp"])   # hạng theo máu (ước lượng)
        on_progress(0.85 + 0.1 * (idx + 1) / max(1, len(rounds)))


def read_players_vote(frames, prof, lang, player_name="", src_h=None):
    """Đọc cột máu trên vài khung hình, lấy theo đa số từng dòng (hoà → khung đầu tiên)."""
    reads = [ocr.read_players(layout.crop(f, prof["boxes"]["players"]), lang, player_name, src_h) for f in frames]
    base, status = reads[0]
    if len(reads) == 1:
        return base, status
    oks = [rd for rd in reads if rd[1] == "ok"] or [rd for rd in reads if rd[1] == "uncertain"]
    if oks:
        # khung có số dòng phổ biến nhất (ưu tiên khung đầu)
        n_common = Counter(len(p) for p, _ in oks).most_common(1)[0][0]
        same = [p for p, _ in oks if len(p) == n_common]
        base = same[0]
        status = oks[0][1]
        voted = []
        for i, row in enumerate(base):
            vals = [p[i]["hp"] for p in same if p[i]["me"] == row["me"]]
            best = max(vals, key=lambda v: (vals.count(v), -vals.index(v)))
            voted.append(dict(row, hp=best))
        base, dropped = ocr._keep_descending(voted)
        if dropped:
            status = "uncertain"
    return base, status


# ============================================================ 6. xuất file
def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(["; ".join(map(str, r.get(c))) if isinstance(r.get(c), list) else
                        ("" if r.get(c) is None else r.get(c)) for c in cols])


def out_dir_for(video):
    base = os.path.splitext(video)[0] + "_dtcl"
    os.makedirs(base, exist_ok=True)
    return base


def run_analysis(video, opts, on_progress=lambda p: None, log=print, cancel=None):
    """opts: profile, fps, keyframes, ai_board, ai_coach, api_key, model, player_name, ocr_lang, start, end."""
    t_begin = time.time()
    miss = core.missing_bins()
    if miss:
        raise RuntimeError("Thiếu: " + ", ".join(miss) + ". Hãy chạy lại install.bat.")
    prof = layout.load(opts.get("profile") or "default_1080p")
    try:
        fps = float(opts.get("fps") or 2)
    except (TypeError, ValueError):
        fps = 2.0
    fps = min(10.0, max(0.2, fps))
    lang = opts.get("ocr_lang") or "auto"
    start, end = float(opts.get("start") or 0), float(opts.get("end") or 0) or None
    info = core.probe(video)
    if info["duration"] and start >= info["duration"]:
        raise core.VideoError(f"Thời điểm bắt đầu ({core.fmt_time(start)}) nằm sau cuối video "
                              f"({core.fmt_time(info['duration'])}).")
    if end is not None and end <= start:
        raise core.VideoError("Thời điểm 'đến' phải sau thời điểm 'từ'.")
    try:
        out = out_dir_for(video)
    except OSError as e:
        raise RuntimeError(f"Không tạo được thư mục kết quả cạnh video (thiếu quyền ghi?):\n{e}") from None
    log(f"Video: {os.path.basename(video)}  {info['w']}x{info['h']}  {core.fmt_time(info['duration'])}")
    log(f"Profile: {prof['name']}" + ("" if prof.get("calibrated") else "  (CHƯA căn chỉnh — toạ độ ước lượng)"))
    log(f"Đọc {fps:g} khung/giây…")

    ff_err = []
    samples = sample_video(info, prof, fps, lang, on_progress, cancel, log, start, end, ff_err)
    if not samples:
        if not info["duration"]:
            raise core.VideoError(f"Video «{os.path.basename(video)}» dài 0 giây — không có khung hình nào để đọc.")
        raise core.VideoError(f"Không đọc được khung hình nào từ video «{os.path.basename(video)}» "
                              "(file hỏng hoặc đoạn thời gian chọn không có hình)."
                              + (f"\n(chi tiết: {ff_err[-1][:200]})" if ff_err else ""))
    if ff_err:
        log("  (ffmpeg báo lỗi khi giải mã — video có thể bị hỏng một phần; vẫn tiếp tục)")
    q = quality(samples)
    log("Tỉ lệ đọc được: " + ", ".join(f"{k} {v}%" for k, v in q.items()))
    S = clean(samples, fps)
    for i, s in enumerate(samples):
        for k in ("round", "gold", "level", "xp"):
            s[k + "_clean"] = S[k][i]
    events = derive_events(samples, S, fps)
    rounds = summarize_rounds(samples, S, events, info["duration"])
    log(f"Tìm thấy {len(rounds)} vòng, {len(events)} sự kiện.")

    warnings = []
    if q["round"] < 25 or q["gold"] < 25:
        warnings.append("Đọc được rất ít số vòng / vàng — có thể vùng HUD chưa khớp video này. "
                        "Hãy mở 'Căn chỉnh vùng' và kéo lại các ô cho đúng chỗ.")
    if q["shop"] < 10:
        warnings.append("Hầu như không đọc được tên tướng trong cửa hàng — sự kiện mua/roll sẽ thiếu.")

    if opts.get("keyframes", True) and rounds:
        log("Lưu ảnh chốt mỗi vòng + đọc bảng tộc/hệ, máu…")
        keyframes(info, prof, rounds, out, lang, opts.get("player_name", ""), on_progress, cancel)

    ai_notes = None
    if (opts.get("ai_board") or opts.get("ai_coach")) and opts.get("api_key"):
        import ai
        if opts.get("ai_board"):
            log("Gửi ảnh chốt cho Claude nhận diện bàn cờ…")
            for k, r in enumerate(rounds):
                if cancel and cancel():
                    raise core.Cancelled()
                if not r.get("keyframe"):
                    continue
                try:
                    r["ai"] = ai.read_board(os.path.join(out, r["keyframe"]), r, opts)
                except Exception as e:  # noqa: BLE001
                    r["ai_error"] = str(e)
                    log(f"  vòng {r['round']}: lỗi AI — {e}")
                on_progress(0.95 + 0.04 * (k + 1) / max(1, len(rounds)))
        if opts.get("ai_coach"):
            log("Nhờ Claude nhận xét trận…")
            try:
                ai_notes = ai.coach(rounds, events, opts)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"AI nhận xét lỗi: {e}")

    match = {
        "video": os.path.abspath(video), "duration": info["duration"], "resolution": [info["w"], info["h"]],
        "profile": prof["name"], "profile_calibrated": prof.get("calibrated", False), "fps": fps,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "read_rate_percent": q, "warnings": warnings,
        "summary": summary(rounds, events), "rounds": rounds, "events": events, "ai_notes": ai_notes,
    }
    tmp = os.path.join(out, "match.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(match, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(out, "match.json"))
    write_csv(os.path.join(out, "samples.csv"), samples,
              ["t", "round", "round_clean", "gold", "gold_clean", "level", "level_clean", "xp", "xp_clean"]
              + layout.SHOP + ["round_raw", "gold_raw", "level_raw", "xp_raw"])
    write_csv(os.path.join(out, "events.csv"), events, ["time", "t", "round", "type", "detail", "gold", "gold_after"])
    write_csv(os.path.join(out, "rounds.csv"), rounds,
              ["round", "time", "duration", "level", "xp", "hp", "rank_hp", "hp_others", "players_panel", "gold_start", "gold_end", "gold_max", "spent",
               "rolls", "xp_buys", "bought", "level_up", "keyframe"])
    if opts.get("chat_pack", True) and any(r.get("keyframe") for r in rounds):
        import chatpack
        pack, n_img = chatpack.write(out, rounds, match["summary"])
        match["chat_pack"] = {"folder": "gui_claude", "images": n_img}
        log(f"Gói gửi Claude chat: {n_img} ảnh + cau_hoi.txt trong thư mục gui_claude")
    import report
    rep = report.write(out, match)
    on_progress(1.0)
    log(f"Xong trong {time.time() - t_begin:.0f}s → {out}")
    return rep


def summary(rounds, events):
    lv = {}
    for e in events:
        if e["type"] == "level_up":
            lvl = int("".join(c for c in e["detail"].split("(")[0] if c.isdigit()) or 0)
            lv.setdefault(lvl, e["round"])
    return {
        "rounds_seen": len(rounds),
        "last_round": rounds[-1]["round"] if rounds else None,
        "final_level": next((r["level"] for r in reversed(rounds) if r.get("level")), None),
        "level_timing": {f"lv{k}": v for k, v in sorted(lv.items())},
        "total_spent": sum(r["spent"] for r in rounds),
        "total_rolls": sum(r["rolls"] for r in rounds),
        "total_xp_buys": sum(r["xp_buys"] for r in rounds),
        "units_bought": sum(len(r["bought"]) for r in rounds),
        "max_gold": max((r["gold_max"] for r in rounds if r.get("gold_max") is not None), default=None),
    }


def friendly_error(e):
    """Đổi lỗi kỹ thuật thành 1 câu tiếng Việt dễ hiểu (không traceback)."""
    if isinstance(e, (core.VideoError,)):
        return str(e)
    if isinstance(e, PermissionError):
        return f"Không có quyền ghi / đọc file: {getattr(e, 'filename', '') or e}\n(File đang mở trong chương trình khác?)"
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "Ổ đĩa đầy — không ghi được kết quả."
    if isinstance(e, OSError):
        return f"Lỗi đọc/ghi file: {e}"
    if isinstance(e, MemoryError):
        return "Hết bộ nhớ — hãy đóng bớt chương trình hoặc giảm 'Số khung/giây đọc'."
    if isinstance(e, RuntimeError) and str(e):
        return str(e)
    return f"Lỗi không mong muốn ({type(e).__name__}: {e}). Chi tiết đã ghi vào file log."


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    st = core.get_settings()
    ap.add_argument("--profile", default=st["profile"])
    ap.add_argument("--fps", type=float, default=st["fps"])
    ap.add_argument("--from", dest="start", type=float, default=0)
    ap.add_argument("--to", dest="end", type=float, default=0)
    ap.add_argument("--no-keyframes", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    o = dict(st, profile=a.profile, fps=a.fps, start=a.start, end=a.end, keyframes=not a.no_keyframes)
    try:
        print(run_analysis(a.video, o))
    except (KeyboardInterrupt, core.Cancelled):
        print("Đã huỷ.", file=sys.stderr)
        sys.exit(130)
    except Exception as ex:  # noqa: BLE001
        import tempfile
        import traceback
        try:
            with open(os.path.join(tempfile.gettempdir(), "dtclscan.log"), "a", encoding="utf-8") as fh:
                fh.write(traceback.format_exc())
        except OSError:
            pass
        print("LỖI: " + friendly_error(ex), file=sys.stderr)
        sys.exit(1)
