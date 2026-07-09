# Kế Hoạch Thực Thi Core Trimming

## Phase 1: Trim CheckManager.java (138 → ~28 checks)

### Giữ lại (KEEP) — 28 checks essential

**Combat (5):**
- `Reach` — geometry reach prediction (best in class)
- `Hitboxes` — hitbox abuse detection (invoked by Reach)
- `MultiInteractA` — multi-target detection
- `MultiInteractB` — multi-target timing
- `KnockbackHandler` — velocity/anti-knockback

**Movement (6):**
- `PredictionRunner` — bridge PredictionEngine → PositionCheck
- `OffsetHandler` — prediction offset violation
- `GroundSpoof` — onGround state validation
- `Phase` — noclip/phase detection
- `NoFall` — fall damage validation
- `NoSlow` — slow movement bypass

**Packet (6):**
- `Timer` — transaction-based timer (phát hiện 1.01x)
- `TickTimer` — client tick end validation
- `TimerLimit` — packet rate limiting
- `BadPacketsA` — impossible state combinations
- `BadPacketsB` — impossible state (pitch limits)
- `PacketOrderA` — packet sequencing

**Scaffolding (4):**
- `InvalidPlaceA` — invalid block placement rotation
- `InvalidPlaceB` — invalid block placement position
- `RotationPlace` — rotation-based placement check
- `AirLiquidPlace` — placement in air/liquid

**Breaking (4):**
- `FastBreak` — mining speed validation
- `RotationBreak` — rotation-based break check
- `WrongBreak` — wrong block breaking
- `PositionBreakA` — position-based break

**Aim/Rotation (3):**
- `AimProcessor` — aim analysis processor
- `AimModulo360` — modulo 360 aim check
- `AimDuplicateLook` — duplicate look detection

### Disable (DISABLE) — 110 checks chuyển config mặc định = false

**BadPackets (24 checks bỏ):** C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z
**PacketOrder (15 checks bỏ):** B, C, D, E, F, G, H, I, J, K, L, M, N, O, P
**Sprint (7 checks bỏ):** SprintA, B, C, D, E, F, G
**Elytra (9 checks bỏ):** ElytraA → I
**Crash (9 checks bỏ):** CrashA → I
**Vehicle (6 checks bỏ):** VehicleA → F
**MultiActions (7 checks bỏ):** MultiActionsA → G
**Breaking (6 checks bỏ):** AirLiquidBreak, MultiBreak, NoSwingBreak, FarBreak, InvalidBreak, PositionBreakB
**Misc (4 checks bỏ):** ClientBrand, GhostBlockMitigation, Post, TransactionOrder
**Chat (4 checks bỏ):** ChatA, B, C, D
**Exploit (2 checks bỏ):** ExploitA, B
**Velocity (1 check bỏ):** ExplosionHandler
**Baritone (1 check bỏ):** Baritone
**Scaffolding (2 checks bỏ):** DuplicateRotPlace, FabricatedPlace, MultiPlace, PositionPlace, FarPlace
**Other (1 check bỏ):** GhostBlockDetector, SuperDebug, DebugHandler, NegativeTimer, VehicleTimer, VehiclePredictionRunner
**Timer (1 check bỏ):** VehicleTimer (chỉ để timer cho player)

## Cách thực thi

### Bước 1: Config mặc định
Thêm vào `config.yml` mặc định:
```yaml
# Checks that are DISABLED by default in MLSHybridAC
# (were part of upstream Grim but trimmed for performance)
disabled-checks:
  - BadPacketsC
  - BadPacketsD
  ...
```

### Bước 2: CheckManager.java
Giữ nguyên registration nhưng check `isEnabled` sẽ đọc từ config.
Check nào disabled trong config → `isEnabled = false` → không flag.

### Bước 3: Build test
```bash
./gradlew :bukkit:compileJava -x test
./gradlew build -x test
```

## Timeline
| Task | Thời gian | Trạng thái |
|------|-----------|------------|
| Tạo config disabled-checks | 30 phút | ⏳ |
| Sửa CheckManager.java | 30 phút | ⏳ |
| Build test | 5 phút | ⏳ |
| Push lên GitHub | 5 phút | ⏳ |
