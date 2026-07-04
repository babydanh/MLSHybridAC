# Dự Án AntiCheat — Overview

## Mục tiêu

Xây dựng anticheat Minecraft server theo hướng:

- nhẹ, ổn định, không làm tụt TPS
- chính xác ở các domain vật lý, packet, reach và interaction
- ít false positive hơn các anticheat heuristic thuần threshold
- có khả năng mở rộng sang hybrid detection mà không phá core

## Ý tưởng cốt lõi

AC không hoạt động theo kiểu:

- ML quyết định toàn bộ anticheat
- từng detector tự flag rồi tự punish
- gom tất cả logic vào một lớp check hỗn hợp

AC hoạt động theo kiểu:

- `Grim` xác nhận điều gì là sai chắc chắn
- `MLS-style analysis` đánh giá điều gì là đáng nghi
- `Fusion` là nơi duy nhất được phép quyết định hành động

## Ba lớp chính

### 1. Whitebox core: `Grim`

`Grim` là source of truth cho:

- movement truth
- packet truth
- reach truth
- world interaction truth

Những nhóm như `Fly`, `Speed`, `NoFall`, `Timer`, `BadPackets`, `Reach`, `FastBreak` ưu tiên do Grim xử lý.

Output của Grim không chỉ là `flag`, mà là các fact có cấu trúc:

- deterministic flags
- prediction deviations
- geometry facts
- packet anomalies
- world-state context

### 2. Behavioral analysis: `MLS-style`

Lớp này dùng để xử lý các bài toán mà deterministic engine không đủ mạnh:

- AimAssist
- AutoClicker
- KillAura humanized
- Ghost client profile
- suspicious combat behavior

Nó không được thay thế Grim.

Output đúng của lớp này là:

- risk
- confidence
- category
- explanation tags
- model metadata

### 3. Decision layer: `Fusion`

Fusion hợp nhất:

- certainty từ Grim
- suspicion từ analysis layer
- ping, jitter, TPS
- exemptions
- session history

Fusion mới là nơi quyết định:

- `observe`
- `alert`
- `assist`
- `soft_mitigate`
- `enforce_candidate`

## Flow tổng thể

```text
Player behavior
-> client packets / actions
-> Grim whitebox validation
-> AC feature extraction
-> MLS-style async analysis
-> Fusion policy
-> alert / mitigation / punishment
```

## Flow runtime chi tiết

```text
1. Player gửi packet hoặc thực hiện hành động
2. Grim cập nhật packet/state/world context
3. Grim chạy deterministic validation
4. AC nhận whitebox facts từ Grim
5. Feature layer trích packet, movement, combat, rotation, click, session signals
6. Nếu cần behavioral analysis thì enqueue job async
7. Analysis layer trả risk/confidence/category
8. Fusion hợp nhất whitebox + blackbox + runtime conditions + history
9. Action layer chọn alert / mitigate / enforce
10. Audit layer ghi đầy đủ lý do và context
```

## Nguyên tắc quyết định

- deterministic truth thắng
- probabilistic suspicion cần corroboration
- ML không được override movement truth
- runtime xấu phải giảm trọng số blackbox
- TPS xấu thì tắt analysis layer trước khi đụng vào core

## Vai trò của feature layer

Feature layer là cầu nối giữa Grim và MLS-style analysis. Nó thu thập các nhóm tín hiệu như:

- packet timing và transaction RTT
- movement offset và prediction residual
- combat geometry
- yaw, pitch, acceleration, jerk
- click intervals, entropy, burst score
- inventory và interaction timing
- session-level profile

Feature layer không tự punish. Nó chỉ biến runtime data thành structured signals.

## Khi nào domain nào dùng lớp nào

### Whitebox-driven

- Fly
- Speed
- NoFall
- Phase
- Timer
- BadPackets
- InventoryMove
- AirPlace

### Hybrid

- KillAura
- Velocity abuse
- Scaffold
- CrystalAura
- AutoTotem
- Freecam

### Blackbox-first, cần corroboration

- AimAssist
- AutoClicker
- Ghost client profile
- legit aura
- session anomaly

## Mục tiêu sản phẩm thực tế

AC không nhắm tới việc có nhiều check nhất. AC nhắm tới:

- movement và packet core ổn định trên production
- combat suspicious cases được xếp risk thay vì flag rời rạc
- rollout tăng dần mà không gây false positive đột biến
- dễ debug, dễ replay, dễ vận hành

## Hướng mở rộng

Sau khi core ổn định, AC có thể thêm:

- remote analysis service
- staff suspects UI
- webhook và dashboard
- ban animation
- cross-server observability

Nhưng các phần này luôn là lớp ngoài. Chúng không được thay thế core deterministic của Grim.
