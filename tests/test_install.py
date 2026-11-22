"""TC10: cài đặt, menu chuột phải, mã hoá file, tự cập nhật, version.txt."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "virtualman209/dtcl-scan"


def _copy_app(dst):
    for f in os.listdir(ROOT):
        s = os.path.join(ROOT, f)
        if os.path.isfile(s) and (f.endswith((".py", ".pyw", ".txt", ".ico", ".npz", ".bat", ".ps1"))):
            shutil.copy(s, os.path.join(dst, f))
    os.makedirs(os.path.join(dst, "bin"), exist_ok=True)


def _run(app, *args):
    return subprocess.run([sys.executable, os.path.join(app, "install.py"), *args], capture_output=True, timeout=60)


def test_install_cli(tmp_path):
    app = str(tmp_path / "Cài đặt DTCLScan")
    os.makedirs(app)
    _copy_app(app)
    r = _run(app, "--config")
    assert r.returncode == 0, r.stderr
    out = r.stdout.decode("utf-8")
    assert "ffmpeg" in out and "tesseract" in out
    cfg = json.load(open(os.path.join(app, "config.json"), encoding="utf-8"))
    assert {"ffmpeg", "ffprobe", "tesseract"} <= set(cfg)
    r = _run(app, "--check")
    assert r.returncode == 0, r.stdout + r.stderr

    for arg, install in (("--reg", True), ("--unreg", False)):
        r = _run(app, arg)
        assert r.returncode == 0, r.stderr
        raw = r.stdout
        assert raw[:2] == b"\xff\xfe", "file .reg phải là UTF-16 LE có BOM"
        text = raw.decode("utf-16")
        assert text.startswith("Windows Registry Editor Version 5.00")
        assert "\r\n" in text
        exts = re.findall(r"SystemFileAssociations\\(\.\w+)\\shell\\DTCLScan\]", text)
        assert ".mp4" in exts and ".mkv" in exts
        if install:
            for verb, label in (("01analyze", "Phân tích trận ĐTCL"), ("02calibrate", "Căn chỉnh vùng HUD"),
                                ("03update", "Kiểm tra cập nhật")):
                assert f"\\shell\\{verb}\\command]" in text, verb
                assert label in text
            # mỗi định dạng video có đủ 3 mục
            assert text.count("\\command]") == 3 * len(set(exts))
            assert "dtclscan.pyw" in text
        else:
            assert "[-HKEY_CURRENT_USER" in text and "\\command]" not in text


def _bytes(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read()


def test_line_endings_and_encoding():
    for f in os.listdir(ROOT):
        if f.endswith(".bat"):
            b = _bytes(f)
            assert b.count(b"\n") == b.count(b"\r\n") > 0, f"{f} phải CRLF"
        if f.endswith(".ps1"):
            b = _bytes(f)
            assert b.count(b"\n") == b.count(b"\r\n") > 0, f"{f} phải CRLF"
            has_bom = b.startswith(b"\xef\xbb\xbf")
            if f == "setup.ps1":
                assert not has_bom, "setup.ps1 chạy qua irm | iex: không được có BOM"
            elif any(c > 127 for c in b):
                assert has_bom, f"{f} có tiếng Việt → phải UTF-8 BOM"
            b.decode("utf-8-sig")


def test_repo_urls():
    for f in ("setup.ps1", "update.ps1", "updater.py", "README.md"):
        t = _bytes(f).decode("utf-8-sig")
        assert REPO in t, f
        assert re.findall(r"virtualman209/[\w.-]+", t) and all(
            x == REPO for x in re.findall(r"virtualman209/[\w.-]+", t) if "MergeCutVid" not in x), f


def test_keep_lists():
    import updater
    need = {"profiles", "settings.json", "tessdata", "champions.txt", "bin"}
    assert need <= updater.KEEP
    for f in ("update.ps1", "setup.ps1"):
        t = _bytes(f).decode("utf-8-sig")
        keep = re.search(r"\$keep\s*=\s*@\(([^)]*)\)", t).group(1)
        for k in need:
            assert f'"{k}"' in keep, (f, k)


def test_version():
    t = _bytes("version.txt")
    assert t.count(b"\n") == t.count(b"\r\n")
    lines = t.decode("utf-8").splitlines()
    import updater
    assert updater._vtuple(lines[0].strip()) > updater._vtuple("1.3.0")
    assert len([ln for ln in lines[1:] if ln.strip()]) >= 2


def test_updater_keeps_user_files(tmp_path, monkeypatch):
    """Giả lập tải zip bản mới: file người dùng (profiles, settings, tessdata, champions, bin) được giữ nguyên."""
    import updater
    app = tmp_path / "app"
    app.mkdir()
    _copy_app(str(app))
    (app / "profiles").mkdir()
    (app / "profiles" / "cua_toi.json").write_text('{"name": "cua_toi"}', encoding="utf-8")
    (app / "settings.json").write_text('{"player_name": "Tôi"}', encoding="utf-8")
    (app / "tessdata").mkdir()
    (app / "tessdata" / "vie.traineddata").write_bytes(b"du lieu")
    (app / "champions.txt").write_text("Ahri\r\n", encoding="utf-8")
    (app / "bin" / "ffmpeg.exe").write_bytes(b"exe")
    (app / "version.txt").write_text("1.3.0\n", encoding="utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in ("dtclscan.pyw", "core.py", "version.txt", "champions.txt", "settings.json"):
            data = b"{}" if f == "settings.json" else (b"# moi\n" if f == "champions.txt" else _bytes(f))
            z.writestr(f"dtcl-scan-main/{f}", data)
        z.writestr("dtcl-scan-main/profiles/default_1080p.json", "{}")
        z.writestr("dtcl-scan-main/tessdata/vie.traineddata", "moi")
    monkeypatch.setattr(updater, "APP_DIR", str(app))
    monkeypatch.setattr(updater, "STATE", str(app / "update_state.json"))
    monkeypatch.setattr(updater, "_get", lambda url, timeout=6: buf.getvalue())
    v = updater._apply_update_python()
    assert v == _bytes("version.txt").decode("utf-8").splitlines()[0].strip()
    assert (app / "profiles" / "cua_toi.json").exists()
    assert not (app / "profiles" / "default_1080p.json").exists()
    assert "Tôi" in (app / "settings.json").read_text(encoding="utf-8")
    assert (app / "tessdata" / "vie.traineddata").read_bytes() == b"du lieu"
    assert (app / "champions.txt").read_text(encoding="utf-8").startswith("Ahri")
    assert (app / "bin" / "ffmpeg.exe").read_bytes() == b"exe"
