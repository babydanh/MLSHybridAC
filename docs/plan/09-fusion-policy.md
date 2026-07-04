# Chính Sách Fusion — Chi Tiết Thuật Toán

## Mục đích

Fusion là lớp quyết định cuối cùng. Nó tổng hợp tất cả signals từ whitebox, blackbox, runtime context và session history để đưa ra hành động cụ thể.

---

## Inputs của Fusion

| Input | Nguồn | Ảnh hưởng |
|---|---|---|
| `whitebox_certainty` | Grim checks | Quyết định trực tiếp cho movement/packet |
| `whitebox_deviation` | Prediction offsets | Feature cho blackbox + evidence quality |
| `blackbox_risk` | ML scoring | Suspicion score 0-1 theo category |
| `blackbox_confidence` | Model calibration | Reliability của score |
| `ping_smoothed` | Network tracking | Downweight blackbox khi cao |
| `ping_jitter` | Network tracking | Downweight khi xấu |
| `tps_current` | Server monitoring | Adjust threshold khi TPS xấu |
| `session_risk_acc` | Per-session tracker | Escalation từ lịch sử |
| `current_exemptions` | Permission system | Loại trừ staff, trusted |
| `prior_reviews` | Staff database | Đã từng bị flag/dismissed/banned |

---

## Fusion Rules

### Rule 1: Deterministic Truth Wins

**Nếu** whitebox_certainty = HIGH cho bất kỳ domain nào (movement, packet, reach geometry):
→ Enforce NGAY mà không cần ML support
→ Chỉ ngoại lệ nếu: ping > 400ms (downgrade action tier), hoặc có exemption

```
if whitebox_certainty >= HIGH and not exempt:
    action = ENFORCE
    reason = whitebox_check_name
```

### Rule 2: ML Risk Cao Cần Corroboration

**Nếu** blackbox_risk > 0.85 mà không có whitebox support:
→ Tăng monitoring, không enforce
→ Gửi alert staff với ML explanation

```
if blackbox_risk > 0.85 and whitebox_certainty < MEDIUM:
    action = ALERT
    flag_session_for_review()
```

### Rule 3: Hybrid Escalation

**Nếu** whitebox_certainty = MEDIUM và blackbox_risk > 0.70:
→ Corroborated evidence → có thể soft mitigation
→ Enforce chỉ khi session_risk_acc đã cao

```
if whitebox_certainty == MEDIUM and blackbox_risk > 0.70:
    if session_risk_acc > escalation_threshold:
        action = SOFT_MITIGATION
    else:
        action = ASSIST  # tăng sampling, thêm debug
```

### Rule 4: Repeated Weak Evidence Escalates

**Nếu** cùng category bị flag > N lần trong cùng session window:
→ session_risk_acc tăng
→ Threshold enforcement hạ xuống

```
session_risk_acc += weight_per_flag * (1 - decay_rate)^time_since_last_flag
if session_risk_acc > ban_threshold and whitebox_confirms:
    action = ENFORCE
```

### Rule 5: Runtime Xấu Giảm Blackbox Weight

**Nếu** ping > 200ms hoặc TPS < 18 hoặc jitter > 50ms:
→ Giảm trọng số blackbox risk trong quyết định
→ Tăng ngưỡng enforce

```
runtime_penalty = compute_runtime_penalty(ping, jitter, tps)
effective_risk = blackbox_risk * (1.0 - runtime_penalty)
```

| Điều kiện | runtime_penalty |
|---|---|
| ping < 100ms, TPS ≥ 19.5, jitter < 20ms | 0.0 |
| ping 100–200ms | 0.1 |
| ping 200–300ms | 0.25 |
| ping > 300ms | 0.45 |
| TPS 18–19.5 | +0.1 |
| TPS < 18 | +0.25 |
| jitter > 50ms | +0.15 |

### Rule 6: Movement Domain Is Immutable

Whitebox movement truth không bao giờ bị ML override.
ML chỉ có thể được dùng để quyết định **severity** của response, không phải **detection**.

### Rule 7: Một Số Domain Cấm Auto-Enforce Hoàn Toàn

Các cheat này KHÔNG BAO GIỜ auto-ban, chỉ alert:
- GhostClient
- Baritone / botting
- AimAssist (giai đoạn đầu)

---

## Các Tầng Action

### Stage 0: Observe
- Ghi log nội bộ
- Không thông báo staff
- Tích lũy vào session_risk_acc với trọng số thấp

**Trigger**: Weak signal, noise nhiều, evidence đơn lẻ

### Stage 1: Alert
- Gửi thông báo staff (quyền `grim.alerts`)
- Hiển thị: check type, violation context, ping, TPS
- Tích lũy session_risk_acc với trọng số cao hơn

**Trigger**: whitebox MEDIUM flag, hoặc blackbox risk > 0.75

### Stage 2: Assist
- Tăng sampling rate cho player đó
- Bật debug flag capture
- Có thể cancel packet nhẹ nếu whitebox partial support

**Trigger**: Stage 1 + repeated trong 60s, hoặc hybrid corroborated

### Stage 3: Soft Mitigation
- Setback: đưa về vị trí hợp lệ
- Cancel action: không cho tác dụng
- Giảm impact exploit (không cho crit, không cho knockback cancel)

**Trigger**: whitebox HIGH hoặc hybrid corroborated với session history

### Stage 4: Enforce
- Kick: ngắt kết nối với message
- Temp ban: thời gian tùy config
- Perm ban: chỉ khi policy cho phép và whitebox confirms

**Trigger**:
- Whitebox HIGH certainty (movement/packet) → Tier 4 ngay
- Hybrid corroborated + session_risk_acc > threshold → Tier 4

---

## Policy Theo Nhóm Cheat

| Nhóm | Chính sách tối thiểu | Chính sách tối đa |
|---|---|---|
| Movement (speed, fly, phase) | Stage 3 (setback) | Stage 4 (ban) khi xác nhận deterministic |
| Packet (timer, badpackets) | Stage 3 (cancel) | Stage 4 (ban) khi sustained |
| Combat geometry (reach, hitbox) | Stage 3 (cancel attack) | Stage 4 nếu geometry impossible |
| Combat behavioral (killaura, aimassist) | Stage 1 (alert) | Stage 3 với corroboration |
| Click automation | Stage 1 (alert) | Stage 3 với entropy + history |
| Ghost profile | Stage 1 (alert) | Stage 1 ONLY — không auto-enforce |
| Botting / baritone | Stage 1 (alert) | Stage 1 ONLY |

---

## Session History Model

```
session_risk_acc = Σ (flag_weight[i] × decay(t - t_i))

decay(Δt) = exp(-λ × Δt)
λ = 0.001 per second  (30-minute half-life)
```

Threshold mặc định:
- Alert escalation: session_risk_acc > 50
- Soft mitigation threshold: session_risk_acc > 150 với whitebox MEDIUM
- Enforce threshold: session_risk_acc > 300 với whitebox HIGH

Flag weights theo severity:
- whitebox HIGH flag: 50
- whitebox MEDIUM flag: 20
- blackbox risk > 0.9: 30
- blackbox risk 0.75–0.9: 15
- blackbox risk < 0.75: 5

---

## Anti-False-Positive Protections

1. **Exemption system**: Staff, trusted players có thể exempt khỏi nhóm check cụ thể
2. **New player grace period**: 60 giây đầu sau join, không enforce (allow lag spike resolution)
3. **High-ping mode**: Tự động khi ping > 250ms, tăng tolerance whitebox
4. **Geyser/BedrockPlayer detection**: Disable một số check không phù hợp với Bedrock client (ví dụ: click pattern, packet order một số loại)
5. **Post-setback window**: 10 tick sau setback, không flag movement check để tránh false flag từ teleport lag
