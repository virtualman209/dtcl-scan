# SPEC — dtcl-scan, đợt nâng cấp "rà lỗi toàn bộ + tăng độ chính xác OCR"

## 1. Mục tiêu
DTCLScan bóc tách dữ liệu trận Đấu Trường Chân Lý (TFT, Set 18 "Enchanted Wilds", client mới chạy Unreal, giao diện **tiếng Việt**) từ video quay màn hình: theo từng vòng ra vàng, cấp, XP, cửa hàng (tên 5 tướng), sự kiện mua XP / roll / mua tướng, tộc/hệ đang kích hoạt, máu của mình + máu người khác. Xuất `report.html`, `rounds.csv`, `events.csv`, `samples.csv`, `match.json`, ảnh chốt mỗi vòng, gói `gui_claude/` (ảnh + câu hỏi để dán vào Claude chat).

Người dùng: người chơi TFT ở Việt Nam, không phải lập trình viên, dùng Windows.

Đợt này: (a) rà và sửa lỗi toàn bộ tool, (b) tăng độ chính xác OCR trên HUD thật.

## 2. Nền tảng & cách chạy (giữ nguyên, không phá)
- Windows, Python 3 + tkinter (`dtclscan.pyw`), ffmpeg/ffprobe, Tesseract OCR (dữ liệu `eng` + `vie` trong `tessdata/`).
- Cài bằng `setup.ps1` (1 lệnh PowerShell) hoặc `install.bat`; menu chuột phải qua `install.py --reg` + `register.bat`; lối tắt `shortcut.ps1`; tự cập nhật qua `updater.py` / `update.ps1` từ repo `virtualman209/dtcl-scan` nhánh `main` (so `version.txt`).
- Khuôn mẫu theo repo `virtualman209/MergeCutVid` (đã làm theo).
- Mã nguồn hiện tại: thư mục này (git, nhánh `nang-cap`, xuất phát từ bản 1.3.0).

## 3. Chức năng bắt buộc
- Mọi chức năng đang có phải còn chạy: phân tích video (GUI + `python analyze.py`), cửa sổ Căn chỉnh vùng (khoanh vùng, Thử đọc, Lưu, Lưu thành profile mới, Khôi phục mặc định), Cài đặt, gói gửi Claude chat, tuỳ chọn Claude API (không bắt buộc), tự cập nhật, menu chuột phải.
- OCR phải đạt các ngưỡng ở mục 6 trên ảnh HUD thật.
- Lỗi phải hiện thông báo tiếng Việt dễ hiểu, không văng traceback thô cho người dùng.

Ngoài phạm vi: nhận diện tướng trên bàn cờ không dùng AI; hỗ trợ HUD tỉ lệ khác 16:9 (chỉ cần căn chỉnh tay được); hỗ trợ macOS.

## 4. Ràng buộc
- Không dùng API trả phí cho chức năng chính (người dùng KHÔNG có Claude API).
- Không thêm phụ thuộc nặng mới (vd. PyTorch, EasyOCR, PaddleOCR) — chỉ numpy, opencv-python-headless, Tesseract, ffmpeg như hiện tại. Có thể ship thêm file dữ liệu nhỏ (vd. mẫu chữ số `digits.npz`, < 2 MB).
- Giao diện, thông báo, README: tiếng Việt.
- Giữ tương thích profile cũ (`profiles/*.json`) và `settings.json` của người dùng.
- File `.bat` CRLF; file `.ps1` có tiếng Việt phải UTF-8 BOM (trừ `setup.ps1` chạy qua `irm | iex`) + CRLF.
- Không push lên GitHub (người điều phối sẽ làm khi người dùng đồng ý). Commit vào nhánh `nang-cap` mỗi vòng.

## 5. Dữ liệu mẫu
- `tests/fixtures/real/hud_2-7.png`, `hud_3-5_a.png`, `hud_3-5_b.png`: khung hình HUD **thật** của người dùng (1920x1080, cắt từ ảnh chụp cửa sổ Căn chỉnh vùng — có vẽ đè khung vàng/đỏ và nhãn của tool). Đáp án: `tests/fixtures/real/truth.json`.
- `tests/fixtures/raw/`: ảnh chụp gốc người dùng gửi (gồm cả ảnh cho thấy OCR cũ đọc sai).
- `tests/make_fake.py`: sinh video HUD giả lập có đáp án (10 hành động: 4 mua XP, 3 roll, 3 mua tướng) — đường dẫn trong file đang cứng, cần sửa cho chạy được ở bất kỳ đâu.
- Hạn chế: chưa có video thật cả trận; video thật của người dùng bị nén (tên file `…_compressed.mp4`).

## 6. Tiêu chí nghiệm thu (TC)
- **TC1 – Test tự động**: `python -m pytest -q tests` chạy xanh trong môi trường Linux có tesseract (eng+vie), ffmpeg, Xvfb.
- **TC2 – Số trên HUD thật**: trên 3 ảnh thật, `round`, `gold`, `level`, `xp` đọc đúng 12/12 (dùng toạ độ mặc định trong `layout.py`).
- **TC3 – Cửa hàng trên HUD thật**: 15 ô (3 ảnh × 5) đúng ≥ 14/15 sau chuẩn hoá `ocr.norm()`; ô trống phải ra rỗng.
- **TC4 – Máu**: máu của mình (87) đúng 3/3; máu người khác trên `hud_3-5_a` + `hud_3-5_b` đúng ≥ 13/14; `hud_2-7` (bảng đang hiện thống kê sát thương) không được trả về số máu người khác sai (rỗng hoặc trạng thái khác "ok" là chấp nhận).
- **TC5 – Tộc/hệ**: trên 3 ảnh thật (25 dòng), tên khớp (độ giống `difflib` ≥ 0.8 sau `norm()`) ≥ 21/25 và số đếm đúng ≥ 20/25; không sinh dòng rác (tên không có trong đáp án) quá 2 dòng / ảnh.
- **TC6 – Đầu cuối video giả lập**: video giả 1080p và bản 720p nén mạnh: bắt đúng 10/10 hành động (loại + vòng + tên tướng mua), không có sự kiện mua/roll/mua XP thừa; tạo đủ các file đầu ra; báo cáo HTML mở được.
- **TC7 – Đầu cuối từ khung thật**: video dựng từ `hud_3-5_a` (30s) + `hud_3-5_b` (30s), nén lại bằng libx264 crf 20: vòng 3-5, vàng 43, cấp 7, máu mình 87 đúng; máu người khác đúng ≥ 5/7.
- **TC8 – Đường dẫn & lỗi**: video đặt trong thư mục có dấu tiếng Việt và khoảng trắng chạy được; file video hỏng / không phải video / video 0 giây → thông báo tiếng Việt rõ ràng, không traceback; chạy 2 lần liền trên cùng video không lỗi (ghi đè kết quả cũ gọn gàng); huỷ giữa chừng dừng được.
- **TC9 – Giao diện**: dưới Xvfb 1366x768: màn hình chính, Căn chỉnh vùng, Cài đặt mở được, không bị cắt chữ/nút; nút "Thử đọc tất cả vùng" trên `hud_3-5_a` hiển thị đúng vòng/vàng/cấp/XP/cửa hàng.
- **TC10 – Cài đặt & cập nhật**: `install.py --config/--reg/--unreg/--check` chạy được và .reg hợp lệ (UTF-16, có đủ 3 mục menu); mọi `.bat` CRLF, `.ps1` đúng mã hoá; `setup.ps1`/`update.ps1`/`updater.py` trỏ đúng `virtualman209/dtcl-scan`; `updater.py` giữ `profiles/`, `settings.json`, `tessdata/`, `champions.txt`, `bin/` khi cập nhật; `version.txt` tăng lên 1.4.0 kèm ghi chú.
- **TC11 – Hiệu năng**: video giả lập 3:20 ở 2 khung/giây xử lý xong < 90 giây trên máy kiểm thử (ghi lại số giây).

## 7. Giả định
- Toạ độ mặc định chỉ cần đúng cho HUD 16:9 như ảnh người dùng; tỉ lệ khác người dùng tự căn.
- Ngưỡng TC có tính tới việc ảnh thật có khung vẽ đè của tool.
