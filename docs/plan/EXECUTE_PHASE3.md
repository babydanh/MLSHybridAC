# Execution Plan — MLSHybridAC Phase 3 ML Integration

## Mục tiêu
Implement 3 blackbox ML models, wire vào FusionEngine, build verify.

## Phase 3.1 — Core ML Models (3 agents song song)

### Agent A: GBDT + AimModel
- Tạo `ml/` package
- Implement `ml/GBDT.java` — Gradient Boosted Decision Tree (depth 4, 30 trees)
- Implement `ml/AimModel.java` — 6 rotation features → GBDT → risk
- Input features: yawJerkStd, pitchJerkStd, aimSmoothness, rotationEntropy, gcdError, snapFreq
- Load/save model từ file txt
- Build verify

### Agent B: LogReg + ClickModel
- Implement `ml/OnlineLogReg.java` — Logistic Regression + online SGD
- Implement `ml/ClickModel.java` — 5 click features → LogReg → risk
- Input features: cps, intervalStd, clickEntropy, burstRatio, fftDominant
- ModelStore: persist weight ra file
- Online training: label từ staff flag/dismiss
- Build verify

### Agent C: SessionModel + ConfidenceModel + Signal Processing
- Implement `ml/SessionModel.java` — Weighted ensemble, 8 session features
- Implement `ml/ConfidenceModel.java` — Bayesian logit + burst tracking
- Implement `ml/FFT.java` — Cooley-Tukey radix-2 FFT
- Implement `ml/KalmanFilter1D.java` — Lọc nhiễu
- Build verify

## Phase 3.2 — Integration (1 agent)
### Agent D: Wire ML → FusionEngine
- FeatureBridge gọi ML models qua BoundedMLQueue
- AimModel → FusionEngine.setBlackboxRisk(risk, COMBAT_AIM)
- ClickModel → FusionEngine.setBlackboxRisk(risk, CLICK)
- SessionModel → FusionEngine.setBlackboxRisk(risk, GHOST_PROFILE)
- ConfidenceModel ảnh hưởng threshold trong FusionEngine
- Build verify

## Phase 3.3 — Final Verify
### Agent E: Build + Test
- `./gradlew :common:build`
- Chạy unit tests
- Fix lỗi nếu có
- Báo cáo kết quả
