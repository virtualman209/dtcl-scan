"""Dữ liệu dùng chung cho các test (tạo 1 lần cho cả phiên pytest).

Video giả lập + video dựng từ ảnh HUD thật được đặt trong thư mục có dấu tiếng Việt và khoảng trắng
(kiểm luôn TC8 về đường dẫn).
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
REAL = os.path.join(TESTS, "fixtures", "real")
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)


def need_bins():
    for b in ("ffmpeg", "ffprobe", "tesseract"):
        if not shutil.which(b):
            pytest.skip(f"thiếu {b}")


@pytest.fixture(scope="session")
def truth():
    with open(os.path.join(REAL, "truth.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def real_frames():
    import cv2
    out = {}
    for f in ("hud_2-7.png", "hud_3-5_a.png", "hud_3-5_b.png"):
        out[f] = cv2.imread(os.path.join(REAL, f))
    return out


@pytest.fixture(scope="session")
def workdir(tmp_path_factory):
    d = tmp_path_factory.mktemp("dtcl") / "Thư mục thử có dấu"
    d.mkdir()
    return str(d)


@pytest.fixture(scope="session", autouse=True)
def isolate_user_files(tmp_path_factory):
    """Không đụng settings.json / profiles thật trong thư mục tool."""
    import core
    d = tmp_path_factory.mktemp("appdata")
    old = core.SETTINGS_PATH, core.PROFILE_DIR
    core.SETTINGS_PATH = str(d / "settings.json")
    core.PROFILE_DIR = str(d / "profiles")
    yield
    core.SETTINGS_PATH, core.PROFILE_DIR = old


def run_analysis_quiet(video, **opts):
    import analyze
    import core
    o = dict(core.DEFAULT_SETTINGS, profile="default_1080p", fps=2, keyframes=True, chat_pack=True,
             ocr_lang="auto")
    o.update(opts)
    logs = []
    t0 = time.time()
    rep = analyze.run_analysis(video, o, log=logs.append)
    secs = time.time() - t0
    with open(os.path.join(os.path.dirname(rep), "match.json"), encoding="utf-8") as f:
        m = json.load(f)
    return {"report": rep, "match": m, "seconds": secs, "log": logs, "dir": os.path.dirname(rep)}


@pytest.fixture(scope="session")
def fake1080(workdir):
    need_bins()
    import make_fake
    p = os.path.join(workdir, "trận giả 1080p.mp4")
    truth = make_fake.make(p, height=1080, crf=23)
    res = run_analysis_quiet(p)
    res.update(video=p, truth=truth)
    return res


@pytest.fixture(scope="session")
def fake720(workdir):
    need_bins()
    import make_fake
    p = os.path.join(workdir, "trận giả 720p nén.mp4")
    truth = make_fake.make(p, height=720, crf=35)
    res = run_analysis_quiet(p)
    res.update(video=p, truth=truth)
    return res


def make_real_video(path, crf=20):
    """Video 60s: 30s hud_3-5_a + 30s hud_3-5_b, nén lại libx264."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-loop", "1", "-t", "30", "-framerate", "10", "-i", os.path.join(REAL, "hud_3-5_a.png"),
                    "-loop", "1", "-t", "30", "-framerate", "10", "-i", os.path.join(REAL, "hud_3-5_b.png"),
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
                    "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", path], check=True)
    return path


@pytest.fixture(scope="session")
def real_video(workdir):
    need_bins()
    return make_real_video(os.path.join(workdir, "khung thật 3-5.mp4"))


@pytest.fixture(scope="session")
def real_result(real_video):
    return run_analysis_quiet(real_video)
