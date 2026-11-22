"""TC8: đường dẫn có dấu/khoảng trắng, video hỏng / không phải video / 0 giây, chạy 2 lần, huỷ giữa chừng."""
import os
import shutil
import subprocess
import sys

import pytest

import analyze
import core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cli(path, *args):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "analyze.py"), path, *args],
                       capture_output=True, timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def _opts(**kw):
    return dict(core.DEFAULT_SETTINGS, fps=2, **kw)


def test_vietnamese_path(real_result):
    assert "Thư mục thử có dấu" in real_result["dir"]
    kf = os.path.join(real_result["dir"], "keyframes")
    assert any(f.endswith(".jpg") for f in os.listdir(kf))
    assert os.listdir(os.path.join(real_result["dir"], "gui_claude"))


@pytest.mark.parametrize("kind", ["text", "empty", "zero", "truncated", "missing"])
def test_bad_videos_clear_message(workdir, kind, fake1080):
    p = os.path.join(workdir, f"hỏng {kind}.mp4")
    if kind == "text":
        open(p, "w", encoding="utf-8").write("đây không phải video")
    elif kind == "empty":
        open(p, "wb").close()
    elif kind == "zero":
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25",
                        "-frames:v", "1", "-c:v", "libx264", p], check=True)
    elif kind == "truncated":
        with open(fake1080["video"], "rb") as f:
            data = f.read()
        open(p, "wb").write(data[: len(data) // 3])       # moov ở cuối file → mất → hỏng
    # gọi hàm
    with pytest.raises(Exception) as ei:
        analyze.run_analysis(p, _opts(), log=lambda s: None)
    msg = analyze.friendly_error(ei.value)
    assert isinstance(ei.value, core.VideoError), repr(ei.value)
    assert any(w in msg for w in ("hỏng", "0 giây", "Không tìm thấy", "rỗng")), msg
    # gọi dòng lệnh: không traceback, có thông báo tiếng Việt, mã thoát 1
    code, out = cli(p)
    assert code == 1, out
    assert "Traceback" not in out
    assert "LỖI:" in out


def test_corrupted_middle_still_runs(workdir, fake1080):
    """Hỏng 1 đoạn giữa file: vẫn chạy ra kết quả (bỏ qua chỗ hỏng), không treo."""
    with open(fake1080["video"], "rb") as f:
        data = bytearray(f.read())
    n = len(data)
    data[n // 2: n // 2 + 200000] = os.urandom(200000)
    p = os.path.join(workdir, "hỏng giữa.mp4")
    open(p, "wb").write(bytes(data))
    rep = analyze.run_analysis(p, _opts(keyframes=False, chat_pack=False), log=lambda s: None)
    assert os.path.isfile(rep)


def test_run_twice_overwrites(real_video, tmp_path):
    p = str(tmp_path / "chạy hai lần.mp4")
    shutil.copy(real_video, p)
    r1 = analyze.run_analysis(p, _opts(), log=lambda s: None)
    out = os.path.dirname(r1)
    stale = os.path.join(out, "keyframes", "99_vong_cu.jpg")
    open(stale, "wb").write(b"x")
    r2 = analyze.run_analysis(p, _opts(), log=lambda s: None)
    assert r1 == r2 and os.path.isfile(r2)
    assert not os.path.exists(stale), "ảnh chốt cũ không được dọn"
    assert not [f for f in os.listdir(out) if f.endswith(".tmp")]


def test_cancel(fake1080):
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 15

    with pytest.raises(core.Cancelled):
        analyze.run_analysis(fake1080["video"], _opts(), log=lambda s: None, cancel=cancel)


def test_bad_time_range(real_video):
    with pytest.raises(core.VideoError):
        analyze.run_analysis(real_video, _opts(start=500), log=lambda s: None)
    with pytest.raises(core.VideoError):
        analyze.run_analysis(real_video, _opts(start=20, end=10), log=lambda s: None)


def test_unicode_image_io(tmp_path):
    import numpy as np
    p = str(tmp_path / "ảnh thử đ.jpg")
    img = np.full((20, 30, 3), 128, np.uint8)
    assert core.imwrite(p, img, [])
    back = core.imread(p)
    assert back is not None and back.shape == img.shape
    assert core.imread(str(tmp_path / "không có.jpg")) is None


def test_old_profile_and_settings_compatible(tmp_path, monkeypatch):
    """Profile cũ (thiếu vùng mới / thừa khoá lạ) và settings.json cũ vẫn đọc được."""
    import json
    import layout
    monkeypatch.setattr(core, "PROFILE_DIR", str(tmp_path / "profiles"))
    monkeypatch.setattr(core, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    os.makedirs(core.PROFILE_DIR)
    # vùng vàng cũ rộng (dính icon đồng xu, bao trùm vùng mặc định) → tự thay bằng vùng mặc định mới;
    # vùng cấp người dùng khoanh ở chỗ khác hẳn (HUD lệch) → giữ nguyên
    old = {"name": "cu", "calibrated": True, "la": 1,
           "boxes": {"gold": [0.5, 0.8, 0.56, 0.85], "level": [0.30, 0.50, 0.35, 0.55]}}
    json.dump(old, open(os.path.join(core.PROFILE_DIR, "cu.json"), "w", encoding="utf-8"))
    p = layout.load("cu")
    assert p["boxes"]["gold"] == layout.DEFAULT["boxes"]["gold"]
    assert p["boxes"]["level"] == [0.30, 0.50, 0.35, 0.55]
    assert "gold" in p["migrated"] and "level" not in p["migrated"]
    assert set(layout.FIELDS) <= set(p["boxes"])
    json.dump({"fps": "3", "profile": "cu"}, open(core.SETTINGS_PATH, "w", encoding="utf-8"))
    st = core.get_settings()
    assert st["profile"] == "cu" and st["ocr_lang"] == "auto"
    open(os.path.join(core.PROFILE_DIR, "hong.json"), "w").write("{không phải json")
    assert layout.load("hong")["boxes"] == layout.DEFAULT["boxes"]
