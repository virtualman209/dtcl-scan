# DTCLScan

Bóc tách dữ liệu trận **Đấu Trường Chân Lý (TFT)** từ video quay màn hình, ra file dữ liệu theo từng vòng:
vòng mấy, bao nhiêu vàng, lên cấp lúc nào, mua XP mấy lần, roll mấy lần, mua tướng nào, đội hình ra sao.

- **Kéo thả video** vào cửa sổ, hoặc chuột phải file video → *DTCLScan ▸ Phân tích trận ĐTCL*.
- **Căn chỉnh vùng HUD**: khoanh chỗ hiện số vòng, vàng, cấp, XP, 5 ô cửa hàng… ngay trên video của bạn, bấm *Thử đọc* để xem OCR đọc đúng chưa.
- **Kết quả** nằm trong thư mục `<tên video>_dtcl\` cạnh video:

| File | Nội dung |
|---|---|
| `report.html` | Báo cáo dễ đọc: tổng kết, biểu đồ vàng, bảng từng vòng kèm ảnh chốt |
| `rounds.csv` | Mỗi vòng 1 dòng: cấp, XP, máu, vàng đầu→cuối, tiêu, số lần roll, mua XP, tướng đã mua |
| `events.csv` | Từng sự kiện có mốc thời gian: vòng mới, lên cấp, mua XP, roll, mua tướng, nhận vàng |
| `samples.csv` | Giá trị đọc được ở từng mốc (mặc định 2 lần/giây) — dữ liệu thô |
| `match.json` | Toàn bộ dữ liệu, để đưa cho AI hoặc script khác |
| `keyframes\` | Ảnh chốt giai đoạn chuẩn bị của mỗi vòng |

- **Tuỳ chọn AI** (cần Claude API key của bạn, có tính phí): Claude đọc ảnh chốt để nhận diện bàn cờ, sao, trang bị; và viết nhận xét cả trận bằng tiếng Việt.
- **Tự cập nhật** từ GitHub (hỏi trước khi cập nhật).

## Cài đặt

Mở **PowerShell** và chạy:

```powershell
irm https://raw.githubusercontent.com/virtualman209/dtcl-scan/main/setup.ps1 | iex
```

Tool được cài vào `%LOCALAPPDATA%\DTCLScan`, tạo lối tắt Start Menu + Desktop và menu chuột phải cho file video.
Nếu máy chưa có Python 3, ffmpeg hoặc Tesseract OCR, script sẽ tự cài qua `winget` (Tesseract có thể hiện hộp thoại xin quyền).

Không dùng PowerShell? Tải zip, giải nén vào chỗ cố định (vd. `C:\Tools\DTCLScan`) rồi chạy `install.bat`.

> Windows 11: chuột phải file → *Show more options* (hoặc Shift + chuột phải) mới thấy menu DTCLScan.

Gỡ cài đặt: chạy `uninstall.bat` trong thư mục cài đặt.

## Dùng lần đầu

1. Mở DTCLScan, kéo video vào, bấm **Căn chỉnh vùng…**
2. Kéo thanh thời gian tới lúc đang **chuẩn bị** (thấy cửa hàng và số vàng).
3. Chọn từng mục bên trái → kéo chuột khoanh đúng chỗ trên ảnh. Phím mũi tên dịch 1px, Shift + mũi tên đổi cỡ.
   - Khoanh **sát chữ số**, không lẫn icon đồng vàng.
   - Với cửa hàng: khoanh dòng **tên tướng** ở đáy mỗi thẻ.
4. Bấm **Thử đọc tất cả vùng** — mục nào có ✓ và giá trị đúng là ổn. Bấm **Lưu**.
5. Quay lại màn hình chính, bấm **Phân tích**.

Mỗi độ phân giải / tỉ lệ màn hình nên có 1 profile riêng (*Lưu thành profile mới…*). Toạ độ mặc định chỉ là ước lượng cho 16:9.

Mẹo quay video: 1080p (hoặc 720p trở lên), chỉ quay màn hình game, không che HUD bằng camera/overlay.
Client tiếng Việt: vào **Cài đặt…** đặt Ngôn ngữ OCR là `eng+vie`. Điền **Tên trong game** để tool tìm đúng dòng máu của bạn.
Có thể điền tên tướng của mùa hiện tại vào `champions.txt` để OCR tự sửa tên đọc sai.

## Hạn chế

- Tool chỉ thấy những gì hiện trên màn hình của bạn. Bàn của đối thủ chỉ có khi bạn bấm sang xem.
- Mua / roll quá nhanh trong chưa đầy 0,5 giây có thể bị gộp. Tăng *Số khung/giây đọc* lên 3–4 nếu cần.
- Không có AI thì tool **không nhận diện được tướng trên bàn cờ** (chỉ đọc chữ). Bật *AI đọc bàn cờ* nếu cần đội hình chi tiết.
- Giá từng tướng được suy từ lượng vàng giảm, nên có thể lệch khi mua nhiều thứ cùng lúc.

## Dòng lệnh

```
python analyze.py video.mp4 --profile default_1080p --fps 2 --from 0 --to 0
```

## Phát hành bản mới

Sửa code → tăng số phiên bản ở dòng đầu `version.txt` (các dòng sau là ghi chú thay đổi) → push lên `main`.

Lỗi được ghi vào `%TEMP%\dtclscan.log`.
