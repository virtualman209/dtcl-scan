"""TC6, TC7, TC11: chạy đầu cuối trên video giả lập và video dựng từ khung HUD thật."""
import json
import os
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS = ["report.html", "rounds.csv", "events.csv", "samples.csv", "match.json",
           os.path.join("gui_claude", "cau_hoi.txt")]


def _actions(match):
    got = []
    for e in match["events"]:
        if e["type"] in ("buy_xp", "reroll"):
            got += [(e["round"], e["type"], "")] * int(e["detail"].split("x")[-1])
        elif e["type"] == "buy":
            got.append((e["round"], "buy", e["detail"]))
    return Counter(got)


def _check_fake(res):
    want = Counter((a["round"], a["type"], a.get("name", "")) for a in res["truth"]["actions"])
    got = _actions(res["match"])
    hit = sum((want & got).values())
    extra = list((got - want).elements())
    print(f"đúng {hit}/{sum(want.values())}, thừa {extra}, thiếu {list((want - got).elements())}")
    assert hit == 10, (want, got)
    assert not extra, extra
    for f in OUTPUTS:
        assert os.path.isfile(os.path.join(res["dir"], f)), f
    kf = os.path.join(res["dir"], "keyframes")
    assert len([f for f in os.listdir(kf) if f.endswith(".jpg")]) == len(res["match"]["rounds"])
    html = open(res["report"], encoding="utf-8").read()
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    assert "Phân tích trận ĐTCL" in html
    m = res["match"]
    assert m["summary"]["last_round"] == "4-1"
    assert m["summary"]["final_level"] == res["truth"]["final_level"]


def test_tc6_fake_1080(fake1080):
    _check_fake(fake1080)


def test_tc6_fake_720_compressed(fake720):
    _check_fake(fake720)


def test_tc6_report_opens_in_browser(fake1080, tmp_path):
    """report.html mở được bằng trình duyệt thật (chrome headless) nếu máy có."""
    import shutil
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        import pytest
        pytest.skip("không có chrome")
    import pathlib
    shot = tmp_path / "report.png"
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", f"--screenshot={shot}",
                    "--window-size=1280,2000", pathlib.Path(fake1080["report"]).as_uri()],
                   capture_output=True, timeout=120)
    assert shot.is_file() and shot.stat().st_size > 10000
    review = os.path.join(ROOT, "_review", "x_shots")
    os.makedirs(review, exist_ok=True)
    shutil.copy(shot, os.path.join(review, "05_report_fake1080.png"))


def test_tc7_real_frames_video(real_result, truth):
    m = real_result["match"]
    rounds = [r for r in m["rounds"] if r["round"] == "3-5"]
    assert rounds, m["rounds"]
    r = rounds[0]
    assert r["gold_start"] == 43 and r["gold_end"] == 43
    assert r["level"] == 7
    assert r["hp"] == 87
    want_a = truth["hud_3-5_a.png"]["hp_others"]
    want_b = truth["hud_3-5_b.png"]["hp_others"]
    got = r["hp_others"]
    n = max(sum(a == b for a, b in zip(got, w)) for w in (want_a, want_b)) if len(got) == 7 else 0
    print("TC7 máu người khác:", got, f"{n}/7")
    assert n >= 5, got


def test_tc11_speed(fake1080):
    secs = fake1080["seconds"]
    print(f"TC11: video 3:20 ở 2 khung/giây xử lý trong {secs:.1f} giây")
    review = os.path.join(ROOT, "_review", "x_shots")
    os.makedirs(review, exist_ok=True)
    with open(os.path.join(review, "tc11_seconds.txt"), "w", encoding="utf-8") as f:
        f.write(f"{secs:.1f}\n")
    assert fake1080["match"]["duration"] >= 199
    assert secs < 90


def test_cli_runs(real_video):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analyze.py"), real_video, "--fps", "1"],
                       capture_output=True, timeout=300)
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    assert r.returncode == 0, out
    assert "Traceback" not in out
    rep = out.strip().splitlines()[-1]
    assert rep.endswith("report.html") and os.path.isfile(rep)
    with open(os.path.join(os.path.dirname(rep), "match.json"), encoding="utf-8") as f:
        assert json.load(f)["fps"] == 1
