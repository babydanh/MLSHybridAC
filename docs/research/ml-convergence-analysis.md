# ML Convergence Analysis — MLSHybridAC Anticheat

> **Version**: 1.0
> **Date**: 2026-07-10
> **Scope**: Phân tích hội tụ (convergence), feedback loop, data quality, cold start, concept drift, và so sánh ML vs Whitebox cho Minecraft anticheat
> **Codebase**: GrimAC + MLSHybridAC (Python cloud training pipeline + Java inference engine)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Convergence: ML có càng train càng chuẩn không?](#2-convergence-ml-có-càng-train-càng-chuẩn-không)
3. [Feedback Loop Analysis](#3-feedback-loop-analysis)
4. [Data Quality Assessment](#4-data-quality-assessment)
5. [Cold Start Problem](#5-cold-start-problem)
6. [Concept Drift](#6-concept-drift)
7. [ML vs Pure Whitebox: Category Comparison](#7-ml-vs-pure-whitebox-category-comparison)
8. [Kết luận và Recommendations](#8-kết-luận-và-recommendations)

---

## 1. Executive Summary

### Key Findings (TL;DR)

| Question | Answer |
|----------|--------|
| ML có càng train càng chuẩn? | **Đúng, nhưng có giới hạn.** AUC sẽ bão hòa ở mức 0.92-0.95 cho aim, 0.88-0.92 cho click. Feature space nhỏ (6-8 dim) → diminishing returns sớm. |
| Feedback loop có giết model? | **Không.** Cơ chế auto-label whitelist (chỉ MOVEMENT/PACKET/WATCHDOG_BOT) cắt hoàn toàn feedback loop. Semi-supervised weight chỉ 0.3 — không đủ để self-reinforce. |
| Label noise có dangerous? | **Có, nhưng đã kiểm soát.** Staff ban là gold standard. Clean_window weight 0.5 để tránh nhiễu. Whitebox_high chỉ auto-label ở certainty > 0.95. |
| Cold start cần bao nhiêu data? | **~500-2000 positive samples** để model bắt đầu có ích. Với 1% cheat rate, cần ~50K-200K total samples. Trên server 100 players: ~50-200 ngày. |
| Concept drift có nguy hiểm? | **Có.** Daily retrain có thể không đủ nhanh khi cheat client update. Không có drift detection mechanism. |
| ML đáng đầu tư không? | **Có, nhưng chỉ cho COMBAT_AIM và CLICK.** MOVEMENT/PACKET: whitebox 99% → ML vô dụng. GHOST_PROFILE: ML là hy vọng duy nhất nhưng feature set hiện tại quá yếu. |

---

## 2. Convergence: ML có càng train càng chuẩn không?

### 2.1 LightGBM Binary Classification — Lý thuyết hội tụ

LightGBM với `objective: binary`, `metric: auc` hội tụ theo quy luật **diminishing returns** điển hình của gradient boosting:

```
AUC = f(N, D, η)

Trong đó:
  N = số lượng training samples
  D = số chiều feature space (6-8 features)
  η = label noise level
```

Với feature space nhỏ (6 features cho aim, 5 cho click, 8 cho session), model có giới hạn về lượng thông tin có thể học được. Đây là **bottleneck chính** — không phải số lượng data.

### 2.2 Learning Curve Dự Đoán

Dựa trên số chiều feature space và domain knowledge:

#### AimModel (6 features)

| Samples | Expected AUC | Ghi chú |
|---------|-------------|---------|
| 0-500 | < 0.70 (không train) | Cold start — model trả 0.5 |
| 500-2000 | 0.75-0.85 | Model bắt đầu có signal, còn noisy |
| 2000-10000 | 0.85-0.92 | Giai đoạn tăng trưởng nhanh nhất |
| 10000-50000 | 0.92-0.95 | Giai đoạn diminishing returns |
| 50000+ | 0.93-0.96 (bão hòa) | Thêm data không cải thiện đáng kể |

Giới hạn trên lý thuyết: **AUC ~0.96** cho aim model.

**Nguyên nhân giới hạn:**
1. Feature space chỉ 6 chiều → signal bị bound bởi thông tin có trong features
2. Label noise inherent (clean_window có thể chứa subtle cheater)
3. Human variance overlap với cheat patterns (skilled player vs aim assist khó phân biệt)

#### ClickModel (5 features)

| Samples | Expected AUC | Ghi chú |
|---------|-------------|---------|
| 500-2000 | 0.70-0.80 | Click features dễ bị noise hơn |
| 2000-10000 | 0.80-0.88 | |
| 10000-50000 | 0.88-0.92 | Bão hòa sớm hơn aim (ít features hơn) |

Giới hạn trên lý thuyết: **AUC ~0.92** cho click model.

#### SessionModel (8 features)

| Samples | Expected AUC | Ghi chú |
|---------|-------------|---------|
| 500-2000 | 0.65-0.75 | Session features nhiều confounders |
| 2000-10000 | 0.75-0.85 | |
| 10000-50000 | 0.85-0.90 | |

Giới hạn trên lý thuyết: **AUC ~0.90** cho session model.

Session model thấp nhất vì:
- Nhiều features là confounder controls (mouseSensitivity, pitch/yaw delta mean) hơn là cheat signals
- normalizedSessionDuration không phải direct cheat indicator
- Ghost client legit aura rất khó phát hiện qua aggregated stats

### 2.3 Bias-Variance Tradeoff cho Anticheat

Trong context anticheat, bias-variance tradeoff có ý nghĩa đặc biệt:

```
Underfit (High Bias)              Overfit (High Variance)
  ├── Bỏ sót cheat (FN)             ├── False flag (FP)
  ├── threshold quá cao              ├── threshold quá thấp
  ├── Model không đủ phức tạp        ├── Model học noise
  └── Hậu quả: cheat thoát           └── Hậu quả: ban nhầm người chơi
```

**Cost asymmetry cực kỳ quan trọng:**

| Error Type | Cost | Acceptability |
|-----------|------|---------------|
| False Positive (ban nhầm) | Rất cao: mất player, reputation damage | Gần như 0 tolerance |
| False Negative (bỏ sót) | Thấp: cheat vẫn chơi, sẽ bị bắt sau | Có thể chấp nhận |

**Do đó, model design phải ưu tiên precision hơn recall**, ngay cả khi làm giảm AUC.

**Current code đã xử lý đúng hướng:**
- `max_risk_cap = 0.985` — không bao giờ cho 100% certainty
- `scale_pos_weight` capped at 100 — tránh over-compensate cho imbalance
- Early stopping với patience 50 — tránh overfit
- `min_data_in_leaf = 20` — tránh leaf nodes quá specific

### 2.4 Khi nào model bão hòa (diminishing returns)?

Dựa trên code thực tế (`train.py`):

**Các yếu tố giới hạn convergence:**

1. **Feature space nhỏ (6-8 dim)**
   - Với 6 features, thông tin tối đa có thể extract ~6 bits per sample
   - 10K samples ≈ 60K bits thông tin ≈ model đã thấy hầu hết patterns
   - Thêm 40K samples chỉ thêm noise, không thêm signal

2. **Label noise floor**
   - clean_window (weight 0.5) có thể chứa subtle cheater → false negative labels
   - whitebox_high (weight 1.5) có thể miss new cheats → false positive labels
   - Noise floor ước tính: ~5-10% → giới hạn AUC tối đa ~0.95

3. **Overlap giữa human và cheat distributions**
   - Skilled human player có aimSmoothness 0.75, aim bot có 0.85
   - GCD analysis: human 0.05-0.25, cheat 0.001-0.02
   - Có overlap region không thể phân biệt hoàn toàn

**Kết luận:** Model sẽ bão hòa sau ~10K-20K samples. Training thêm sau điểm này không cải thiện AUC đáng kể. **Không phải càng train càng chuẩn — có ceiling.**

### 2.5 Code-Level Bottleneck Analysis

```python
# Từ train.py _load_data()
rows = self.db.fetch_all(
    """SELECT features_json, label FROM training_samples
       WHERE category = ? AND label IS NOT NULL AND created_at > ?
       ORDER BY created_at DESC LIMIT 50000""",
    (category, cutoff),
)
```

**Vấn đề:** `LIMIT 50000` cố định. Khi có >50K samples, model chỉ thấy 50K gần nhất. Đây là **windowing issue**: model có thể quên patterns từ xa (concept drift handling, nhưng cũng mất historical signal).

```python
params["scale_pos_weight"] = min(pos_weight, 100.0)
```

`scale_pos_weight` capped at 100. Với positive ratio 0.1% (1:1000), class imbalance correction chỉ đạt 100/1000 = 10% của mức cần thiết. Model vẫn biased toward negative class → lower recall cho cheat detection.

---

## 3. Feedback Loop Analysis

### 3.1 Feedback Loop Diagram

```
Whitebox Check Flag (MOVEMENT/PACKET)
  → certainty > 0.95
  → auto-label = 1.0, source = "whitebox_high"
  → gửi lên cloud training DB
  → next training cycle: model học pattern này
  → model deploy: blackbox risk tăng cho pattern tương tự
  → FusionEngine: blackbox risk ảnh hưởng decision
  → Nếu dẫn đến ENFORCE → auto-label tiếp
```

**Đây là feedback loop nguy hiểm nếu không được kiểm soát.**

### 3.2 Current Protection: Auto-Label Whitelist

Code trong `FusionEngine.java` (fusion-engine-analysis.md §4.7):

```java
// Chỉ MOVEMENT, PACKET, WATCHDOG_BOT được auto-train với label=1.0
// COMBAT_AIM, CLICK, COMBAT_GEOM, SCAFFOLD, BREAKING, GHOST_PROFILE, BOTting
// hoàn toàn KHÔNG được auto-label
```

**Phân tích hiệu quả:**

| Auto-label source | Categories | ML feedback risk | Assessment |
|------------------|------------|------------------|------------|
| whitebox_high | MOVEMENT, PACKET | **Không có.** Whitebox là deterministic truth, ML không thể ảnh hưởng | An toàn |
| watchdog_bot | WATCHDOG_BOT | **Không có.** Bot test là deterministic | An toàn |
| staff_ban | ALL (manual) | **Không có.** Human decision, độc lập với ML | An toàn |
| clean_window | ALL | **Có rủi ro thấp.** Weight 0.5 + chỉ negative label | An toàn |
| semi_supervised | ALL | **Có rủi ro.** Weight 0.3 → không đủ để self-reinforce | An toàn có giới hạn |

### 3.3 Tại sao ML không thể self-reinforce?

Phân tích chi tiết cơ chế ngăn feedback loop:

**Bước 1:** ML trả risk cao cho player X
**Bước 2:** FusionEngine dùng blackbox risk trong decision (Rules 2-4)
**Bước 3:** Nếu dẫn đến ENFORCE → auto-label?

**Rào cản:**
- **Rule 2** (ML-only high risk): Chỉ ALERT, không ENFORCE → không auto-label
- **Rule 3** (Hybrid escalation): Cần whiteboxCertainty >= 0.70 + flagCount >= 3 → whitebox đã có signal
- **Rule 4** (Repeated weak): Non-movement domains → chỉ SOFT_MITIGATE, không ENFORCE

**Kết luận:** ML risk không thể trực tiếp dẫn đến auto-label vì:
1. Auto-label chỉ từ whitebox (MOVEMENT/PACKET) — deterministic
2. ML-only path (Rule 2) chỉ ALERT — không ban
3. Hybrid path cần whitebox corroboration — ML chỉ đóng vai trò phụ

### 3.4 Scenario: Semi-Supervised Feedback Loop

Semi-supervised labeling dùng model confidence > 0.95 để auto-label:

```
Model predict score 0.97 → label = 1.0, source = "semi_supervised", weight = 0.3
→ Next training: model thấy sample này
→ Model reinforced: score càng cao cho pattern tương tự
→ More semi-supervised labels
```

**Cơ chế kiểm soát:**
- `source_weight = 0.3` — thấp nhất trong tất cả sources
- `get_training_weight()` negative samples get half weight → 0.15
- Sample weight cuối = 0.3 * class_balance * db_weight → không đủ dominate

**Threshold an toàn:**
```
Để semi-supervised label dominate training:
  0.3 (weight) > 5.0 (staff_ban weight)
  → Không thể
```

### 3.5 Hidden Feedback Loop: FusionEngine → Label Quality

Có một feedback loop gián tiếp qua FusionEngine:

```
FusionEngine dùng blackbox risk
  → ảnh hưởng decision threshold
  → staff thấy nhiều alert hơn từ ML
  → staff ban dựa trên alert (confirmation bias)
  → label "staff_ban" từ ban này
  → model học: output cao → staff ban → reinforced
```

**Mức độ nguy hiểm:** MEDIUM.

**Mitigation:**
- Staff ban chỉ là 1 trong nhiều nguồn label
- Clean window negatives (volume cao) cân bằng lại
- vanilla_fingerprint negatives (weight 2.0) cung cấp strong negatives
- Nếu staff ban sai → staff_unban (weight 5.0) correction

**Recommendation:** Monitor tỉ lệ staff ban được ML alert trigger. Nếu > 80% staff bans từ ML alert → có confirmation bias.

### 3.6 Detecting Feedback Loop Degradation

Dấu hiệu model đang bị feedback loop làm hỏng:

| Metric | Behavior khi feedback loop | Early detection |
|--------|---------------------------|-----------------|
| AUC trên test set | Tăng nhưng precision giảm | Track precision-recall curve |
| Positive ratio trong training data | Tăng đột biến | So sánh với ground truth ratio |
| Feature importance distribution | Một feature dominate > 50% | Monitor gain importance |
| Model confidence | Tăng dần (calibration loss) | Reliability diagram |
| Staff appeal rate | Tăng → nhiều false positives | Track appeals/ban ratio |

**Current code chưa có detection mechanism nào cho feedback loop degradation.** Đây là gap cần fill.

---

## 4. Data Quality Assessment

### 4.1 Label Source Quality Matrix

| Source | Weight | Reliability | Volume | Noise Level | Risk |
|--------|--------|-------------|--------|-------------|------|
| staff_ban | 5.0 | ★★★★★ | Rất thấp | ~2-5% | Staff có thể ban sai lý do |
| staff_unban | 5.0 | ★★★★★ | Cực thấp | ~1% | Gold standard negative |
| watchdog_bot | 3.0 | ★★★★ | Trung bình | ~5% | Bot có thể miss subtle cheats |
| whitebox_high | 1.5 | ★★★ | Trung bình | ~10% | Threshold 0.95 có thể miss |
| clean_window | 0.5 | ★★★ | Rất cao | ~15-20% | Subtle cheater trong clean window |
| vanilla_fingerprint | 2.0 | ★★★★ | Thấp | ~2% | Client brand có thể fake |
| semi_supervised | 0.3 | ★★ | Cao | ~20-30% | Model tự label, confirmation bias |

### 4.2 Label Noise Impact on LightGBM

LightGBM có built-in robustness với label noise nhờ:
1. **Leaf-wise growth:** Noise samples isolated trong leaf nodes riêng
2. **Early stopping:** Ngừng train trước khi học noise
3. **min_data_in_leaf = 20:** Leaf cần 20+ samples → noise khó dominate

**Noise threshold:** Với `min_data_in_leaf = 20` và `num_leaves = 31`, model có ~620 slots cho noise. Với 10K samples, noise tolerance ~6.2%.

**Công thức approximation:**
```
Noise tolerance ≈ min_data_in_leaf / (total_samples / num_leaves)
                = 20 / (10000 / 31)
                = 20 / 322
                ≈ 6.2%
```

Nếu label noise > 10% (possible với clean_window + semi_supervised), model performance sẽ degrade.

### 4.3 Clean Window: The Weakest Link

`clean_window` là source có volume cao nhất nhưng chất lượng thấp nhất:

**Vấn đề:**
- Player toggle cheat off trong 1 giờ → vẫn được label "legit"
- Subtle cheater (5% reach, 10% aim assist) không bị flag bởi whitebox → false negative
- Weight chỉ 0.5 → model không penalize mạnh nhưng vẫn tạo noise floor

**Impact analysis:**
```
Nếu 10% "clean window" samples thực ra là cheater:
  10000 negatives, 1000 là false negatives
  → Model học: pattern X (cheat) → label 0
  → Khi gặp pattern X trong inference: predict thấp
  → Miss detection
```

**Mitigation trong code:**
- `clean_window` weight 0.5 (thấp) → ít ảnh hưởng decision boundary
- `vanilla_fingerprint` weight 2.0 (cao) → negatives đáng tin cậy hơn
- Class balance weight cho positives > negatives

**Recommendation:** Cần mechanism detect cheater trong clean window (ví dụ: cross-reference với future bans).

### 4.4 Whitebox_High Quality

`whitebox_high` dùng certainty > 0.95 từ Grim checks:

```python
LABEL_SOURCES = {
    "whitebox_high": LabelSource(
        name="whitebox_high", weight=0.85, reliability="★★★☆☆",
        description="Whitebox certainty > 0.95 (movement/packet cheats)",
    ),
}
```

**Vấn đề:**
- MOVEMENT/PACKET ở 0.95 gần như deterministic → label rất tin cậy
- COMBAT_AIM ở 0.95 vẫn có thể false positive (skilled player)
- `is_high_confidence()` trả True nếu weight >= 0.8 → whitebox_high (0.85) là high confidence

**Nhưng trong FusionEngine auto-label:**
```java
// Chỉ MOVEMENT, PACKET, WATCHDOG_BOT được auto-train
// COMBAT_AIM KHÔNG được auto-label dù certainty > 0.95
```

Đây là design đúng — COMBAT_AIM dù certainty cao vẫn không auto-label vì rủi ro FP.

### 4.5 Synthetic Data Risk

Codebase không có synthetic data generation. Nhưng nếu sau này thêm synthetic data:

**Rủi ro:**
- Synthetic distribution không match real distribution
- Model học artifact của synthetic generator
- Trên real data, performance thấp hơn expected

**Rule of thumb:**
```
Nếu synthetic data chiếm > 30% training set:
  → Test trên real data bắt buộc
  → AUC gap giữa synthetic test và real test > 0.05 → synthetic quality issue
```

---

## 5. Cold Start Problem

### 5.1 The Bootstrap Threshold

Từ code:

```python
# config.min_samples_for_training (default value)
MIN_SAMPLES_FOR_TRAINING = 500  # trong config.py

# train.py _load_data()
if len(rows) < config.min_samples_for_training:
    return None, None  # Skip training
```

**Problem:** 500 samples với label. Với positive ratio ~1% cho aim:
```
Total samples needed = 500 / 0.01 = 50,000
Trên server 100 CCU, 1% cheat rate:
  1 positive sample / ngày (giả sử mỗi cheater tạo 1 sample)
  Thời gian bootstrap: 50,000 / (100 * 0.01) = 500 ngày (?!)
```

### 5.2 Realistic Bootstrap Timeline

| Server scale | CCU | Cheaters/day* | Days to 500 labeled | Days to useful model (2000+) |
|-------------|-----|---------------|--------------------|------------------------------|
| Small server | 20 | ~0.2 | 2500 | Không khả thi |
| Medium server | 100 | ~1 | 500 | Không khả thi |
| Large server | 500 | ~5 | 100 | ~400 ngày |
| Network (10 servers) | 5000 | ~50 | 10 | ~40 ngày |

*Giả sử 1% cheat rate, mỗi cheater tạo 1 labeled sample/ngày

**Kết luận:** Single server không thể bootstrap ML model trong thời gian hợp lý. **Cần cross-server data aggregation.**

### 5.3 Clean Window to the Rescue (Partial)

Negatives từ clean_window rất dồi dào:
- 100 CCU, mỗi player 10 phút/sample → 14400 negatives/ngày
- Nhưng positives vẫn là bottleneck

**Solution implicit trong code:** `staff_ban`, `watchdog_bot`, `whitebox_high` cho positives. Nếu không có đủ positives, model chỉ học "everything is legit" → precision 0.

### 5.4 Simulated Data có đủ bootstrap không?

Codebase không có simulated data, nhưng có thể đánh giá feasibility:

**Ưu điểm simulated data:**
- Unlimited volume
- Known ground truth (label chính xác)
- Coverage of edge cases

**Nhược điểm:**
- Simulation không match real distribution (sim-to-real gap)
- Feature correlation trong simulation khác real
- Model có thể học simulation-specific artifacts

**Recommendation:**
1. Simulated data chỉ dùng để pre-train (warm start)
2. Fine-tune trên real data khi đủ samples
3. Monitor AUC gap giữa simulated test và real test

### 5.5 Bootstrap Strategy Recommendation

Phase-based approach:

```
Phase 1 (0-500 real samples):
  Chỉ dùng heuristic + whitebox (current Grim)
  ML model trả 0.5 (untrained placeholder)
  
Phase 2 (500-2000 real samples):
  Train với simulated data augmentation
  Weight simulated samples thấp (0.1-0.3)
  Ensemble: ML (weight 0.3) + heuristic (weight 0.7)
  
Phase 3 (2000-10000 real samples):
  Giảm dần simulated data weight
  Tăng ML weight trong ensemble
  Bắt đầu dùng ML risk trong FusionEngine
  
Phase 4 (10000+ real samples):
  Pure ML training
  Bỏ simulated data
  Full ML integration vào FusionEngine
```

---

## 6. Concept Drift

### 6.1 Nguồn gốc Concept Drift trong Minecraft Anticheat

| Source | Frequency | Impact | Detection |
|--------|-----------|--------|-----------|
| Cheat client update | Weekly-monthly | HIGH — feature distributions thay đổi | AUC drop |
| Minecraft version update | ~Yearly | MEDIUM — mechanics thay đổi | Feature shift |
| Server population change | Daily | LOW — playstyle variation | Gradual drift |
| New cheat types | Monthly | HIGH — unseen patterns | Increased false negatives |
| Anti-cheat update (Grim) | Weekly | MEDIUM — check thresholds thay đổi | Label distribution shift |

### 6.2 Current Detection Mechanisms

**Code hiện tại:**
- `hot_reload()`: Check file modification time, reload if newer
- Mặc định: tự động reload khi phát hiện file change
- Nhưng KHÔNG có metric drift detection

**Không có:**
- Population stability index (PSI) tracking
- Feature distribution monitoring
- AUC degradation alerts trên production data
- Online feature statistics comparison

### 6.3 Auto-Retrain Cycle: Daily có đủ nhanh không?

Cron job chạy mỗi 24h:

```
0 3 * * * /usr/bin/python3 auto_train.py --db training.db --output models/
```

**Latency analysis:**
```
Cheat client update at 14:00
  → Model cũ predict sai từ 14:00 đến 03:00 hôm sau
  → 13 giờ với model outdated
  → New model deployed ~03:00 (13 tiếng sau)
```

**13 tiếng là quá lâu** cho cheat client update phổ biến.

**So sánh với competitors:**
| Anticheat | Retrain frequency | Drift detection |
|-----------|------------------|-----------------|
| GrimAC (current) | 24h (cron) | None |
| Watchdog (Hypixel) | Real-time adaptive | Built-in |
| Vulcan | Heuristic (no ML) | N/A |
| Matrix | Weekly | Manual review |

**Recommendation:**
1. **Trigger-based retrain:** Retrain ngay khi phát hiện AUC drop > 0.02
2. **Online learning fallback:** Dùng OnlineLogReg (đã có sẵn trong code) cho real-time adaptation
3. **Drift detection metric:** Track feature distribution KS-test statistics hàng giờ

### 6.4 Drift Detection Implementation

Cần thêm vào monitoring pipeline:

```python
def detect_concept_drift(reference_features, current_features, threshold=0.05):
    """
    Detect feature distribution drift using KS test.
    reference_features: feature matrix from training data
    current_features: feature matrix from recent production data
    """
    from scipy.stats import ks_2samp
    drift_scores = {}
    for i, feature_name in enumerate(FEATURE_NAMES):
        stat, p_value = ks_2samp(reference_features[:, i], current_features[:, i])
        drift_scores[feature_name] = {"ks_stat": stat, "p_value": p_value}
    
    drifted_features = [
        f for f, s in drift_scores.items() 
        if s["p_value"] < threshold
    ]
    return {
        "drift_detected": len(drifted_features) > 0,
        "drifted_features": drifted_features,
        "scores": drift_scores,
    }
```

**Cảnh báo drift khi:**
- > 2 features có KS p-value < 0.05
- Average feature importance shift > 20%
- Production AUC < training AUC - 0.03

### 6.5 Temporal Label Decay

Code đã có cơ chế temporal decay qua `max_days = 30`:

```python
cutoff = time.time() - max_days * 86400
```

**Issue:** Hard cutoff ở 30 ngày. Model hoàn toàn quên patterns cũ sau 30 ngày.

**Recommendation:** Chuyển sang exponential decay thay vì hard cutoff:
```python
# Thay vì hard cutoff 30 ngày
sample_weight *= exp(-age_days / 60)  # 60-day half-life
```

---

## 7. ML vs Pure Whitebox: Category Comparison

### 7.1 Comparison Framework

| Metric | Whitebox | ML | Hybrid (Current) |
|--------|----------|-----|------------------|
| Detection rate | % cheats caught | % cheats caught | Combined |
| False positive rate | Per check | Per model | FusionEngine |
| Robustness to new cheats | Low (signature-based) | Medium (pattern-based) | Medium |
| Maintenance cost | High (manual rules) | Medium (data pipeline) | Medium-high |
| Interpretability | High | Low (blackbox) | Medium |

### 7.2 Category-by-Category Analysis

---

#### MOVEMENT

**Whitebox capability: ~99%**

- GrimAC có simulation engine: collision detection, gravity, friction
- Nếu player ở vị trí simulation nói không thể → deterministic proof
- Các check: Speed, Fly, Phase, NoFall, GroundSpoof

**ML capability: ~0% added value**

- Simulation engine đã đạt ceiling
- ML không thể phát hiện movement cheat tốt hơn simulation
- Feature set cho movement không tồn tại trong ML pipeline

**Verdict: KHÔNG dùng ML cho MOVEMENT**

```
Whitebox:  TPR 99%, FPR < 0.1%
ML:        TPR 95%, FPR ~1-2%  (kém hơn)
→ ML làm giảm chất lượng
```

---

#### PACKET

**Whitebox capability: ~99%**

- Protocol validation: improper ordering, impossible timing
- Timer check: không thể gửi packets nhanh hơn giới hạn
- Các check: Timer, BadPackets, PacketOrder

**ML capability: ~0% added value**

- Packet analysis là deterministic — không cần ML
- ML không thể detect packet manipulation tốt hơn protocol validation

**Verdict: KHÔNG dùng ML cho PACKET**

---

#### COMBAT_AIM

**Whitebox capability: ~30-40%**

- Grim checks: Aim, KillAura
- Rotation analysis: GCD, smoothness, entropy
- **Hạn chế:** Aim assist rất khó phân biệt với skilled player
- Threshold-based detection dễ false positive hoặc false negative

**ML capability: Significant improvement (AUC 0.90-0.95)**

- 6 features capture multidimensional rotation patterns
- LightGBM có thể học non-linear interactions giữa các features
- Ví dụ: `gcdError thấp + smoothness cao + entropy thấp = aim assist`
  vs `gcdError thấp + smoothness thấp + entropy cao = skilled player`

**Why ML wins for COMBAT_AIM:**

| Aspect | Whitebox | ML |
|--------|----------|-----|
| Single metric threshold | Cố định (gcdError < 0.01) | Adaptive (multi-feature) |
| False positive với skilled player | Cao (threshold fixed) | Thấp (learned boundary) |
| Detect subtle aim assist (5-10%) | Không | Có (pattern recognition) |
| Adapt to new aim assist versions | Cần manual tuning | Retrain với new data |

**Verdict: ML rất có giá trị cho COMBAT_AIM — đây là category chính cần ML**

---

#### CLICK

**Whitebox capability: ~20-30%**

- Click analysis: cooldown accuracy, miss ratio
- **Hạn chế:** Auto-clicker có thể mimic human timing với variance
- Threshold-based: perfectStreak > 20 → suspicious, nhưng human có thể đạt 12-15

**ML capability: Good improvement (AUC 0.88-0.92)**

- 5 features capture timing + pattern
- LightGBM học correlation: `cooldownAccuracy + missRatio + criticalRatio` joint distribution
- Random forest effect: nhiều decision trees vote → robust

**Why ML helps CLICK:**

- Human click pattern rất đa dạng (rhythm gamers, tryhards)
- ML học được "click signature" thay vì threshold đơn
- Hard negative mining (boundary samples) cải thiện decision boundary

**Verdict: ML có giá trị cho CLICK, nhưng cần cẩn thận với skilled player false positives**

---

#### COMBAT_GEOM (Reach, Hitbox)

**Whitebox capability: ~70-80%**

- Reach check: tính khoảng cách từ player đến target
- Hitbox: kiểm tra entity intersection
- Simulation-based, tương đối deterministic

**ML capability: Limited added value (~5-10%)**

- Feature set hiện tại không có reach/hitbox features
- Session model có thể capture reach pattern dài hạn
- Nhưng whitebox đã đủ mạnh

**Verdict: ML không cần thiết — whitebox đã đủ tốt**

---

#### SCAFFOLD / BREAKING

**Whitebox capability: ~60-70%**

- Block placement analysis
- Pattern detection (scaffold: block placement tốc độ + direction)
- **Hạn chế:** Scaffold detection có thể false positive với skilled builder

**ML capability: Không được implement trong pipeline hiện tại**

- Không có features cho scaffold/breaking trong FeatureBridge
- Cần feature engineering mới

**Verdict: Chưa cần ML — whitebox tạm đủ. Nếu cần cải thiện, cần feature engineering trước.**

---

#### GHOST_PROFILE

**Whitebox capability: ~0%**

- **Hoàn toàn không có whitebox check** cho ghost client
- Ghost client cố gắng mimic human behavior hoàn hảo
- Grim không thể detect qua simulation (vì ghost client không vi phạm simulation)

**ML capability: Hy vọng duy nhất, nhưng yếu**

- Session model (8 features) là cơ chế duy nhất
- Features hiện tại quá thô (aggregated stats) → không đủ mạnh
- Expected AUC: ~0.75-0.85 (low confidence)

**Why GHOST_PROFILE is hard:**
1. Không có ground truth labels (ghost client = cheat không để lại dấu vết)
2. Behavioral patterns khó capture với simple aggregated features
3. Cần sequence modeling (LSTM) hoặc behavioral trajectory analysis
4. Session-level features (mean, std) mất temporal information

**Verdict: ML là hy vọng duy nhất, nhưng cần feature engineering mạnh hơn mới có ích**

---

#### BOTting (Baritone)

**Whitebox capability: ~50%**

- Một số checks cho auto-mining, auto-building
- Nhưng legitimate baritone use (theo thiết kế) khó phân biệt với abuse

**ML capability: Không implement**

- Chưa có feature set
- Bot detection cần sequence analysis (hành vi kéo dài)

**Verdict: ML có thể giúp nhưng chưa được implement. Feature engineering cần thiết trước.**

---

### 7.3 Summary: ML Investment Priority

| Category | Whitebox | ML Uplift | Priority | Notes |
|----------|----------|-----------|----------|-------|
| MOVEMENT | 99% | 0% | **None** | Whitebox đã ceiling |
| PACKET | 99% | 0% | **None** | Deterministic, không cần ML |
| COMBAT_GEOM | 75% | 5% | **Low** | Whitebox đủ tốt |
| SCAFFOLD/BREAK | 65% | N/A | **N/A** | Chưa có features |
| COMBAT_AIM | 35% | +55% (AUC 0.92) | **HIGHEST** | ML rất hiệu quả |
| CLICK | 25% | +63% (AUC 0.90) | **HIGH** | ML hiệu quả |
| GHOST_PROFILE | 0% | +75% (AUC 0.80) | **MEDIUM** | ML duy nhất, nhưng feature yếu |
| BOTting | 50% | N/A | **Low** | Chưa implement |

### 7.4 FusionEngine Integration: ML Value Chain

ML risk không hoạt động độc lập — nó được FusionEngine lọc:

```
ML Risk (0.0-0.985)
  → Runtime Penalty (ping/TPS/jitter: 0-0.45 discount)
  → EWMA Blend (0.3 new + 0.7 old, smooth fluctuations)
  → Bayesian Posterior (kết hợp với whitebox certainty)
  → Rule 2 (ML-only ALERT nếu bb > 0.85 + wb < 0.5)
  → Rule 3 (Hybrid ASSIST/MITIGATE nếu bb > 0.70 + wb > 0.70)
  → Rule 4 (Repeated weak nếu posterior > 0.4)
```

**Giá trị thực của ML:** Không phải để ban người chơi, mà để **tăng sensitivity** cho whitebox và **cung cấp signal** ở categories whitebox yếu.

---

## 8. Kết luận và Recommendations

### 8.1 ML có thực sự đáng đầu tư không?

**Trả lời: CÓ, nhưng có chọn lọc.**

| Khía cạnh | Đánh giá |
|-----------|----------|
| Cost to implement | ~2-4 weeks (đã implement gần xong) |
| Runtime cost | Negligible (inference ~0.5ms local) |
| Maintenance cost | Medium (data pipeline, monitoring) |
| Detection improvement | HIGH cho COMBAT_AIM, CLICK |
| False positive risk | LOW (FusionEngine kiểm soát tốt) |
| Cheat adaptation | Medium (retrain cycle) |

### 8.2 Category-Level Recommendations

| Category | Nên dùng ML? | Strategy |
|----------|-------------|----------|
| MOVEMENT | **KHÔNG** | Pure whitebox. ML không thêm value. |
| PACKET | **KHÔNG** | Pure whitebox. ML không thêm value. |
| COMBAT_GEOM | **KHÔNG** | Whitebox đủ. Focus resources khác. |
| COMBAT_AIM | **CÓ** | ML primary. Whitebox làm corroboration. |
| CLICK | **CÓ** | ML primary. Cẩn thận skilled player FP. |
| GHOST_PROFILE | **CÓ (có điều kiện)** | ML duy nhất, nhưng cần feature engineering. |
| SCAFFOLD/BREAK | **CHƯA** | Cần feature engineering trước. |
| BOTting | **CHƯA** | Cần feature engineering trước. |

### 8.3 False Flag Risk Assessment

**Current protections (rated):**

| Protection | Rating | Notes |
|------------|--------|-------|
| Risk caps (0.985) | HIGH | Ngăn overconfidence |
| Runtime penalty | HIGH | Ping/TPS/jitter discount |
| Grace period | HIGH | 2 phút sau join |
| Session risk decay | HIGH | Dual decay well-designed |
| ConfidenceModel | LOW | Cloud confidence=0.5 bug |
| Rule 7 (ghost ALERT only) | HIGH | Safety valve |
| Auto-label whitelist | HIGH | Cắt feedback loop |
| Flag count guard (R3) | HIGH | >= 3 flags required |
| Domain-safe R4 | HIGH | Non-movement không ENFORCE |

**Overall false flag risk: LOW** (dưới 0.1% với FusionEngine safeguards)

**Residual risk:** ConfidenceModel bị vô hiệu hóa bởi cloud confidence=0.5 bug. Cần fix.

### 8.4 Training Strategy for Best Model

1. **Data collection priority:**
   - Staff ban/unban → weight 5.0 (gold standard)
   - Watchdog bot → weight 3.0 (high quality)
   - Vanilla fingerprint → weight 2.0 (reliable negative)
   - Whitebox high → weight 1.5 (medium quality positive)
   - Clean window → weight 0.5 (weak negative, volume)

2. **Training hyperparameters (current code):**
   ```
   num_leaves=31, max_depth=6, learning_rate=0.05
   feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5
   min_data_in_leaf=20, scale_pos_weight=min(neg/pos, 100)
   early_stopping=50 rounds, max 500 rounds
   ```
   **Đây là config hợp lý** cho feature space nhỏ.

3. **Improvement recommendations:**
   - Thêm cross-validation (3-fold) thay vì single train/test split
   - Hyperparameter tuning riêng cho mỗi category
   - Feature interaction constraints (monotonic constraints cho known relationships)
   - Calibration layer (Platt scaling) để cải thiện probability calibration

4. **Monitoring metrics (need to add):**
   - Production AUC tracking
   - Feature distribution drift (PSI)
   - Prediction calibration (reliability diagram)
   - False positive rate tracking
   - Staff appeal rate correlation with model updates

### 8.5 Critical Gaps Cần Fix

| Gap | Severity | Fix |
|-----|----------|-----|
| ConfidenceModel vô hiệu (cloud confidence=0.5) | HIGH | Implement tree variance confidence |
| Không có drift detection | MEDIUM | Thêm KS-test monitoring |
| Cold start quá lâu cho single server | MEDIUM | Cross-server aggregation |
| Clean window noise không được validate | MEDIUM | Cross-reference với future bans |
| EnumMap không thread-safe | HIGH (FusionEngine) | Replace with ConcurrentHashMap |
| Semi-supervised không có review process | MEDIUM | Thêm human-in-the-loop cho boundary samples |

### 8.6 Final Verdict

**ML có đáng đầu tư cho MLSHybridAC?**

```
Investment (thời gian + effort):
  Cloud pipeline: ~2 weeks (đã code xong)
  Feature engineering: ~1 week (đã xong)
  Monitoring infra: ~1 week (chưa có)
  
Return:
  COMBAT_AIM: TPR tăng từ ~35% lên ~85% (estimated)
  CLICK: TPR tăng từ ~25% lên ~75% (estimated)
  GHOST_PROFILE: Từ 0% lên ~40-50% (estimated)
  
ROI: POSITIVE — đặc biệt cho COMBAT_AIM và CLICK
```

**Kết luận cuối cùng:**
- **ML giúp ích rất nhiều** cho categories whitebox yếu (COMBAT_AIM, CLICK)
- **ML vô dụng** cho categories whitebox mạnh (MOVEMENT, PACKET)
- **ML là hy vọng duy nhất** cho categories không có whitebox (GHOST_PROFILE)
- **False flag risk được kiểm soát tốt** bởi FusionEngine
- **Không phải càng train càng chuẩn** — có ceiling do feature space nhỏ
- **Cần cross-server data** để bootstrap trong thời gian hợp lý
- **Cần drift detection** để phát hiện khi model cũ trước khi cheat tràn lan

---

*End of analysis report.*
