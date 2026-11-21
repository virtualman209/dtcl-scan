"""Độ bền OCR trên ảnh HUD thật đã biến đổi: thu 720p, nén JPEG q60, dịch lệch 2–3px (căn chỉnh lệch).

Ngưỡng chọn theo số đo thật (xem báo cáo vòng 2), không phải mong muốn:
- Số HUD 12/12, cửa hàng >= 14/15, máu mình 3/3, hud_2-7 không bao giờ trả máu người khác "ok": mọi biến thể.
- Tộc/hệ: tên và số đếm >= 22/25, rác <= 2 dòng/ảnh: mọi biến thể (thấp nhất đo được: 720p+JPEG60 = 22).
- Máu người khác: ở 720p hoặc khoanh lệch sang PHẢI 2–3px, chữ số quá nhoè / bị cắt → không đọc đúng được,
  nhưng KHÔNG được báo "ok" (phải là uncertain/unknown). Các biến thể còn lại: >= 13/14 và trạng thái "ok".
  Mọi biến thể: số giá trị sai mà vẫn "ok" <= 1 (một lần đọc nhầm vẫn đúng thứ tự giảm dần, vd 68→64,
  thì không có cách phát hiện).
"""
import difflib
from collections import Counter

import pytest

import layout
import ocr
from variants import variant

B = layout.DEFAULT["boxes"]
FILES = ["hud_2-7.png", "hud_3-5_a.png", "hud_3-5_b.png"]
HP_OK = {"orig": 14, "jpeg60": 13, "shift0_2": 14, "shift-2_0": 13, "shift-3_0": 13, "shift-2_-2": 13}
HP_SAFE_ONLY = ["720", "720jpeg60", "shift2_0", "shift3_3"]


@pytest.fixture(scope="module", autouse=True)
def _bins():
    from conftest import need_bins
    need_bins()


def _traits_score(lines, want_pairs):
    got = ocr.parse_traits(lines)
    want = [(ocr.norm(n), c) for n, c in want_pairs]
    used, name, cnt, junk = set(), 0, 0, 0
    for g in got:
        n = ocr.norm(g["trait"])
        sc = [(difflib.SequenceMatcher(None, n, w).ratio(), j) for j, (w, _) in enumerate(want) if j not in used]
        if sc and max(sc)[0] >= 0.8:
            j = max(sc)[1]
            used.add(j)
            name += 1
            cnt += g["count"] == want[j][1]
        else:
            junk += 1
    return name, cnt, junk


@pytest.mark.parametrize("v", list(HP_OK) + HP_SAFE_ONLY)
def test_variant(v, real_frames, truth):
    num = shop = me = name = cnt = hp_good = wrong_ok = 0
    notes = []
    for f in FILES:
        img = variant(real_frames[f], v)
        t = truth[f]
        for k in ("round", "gold", "level", "xp"):
            _, val = ocr.read_field(layout.crop(img, B[k]), k, layout.FIELDS[k][1], "auto")
            num += str(val) == str(t[k])
        for i in range(5):
            key = f"shop{i + 1}"
            _, val = ocr.read_field(layout.crop(img, B[key]), key, "name", "auto")
            if t["shop"][i] == "":
                assert not val, (f, key, val)
            shop += ocr.norm(val or "") == ocr.norm(t["shop"][i])
        players, st = ocr.read_players(layout.crop(img, B["players"]), "auto")
        mine = [p["hp"] for p in players if p["me"]]
        others = [p["hp"] for p in players if not p["me"]]
        me += mine[:1] == [t["hp_me"]]
        if t["hp_others"] is None:
            assert not (st == "ok" and others), (v, f, others)
        else:
            good = sum((Counter(others) & Counter(t["hp_others"])).values())
            if st == "ok":
                wrong_ok += len(others) - good
                hp_good += good
            elif v in HP_OK:
                notes.append(f"{f}: trạng thái {st} {others}")
        n, c, junk = _traits_score(ocr.read_traits(layout.crop(img, B["traits"]), "auto"), t["traits"])
        name += n
        cnt += c
        assert junk <= 2, (v, f, junk)
    print(f"{v}: số {num}/12 cửa hàng {shop}/15 máu mình {me}/3 máu khác(ok) {hp_good}/14 "
          f"sai-mà-ok {wrong_ok} tộc/hệ {name}/{cnt} /25", notes)
    assert num == 12
    assert shop >= 14
    assert me == 3
    assert name >= 22 and cnt >= 22
    assert wrong_ok <= 1
    if v in HP_OK:
        assert hp_good >= HP_OK[v], notes
