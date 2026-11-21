"""Tạo video HUD giả lập (có đáp án) để kiểm thử cả quy trình.

    python tests/make_fake.py OUT.mp4 [--height 1080] [--crf 23] [--fps 10]

Ghi kèm OUT.truth.json: danh sách 10 hành động (4 mua XP, 3 roll, 3 mua tướng) theo vòng,
vàng / XP / cấp ở cuối mỗi vòng (round_end) và cuối trận. Video dài 10 vòng x 20 giây = 3:20.
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import layout  # noqa: E402

NAMES = ["Ahri", "Garen", "Lillia", "Veigar", "Rakan", "Xayah", "Ornn", "Malphite", "Azir", "Warwick",
         "Kayle", "Rammus", "Teemo", "Yorick", "Sett", "Zyra", "Taric", "Maokai"]
ROUNDS = ["1-1", "1-2", "1-3", "2-1", "2-2", "2-3", "3-1", "3-2", "3-3", "4-1"]
# (vòng, giây trong vòng) -> hành động
ACTS = {("2-1", 8): "xp", ("2-1", 12): "roll", ("2-1", 15): "buy2", ("3-2", 6): "xp", ("3-2", 9): "roll",
        ("3-2", 11): "roll", ("3-2", 14): "buy1", ("3-2", 16): "buy4", ("4-1", 5): "xp", ("4-1", 7): "xp"}
ROUND_SEC = 20


def make(out, height=1080, crf=23, fps=10, seed=1):
    W, H = 1920, 1080
    B = layout.DEFAULT["boxes"]
    rng = random.Random(seed)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    ow = int(round(W * height / H / 2)) * 2
    proc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                             "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-vf", f"scale={ow}:{height}",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", out],
                            stdin=subprocess.PIPE)

    def put(img, key, text, scale=0.9):
        x1, y1, x2, y2 = B[key]
        cv2.putText(img, text, (int(x1 * W) + 4, int(y2 * H) - 7), cv2.FONT_HERSHEY_SIMPLEX, scale * 0.85,
                    (230, 240, 255), 2, cv2.LINE_AA)

    gold, level, xp, need = 0, 3, 0, 6
    base = np.random.default_rng(0).integers(10, 45, (H, W, 3)).astype(np.uint8)
    actions, round_end = [], []
    for r in ROUNDS:
        gold += 5 + min(5, gold // 10)
        xp += 2
        if xp >= need:
            level += 1
            xp -= need
            need += 4
        shop = rng.sample(NAMES, 5)
        for f in range(ROUND_SEC * fps):
            sec = f / fps
            if f % fps == 0:
                a = ACTS.get((r, int(sec)))
                if a == "xp" and gold >= 4:
                    gold -= 4
                    xp += 4
                    if xp >= need:
                        level += 1
                        xp -= need
                        need += 4
                    actions.append({"round": r, "type": "buy_xp", "t": ROUNDS.index(r) * ROUND_SEC + sec})
                elif a == "roll":
                    gold -= 2
                    shop = rng.sample(NAMES, 5)
                    actions.append({"round": r, "type": "reroll", "t": ROUNDS.index(r) * ROUND_SEC + sec})
                elif a and a.startswith("buy"):
                    i = int(a[3]) - 1
                    actions.append({"round": r, "type": "buy", "name": shop[i],
                                    "t": ROUNDS.index(r) * ROUND_SEC + sec})
                    shop[i] = ""
                    gold -= 3
            img = base.copy()
            cv2.rectangle(img, (480, 925), (1480, 1078), (40, 30, 25), -1)
            put(img, "round", r)
            put(img, "gold", str(gold))
            put(img, "level", f"Lv. {level}")
            put(img, "xp", f"{xp}/{need}", 0.8)
            for i, n in enumerate(shop):
                if n:
                    put(img, f"shop{i + 1}", n, 0.85)
            proc.stdin.write(img.tobytes())
        round_end.append({"round": r, "gold_end": gold, "xp": f"{xp}/{need}", "level": level})
    proc.stdin.close()
    proc.wait()
    if proc.returncode:
        raise RuntimeError("ffmpeg lỗi khi tạo video giả")
    truth = {"actions": actions, "round_end": round_end, "final_gold": gold, "final_level": level, "rounds": ROUNDS,
             "duration": len(ROUNDS) * ROUND_SEC}
    with open(os.path.splitext(out)[0] + ".truth.json", "w", encoding="utf-8") as f:
        json.dump(truth, f, ensure_ascii=False, indent=1)
    return truth


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--crf", type=int, default=23)
    ap.add_argument("--fps", type=int, default=10)
    a = ap.parse_args()
    t = make(a.out, a.height, a.crf, a.fps)
    print(json.dumps(t, ensure_ascii=False))
