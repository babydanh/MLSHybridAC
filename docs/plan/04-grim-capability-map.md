# Bản Đồ Năng Lực Của Grim

## Bản chất của Grim

`Grim` là một whitebox anticheat theo hướng:

- packet-level state tracking
- transaction-based latency compensation
- per-player world replication
- movement prediction engine
- deterministic validity checks

## Grim mạnh nhất ở đâu

### Movement truth

- speed
- fly
- nofall
- phase
- step-related validation
- vehicle movement
- elytra, fluid và block interaction edge cases

### Reach và geometry

- attack reach validation
- hitbox hoặc raytrace-based impossible interactions

### Packet integrity

- timer
- bad packets
- packet order
- impossible action combinations

### Interaction validity

- block place
- block break
- multi-action conflicts
- ghost block mitigation

## Grim bắt tốt các cheat nào

- Reach
- Speed
- Fly
- NoFall
- Phase
- Timer
- BadPackets
- PacketOrder
- FastBreak
- nhiều biến thể Scaffold
- nhiều biến thể velocity abuse

## Grim bắt được nhưng không phải sở trường

- KillAura ở mức geometry và sequencing
- Hitbox abuse ở mức impossible angle
- một phần combat interaction order abuse

## Grim yếu hơn ở đâu

- AimAssist tinh vi
- AutoClicker humanized
- Ghost client profiling
- "legit aura"
- reaction model
- session-level behavioral anomaly

## Kết luận kiến trúc

Grim không "chưa đủ" vì yếu. Nó "chưa đủ" vì bài toán combat behavior không phù hợp với deterministic engine.

## Vai trò đề xuất cho Grim trong dự án

- là authority cho movement, packet, reach và world validity
- là nguồn state cho feature extraction
