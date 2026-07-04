# Tầm Nhìn Và Mục Tiêu

## Mục tiêu sản phẩm

Xây dựng một anticheat cho Minecraft theo hướng:

- bắt chắc các cheat có quy luật vật lý, packet và world-state
- phát hiện tốt hơn các cheat combat kiểu "humanized"
- false positive thấp hơn các anticheat heuristic thuần threshold
- vẫn giữ TPS ổn định trên server production
- có khả năng mở rộng thành hệ thống phân tích hybrid trong tương lai

## Mục tiêu kỹ thuật

- `Grim` là whitebox core cho movement, reach, packet và interaction validity
- hybrid layer đánh giá combat behavior, click behavior và profile-level suspicion
- ML nếu có phải chạy async, timeout rõ ràng, có fallback
- mọi quyết định auto-ban phải có ngưỡng tin cậy cao và có corroboration

Flow tổng quát mong muốn:

```text
user behavior
-> packet/state/context
-> whitebox validation
-> feature extraction
-> blackbox scoring
-> fusion
-> action
```

## Mục tiêu vận hành

- staff có alert dễ đọc
- có log debug cho từng flag
- có replay-friendly traces cho các ca nghi ngờ
- có safe mode để tắt ML mà không làm hỏng core anticheat

## Phi mục tiêu

- không cố làm "AI bắt tất cả"
- không để ML override whitebox movement truth
- không phụ thuộc bắt buộc vào cloud service bên ngoài
- không sao chép code từ các nguồn có license mơ hồ hoặc bất lợi cho dự án

## Tiêu chí thành công

- movement và packet core ổn định trên production
- combat suspicious cases được xếp hạng theo risk thay vì flag rời rạc theo từng check
- rollout theo từng giai đoạn mà không làm tăng đột biến false positive
- bộ tài liệu đủ chi tiết để team có thể chia việc
