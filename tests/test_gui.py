"""TC9: giao diện dưới Xvfb 1366x768 (chạy tests/gui_shots.py bằng 1 Python có tkinter)."""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _python_with_tk():
    cands = [sys.executable, shutil.which("python3"), "/usr/bin/python3", "/usr/bin/python3.12"]
    for py in cands:
        if py and os.path.exists(py):
            r = subprocess.run([py, "-c", "import tkinter, cv2, numpy"], capture_output=True)
            if r.returncode == 0:
                return py
    return None


def test_tc9_gui_under_xvfb():
    py = _python_with_tk()
    if not py:
        pytest.skip("không có Python nào có tkinter + opencv")
    if not shutil.which("xvfb-run"):
        pytest.skip("không có xvfb-run")
    out = os.path.join(ROOT, "_review", "x_shots")
    r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1366x768x24", py,
                        os.path.join(ROOT, "tests", "gui_shots.py"), out],
                       capture_output=True, timeout=600)
    text = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    print(text)
    assert r.returncode == 0, text
    assert "GUI OK" in text
    for f in ("01_man_hinh_chinh.png", "02_cai_dat.png", "03_can_chinh.png", "04_thu_doc_tat_ca.png"):
        assert os.path.getsize(os.path.join(out, f)) > 5000, f
