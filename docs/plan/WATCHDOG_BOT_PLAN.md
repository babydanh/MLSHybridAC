# Kế Hoạch Implement — Watchdog Bot

## Mục tiêu
Hệ thống NPC ảo bay phía sau lưng người chơi để phát hiện KillAura tự động.

## Tuân thủ rule-skills.md

| Rule | Áp dụng |
|---|---|
| Không import Bukkit API trong common module | ✅ Packet NPC nằm trong common, dùng PacketEvents API |
| Dùng ParticleCompat | ✅ Animation spawn bot dùng ParticleCompat |
| Adventure API (MiniMessage) | ✅ Dùng cho alert messages |
| Scheduler (Bukkit/Folia) | ✅ Dùng SchedulerManager.getAdapter() |
| Dùng libs.versions.toml | ✅ PacketEvents đã có sẵn |
| Lombok | ✅ @Getter, @Setter |

## Kiến trúc

```
common/ (Platform-independent)
├── manager/
│   ├── watchdog/
│   │   ├── WatchdogBotManager.java    ← Singleton: quản lý tất cả bot
│   │   ├── WatchdogBot.java           ← Một bot instance cho 1 player
│   │   └── WatchdogBotCheck.java      ← Check phát hiện hit bot
│   └── FusionEngine.java (sửa)        ← Thêm Rule cho watchdog

bukkit/ (Platform implementation)
└── platform/bukkit/
    └── watchdog/
        └── BukkitWatchdogSpawner.java  ← Spawn packet entity qua PacketEvents
```

## Flow chi tiết

```
TickManager mỗi 5 giây:
  → WatchdogBotManager.tick()
    → Tìm player đang combat (có target, recent attack)
    → Nếu chưa có bot cho player này:
      → WatchdogBotManager.spawnBot(player)
        → Tính vị trí bot: sau lưng player >110°, cách 3.5-4.5 blocks
        → WatchdogBot.start() gửi packet spawn + rotation + teleport

Mỗi tick:
  → WatchdogBot.tick():
    → Update bot position theo quỹ đạo vòng tròn
    → Gửi PacketPlayOutEntityTeleport + PacketPlayOutEntityHeadRotation
    → Nếu đã sống >10 giây → despawn

Khi attack packet đến (CheckManagerListener):
  → WatchdogBotCheck.onPacketReceive():
    → Nếu entityId trùng với bot ID → hitCount++
    → Nếu hitCount ≥ 3 trong 2s → flag → FusionEngine → ALERT/ENFORCE

Khi player disconnect:
  → WatchdogBotManager.removeBot(player) → gửi packet despawn
```

## Packet NPC Implementation

Dùng PacketEvents API (đã có sẵn trong dependencies):

```java
// Spawn: gói tin giả lập entity người chơi
WrapperPlayServerSpawnEntity spawnPacket = new WrapperPlayServerSpawnEntity(
    entityId, UUID.randomUUID(),
    EntityTypes.PLAYER, position, yaw, pitch, headYaw, 0, null
);

// Rotation: cập nhật hướng nhìn mỗi tick
WrapperPlayServerEntityHeadRotation headPacket = 
    new WrapperPlayServerEntityHeadRotation(entityId, headYaw);
WrapperPlayServerEntityRotation rotationPacket = 
    new WrapperPlayServerEntityRotation(entityId, yaw, pitch, true);

// Teleport: di chuyển bot theo quỹ đạo
WrapperPlayServerEntityTeleport teleportPacket = 
    new WrapperPlayServerEntityTeleport(entityId, position, yaw, pitch, true);

// Metadata: skin người chơi (tùy chọn)
WrapperPlayServerEntityMetadata metadataPacket = 
    new WrapperPlayServerEntityMetadata(entityId, metadataList);

// Destroy: khi hết thời gian
WrapperPlayServerDestroyEntities destroyPacket = 
    new WrapperPlayServerDestroyEntities(entityId);
```

## File Implementation

### 1. WatchdogBot.java (~150 dòng)
- State: entityId, player, position, yaw, pitch, hitCount, spawnTime
- Quỹ đạo: circle around player at 4 blocks radius
- isBehindPlayer(): check góc >110°
- tick(): update position + gửi packet
- spawn(): gửi spawn packet đến player
- despawn(): gửi destroy packet
- recordHit(): tăng hitCount, kiểm tra threshold

### 2. WatchdogBotManager.java (~100 dòng)
- Singleton, Map<UUID, WatchdogBot> activeBots
- tick(): duyệt player đang combat, spawn bot mới, tick bot hiện tại
- spawnBot(player): tạo WatchdogBot mới
- removeBot(player): despawn + xóa khỏi map
- getBot(entityId): tìm bot theo entityId

### 3. WatchdogBotCheck.java (~80 dòng)
- PacketCheck, onPacketReceive()
- Bắt attack packet (UseEntity/ATTACK)
- Nếu entityId == botId → WatchdogBot.recordHit()
- Flag nếu hitCount ≥ 3 trong 2 giây

### 4. FusionEngine.java (sửa ~5 dòng)
- Thêm Category.WATCHDOG_BOT
- Rule: watchdog flag → ENFORCE (tương tự R6)

## Timeline

| File | Thời gian |
|---|---|
| `WatchdogBot.java` | 30 phút |
| `WatchdogBotManager.java` | 20 phút |
| `WatchdogBotCheck.java` | 20 phút |
| `FusionEngine.java` sửa | 5 phút |
| Build verify | 5 phút |
| **Total** | **~80 phút** |
