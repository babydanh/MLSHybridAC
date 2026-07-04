# Kiến Trúc Hybrid — Complete Data Flow

## 1. Sơ Đồ Complete Data Flow (6 Layers)

Dữ liệu luân chuyển qua 6 Layer tuần tự. Mỗi layer có nhiệm vụ riêng biệt, đảm bảo tính bất đồng bộ (async) cho các bước nặng và không bao giờ block game thread.

```text
       PACKET EVENTS (PacketEvents API / Network Inbound)
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 1. INGESTION LAYER (PacketProcessor — Game Thread)                                  │
│ ─────────────────────────────────────────────────────────────────────────────────── │
│  Phân loại gói tin → Route sang các Handler → Ghi vào Player Session State (RAM)    │
│                                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │
│  │ Movement    │  │ Combat      │  │ Packet/     │  │ World       │                │
│  │ Packets     │  │ Packets     │  │ Connection  │  │ Packets     │                │
│  │ (Position,  │  │ (UseEntity, │  │ (KeepAlive, │  │ (BlockPlace,│                │
│  │  Look, Fly) │  │  Swing)     │  │  Transact.) │  │  BlockBreak)│                │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                │
│         │                │                │                │                       │
│         └────────────────┴────────────────┴────────────────┘                       │
│                                           │                                         │
│                                           ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │              PLAYER SESSION STATE (ThreadLocal / Heap RAM)                   │   │
│  │  positionHistory    : EvictingQueue<PositionPacket>(40)  // ~2 giây          │   │
│  │  rotationHistory    : EvictingQueue<RotationPacket>(40)                      │   │
│  │  attackHistory      : EvictingQueue<AttackPacket>(20)   // 20 swing gần nhất │   │
│  │  clickHistory       : EvictingQueue<ClickPacket>(50)    // 50 clicks         │   │
│  │  transactionHistory : EvictingQueue<Transaction>(100)   // RTT tracking      │   │
│  │  blockHistory       : EvictingQueue<BlockAction>(30)                         │   │
│  │  ─────────────────────────────────────────────────────                       │   │
│  │  Derived State (cập nhật mỗi tick):                                          │   │
│  │    currentPos / currentVel / currentRot / onGround / vehicle                 │   │
│  │    isSneaking / isSprinting / activeEffects / crawling                       │   │
│  │  ─────────────────────────────────────────────────────                       │   │
│  │  Network Context:                                                            │   │
│  │    pingMs / pingJitterMs / packetLossRatio / currentCPS                      │   │
│  │    lastSwingTick / lastTargetId / windChargeContext                          │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼ (Game Thread — Per Tick, max 0.1ms per player)
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 2. WHITEBOX ENGINE (Grim Core — Deterministic Truth)                                │
│ ─────────────────────────────────────────────────────────────────────────────────── │
│  Kiểm tra tính hợp lệ hình học, vật lý, giao thức Minecraft 1.21.11                 │
│                                                                                     │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │ Movement Engine     │  │ Combat Engine       │  │ Packet Engine       │          │
│  │ • PredictionRunner  │  │ • ReachValidator    │  │ • TransactionManager│          │
│  │   (simulate pos/vel)│  │   (raytrace, hitbox)│  │   (RTT, lag class)  │          │
│  │ • FlightCheck       │  │ • KnockbackValidator│  │ • PacketOrderCheck  │          │
│  │ • PhaseCheck        │  │ • CriticalValidator │  │ • BadPacketCheck    │          │
│  │ • NoFallCheck       │  │ • MaceSmashValidator│  │ • TimerCheck        │          │
│  │ • SpeedCheck        │  │ • CrystalValidator  │  │                     │          │
│  └─────────┬───────────┘  └─────────┬───────────┘  └─────────┬───────────┘          │
│            └────────────────────────┴────────────────────────┘                      │
│                                           │                                          │
│                                           ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                     WHITEBOX EVIDENCE (Structured Fact Output)               │   │
│  │  WhiteboxEvidence {                                                          │   │
│  │    FlyFact       { deviation: Vector3, certainty: 0.97, lagClass: GOOD }    │   │
│  │    SpeedFact     { hVelDeviation: 0.12, certainty: 0.95, lagClass: GOOD }   │   │
│  │    NoFallFact    { fallDist: 4.2, damageTaken: 0, certainty: 0.99 }         │   │
│  │    ReachFact     { distance: 3.12, maxLegit: 3.0, excess: 0.12, cert: 0.95}│   │
│  │    KBFact        { expected: Vec, actual: Vec, deviation: 0.15, cert: 0.9 } │   │
│  │    CriticalFact  { onGround: true, fakeAir: true, certainty: 0.98 }         │   │
│  │    MaceFact      { fallDistPreSmash: 0.3, required: 1.5, cert: 0.99 }       │   │
│  │    TransactFact  { avgRTT: 45ms, jitter: 8ms, loss: 0.01, lagClass: GOOD } │   │
│  │    BadPacketFact { violations: [], certainty: 1.0 }                         │   │
│  │  }                                                                           │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                     │
                     │  Nếu whitebox certainty >= HIGH → Enforce NGAY (bỏ qua Layer 3-5)
                     │  Nếu certainty < HIGH → tiếp tục pipeline async
                     ▼ (Async Worker Pool — Batched theo combat window 3-10s)
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 3. FEATURE EXTRACTION LAYER (Bridge: Facts + State → Signal Vector)                 │
│ ─────────────────────────────────────────────────────────────────────────────────── │
│  Kết hợp WhiteboxEvidence + Session State + Raw History Buffers → FeatureVector     │
│                                                                                     │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │ Movement Features   │  │ Combat / Aim Feat.  │  │ Session Features    │          │
│  │ • pos_delta         │  │ • target_snap_angle │  │ • violation_rate    │          │
│  │ • vel_residual      │  │ • gcd_error_yaw/pch │  │ • category_dist     │          │
│  │ • accel_magnitude   │  │ • rotation_jerk_dist│  │ • lagProfile embed  │          │
│  │ • prediction_offset │  │ • post_hit_lock_dur │  │ • trust_score       │          │
│  │ • onground_trans    │  │ • hitbox_edge_ratio │  │ • playtime / history│          │
│  │ • timer_ratio       │  │ • reach_excess      │  │                     │          │
│  └─────────┬───────────┘  └─────────┬───────────┘  └─────────┬───────────┘          │
│            └────────────────────────┴────────────────────────┘                      │
│                                           │                                          │
│                                           ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                     FEATURE VECTOR (Normalized, Fixed Size)                  │   │
│  │  FeatureVector {                                                             │   │
│  │    double[] movement;   // 32 features (8 per tick × 4 tick window)          │   │
│  │    double[] combat;     // 24 features (6 per swing × 4 swing window)        │   │
│  │    double[] click;      // 8 features (entropy, CPS, burst, intervals)       │   │
│  │    double[] rotation;   // 20 features (yaw/pitch delta, jerk distribution)  │   │
│  │    double[] packet;     // 16 features (RTT, jitter, loss, timer drift)      │   │
│  │    double[] session;    // 12 features (reputation, history, playtime)       │   │
│  │    LagProfile lag;      // { avgRTT, p95RTT, jitter, loss, lagClass }        │   │
│  │    long windowTimestamp;                                                     │   │
│  │  }                                                                           │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼ (Async — timeout 50ms, circuit breaker, fallback local)
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 4. BLACKBOX ANALYSIS LAYER (Probabilistic Scoring)                                  │
│ ─────────────────────────────────────────────────────────────────────────────────── │
│  Chạy song song nhiều model học máy, mỗi model chuyên một nhóm hành vi              │
│                                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ Aim (GBDT)   │  │ Click(LogReg)│  │ Ghost (Ensem)│  │ Seq. (LSTM)  │             │
│  │ • gcd_error  │  │ • entropy    │  │ • hit_consist│  │ • temporal   │             │
│  │ • curvature  │  │ • rhythm     │  │ • snap_score │  │ • cross-cat  │             │
│  │ • jerk_dist  │  │ • burst_score│  │ • rot_corr   │  │ • burst_time │             │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘             │
│         └─────────────────┴─────────────────┴─────────────────┘                    │
│                                           │                                          │
│                                           ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                     BLACKBOX RISK OUTPUT                                     │   │
│  │  BlackboxRisk {                                                              │   │
│  │    Map<Category, Double> riskScores;   // 0.0–0.985 (không bao giờ 1.0)     │   │
│  │    Map<Category, Double> confidence;   // model confidence                  │   │
│  │    Map<Category, List<String>> tags;   // "gcd_error_low", "post_hit_lock"  │   │
│  │    long modelVersion;                                                        │   │
│  │    long inferenceTimeMs;                                                     │   │
│  │  }                                                                           │   │
│  │  Ví dụ:                                                                      │   │
│  │    AIM_ASSIST: risk=0.87, conf=0.92, tags=["gcd_low","post_hit_lock"]        │   │
│  │    AUTO_CLICK: risk=0.61, conf=0.78, tags=["entropy_low","burst_pattern"]    │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼ (Async — Đọc từ cache nếu còn TTL, tính mới nếu hết hạn)
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 5. FUSION ENGINE (Decision Layer — Bayesian Integration)                            │
│ ─────────────────────────────────────────────────────────────────────────────────── │
│  Inputs:                                                                            │
│    ├─ WhiteboxEvidence  (Facts chắc chắn từ Layer 2)                                │
│    ├─ BlackboxRisk      (Probability scores từ Layer 4)                             │
│    ├─ RuntimeContext    { ping, tps, jitter, lagClass, exemptions }                 │
│    └─ SessionState      { reputation, priorFlags, playtime, staffNotes }            │
│                                                                                     │
│  Process:                                                                           │
│    1. bbWeight = f(lagClass, tps, trustScore)      // giảm trọng số khi lag xấu    │
│    2. posterior = bayesianFusion(wb_certainty, bb_risk × bbWeight, prior)           │
│    3. Corroboration bonus: nhiều category cùng flag → posterior tăng               │
│    4. Runtime penalty: TPS < 18 hoặc ping > 300ms → threshold tăng                 │
│    5. Policy decision dựa trên posteriorMap + SessionRiskAccumulator                │
│                                                                                     │
│  Output:                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  FusionResult {                                                              │   │
│  │    Map<Category, Double> posteriorRisk;                                      │   │
│  │    Action action;    // OBSERVE / ALERT / ASSIST / SOFT_MITIGATE / ENFORCE   │   │
│  │    Category primary; // category có risk cao nhất                            │   │
│  │    String reasoning; // "Whitebox Fly 0.99 + lagClass GOOD → ENFORCE"        │   │
│  │    EvidenceSnapshot evidence; // toàn bộ context để audit / replay           │   │
│  │    long decisionTimestamp;                                                   │   │
│  │  }                                                                           │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼ (Dispatch về Game Thread cho setback/kick, Async cho log/DB)
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 6. ACTION LAYER (Execution & Audit)                                                 │
│ ─────────────────────────────────────────────────────────────────────────────────── │
│  ActionExecutor {                                                                   │
│    OBSERVE:       log nội bộ, tăng SessionRiskAcc, không thông báo staff           │
│    ALERT:         staff ingame + Discord/webhook, log, tăng VL                     │
│    ASSIST:        tăng sampling rate, bật debug, suggest /spectate cho staff       │
│    SOFT_MITIGATE: setback vị trí / cancel knockback cancel / reduce crit effect    │
│    ENFORCE:       kick/ban + BanAnimationEngine + đẩy EvidencePacket → Database    │
│  }                                                                                  │
│                                                                                     │
│  EvidencePacket (lưu khi ENFORCE / cao hơn ALERT):                                 │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │    WhiteboxEvidence snapshot   (fact tại thời điểm phạt)                    │   │
│  │    BlackboxRisk snapshot       (ML score + tags)                            │   │
│  │    FeatureVector[5]            (5 cửa sổ gần nhất trước khi phạt)           │   │
│  │    RuntimeContext snapshot     (ping, TPS, jitter lúc đó)                   │   │
│  │    DecisionTrace { rules fired, weights, thresholds, posterior }            │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                     │
                     ▼ (Async I/O — không block bất kỳ thread nào)
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 7. STORAGE LAYER (Database — SQLite / MySQL / MongoDB)                              │
│    [Xem chi tiết tại Phần 3]                                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Cấu Trúc Player Session State (Chi Tiết)

Dữ liệu thô lưu trong RAM dạng **EvictingQueue (rolling window)** — tự giải phóng bộ nhớ khi quá kích thước:

```java
public class PlayerData {

    // ========== 1. Raw Rolling Buffers (RAM — EvictingQueue tự purge) ==========
    Queue<PositionPacket>    positionHistory    = new EvictingQueue<>(40);   // 2 giây (~40 ticks)
    Queue<RotationPacket>    rotationHistory    = new EvictingQueue<>(40);
    Queue<AttackPacket>      attackHistory      = new EvictingQueue<>(20);   // 20 swing gần nhất
    Queue<ClickPacket>       clickHistory       = new EvictingQueue<>(50);   // 50 clicks gần nhất
    Queue<TransactionPacket> transactionHistory = new EvictingQueue<>(100);  // RTT tracking
    Queue<BlockActionPacket> blockHistory       = new EvictingQueue<>(30);   // đặt/phá block

    // ========== 2. Derived State (cập nhật mỗi tick, không cần queue) ==========
    double currentX, currentY, currentZ;
    double motionX, motionY, motionZ;
    float  currentYaw, currentPitch;
    boolean onGround, isSneaking, isSprinting, isCrawling;
    Entity  vehicle;
    Set<PotionEffect> activeEffects;

    // ========== 3. Network & Context ==========
    int    pingMs;              // Transaction RTT thực tế
    int    pingJitterMs;        // Độ lệch RTT
    double packetLossRatio;     // Tỷ lệ mất packet phản hồi
    int    currentCPS;          // Clicks per second hiện tại
    long   lastSwingTick;
    UUID   lastTargetId;
    boolean windChargeActive;   // Wind Charge impact context (1.21)
    int    ticksSinceSetback;   // Tránh false-flag sau setback

    // ========== 4. Session Risk (Accumulator) ==========
    double sessionRiskAccumulator;   // Decay theo thời gian: acc × exp(-λΔt)
    long   lastFlagTimestamp;
    Map<CheckCategory, Integer> flagCountByCategory;
}
```

---

## 3. Kiến Trúc Lưu Trữ 2 Lớp

### Lớp 1: Hot Cache (RAM — Truy cập <1ms)
- **Player Session State** và **WhiteboxEvidence** sống hoàn toàn trong RAM.
- Không ghi vào đĩa, không gọi database.
- Giải phóng tự động khi player disconnect.

### Lớp 2: Cold Store (Database — Ghi bất đồng bộ)

Tận dụng hệ thống kết nối sẵn có của Grim (SQLite/MySQL). Chỉ ghi khi:
- Có sự kiện vi phạm (Alert trở lên)
- Player disconnect (flush session profile)

| Bảng | Nội dung | Backend |
|---|---|---|
| `grim_hybrid_evidence` | EvidencePacket JSON, timestamp, player UUID, check type | SQLite / MySQL |
| `grim_player_reputation` | trustScore, priorFlagCount, last ban timestamp | SQLite / MySQL |
| `grim_feature_archive` | FeatureVector raw (optional, dùng cho training ML sau này) | MongoDB (optional) |

**Quy tắc bắt buộc**: Mọi ghi database đều phải chạy trong Async Worker Pool, không được gọi trực tiếp từ Game Thread.

---

## 4. Thread Model

| Thread | Nhiệm vụ | Giới hạn thời gian |
|---|---|---|
| Game Thread | Nhận packet, cập nhật PlayerData, chạy Whitebox checks, thực thi setback/kick | ≤ 0.1ms / player / tick |
| Async Worker Pool | Feature extraction, ML inference, Fusion evaluation, DB write, webhook | Không giới hạn (bounded queue) |
| ML Remote gRPC (Optional) | ONNX / LSTM remote inference service | Timeout cứng 50ms |

Nguyên tắc dispatch:
- Từ Game Thread → Async: `CompletableFuture.runAsync(task, asyncPool)`
- Từ Async → Game Thread: `SchedulerManager.getAdapter().runEntitySync(player, task)`

---

## 5. Nguyên Tắc Thiết Kế Cốt Lõi

| Nguyên tắc | Quy tắc thực thi |
|---|---|
| **Corroboration > Single signal** | Không enforce chỉ dựa trên một check đơn lẻ. Cần nhiều signal cùng category. |
| **Whitebox wins** | Whitebox certainty = 1.0. Không ML nào có thể override movement truth. |
| **Blackbox risk ceiling** | ML risk score tối đa 0.985 — không bao giờ đạt 1.0. |
| **Runtime-aware weighting** | Tăng ping/jitter/TPS xấu → giảm trọng số blackbox tự động. |
| **Configurable policy (YAML)** | Thresholds, weights và actions không hardcode — cấu hình trong YAML. |
| **Audit trail bắt buộc** | Mỗi lần ENFORCE phải có EvidencePacket đầy đủ lưu vào database. |
| **Safe mode** | Khi TPS < 15: tắt toàn bộ ML, chỉ giữ Whitebox movement + packet core. |
