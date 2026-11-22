"""Hồi quy logic vòng 2: ổn định chuỗi đọc, ranh giới vòng, profile mặc định, kiểm tra cài đặt, máu giảm dần."""
import json
import os
import subprocess
import sys
from itertools import groupby

import analyze
import core
import layout
import ocr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _segments(series):
    return [k for k, _ in groupby(series)]


def test_stabilize_recovers_from_one_wrong_higher_round():
    vals = ["3-1"] * 10 + ["3-7"] * 4 + ["3-1"] * 6 + ["3-2"] * 20 + ["3-3"] * 20 + ["4-1"] * 20
    out = analyze.stabilize(vals, 3, plausible=analyze.next_round_ok)
    assert _segments(out) == ["3-1", "3-2", "3-3", "4-1"]


def test_stabilize_backdates_to_first_read():
    # vàng đổi ở mẫu 3 → chuỗi sạch cũng đổi ở mẫu 3 (không trễ 1 mẫu so với vòng)
    assert analyze.stabilize([5, 5, 5, 10, 10, 10], 2) == [5, 5, 5, 10, 10, 10]
    r = analyze.stabilize(["1-1"] * 5 + ["1-2"] * 5, 3, plausible=analyze.next_round_ok)
    g = analyze.stabilize([5] * 5 + [10] * 5, 2)
    assert r.index("1-2") == g.index(10) == 5
    # nhiễu 1 mẫu không được nhận
    assert analyze.stabilize([5, 5, 9, 5, 5], 2) == [5] * 5


def test_round_end_values_not_from_next_round():
    """Mẫu đầu vòng mới (vàng đã cộng lãi) không được tính vào vàng cuối vòng cũ."""
    samples, S = [], {"round": [], "gold": [], "level": [], "xp": [], "shop": []}
    raw = [("1-1", 5, "2/6")] * 8 + [("1-2", 10, "4/6")] * 8
    for i, (r, gld, xp) in enumerate(raw):
        samples.append({"t": i * 0.5, "round": r, "gold": gld, "level": 3, "xp": xp,
                        **{k: "" for k in layout.SHOP}})
    S = analyze.clean(samples, 2)
    ev = analyze.derive_events(samples, S, 2)
    rounds = analyze.summarize_rounds(samples, S, ev, 8.0)
    assert [(r["round"], r["gold_end"], r["xp"]) for r in rounds] == [("1-1", 5, "2/6"), ("1-2", 10, "4/6")]


def test_keep_descending():
    rows = [{"hp": h, "me": m, "conf": 0.8} for h, m in
            [(103, False), (87, True), (80, False), (75, False), (62, False), (1, False), (58, False)]]
    kept, dropped = ocr._keep_descending(rows)
    assert [r["hp"] for r in kept] == [103, 87, 80, 75, 62, 58] and dropped == 1
    rows = [{"hp": h, "me": False, "conf": 0.8} for h in (60, 79, 64, 61)]
    kept, dropped = ocr._keep_descending(rows)
    assert dropped >= 1


def test_default_profile_follows_code(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "PROFILE_DIR", str(tmp_path / "profiles"))
    assert layout.list_profiles()[0] == "default_1080p"
    assert not os.path.exists(core.PROFILE_DIR) or not os.listdir(core.PROFILE_DIR)   # không tự ghi file
    os.makedirs(core.PROFILE_DIR, exist_ok=True)
    old = {"name": "default_1080p", "calibrated": False, "boxes": {"players": [0.86, 0.14, 1.0, 0.76]}}
    json.dump(old, open(os.path.join(core.PROFILE_DIR, "default_1080p.json"), "w", encoding="utf-8"))
    assert layout.load("default_1080p")["boxes"]["players"] == layout.DEFAULT["boxes"]["players"]
    old["calibrated"] = True
    json.dump(old, open(os.path.join(core.PROFILE_DIR, "default_1080p.json"), "w", encoding="utf-8"))
    assert layout.load("default_1080p")["boxes"]["players"] == [0.86, 0.14, 1.0, 0.76]


def test_install_check_needs_vie(tmp_path):
    from test_install import _copy_app
    app = tmp_path / "app"
    app.mkdir()
    _copy_app(str(app))
    (app / "tessdata").mkdir()
    (app / "tessdata" / "eng.traineddata").write_bytes(b"x")       # chỉ có tiếng Anh
    r = subprocess.run([sys.executable, str(app / "install.py"), "--check"], capture_output=True, timeout=60)
    assert r.returncode == 1 and b"tessdata-vie" in r.stdout


def test_settings_has_no_dead_player_name_field():
    src = open(os.path.join(ROOT, "dtclscan.pyw"), encoding="utf-8").read()
    assert '("player_name"' not in src
    assert "Tên trong game" not in open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()


def test_single_wrong_reads_do_not_corrupt(fake1080, monkeypatch):
    """Tiêm lỗi (vòng 2 review): MỘT lần OCR sai — vòng 4-1 → '1-1', vòng 2-2 → '2-7' (lớn hơn), cấp 6 → 1 —
    không được sinh vòng ma, xoá đoạn đúng, làm mất hành động hay làm cấp đi lùi."""
    import threading
    orig = ocr.read_field
    lock = threading.Lock()
    seen = {}
    wrong = {("round", "4-1"): "1-1", ("round", "2-2"): "2-7", ("level", 6): 1}

    def fake(c, key, ftype, lang="eng"):
        raw, val = orig(c, key, ftype, lang)
        k = (key, val)
        if k in wrong:
            with lock:
                seen[k] = seen.get(k, 0) + 1
                if seen[k] == 3:
                    return str(wrong[k]), wrong[k]
        return raw, val

    monkeypatch.setattr(ocr, "read_field", fake)
    o = dict(core.DEFAULT_SETTINGS, fps=2, keyframes=False, chat_pack=False)
    rep = analyze.run_analysis(fake1080["video"], o, log=lambda s: None)
    m = json.load(open(os.path.join(os.path.dirname(rep), "match.json"), encoding="utf-8"))
    assert all(v >= 3 for v in seen.values()) and len(seen) == 3, seen    # đã tiêm đủ 3 lỗi
    truth = fake1080["truth"]
    assert [r["round"] for r in m["rounds"]] == truth["rounds"]
    assert m["summary"]["final_level"] == truth["final_level"]
    assert m["summary"]["units_bought"] == 3 and m["summary"]["total_xp_buys"] == 4
    assert m["summary"]["total_rolls"] == 3


def _k(*parts):
    out = []
    for kind, n in parts:
        out += [kind] * n
    return out


def test_stabilize_change_frame_cases():
    """Đọc sai ở KHUNG ĐỔI (lần đọc 'new' + 'recheck' trên gần như cùng hình), rồi lần đọc lại định kỳ ra đúng."""
    from itertools import groupby

    def seg(r):
        return [(k, len(list(g))) for k, g in groupby(r)]
    k = _k(("new", 1), ("same", 9), ("new", 1), ("recheck", 1), ("same", 14), ("reread", 1), ("same", 19))
    # vòng: 3-1 → (đọc nhầm 3-7) → 3-2: không kẹt ở 3-7, ranh giới vòng ở khung đổi
    r = analyze.stabilize(["3-1"] * 10 + ["3-7"] * 16 + ["3-2"] * 20, 2, k, analyze.next_round_ok)
    assert seg(r) == [("3-1", 10), ("3-2", 36)]
    # cấp: 4 → (đọc nhầm 9) → 5
    assert seg(analyze.stabilize([4] * 10 + [9] * 16 + [5] * 20, 2, k, analyze.level_step_ok)) == [(4, 10), (5, 36)]
    # vàng: 13 → (đọc nhầm 29 hai lần trên cùng hình) → lần đọc lại ra 19: cả đoạn là 19
    assert seg(analyze.stabilize([13] * 10 + [29] * 16 + [19] * 20, 2, k)) == [(13, 10), (19, 36)]
    # cửa hàng: lần đọc đầu ở khung đổi sai 1 ô, lần đọc ngay sau đúng → vẫn nhận cửa hàng mới
    k2 = _k(("new", 1), ("same", 9), ("new", 1), ("recheck", 1), ("same", 19))
    assert seg(analyze.stabilize(["a"] * 10 + ["X"] + ["b"] * 20, 2, k2)) == [("a", 10), ("b", 21)]
    # vàng 16 → 10 → 16 là thay đổi thật (không phải "hoàn tác")
    g = analyze.stabilize([16] * 10 + [10] * 10 + [16] * 10, 2)
    assert seg(g) == [(16, 10), (10, 10), (16, 10)]


def test_change_frame_wrong_reads_do_not_corrupt(fake1080, monkeypatch):
    """Tiêm lỗi ở khung đổi (2 lần OCR đầu của giá trị mới sai): vòng 3-2→'3-7', cấp 5→9, vàng 19→29;
    ô cửa hàng 1: lần OCR đầu mỗi khi đổi tên ra tên nhiễu. Mọi hành động / vòng / cấp vẫn đúng."""
    import threading
    orig = ocr.read_field
    lock = threading.Lock()
    cnt, log, last = {}, [], {"shop1": None}

    def fake(c, key, ftype, lang="eng"):
        raw, val = orig(c, key, ftype, lang)
        with lock:
            n = cnt[(key, val)] = cnt.get((key, val), 0) + 1
            rep = None
            if key == "round" and val == "3-2" and n <= 2:
                rep = "3-7"
            elif key == "level" and val == 5 and n <= 2:
                rep = 9
            elif key == "gold" and val == 19 and n <= 2:
                rep = 29
            elif key == "shop1" and val and val != last["shop1"]:
                last["shop1"] = val
                rep = "Xyzzq"
            if rep is not None:
                log.append(key)
                return str(rep), rep
        return raw, val

    monkeypatch.setattr(ocr, "read_field", fake)
    o = dict(core.DEFAULT_SETTINGS, fps=2, keyframes=False, chat_pack=False)
    rep = analyze.run_analysis(fake1080["video"], o, log=lambda s: None)
    m = json.load(open(os.path.join(os.path.dirname(rep), "match.json"), encoding="utf-8"))
    assert {"round", "level", "gold", "shop1"} <= set(log), log
    truth = fake1080["truth"]
    from collections import Counter
    want = Counter((a["round"], a["type"], a.get("name", "")) for a in truth["actions"])
    got = Counter()
    for e in m["events"]:
        if e["type"] in ("buy_xp", "reroll"):
            got[(e["round"], e["type"], "")] += int(e["detail"].split("x")[-1])
        elif e["type"] == "buy":
            got[(e["round"], "buy", e["detail"])] += 1
    assert got == want, (got, want)
    assert [r["round"] for r in m["rounds"]] == truth["rounds"]
    ends = {r["round"]: (r["gold_end"], r["level"]) for r in m["rounds"]}
    assert all(ends[w["round"]] == (w["gold_end"], w["level"]) for w in truth["round_end"]), ends
    assert not [e for e in m["events"] if e["type"] in ("spend", "free_roll")]


def test_hard_scenario_lagged_shop(workdir):
    """Cửa hàng hiện tên mới trễ 0,4s sau số vàng (hoạt ảnh lật thẻ); bán rồi roll, vàng augment rồi mua XP…"""
    import make_hard
    from collections import Counter
    from conftest import run_analysis_quiet
    p = os.path.join(workdir, "khó trễ 0.4.mp4")
    truth = make_hard.make(p, lag=0.4)
    m = run_analysis_quiet(p, keyframes=False, chat_pack=False)["match"]
    want = Counter((a["round"], a["type"], a.get("name", "")) for a in truth["actions"]
                   if a["type"] in ("buy_xp", "reroll", "buy"))
    got = Counter()
    for e in m["events"]:
        if e["type"] in ("buy_xp", "reroll"):
            got[(e["round"], e["type"], "")] += int(e["detail"].split("x")[-1])
        elif e["type"] == "buy":
            got[(e["round"], "buy", e["detail"])] += 1
    assert got == want, (got, want)
    ends = {r["round"]: r["gold_end"] for r in m["rounds"]}
    assert all(ends[w["round"]] == w["gold_end"] for w in truth["round_end"]), ends
