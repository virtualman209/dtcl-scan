"""Video HUD giả "khó" có đáp án (kịch bản do kỹ sư kiểm thử vòng 3 đề xuất, đưa vào bộ test).

    python3 tests/make_hard.py OUT.mp4 [--height 1080] [--crf 23] [--lag 0.4] [--scenario hard|sync]

Mỗi vòng 20s; đầu vòng: nhận vàng + cửa hàng tự làm mới (như TFT thật).
Thao tác ngay sau khi nhận vàng (≤6s): roll, mua XP, bán tướng (+vàng, cửa hàng không đổi) rồi mua lại,
vàng augment/Wisp rồi tiêu. `lag`: cửa hàng hiện tên mới trễ `lag` giây so với số vàng (hoạt ảnh lật thẻ
của client thật) — chỉ áp cho thao tác đánh dấu "L".
"""
import argparse, json, os, random, shutil, subprocess, sys
import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import layout  # noqa: E402

NAMES = ["Ahri", "Garen", "Lillia", "Veigar", "Rakan", "Xayah", "Ornn", "Malphite", "Azir", "Warwick",
         "Kayle", "Rammus", "Teemo", "Yorick", "Sett", "Zyra", "Taric", "Maokai"]
ROUNDS = ["1-1", "1-2", "1-3", "2-1", "2-2", "2-3", "3-1", "3-2", "3-3", "4-1"]
# (vòng, giây) -> (hành động, trễ cửa hàng?)   giây có thể lẻ .5
SCEN = {
    "hard": {
        ("2-1", 2.0): ("roll", False),          # đối chứng: roll đồng bộ ngay sau nhận vàng
        ("2-2", 3.0): ("roll", True),           # roll sau nhận vàng 3s, cửa hàng trễ
        ("2-3", 4.0): ("sell3", False),         # bán tướng +3, cửa hàng không đổi
        ("2-3", 6.0): ("buy2", True),           # mua lại sau 2s, cửa hàng trễ
        ("3-1", 5.0): ("gain10", False),        # vàng augment/Wisp
        ("3-1", 7.0): ("xp", False),            # tiêu ngay vào XP
        ("3-2", 2.0): ("xp", False),            # nhiều thao tác trong 1 giây
        ("3-2", 2.5): ("roll", False),
        ("3-3", 3.0): ("sell3", False),
        ("3-3", 5.0): ("roll", False),          # bán rồi roll (đồng bộ)
        ("4-1", 2.0): ("roll", True),
        ("4-1", 4.0): ("roll", True),
        ("4-1", 9.0): ("buy1", True),
    },
}


def make(out, height=1080, crf=23, fps=10, lag=0.4, scen="hard", seed=3):
    W, H = 1920, 1080
    B = layout.DEFAULT["boxes"]
    rng = random.Random(seed)
    acts = SCEN[scen]
    ow = int(round(W * height / H / 2)) * 2
    proc = subprocess.Popen([shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt",
                             "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-vf", f"scale={ow}:{height}",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", out],
                            stdin=subprocess.PIPE)

    def put(img, key, text, scale=0.9):
        x1, y1, x2, y2 = B[key]
        cv2.putText(img, text, (int(x1 * W) + 4, int(y2 * H) - 7), cv2.FONT_HERSHEY_SIMPLEX, scale * 0.85,
                    (230, 240, 255), 2, cv2.LINE_AA)

    gold, level, xp, need = 0, 3, 0, 6
    base = np.random.default_rng(0).integers(10, 45, (H, W, 3)).astype(np.uint8)
    actions, round_end = [], []
    shown_shop, pending = None, None
    for ri, r in enumerate(ROUNDS):
        gold += 5 + min(5, gold // 10) + (6 if r in ("2-1", "2-2", "4-1") else 0)   # thêm vàng để đủ roll
        xp += 2
        if xp >= need:
            level += 1; xp -= need; need += 4
        shop = rng.sample(NAMES, 5)
        shown_shop = list(shop)
        for f in range(20 * fps):
            sec = f / fps
            T = ri * 20 + sec
            a = acts.get((r, round(sec, 1)))
            if a:
                kind, lagged = a
                if kind == "xp":
                    gold -= 4; xp += 4
                    if xp >= need:
                        level += 1; xp -= need; need += 4
                    actions.append({"round": r, "type": "buy_xp", "t": T})
                elif kind == "roll":
                    gold -= 2
                    shop = rng.sample(NAMES, 5)
                    actions.append({"round": r, "type": "reroll", "t": T, "lag": lagged})
                elif kind.startswith("buy"):
                    i = int(kind[3]) - 1
                    actions.append({"round": r, "type": "buy", "name": shop[i], "t": T, "lag": lagged})
                    shop = list(shop); shop[i] = ""
                    gold -= 3
                elif kind.startswith("sell"):
                    gold += int(kind[4:]); actions.append({"round": r, "type": "sell", "t": T})
                elif kind.startswith("gain"):
                    gold += int(kind[4:]); actions.append({"round": r, "type": "gain", "t": T})
                if kind in ("roll",) or kind.startswith("buy"):
                    if lagged:
                        pending = (T + lag, list(shop))
                    else:
                        shown_shop, pending = list(shop), None
            if pending and T >= pending[0] - 1e-6:
                shown_shop, pending = pending[1], None
            img = base.copy()
            cv2.rectangle(img, (480, 925), (1480, 1078), (40, 30, 25), -1)
            put(img, "round", r)
            put(img, "gold", str(gold))
            put(img, "level", f"Lv. {level}")
            put(img, "xp", f"{xp}/{need}", 0.8)
            for i, nm in enumerate(shown_shop):
                if nm:
                    put(img, f"shop{i + 1}", nm, 0.85)
            proc.stdin.write(img.tobytes())
        round_end.append({"round": r, "gold_end": gold, "xp": f"{xp}/{need}", "level": level})
    proc.stdin.close(); proc.wait()
    truth = {"actions": actions, "round_end": round_end, "final_gold": gold, "final_level": level,
             "rounds": ROUNDS, "duration": 200, "lag": lag}
    with open(os.path.splitext(out)[0] + ".truth.json", "w", encoding="utf-8") as fh:
        json.dump(truth, fh, ensure_ascii=False, indent=1)
    return truth


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--crf", type=int, default=23); ap.add_argument("--lag", type=float, default=0.4)
    ap.add_argument("--scenario", default="hard")
    a = ap.parse_args()
    t = make(a.out, a.height, a.crf, lag=a.lag, scen=a.scenario)
    print(len(t["actions"]), "hành động")
