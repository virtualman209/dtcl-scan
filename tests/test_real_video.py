"""Hồi quy từ VIDEO THẬT của người dùng (lỗi 1.4.0: cửa hàng 0%, vàng dính icon, 'Cấp 10' → 1, máu sai)."""
import json
import os
import shutil
import sys

import cv2
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import core  # noqa: E402
import layout  # noqa: E402
import ocr  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "real_video")
TRUTH = json.load(open(os.path.join(FIX, "truth.json"), encoding="utf-8"))


def _sys_tessdata():
    for d in ("/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata",
              "/usr/share/tessdata", "/usr/local/share/tessdata"):
        if os.path.isfile(os.path.join(d, "eng.traineddata")):
            return d
    return None


@pytest.fixture
def windows_like_tessdata(tmp_path, monkeypatch):
    """Giống máy Windows sau install.bat: thư mục tessdata RIÊNG chỉ có eng/vie.traineddata, KHÔNG có configs/."""
    src = _sys_tessdata()
    if not src:
        pytest.skip("không tìm thấy tessdata hệ thống")
    td = tmp_path / "tessdata"
    td.mkdir()
    for lang in ("eng", "vie"):
        if os.path.isfile(os.path.join(src, lang + ".traineddata")):
            shutil.copy(os.path.join(src, lang + ".traineddata"), td)
    monkeypatch.setattr(core, "TESSDATA_DIR", str(td))
    monkeypatch.setattr(ocr, "_LANGS", None)
    monkeypatch.setattr(ocr, "_TSV_OK", None)
    return td


def _user_profile(tmp_path, monkeypatch):
    pd = tmp_path / "profiles"
    pd.mkdir(exist_ok=True)
    data = json.load(open(os.path.join(FIX, "profile_user_v13.json"), encoding="utf-8"))
    data["name"] = "user_v13"
    (pd / "user_v13.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(core, "PROFILE_DIR", str(pd))
    return layout.load("user_v13")


def test_shop_names_with_private_tessdata(windows_like_tessdata, tmp_path, monkeypatch):
    prof = _user_profile(tmp_path, monkeypatch)
    im = cv2.imread(os.path.join(FIX, "v_2-2.jpg"))
    got = [ocr.read_field(layout.crop(im, prof["boxes"][k]), k, "name", "auto")[1] for k in layout.SHOP]
    exp = TRUTH["v_2-2.jpg"]["shop"]
    ok = sum(ocr.norm(a) == ocr.norm(b) for a, b in zip(got, exp))
    assert ok >= 5, (got, exp)
    assert (windows_like_tessdata / "configs" / "tsv").is_file()


def test_old_profile_migrated_numbers(windows_like_tessdata, tmp_path, monkeypatch):
    prof = _user_profile(tmp_path, monkeypatch)
    assert set(prof.get("migrated", [])) >= {"gold", "level", "players"}
    for name in ("v_2-2.jpg", "v_6-1.jpg"):
        im = cv2.imread(os.path.join(FIX, name))
        t = TRUTH[name]
        for k in ("round", "gold", "level", "xp"):
            if k in t:
                v = ocr.read_field(layout.crop(im, prof["boxes"][k]), k, layout.FIELDS[k][1], "auto")[1]
                assert v == t[k], (name, k, v, t[k])


def test_hp_real_video(tmp_path, monkeypatch):
    prof = _user_profile(tmp_path, monkeypatch)
    im = cv2.imread(os.path.join(FIX, "v_3-6.jpg"))
    pl, st = ocr.read_players(layout.crop(im, prof["boxes"]["players"]), "auto", src_h=1080)
    me = [p["hp"] for p in pl if p["me"]]
    others = [p["hp"] for p in pl if not p["me"]]
    t = TRUTH["v_3-6.jpg"]
    assert me == [t["hp_me"]]
    assert sum(a == b for a, b in zip(others, t["hp_others"])) >= 6, others
