"""Biến thể ảnh HUD thật để thử độ bền OCR: thu 720p, nén JPEG, dịch lệch vài px."""
import cv2
import numpy as np

VARIANTS = ["orig", "720", "900", "jpeg60", "720jpeg60", "shift2_0", "shift-2_0", "shift3_3", "shift-3_0",
            "shift0_2", "shift-2_-2"]


def to1920(img):
    h, w = img.shape[:2]
    if w == 1920:
        return img
    return cv2.resize(img, (1920, int(round(h * 1920 / w))), interpolation=cv2.INTER_CUBIC)


def src_height(v):
    """Chiều cao video gốc tương ứng biến thể (để OCR biết video thấp)."""
    return 720 if v.startswith("720") else 900 if v == "900" else 1080


def variant(img, v):
    if v == "orig":
        return img
    if v == "720":       # giống core.iter_frames: video 720p được phóng về rộng 1920
        return to1920(cv2.resize(img, (1280, 720), interpolation=cv2.INTER_AREA))
    if v == "900":       # laptop 1600x900
        return to1920(cv2.resize(img, (1600, 900), interpolation=cv2.INTER_AREA))
    if v == "jpeg60":
        ok, b = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
        return cv2.imdecode(b, cv2.IMREAD_COLOR)
    if v == "720jpeg60":
        return variant(variant(img, "720"), "jpeg60")
    if v.startswith("shift"):
        dx, dy = map(int, v[5:].split("_"))
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)
    raise ValueError(v)
