# Execution Plan — Phase 3 ML Integration

## Mục tiêu
Port 6 ML models từ BakiVF vào MLSHybridAC để blackboxRisk có giá trị thực,
không còn là heuristic tạm.

## Phase 3.1 — Core ML Models (3 tasks song song)

### Task A: GBDTModel (Gradient Boosted Decision Tree)
- File: `ml/GBDTModel.java` (mới)
- Pattern: BakiVF `GBDTModel.java`
- Chức năng: predict risk từ feature vector float[]
- Dùng cho: AimAssist, AutoClicker classification
- Input: 10 features từ FeatureBridge (yawJerk, smoothness, entropy, CPS, ...)
- Output: risk 0-1 qua sigmoid

### Task B: OnlineLogReg (Logistic Regression)
- File: `ml/OnlineLogReg.java` (mới)
- Pattern: BakiVF `OnlineLogReg.java`
- Chức năng: online training ngay trên server, không cần offline
- Dùng cho: Click pattern, reach abuse
- Input: double[] features
- Output: probability + tự cập nhật weight theo staff feedback

### Task C: ConfidenceModel + KalmanFilter
- File: `ml/ConfidenceModel.java` + `ml/KalmanFilter1D.java` (mới)
- Pattern: BakiVF
- Chức năng: ước lượng độ tin cậy của risk score, lọc nhiễy rotation
- Dùng cho: FusionEngine đầu vào

## Phase 3.2 — Feature Pipeline Upgrade (2 tasks)

### Task D: FeatureExtractor
- Nâng cấp FeatureBridge → extract đúng 10 features cho GBDT
- Các feature: predictionOffset, yawJerkStd, smoothness, entropy, CPS, 
  pitchDelta, hitDistance, comboFrequency, ping, packetLoss

### Task E: Wire ML → FusionEngine
- BoundedMLQueue.submit() gọi GBDT.predict() + OnlineLogReg.predict()
- Kết quả → FusionEngine.setBlackboxRisk()
- ConfidenceModel ước lượng độ tin cậy của prediction

## Phase 3.3 — Persistence & Training (1 task)

### Task F: ModelStore + Online Training
- Persist model weights ra file (txt format)
- Online training: staff flag = positive, staff dismiss = negative
- Tự động save mỗi 5 phút

## Timeline
| Phase | Tasks | Thời gian |
|---|---|---|
| 3.1 | A + B + C (song song) | 2-3 ngày |
| 3.2 | D + E | 1-2 ngày |
| 3.3 | F | 1 ngày |
| **Total** | **6 tasks** | **~5 ngày** |
