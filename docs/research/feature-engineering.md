# Feature Engineering cho Minecraft Anticheat ML Models

> **Phiên bản:** 1.0  
> **Dự án:** MLSHybridAC (GrimAC + ML Layer)  
> **Ngày:** 2026-07-10  
> **Mục tiêu:** Phân tích chi tiết từng feature, cách tính, ý nghĩa thống kê, khoảng giá trị, edge cases, và chiến lược tối ưu cho LightGBM/GBDT training.

---

## Mục lục

1. [Tổng quan hệ thống](#1-t%E1%BB%95ng-quan-h%E1%BB%87-th%E1%BB%91ng)
2. [AimModel: 6 Rotation Features](#2-aimmodel-6-rotation-features)
3. [ClickModel: 5 Click Features](#3-clickmodel-5-click-features)
4. [SessionModel: 8 Session Features](#4-sessionmodel-8-session-features)
5. [Ping Normalization & Runtime Context](#5-ping-normalization--runtime-context)
6. [Derived Features cho LightGBM](#6-derived-features-cho-lightgbm)
7. [Feature Extraction Pipeline (Code-Level)](#7-feature-extraction-pipeline-code-level)
8. [Feature Importance Analysis](#8-feature-importance-analysis)
9. [So sánh Feature Extraction: Local vs Cloud](#9-so-s%C3%A1nh-feature-extraction-local-vs-cloud)
10. [Edge Cases & Failure Modes](#10-edge-cases--failure-modes)
11. [Behavioral Traps (Cross-Correlation Features)](#11-behavioral-traps-cross-correlation-features)
12. [Adaptive Baseline & Online Learning](#12-adaptive-baseline--online-learning)
13. [Phụ lục: Feature Matrix](#13-ph%E1%BB%A5-l%E1%BB%A5c-feature-matrix)

---

## 1. Tổng quan hệ thống

### Kiến trúc ML Pipeline

```
Game Thread (50ms/tick)
  │
  ├── FeatureBridge.tick()              ← Thu thập raw features mỗi tick
  │     ├── FeatureVector (per-tick)
  │     ├── FeatureSnapshot Deque (64 ticks rolling window)
  │     ├── CombatSnapshot Deque (32 attacks)
  │     └── ClickSnapshot Deque (50 clicks)
  │
  ├── computeProvisionalRisk()          ← Heuristic fallback (cap 0.70)
  │     ├── Click risk (cooldown, entropy)
  │     ├── Aim risk (4-metric weighted)
  │     ├── Auto-jump risk
  │     ├── Cross-correlation risk
  │     └── TriggerBot risk
  │
  └── submitMLInference()               ← Async ML qua BoundedMLQueue
        ├── AimModel (GBDT 30 trees)    ← 6 features
        ├── ClickModel (OnlineLogReg)   ← 5 features
        └── SessionModel (Ensemble 5)   ← 8 features
              │
              ▼
        FusionEngine.setBlackboxRisk(category, risk)
              │
              ▼
        Fusion Policy → Alert / Mitigation / Enforce
```

### Ba Model ML

| Model | Algorithm | Features | Output Range | Fallback |
|-------|-----------|----------|--------------|----------|
| AimModel | GBDT (30 trees, depth 4) | 6 rotation | [0.0, 0.985] | OnlineLogReg (6 features) |
| ClickModel | Online Logistic Regression | 5 click | [0.0, 0.985] | None (heuristic) |
| SessionModel | Ensemble of 5 Logistic Regression | 8 session | [0.0, 0.85] | OnlineLogReg (8 features) |

### Lưu ý quan trọng từ codebase

1. **ClickModel có 2 phiên bản feature naming**: Trong `ClickModel.java`, method `predict()` overload có parameter names là `cps, intervalStd, clickEntropy, burstRatio, fftDominant` (1.8-era), nhưng `extractClickFeatures()` trong `MLModelManager` thực tế extract 5 features 1.9+: `cooldownAccuracy, missRatio, hitMissRatio, criticalRatio, perfectStreak`. Đây là một **inconsistency** cần được resolve khi training.

2. **SessionModel**: Feature naming trong code cũ (ML_MODELS_DETAILED.md) khác với implementation thực tế. Implementation thật có `mouseSensitivity, pitchDeltaMean, yawDeltaMean` thay vì `avgHitDistance, hitDistanceStd`. Document này phân tích dựa trên **implementation thật**.

---

## 2. AimModel: 6 Rotation Features

### Tổng quan

AimModel phát hiện aim assist, kill aura, smooth aim thông qua phân tích rotation pattern.
Input: 6 features, Output: GBDT ensemble (30 trees, depth 4) + OnlineLogReg fallback.

```
yawJerkStd     ───┐
pitchJerkStd   ───┤
aimSmoothness  ───┤──► GBDT (30 trees, depth 4) ──► sigmoid ──► risk [0, 0.985]
rotationEntropy───┤
gcdError       ───┤
snapFreq       ───┘
```

### 2.1 yawJerkStd

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Standard deviation of yaw jerk (second derivative of yaw) |
| **Công thức** | `stddev(abs(yawDelta[t] - yawDelta[t-1]))` over 64-tick window |
| **Đơn vị** | degrees/tick^2 |
| **Khoảng giá trị** | [0.0, ~1.0+] |
| **Human typical** | 0.5 - 1.5+ |
| **Cheat typical** | 0.05 - 0.4 |
| **Vai trò** | Feature chính cho aim assist detection |

**Cách tính (FeatureBridge.java line 514-532)**:
```java
double[] deltas = new double[featureHistory.size() - 1];
for (int i = 1; i < arr.length; i++) {
    deltas[i - 1] = Math.abs(arr[i].getYawDelta() - arr[i - 1].getYawDelta());
}
// Tính mean của first differences (đây là jerk)
// Sau đó tính stddev của các jerk values
```

**Giải thích**:
- Yaw jerk là tốc độ thay đổi của yaw acceleration (đạo hàm bậc 3 của góc xoay)
- Khi aim assist hoạt động, nó smooth rotation → jerk rất thấp và ổn định → stddev thấp
- Human aim tự nhiên có jerk không đều → stddev cao

**Ping Normalization** (MLModelManager.java line 127):
```java
double pingNorm = Math.max(1.0, Math.sqrt(ping / 50.0));
yawJerkStd /= pingNorm;  // Chia cho sqrt(ping/50)
```
- Ping cao làm rotation updates thưa hơn → jerk tự nhiên thấp hơn → dễ false positive
- Normalize bằng `sqrt(ping/50)`: ping 50ms → factor 1.0; ping 200ms → factor 2.0

**False positive scenarios**:
- Player có sensitivity rất thấp (rotation changes chậm và đều)
- Cinematic mode / smooth camera mods
- Player đang AFK hoặc idle
- High ping > 200ms (đã có normalize nhưng vẫn có thể gây FP)

**Tương quan với các feature khác**:
- Tương quan âm mạnh với `aimSmoothness` (càng smooth → jerk càng thấp)
- Tương quan dương với `rotationEntropy` (jerk cao → patterns phong phú → entropy cao)

### 2.2 pitchJerkStd

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Standard deviation of pitch jerk |
| **Công thức** | `stddev(abs(pitchDelta[t] - pitchDelta[t-1]))` |
| **Đơn vị** | degrees/tick^2 |
| **Khoảng giá trị** | [0.0, ~0.8] |
| **Human typical** | 0.3 - 0.6 |
| **Cheat typical** | 0.05 - 0.2 |

**Cách tính**: Hoàn toàn tương tự `yawJerkStdDev()` nhưng dùng pitchDelta thay vì yawDelta.

**Khác biệt với yawJerkStd**:
- Pitch thường có biên độ nhỏ hơn yaw (player xoay ngang nhiều hơn xoay dọc)
- Pitch movement ít đa dạng hơn → stddev thường thấp hơn
- Vẫn quan trọng để phát hiện aim assist ở cả 2 trục

**Khi nào feature này weak**:
- Player aim mostly horizontally (pitch gần như không đổi)
- Build battle (pitch thay đổi liên tục khi nhìn lên/xuống)

### 2.3 aimSmoothness

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Lag-1 autocorrelation of consecutive yaw deltas |
| **Công thức** | `mean(abs(yawDelta[t] * yawDelta[t+1]) / (abs(yawDelta[t]) * abs(yawDelta[t+1])))` |
| **Khoảng giá trị** | [0.0, 1.0] |
| **Human typical** | 0.4 - 0.75 |
| **Cheat typical** | 0.85 - 0.99 |

**Cách tính (FeatureBridge.java line 593-608)**:
```java
for (int i = 0; i < arr.length - 1; i++) {
    double d1 = arr[i].getYawDelta();
    double d2 = arr[i + 1].getYawDelta();
    if (d1 > 0.001 && d2 > 0.001) {
        totalCorrelation += (d1 * d2) / (Math.abs(d1) * Math.abs(d2));
        count++;
    }
}
```

**Giải thích chi tiết**:
- Đây thực chất là normalized cross-correlation: `corr = mean(cos(theta))` giữa các consecutive yaw deltas
- Khi d1 và d2 cùng dấu → tích dương → smoothness cao
- Khi d1 và d2 trái dấu → smoothness thấp (human aim overshoot liên tục)
- **Aim assist**: rotation thay đổi rất mượt, các delta kế tiếp gần như cùng hướng → smoothness cao

**Tại sao threshold 0.85?**:
- Skilled 1.9+ PvP player: smoothness tối đa ~0.75 khi tracking đối thủ
- Trigger ở 0.85 đảm bảo chỉ aim assist/smooth aim bị flag
- Weight trong heuristic: 30%

**False positive scenarios**:
- Tracking mục tiêu di chuyển chậm, đều (e.g., nhìn theo một player chạy đường thẳng)
- Cinema mode / smooth camera
- Mouse với polling rate thấp (125Hz)

### 2.4 rotationEntropy

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Shannon entropy of yaw delta distribution |
| **Công thức** | `-sum(p * log2(p))` với p là probability của mỗi bin |
| **Khoảng giá trị** | [0.0, ~7.5] bits |
| **Human typical** | 5.0 - 7.0 bits |
| **Cheat typical** | 2.0 - 4.0 bits |

**Cách tính (FeatureBridge.java line 615-633)**:
```java
for (FeatureSnapshot s : arr) {
    int bucket = (int) (Math.abs(s.getYawDelta()) * 50);  // 50 bins per degree
    bins.merge(bucket, 1, Integer::sum);
}
// entropy = -sum(p * log2(p)) for all bins
```
- 50 bins per degree → resolution 0.02 degrees
- Window: featureHistory (64 ticks)

**Giải thích**:
- Human aim có yaw delta distribution gần như uniform → entropy cao (~5-7 bits)
- Aim assist tạo ra các yaw delta lặp đi lặp lại → distribution có peaks → entropy thấp
- Càng ít bins được dùng → entropy càng thấp

**Ví dụ cụ thể**:
- Human: yaw deltas {0.1, 0.3, 0.05, 0.8, 0.2, 0.4, ...} → phân bố đều 6 bins → entropy ~5.8 bits
- Aim assist: yaw deltas {0.1, 0.1, 0.15, 0.1, 0.15, 0.1, ...} → tập trung 2-3 bins → entropy ~2.5 bits

**False positive**:
- AFK players (rotation không đổi → entropy 0, nhưng feature khác cũng 0 → risk thấp)
- Player ngắm bắn cung / bow (yaw delta rất thấp)
- Player stand still (không combat → không dangerous)

### 2.5 gcdError

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | GCD (Greatest Common Divisor) error - deviation from 0.5-degree grid |
| **Công thức** | `mean(abs(yawDelta % 0.5 - nearest_0.5_multiple))` |
| **Khoảng giá trị** | [0.0, 0.25] |
| **Human typical** | 0.05 - 0.25 |
| **Cheat typical** | 0.001 - 0.02 |

**Cách tính (FeatureBridge.java line 742-759)**:
```java
for (FeatureSnapshot s : arr) {
    double delta = Math.abs(s.getYawDelta());
    if (delta > 0.01) {
        double remainder = delta % 0.5;       // distance from grid
        if (remainder > 0.25) remainder = 0.5 - remainder;  // nearest distance
        errorSum += remainder;
        count++;
    }
}
```
- Grid size 0.5 degrees — đây là threshold chuẩn cho Minecraft GCD analysis
- Remainder > 0.25 → distance to nearest neighbor = 0.5 - remainder

**Giải thích**:
- Minecraft rotation angle dùng float (32-bit) với precision hạn chế
- Aim assist thường snap angles đến discrete grid (0.5-degree multiples)
- Human rotation không tự nhiên snap → deviation from grid cao hơn

**Khoa học đằng sau GCD**:
- Minecraft store yaw/pitch as float (IEEE 754)
- Khi aim assist chỉnh góc, nó thường set angle = round(angle / 0.5) * 0.5
- Human mouse movement tạo ra arbitrary float values

**Điều kiện borderline**:
- Player có sensitivity là bội số của 0.5 → natural GCD alignment → false positive
- Solution: dùng combined với các feature khác, không standalone

### 2.6 snapFreq

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Frequency of sudden rotation changes exceeding threshold |
| **Công thức** | `count(anomalies) / (window_size - 2)` |
| **Khoảng giá trị** | [0.0, 1.0] |
| **Human typical** | 0.0 - 0.1 |
| **Cheat typical** | 0.2 - 0.8 |

**Cách tính**: Đơn giản gọi `computeAccelerationAnomaly()` (FeatureBridge.java line 639-652).

```java
for (int i = 1; i < arr.length - 1; i++) {
    double prev = arr[i - 1].getYawDelta();
    double curr = arr[i].getYawDelta();
    double next = arr[i + 1].getYawDelta();
    if (curr > prev * 1.5 && curr > next * 1.5) anomalies++;
}
```

**Giải thích**:
- Snap event = yaw delta hiện tại lớn hơn 1.5x cả 2 neighbor
- Đây là signature của aim bot: rotation đột ngột jump đến target
- Human aim hiếm khi có snap (trừ khi flick shot — nhưng flick shot rất hiếm trong PvP)

**False positive**:
- Lag spike (rotation updates bị delayed → sudden jump khi packets đến)
- Player quay ngoắt 180 độ khi nghe tiếng động (có thể là legitimate)
- Mouse lift-off và reposition

### 2.7 Tổng hợp Aim Feature Interactions

```
yawJerkStd ↓ + aimSmoothness ↑ + rotationEntropy ↓ + gcdError ↓ = Aim Assist với độ chắc chắn cao
snapFreq ↑ + yawJerkStd ↑ = AimBot (snap + jerk không ổn định)
yawJerkStd ↓ + pitchJerkStd ↑ = Chỉ aim assist ngang (horizontal aim assist)
Tất cả features ≈ 0 = AFK / idle → risk thấp
```

### 2.8 Heuristic Weights (FeatureBridge.computeAimRiskScore)

| Metric | Weight | Human Range | Suspicious Threshold | Contribution |
|--------|--------|-------------|---------------------|-------------|
| Smoothness | 30% | 0.4-0.75 | > 0.85 | `(smoothness - 0.75) * 0.30` |
| Jerk StdDev | 25% | 0.5-1.5 | < 0.4 | `(1.0 - yawJerk / 0.4) * 0.25` |
| Rotation Entropy | 25% | 5-7 bits | < 4.0 bits | `(1.0 - entropy / 4.0) * 0.25` |
| Acceleration Anomaly | 20% | 0.05-0.08 | > 0.2 | `min(anomaly, 1.0) * 0.20` |

---

## 3. ClickModel: 5 Click Features

### Tổng quan

ClickModel phát hiện autoclicker và các dạng automated click pattern.
Input: 5 features, Output: Online Logistic Regression.

> **CRITICAL NOTE**: `ClickModel.java` có inconsistency. Method `predict()` overload dùng tên `cps, intervalStd, clickEntropy, burstRatio, fftDominant` (1.8 cũ), nhưng `extractClickFeatures()` trong `MLModelManager` thực tế extract 5 features cho 1.9+ PVP. Cần resolve khi train — implementation thật dùng 5 features 1.9+.

### 3.1 cooldownAccuracy

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | How precisely attack timing matches weapon cooldown (1.9+) |
| **Công thức** | `max(0, 1.0 - avg_error / 200.0)`, capped at 0.98 |
| **Khoảng giá trị** | [0.0, 0.98] |
| **Human typical** | 0.3 - 0.75 |
| **Cheat typical** | 0.85 - 0.98 |

**Cách tính (FeatureBridge.java line 801-833)**:
```java
double cooldownMs = 1000.0 / attackSpeed;  // Sword 1.6 → 625ms, Axe 1.0 → 1000ms
for (int i = 1; i < arr.length; i++) {
    long intervalMs = (arr[i].getTimestamp() - arr[i-1].getTimestamp()) / 1_000_000L;
    double error = Math.abs(intervalMs - cooldownMs);
    totalError += error;
    count++;
}
double avgError = totalError / count;
return Math.min(0.98, Math.max(0, 1.0 - avgError / 200.0));
```

**Ý nghĩa**:
- Minecraft 1.9+ có attack cooldown (khác nhau theo weapon type)
- Human click không thể đều exactly cooldown → avg error ~50-100ms → accuracy 0.5-0.75
- AutoClicker click exactly khi cooldown reset → error < 5ms → accuracy 0.97-0.98

**Cooldown theo weapon**:
| Weapon | Attack Speed | Cooldown | Accuracy tại error 25ms |
|--------|-------------|----------|------------------------|
| Sword | 1.6 | 625ms | 0.875 |
| Axe | 1.0 | 1000ms | 0.875 |
| Pickaxe | 1.2 | 833ms | 0.875 |
| Shovel | 1.0 | 1000ms | 0.875 |
| Fist | 4.0 | 250ms | 0.875 |
| Trident | 1.1 | 909ms | 0.875 |

**False positive**:
- Player có timing rất tốt (skill issue, rhythm gamers)
- Network smoothing làm interval errors artificially thấp

### 3.2 missRatio

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Fraction of attack opportunities missed |
| **Công thức** | `min(1.0, raw_miss_ratio * 10.0)` |
| **Khoảng giá trị** | [0.0, 1.0] |
| **Human typical** | 0.3 - 0.7 (normalized) |
| **Cheat typical** | 0.0 - 0.1 (normalized) |

**Cách tính (FeatureBridge.java line 850-886)**:
```java
for (int i = 1; i < arr.length; i++) {
    long gap = arr[i].getTimestamp() - arr[i - 1].getTimestamp();
    if (gap > cooldownNs * 1.5) {
        opportunities++;
        missed++;
    }
}
double rawRatio = (double) missed / opportunities;
return Math.min(1.0, rawRatio * 10.0);  // Normalize
```
- Gap > 1.5x cooldown = missed opportunity (người chơi đã có thể attack nhưng không attack)
- Normalization: raw 0.01 → 0.1; raw 0.05 → 0.5; raw 0.10 → 1.0

**Ý nghĩa**:
- Human: miss 5-15% opportunities → raw 0.05-0.15 → normalized 0.5-1.0
- AutoClicker: miss < 1% → raw < 0.01 → normalized < 0.1
- Càng thấp càng suspicious

### 3.3 hitMissRatio

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Hit-to-miss ratio over combat window |
| **Công thức** | `combatHistory.size() / clickHistory.size()` |
| **Khoảng giá trị** | [0.0, 1.0] |
| **Human typical** | 0.3 - 0.8 |
| **Cheat typical** | 0.8 - 1.0 |

**Cách tính (FeatureBridge.java line 897-904)**:
```java
double ratio = (double) totalHits / totalSwings;
return Math.min(1.0, Math.max(0.0, ratio));
```

**Ý nghĩa**:
- Tỉ lệ hits (combatHistory) trên swings (clickHistory)
- Human miss thường xuyên do strafing, knockback → hit rate 60-80%
- AutoClicker hoặc KillAura: hit rate 95-100% (chỉ click khi target trong range)

**False positive**:
- Player camping trong corner với target trong range liên tục
- 1v1 fight không có knockback đáng kể

### 3.4 criticalRatio

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Fraction of attacks made while sprint-jumping (crit-eligible) |
| **Công thức** | `critEligibleCount / totalSprintingAttacks` |
| **Khoảng giá trị** | [0.0, 1.0] |
| **Human typical** | 0.1 - 0.65 |
| **Cheat typical** | 0.7 - 1.0 |

**Cách tính (FeatureBridge.java line 918-937)**:
```java
for (CombatSnapshot snap : combatHistory) {
    if (snap.isAttackerSprinting()) {
        total++;
        if (!snap.isAttackerOnGround()) {  // Sprint-jumping = crit eligible
            critEligible++;
        }
    }
}
```

**Ý nghĩa**:
- Trong 1.9+, critical hit cần sprint-jump (không trên ground + sprinting)
- Skilled player: 40-65% attacks là crit-eligible (jump strategically)
- KillAura/autoclicker bot: 70-100% (luôn sprint-jump để maximize damage)
- Casual player: 10-30%

**False positive**:
- Player chơi Kit PvP luôn sprint-jump (Hypixel Skywars style)
- Player không biết về cơ chế critical hit nhưng vô tình jump nhiều

### 3.5 perfectStreak

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Longest consecutive attacks matching perfect cooldown |
| **Công thức** | Max streak of attacks within 5% tolerance of cooldown |
| **Khoảng giá trị** | [0, 50+] |
| **Human typical** | 1 - 8 |
| **Cheat typical** | 12 - 50+ |

**Cách tính (FeatureBridge.java line 951-985)**:
```java
long toleranceNs = Math.max((long) (cooldownNs * 0.05), 25_000_000L);  // 5% or 25ms min
for (int i = 1; i < arr.length; i++) {
    long gap = arr[i].getTimestamp() - arr[i - 1].getTimestamp();
    long deviation = Math.abs(gap - cooldownNs);
    if (deviation <= toleranceNs) {
        currentStreak++;
    } else {
        // Check double-hit: gap ~2x cooldown (missed one cycle, then perfect)
        if (Math.abs(gap - 2 * cooldownNs) <= toleranceNs) {
            currentStreak = Math.max(currentStreak - 1, 0);
        } else {
            currentStreak = 0;
        }
    }
}
```

**Giải thích chi tiết**:
- Tolerance = 5% cooldown, minimum 25ms (network jitter floor)
- Sword (625ms): tolerance = 31ms
- Axe (1000ms): tolerance = 50ms
- Double-hit handling: nếu gap = 2x cooldown, coi như miss 1 hit nhưng streak vẫn tiếp tục (giảm 1)
- Skilled human max ~8 consecutive perfect hits
- Suspicion threshold: 12+
- AutoClicker: 20+ (thường xuyên đạt 30-50)

### 3.6 ClickModel Feature Interactions

```
cooldownAccuracy ↑ + missRatio ↓ + perfectStreak ↑ = AutoClicker gần như chắc chắn
criticalRatio ↑ + hitMissRatio ↑ = KillAura với auto-crit
perfectStreak > 20 = AutoClicker (không cần feature khác)
cooldownAccuracy cao nhưng clickHistory nhỏ = cần thêm data
```

---

## 4. SessionModel: 8 Session Features

### Tổng quan

SessionModel phát hiện ghost client, legit aura, và behavioral drift dài hạn.
Input: 8 features, Output: Ensemble of 5 OnlineLogReg units (weighted average).

```
cooldownAccuracy        ───┐
missRatio               ───┤
mouseSensitivity        ───┤
pitchDeltaMean          ───┤──► EnsembleMember[0] ──┐
yawDeltaMean            ───┤──► EnsembleMember[1] ──┤
gcdConsistency          ───┤──► EnsembleMember[2] ──┤──► average ──► sigmoid ──► risk
rotationEntropy         ───┤──► EnsembleMember[3] ──┤
normalizedSessionDuration───┘──► EnsembleMember[4] ──┘
```

### 4.1 cooldownAccuracy

(Tương tự ClickModel feature 3.1)
- Dùng lại feature từ click analysis nhưng trong context session
- Ở session level, cooldownAccuracy trung bình qua nhiều combat sessions cho thấy consistency pattern

### 4.2 missRatio

(Tương tự ClickModel feature 3.2)
- Session-level aggregation: pattern duy trì qua nhiều phút
- Một player có missRatio thấp trong 1 combat có thể là may mắn
- Nhưng missRatio thấp trong 30+ phút → rất suspicious

### 4.3 mouseSensitivity

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Normalised mouse sensitivity from pitch/yaw ratio |
| **Công thức** | `pitchDeltaMean / yawDeltaMean` (capped [0, 1]) |
| **Khoảng giá trị** | [0.0, 1.0] |
| **Human typical** | 0.2 - 0.8 |
| **Cheat typical** | Giống human (không phải signal mạnh) |

**Cách tính (FeatureBridge.java line 991-1006)**:
```java
double yawMean = yawSum / arr.length;
double pitchMean = pitchSum / arr.length;
if (yawMean < 0.001) return 0.5;
return Math.min(1.0, Math.max(0.0, pitchMean / yawMean));
```

**Ý nghĩa**:
- Tỉ lệ pitch movement / yaw movement
- Player có sensitivity bằng nhau ở 2 axis → ratio ≈ 1.0
- Player aim ngang nhiều hơn → ratio < 0.5
- **Không phải feature phát hiện cheat trực tiếp** — là context feature giúp model hiểu behavior baseline

**Tại sao feature này quan trọng**:
- Giúp model phân biệt: "player này pitch movement thấp vì sensitivity thấp → rotation entropy thấp là natural"
- Là confounder control: kiểm soát variation do sensitivity, không do cheat

### 4.4 pitchDeltaMean

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Mean absolute pitch delta per tick |
| **Công thức** | `mean(abs(pitchDelta))` over featureHistory |
| **Khoảng giá trị** | [0.0, ~5.0+] |
| **Human typical** | 0.5 - 3.0 |
| **Cheat typical** | < 0.3 (aim assist) hoặc > 5.0 (kill aura velocity) |

### 4.5 yawDeltaMean

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Mean absolute yaw delta per tick |
| **Công thức** | `mean(abs(yawDelta))` over featureHistory |
| **Khoảng giá trị** | [0.0, ~10.0+] |

**Cách tính (FeatureBridge.java line 1025-1034)**: Tương tự pitchDeltaMean nhưng cho yaw.

**Ý nghĩa**:
- Baseline rotation speed của player
- Yaw delta thường cao hơn pitch delta (player xoay ngang nhiều hơn)
- Giúp model hiểu activity level và playstyle

### 4.6 gcdConsistency

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Inverse of computeGcdError(), mapped to [0, 1] |
| **Công thức** | `max(0, 1.0 - gcdError * 4)` |
| **Khoảng giá trị** | [0.0, 1.0] |
| **Human typical** | 0.0 - 0.6 |
| **Cheat typical** | 0.9 - 1.0 |

**Cách tính (FeatureBridge.java line 1041-1044)**:
```java
double error = computeGcdError();
return Math.max(0, 1.0 - error * 4);
```
- gcdError = 0.25 → gcdConsistency = 0.0 (hoàn toàn random)
- gcdError = 0.01 → gcdConsistency = 0.96 (rất consistent = suspicious)

### 4.7 rotationEntropy

(Tương tự AimModel feature 2.4 nhưng ở session scale)
- Ở session level, dùng window dài hơn (nhiều ticks hơn) để tính entropy
- Entropy thấp kéo dài → strong signal

### 4.8 normalizedSessionDuration

| Thuộc tính | Giá trị |
|------------|---------|
| **Tên đầy đủ** | Session duration normalised to [0, 1] |
| **Công thức** | `min(1.0, elapsedMs / 3_600_000)` |
| **Khoảng giá trị** | [0.0, 1.0] |
| 1 hour → | 1.0 |
| 30 min → | 0.5 |

**Cách tính (FeatureBridge.java line 1050-1053)**:
```java
long elapsed = System.currentTimeMillis() - sessionStartTime;
return Math.min(1.0, elapsed / 3_600_000.0);
```

**Ý nghĩa**:
- Context feature: behavioral drift theo thời gian
- Player mới join (sessionDuration thấp) có ít data → model nên thận trọng
- Player đã chơi lâu (sessionDuration cao) có behavioral pattern ổn định → prediction đáng tin hơn

**Tại sao cần feature này**:
- Một số cheat chỉ bật sau khi chơi được 1 lúc (để tránh detection ngay khi join)
- Session duration feature giúp model capture behavioral change points
- Model có thể học: "nếu feature X thay đổi đột ngột sau Y phút → suspicious"

### 4.9 SessionModel Feature Interactions

```
gcdConsistency ↑ + rotationEntropy ↓ + cooldownAccuracy ↑ = Ghost Client / Legit Aura
mouseSensitivity + pitchDeltaMean + yawDeltaMean = Baseline playstyle (confounder control)
normalizedSessionDuration × other features = Temporal confidence weighting
```

---

## 5. Ping Normalization & Runtime Context

### 5.1 Ping Normalization Factor

Trong `MLModelManager.extractAimFeatures()`:

```java
double pingNorm = Math.max(1.0, Math.sqrt(ping / 50.0));
yawJerkStd /= pingNorm;
pitchJerkStd /= pingNorm;
```

| Ping | sqrt(ping/50) | Hiệu ứng |
|------|---------------|----------|
| 0-50ms | ~1.0 | Không thay đổi |
| 100ms | ~1.41 | Jerk giảm ~29% |
| 200ms | ~2.0 | Jerk giảm ~50% |
| 300ms | ~2.45 | Jerk giảm ~59% |

**Tại sao dùng sqrt?**:
- Rotation updates phụ thuộc vào movement packets, frequency tỉ lệ với ping
- Nhưng không phải linear — dùng sqrt là approximation tốt
- ping 50ms = 20 ticks/s → 20 rotation updates
- ping 200ms = 5 ticks/s → 5 rotation updates → jerk stddev tự nhiên thấp hơn

### 5.2 Jitter-based Weighting (Ping Factor)

Khác với ping normalization ở feature extraction, `getPingFactor()` trong FeatureBridge dùng **jitter** (biến động ping) để giảm weight của heuristic risk:

```java
public double getPingFactor() {
    long jitter = lagProfile.getJitter();
    if (jitter < 20) return 1.0;      // Ping ổn định
    if (jitter > 80) return 0.2;      // Lag spike → feature không đáng tin
    return 1.0 - (jitter - 20) * 0.8 / 60.0;
}
```

| Jitter (ms) | Factor | Ý nghĩa |
|-------------|--------|---------|
| < 20 | 1.0 | Feature đáng tin |
| 30 | 0.87 | Giảm nhẹ |
| 50 | 0.60 | Giảm vừa |
| 80+ | 0.20 | Feature không đáng tin |

> **Quan trọng**: Factor này chỉ áp dụng cho heuristic risk (computeProvisionalRisk). ML model tự học ping normalization thông qua features (cooldownAccuracy đã bị ảnh hưởng bởi ping).

### 5.3 Lag Profile

`LagProfile` trong FeatureBridge tracking:

| Field | Nguồn | EWMA decay | Mục đích |
|-------|-------|------------|----------|
| avgPing | Transaction ping | 0.9 | Smoothed RTT |
| jitter | |ping - avgPing|| N/A | Network stability |
| packetLoss | PacketStateData | N/A | Connection quality |

---

## 6. Derived Features cho LightGBM

> LightGBM là tree-based model → KHÔNG cần feature normalization.
> Nhưng derived features vẫn cải thiện accuracy bằng cách cung cấp inductive bias.

### 6.1 Runtime Context Features

```python
# Ping stability context
features['ping_bucket'] = pd.cut(df['ping'], bins=[0, 50, 100, 200, 300, 9999], labels=False)
# 0: <50ms (excellent), 1: 50-100ms (good), 2: 100-200ms (ok), 3: 200-300ms (laggy), 4: >300ms (very laggy)

# TPS quality indicator
features['tps_quality'] = (df['tps'] - 15) / 5  # 15-20 → 0.0-1.0

# Binary flags
features['high_jitter'] = (df['jitter'] > 50).astype(int)
features['is_pre_19'] = (df['client_version'] < '1.9').astype(int)
features['is_mobile'] = (df['client_type'] == 'geyser').astype(int)
```

### 6.2 Interaction Features

```python
# Ping-adjusted jerk (LightGBM tự học cái này, nhưng explicit giúp tree depth thấp hơn)
features['yaw_jerk_adj'] = df['yawJerkStd'] * (1.0 / (df['ping'] / 50 + 1))
features['pitch_jerk_adj'] = df['pitchJerkStd'] * (1.0 / (df['ping'] / 50 + 1))

# Smoothness-entropy interaction (low entropy + high smoothness = very suspicious)
features['smoothness_x_entropy'] = df['aimSmoothness'] * (7.0 - df['rotationEntropy']) / 7.0

# GCD-Smoothness product (grid snap + smooth aim = aim assist)
features['gcd_x_smoothness'] = (1.0 - df['gcdError']) * df['aimSmoothness']

# Cooldown accuracy adjusted by ping
features['cooldown_x_ping'] = df['cooldownAccuracy'] * (1.0 / (df['ping'] / 50 + 1))
```

### 6.3 Ratio Features

```python
# Jerk ratio (pitch/yaw): phát hiện aim assist chỉ ở 1 trục
features['jerk_ratio'] = df['pitchJerkStd'] / (df['yawJerkStd'] + 1e-6)

# Click consistency: perfect streak / total clicks
features['streak_ratio'] = df['perfectStreak'] / (df['totalClicks'] + 1)

# Activity level
features['combat_activity'] = df['combatHistorySize'] / (df['sessionTicks'] / 20.0)
```

### 6.4 Statistical Features

```python
# Rolling statistics (cần tính trên window)
features['yaw_jerk_zscore'] = (df['yawJerkStd'] - df['yawJerkStd_baseline']) / (df['yawJerkStd_baseline_std'] + 1e-6)
features['cps_zscore'] = (df['cps'] - df['cps_baseline']) / (df['cps_baseline_std'] + 1e-6)
```

### 6.5 Khi nào dùng derived features?

| Tình huống | Derived feature | Impact |
|------------|----------------|--------|
| Training data ít (< 10K samples) | Dùng nhiều derived, ít raw | Giúp model generalize |
| Training data nhiều (> 100K) | Dùng raw + 1-2 interaction | Model tự học |
| High ping players > 200ms | ping_bucket, ping-adjusted features | Giảm false positive |
| Cross-version (1.8 + 1.9+) | is_pre_19 flag | Version-specific thresholds |

---

## 7. Feature Extraction Pipeline (Code-Level)

### 7.1 Data Flow

```
FeatureBridge.tick() (50ms intervals)
  │
  ├── currentFeatures.yawDelta = Math.abs(player.yaw - player.lastYaw)
  ├── currentFeatures.pitchDelta = Math.abs(player.pitch - player.lastPitch)
  ├── currentFeatures.pingMs = player.getTransactionPing()
  ├── currentFeatures.tps = GrimAPI.INSTANCE.getPlatformServer().getTPS()
  │
  ├── FeatureSnapshot → featureHistory Deque (max 64)
  ├── updateLagProfile()
  ├── updateBaseline() [every 60s]
  └── computeProvisionalRisk() [heuristic fallback]

FeatureBridge.onAttack() (per attack packet)
  │
  ├── CombatSnapshot → combatHistory Deque (max 32)
  ├── rotationAtAttack ArrayList (max 100) ← yaw delta tại thời điểm attack
  └── currentFeatures.lastHitDistance, lastHitAngle

FeatureBridge.onSwing() (per swing packet)
  │
  └── ClickSnapshot → clickHistory Deque (max 50)
      └── CPS tính real-time từ clickHistory

submitMLInference() [every tick, if data enough]
  │
  ├── AimModel: combatHistory.size >= 3
  │     └── extractAimFeatures(fb) → float[6]
  │
  ├── ClickModel: clickHistory.size >= 5
  │     └── extractClickFeatures(fb) → float[5]
  │
  └── SessionModel: every 100 ticks && featureHistory.size >= 20
        └── extractSessionFeatures(fb) → float[8]
```

### 7.2 Feature Vector Size

| Component | Size (bytes) | Gồm |
|-----------|-------------|-----|
| Aim features | 6 × 4 = 24 | 6 floats |
| Click features | 5 × 4 = 20 | 5 floats |
| Session features | 8 × 4 = 32 | 8 floats |
| Total per inference | ~76 bytes | |
| + Ping context | 2 × 4 = 8 | pingMs, jitter |
| + Version info | ~4 | client version code |
| **Total per request** | **~100 bytes** | |

Đây là kích thước rất nhỏ — phù hợp cho cả local và cloud inference.

### 7.3 Thread Safety Architecture

```
Game Thread (writes)            ML Worker Thread (reads)
  │                                   │
  ├── featureHistory.add()            ├── featureHistory.toArray()
  ├── combatHistory.add()             ├── combatHistory.toArray()
  ├── clickHistory.add()              └── clickHistory.toArray()
  └── rotationAtAttack.add()
        │
  ConcurrentLinkedDeque ──── thread-safe deques ──── read không lock
  ArrayList + only game thread writes ──── rotationAtAttack chỉ đọc trong ML thread
```

**Why ConcurrentLinkedDeque?**
- ArrayDeque không thread-safe
- `synchronized` sẽ block game thread
- ConcurrentLinkedDeque: lock-free, dùng CAS operations
- Trade-off: tốn memory hơn ArrayDeque ~2x

---

## 8. Feature Importance Analysis

### 8.1 Expected Feature Importance (AimModel)

Dựa trên heuristic weights và domain knowledge, expected importance:

| Rank | Feature | Expected Gain Importance | Lý do |
|------|---------|-------------------------|-------|
| 1 | aimSmoothness | ~30% | Strongest single signal |
| 2 | yawJerkStd | ~25% | Capture jerk variance |
| 3 | rotationEntropy | ~20% | Distribution signature |
| 4 | gcdError | ~15% | Grid alignment |
| 5 | snapFreq | ~5% | Rare event, but specific |
| 6 | pitchJerkStd | ~5% | Redundant với yawJerkStd |

### 8.2 Expected Feature Importance (ClickModel)

| Rank | Feature | Expected Weight | Lý do |
|------|---------|----------------|-------|
| 1 | cooldownAccuracy | ~35% | Core autoclicker signal |
| 2 | perfectStreak | ~25% | Sustained perfect timing |
| 3 | missRatio | ~20% | Complement cho cooldownAccuracy |
| 4 | criticalRatio | ~15% | AutoCrit detection |
| 5 | hitMissRatio | ~5% | Noisy, phụ thuộc map/game mode |

### 8.3 Expected Feature Importance (SessionModel)

| Rank | Feature | Expected Weight | Lý do |
|------|---------|----------------|-------|
| 1 | gcdConsistency | ~25% | Strongest at session level |
| 2 | rotationEntropy | ~20% | Distribution over long window |
| 3 | cooldownAccuracy | ~20% | Sustained pattern |
| 4 | missRatio | ~15% | Consistency metric |
| 5 | mouseSensitivity | ~5% | Confounder control |
| 6 | yawDeltaMean | ~5% | Activity level |
| 7 | pitchDeltaMean | ~5% | Activity level |
| 8 | normalizedSessionDuration | ~5% | Temporal weighting |

### 8.4 Code for Feature Importance Analysis

```python
import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np

def analyze_feature_importance(model_path: str, feature_names: list, importance_type: str = 'gain'):
    """
    Phân tích feature importance từ trained LightGBM model.
    
    Args:
        model_path: Path to .txt model file
        feature_names: List of feature names in order
        importance_type: 'gain' (default) | 'split' | 'weight'
    """
    model = lgb.Booster(model_file=model_path)
    importance = model.feature_importance(importance_type=importance_type)
    total = importance.sum()
    
    print(f"\n=== Feature Importance ({importance_type}) ===")
    print(f"{'Feature':30s} {'Importance':>12s} {'%':>8s}")
    print("-" * 52)
    
    sorted_pairs = sorted(
        zip(feature_names, importance), 
        key=lambda x: -x[1]
    )
    
    for name, imp in sorted_pairs:
        pct = imp / total * 100 if total > 0 else 0
        bar = "#" * int(pct / 2)
        print(f"{name:30s} {imp:12.4f} {pct:7.1f}% {bar}")
    
    return sorted_pairs

def plot_feature_importance(pairs, title="Feature Importance", top_n=20):
    """Plot feature importance bar chart."""
    names, scores = zip(*pairs[:top_n])
    total = sum(scores)
    percentages = [s/total*100 for s in scores]
    
    plt.figure(figsize=(10, 6))
    plt.barh(range(len(names)), percentages)
    plt.yticks(range(len(names)), names)
    plt.xlabel("Importance (%)")
    plt.title(title)
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.show()

def analyze_shap(model_path: str, X_test: np.ndarray, feature_names: list):
    """SHAP analysis for model interpretability."""
    import shap
    
    model = lgb.Booster(model_file=model_path)
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)
    
    # Summary plot
    shap.summary_plot(shap_values, X_test, feature_names=feature_names)
    
    # SHAP feature importance (mean |SHAP value|)
    shap_importance = np.abs(shap_values).mean(axis=0)
    for name, imp in sorted(zip(feature_names, shap_importance), key=lambda x: -x[1]):
        print(f"{name:30s} {imp:.4f}")
```

### 8.5 Interpreting Importance Results

**Gain Importance** (mặc định, khuyến nghị dùng):
- Tổng improvement trong loss function mỗi khi feature được dùng để split
- Cao nhất với features có predictive power mạnh
- Nên dùng để chọn features

**Split Importance**:
- Số lần feature được dùng làm split condition
- Ưu tiên features có nhiều unique values (continuous features)
- Dễ bị bias → không khuyến nghị dùng standalone

**SHAP Values**:
- Model-agnostic interpretation
- Cho biết hướng tác động (positive/negative)
- Dùng để debug bias và false positive patterns

### 8.6 Feature Selection Strategy

```python
def recursive_feature_elimination(X, y, feature_names, n_features_to_select=10):
    """RFE using LightGBM feature importance."""
    from sklearn.feature_selection import RFE
    from lgb import LGBMClassifier
    
    model = LGBMClassifier(n_estimators=100, max_depth=4, random_state=42)
    rfe = RFE(model, n_features_to_select=n_features_to_select)
    rfe.fit(X, y)
    
    selected = [name for name, selected in zip(feature_names, rfe.support_) if selected]
    print(f"Selected {len(selected)} features: {selected}")
    return selected

def correlation_analysis(X, feature_names, threshold=0.95):
    """Remove highly correlated features."""
    corr_matrix = np.corrcoef(X.T)
    upper = np.triu(np.abs(corr_matrix), k=1)
    to_drop = []
    
    for i in range(len(feature_names)):
        for j in range(i + 1, len(feature_names)):
            if upper[i, j] > threshold:
                # Drop feature với importance thấp hơn
                to_drop.append(j)
    
    kept = [f for i, f in enumerate(feature_names) if i not in set(to_drop)]
    print(f"Removed {len(set(to_drop))} highly correlated features")
    return kept
```

---

## 9. So sánh Feature Extraction: Local vs Cloud

### 9.1 Architecture

```
=== LOCAL ===
Game Server JVM
  ├── FeatureBridge (tính features từ raw player state)
  ├── MLModelManager (feature extraction → float array)
  ├── BoundedMLQueue (async inference)
  ├── GBDT / OnlineLogReg (JVM-native inference)
  └── FusionEngine

=== CLOUD ===
Game Server JVM                           Cloud Server
  ├── FeatureBridge (tính features)         
  ├── MLModelManager (feature extraction)   
  ├── BoundedMLQueue ── gRPC/HTTP ──► Python Inference Server
  │                                          ├── LightGBM / XGBoost
  │               ◄── risk score             ├── PyTorch (LSTM)
  └── FusionEngine                           └── ONNX Runtime
```

### 9.2 Tại sao feature extraction local?

**Bandwidth Analysis**:
```
Raw rotation history (64 ticks):
  64 × (yaw + pitch) × 4 bytes = 512 bytes

Raw click history (50 clicks):
  50 × timestamp × 8 bytes = 400 bytes

Total raw: ~1-2 KB per inference per player

Feature vector:
  6 + 5 + 8 = 19 floats × 4 bytes = 76 bytes

Network savings: ~20-30x reduction
```

**Latency Analysis**:
```
Local:  feature extraction 0.01ms + inference 0.5ms = ~0.51ms
Cloud:  feature extraction 0.01ms + serialization 0.1ms + 
        network RTT 10-50ms + inference 0.5ms = ~10-50ms
```

**Kết luận**: Feature extraction luôn local vì:
1. Raw data quá lớn để gửi qua network (1-2KB vs 76 bytes)
2. Feature extraction cost rất thấp (< 0.01ms)
3. Cloud latency không đáng kể cho batch inference

### 9.3 So sánh Local vs Cloud Models

| Tiêu chí | Local (GBDT/LogReg) | Cloud (LightGBM/LSTM) |
|----------|--------------------|----------------------|
| Model complexity | Medium | High |
| Feature count | 6-8 per model | 19+ derived features |
| Sequence modeling | No | Yes (LSTM) |
| Inference latency | ~0.5ms | ~1-2ms (network excluded) |
| Update frequency | Per-restart | Real-time |
| Training data access | Limited | Full database |
| False positive rate | Higher | Lower |
| Memory usage | ~50KB per model | ~500KB+ per model |

---

## 10. Edge Cases & Failure Modes

### 10.1 Edge Case Matrix

| Tình huống | Aim Features | Click Features | Session Features | Risk | Hành động |
|------------|-------------|----------------|-----------------|------|-----------|
| AFK / Stand still | All ≈ 0 | None | sessionDuration tăng | 0.0 (low) | Skip inference |
| High ping (300ms+) | Jerk thấp + Smoothness cao | cooldownAccuracy thấp | gcdConsistency thấp | Có thể FP | Ping normalization |
| Low TPS (< 15) | Tất cả features noisy | Unreliable | Unreliable | N/A | Skip ML hoàn toàn |
| First join (no history) | Có (tick window) | Có thể trống | sessionDuration = 0 | Medium | Chỉ aim model |
| 1.8 player | Normal | cooldownAccuracy = 0.5 | missRatio = 0.5 | Medium-cap | Version override |
| Geyser (Bedrock) | Different sensitivity curve | Different click model | N/A | Có thể FP | Feature scaling |
| Lag spike (sudden jitter) | Jerk spike → false snap | interval spike → false miss | N/A | Có thể FP | Jitter factor |
| Silent aura | Tracking rotation ít → feature khác thường | N/A | N/A | Bypass | Cần behavioral trap |

### 10.2 Failure Mode Analysis

#### F1: High Ping False Positive

**Cơ chế**: Ping 200ms + rotation updates ít → yawJerkStd thấp tự nhiên
**Giải pháp**:
- `yawJerkStd /= sqrt(ping/50)` — normalization
- `getPingFactor()` — jitter-based weighting cho heuristic
- ping feature trong model → model học "yawJerkStd thấp nhưng ping cao → không phải cheat"

#### F2: Cinematic Mode False Positive

**Cơ chế**: OptiFine cinematic mode làm rotation cực kỳ smooth
**Giải pháp**:
- Cần train data có cinematic mode samples
- Hoặc detect cinematic mode riêng (thay đổi smoothness đột ngột khi bật/tắt)
- Current code không có detection riêng — đây là gap cần fix

#### F3: Skilled Player False Positive

**Cơ chế**: Player PvP chuyên nghiệp có timing và aim rất tốt
**Giải pháp**:
- Adaptive baseline (học behavior của từng player)
- SessionModel features capture baseline drift
- Heuristic cap 0.70 ngăn false flag từ heuristic
- ML cap 0.985 nhưng fusion cần whitebox corroboration để action

#### F4: Silent Aim / Legit Aura Bypass

**Cơ chế**: Cheat không modify rotation packets (silent aim), chỉ thay đổi attack timing
**Giải pháp**:
- Cross-correlation feature: rotation variance at attack moments
- Trigger reaction score: yawDelta khi click vs baseline
- Session-level gcdConsistency tracking

#### F5: Data Insufficient (Cold Start)

**Cơ chế**: Player mới join, chưa có đủ data
**Giải pháp**:
```
featureHistory.size < 10  → compute methods return defaults (0, 0.5, 7.0)
combatHistory.size < 3    → Aim risk = 0
clickHistory.size < 3     → Click features = 0.5
rotationAtAttack.size < 10 → cross-correlation = 0.5
jumpIntervals.size < 5    → jumpStddev = 999 (high = human)
```

#### F6: Version Inconsistency

**Cơ chế**: Feature extractor dùng 1.9+ cooldown features, không phù hợp cho 1.8
**Giải pháp**:
- `player.getClientVersion().isOlderThan(ClientVersion.V_1_9)` check trong computeCooldownAccuracy
- Nếu 1.8: `computeCooldownAccuracy()` return 0.5, `computeMissRatio()` return 0.5
- Feature extraction vẫn extract cả 5 features, nhưng model học version-specific thresholds

---

## 11. Behavioral Traps (Cross-Correlation Features)

### 11.1 Cross-Correlation: Rotation Stability at Attack

**FeatureBridge.java line 1161-1173**:
```java
public double computeClickRotationVariance() {
    // Variance of yawDelta at attack moments
    // Low variance = aim assist (rotation settled before click)
    // Human: variance 0.1-0.5, Bot: variance < 0.01
}
```

**Cách hoạt động**:
- Track `rotationAtAttack` ArrayList: yaw delta tại mỗi attack moment
- Human click trong khi rotation vẫn đang thay đổi → variance cao
- Aim assist chờ rotation ổn định trên target rồi mới click → variance rất thấp
- Threshold: variance < 0.01 → suspicious

**ROC analysis (theoretical)**:
```
Tại variance threshold 0.01:
  TPR (detect aim assist): ~0.85
  FPR (false positive): ~0.02
  
Tại variance threshold 0.02:
  TPR: ~0.92
  FPR: ~0.07
```

### 11.2 TriggerBot Detection

**FeatureBridge.java line 1186-1212**:
```java
public double computeTriggerReactionScore() {
    double ratio = attackAvgYawDelta / baselineAvgYawDelta;
    // ratio < 0.3 + rotationAtAttack.size > 10 → risk 0.8
    // ratio < 0.5 + rotationAtAttack.size > 15 → risk 0.5
}
```

**Cách hoạt động**:
- Human: yawDelta khi click ≈ baseline yawDelta (click continuously while turning)
- TriggerBot: yawDelta khi click << baseline (chỉ click khi crosshair trên target, rotation ổn định)
- Tỉ lệ attack/baseline < 0.3 → rất suspicious

**Khoa học**:
- Human có reaction time ~150-250ms
- Khi tracking target, human click throughout the tracking motion
- TriggerBot chỉ click khi crosshair alignment đạt threshold

### 11.3 Auto-Jump Detection

**FeatureBridge.java line 1067-1098**:
```java
autoJumpRatio = combatJumpTicks / (combatJumpTicks + combatNonJumpTicks)
jumpStddev = stddev(jumpIntervals)  // Interval between jumps
groundedRatio = combatGroundedTicks / totalCombatTicks
```

**Rules**:
- jumpRatio > 0.65 + jumpStddev < 100ms + groundedRatio < 0.3 → auto-jump
- AutoJumpReset: jump ngay khi chạm đất → groundedRatio thấp

**Auto-jump patterns**:
```
Human jump intervals: 350ms, 800ms, 420ms, 1200ms → stddev ~350ms
Auto-jump intervals:  500ms, 510ms, 490ms, 505ms → stddev ~10ms
```

---

## 12. Adaptive Baseline & Online Learning

### 12.1 Adaptive Baseline (FeatureBridge)

Cập nhật mỗi 60s từ feature history:

```java
public void updateBaseline() {
    // EWMA update (decay 0.9)
    baselineOffset = baselineOffset * 0.9 + offset * 0.1;
    baselineOffsetStd = baselineOffsetStd * 0.9 + Math.abs(offset - baselineOffset) * 0.1;
    baselineCps = baselineCps * 0.9 + currentFeatures.getCps() * 0.1;
}
```

**Adaptive thresholds**:
```java
getAdaptiveCpsThreshold() = max(12, baselineCps + baselineCpsStd * 2.0)
getAdaptiveOffsetThreshold() = max(0.001, baselineOffset + baselineOffsetStd * 3.0)
```

**Ý nghĩa**:
- Player CPS baseline 8 → threshold = max(12, 8 + 3*2) = 14
- Player CPS baseline 15 → threshold = max(12, 15 + 5*2) = 25
- Tránh false flag cho player có baseline cao tự nhiên

### 12.2 Online Model Training

**ClickModel** (OnlineLogReg): Online SGD update mỗi sample
```java
void train(float[] features, float label) {
    float prediction = sigmoid(dot(weights, features) + bias);
    float error = prediction - label;
    for (int i = 0; i < numFeatures; i++) {
        weights[i] -= learningRate * error * features[i];
    }
    bias -= learningRate * error;
}
```

**SessionModel** (Ensemble): Mỗi member train độc lập
```java
void train(float[] features, float label) {
    for (EnsembleMember member : members) {
        member.train(features, label);
    }
}
```

**ConfidenceModel** (Bayesian): Update posterior means + variances
```java
void updateImpl(double[] features, double label) {
    // Natural gradient approximation
    for (int i = 0; i < NUM_FEATURES; i++) {
        double grad = error * features[i] + lambda * weightMeans[i];
        weightMeans[i] -= learningRate * grad;
    }
    // Variance update using observed Fisher information
    double hessian = prediction * (1.0 - prediction);
    for (int i = 0; i < NUM_FEATURES; i++) {
        precision += hessian * features[i] * features[i];
        weightVariances[i] = 1.0 / precision;
    }
}
```

### 12.3 Online Training Data Sources

| Label Source | Quality | Quantity | Use Case |
|-------------|---------|----------|----------|
| Whitebox high-confidence flags | High | Low | Positive samples |
| Staff manual review | Very high | Very low | Validation |
| Known clean players (ops, trusted) | High | Medium | Negative samples |
| Player reports | Low | High | Avoid |
| Auto-ban appeals (reversed = FP) | High | Low | False positive correction |

### 12.4 Online Training Safety

```python
def safe_online_train(model, features, label, confidence_threshold=0.9):
    """
    Only train on high-confidence labels to avoid model poisoning.
    """
    if label == 1.0:  # Cheat
        # Only train if whitebox also suspicious
        if not whitebox_corroboration(features):
            return  # Skip — might be false positive
    else:  # Legit
        # Only train if player has clean history
        if player_risk_history > 0.3:
            return  # Skip — might be undetected cheat
    
    model.train(features, label)
```

---

## 13. Phụ lục: Feature Matrix

### 13.1 Complete Feature Summary

| # | Feature | Model | Range | Human | Cheat | Computation Cost | Window |
|---|---------|-------|-------|-------|-------|-----------------|--------|
| 1 | yawJerkStd | Aim | [0, 1+] | 0.5-1.5 | 0.05-0.4 | Low | 64 ticks |
| 2 | pitchJerkStd | Aim | [0, 0.8] | 0.3-0.6 | 0.05-0.2 | Low | 64 ticks |
| 3 | aimSmoothness | Aim | [0, 1] | 0.4-0.75 | 0.85-0.99 | Medium | 64 ticks |
| 4 | rotationEntropy | Aim/Session | [0, 7.5] bits | 5-7 bits | 2-4 bits | Medium | 64 ticks |
| 5 | gcdError | Aim | [0, 0.25] | 0.05-0.25 | 0.001-0.02 | Low | 64 ticks |
| 6 | snapFreq | Aim | [0, 1] | 0-0.1 | 0.2-0.8 | Low | 64 ticks |
| 7 | cooldownAccuracy | Click/Session | [0, 0.98] | 0.3-0.75 | 0.85-0.98 | Medium | 50 clicks |
| 8 | missRatio | Click/Session | [0, 1] | 0.3-0.7 | 0-0.1 | Low | 50 clicks |
| 9 | hitMissRatio | Click | [0, 1] | 0.3-0.8 | 0.8-1.0 | Low | 32 attacks |
| 10 | criticalRatio | Click | [0, 1] | 0.1-0.65 | 0.7-1.0 | Low | 32 attacks |
| 11 | perfectStreak | Click | [0, 50+] | 1-8 | 12-50+ | Medium | 50 clicks |
| 12 | mouseSensitivity | Session | [0, 1] | 0.2-0.8 | N/A | Low | 64 ticks |
| 13 | pitchDeltaMean | Session | [0, 5+] | 0.5-3.0 | N/A | Low | 64 ticks |
| 14 | yawDeltaMean | Session | [0, 10+] | 1.0-5.0 | N/A | Low | 64 ticks |
| 15 | gcdConsistency | Session | [0, 1] | 0-0.6 | 0.9-1.0 | Low | 64 ticks |
| 16 | sessionDuration | Session | [0, 1] | N/A | N/A | Low | Session |

### 13.2 Model Architecture Summary

| Model | Algorithm | Features | Training | Predict() | Memory |
|-------|-----------|----------|----------|-----------|--------|
| AimModel | GBDT (30 trees, depth 4) | 6 | Offline (LightGBM→export) | `O(depth * num_trees)` | ~15KB |
| ClickModel | OnlineLogReg | 5 | Online SGD | `O(num_features)` | ~200 bytes |
| SessionModel | Ensemble (5× OnlineLogReg) | 8 | Online SGD | `O(members * features)` | ~1KB |
| AimModel (fallback) | OnlineLogReg | 6 | Online SGD | `O(num_features)` | ~200 bytes |
| SessionModel (fallback) | OnlineLogReg | 8 | Online SGD | `O(num_features)` | ~200 bytes |

### 13.3 Heuristic Fallback Weights

```python
# FeatureBridge.computeAimRiskScore() weights
HEURISTIC_WEIGHTS = {
    'smoothness': 0.30,      # threshold: > 0.85
    'jerk_stddev': 0.25,     # threshold: < 0.4
    'rotation_entropy': 0.25, # threshold: < 4.0
    'accel_anomaly': 0.20,   # threshold: > 0.2
}
HEURISTIC_CAP = 0.70  # Never exceed 0.70 (real ML can reach 0.985)
```

---

## References

1. **FeatureBridge.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\player\features\FeatureBridge.java`
2. **AimModel.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\AimModel.java`
3. **ClickModel.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\ClickModel.java`
4. **SessionModel.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\SessionModel.java`
5. **MLModelManager.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\ml\MLModelManager.java`
6. **GBDT.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\GBDT.java`
7. **ConfidenceModel.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\ConfidenceModel.java`
8. **OnlineLogReg.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\OnlineLogReg.java`
9. **FeatureVector.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\player\features\FeatureVector.java`
10. **docs/plan/07-feature-spec.md** — Feature specification document
11. **docs/plan/08-ml-system.md** — ML system architecture
12. **docs/plan/ML_MODELS_DETAILED.md** — Detailed ML models plan (note: implementation differs from this plan)
