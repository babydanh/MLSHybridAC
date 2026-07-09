# FusionEngine Analysis Report — MLSHybridAC

> Research conducted on 2026-07-10
> Codebase: `D:\Duancanhan\AC\Grim` (Java plugin) + `D:\Duancanhan\AC\cloud` (Python inference server)

---

## Table of Contents

1. [FusionEngine Complete Documentation](#1-fusionengine-complete-documentation)
   - [1.1 Architecture Overview](#11-architecture-overview)
   - [1.2 Seven Rules (R1-R7)](#12-seven-rules-r1-r7)
   - [1.3 Bayesian Posterior Formula](#13-bayesian-posterior-formula)
   - [1.4 Runtime Penalty (Ping/TPS/Jitter)](#14-runtime-penalty-pingtpsjitter)
   - [1.5 Session Risk Accumulator](#15-session-risk-accumulator)
   - [1.6 Category-Specific Decay Rates](#16-category-specific-decay-rates)
   - [1.7 Grace Period](#17-grace-period)
   - [1.8 Thread Safety](#18-thread-safety)
   - [1.9 AnomalyTracker Integration](#19-anomalytracker-integration)
   - [1.10 ConfidenceModel Integration](#110-confidencemodel-integration)
2. [Cloud Composite Prediction Analysis](#2-cloud-composite-prediction-analysis)
3. [FeatureBridge to Cloud to FusionEngine Data Flow](#3-featurebridge-to-cloud-to-fusionengine-data-flow)
4. [False Positive Prevention Analysis](#4-false-positive-prevention-analysis)
5. [Improvement Suggestions](#5-improvement-suggestions)
6. [Conclusion](#6-conclusion)

---

## 1. FusionEngine Complete Documentation

### 1.1 Architecture Overview

**File:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\FusionEngine.java`

FusionEngine is the central decision layer for the MLSHybridAC anticheat. It synthesizes four input groups to produce a graded action recommendation:

```
Input Groups:
  WhiteboxEvidence  (Grim checks: certainty + VL)
  + BlackboxRisk    (ML scores: 0.0-0.985, 0 if no ML)
  + RuntimeContext  (ping, TPS, jitter)
  + SessionState    (reputation, priorFlags, playtime)
  ──────────────────────────────────────────────
  → Action: OBSERVE / ALERT / ASSIST / SOFT_MITIGATE / ENFORCE
```

The system supports 10 categories:

| Category | Description | Key Checks |
|---|---|---|
| MOVEMENT | Speed, Fly, Phase, NoFall, GroundSpoof | Simulation engine |
| PACKET | Timer, BadPackets, PacketOrder | Protocol validation |
| COMBAT_GEOM | Reach, Hitbox abuse | Reach, Hitbox, Interact |
| COMBAT_AIM | AimAssist, KillAura, rotation | Aim, KillAura |
| CLICK | AutoClicker | Click patterns (planned) |
| SCAFFOLD | Block placement | Scaffold |
| BREAKING | Block break | Break checks |
| GHOST_PROFILE | Ghost client | Alert only, never enforce |
| BOTting | Baritone | Alert only, never enforce |
| WATCHDOG_BOT | Test bot hits | Deterministic |

### 1.2 Seven Rules (R1-R7)

The rules are evaluated in strict priority order (first match wins):

---

#### RULE 7: No-Auto-Enforce Domains (Highest Priority)

**Condition:** `whiteboxCategory == GHOST_PROFILE || whiteboxCategory == BOTting`

**Action:** `ALERT`

**Rationale:** GhostClient and Baritone auto-bots are NEVER auto-banned, regardless of certainty. They only generate staff alerts. This ensures staff review is required before any punitive action against these categories.

**Implementation details:**
- Fires BEFORE Rule 6 and Rule 1
- `isExempt` check is NOT applied (even exempt players get ALERT — but PunishmentManager's `OBSERVE` override for exempt players still applies after evaluation)
- Risk is NOT accumulated (no `accumulateRisk()` call)
- No action tier filtering: `ALERT` allows log + alert + webhook

---

#### RULE 6: Movement/Packet/WatchdogBot Domain Immutable

**Condition:** `(MOVEMENT || PACKET || WATCHDOG_BOT) && certainty >= 0.95 && !isExempt`

**Action:** `ENFORCE`

**Rationale:** Blackbox (ML) can NEVER override whitebox movement/packet truth. These domains have near-zero false-positive rates because:
- **MOVEMENT:** Based on the simulation engine (collision detection, gravity, friction) — if the player is at X but the simulation says they cannot be at X given their inputs, it is deterministic proof of cheating.
- **PACKET:** Protocol validation (improper packet ordering, impossible timing) — equally deterministic.
- **WATCHDOG_BOT:** Hitting a test bot is a deterministic test.

**Key detail:** Threshold is 0.95 (lower than Rule 1's 0.98) specifically because these domains have lower FP rates than general checks.

**Security:** `!isExempt` prevents staff/trusted players from being auto-enforced.

---

#### RULE 1: Deterministic Truth Wins

**Condition:** `whiteboxCertainty >= 0.98 && !isExempt`

**Action:** `ENFORCE`

**Rationale:** Any domain at very high certainty → enforce immediately. This covers cases not caught by Rule 6 (e.g., COMBAT_AIM at 0.98, SCAFFOLD at 0.98).

**Key detail:** Because Rule 6 fires first, MOVEMENT/PACKET/WATCHDOG_BOT at 0.95-0.979 are caught by R6. Rule 1 catches everything else at >=0.98.

**Risk accumulation:** `accumulateRisk(50, whiteboxCategory)` — adds 50 weight to session risk.

---

#### RULE 5: Bayesian Posterior Fusion (Applied Before Rules 2-4)

**Condition:** Always applied as a pre-processing step for Rules 2-4

**Computation:**
```java
double effectiveBlackboxRisk = blackboxRisk * (1.0 - runtimePenalty);
// Bayesian posterior formula:
double posterior = wb * bb / (wb * bb + (1-wb) * (1-bb));
```

For MOVEMENT/PACKET domains, posterior = whiteboxCertainty (no Bayesian blend — whitebox IS the truth).

**Confidence-adjusted thresholds:**
```java
double confidenceMul = getConfidenceThresholdMultiplier();
// confidenceMul = 1.0 + min(uncertainty / 10.0, 0.5)
// range: [1.0, 1.5]
double adjustedAlert = ALERT_THRESHOLD * confidenceMul;        // 50 * mul
double adjustedSoftMitigate = SOFT_MITIGATE_THRESHOLD * confidenceMul; // 150 * mul
double adjustedEnforce = ENFORCE_THRESHOLD * confidenceMul;    // 300 * mul
```

When the ConfidenceModel detects high uncertainty in ML predictions, all three thresholds scale up proportionally (max 1.5x).

---

#### RULE 2: ML Risk High Needs Corroboration

**Condition:** `effectiveBlackboxRisk >= 0.85 && whiteboxCertainty < 0.5`

**Action:** `ALERT`

**Sub-condition:** `whiteboxCertainty >= 0.2` → also `accumulateRisk(15, whiteboxCategory)` (only if there is some whitebox evidence — not zero)

**Rationale:** High blackbox risk with low whitebox certainty → notify staff but do NOT auto-enforce. This prevents ML-only false positives. The threshold `effectiveBlackboxRisk >= 0.85` ensures only very confident ML predictions trigger alerts.

**Limitation:** Because R2 fires before R3 and R4, a high blackbox risk combined with moderate whitebox (0.5-0.7) skips R2 entirely and falls through to R3/R4. This is by design — moderate whitebox changes the risk profile from "ML-only" to "corroborated."

---

#### RULE 3: Hybrid Escalation

**Condition:**
```java
whiteboxCertainty >= 0.70 && whiteboxCertainty < 0.95
&& blackboxRisk > 0.70
&& flagCountByCategory.getOrDefault(whiteboxCategory, 0) >= 3
```

**Actions:**
- `sessionRiskAccumulator >= adjustedSoftMitigate` → `SOFT_MITIGATE`
- Otherwise → `ASSIST`

**Rationale:** Medium whitebox + medium blackbox = corroborated evidence. The `flagCount >= 3` guard (added after the initial 0.50 threshold was found too low) ensures at least 3 flags in the same category exist before hybrid escalation triggers, filtering out single-flag flukes.

**Key change history:**
1. Original: `certainty >= 0.50` (VL ~7) → too many false escalations from marginal simulation flags
2. V2: `certainty >= 0.70` (VL ~15+) — filters marginal simulation flags (0.001 offset)
3. Added `flagCount >= 3` — prevents single-flag fluke escalation

---

#### RULE 4: Repeated Weak Evidence Escalates

**Condition:** `posterior >= 0.4`

**Action (depends on sessionRiskAccumulator):**
- `>= adjustedEnforce`:
  - MOVEMENT/PACKET/WATCHDOG_BOT only → `ENFORCE`
  - All other domains → `SOFT_MITIGATE` (never ENFORCE via R4 alone)
- `>= adjustedSoftMitigate` → `SOFT_MITIGATE`
- `>= adjustedAlert` → `ALERT`

**Accumulation:** `accumulateRisk(10, whiteboxCategory)` — lower weight per flag because certainty is moderate

**Critical security constraint:** For non-movement/packet domains (combat aim, click, scaffold, etc.), ENFORCE is NOT reachable via R4 alone. The session-risk threshold for those domains caps at SOFT_MITIGATE. This prevents a long tail of low-certainty flags from producing a false-positive ban on domains where certainty is inherently less reliable.

---

#### DEFAULT: OBSERVE

**Condition:** No rule matches

**Action:** `OBSERVE`

**Rationale:** Log internal, accumulate risk. No notification to staff.

---

### 1.3 Bayesian Posterior Formula

**Formula:**
```
posterior = whiteboxCertainty × effectiveBlackboxRisk
            ────────────────────────────────────────────────────
            (whiteboxCertainty × effectiveBlackboxRisk) +
            (1 - whiteboxCertainty) × (1 - effectiveBlackboxRisk)
```

**Behavior analysis:**

| wb | bb | posterior | Interpretation |
|---|---|---|---|
| 0.90 | 0.90 | 0.988 | Both high → very high (corroboration bonus) |
| 0.90 | 0.50 | 0.900 | Whitebox dominates |
| 0.50 | 0.90 | 0.900 | Blackbox dominates |
| 0.80 | 0.30 | 0.632 | One moderate, one low → moderate |
| 0.30 | 0.30 | 0.155 | Both low → low |
| 0.70 | 0.70 | 0.845 | Both moderate → moderate-high |
| 0.99 | 0.50 | 0.990 | Very high wb dominates |
| 0.50 | 0.99 | 0.990 | Very high bb dominates |

**Important:** For MOVEMENT and PACKET categories, posterior = whiteboxCertainty (no Bayesian blend). This is because whitebox IS the truth for these domains.

The posterior is used in Rule 4 (`posterior >= 0.4` threshold). It is NOT used in Rules 1-3 (they use raw whiteboxCertainty and effectiveBlackboxRisk separately).

---

### 1.4 Runtime Penalty (Ping/TPS/Jitter)

**File:** `FusionEngine.java` lines 673-697

The runtime penalty is a discount factor applied to blackbox risk. It ranges from `[0.0, 0.45]`.

#### Ping-based Penalty

| Ping | Penalty | Rationale |
|---|---|---|
| < 100ms | 0.0 | Network is good, features are reliable |
| 100-200ms | 0.1 | Slight delay, minor feature degradation |
| 200-300ms | 0.25 | Significant delay, features less reliable |
| > 300ms | 0.45 | Extreme delay, features unreliable |

#### Jitter Sanity Check (Anti-Exploit)

```
if jitter > 50ms AND penalty > 0.25:
    cap penalty at 0.25
```

**Security rationale:** A player who intentionally spikes their ping (to get the 0.45 penalty and avoid enforcement) is only allowed a partial discount. This prevents "lag to avoid enforcement" exploitation.

The baseline ping is computed via a 10-second EWMA:
```java
baselinePing = (long)(baselinePing * 0.9 + current * 0.1); // ~10s window
```

Jitter = `|currentPing - baselinePing|`

#### TPS Penalty (Additive)

| TPS | Penalty | Rationale |
|---|---|---|
| >= 19.5 | 0.0 | Server healthy |
| 18 - 19.5 | +0.1 | Mild lag |
| < 18 | +0.25 | Significant server lag |

**Total penalty capped at 0.45** so blackbox risk is never fully nullified.

#### TPS Hysteresis (Safe Mode)

```java
TPS_FREEZE = 15.0;   // Once frozen, don't resume until 17.0
TPS_RESUME = 17.0;
```

**Behavior:**
- TPS >= 17 → Normal (all rules active, after resume)
- TPS 15-17 → Reduced (whitebox only, blackboxRisk = 0)
- TPS < 15 → Frozen (OBSERVE everything — only vanilla Grim)

The `tpsFrozen` boolean implements hysteresis: once frozen at 15 TPS, the system won't resume until 17 TPS. This prevents rapid on/off cycling near threshold (e.g., 15.1 → 14.9 → 15.1).

---

### 1.5 Session Risk Accumulator

**Model:**
```java
sessionRiskAcc = Σ(weight × exp(-λ × Δt))
```

Two decay paths:
1. **Per-flag decay** (in `accumulateRisk()`): Applied before adding new weight. Uses `getCategoryDecay()` for the flag's category.
2. **Time-based decay** (in `applyTimeDecay()`): Applied between `evaluate()` calls. Uses `DECAY_BACK_LAMBDA = 0.005` (~2.3-minute half-life) — faster decay so clean play reduces risk within minutes.

**Thresholds (base, before ConfidenceModel modulation):**

| Level | Threshold | Action Tier |
|---|---|---|
| Alert | 50 | ALERT |
| Soft Mitigate | 150 | SOFT_MITIGATE |
| Enforce | 300 | ENFORCE |

**Flag weights:**

| Source | Weight |
|---|---|
| Rule 1/6 ENFORCE | 50 |
| Rule 3 (hybrid escalation) | 20 |
| Rule 2 (ML-only high risk) | 15 |
| Rule 4 (repeated weak evidence) | 10 |

**Session risk reset behavior:**
- After enforcement: `resetSessionRisk(sessionRisk * 0.5)` — halves instead of zeroing to prevent yo-yo exploit
- On player reconnect: also halves (`onPlayerJoin()`) — prevents relog-to-clear exploit
- SuspicionCheck: `resetSessionRisk(sessionRisk * 0.5)` — same half-life pattern

---

### 1.6 Category-Specific Decay Rates

Decay rates are used in `accumulateRisk()` for per-flag decay:

| Category Group | Lambda | Half-Life | Rationale |
|---|---|---|---|
| MOVEMENT, PACKET, WATCHDOG_BOT | 0.001 | ~30 min | High confidence, deterministic |
| COMBAT_GEOM, SCAFFOLD, BREAKING | 0.002 | ~5.8 min | Medium FP rate |
| COMBAT_AIM, CLICK | 0.003 | ~3.8 min | Higher FP rate, faster decay |

This means:
- A MOVEMENT flag at t=0 contributes weight 50. At t=30min, it contributes 50 × exp(-0.001 × 1800) = 50 × 0.165 = 8.3.
- A CLICK flag at t=0 contributes weight 10. At t=30min, it contributes 10 × exp(-0.003 × 1800) = 10 × 0.0045 = 0.045.

Combat aim and click domains decay faster because they have inherently higher false-positive rates — their risk shouldn't persist unfairly.

---

### 1.7 Grace Period

```java
GRACE_PERIOD_MS = 120_000L;    // 2 minutes
GRACE_COOLDOWN_MS = 300_000L;  // 5 minutes
```

**Behavior:**
- On first join (or after 5+ minutes offline): `isNewPlayer = true`, timer starts
- For 2 minutes after join: if FusionEngine returns ENFORCE, PunishmentManager **downgrades to ALERT**
- After 2 minutes: grace expires, full enforcement resumes

**Relog exploit protection:**
- If a player relogs within 5 minutes, grace is NOT renewed
- Session risk is halved on reconnect (not zeroed)
- This prevents: (1) reconnecting to get a fresh grace window, and (2) reconnecting to clear session risk

```java
public void onPlayerJoin() {
    this.sessionRiskAccumulator *= 0.5; // half-life on reconnect
    long now = System.currentTimeMillis();
    // Grant grace period only if enough time has passed since last disconnect.
    if (now - joinTimeMs > GRACE_COOLDOWN_MS || joinTimeMs == 0) {
        this.isNewPlayer = true;
        this.joinTimeMs = now;
    }
}
```

---

### 1.8 Thread Safety

FusionEngine state is per-player (one FusionEngine instance per GrimPlayer). There are no shared global states.

**Callers:**
1. **Game thread** (primary): `evaluate()` called from `PunishmentManager.handleAlert()`
2. **ML worker thread** (async): `setBlackboxRisk()` called from `FeatureBridge.submitMLInference()` via `BoundedMLQueue`
3. **Async tick**: `updateAnomalyScore()` called from `AnomalyTracker.tick()`
4. **Packet thread**: `onPlayerJoin()` called on reconnect

**Synchronization mechanisms:**
- No explicit synchronization on FusionEngine fields (e.g., `blackboxRiskByCategory`, `sessionRiskAccumulator`)
- The `blackboxRiskByCategory` is updated from the ML pool (async) and read from the game thread in `evaluate()`
- This creates a **benign data race**: the Java Memory Model guarantees that a final field (like `player`) is visible after construction, but mutable fields (`sessionRiskAccumulator`, `blackboxRiskByCategory`) may not be immediately visible to other threads
- In practice, the impact is minimal because FusionEngine uses EWMA blends and time decay — a slightly stale read of `blackboxRiskByCategory` just means using the previous value for one evaluation cycle
- The ConfidenceModel IS internally synchronized (ReentrantReadWriteLock), so `updateConfidence()` and `getConfidenceThresholdMultiplier()` are thread-safe

**Risk:** A more serious race condition: `evaluate()` reads `blackboxRiskByCategory` while `setBlackboxRisk()` writes to it. Since both use `ConcurrentHashMap`-backed `EnumMap`... wait, `EnumMap` is NOT thread-safe. However, the FusionEngine uses vanilla `java.util.EnumMap`, which is NOT thread-safe.

**Verdict:** There is a potential `ConcurrentModificationException` or stale read on `blackboxRiskByCategory` during concurrent access. The `EnumMap` is not designed for concurrent read/write. This should be addressed.

---

### 1.9 AnomalyTracker Integration

**File:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\ml\AnomalyTracker.java`

The AnomalyTracker runs every async tick (20 TPS on a separate thread from the game thread). It:

1. Reads player features from FeatureBridge
2. Updates per-player statistical profiles (predictionOffset, playerSpeed, interPacketTime, yawStddev, CPS, reach)
3. Computes overall anomaly score
4. Pushes anomaly score to FusionEngine via `updateAnomalyScore()`

**FP protections in AnomalyTracker:**
- Skips during server lag (TPS < 18)
- Skips if player is in vehicle
- Skips lag spikes (inter-packet time > 200ms)
- Requires 100 samples before scoring begins (PlayerProfile logic)

**Confidence multiplier mapping (FusionEngine):**

| Anomaly Score | Multiplier | Meaning |
|---|---|---|
| < 0.3 | 1.0x | Player behaving normally |
| 0.3 - 0.7 | 1.0x -> 1.2x | Slightly anomalous, gentle boost |
| 0.7 - 0.9 | 1.2x -> 1.5x | Clearly anomalous, stronger boost |
| > 0.9 | 1.5x (capped) | Highly anomalous (but never >1.5x) |

**Security:** The multiplier is capped at 1.5x so it can never cause a flag by itself — it only amplifies existing heuristic confidence.

**Potential issue:** The anomaly multiplier compounds with the flag multiplier (also 1.0x to 1.25x), leading to a combined multiplier of up to 1.5 × 1.25 = 1.875x, which could theoretically push a marginal certainty (e.g., 0.52) close to Rule 3's 0.70 threshold. However, the `Math.min(1.0, certainty * multiplier)` cap in `evaluate()` prevents overflow beyond 1.0.

---

### 1.10 ConfidenceModel Integration

**File:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\ConfidenceModel.java`

The ConfidenceModel is a Bayesian logistic regressor with burst detection:

- **5 features:** predictionDelta, uncertaintyDelta, rawScore, recentVariance, timeSinceLastBurst
- **Online update:** stochastic natural-gradient approximation to variational Bayesian logistic regression
- **Burst detection:** EWMA-based deviation tracking with configurable threshold (default 2.5 sigma)

**Integration with FusionEngine:**
1. `updateConfidence(risk)` is called when new ML risk arrives (from cloud or local fallback)
2. Features are computed from the delta between current and previous prediction
3. Label: 1.0 if risk > 0.5 (anomalous), 0.0 otherwise
4. `getConfidenceThresholdMultiplier()` computes a threshold modulation factor:
   - uncertainty = model's predictive variance on a neutral feature vector
   - multiplier = `1.0 + min(uncertainty / 10.0, 0.5)` → range [1.0, 1.5]

**Effect:** When ML predictions are uncertain (high variance, bursts), all three decision thresholds scale up, making enforcement harder to trigger. When uncertainty is low, thresholds return to baseline.

**Limitation:** The ConfidenceModel is updated from `fallbackAim()` and `fallbackSession()` but NOT from the cloud path. Cloud inference calls `updateConfidence()` with the `resp.confidence()` value (from the PredictionResponse), but the cloud server's `_cap_risk()` does not return a meaningful confidence value — the `PredictionResponse.confidence` field defaults to 0.5. This means the ConfidenceModel's threshold modulation is only effective when the fallback OnlineLogReg models are used (cloud offline). When the cloud is online, the model receives confidence=0.5 from every prediction, which provides no meaningful uncertainty signal.

---

## 2. Cloud Composite Prediction Analysis

### 2.1 Current Implementation

**Endpoint:** `POST /v1/predict/all` (server.py line 250)

**Current composite formula:**
```python
aim_weight = 0.4
click_weight = 0.3
session_weight = 0.1
wb_weight = 0.2

composite = (aim_risk * 0.4 + click_risk * 0.3 + session_risk * 0.1 + wb_avg * 0.2)
composite = _cap_risk(composite)  # cap at max_risk_cap (default 0.985)
```

### 2.2 Analysis of Current Composite

**Strengths:**
- Simple and predictable
- Returns per-category risks separately (aim_risk, click_risk, session_risk) in addition to composite
- The per-category risks are what actually get used (via setBlackboxRisk)

**Weaknesses:**
- **Weighted average is not used for anything.** The client (FeatureBridge/submitMLInference) does NOT use the composite_risk from the response — it only uses the per-category risks (aim_risk, click_risk, session_risk) via `setBlackboxRisk()`. The composite is computed but never consumed.
- **Whitebox_certainties integration is questionable.** The `/v1/predict/all` endpoint accepts `whitebox_certainties` and computes `wb_avg`, but this is a simple average across all checks, which loses category-specific information.
- **Session risk has half the cap (0.85)** on the cloud side but FusionEngine already independently caps at 0.985.
- **No runtime context considered.** The composite formula does not incorporate ping, TPS, or jitter — these are handled independently by FusionEngine on the client.

### 2.3 Cloud vs Local Fusion Design Question

**Should the cloud run a copy of FusionEngine?**

Arguments AGAINST:
- FusionEngine is already complete and runs locally per-player
- Replicating the 7-rule state machine on the cloud adds complexity (duplicated logic, synchronization issues)
- Session risk accumulation MUST be local (per-player, real-time)
- The cloud already returns per-category risks independently — FusionEngine already handles fusion

Arguments FOR:
- Could enable server-side composite review and cross-server coordination
- Could use richer data (aggregate statistics from all players) for threshold modulation

**Recommendation:** Do NOT duplicate FusionEngine on the cloud. The current design (cloud returns raw per-category risks, FusionEngine handles fusion locally) is the correct separation of concerns. The cloud's job is ML prediction, not policy enforcement.

### 2.4 Should the Cloud Return 3 Separate Risks Instead of Composite?

The cloud ALREADY returns 3 separate risks (`aim_risk`, `click_risk`, `session_risk`). The `composite_risk` is computed but unused.

**Recommendation:** Remove the composite computation from `/v1/predict/all` to simplify the endpoint. The response should just return `{ aim_risk, aim_confidence, click_risk, click_confidence, session_risk, session_confidence, model_version, server_timestamp }`.

### 2.5 Cloud Confidence Issue

The cloud server's `PredictionResponse` includes a `confidence` field that defaults to 0.5 in the schema:
```python
class PredictionResponse(BaseModel):
    risk: float = Field(..., ge=0.0, le=0.985)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
```

However, the predict endpoints never populate `confidence` — they return the default 0.5. This means:
- FusionEngine's `updateConfidence()` receives 0.5 from every cloud prediction
- The ConfidenceModel receives a constant value and cannot learn meaningful uncertainty
- The threshold modulation via `getConfidenceThresholdMultiplier()` is effectively disabled when the cloud is online

**Recommendation:** Either (a) compute proper confidence from the LightGBM model (e.g., variance of tree predictions, calibration error), or (b) remove the ConfidenceModel integration from the cloud path and only use it for local fallback models.

---

## 3. FeatureBridge to Cloud to FusionEngine Data Flow

### 3.1 Detailed Flow Diagram

```
Game Thread (every tick)                    ML Worker Thread (async)          Cloud Server
═══════════════════════                     ══════════════════════           ═══════════════
                                                                             
FeatureBridge.tick()                                                        
  │                                                                          
  ├── collect per-tick features                                              
  ├── computeProvisionalRisk()                                               
  │     (heuristic risk → FusionEngine.setBlackboxRisk())                    
  │                                                                          
  └── submitMLInference()                                                    
        │                                                                    
        ├── extractAimFeatures()                                             
        ├── extractClickFeatures()                                           
        ├── extractSessionFeatures()                                         
        │                                                                    
        └── BoundedMLQueue.submit(player, lambda) ──────→                   
                                                          │                  
                                                          ├── predictAim() ──────────→ POST /v1/predict/aim
                                                          │     .thenAccept(resp →   → returns PredictionResponse{risk, confidence})
                                                          │       fusion.setBlackboxRisk(resp.risk(), COMBAT_AIM)                          
                                                          │       fusion.updateConfidence(resp.confidence())                              
                                                          │     .exceptionally(ex → fallbackAim())                                       
                                                          │                                                                              
                                                          ├── predictClick() ────────→ POST /v1/predict/click
                                                          │     .thenAccept(resp →   → returns PredictionResponse{risk})
                                                          │       fusion.setBlackboxRisk(resp.risk(), CLICK)                             
                                                          │                                                                              
                                                          └── predictSession() ──────→ POST /v1/predict/session
                                                                .thenAccept(resp →   → returns PredictionResponse{risk})
                                                                  fusion.setBlackboxRisk(resp.risk(), GHOST_PROFILE)                   
                                                                  fusion.updateConfidence(resp.confidence())                           
                                                                                                                                       
GAME THREAD (on check flag)                                                                                                             
                                                                              
PunishmentManager.handleAlert()                                              
  │                                                                          
  ├── certainty = mapVlToCertainty(check.violations)                         
  ├── category = classifyCheck(check)                                        
  ├── fusion.onFlag(category)  (increment flagCount)                         
  ├── bbRisk = fusion.getBlackboxRisk(category)                              
  ├── fusionAction = fusion.evaluate(certainty, category, bbRisk, category)  
  │     │                                                                    
  │     ├── anomalyScore → getAnomalyMultiplier()                            
  │     ├── flagCount → getFlagMultiplier()                                  
  │     ├── applyTimeDecay()                                                 
  │     ├── computeRuntimePenalty()                                          
  │     ├── TPS hysteresis check                                             
  │     ├── R7: GHOST_PROFILE/BOTting → ALERT                               
  │     ├── R6: MOVEMENT/PACKET/WB >= 0.95 → ENFORCE                        
  │     ├── R1: >= 0.98 → ENFORCE                                            
  │     ├── R5: Bayesian posterior + confidence modulation                   
  │     ├── R2: bb >= 0.85 + wb < 0.5 → ALERT                              
  │     ├── R3: wb >= 0.70 + bb > 0.70 + flagCount >= 3 → ASSIST/MITIGATE  
  │     └── R4: posterior >= 0.4 → ALERT/MITIGATE/ENFORCE per domain        
  │                                                                          
  ├── Grace period check (downgrade ENFORCE → ALERT)                        
  ├── Exempt check (→ OBSERVE)                                               
  ├── Auto-train ML (if certainty >= 0.95)                                  
  ├── Weak label ML (if aim/click pattern)                                   
  ├── Evidence packet (if ENFORCE)                                           
  └── Command execution (filtered by fusionAction tier)                      
```

### 3.2 Key Observations About the Flow

1. **Heuristic pre-population:** `computeProvisionalRisk()` runs every tick on the game thread and pushes heuristic risk to FusionEngine via `setBlackboxRisk()`. This provides baseline risk BEFORE the async cloud inference completes.

2. **EWMA blend:** `setBlackboxRisk()` uses `0.3 * newRisk + 0.7 * oldRisk(decayed)`. This smooths out fluctuations and prevents single anomalous predictions from dominating.

3. **Race condition in setBlackboxRisk:** The heuristic path (game thread) and cloud path (ML worker, via BoundedMLQueue) both call `setBlackboxRisk()` for the same category. Since the category is the key in `blackboxRiskByCategory` (an `EnumMap` — NOT thread-safe), concurrent writes could cause data corruption.

4. **Unused composite endpoint:** The `predictAll()` endpoint exists but is never called from `submitMLInference()`. The client calls individual endpoints (`predictAim`, `predictClick`, `predictSession`) separately.

5. **BoundedMLQueue acts as a buffer:** The queue decouples the game thread from the async ML worker. If the queue is full, jobs are silently dropped (bounded), and the system falls back to heuristic risk values.

---

## 4. False Positive Prevention Analysis

Each FP prevention mechanism, assessed for effectiveness:

### 4.1 Risk Caps

| Risk Type | Cap | Effectiveness |
|---|---|---|
| Aim/Click blackbox | 0.985 | Prevents absolute certainty — even the best ML prediction can't claim 100% |
| Session blackbox | 0.85 | Lower cap for session model (less reliable, more FP-prone) |
| Heuristic risk | 0.70 | Temporary cap (Phase 3 placeholder) — prevents heuristics from dominating |
| Composite | 0.985 | Final safety net |

**Assessment:** Effective. The caps are conservative and prevent ML overconfidence. The 0.985 cap (not 1.0 or 0.99) is a deliberate margin that leaves room for doubt.

### 4.2 Runtime Penalty

**Mechanism:** Ping 100-300ms → penalty 0.1-0.45; TPS < 19.5 → +0.1 to +0.25; Jitter > 50ms → cap at 0.25

**Effectiveness:** HIGH. This is a mature pattern adapted from BakiVF. The jitter sanity check is particularly important as it prevents intentional lag exploitation.

**Vulnerability:** The jitter check only triggers when jitter > 50ms AND penalty > 0.25. A sophisticated player could maintain ping of 250ms with jitter of 40ms (just under the 50ms threshold) and still get a 0.25 penalty. However, 0.25 penalty is already a significant reduction, and sustained 250ms ping is itself a disadvantage.

### 4.3 Grace Period

**Mechanism:** 2 minutes after join, ENFORCE is downgraded to ALERT. Grace is NOT extended by rapid relogging.

**Effectiveness:** HIGH for the intended use case (legit players with lag spikes on first join). The 5-minute relog cooldown is a good anti-exploit measure.

**Limitation:** 2 minutes may be too short for players on unstable connections (e.g., satellite internet, cellular). Consider making this configurable.

### 4.4 Session Risk Decay

**Mechanism:**
- Per-flag decay: weighted by category half-life (30min for movement, 3.8min for aim/click)
- Time-based decay between evaluate() calls: λ=0.005 (2.3min half-life)

**Effectiveness:** HIGH. The dual decay is well-designed. Per-flag decay ensures past cheating doesn't unfairly penalize a player who has stopped, while time-based decay ensures clean play gradually reduces risk.

### 4.5 ConfidenceModel Threshold Modulation

**Mechanism:** When ML uncertainty is high, response thresholds scale up (max 1.5x). Alert threshold goes from 50 to 75, soft mitigate from 150 to 225, enforce from 300 to 450.

**Effectiveness:** LOW in current implementation. As analyzed in §1.10, the cloud path always sends confidence=0.5, so the model never learns meaningful uncertainty from cloud predictions. The threshold modulation only works when the local fallback models are active.

**Recommendation:** Either (a) implement proper confidence estimation on the cloud, or (b) decouple the ConfidenceModel from the cloud path and only use it for local fallback models.

### 4.6 Rule 7: Ghost Profile ALERT Only

**Mechanism:** GHOST_PROFILE and BOTting categories are hardcoded to return ALERT, regardless of certainty.

**Effectiveness:** HIGH. This is a deliberate safety valve for the two highest-risk categories (ghost client detection is inherently uncertain; bot detection can false-positive on legitimate baritone use).

### 4.7 Category Whitelist for Auto-Label

**Mechanism:** Only MOVEMENT, PACKET, and WATCHDOG_BOT are eligible for auto-training with label=1.0. COMBAT_AIM, CLICK, COMBAT_GEOM, SCAFFOLD, BREAKING, GHOST_PROFILE, and BOTting are explicitly excluded.

**Effectiveness:** HIGH. This prevents the most dangerous feedback loop: training ML models on data that was itself influenced by ML predictions. The whitelisted categories are deterministic — their whitebox detections are ground truth, not influenced by blackbox.

### 4.8 Feedback Loop Protection

**Analysis of the feedback loop risk:**

The feedback loop would look like:
1. ML model returns risk 0.80 for category X
2. FusionEngine incorporates this risk into its decision
3. If action is ENFORCE, the system auto-labels this as cheat
4. Next ML training cycle trains on this labeled data
5. ML model learns: "if I output high risk, I'll get reinforced"

**Current protections:**
- Auto-training only applies to MOVEMENT/PACKET/WATCHDOG_BOT (pure whitebox) — these categories don't use blackbox risk in the Bayesian blend, so ML can't influence the decision
- Hybrid categories (COMBAT_AIM, CLICK, etc.) are NOT auto-labeled
- Weak labeling (from heuristic patterns) uses label=0.8 (not 1.0) and has strict guards (certainty >= 0.85, flagCount > 5, specific metric thresholds)

**Assessment:** The feedback loop protection is well-designed. The key insight — only training on categories where the decision is purely whitebox — completely severs the loop.

### 4.9 FP Prevention Summary

| Mechanism | Effectiveness | Notes |
|---|---|---|
| Risk caps | HIGH | Conservative, prevents overconfidence |
| Runtime penalty | HIGH | Jitter sanity check prevents exploitation |
| Grace period | HIGH | Relog protection is thorough |
| Session risk decay | HIGH | Dual decay is well-designed |
| ConfidenceModel | LOW | Broken by cloud confidence=0.5 issue |
| Rule 7 | HIGH | Hardcoded safety valve |
| Auto-label whitelist | HIGH | Prevents feedback loop |
| Flag count guard (R3) | HIGH | Prevents single-flag fluke escalation |
| Domain-safe R4 | HIGH | Non-movement domains can't ENFORCE via R4 alone |
| Exempt system | HIGH | Staff/trusted players excluded |
| TPS hysteresis | HIGH | Prevents rapid cycling near threshold |

---

## 5. Improvement Suggestions

### 5.1 Critical Issues

**1. EnumMap is NOT thread-safe (BUG)**

The `blackboxRiskByCategory` and `blackboxLastUpdateByCategory` fields are `EnumMap` instances, accessed from both the game thread (in `evaluate()`) and the ML worker thread (in `setBlackboxRisk()`). `java.util.EnumMap` is not thread-safe and can throw `ConcurrentModificationException` or produce stale reads.

**Fix:** Replace with `synchronized` blocks or use `ConcurrentHashMap` (which implements `Map` and can be used similarly):
```java
private final Map<Category, Double> blackboxRiskByCategory = new ConcurrentHashMap<>();
private final Map<Category, Long> blackboxLastUpdateByCategory = new ConcurrentHashMap<>();
```

Note: `ConcurrentHashMap` is slightly slower than `EnumMap` for single-threaded access, but the lookup inside `evaluate()` (via `getBlackboxRisk()` which stream-finds the max) is already O(n) and happens at most once per flag. The performance impact is negligible.

**2. Cloud confidence=0.5 makes ConfidenceModel ineffective**

The cloud server always returns `confidence=0.5` in `PredictionResponse`. This means FusionEngine's `updateConfidence()` receives a meaningless value, and `getConfidenceThresholdMultiplier()` never modulates thresholds when the cloud is online.

**Fix:** Implement proper confidence estimation on the cloud:
```python
# LightGBM can return variance across trees:
def predict_with_confidence(model, features):
    preds = model.predict(features, num_iteration=model.best_iteration, pred_leaf=True)
    # variance of leaf predictions → uncertainty estimation
    # Then normalize to [0, 1]
    ...
```

Or simpler: remove confidence from the cloud path entirely and only use ConfidenceModel for local fallback models.

### 5.2 Architecture Improvements

**3. Remove `/v1/predict/all` composite endpoint**

The composite endpoint computes a weighted average that is never consumed by the client. The individual endpoints (`/v1/predict/aim`, `/v1/predict/click`, `/v1/predict/session`) are what actually get called.

**Fix:** Deprecate and remove the composite endpoint to reduce confusion and maintenance burden.

**4. Consider removing heuristic provisional risk after Phase 3**

The heuristic risk in `computeProvisionalRisk()` (aim, click, auto-jump, cross-correlation, trigger bot) is a Phase 2 placeholder. When real ML models are deployed in Phase 3, these heuristics should be replaced entirely.

**Current risk:** The heuristic code path and the ML code path both write to `FusionEngine.setBlackboxRisk()` for the same categories. Even with the EWMA blend, this creates inconsistency — the heuristic might set COMBAT_AIM risk to 0.6, then 50ms later the ML sets it to 0.8, then the EWMA blends them to 0.66. The heuristic and ML signals are not meaningfully combined.

**Fix:** In Phase 3, disable `computeProvisionalRisk()` when ML is active and the queue is not dropping jobs.

**5. BoundedMLQueue job limit needs monitoring**

The `BoundedMLQueue` silently drops jobs when full. On a busy server with many players, this could mean ML inference is rarely performed, and the system operates almost entirely on heuristics.

**Fix:** Add a metric/counter for dropped ML jobs. If the drop rate exceeds a threshold, either increase queue capacity or reduce inference frequency.

### 5.3 Medium-Priority Improvements

**6. Grace period should be configurable**

The 2-minute grace period is hardcoded:
```java
private static final long GRACE_PERIOD_MS = 120_000L;
```

For servers with high-latency players (e.g., cross-region), 2 minutes may be insufficient. Consider making this configurable in `config.yml`.

**7. EvidencePacket should be persisted**

The `EvidencePacket` is constructed in `PunishmentManager.handleAlert()` when ENFORCE fires, but it is currently just a Java object — it's not written to any database or log.

**Fix:** Implement a persistence layer for EvidencePackets (e.g., JSON logging, SQLite, or the grim_hybrid_evidence table referenced in the design docs).

**8. SuspicionCheck thresholds are independent of ConfidenceModel modulation**

SuspicionCheck uses hardcoded thresholds (350, 200, 100) that are NOT modulated by the ConfidenceModel. While SuspicionCheck is a separate check from FusionEngine, this inconsistency means that when ML uncertainty is high and FusionEngine thresholds scale up, SuspicionCheck still fires at the same thresholds.

**Fix:** Either remove SuspicionCheck and let FusionEngine handle all escalation, or wire SuspicionCheck thresholds through the ConfidenceModel.

**9. Weak label thresholds may be too aggressive**

```java
// Click weak label:
cooldownAccuracy > 0.98 && perfectStreak > 20

// Aim weak label:
smoothness > 0.95 && jerk < 0.05
```

These thresholds are deliberately high (as the comments note), but they create a dead zone where legitimate players who happen to have very consistent aim or click patterns are correctly NOT flagged but also NOT labeled. This means the model doesn't learn from the most borderline cases.

**Fix:** Consider adding semi-supervised labeling for the dead zone (0.85-0.94 certainty) where the model trains with label=0.5 (uncertain) instead of 0.8 or 1.0.

### 5.4 Minor Issues

**10. `accumulateRisk(weight)` overload is unused**

The no-category overload calls `accumulateRisk(weight, Category.MOVEMENT)` as default. This overload is never used — all callers pass a category. Remove the dead code.

**11. Jitter field is sent as hardcoded 0**

In `RemoteInferenceClient.predictAim()`:
```java
body.put("jitter", 0);
```

This should compute actual jitter from the `LagProfile`:
```java
body.put("jitter", fb.getLagProfile().getJitter());
```

**12. Session refresh rate every 100 ticks is inconsistent with flag rate**

Session inference runs every 100 ticks (5 seconds). But a session model is meant to capture long-term behavioral patterns — running it every 5 seconds is excessive. Consider 600 ticks (30 seconds) or event-driven (on flag).

---

## 6. Conclusion

### 6.1 Is FusionEngine Strong Enough?

**Yes, in its current form, FusionEngine is a well-designed decision layer.** The 7-rule priority system, Bayesian posterior fusion, session risk accumulation, category-specific decay rates, and runtime penalty form a comprehensive and mature foundation.

**Strengths:**
1. Clear rule priority (R7 before R6 before R1 before R5 before R2 before R3 before R4)
2. Strong FP prevention (caps, flag counts, category whitelists, domain-safe R4)
3. Session risk with dual-decay (per-flag decay + time-based decay)
4. Runtime context awareness (ping, TPS, jitter, TPS hysteresis)
5. Grace period with relog protection
6. Feedback loop protection (auto-train only on pure whitebox categories)
7. Confidence model for threshold modulation (though currently limited by cloud confidence)

### 6.2 What Needs Fixing

**Critical (high risk):**
1. **EnumMap thread safety** — `blackboxRiskByCategory` uses `EnumMap` which is NOT thread-safe. Concurrent access from game thread and ML worker thread can cause data corruption. **Fix priority: HIGH.**

**Important (medium risk):**
2. **Cloud confidence=0.5** — The ConfidenceModel's threshold modulation is effectively disabled when the cloud is online. **Fix priority: HIGH.**
3. **Unused composite endpoint** — `/v1/predict/all` computes a composite that nobody consumes. **Fix priority: LOW (cleanup).**
4. **Jitter field hardcoded to 0** — Cloud requests always send jitter=0 instead of actual jitter from LagProfile. **Fix priority: MEDIUM.**

### 6.3 ML Training Pipeline Issues

1. **Auto-training coverage is limited:** Only MOVEMENT/PACKET/WATCHDOG_BOT categories produce auto-labels. This means the session model gets trained on movement/packet data but NOT on combat/click data, which limits its usefulness for ghost client detection.

2. **No data augmentation:** The training pipeline (cloud/training/train.py) likely has no data augmentation for class imbalance. Cheat samples are rare compared to legitimate samples.

3. **No periodic retraining trigger:** The `/v1/train/trigger` endpoint exists but there's no automated retraining schedule. Models will become stale over time as the game client changes.

4. **Weak label quality is unverified:** The weak labeling logic (`weakLabelML()` in PunishmentManager) has high thresholds (cooldownAccuracy > 0.98, smoothness > 0.95), but the labeled data quality is not validated before being sent to the cloud.

### 6.4 Overall Assessment

FusionEngine is a mature, comprehensive fusion layer that correctly integrates whitebox (deterministic) and blackbox (ML-based) detection with runtime awareness and session history. The architecture is well-designed with strong FP prevention.

The two critical issues (EnumMap thread safety, cloud confidence) should be addressed before production deployment. The remaining suggestions are refinements that would improve robustness and maintainability but are not blocking.

The separation of concerns — cloud handles ML prediction, FusionEngine handles policy — is the correct architectural choice. Do NOT duplicate FusionEngine logic on the cloud server.

---

*End of analysis report.*
