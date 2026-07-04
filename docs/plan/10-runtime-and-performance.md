# Runtime Và Hiệu Năng — Thiết Kế Chi Tiết

## Nguyên tắc hiệu năng cốt lõi

**Quy tắc tối thượng**: Game thread không bao giờ bị block bởi ML inference, network call, hoặc file I/O.

Phân cấp thread priority:
1. **Game thread (hot path)**: Whitebox validation, packet state update, basic feature collection
2. **Entity scheduler / region thread**: Setback execution, lightweight combat checks
3. **Async pool (low priority)**: Feature aggregation, ML inference, webhook, log flush

---

## Pipeline Runtime Cụ Thể

```
[1] Packet nhận (PacketEvents listener)
      → Cập nhật player state (transaction tracking, position, rotation)
      → Hot-path feature capture (interval, delta, state flags)

[2] Whitebox validation (game thread, < 0.1ms per player per tick)
      → Movement prediction check
      → Reach geometry raytrace
      → Packet validity check
      → Flag hoặc setback nếu deterministic violation

[3] Feature extraction trigger (game thread, non-blocking push)
      → Enqueue feature snapshot vào bounded per-player queue
      → Return ngay, không đợi kết quả

[4] Feature aggregation worker (async thread pool)
      → Đọc queue, tính windowed aggregates
      → Cập nhật per-player feature cache

[5] ML / blackbox scoring (async thread pool)
      → Lấy feature từ cache
      → Gọi local model hoặc remote service (async, timeout 50ms)
      → Lưu risk score vào per-player risk cache (TTL 2-5s)

[6] Fusion evaluation (triggered on flag or periodic check)
      → Đọc whitebox certainty + risk cache + session history
      → Áp fusion rules
      → Quyết định action

[7] Action execution
      → Alert: Bukkit async message dispatch
      → Setback: queue vào entity scheduler
      → Kick/ban: execute trên main thread hoặc entity scheduler
      → Log: async write
```

---

## Budget Theo Layer

| Layer | Thread | Max time | Ghi chú |
|---|---|---|---|
| Packet state update | Game thread | 0.05ms | Critical — không được vượt |
| Whitebox validation | Game thread | 0.1ms per player per tick | Phải có early-exit nếu light mode |
| Feature capture | Game thread | < 0.01ms | Chỉ push to queue, không compute |
| Feature aggregation | Async pool | 5ms per player per window | Không block |
| ML local inference | Async pool | < 5ms per request | ONNX model nhỏ |
| ML remote inference | Async pool | timeout 50ms | Circuit breaker bảo vệ |
| Fusion evaluation | Async pool | < 1ms | Rule-based, không ML |
| Alert dispatch | Async pool | < 2ms | Bukkit sendMessage |
| Log write | Async pool | < 5ms | Buffer + batch write |

---

## Queue và Load Shedding

### Per-player feature queue
- Bounded size: 100 entries per player
- Drop policy: drop oldest khi đầy
- Stale threshold: entries > 2s tuổi được skip

### Global ML inference queue
- Bounded size: 500 tasks tổng
- Priority: combat events > movement events > session events
- Drop policy: drop session events trước, rồi movement, combat không drop

### Backpressure signal
- Nếu queue depth > 80% → tắt session-level ML
- Nếu queue depth > 95% → chỉ giữ whitebox core

---

## Adaptive Load Shedding Theo TPS

| TPS Server | Chế độ | ML layer bật |
|---|---|---|
| ≥ 19.5 | Normal | Tất cả |
| 18–19.5 | Warning | Tắt session profiling ML |
| 15–18 | Reduced | Chỉ giữ local rule-based scoring |
| < 15 | Safe mode | Tắt toàn bộ ML, chỉ whitebox core |
| < 10 | Emergency | Tắt cả logging nặng, chỉ setback+kick deterministic |

TPS được đọc từ server mỗi 5 giây, không đọc mỗi tick.

---

## Fallback States

```
Remote ML → timeout → retry 1 lần → fallback local model
Local model → exception → fallback rule-based score
Rule-based → exception → fallback score = 0 (observe only)
Circuit OPEN → reject all remote calls → local only mode
```

---

## Observability

### Metrics cần expose (JMX hoặc Prometheus endpoint)

| Metric | Type | Mô tả |
|---|---|---|
| `ac.whitebox.flags_per_second` | Counter | Rate flags whitebox |
| `ac.whitebox.setback_per_second` | Counter | Rate setbacks |
| `ac.feature.queue_depth` | Gauge | Số item trong feature queue |
| `ac.ml.inference_latency_ms` | Histogram | Latency ML call |
| `ac.ml.timeout_count` | Counter | Số timeout ML |
| `ac.ml.circuit_state` | Gauge | 0=CLOSED, 1=OPEN, 2=HALF_OPEN |
| `ac.ml.cache_hit_ratio` | Gauge | % lần lấy từ cache thay vì infer |
| `ac.fusion.action_tier_count` | Counter | Alert/assist/soft/enforce count |
| `ac.player.top_risk_score` | Gauge | Risk cao nhất đang quan sát |
| `ac.tps_mode` | Gauge | Chế độ load shedding hiện tại |

### Log levels

- `TRACE`: per-packet detail (chỉ khi debug mode cho player cụ thể)
- `DEBUG`: per-flag detail
- `INFO`: action taken (alert, setback, kick, ban)
- `WARN`: anomalies (circuit open, queue overflow, model error)
- `ERROR`: critical failures

---

## Safe Mode

Khi bật safe mode (command hoặc TPS trigger):

```
/grimac safemode on
```

- Tắt toàn bộ ML inference (local và remote)
- Tắt blackbox scoring
- Giữ Grim whitebox + packet protection đầy đủ
- Giữ alert cho deterministic flags
- Log safe mode activation với reason

Safe mode không phải "tắt anticheat". Vẫn bảo vệ movement, reach, packet, timer.
