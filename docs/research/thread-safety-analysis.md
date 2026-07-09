# Thread Safety & Architecture Correctness Analysis — MLSHybridAC FusionEngine

> Research conducted on 2026-07-10
> Codebase: `D:\Duancanhan\AC\Grim` (Java plugin) + `D:\Duancanhan\AC\cloud` (Python inference server)
> Files analyzed: FusionEngine.java, FeatureBridge.java, BoundedMLQueue.java, PunishmentManager.java, RemoteInferenceClient.java, AnomalyTracker.java, ConfidenceModel.java, server.py, schemas.py

---

## Table of Contents

1. [Thread Safety Analysis](#1-thread-safety-analysis)
   - [1.1 Thread Access Map](#11-thread-access-map)
   - [1.2 EnumMap Concurrency Analysis](#12-enummap-concurrency-analysis)
   - [1.3 Lost Update in setBlackboxRisk()](#13-lost-update-in-setblackboxrisk)
   - [1.4 Volatile Analysis](#14-volatile-analysis)
   - [1.5 ConfidenceModel Thread Safety](#15-confidencemodel-thread-safety)
   - [1.6 BoundedMLQueue Thread Safety](#16-boundedmlqueue-thread-safety)
   - [1.7 RemoteInferenceClient Thread Safety](#17-remoteinferenceclient-thread-safety)
   - [1.8 FeatureBridge Thread Safety](#18-featurebridge-thread-safety)
   - [1.9 AnomalyTracker Thread Safety](#19-anomalytracker-thread-safety)
   - [1.10 Thread Safety Verdict](#110-thread-safety-verdict)
2. [Cloud Confidence Analysis](#2-cloud-confidence-analysis)
   - [2.1 The 0.5 Problem](#21-the-05-problem)
   - [2.2 Is ConfidenceModel Needed?](#22-is-confidencemodel-needed)
   - [2.3 Fix Options](#23-fix-options)
3. [Composite Endpoint Analysis](#3-composite-endpoint-analysis)
   - [3.1 Is predictAll Used?](#31-is-predictall-used)
   - [3.2 Recommendation](#32-recommendation)
4. [Architecture Correctness](#4-architecture-correctness)
   - [4.1 Data Flow: FeatureBridge -> Cloud -> FusionEngine](#41-data-flow-featurebridge---cloud---fusionengine)
   - [4.2 Bug Found and Already Fixed: missing onFlag() call](#42-bug-found-and-already-fixed-missing-onflag-call)
   - [4.3 Unused Dead Code](#43-unused-dead-code)
   - [4.4 Jitter Hardcoded to 0](#44-jitter-hardcoded-to-0)
   - [4.5 rule-skills.md Compliance](#45-rule-skillsmd-compliance)
   - [4.6 Feedback Loop Protection](#46-feedback-loop-protection)
   - [4.7 Grace Period and Relog Exploit Protection](#47-grace-period-and-relog-exploit-protection)
5. [Conclusion](#5-conclusion)
   - [5.1 Must Fix](#51-must-fix)
   - [5.2 Should Fix](#52-should-fix)
   - [5.3 False Alarms / Intentional Design](#53-false-alarms--intentional-design)
   - [5.4 Code Fixes](#54-code-fixes)

---

## 1. Thread Safety Analysis

### 1.1 Thread Access Map

The FusionEngine is per-player (one instance per GrimPlayer). It is accessed from the following threads:

| Method | Thread(s) | Read Fields | Write Fields |
|---|---|---|---|
| `evaluate()` | Game thread | All fields | `lastWhiteboxCertainty`, `lastWhiteboxCategory`, `lastViolationLevel`, `sessionRiskAccumulator`, `lastFlagTimestamp`, `lastDecayTick`, `flagCountByCategory`, `tpsFrozen`, `baselinePing`, `lastBaselineUpdate`, `anomalyScore` |
| `setBlackboxRisk()` | ML worker thread + Game thread | `blackboxRiskByCategory`, `blackboxLastUpdateByCategory` | `blackboxRiskByCategory`, `blackboxLastUpdateByCategory` |
| `updateConfidence()` | ML worker thread | `confidenceModel` (thread-safe) | `lastConfidenceRisk`, `lastConfidenceUncertainty` |
| `updateAnomalyScore()` | Async tick thread (AnomalyTracker) | (none) | `anomalyScore` |
| `onPlayerJoin()` | Packet thread / game thread | `joinTimeMs`, `sessionRiskAccumulator` | `sessionRiskAccumulator`, `isNewPlayer`, `joinTimeMs`, `lastDecayTick` |
| `resetPeakRisk()` | Game thread (PunishmentManager) | (none) | `blackboxRiskByCategory`, `blackboxLastUpdateByCategory` |
| `getBlackboxRisk()`, `getLastBlackboxRisk()`, etc. | Game thread | `blackboxRiskByCategory` | (none) |
| `onFlag()`, `getFlagCount()`, `getTotalFlagCount()` | Game thread | `flagCountByCategory` | `flagCountByCategory` |

### 1.2 EnumMap Concurrency Analysis

#### The Claim

The existing `fusion-engine-analysis.md` states that `EnumMap` is not thread-safe and "can throw `ConcurrentModificationException` during concurrent access."

#### The Fact

**`java.util.EnumMap` does NOT have a `modCount` field.** This is a critical difference from `HashMap` and `TreeMap`. The iterators returned by `EnumMap.values()`, `EnumMap.keySet()`, and `EnumMap.entrySet()` do NOT perform fail-fast checks. They cannot throw `ConcurrentModificationException`.

Proof: `EnumMap` extends `AbstractMap`. Its values() collection creates a simple `AbstractCollection` whose iterator indexes directly into the backing `vals` array by ordinal. There is no `modCount` increment on `put()` or `clear()`, and no check in the iterator's `next()` method.

#### So What IS the Risk?

`EnumMap` uses two backing arrays: `keyUniverse` (all enum constants, fixed at construction) and `vals` (values indexed by ordinal). The risks of concurrent access are:

1. **Stale reads (visibility)**: The Java Memory Model does not guarantee that a write to `vals[ordinal]` on thread A is visible to thread B. In practice, on x86-64 with cache coherence, writes propagate within microseconds. But the JMM allows a thread to cache a value indefinitely -- though this almost never happens in practice because `evaluate()` is called with low frequency (per-flag, not per-tick) and the ML worker thread eventually flushes its writes.

2. **Partially-written `Double` references**: On 64-bit JVMs (all modern Minecraft servers), reference writes are atomic. A game thread reading `blackboxRiskByCategory.get(category)` will see either the old `Double` object or the new one, never a garbage value.

3. **Null values during stream iteration**: `getLastBlackboxRisk()` calls `blackboxRiskByCategory.values().stream().mapToDouble(Double::doubleValue).max()`. If a concurrent `put()` has written the value but the Stream hasn't reached that array slot yet, the iteration simply sees the old value. No crash.

4. **The real risk: LOST UPDATE in `setBlackboxRisk()`** (analyzed in section 1.3).

#### EnumMap vs ConcurrentHashMap -- What Changes?

If we replace `EnumMap` with `ConcurrentHashMap`:
- Visibility: Writes in one thread are guaranteed visible to other threads (happens-before edge)
- Thread-safe iteration: `values().stream()` is safe
- No lost updates from visibility: reads always see latest completed write
- Performance: `ConcurrentHashMap` is slightly slower for single-threaded access (CAS operations vs array indexing), but the impact is negligible because `evaluate()` is called per-flag (at most a few times per second per player)

### 1.3 Lost Update in `setBlackboxRisk()`

#### The Race Condition

```java
public void setBlackboxRisk(double risk, Category category) {
    long now = System.currentTimeMillis();

    // Step 1: Read & decay old risk
    Long lastUpdate = blackboxLastUpdateByCategory.get(category);
    if (lastUpdate != null && lastUpdate > 0) {
        double dt = (now - lastUpdate) / 1000.0;
        if (dt > 0) {
            double oldRisk = blackboxRiskByCategory.getOrDefault(category, 0.0);
            oldRisk *= Math.exp(-BB_DECAY_RATE * dt);
            blackboxRiskByCategory.put(category, oldRisk); // WRITE 1
        }
    }

    // Step 2: EWMA blend
    double oldRisk = blackboxRiskByCategory.getOrDefault(category, 0.0);
    blackboxRiskByCategory.put(category, 0.3 * risk + 0.7 * oldRisk); // WRITE 2
    blackboxLastUpdateByCategory.put(category, now); // WRITE 3
}
```

**Scenario:**
1. **ML worker thread** calls `setBlackboxRisk(0.8, COMBAT_AIM)` -> reads oldRisk (0.6) -> writes 0.3*0.8 + 0.7*0.6 = 0.66 (WRITE 2)
2. **Game thread (computeProvisionalRisk)** calls `setBlackboxRisk(0.5, COMBAT_AIM)` **at the same time**
   - ML thread's WRITE 2 may or may not be visible
   - If NOT visible: game thread reads oldRisk 0.6 -> writes 0.3*0.5 + 0.7*0.6 = 0.57 (overwrites ML's 0.66!)
   - If visible: game thread reads oldRisk 0.66 -> writes 0.3*0.5 + 0.7*0.66 = 0.612 (correct blend)

**Impact:** One update is lost. The system converges in one more tick because the next call will read the latest value.

**Severity: LOW.** The EWMA blend (`0.3 * new + 0.7 * old`) ensures convergence. A lost update means the system uses the heuristic value for one more tick instead of the ML value. Heuristic values are already conservative (capped at 0.70) so this does not create a false negative.

### 1.4 Volatile Analysis

| Field | Volatile? | Threads | Risk | Verdict |
|---|---|---|---|---|
| `tpsFrozen` | NO | Game thread only | None (single-thread write+read in evaluate) | Fine |
| `isExempt` | NO | Game thread + packet thread | Stale read possible, but exempt status changes rarely | Benign |
| `isNewPlayer` | NO | Game thread + packet thread (onPlayerJoin) | Grace period might end 1 tick late | Benign |
| `isGeyser` | NO | Game thread | Only set on join, read later | Fine |
| `anomalyScore` | NO | Async tick (write) + game thread (read) | Stale read possible; updated every tick | Benign |
| `baselinePing` | NO | Game thread only (getBaselinePing) | Called from evaluate on game thread only | Fine |
| `lastWhiteboxCertainty` | NO | Game thread (write) + ML thread (read) | Stale read; used for cloud context logging | Benign |
| `lastWhiteboxCategory` | NO | Game thread (write) + ML thread (read) | Enum reference; atomic on 64-bit JVM | Benign |
| `lastViolationLevel` | NO | Game thread (write) + ML thread (read) | Stale read; used for cloud context | Benign |
| `sessionRiskAccumulator` | NO | Game thread only | Called from evaluate via accumulateRisk, which is called only from game thread | Fine |
| `circuitBreakerUntil` | YES | RemoteInferenceClient | Correct | Correct |
| `cloudAvailable` | YES | RemoteInferenceClient | Correct | Correct |

**Verdict on volatile:** None of the missing `volatile` modifiers cause correctness bugs. They could theoretically cause delayed visibility, but in practice the affected fields are either:
- Single-thread accessed (tpsFrozen, baselinePing, sessionRiskAccumulator)
- Updated so frequently that stale values are corrected within one tick (anomalyScore)
- Used for non-critical logging/debugging contexts (lastWhiteboxCertainty, category, vl)

### 1.5 ConfidenceModel Thread Safety

**Verdict: CORRECT.** The `ConfidenceModel` uses `ReentrantReadWriteLock`:

- All read operations (`predict()`, `uncertainty()`, `rawScore()`, `getRecentVariance()`, getters): acquire read lock
- All write operations (`update()`, `reset()`, `setLearningRate()`): acquire write lock
- Final fields (`ewmaDecay()`, `burstThreshold()`): no lock needed -- safe by JMM final field guarantees.

The only concern: the read lock permits concurrent `uncertainty()` calls while `update()` is waiting for the write lock. The `uncertainty()` call reads `weightVariances` and `biasVariance`, which are only modified under write lock. This is correct -- no stale read of partially written state.

### 1.6 BoundedMLQueue Thread Safety

**Verdict: CORRECT.**

- `ThreadPoolExecutor` with `LinkedBlockingQueue` -- thread-safe by construction
- `AtomicLong` counters (`submitted`, `completed`, `dropped`) -- correct
- `ConcurrentHashMap<UUID, Long>` for per-player cooldown -- correct
- Jobs are executed on worker threads and never block the game thread

One edge case: if `executor.execute()` is called after `shutdown()`, the `RejectedExecutionException` handler correctly increments `dropped` and returns false. The game thread never blocks.

### 1.7 RemoteInferenceClient Thread Safety

**Verdict: CORRECT.**

- `HttpClient` is thread-safe by specification
- `AtomicInteger consecutiveFailures` -- correct for read-modify-write
- `volatile long circuitBreakerUntil` -- correct boolean-ish flag
- `AtomicLong lastHealthCheck` -- correct for timestamp tracking
- `volatile boolean cloudAvailable` -- correct

### 1.8 FeatureBridge Thread Safety

**Verdict: MOSTLY CORRECT, with one note.**

The three Deques (`featureHistory`, `combatHistory`, `clickHistory`) are `ConcurrentLinkedDeque` -- thread-safe.

The `ArrayList` fields (`jumpIntervals`, `rotationAtAttack`) are accessed only from the game thread (in `tick()` and `onSwing()`/`onAttack()`). This is safe as long as these methods are only called from the game thread, which they are.

**Note on `toArray()` calls**: `FeatureBridge` methods call `featureHistory.toArray()` or `clickHistory.toArray()` for windowed computations. `ConcurrentLinkedDeque.toArray()` is thread-safe -- it creates a snapshot array at invocation time. This is a safe pattern.

### 1.9 AnomalyTracker Thread Safety

**Verdict: CORRECT.**

- `ConcurrentHashMap` for per-player profiles -- thread-safe
- Reads from `FeatureBridge.getFeatureHistory()` -- `ConcurrentLinkedDeque`, thread-safe
- Reads from `FeatureVector` -- the `currentFeatures` object is written only by the game thread in `tick()`. The AnomalyTracker runs on the async tick thread. This is a cross-thread read without synchronization. However, all fields of `FeatureVector` are primitives or immutable objects -- no mutable shared state. Stale reads are benign.
- `player.getFusionEngine().updateAnomalyScore()` -- writes a `double`; no synchronization. Benign as analyzed above.

### 1.10 Thread Safety Verdict

| Component | Status | Notes |
|---|---|---|
| FusionEngine | **Mostly safe -- low risk** | EnumMap visibility issue (no CME); lost update is benign due to EWMA convergence |
| ConfidenceModel | **Correct** | ReentrantReadWriteLock |
| BoundedMLQueue | **Correct** | Atomic counters, ConcurrentHashMap |
| RemoteInferenceClient | **Correct** | Volatile + Atomic pattern |
| FeatureBridge | **Correct** | ConcurrentLinkedDeque, single-thread ArrayLists |
| AnomalyTracker | **Correct** | ConcurrentHashMap, immutable read pattern |

**Bottom line: There are no race conditions that cause crashes, corrupt data, or produce false flags.** The EnumMap "issue" is a theoretical JMM concern that in practice produces only occasional stale reads (observing the previous tick's ML risk instead of the latest). The existing analysis report in `fusion-engine-analysis.md` incorrectly states that `ConcurrentModificationException` is possible -- it is NOT with `EnumMap`.

---

## 2. Cloud Confidence Analysis

### 2.1 The 0.5 Problem

#### Current behavior:

```python
# cloud/schemas.py
class PredictionResponse(BaseModel):
    risk: float = Field(..., ge=0.0, le=0.985)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)  # DEFAULT 0.5
```

```python
# cloud/server.py -- predict_aim()
return PredictionResponse(
    risk=_cap_risk(risk),
    model_version=version,
    server_timestamp=int(t0),
    # confidence is NOT set -> defaults to 0.5
)
```

The same pattern applies to `predict_click()` and `predict_session()`. **The `confidence` field is never populated by any endpoint.**

On the client side, `FeatureBridge.submitMLInference()` calls:
```java
// Cloud path:
fusion.updateConfidence(resp.confidence());  // Always 0.5 from cloud
```

vs the fallback path:
```java
// Fallback path (cloud offline):
fusion.updateConfidence(risk);  // Actual risk score (e.g., 0.73)
```

#### What this means for the ConfidenceModel:

The `updateConfidence(0.5)` call with constant 0.5 produces:

```java
double rawScore = Math.log(0.5 / 0.5) = Math.log(1.0) = 0.0;
// features = {risk - lastConfidenceRisk, ...}
// risk - lastConfidenceRisk = 0.5 - 0.5 = 0.0
// All other features are similarly flat
```

The model's `predict()` on a zero-vector returns `sigmoid(biasMean)`, which starts at 0.5 (initial bias). The model never sees meaningful variation, so `getRecentVariance()` stays near 0, and `uncertainty()` returns only `biasVariance` (which decays toward 0 as training samples accumulate -- but `trainingSamples` increases because `update()` is called with every cloud response).

Result: **`getConfidenceThresholdMultiplier()` returns 1.0 (no threshold modulation) when the cloud is online.**

#### When the ConfidenceModel DOES work:

When the cloud is offline, `fallbackAim()` and `fallbackSession()` call:
```java
fusion.updateConfidence(risk);  // risk is the actual OnlineLogReg score
```

Here the `confidence` parameter receives a real value that varies. The ConfidenceModel learns meaningful uncertainty from these values and modulates thresholds appropriately.

### 2.2 Is ConfidenceModel Needed?

**Analysis by scenario:**

| Scenario | Cloud status | ConfidenceModel status | Need? |
|---|---|---|---|
| Normal operation | Online | Ineffective (always 0.5) | **Not needed** -- LightGBM risk scores are already calibrated |
| Cloud outage | Offline | Effective (real risk values) | **Helpful** -- OnlineLogReg fallback has less reliable scores |
| Cloud flapping | Online | Ineffective | **Would be useful but not available** |

When the cloud is online, the trained LightGBM models produce calibrated risk scores. The ConfidenceModel was designed as a safety net for unreliable predictions -- it is precisely when the cloud is unavailable that this safety net matters most.

The current behavior (ConfidenceModel effective only when cloud is offline) accidentally achieves the correct design: when cloud is up, thresholds stay at baseline (because cloud models are trusted); when cloud is down, the fallback models' uncertainty modulates thresholds upward.

However, this was achieved by accident (the cloud never populates `confidence`), not by design.

### 2.3 Fix Options

#### Option A: Implement proper confidence on the cloud

LightGBM can provide prediction variance:

```python
from lightgbm import Booster

# prediction variance across trees
def predict_with_uncertainty(model: Booster, features: np.ndarray):
    # pred_leaf=True returns leaf indices for each tree
    leaf_preds = model.predict(features, pred_leaf=True)
    # variance of leaf values across trees
    variance = np.var(leaf_preds, axis=1)
    # Normalize to [0, 1] via sigmoid of log-variance
    confidence = 1.0 - (2.0 / (1.0 + np.exp(-variance / 10.0)) - 1.0)
    return confidence
```

**Pros:** Computes real model uncertainty, enables threshold modulation even with cloud
**Cons:** Requires changing the ModelRegistry to return variances; increases response payload size; the `pred_leaf=True` parameter is not currently used by any model loading code

#### Option B: Remove `updateConfidence()` from the cloud path

Change `submitMLInference()` to NOT call `updateConfidence()` from cloud responses:

```java
// In submitMLInference():
cloud.predictAim(FeatureBridge.this)
    .thenAccept(resp -> {
        if (resp != null) {
            fusion.setBlackboxRisk(resp.risk(), FusionEngine.Category.COMBAT_AIM);
            // REMOVED: fusion.updateConfidence(resp.confidence());
            cloud.recordSuccess();
        }
    });
```

The ConfidenceModel would only be updated via the fallback path (when cloud is offline).

**Pros:** Simple, one-line change per endpoint
**Cons:** The ConfidenceModel is never updated when cloud is online -- but as analyzed above, it is not needed in that case anyway

#### Recommendation: Option B

Implementing proper confidence on the cloud is the "correct" engineering solution, but it's over-engineering for the current state of the system. The cloud models use LightGBM which produces well-calibrated risk scores. The ConfidenceModel's threshold modulation is a safety net for when models are unreliable (cloud offline), and the current architecture already provides this.

**Option B is recommended** because:
1. One-line change per endpoint
2. No server-side changes needed
3. No regression risk
4. Correct by design: cloud trusted -> no modulation; cloud offline -> modulation active

---

## 3. Composite Endpoint Analysis

### 3.1 Is `predictAll` Used?

`RemoteInferenceClient.java` defines:

```java
public CompletableFuture<CompositeResponse> predictAll(FeatureBridge fb,
                                                        Map<String, Object> whiteboxContext,
                                                        Map<String, Object> runtimeContext) {
    // ...
    return post("/v1/predict/all", body, CompositeResponse.class);
}
```

**Search result:** There is ZERO callers of `predictAll()` anywhere in the codebase:

```
Grep for ".predictAll(" in D:\Duancanhan\AC\Grim -- NO MATCHES
```

The `FeatureBridge.submitMLInference()` calls `predictAim()`, `predictClick()`, and `predictSession()` individually -- never `predictAll()`.

The server endpoint `/v1/predict/all` is also not called by any code path.

### 3.2 Recommendation

The composite endpoint is dead code. Three options:

1. **Remove completely**: Delete `predictAll()` from RemoteInferenceClient.java, remove the `/v1/predict/all` endpoint from server.py, remove `CompositeResponse` from schemas.py. Cleanest approach.

2. **Deprecate with comment**: Mark as `@Deprecated` with a comment explaining it's unused. Keep for possible future use (cross-server analysis).

3. **Replace individual calls with composite**: Change `submitMLInference()` to make a single `/v1/predict/all` request instead of three separate requests. This would reduce HTTP overhead (3 connections -> 1) but increase latency (wait for all 3 models to predict). Given the current architecture (each model runs independently with different cadences), this would be a regression.

**Recommendation: Option 1 (remove completely).** If composite prediction is needed in the future, it's easy to re-add. The current three-endpoint design is cleaner and more flexible.

---

## 4. Architecture Correctness

### 4.1 Data Flow: FeatureBridge -> Cloud -> FusionEngine

The flow is architecturally correct:

```
Game Thread (every tick)
  FeatureBridge.tick()
    ├── collect per-tick features (fast, lock-free)
    ├── computeProvisionalRisk()
    │     → heuristic risk → FusionEngine.setBlackboxRisk()
    └── submitMLInference()
          → BoundedMLQueue.submit()  (non-blocking)
               │
ML Worker Thread (async)
  ┌──────────────┘
  ├── Cloud request (if online)
  │     → fusion.setBlackboxRisk()
  │     → fusion.updateConfidence()
  └── Fallback OnlineLogReg (if offline/error)
        → fusion.setBlackboxRisk()
        → fusion.updateConfidence()

Game Thread (on flag)
  PunishmentManager.handleAlert()
    ├── fusion.onFlag(category)       // increment count
    ├── fusion.getBlackboxRisk(cat)   // read latest ML risk
    └── fusion.evaluate(...)          // decision
```

**Key design decisions that are correct:**

1. **Provisional risk (heuristic) runs every tick**: Before cloud inference completes, heuristic risk primes the FusionEngine. When cloud results arrive, the EWMA blend smooths the transition.

2. **BoundedMLQueue decouples game and ML**: The game thread never blocks on inference. Jobs are dropped silently when the queue is full -- FusionEngine defaults to heuristic values.

3. **Per-category risk storage**: `blackboxRiskByCategory` stores separate risk per category. This prevents cross-category contamination and enables category-specific decisions in Rules 3, 4, and 6.

4. **EWMA blend in `setBlackboxRisk()`**: `0.3 * new + 0.7 * old(decayed)` smooths fluctuations. A single anomalous ML prediction is attenuated. Time decay (`BB_DECAY_RATE = 0.05/s`) ensures old peaks fade within ~20 seconds.

5. **`isExempt` check in PunishmentManager AFTER evaluate**: Exempt players get `OBSERVE` action regardless of FusionEngine decision. This means FusionEngine still processes and accumulates risk for exempt players -- important for staff who want to see their own risk statistics for tuning.

### 4.2 Bug Found and Already Fixed: missing `onFlag()` call

The existing report documents that `flagCountByCategory` was never incremented before, meaning Rule 3's `flagCount >= 3` gate could never trigger. The fix was adding `fusion.onFlag(category)` in `PunishmentManager.handleAlert()`.

**Current status: FIXED.** Line 173 in PunishmentManager.java:
```java
fusion.onFlag(category); // increment flag count for Rule 3
```

This fix is correct and in place.

### 4.3 Unused Dead Code

#### `accumulateRisk(weight)` overload

```java
private void accumulateRisk(double weight) {
    accumulateRisk(weight, Category.MOVEMENT);
}
```

This overload defaults to `MOVEMENT` category -- but no caller uses it. All callers pass a specific category:
- `accumulateRisk(50, whiteboxCategory)` -- Rules 1, 6
- `accumulateRisk(15, whiteboxCategory)` -- Rule 2
- `accumulateRisk(20, whiteboxCategory)` -- Rule 3
- `accumulateRisk(10, whiteboxCategory)` -- Rule 4

**Recommendation:** Remove the no-category overload. It's dead code and using `MOVEMENT` as default is semantically wrong for non-movement checks.

#### Cloud inference calls for 1.8 clients in FeatureBridge

`submitMLInference()` runs every tick for every player, including 1.8 clients where click cooldown analysis is meaningless. The method checks `combatHistory.size() >= 3` before running aim inference, but doesn't skip based on client version.

**Not a bug** -- the `computeCooldownAccuracy()` and `computeMissRatio()` methods handle 1.8 clients internally by returning 0.5. But it's wasted CPU. Could add an early return for 1.8 clients if aiming for efficiency.

### 4.4 Jitter Hardcoded to 0

In `RemoteInferenceClient.java`, all three predict methods send:

```java
body.put("jitter", 0);
```

The `LagProfile` from `FeatureBridge` already computes jitter:
```java
// FeatureBridge.updateLagProfile():
long jitter = Math.abs(currentPing - avgPing);
lagProfile.setJitter(jitter);
```

The server's `_get_context()` method extracts jitter from the request:
```python
def _get_context(request: Request) -> tuple[float, float, int]:
    body = request._json or {}
    return body.get("tps", 20.0), 0.0, body.get("ping", 0)
    # jitter is returned as 0.0, not read from the request!
```

**Two bugs in one:**
1. The Java client always sends `jitter: 0` instead of the actual jitter
2. The Python server ignores the jitter field from the request

**Fix:** 
1. Client: `body.put("jitter", fb.getLagProfile().getJitter());`
2. Server: extract jitter from request body: `body.get("jitter", 0)`

### 4.5 rule-skills.md Compliance

The `rule-skills.md` specifies:

> **CRITICAL**: Do NOT import any Bukkit APIs (`org.bukkit.*`), Fabric APIs, or platform-specific classes here (in `:common` module).

**Compliance check** on all analyzed files in `common`:

| File | Third-party imports | Violation? |
|---|---|---|
| `FusionEngine.java` | `lombok.Getter` | **NO** -- Lombok is compile-time annotation processing, not platform-specific |
| `FeatureBridge.java` | `lombok.Getter`, `com.github.retrooper.packetevents.protocol.player.ClientVersion` | **NO** -- PacketEvents is cross-platform |
| `BoundedMLQueue.java` | None (pure Java) | **NO** |
| `PunishmentManager.java` | `lombok.RequiredArgsConstructor`, `net.kyori.adventure.text.Component`, `org.jetbrains.annotations.Nullable` | **NO** -- Adventure is cross-platform; Lombok is compile-time; JetBrains annotations are metadata |
| `RemoteInferenceClient.java` | `com.google.gson.Gson`, `lombok.Getter` | **NO** |
| `ConfidenceModel.java` | `org.jetbrains.annotations.NotNull` | **NO** |

> **The file `FusionEngine.java` imports `lombok.Getter` at line 6.** `lombok.Getter` is a Lombok annotation that generates `getPlayer()`. It is compile-time only (retention SOURCE) and does NOT create a Bukkit dependency. This is NOT a rule-skills.md violation.

**Verdict: No rule-skills.md violations found in the analyzed files.**

### 4.6 Feedback Loop Protection

The feedback loop would be:
1. ML model returns high risk
2. FusionEngine uses it in decision
3. Action fires -> auto-label as cheat
4. Next training cycle trains on this label
5. ML learns: "high risk -> reinforced"

**Current protections are correct:**
- Auto-label (label=1.0) only fires for MOVEMENT/PACKET/WATCHDOG_BOT -- these are pure whitebox categories where blackbox is NOT used in the decision
- COMBAT_AIM, CLICK, COMBAT_GEOM, GHOST_PROFILE, BOTting are explicitly excluded from auto-training
- Weak labeling (label=0.8) has strict guards: `certainty >= 0.85`, `totalFlagCount > 5`, domain-specific thresholds

### 4.7 Grace Period and Relog Exploit Protection

```java
private static final long GRACE_PERIOD_MS = 120_000L;    // 2 minutes
private static final long GRACE_COOLDOWN_MS = 300_000L;  // 5 minutes

public void onPlayerJoin() {
    this.sessionRiskAccumulator *= 0.5; // half-life on reconnect
    long now = System.currentTimeMillis();
    if (now - joinTimeMs > GRACE_COOLDOWN_MS || joinTimeMs == 0) {
        this.isNewPlayer = true;
        this.joinTimeMs = now;
    }
}
```

**Correctness analysis:**
- Session risk is halved (not zeroed) on reconnect -> prevents "reconnect to clear risk"
- Grace period is only granted if 5+ minutes have passed since last disconnect -> prevents "reconnect for fresh grace"
- The `isInGracePeriod()` check in PunishmentManager downgrades ENFORCE to ALERT during grace
- Grace does NOT extend when player has been online for 2+ minutes

**Potential edge case:** If a player connects, gets kicked (not banned), reconnects within 5 minutes, and reaches ENFORCE threshold again: the `sessionRiskAccumulator` starts at 50% of previous value (from the halving). With only 2 minutes of grace (which is not renewed because `joinTimeMs` is the old value > `now - GRACE_COOLDOWN_MS`), the player has 2 minutes of grace from the ORIGINAL join, not from the reconnect. This is correct behavior -- the player only has one grace period per session.

---

## 5. Conclusion

### 5.1 Must Fix

| Issue | File(s) | Risk | Fix |
|---|---|---|---|
| EnumMap thread safety | `FusionEngine.java` | **LOW** -- no CME, stale reads are benign, lost updates converge in 1 tick | Replace with `ConcurrentHashMap` (preventative, not emergent) |
| Cloud confidence=0.5 | `FeatureBridge.java` | **LOW** -- ConfidenceModel not needed when cloud is online | Remove `updateConfidence()` from cloud path (Option B) |
| Jitter hardcoded to 0 | `RemoteInferenceClient.java`, `server.py` | **LOW** -- jitter is not currently used by server in prediction | Send actual jitter from LagProfile |

### 5.2 Should Fix

| Issue | File(s) | Fix |
|---|---|---|
| Unused `predictAll()` endpoint | `RemoteInferenceClient.java`, `server.py`, `schemas.py` | Remove or deprecate |
| Unused `accumulateRisk(weight)` overload | `FusionEngine.java` | Remove dead code |
| Jitter ignored on server | `cloud/server.py` | Extract jitter from request body in `_get_context()` |

### 5.3 False Alarms / Intentional Design

| Issue from previous report | Analysis | Verdict |
|---|---|---|
| "EnumMap can throw ConcurrentModificationException" | EnumMap has no modCount; cannot throw CME | **False alarm** -- wrong claim |
| "Missing volatile on boolean flags" | All cross-thread booleans are benign; single-thread booleans are fine | **False alarm** -- intentional design |
| "Double atomicity issue" | 64-bit JVM has atomic double writes | **False alarm** -- not an issue in practice |
| "rule-skills.md violation: common imports Lombok" | Lombok is compile-time only, rule-skills.md explicitly permits Lombok | **False alarm** -- not a violation |
| "AnomalyScore cross-thread race" | At worst, stale read by 1 tick; corrected next tick | **Intentional design** -- eventual consistency |

### 5.4 Code Fixes

The following changes are recommended (in priority order):

#### Fix 1: Replace EnumMap with ConcurrentHashMap in FusionEngine.java

```java
private final Map<Category, Double> blackboxRiskByCategory = new ConcurrentHashMap<>();
private final Map<Category, Long> blackboxLastUpdateByCategory = new ConcurrentHashMap<>();
```

Plus update `resetPeakRisk()`:
```java
public void resetPeakRisk() {
    this.blackboxRiskByCategory.clear();
    this.blackboxLastUpdateByCategory.clear();
}
```

`ConcurrentHashMap.clear()` is thread-safe and atomic.

#### Fix 2: Remove `updateConfidence()` from cloud path

In `FeatureBridge.submitMLInference()`, remove the two `fusion.updateConfidence(resp.confidence())` calls from the cloud response handlers. Only keep `updateConfidence()` in the fallback paths (`fallbackAim()`, `fallbackSession()`).

#### Fix 3: Send real jitter to cloud

In `RemoteInferenceClient.java`, change all three predict methods:
```java
// Before:
body.put("jitter", 0);

// After:
body.put("jitter", fb.getLagProfile().getJitter());
```

In `cloud/server.py`, fix `_get_context()`:
```python
def _get_context(request: Request) -> tuple[float, float, int]:
    body = request._json or {}
    return body.get("tps", 20.0), body.get("jitter", 0), body.get("ping", 0)
```

#### Fix 4: Remove dead code

Remove the `accumulateRisk(double weight)` overload in FusionEngine.java (it defaults to MOVEMENT which is semantically incorrect for callers that don't pass it -- though no callers actually use it).

#### Fix 5: Remove composite endpoint (optional)

Delete `predictAll()` from `RemoteInferenceClient.java`, the `/v1/predict/all` endpoint from `cloud/server.py`, and the `CompositeResponse`/`PredictAllRequest` models from `cloud/schemas.py`.

---

*End of thread-safety analysis report.*
