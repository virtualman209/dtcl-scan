"""TC2–TC5: OCR trên 3 khung HUD thật (toạ độ mặc định trong layout.py)."""
import difflib

import pytest

import layout
import ocr

B = layout.DEFAULT["boxes"]
FILES = ["hud_2-7.png", "hud_3-5_a.png", "hud_3-5_b.png"]


@pytest.fixture(scope="module", autouse=True)
def _bins():
    from conftest import need_bins
    need_bins()


def test_tc2_numbers(real_frames, truth):
    ok, bad = 0, []
    for f in FILES:
        for k in ("round", "gold", "level", "xp"):
            raw, v = ocr.read_field(layout.crop(real_frames[f], B[k]), k, layout.FIELDS[k][1], "auto")
            if str(v) == str(truth[f][k]):
                ok += 1
            else:
                bad.append((f, k, v, raw))
    print(f"TC2: {ok}/12", bad)
    assert ok == 12, bad


def test_tc3_shop(real_frames, truth):
    ok, bad = 0, []
    for f in FILES:
        for i in range(5):
            key = f"shop{i + 1}"
            _, v = ocr.read_field(layout.crop(real_frames[f], B[key]), key, "name", "auto")
            want = truth[f]["shop"][i]
            if want == "":
                assert not v, f"{f} {key}: ô trống nhưng đọc ra {v!r}"
            if ocr.norm(v or "") == ocr.norm(want):
                ok += 1
            else:
                bad.append((f, key, v, want))
    print(f"TC3: {ok}/15", bad)
    assert ok >= 14, bad


def test_tc4_hp(real_frames, truth):
    me_ok, oth_ok, bad = 0, 0, []
    for f in FILES:
        players, status = ocr.read_players(layout.crop(real_frames[f], B["players"]), "auto")
        me = [p["hp"] for p in players if p["me"]]
        others = [p["hp"] for p in players if not p["me"]]
        if me[:1] == [truth[f]["hp_me"]]:
            me_ok += 1
        else:
            bad.append((f, "me", me))
        want = truth[f]["hp_others"]
        if want is None:
            # bảng đang hiện thống kê sát thương → không được trả số máu người khác sai
            assert status != "ok" or not others, f"{f}: đọc nhầm bảng sát thương thành máu {others}"
            continue
        n = sum(a == b for a, b in zip(others, want)) if len(others) == len(want) else 0
        oth_ok += n
        if n < len(want):
            bad.append((f, "others", others, want))
    print(f"TC4: máu mình {me_ok}/3, người khác {oth_ok}/14", bad)
    assert me_ok == 3, bad
    assert oth_ok >= 13, bad


def test_tc5_traits(real_frames, truth):
    name_ok = cnt_ok = total = 0
    report = []
    for f in FILES:
        lines = ocr.read_traits(layout.crop(real_frames[f], B["traits"]), "auto")
        got = ocr.parse_traits(lines)
        want = [(ocr.norm(n), c) for n, c in truth[f]["traits"]]
        total += len(want)
        junk = 0
        used = set()
        for g in got:
            n = ocr.norm(g["trait"])
            scores = [(difflib.SequenceMatcher(None, n, w[0]).ratio(), j) for j, w in enumerate(want) if j not in used]
            if not scores:
                junk += 1
                continue
            r, j = max(scores)
            if r >= 0.8:
                used.add(j)
                name_ok += 1
                cnt_ok += g["count"] == want[j][1]
            else:
                junk += 1
        report.append((f, lines))
        assert junk <= 2, f"{f}: {junk} dòng rác: {lines}"
    print(f"TC5: tên {name_ok}/{total}, số đếm {cnt_ok}/{total}", report)
    assert total == 25
    assert name_ok >= 21, report
    assert cnt_ok >= 20, report


def test_empty_regions_give_nothing():
    import numpy as np
    black = np.zeros((40, 150, 3), np.uint8)
    assert ocr.read_field(black, "shop1", "name", "auto")[1] == ""
    assert ocr.read_field(black, "gold", "int", "auto")[1] is None
    assert ocr.read_traits(np.zeros((480, 160, 3), np.uint8), "auto") == []
    assert ocr.read_players(np.zeros((600, 80, 3), np.uint8))[1] != "ok"


def test_parse_helpers():
    assert ocr.parse_round("2 3-5") == "3-5"
    assert ocr.parse_round("35") == "3-5"
    assert ocr.parse_round("9-9") is None
    assert ocr.parse_xp("0/56") == "0/56"
    assert ocr.parse_xp("60/56") is None
    assert ocr.parse_int("Cấp 7", 1, 10) == 7
    assert ocr.clean_name("_ Hỏa Ngục |") == "Hỏa Ngục"
    assert ocr.norm("Mâm Non") == "mamnon"
