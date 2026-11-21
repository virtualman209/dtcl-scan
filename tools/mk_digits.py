"""Sinh mẫu chữ số 0-9 từ vài font sans đậm → digits.npz (ship kèm tool)."""
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont
FONTS=["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
       "/usr/share/fonts/truetype/google-fonts/ofl/firasans/FiraSans-SemiBold.ttf","/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
       "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreheros-bold.otf","/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf"]
N=32
def norm_glyph(m):
    ys,xs=np.where(m>0)
    if len(xs)==0: return None
    m=m[ys.min():ys.max()+1, xs.min():xs.max()+1]
    h,w=m.shape; s=N/h; nw=max(1,min(N,int(round(w*s))))
    r=cv2.resize(m,(nw,N),interpolation=cv2.INTER_AREA)
    c=np.zeros((N,N),np.float32); x0=(N-nw)//2; c[:,x0:x0+nw]=r
    return cv2.GaussianBlur(c,(3,3),0)
if __name__=="__main__":
    T=[];L=[]
    for f in FONTS:
        try: font=ImageFont.truetype(f,64)
        except Exception as e: print("skip",f); continue
        for d in "0123456789":
            im=Image.new("L",(80,90),0); ImageDraw.Draw(im).text((10,5),d,font=font,fill=255)
            a=np.array(im)
            for blur in (0,1):           # bản mờ giống video nén
                b=a if not blur else cv2.resize(cv2.resize(a,(10,11),interpolation=cv2.INTER_AREA),(80,90),interpolation=cv2.INTER_CUBIC)
                _,b=cv2.threshold(b,110,255,cv2.THRESH_BINARY)
                g=norm_glyph(b)
                if g is not None: T.append(g); L.append(int(d))
    np.savez_compressed("/home/claude/DTCLScan/digits.npz",t=np.array(T,np.float32),l=np.array(L))
    print(len(T),"templates")
