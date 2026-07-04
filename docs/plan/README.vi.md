# Giải Thích Nhanh Bộ File `.md` Trong `docs/plan`

File này tóm tắt mục đích của từng tài liệu để đọc nhanh hoặc bàn giao cho người khác.

## Cách dùng

- Đọc [00-index.md](D:/Duancanhan/AC/docs/plan/00-index.md) trước để có thứ tự tổng quát.
- Nếu đang thiết kế hệ thống, ưu tiên các file `01` đến `05`.
- Nếu đang triển khai detector hoặc ML, ưu tiên các file `06` đến `10`.
- Nếu đang chuẩn bị rollout hoặc rà soát legal, đọc `11` và `12`.

## Ý nghĩa từng file

### `00-index.md`

Chỉ mục của cả bộ tài liệu, dùng để định hướng thứ tự đọc và nguyên tắc sử dụng.

### `01-vision-and-goals.md`

Giải thích dự án muốn đạt điều gì, giới hạn của dự án là gì, và tiêu chí nào được xem là thành công.

### `02-design-principles.md`

Đặt ra nguyên tắc kiến trúc cốt lõi: whitebox nắm sự thật, blackbox nắm nghi vấn, fusion nắm quyết định leo thang.

### `03-cheat-taxonomy.md`

Liệt kê các nhóm cheat cần xử lý theo hành vi để tránh thiết kế detector mơ hồ hoặc thiếu phạm vi.

### `04-grim-capability-map.md`

Chỉ ra Grim mạnh ở đâu, yếu ở đâu, và nên giữ vai trò gì trong kiến trúc AC.

### `05-hybrid-architecture.md`

Mô tả flow tổng thể giữa whitebox, feature extraction, blackbox và fusion.

### `06-detection-matrix.md`

Là bảng quyết định nhanh: cheat nào ưu tiên whitebox, cheat nào cần hybrid, cheat nào chưa nên enforce sớm.

### `07-feature-spec.md`

Là danh sách feature cần thu thập để phục vụ phân tích hành vi, ML và fusion policy.

### `08-ml-system.md`

Nói rõ ML nên đứng ở đâu trong hệ thống, không nên làm gì, và lộ trình triển khai thực tế.

### `09-fusion-policy.md`

Mô tả quy tắc hợp nhất tín hiệu để tránh việc một model đơn lẻ tự quyết định punish.

### `10-runtime-and-performance.md`

Tập trung vào runtime cost, queue, fallback, observability và safe mode.

### `11-rollout-and-testing.md`

Định nghĩa cách rollout theo pha và cách kiểm thử để giảm false positive.

### `12-legal-and-sourcing.md`

Ghi rõ ranh giới học ý tưởng từ upstream và việc không sao chép code từ nguồn có license không rõ.

## Gợi ý cho người đọc mới

- Nếu cần hiểu bức tranh lớn trong 10 phút: đọc `00`, `01`, `04`, `05`.
- Nếu cần bắt tay viết detector: đọc `03`, `06`, `07`, `09`.
- Nếu cần triển khai ML hoặc service ngoài: đọc `05`, `08`, `10`.
- Nếu cần review rủi ro release: đọc `11`, `12`.
