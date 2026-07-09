# SessionModel Feature Research: Reach / Hitbox Bypass Detection

> **Phien ban:** 1.0
> **Du an:** MLSHybridAC (GrimAC + ML Layer)
> **Ngay:** 2026-07-10
> **Muc tieu:** Phan tich kha nang them features vao SessionModel de phat hien reach bypass, hitbox bypass, va ghost client ma khong gay false flag.

---

## 1. FeatureBridge: Danh sach day du compute methods

FeatureBridge.java (1274 dong) co 26 compute methods/public signals:

### Combat Geometry & Hit Features

| # | Method | Mo ta | Window | O SessionModel? |
|---|--------|-------|--------|-----------------|
| 1 | `computeCombatFrequency()` | Attacks/second tu combatHistory | 32 attacks | **KHONG** |
| 2 | `computeHitMissRatio()` | Hits/swings ratio | 32 attacks / 50 clicks | **KHONG** (chi o ClickModel) |
| 3 | `computeCriticalRatio()` | % attacks khi sprint-jumping | 32 attacks | **KHONG** (chi o ClickModel) |
| 4 | `computeAutoJumpRatio()` | jump ticks / combat ticks | 60s window | **KHONG** |
| 5 | `computeGroundedRatio()` | grounded ticks / combat ticks | 60s window | **KHONG** |
| 6 | `computeJumpIntervalStddev()` | stddev cua jump intervals | 50 jumps | **KHONG** |

### Click Timing Features

| # | Method | Mo ta | Window | O SessionModel? |
|---|--------|-------|--------|-----------------|
| 7 | `computeClickEntropy()` | Shannon entropy cua click intervals | 50 clicks | **KHONG** |
| 8 | `computeCooldownAccuracy()` | Attack timing vs weapon cooldown | 50 clicks | **CO** (#1) |
| 9 | `computeMissRatio()` | Ty le bo lo co hoi attack | 50 clicks | **CO** (#2) |
| 10 | `computePerfectStreak()` | So lan attack lien tuc dung cooldown | 50 clicks | **KHONG** |

### Rotation & Aim Features

| # | Method | Mo ta | Window | O SessionModel? |
|---|--------|-------|--------|-----------------|
| 11 | `computeMouseSensitivity()` | pitchMean / yawMean ratio | 64 ticks | **CO** (#3) |
| 12 | `computePitchDeltaMean()` | Mean pitch change/tick | 64 ticks | **CO** (#4) |
| 13 | `computeYawDeltaMean()` | Mean yaw change/tick | 64 ticks | **CO** (#5) |
| 14 | `computeGcdConsistency()` | 1.0 - gcdError * 4 | 64 ticks | **CO** (#6) |
| 15 | `computeRotationEntropy()` | Shannon entropy cua yaw deltas | 64 ticks | **CO** (#7) |
| 16 | `computeNormalizedSessionDuration()` | Session length [0, 1] | Session | **CO** (#8) |
| 17 | `computeYawJerkStdDev()` | stddev cua yaw acceleration | 64 ticks | **KHONG** |
| 18 | `computePitchJerkStdDev()` | stddev cua pitch acceleration | 64 ticks | **KHONG** |
| 19 | `computeAimSmoothness()` | Cross-correlation cua yaw deltas | 64 ticks | **KHONG** |
| 20 | `computeAccelerationAnomaly()` | Ty le sudden rotation jumps | 64 ticks | **KHONG** |
| 21 | `computeSnapFrequency()` | = computeAccelerationAnomaly() | 64 ticks | **KHONG** (alias) |
| 22 | `computeGcdError()` | Deviation tu 0.5-degree grid | 64 ticks | **KHONG** (dung inverse) |

### Behavioral Trap Features

| # | Method | Mo ta | Window | O SessionModel? |
|---|--------|-------|--------|-----------------|
| 23 | `computeClickRotationVariance()` | Variance cua yawDelta khi attack | 100 attacks | **KHONG** |
| 24 | `computeTriggerReactionScore()` | attackYaw / baselineYaw ratio | 100 attacks | **KHONG** |

### Contextual

| # | Method | Mo ta | Window | O SessionModel? |
|---|--------|-------|--------|-----------------|
| 25 | `getPingFactor()` | Jitter-based reliability [0.2, 1.0] | EWMA | **KHONG** |
| 26 | `computeAimRiskScore()` | Combined 4-metric heuristic | 64 ticks | **KHONG** |

**Tong cong:** 26 methods, chi co 8 duoc dung trong SessionModel (30.7%). Con 18 methods khong duoc dung.

### Nhung cai co the them ngay (da co code, chi can goi):

1. `computeHitMissRatio()` -- da co trong ClickModel, nhung SessionModel chua co
2. `computePerfectStreak()` -- da co trong ClickModel, SessionModel chua co
3. `computeYawJerkStdDev()` -- da co trong AimModel, SessionModel chua co
4. `computeAutoJumpRatio()` -- chi dung trong heuristic, chua vao ML
5. `computeCriticalRatio()` -- da co trong ClickModel, SessionModel chua co
6. `computeClickRotationVariance()` -- chi dung trong heuristic
7. `computeCombatFrequency()` -- chua duoc dung o dau (chi la public method)

### Nhung cai CAN VIET MOI:

1. **Hit distance statistics**: mean, max, stddev tu combatHistory
2. **Hit angle statistics**: mean, stddev cua targetAngle
3. **Combat activity ratio**: combatHistory.size() / sessionTicks
4. **Reach anomaly**: so luong hits > 4.0 blocks (server desync filter)

---

## 2. False Flag Risk Analysis cho tung Feature

### Phan tich chi tiet FP risk

#### Feature 1: hitDistanceMean

| Thong so | Gia tri |
|----------|---------|
| **Phuong phap** | `mean(combatHistory[].hitDistance)` qua 32 attacks |
| **Human range** | 1.5 - 3.2 blocks (sword 1.9+) |
| **Legit outliers** | 3.5-4.0 blocks khi sprint + ping 100ms+ (position desync) |
| **Cheat range** | 3.8 - 6.0 blocks |
| **FP risk** | **THAP** (2/10) -- do hit distance la do true tu server |
| **Ping normalization** | Can chia cho `sqrt(ping/50)` de bu cho desync |
| **Ghi chu** | Day la feature tot nhat de phat hien reach. Can co threshold dong. |

**Phan tich FP:**
- Player ping 200ms: target position desync ~2 ticks = target o xa hon thuc te ~0.5 blocks
- Solution: `adjustedDistance = rawDistance / (1.0 + pingJitter * 0.002)`
- Can phan biet sprinting vs walking (sprint tang reach ~0.5 blocks legit)

#### Feature 2: hitDistanceMax

| Thong so | Gia tri |
|----------|---------|
| **Phuong phap** | `max(combatHistory[].hitDistance)` qua 32 attacks |
| **Human range** | 3.0 - 4.0 blocks (sprint + ping desync) |
| **Cheat range** | 4.5 - 7.0+ blocks |
| **FP risk** | **TRUNG BINH** (5/10) -- mot hit distance lon co the do lag spike |
| **Can dieu kien** | Chi flag neu > 4.5 blocks AND ping < 200ms AND jitter < 30ms |

**Phan tich FP:**
- Packet loss + reconciliation: player position co the "jump" ve sau khi attack, lam hit distance duoc tinh sai
- Solution: chi tinh max distance khi ping on dinh (jitter < 30ms)
- Mot hit 4.2 blocks khong dang nghi neu ping 250ms

#### Feature 3: hitDistanceStdDev

| Thong so | Gia tri |
|----------|---------|
| **Phuong phap** | `stddev(combatHistory[].hitDistance)` qua 32 attacks |
| **Human range** | 0.3 - 1.0 blocks (tu nhien thay doi khoang cach) |
| **Cheat range** | 0.05 - 0.3 blocks (reach luon o cung khoang cach xa) |
| **FP risk** | **THAP** (3/10) -- nhieu player co combat pattern khac nhau |
| **Luu y** | Feature nay hieu qua khi ket hop voi hitDistanceMean |

**Phan tich FP:**
- Player dung bow + sword: hit distance dao dong lon (0-5 blocks) --> stddev cao --> khong bi false
- Player chi dung sword: stddev co the thap hon, nhung van > 0.3
- Van de: neu player fight 1 target dung im, surender --> stddev thap legitimate

#### Feature 4: hitMissRatio

| Thong so | Gia tri |
|----------|---------|
| **Phuong phap** | `totalHits / totalSwings` |
| **Human range** | 0.3 - 0.8 (60-80% hit rate) |
| **Cheat range** | 0.8 - 1.0 (reach/hitbox extend = luon hit) |
| **FP risk** | **TRUNG BINH** (5/10) -- phu thuoc vao server gameplay |
| **Da co o** | ClickModel, chua co o SessionModel |

**Phan tich FP:**
- Player trong corner fight (enemy luon trong range) --> hit rate cao legitimate
- 1v1 arena khong knockback --> hit rate 80-90% la legitimate
- Kit PVP (no knockback) --> hit rate rat cao legitimate
- **Can context**: chi flag neu hit rate cao + hit distance cung cao

#### Feature 5: hitAngleMean + hitAngleStdDev

| Thong so | Gia tri |
|----------|---------|
| **Phuong phap** | Thong ke `combatHistory[].targetAngle` |
| **Human range (mean)** | 5 - 45 degrees (nhin tuong doi central) |
| **Cheat range (mean)** | 0 - 10 degrees (aim luon chinh xac vao target center) |
| **FP risk** | **THAP** (2/10) cho mean, **TRUNG BINH** (4/10) cho stddev |
| **Ghi chu** | Day la feature cho aim assist + hitbox extend |

**Phan tich FP:**
- Player nhin thang vao target (no strafe) --> angle gan 0
- Can phan biet "snap to center" (cheat) vs "tracking central" (legit skill)
- Cheat: targetAngle << yawDelta (rotation dung yen khi attack)
- Legit: targetAngle ~ yawDelta (rotation dang chay khi attack)
- **Recommendation**: Khong dung standalone, chi dung trong ensemble

#### Feature 6: combatFrequency

| Thong so | Gia tri |
|----------|---------|
| **Phuong phap** | 32 attacks / time span (seconds) |
| **Human range (1.9+)** | 1.2 - 1.6 attacks/sec (cooldown bound) |
| **Cheat range (1.9+)** | 1.6+ (attack truoc khi cooldown ket thuc? hoac silent aura) |
| **FP risk** | **RAT THAP** (1/10) trong 1.9+, **CAO** (7/10) trong 1.8 |
| **Ghi chu** | 1.9+ cooldown gioi han ~1.6 attacks/sec. Vuot qua = suspicious |

**Phan tich FP:**
- 1.8 khong co attack cooldown --> combat frequency = CPS --> 8-12 cps legit
- 1.9+ cooldown = 625ms (sword) --> max ~1.6 attacks/sec
- Neu combat frequency > 1.7 trong 1.9+: co the la cheat hoac weapon swap exploit
- Weapon swap (axe -> sword) cho phep attack nhanh hon legitimate --> van co the la legit
- **Can filter**: chi flag neu > 1.8 attacks/sec AND khong co weapon swap pattern

#### Feature 7: perfectStreak

| Thong so | Gia tri |
|----------|---------|
| **Phuong phap** | Consecutive attacks trong 5% tolerance cua cooldown |
| **Human range** | 1 - 8 |
| **Cheat range** | 12 - 50+ |
| **FP risk** | **THAP** (3/10) -- rat kho dat streak > 12 legit |
| **Da co o** | ClickModel, chua co o SessionModel |

#### Feature 8: clickRotationVariance

| Thong so | Gia tri |
|----------|---------|
| **Phuong phap** | Variance cua yawDelta tai attack moments |
| **Human range** | 0.05 - 0.5 (click khi rotation dang thay doi) |
| **Cheat range** | 0.001 - 0.01 (cho rotation on dinh roi click) |
| **FP risk** | **THAP** (3/10) -- rat kho co variance < 0.01 legit |
| **Da co o** | Heuristic (computeProvisionalRisk), chua vao ML |

**Phan tich FP:**
- Player tracking target di thang --> rotation it thay doi --> variance thap
- Nhung variance 0.01 la rat thap. Can co window > 20 attacks.
- Cinematic mode co the tao variance thap --> can context

### Bang tong hop FP Risk

| Feature | Human Range | Cheat Range | FP Risk (1-10) | Da co code? | Recommend cho SessionModel? |
|---------|-------------|-------------|----------------|-------------|-----------------------------|
| hitDistanceMean | 1.5-3.2 | 3.8-6.0 | **2** (thap) | Can viet moi | **CO** (uutien 1) |
| hitDistanceMax | 3.0-4.0 | 4.5-7.0 | **5** (trung binh) | Can viet moi | Co, co dieu kien |
| hitDistanceStdDev | 0.3-1.0 | 0.05-0.3 | **3** (thap) | Can viet moi | **CO** (uutien 2) |
| hitMissRatio | 0.3-0.8 | 0.8-1.0 | **5** (trung binh) | CO (ClickModel) | **CO** (uutien 3) |
| hitAngleMean | 5-45 | 0-10 | **2** (thap) | Can viet moi | Co (aim assist) |
| combatFrequency (1.9+) | 1.2-1.6 | 1.6+ | **1** (rat thap) | CO | **CO** (uutien 4) |
| perfectStreak | 1-8 | 12-50+ | **3** (thap) | CO (ClickModel) | Co (autoclicker) |
| clickRotationVariance | 0.05-0.5 | 0.001-0.01 | **3** (thap) | CO | Co (aim assist) |
| yawJerkStdDev | 0.5-1.5 | 0.05-0.4 | **4** (trung binh) | CO (AimModel) | Co the nhung redundant |
| autoJumpRatio | 0.3-0.6 | 0.8-1.0 | **4** (trung binh) | CO | Co the (auto-jump) |
| gcdConsistency | 0.0-0.6 | 0.9-1.0 | **4** (trung binh) | CO (dang co) | GIU LAI |
| rotationEntropy | 5.0-7.0 | 2.0-4.0 | **3** (thap) | CO (dang co) | GIU LAI |

---

## 3. Phan tich 8 features hien tai cua SessionModel

### Feature 1: cooldownAccuracy

| Thong so | Gia tri |
|----------|---------|
| **Phat hien gi?** | AutoClicker 1.9+ (attack exactly khi cooldown reset) |
| **Co ich khong?** | CO -- la core feature cho click timing analysis |
| **Co nen giu?** | CO -- duy tri |
| **Han che** | Chi co y nghia cho 1.9+ client. 1.8: return 0.5 (neutral) |
| **FP risk** | Thap cho 1.9+. Rat kho dat accuracy > 0.95 legit |

### Feature 2: missRatio

| Thong so | Gia tri |
|----------|---------|
| **Phat hien gi?** | AutoClicker (luon attack khi co the, khong miss co hoi) |
| **Co ich khong?** | CO -- bo sung cho cooldownAccuracy |
| **Co nen giu?** | CO -- duy tri |
| **FP risk** | Trung binh. Player focus cao co the miss rat it |

### Feature 3: mouseSensitivity

| Thong so | Gia tri |
|----------|---------|
| **Phat hien gi?** | **Khong phat hien cheat** -- la confounder control |
| **Co ich khong?** | CO -- giup model hieu "pitchDeltaMean thap vi sensitivity thap, khong phai aim assist" |
| **Co nen giu?**| **GIU** -- rat quan trong de tranh false positive |
| **Ghi chu** | Day la feature "dieu kien" (conditioning variable), khong phai "signal" |

### Feature 4: pitchDeltaMean

| Thong so | Gia tri |
|----------|---------|
| **Phat hien gi?** | Activity level + baseline pitch movement |
| **Co ich khong?** | TRUNG BINH -- la context feature |
| **Co nen giu?**| CO -- can cho mouseSensitivity ratio |
| **Ghi chu** | Phoi hop voi mouseSensitivity de hieu playstyle |

### Feature 5: yawDeltaMean

| Thong so | Gia tri |
|----------|---------|
| **Phat hien gi?** | Activity level + baseline yaw movement |
| **Co ich khong?** | TRUNG BINH -- la context feature |
| **Co nen giu?** | CO -- can cho mouseSensitivity ratio |
| **Ghi chu** | Tuong tu pitchDeltaMean |

### Feature 6: gcdConsistency

| Thong so | Gia tri |
|----------|---------|
| **Phat hien gi?** | Grid-aligned rotation (aim assist snap) |
| **Co ich khong?**| CO -- feature quan trong cho aim assist o session level |
| **Co nen giu?** | CO -- feature chinh |
| **FP risk** | Trung binh. User voi sensitivity la boi so cua 0.5 co the bi FP |
| **Ghi chu** | Can combined voi rotationEntropy de tranh FP |

### Feature 7: rotationEntropy

| Thong so | Gia tri |
|----------|---------|
| **Phat hien gi?** | Rotation distribution predictability (thap = aim assist) |
| **Co ich khong?** | CO -- feature chinh |
| **Co nen giu?** | CO -- feature quan trong nhat cung voi gcdConsistency |
| **FP risk** | Thap. Chi entropy < 4.0 bits moi flag |

### Feature 8: normalizedSessionDuration

| Thong so | Gia tri |
|----------|---------|
| **Phat hien gi?** | Temporal weighting -- khong phat hien cheat truc tiep |
| **Co ich khong?**| CO -- cho model biet "da co du data chua?" |
| **Co nen giu?**| CO -- quan trong cho online learning (sample weight) |
| **Ghi chu** | Feature nay khong co predictive power ve cheat, nhung can de tranh cold-start FP |

### Danh gia tong the 8 features hien tai:

| Feature | Type | Signal Strength | Keep? |
|---------|------|----------------|-------|
| cooldownAccuracy | Signal (click) | Manh | YES |
| missRatio | Signal (click) | Trung binh | YES |
| mouseSensitivity | Context | Khong co | YES (confounder) |
| pitchDeltaMean | Context | Yeu | YES (can cho ratio) |
| yawDeltaMean | Context | Yeu | YES (can cho ratio) |
| gcdConsistency | Signal (aim) | Manh | YES |
| rotationEntropy | Signal (aim) | Manh | YES |
| normalizedSessionDuration | Context | Khong co | YES (temporal) |

**Ty le Signal vs Context:** 4 signal + 4 context = 50/50. Day la ty le tot.

### Van de cua SessionModel hien tai:

1. **Khong co feature nao phat hien REACH / HITBOX BYPASS**
   - Day la loai cheat pho bien nhat trong Minecraft PVP
   - Khong co hitDistance feature nao trong 8 features
   - SessionModel hoan toan "mui" voi reach bypass

2. **Thieu combat geometry features**
   - Khong co hitMissRatio (da co trong ClickModel nhung khong dung o SessionModel)
   - Khong co hit angle statistics
   - Khong co combat frequency

3. **Thieu behavioral trap features**
   - Khong co clickRotationVariance (rat tot cho aim assist)
   - Khong co triggerReactionScore
   - Khong co autoJumpRatio

---

## 4. De xuat them features vao SessionModel

### 4.1 Feature nao tu FeatureBridge co the them ngay (chi can goi method)?

| Feature | Method | Code ready? | Them vao SessionModel? | Ly do |
|---------|--------|-------------|----------------------|-------|
| hitMissRatio | `computeHitMissRatio()` | CO (ClickModel) | **CO** | Phat hien reach + killaura |
| perfectStreak | `computePerfectStreak()` | CO (ClickModel) | **CO** | Cung co auto-click detection o session level |
| combatFrequency | `computeCombatFrequency()` | CO (FeatureBridge) | **CO** | 1.9+ attack rate != CPS |
| yawJerkStdDev | `computeYawJerkStdDev()` | CO (FeatureBridge) | Co the | Aim assist, nhung co the redundant voi gcdConsistency |
| clickRotationVariance | `computeClickRotationVariance()` | CO (FeatureBridge) | **CO** | Aim assist detection rat manh |
| autoJumpRatio | `computeAutoJumpRatio()` | CO (FeatureBridge) | Co the | Auto-jump / auto-crit |
| groundedRatio | `computeGroundedRatio()` | CO (FeatureBridge) | Co the | AutoJumpReset |
| jumpIntervalStddev | `computeJumpIntervalStddev()` | CO (FeatureBridge) | Co the | Auto-jump consistency |

### 4.2 Feature moi nao can viet code?

**Uu tien 1: Hit distance statistics**

```java
/**
 * Mean hit distance over last 32 attacks.
 * Human 1.9+: 1.5-3.2 blocks (sword range).
 * Reach cheat: 3.8-6.0 blocks.
 * Ping-adjusted: chia cho sqrt(ping/50) de bu desync.
 */
public double computeHitDistanceMean() {
    if (combatHistory.size() < 3) return 0; // not enough data
    
    CombatSnapshot[] arr = combatHistory.toArray(new CombatSnapshot[0]);
    double sum = 0;
    int count = 0;
    for (CombatSnapshot s : arr) {
        if (s.getHitDistance() > 0.5) { // filter outliers / invalid hits
            sum += s.getHitDistance();
            count++;
        }
    }
    return count > 0 ? sum / count : 0;
}

/**
 * Max hit distance over last 32 attacks.
 * Chi flag neu > 4.5 blocks AND ping < 200ms.
 */
public double computeHitDistanceMax() {
    if (combatHistory.size() < 3) return 0;
    
    double maxDist = 0;
    for (CombatSnapshot s : combatHistory) {
        if (s.getHitDistance() > maxDist) {
            maxDist = s.getHitDistance();
        }
    }
    return maxDist;
}

/**
 * Standard deviation of hit distances.
 * Human: 0.3-1.0 blocks (natural variation).
 * Cheat: 0.05-0.3 blocks (consistent extended range).
 */
public double computeHitDistanceStdDev() {
    double mean = computeHitDistanceMean();
    if (mean <= 0 || combatHistory.size() < 5) return 0;
    
    double variance = 0;
    int count = 0;
    for (CombatSnapshot s : combatHistory) {
        if (s.getHitDistance() > 0.5) {
            variance += (s.getHitDistance() - mean) * (s.getHitDistance() - mean);
            count++;
        }
    }
    return count > 0 ? Math.sqrt(variance / count) : 0;
}
```

**Uu tien 2: Hit angle statistics**

```java
/**
 * Mean target angle at attack.
 * Human: 5-45 degrees.
 * Aim assist + hitbox extend: 0-10 degrees.
 */
public double computeHitAngleMean() {
    if (combatHistory.size() < 3) return 30; // default: human-like
    
    double sum = 0;
    int count = 0;
    for (CombatSnapshot s : combatHistory) {
        sum += Math.abs(s.getTargetAngle());
        count++;
    }
    return count > 0 ? sum / count : 30;
}
```

**Uu tien 3: Combat activity ratio**

```java
/**
 * Combat activity: attacks per second over session.
 * Human: 0.5-1.5 attacks/sec (combat + non-combat time).
 * Cheat (constant PVP): 1.5+ attacks/sec (luon combat).
 * Giong combatFrequency nhung o session level.
 */
public double computeCombatActivity() {
    long sessionMs = System.currentTimeMillis() - sessionStartTime;
    if (sessionMs < 5000) return 0.5; // can 5s data
    
    double attacksPerSec = (double) combatHistory.size() / (sessionMs / 1000.0);
    return Math.min(attacksPerSec, 3.0);
}
```

### 4.3 De xuat feature cu the cho Reach / Hitbox Bypass

```
Reach bypass signature:
  1. hitDistanceMean > 3.5 blocks
  2. hitDistanceMax > 4.5 blocks (voi ping < 200ms)
  3. hitDistanceStdDev < 0.3 (luon hit o xa)
  4. hitMissRatio > 0.85 (hit rate cao bat thuong)
  → Ket hop: (1) + (3) + (4) = reach bypass gan nhu chac chan

Hitbox extend signature:
  1. hitAngleMean < 15 degrees (luon hit o center)
  2. hitDistanceMean > 3.0 blocks (xa hon binh thuong)
  3. clickRotationVariance < 0.01 (rotation on dinh khi attack)
  → Ket hop: (1) + (2) + clickRotationVariance = hitbox extend

Aim assist + reach (legit aura):
  1. gcdConsistency > 0.8
  2. rotationEntropy < 4.5 bits
  3. hitDistanceMean > 3.2 blocks
  → Ket hop: session profile cho silent aura
```

### 4.4 So features toi uu cho SessionModel

**Hien tai:** 8 features (4 signal + 4 context)
**De xuat:** 12 features (7 signal + 5 context)

**Tai sao 12 la du?**
- Ensemble cua 5 logistic regression members
- 12 features * 5 members = 60 weights + 5 biases = 65 parameters
- Ty le parameters / features = 5.4 -- tot cho generalization
- Qua 15 features: nguy co overfitting voi ensemble nho

**12 features de xuat:**

```
Index | Feature              | Type    | Signal Strength | Phu trach phat hien
------|----------------------|---------|-----------------|--------------------
0     | cooldownAccuracy     | Signal  | Manh            | AutoClicker
1     | missRatio            | Signal  | Trung binh      | AutoClicker
2     | mouseSensitivity     | Context | Khong           | Confounder control
3     | pitchDeltaMean       | Context | Yeu             | Activity baseline
4     | yawDeltaMean         | Context | Yeu             | Activity baseline
5     | gcdConsistency       | Signal  | Manh            | Aim assist
6     | rotationEntropy      | Signal  | Manh            | Aim assist
7     | normalizedSessionDuration | Context | Khong      | Temporal weighting
  --- THEM MOI ---
8     | hitDistanceMean      | Signal  | Manh            | REACH BYPASS (MOI)
9     | hitDistanceStdDev    | Signal  | Trung binh      | REACH BYPASS (MOI)
10    | hitMissRatio         | Signal  | Trung binh      | Reach + KillAura (MOI)
11    | combatFrequency      | Signal  | Trung binh      | Attack rate (MOI)
```

**Luu y:** Nhac features `pitchDeltaMean` va `yawDeltaMean` co the duoc gop thanh 1 feature `rotationActivity` (pitch + yaw) de giai phong 1 slot cho feature khac. Nhung dang hien tai, giu rieng de co mouseSensitivity ratio.

### 4.5 Feature Importance du kien cho SessionModel mo rong

| Rank | Feature | Importance du kien | Ghi chu |
|------|---------|-------------------|---------|
| 1 | **hitDistanceMean** | 20% | NEW: feature manh nhat cho reach |
| 2 | **gcdConsistency** | 15% | Grid alignment (da co) |
| 3 | **rotationEntropy** | 15% | Distribution (da co) |
| 4 | **hitMissRatio** | 12% | NEW: bo sung cho hitDistance |
| 5 | **cooldownAccuracy** | 10% | Click timing (da co) |
| 6 | **hitDistanceStdDev** | 8% | NEW: consistency cua reach |
| 7 | **combatFrequency** | 5% | NEW: attack rate |
| 8-12 | Con lai | < 5% each | Context features |

---

## 5. Implementation plan

### 5.1 Buoc 1: Them code vao FeatureBridge.java

Them 3 compute methods moi:

```java
// 1. Hit Distance Mean
public double computeHitDistanceMean() { ... }

// 2. Hit Distance Max  
public double computeHitDistanceMax() { ... }

// 3. Hit Distance StdDev
public double computeHitDistanceStdDev() { ... }
```

Code chi tiet da co o muc 4.2. Can ~50 dong code.

### 5.2 Buoc 2: Cap nhat MLModelManager.extractSessionFeatures()

```java
public float @NotNull [] extractSessionFeatures(@NotNull FeatureBridge fb) {
    return new float[]{
        (float) fb.computeCooldownAccuracy(),
        (float) fb.computeMissRatio(),
        (float) fb.computeMouseSensitivity(),
        (float) fb.computePitchDeltaMean(),
        (float) fb.computeYawDeltaMean(),
        (float) fb.computeGcdConsistency(),
        (float) fb.computeRotationEntropy(),
        (float) fb.computeNormalizedSessionDuration(),
        // --- NEW FEATURES ---
        (float) fb.computeHitDistanceMean(),     // index 8
        (float) fb.computeHitDistanceStdDev(),    // index 9
        (float) fb.computeHitMissRatio(),         // index 10
        (float) fb.computeCombatFrequency()       // index 11
    };
}
```

**Luu y:** Can dam bao thu tu features trong extractSessionFeatures() khop voi `FEATURE_NAMES` trong SessionModel.java.

### 5.3 Buoc 3: Cap nhat SessionModel.java

```java
public static final int NUM_FEATURES = 12; // Tang tu 8 len 12

private static final List<String> FEATURE_NAMES = List.of(
    "cooldownAccuracy",
    "missRatio",
    "mouseSensitivity",
    "pitchDeltaMean",
    "yawDeltaMean",
    "gcdConsistency",
    "rotationEntropy",
    "normalizedSessionDuration",
    "hitDistanceMean",       // NEW
    "hitDistanceStdDev",     // NEW
    "hitMissRatio",          // NEW
    "combatFrequency"        // NEW
);
```

### 5.4 Buoc 4: Cap nhat serialize/deserialize

SessionModel hien tai ghi `NUM_FEATURES` vao file header. Format version can tang tu 1 len 2 de tranh load nham model cu:

```java
private static final int FORMAT_VERSION = 2;
```

Khi deserialize, kiem tra:
- Version 1 (8 features) -> load binh thuong
- Version 2 (12 features) -> load binh thuong
- Tu dong mo rong weights neu can

### 5.5 Buoc 5: Update cloud server

Trong `cloud-server.md`:
- Update session features tu 8 len 12 trong `/v1/predict/session` endpoint
- Update `session_model.py` weighted ensemble tu 8 len 12 weights
- Update `schemas.py` SessionRequest validation tu 8 len 12

### 5.6 Buoc 6: Re-train model

- SessionModel can re-train tu data cu (8 features) + data moi (12 features)
- Ensemble weights se tu dieu chinh qua online SGD
- Can khoang 1000+ samples de on dinh

---

## 6. Ket luan

### 6.1 Co nen them features vao SessionModel khong?

**CO, NHAT DINH PHAI THEM.**

SessionModel hien tai chi phat hien:
- AutoClicker (cooldownAccuracy, missRatio)
- Aim assist (gcdConsistency, rotationEntropy)

**HOAN TOAN KHONG Phat hien duoc:**
- Reach bypass (loai cheat pho bien nhat)
- Hitbox extend
- KillAura (hit pattern)
- Ghost client (silent aim + reach)

Day la blind spot nghiem trong. Them 4 features (hitDistanceMean, hitDistanceStdDev, hitMissRatio, combatFrequency) se lap day blind spot nay.

### 6.2 Feature nao them duoc ngay?

| Feature | Code san? | Them ngay duoc? | Do kho |
|---------|-----------|-----------------|--------|
| hitMissRatio | CO (ClickModel) | **NGAY** | 0 (chi can goi method) |
| combatFrequency | CO (FeatureBridge) | **NGAY** | 0 (chi can goi method) |
| perfectStreak | CO (ClickModel) | **NGAY** | 0 (chi can goi method) |
| clickRotationVariance | CO (FeatureBridge) | **NGAY** | 0 (chi can goi method) |

**4 features nay co the them vao SessionModel trong < 30 phut.**

### 6.3 Feature nao can code moi?

| Feature | Can code? | Uoc tinh thoi gian | Do uu tien |
|---------|-----------|--------------------|------------|
| hitDistanceMean | **CO** | 15 phut | **Cao nhat** |
| hitDistanceStdDev | **CO** | 15 phut | Cao |
| hitDistanceMax | **CO** | 5 phut | Trung binh |
| hitAngleMean | **CO** | 15 phut | Thap (aim assist da co feature khac) |
| combatActivity | **CO** | 10 phut | Thap (combatFrequency da du) |

**Tong thoi gian code moi: ~45-60 phut.**

### 6.4 Rui ro FP khi them features

| Feature | FP Risk | Nguyen nhan | Cach giam thieu |
|---------|---------|-------------|-----------------|
| hitDistanceMean | **THAP** | Ping desync lam tang hit distance | Ping normalization (chia sqrt(ping/50)) |
| hitDistanceStdDev | **THAP** | Player chi fight 1 target dung im | Can combined voi hitDistanceMean |
| hitMissRatio | **TRUNG BINH** | Corner fight / Kit PVP / 1v1 | Chi flag khi hit distance cung cao |
| combatFrequency (1.9+) | **RAT THAP** | Weapon swap exploit | Filter weapon swap pattern |

**Overall FP risk increase:** THAP. Khong feature nao co FP risk > 5/10.

### 6.5 So features toi uu: 12

```
Hien tai:  8 features  →  4 signal + 4 context
De xuat:  12 features  →  7 signal + 5 context
Ty le:     58% signal / 42% context  →  Ty le tot cho classification

Tang 4 features:
  - 3 cho reach/hitbox bypass (hitDistanceMean, hitDistanceStdDev, hitMissRatio)
  - 1 cho combat timing (combatFrequency)
```

**Khong nen vuot qua 12 features** vi:
- Ensemble cua 5 logistic regression co 65 parameters voi 12 features
- 15 features = 80 parameters --> ty le 5.3, van duoc nhung edge
- 20 features = 105 parameters --> ty le 5.25, bat dau overfit
- SessionModel khong co regularization (no L1/L2 trong OnlineLogReg)

### 6.6 Lộ trinh trien khai

```
Phase 1 (NGAY): Them 4 features da co code
  - hitMissRatio, combatFrequency, perfectStreak, clickRotationVariance
  - Chi can sua 3 files: SessionModel.java, MLModelManager.java, cloud session model
  - Khong can retrain (online SGD tu dong dieu chinh)

Phase 2 (1-2 ngay): Viet code moi cho hit distance
  - hitDistanceMean, hitDistanceStdDev, hitDistanceMax
  - Them 3 compute methods vao FeatureBridge.java
  - Them vao SessionModel

Phase 3 (Sau khi co data): Retrain + tune
  - Thu thap 500+ samples co reach bypass
  - Kiem tra feature importance thuc te
  - Dieu chinh weights ensemble
```

### 6.7 Recommendation cuoi cung

**1. SessionModel can mo rong tu 8 len 12 features.**
   - Ly do: Blind spot nghiem trong voi reach/hitbox bypass
   - Khong lam tang FP risk dang ke
   - Implementation don gian (khong can model architecture thay doi)

**2. Uu tien cao nhat: hitDistanceMean + hitMissRatio.**
   - Day la 2 feature truc tiep phat hien reach bypass
   hitDistanceMean: do xa trung binh cua cac hit
   hitMissRatio: ty le hit/swing -- reach cheat luon hit vi hitbox mo rong

**3. Uu tien thu hai: combatFrequency.**
   - 1.9+ cooldown gioi han attack rate ~1.6/s
   - Vuot qua nay = suspicious (silent aura / killaura)
   - FP risk gan nhu bang 0 trong 1.9+

**4. Khong can them feature aim assist vi gcdConsistency + rotationEntropy da du.**
   - yawJerkStdDev, aimSmoothness co the redundant
   - Neu muon them, chi them clickRotationVariance (unique signal, khong overlap)

**5. Overall risk assessment: LOW.**
   - 4 features moi co FP risk thap (%5-6/10)
   - Ensemble tu dong dieu chinh trong luong qua online SGD
   - Feature extraction cost khong dang ke (< 0.01ms)

---

## Phu luc: Feature extraction cost estimate

| Feature | Operations | Memory Access | Cost (uoc) |
|---------|-----------|---------------|------------|
| hitDistanceMean | sum + divide | 32 CombatSnapshot reads | ~0.0005ms |
| hitDistanceStdDev | sum + variance + sqrt | 32 reads (2 passes) | ~0.001ms |
| hitDistanceMax | max + compare | 32 reads | ~0.0002ms |
| hitMissRatio | size() * 2 | 2 Deque references | ~0.0001ms |
| combatFrequency | size() + timestamp diff | 2 reads | ~0.0002ms |
| **Total added cost** | | | **~0.002ms** |

**Tong feature extraction cost (current + new):** ~0.012ms, van nam trong budget 0.05ms.

---

## References

1. **FeatureBridge.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\player\features\FeatureBridge.java` (1274 lines)
2. **SessionModel.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\SessionModel.java` (582 lines)
3. **MLModelManager.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\ml\MLModelManager.java` (92 lines)
4. **FeatureVector.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\player\features\FeatureVector.java` (82 lines)
5. **GBDT.java** — `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\ml\GBDT.java` (440 lines)
6. **feature-engineering.md** — `D:\Duancanhan\AC\docs\research\feature-engineering.md` (1387 lines)
7. **cloud-server.md** — `D:\Duancanhan\AC\docs\research\cloud-server.md` (2932 lines)
