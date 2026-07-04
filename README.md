# AC

AC là một anticheat Minecraft theo kiến trúc hybrid:

- `Grim` làm `whitebox core`
- `MLS-style analysis` làm `behavior analysis` ngoài luồng
- `Fusion` là nơi quyết định hành động cuối cùng

## Tư tưởng cốt lõi

AC không để ML quyết định toàn bộ anticheat.

AC vận hành theo nguyên tắc:

- `Grim` xác nhận điều gì là impossible
- `Analysis layer` đánh giá điều gì là suspicious
- `Fusion` hợp nhất certainty và risk để chọn action an toàn

## High-level flow

```text
Player behavior
-> client packets / actions
-> Grim whitebox validation
-> AC feature extraction
-> MLS-style async analysis
-> Fusion policy
-> alert / mitigation / punishment
```

## Vai trò từng lớp

### Grim whitebox core

Grim là source of truth cho:

- movement truth
- packet truth
- reach truth
- world interaction truth

Nó phù hợp nhất cho các domain như:

- Fly
- Speed
- NoFall
- Timer
- BadPackets
- Reach

### Feature extraction

Layer này gom dữ liệu từ runtime để phục vụ phân tích hành vi:

- packet timing
- transaction RTT / jitter
- prediction residual
- combat geometry
- rotation behavior
- click rhythm
- session profile

### MLS-style analysis

Layer này dùng cho các bài toán khó kết luận bằng deterministic rules:

- AimAssist
- AutoClicker
- KillAura humanized
- Ghost client profile

Output của nó nên là:

- risk
- confidence
- category
- explanation tags

### Fusion

Fusion nhận:

- Grim facts
- analysis risk
- ping / jitter / TPS
- session history

Fusion trả ra:

- `observe`
- `alert`
- `assist`
- `soft_mitigate`
- `enforce_candidate`

## Decision model

- deterministic truth thắng
- probabilistic suspicion cần corroboration
- ML không được override movement truth
- runtime xấu phải giảm trọng số blackbox
- TPS xấu thì tắt analysis layer trước, giữ Grim sống

## Tài liệu

- [overview.md](D:/Duancanhan/AC/overview.md)
- [docs/plan/00-index.md](D:/Duancanhan/AC/docs/plan/00-index.md)
- [docs/plan/README.vi.md](D:/Duancanhan/AC/docs/plan/README.vi.md)

## Định hướng implementation

AC nên được tổ chức thành các khối:

- `core`: bridge sang Grim và whitebox facts
- `features`: collectors và feature schema
- `analysis`: async scoring và ML client
- `fusion`: policy và escalation
- `actions`: alerts, mitigation, punishment
- `ops`: logging, replay, metrics, webhook hooks
