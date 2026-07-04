# Hệ Thống ML — Hướng Dẫn Chi Tiết Thực Chiến

## Vai Trò Đúng Của ML

ML là lớp **scoring risk hành vi**, không phải là anticheat core. Nó xử lý chính xác những gì whitebox không thể:

- **Aim behavior**: phân phối xoay camera, jitter, snap pattern
- **Click rhythm**: entropy, interval distribution, burst/silence
- **Combat automation**: multi-tick attack correlation, hit rate vs movement complexity
- **Session profile**: long-window behavioral drift

ML **không được**:
- Quyết định movement truth
- Override deterministic Grim whitebox checks
- Auto-ban mà không có whitebox corroboration (trong các giai đoạn đầu)

---

## Vị Trí Trong Pipeline

```
packet/state/context
  → Grim whitebox (deterministic truth)
  → Feature extraction (per-tick, per-window, per-session)
  → ML / blackbox scoring (async, không block game thread)
  → Fusion policy (quyết định cuối)
  → Alert / mitigation / enforcement
```

**ML nhận đầu vào là:**
- Raw behavioral features (aim, click, movement)
- Windowed aggregates (CPS, jitter std dev, rotation variance)
- Selected whitebox signals (prediction offset, hit geometry delta, packet anomalies)
- Runtime context (ping, jitter, TPS)

**Không phải** là "rank tổng của whitebox" rồi cho vào ML.

---

## Kiến Trúc Đề Xuất

### Option A: Local Light Inference (Ưu tiên giai đoạn đầu)

**Phù hợp với:**
- Logistic regression
- Gradient Boosting (XGBoost, LightGBM — nhúng qua ONNX)
- Rule-assisted scoring có trọng số

**Ưu điểm:**
- Không phụ thuộc mạng
- Latency < 1ms
- Dễ debug và audit
- Chạy trong JVM qua ONNX4J hoặc SmileML

**Nhược điểm:**
- Model phức tạp (RNN, Transformer) không dùng được
- Mở rộng sequence modeling khó

**Dùng cho:** AimAssist scoring, AutoClicker classification, click entropy score

---

### Option B: Remote Inference Service (Giai đoạn 2+)

**Phù hợp với:**
- LSTM / GRU cho rotation sequence modeling
- Transformer encoder cho session behavioral profiling
- Ensemble phức tạp

**Kiến trúc:**
```
Plugin (Java)
  → Feature buffer (non-blocking queue)
  → gRPC hoặc HTTP/2 call (async)
  → Inference server (Python/Go + ONNX Runtime)
  → Risk score response
  → Local cache với TTL 5-10s
```

**Ưu điểm:**
- Tách hoàn toàn khỏi JVM game server
- Cập nhật model không cần restart plugin
- Scalable theo số lượng player

**Bắt buộc có:**
- Timeout cứng: 50ms per request
- Circuit breaker: sau 5 timeout liên tiếp → tắt remote, dùng local fallback
- Bounded queue: max 500 pending tasks, drop oldest khi đầy
- Fallback: local rule-based score khi remote unreachable

---

## Lộ Trình Model Theo Giai Đoạn

### Giai đoạn 1: Rule-based scoring (không ML thật)

```
click_entropy_score = entropy(click_intervals_1min)
aim_consistency_score = 1 - std_dev(yaw_jerk_per_tick) / baseline
combat_score = weighted_sum([click_entropy, aim_consistency, velocity_respect_ratio])
```

- Không cần training data
- Dễ audit
- Chưa auto-enforce

### Giai đoạn 2: Statistical ML (Logistic + GBM)

- **Target**: binary label (cheat / legit) từ staff review + whitebox certainty cases
- **Features**: top 20 features từ feature spec
- **Calibration**: Platt scaling để output là probability
- **Thresholds**: P > 0.85 → alert, P > 0.95 + whitebox corroboration → enforce candidate
- **Feature importance**: XGBoost SHAP để kiểm tra bias

### Giai đoạn 3: Sequence Models

- **Aim sequence**: GRU/LSTM trên window 2s yaw/pitch delta → detect inhuman smoothness
- **Click sequence**: 1D CNN trên interval distribution → detect scripted pattern
- **Session profile**: Gradient boosting trên session-level aggregates

---

## Labeling & Data

**Nguồn label chất lượng cao:**
1. Whitebox certainty cases (Grim flag với confidence cao → positive)
2. Staff manual review + replay verification
3. Known clean players (op staff, trusted longtime players) → negative

**Tránh:**
- Dùng punishment action làm label duy nhất (circular bias)
- Label từ player reports (noisy)
- Train trên unreviewed flags (self-reinforcing)

**Data hygiene:**
- Stratified sampling: không để imbalanced classes quá nặng
- Hold-out test set từ server khác hoặc thời điểm khác để tránh overfitting temporal
- Track false positive rate theo client type (Geyser, ViaVersion)

---

## Runtime Guardrails

| Điều kiện | Hành động |
|---|---|
| ML inference timeout > 50ms | Dùng cached score hoặc rule-based fallback |
| Circuit breaker OPEN | Tắt remote, chạy local model |
| TPS < 18 | Dừng toàn bộ ML tier cao, chỉ giữ whitebox |
| TPS < 15 | Tắt cả ML, chỉ giữ movement + packet core |
| Queue depth > 80% | Drop low-priority tasks (session-level, không phải per-attack) |
| Player ping > 500ms | Giảm trọng số ML risk, tăng ping_jitter discount trong fusion |

---

## Observability ML

Cần track trong production:

- `ml_inference_latency_ms` — histogram
- `ml_timeout_count` — counter
- `ml_circuit_state` — gauge (CLOSED/OPEN/HALF_OPEN)
- `ml_cache_hit_ratio` — gauge
- `ml_score_distribution` — histogram by check type
- `ml_false_positive_estimate` — từ staff dismissal rate
- `model_version` — tagged on all metrics
