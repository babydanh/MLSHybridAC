# Blackbox ML Models — MLSHybridAC Phase 3

## Triết lý
Blackbox KHÔNG thay thế whitebox. Blackbox chỉ sinh risk score [0, 0.985].
Fusion quyết định hành động dựa trên whitebox + blackbox + runtime.

```
Whitebox (Grim) → FeatureBridge → BLACKBOX MODELS → FusionEngine → Action
                                        │
                                  3 model chính:
                                  ├── AimModel    (rotation)
                                  ├── ClickModel  (click pattern)
                                  └── SessionModel (behavioral profile)
```

## Model 1: AimModel — Rotation Analysis
**Phát hiện:** AimAssist, KillAura, SmoothAim
**Input (6 features):**
```
f1: yawJerkStdDev    — variance của yaw acceleration
f2: pitchJerkStdDev  — variance của pitch acceleration
f3: aimSmoothness    — correlation giữa consecutive rotation deltas
f4: rotationEntropy  — Shannon entropy của rotation distribution
f5: gcdError         — Greatest Common Divisor error (aim assist thường có GCD đều)
f6: snapFrequency    — số lần rotation đột ngột > threshold/giây
```
**Model:** Gradient Boosting (depth 3, 30 trees) + Sigmoid output
→ risk: `GBDT(features) → sigmoid → [0, 0.985]`
→ confidence: `ConfidenceModel.update(risk) → stability 0-1`

## Model 2: ClickModel — Click Pattern Analysis
**Phát hiện:** AutoClicker, Butterfly click, Script click
**Input (5 features):**
```
f1: cps             — clicks per second
f2: clickIntervalStd— standard deviation của intervals
f3: clickEntropy    — Shannon entropy (thấp = script)
f4: burstRatio      — tỷ lệ burst click vs sustained
f5: fftDominantFreq— tần số trội từ FFT (phát hiện script cycle)
```
**Model:** Logistic Regression (online training được)
→ risk: `sigmoid(w·f + b) → [0, 0.985]`
→ online train: `w -= lr * (predict - label) * f`

## Model 3: SessionModel — Behavioral Profile
**Phát hiện:** GhostClient, legit aura, baritone
**Input (8 features — window 10 phút):**
```
f1: avgHitDistance        — trung bình reach hành hiệp
f2: hitDistanceStd        — std dev reach (ghost rất consistent)
f3: reactionTimeMs        — reaction time khi target đổi hướng
f4: missPercentage        — % miss khi target di chuyển phức tạp
f5: aimLockDuration       — thời gian lock trên target > 5s
f6: targetSwitchSpeed     — tốc độ chuyển mục tiêu
f7: noBadTickRatio        — tỷ lệ tick không có hesitation
f8: movementComplexity    — path complexity so với vanilla
```
**Model:** Weighted Ensemble — điểm mỗi feature × weight riêng
→ risk: `w1*f1 + w2*f2 + ... + w8*f8 → sigmoid → [0, 0.85]`
→ **Không bao giờ auto-ban** (Rule 7: GHOST_PROFILE chỉ ALERT)

## Priorities

| Domain | Whitebox | Blackbox | Model | Fusion Rule |
|---|---|---|---|---|
| Movement | ✅ Mạnh | Không cần | — | R6: enforce ngay |
| Reach | ✅ Mạnh | Optional | SessionModel (f1,f2) | R1: enforce sớm |
| KillAura | 🔶 Trung bình | ✅ Cần | AimModel + SessionModel | R3: hybrid escalate |
| AimAssist | ❌ Yếu | ✅ Cần | AimModel | R2: chỉ ALERT |
| AutoClicker | 🔶 Trung bình | ✅ Cần | ClickModel | R3/R4: alert→escalate |
| GhostClient | ❌ Rất yếu | ✅ Cần | SessionModel | R7: ALERT only |

## Files sẽ tạo

```
ml/
├── AimModel.java        — GBDT cho rotation analysis
├── ClickModel.java      — Logistic Regression cho click
├── SessionModel.java    — Weighted ensemble cho profile
├── ConfidenceModel.java — Bayesian confidence + burst detect
├── FFT.java             — Fast Fourier Transform (độc lập)
├── KalmanFilter.java    — Lọc nhiễu rotation
├── ModelStore.java      — Persist weight ra file
├── ModelTrainer.java    — Online training helper
└── package-info.java
```
