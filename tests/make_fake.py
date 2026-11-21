"""Tạo video HUD giả lập để kiểm thử pipeline."""
import sys, random, subprocess
import numpy as np, cv2
sys.path.insert(0, "/home/claude/DTCLScan")
import layout
B = layout.DEFAULT["boxes"]
W, H, FPS = 1920, 1080, 10
NAMES = ["Ahri", "Garen", "Lillia", "Veigar", "Rakan", "Xayah", "Ornn", "Malphite", "Azir", "Warwick",
         "Kayle", "Rammus", "Teemo", "Yorick", "Sett", "Zyra", "Taric", "Maokai"]
rng = random.Random(1)
def put(img, key, text, scale=0.9):
    x1, y1, x2, y2 = B[key]
    cv2.putText(img, text, (int(x1*W)+4, int(y2*H)-7), cv2.FONT_HERSHEY_SIMPLEX, scale*0.85, (230,240,255), 2, cv2.LINE_AA)
rounds = ["1-1","1-2","1-3","2-1","2-2","2-3","3-1","3-2","3-3","4-1"]
# script of actions: (round, second_in_round, action)
acts = {("2-1",8):"xp", ("2-1",12):"roll", ("2-1",15):"buy2", ("3-2",6):"xp",("3-2",9):"roll",("3-2",11):"roll",
        ("3-2",14):"buy1",("3-2",16):"buy4",("4-1",5):"xp",("4-1",7):"xp"}
proc = subprocess.Popen(["ffmpeg","-y","-loglevel","error","-f","rawvideo","-pix_fmt","bgr24","-s",f"{W}x{H}","-r",str(FPS),
                         "-i","-","-c:v","libx264","-preset","veryfast","-crf","23","-pix_fmt","yuv420p","/home/claude/test/fake.mp4"],stdin=subprocess.PIPE)
gold, level, xp, need = 0, 3, 0, 6
shop = rng.sample(NAMES, 5)
base = (np.random.default_rng(0).integers(10, 45, (H, W, 3))).astype(np.uint8)
truth=[]
for r in rounds:
    gold += 5 + min(5, gold//10); xp += 2
    if xp >= need: level += 1; xp -= need; need += 4
    shop = rng.sample(NAMES, 5)
    for f in range(20*FPS):
        sec = f/FPS
        if f % FPS == 0:
            a = acts.get((r, int(sec)))
            if a == "xp" and gold >= 4:
                gold -= 4; xp += 4
                if xp >= need: level += 1; xp -= need; need += 4
                truth.append((r,"xp"))
            elif a == "roll": gold -= 2; shop = rng.sample(NAMES, 5); truth.append((r,"roll"))
            elif a and a.startswith("buy"):
                i = int(a[3])-1; truth.append((r,"buy "+shop[i])); shop[i] = ""; gold -= 3
        img = base.copy()
        cv2.rectangle(img, (480, 925), (1480, 1078), (40, 30, 25), -1)
        put(img,"round",r); put(img,"gold",str(gold)); put(img,"level",f"Lv. {level}"); put(img,"xp",f"{xp}/{need}",0.8)
        for i,n in enumerate(shop):
            if n: put(img,f"shop{i+1}",n,0.85)
        y=int(B["traits"][1]*H)+40
        for t in ["3 Blossom","2 Elderwood","1 Riftbeast"]:
            cv2.putText(img,t,(20,y),cv2.FONT_HERSHEY_SIMPLEX,0.8,(220,220,220),2); y+=45
        y=int(B["players"][1]*H)+40
        for p,hp in [("Ta",100-len(truth)*2),("Bot1",88),("Bot2",73)]:
            cv2.putText(img,f"{p} {hp}",(1680,y),cv2.FONT_HERSHEY_SIMPLEX,0.8,(220,220,220),2); y+=60
        proc.stdin.write(img.tobytes())
proc.stdin.close(); proc.wait()
print("truth:", truth); print("final gold", gold, "level", level)
