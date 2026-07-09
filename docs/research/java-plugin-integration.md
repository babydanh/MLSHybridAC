# Java Plugin Integration: Cloud-First ML Inference

> Chuyển đổi GrimAC plugin từ local ML inference (GBDT/OnlineLogReg trên JVM)
> sang cloud-first inference với HTTP communication + graceful degradation.

## Mục lục

1. [Tổng quan kiến trúc hiện tại](#1-tổng-quan-kiến-trúc-hiện-tại)
2. [Thiết kế Cloud-First Architecture](#2-thiết-kế-cloud-first-architecture)
3. [3.1 RemoteInferenceClient.java REWRITE](#31-remoteinferenceclientjava-rewrite)
4. [3.2 MLModelManager.java STRIP](#32-mlmodelmanagerjava-strip)
5. [3.3 FeatureBridge.java MODIFY](#33-featurebridgejava-modify)
6. [3.4 FusionEngine.java MODIFY](#34-fusionenginejava-modify)
7. [4. Graceful Degradation Matrix](#4-graceful-degradation-matrix)
8. [5. Deprecation Plan cho Java Models](#5-deprecation-plan-cho-java-models)
9. [6. GrimAPI.java Wiring Updates](#6-grimapijava-wiring-updates)
10. [7. Config Changes](#7-config-changes)
11. [8. Build Changes](#8-build-changes)
12. [9. Migration Sequence](#9-migration-sequence)

---

## 1. Tổng quan kiến trúc hiện tại

### 1.1 Flow hiện tại (Local ML)

```
Game Thread                    ML Worker Thread (BoundedMLQueue)     Cloud
    │                                    │
    │  FeatureBridge.tick()              │
    │  ├─ collect features              │
    │  ├─ computeProvisionalRisk()       │
    │  └─ submitMLInference() ──────────→│
    │                                    │
    │                                    ├─ AimModel.predict()     [GBDT 30 trees]
    │                                    ├─ ClickModel.predict()   [OnlineLogReg]
    │                                    ├─ SessionModel.predict() [Ensemble 5 members]
    │                                    │
    │                                    ├─ fusion.setBlackboxRisk()
    │                                    └─ fusion.updateConfidence()
    │
    │  FusionEngine.evaluate()
    │  ├─ whiteboxCertainty (Grim checks)
    │  ├─ blackboxRisk (ML scores)
    │  ├─ sessionRiskAccumulator
    │  └─ → Action: OBSERVE/ALERT/ENFORCE
    │
    PunishmentManager.handleAlert()
    └─ Thực thi commands dựa trên FusionEngine Action
```

### 1.2 File hiện tại và vai trò

| File | Package | Vai trò |
|------|---------|---------|
| `RemoteInferenceClient.java` | `manager.ml` | HTTP client gửi request lên cloud (chưa dùng trong inference flow) |
| `MLModelManager.java` | `manager.ml` | Singleton quản lý model instances + feature extraction |
| `FeatureBridge.java` | `manager.player.features` | Collect features + submit ML inference qua BoundedMLQueue |
| `FusionEngine.java` | `manager` | Decision layer: blend whitebox + blackbox → action |
| `BoundedMLQueue.java` | `manager` | Async queue cho ML inference (thread pool + backpressure) |
| `PunishmentManager.java` | `manager` | Handle alerts, gọi FusionEngine.evaluate(), auto-train ML |
| `AimModel.java` | `ml` | GBDT wrapper, 6 features, predict → risk score |
| `ClickModel.java` | `ml` | OnlineLogReg wrapper, 5 features |
| `SessionModel.java` | `ml` | Ensemble 5 OnlineLogReg members, 8 features |
| `GBDT.java` | `ml` | 30 trees, max depth 4, sigmoid output |
| `ConfidenceModel.java` | `ml` | Bayesian logistic regression + burst detection |
| `OnlineLogReg.java` | `ml` | Logistic regression với SGD online training |
| `MLDataManager.java` | `manager.ml` | Load/save model weights, record training samples |
| `AnomalyTracker.java` | `manager.ml` | Per-player statistical anomaly scores (confidence modifier) |
| `PlayerProfile.java` | `manager.ml` | Sliding window stats cho anomaly detection |
| `GrimAPI.java` | root | DI container: khởi tạo tất cả manager |

### 1.3 Vấn đề với architecture hiện tại

1. **CPU-bound ML trên game server**: GBDT 30 trees + Session 5-member ensemble chạy trên JVM, cạnh tranh tài nguyên với Minecraft server.
2. **Model weights trong JAR/disk**: AimModel, ClickModel, SessionModel cần load/save weights, phức tạp hóa deployment.
3. **Không real-time updates**: Model chỉ được training batch offline, không học được pattern mới.
4. **Feature extraction + inference coupling**: `submitMLInference()` trong FeatureBridge gọi model trực tiếp, khó thay thế.
5. **Training data thu thập thủ công**: MLDataManager ghi CSV, cần offline pipeline để train GBDT.

---

## 2. Thiết kế Cloud-First Architecture

### 2.1 Flow mới (Cloud-First)

```
Game Thread                    Cloud-First Flow
    │
    │  FeatureBridge.tick()
    │  ├─ collect features
    │  ├─ computeProvisionalRisk()    [heuristics, vẫn giữ]
    │  └─ submitMLInference()
    │       │
    │       ├── Cloud available? ───── YES ──→ RemoteInferenceClient.predictAll()
    │       │                                       │ async CompletableFuture
    │       │                                       │
    │       │                               ┌───────┴──────────┐
    │       │                               │  Cloud Response  │
    │       │                               │  ├─ aimRisk      │
    │       │                               │  ├─ clickRisk    │
    │       │                               │  ├─ sessionRisk  │
    │       │                               │  ├─ confidence   │
    │       │                               │  └─ modelVersion │
    │       │                               └───────┬──────────┘
    │       │                                       │
    │       │                               fusion.setBlackboxRisk(...)
    │       │                               cloud.recordSuccess()
    │       │
    │       └── Cloud unavailable? ── YES ──→ fallbackToOnlineLogReg()
    │                                               │
    │                                        fusion.setBlackboxRisk(...)
    │                                        (lower confidence flag)
    │
    │  FusionEngine.evaluate()
    │  ├─ cloudAvailable flag
    │  ├─ Nếu !cloudAvailable → tighten thresholds
    │  └─ Nếu cloudAvailable → normal fusion
    │
    │  PunishmentManager.handleAlert()
    └─ fusionCommandAllowed() kiểm tra cloud state
```

### 2.2 Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     GrimAPI (DI Container)                       │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ MLModelManager   │  │ RemoteInference  │  │ BoundedMLQueue │  │
│  │ (stripped)      │  │ Client (rewritten)│  │ (keep for      │  │
│  │                 │  │                  │  │  fallback)     │  │
│  │ - OnlineLogReg  │  │ - Circuit Breaker│  └────────────────┘  │
│  │   aimOnline     │  │ - Health Check   │                      │
│  │ - OnlineLogReg  │  │ - Per-model      │  ┌────────────────┐  │
│  │   sessionOnline │  │   endpoints      │  │ FusionEngine   │  │
│  │ - extract*Feat()│  │ - Connection Pool│  │ (modified)     │  │
│  │ - isCloudAvail  │  └──────────────────┘  │ - cloudAvail   │  │
│  └─────────────────┘                       │ - tighten      │  │
│                                            │   thresholds   │  │
│  ┌─────────────────┐  ┌──────────────────┐  └────────────────┘  │
│  │ FeatureBridge   │  │ PunishmentManager│                      │
│  │ (modified)      │  │ (modified)       │                      │
│  │ - cloud-first   │  │ - autoTrainML    │                      │
│  │   submitMLInfer │  │   gọi cloud API  │                      │
│  │ - fallbackToOLR │  │   thay vì local  │                      │
│  └─────────────────┘  └──────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Chi tiết code thay đổi

### 3.1 RemoteInferenceClient.java REWRITE

**File đích:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\ml\RemoteInferenceClient.java`

**Package:** `ac.grim.grimac.manager.ml`

#### 3.1.1 Circuit Breaker Pattern

```java
// Circuit breaker state machine
public enum CircuitState {
    CLOSED,    // Hoạt động bình thường
    OPEN,      // Quá nhiều failures — không gửi request
    HALF_OPEN  // Đang thử lại sau backoff
}

private static final int FAILURE_THRESHOLD = 5;       // 5 failures → OPEN
private static final long[] BACKOFF_DURATIONS = {     // Exponential backoff (ms)
    30_000L,   // Lần 1: 30 giây
    60_000L,   // Lần 2: 1 phút
    120_000L,  // Lần 3: 2 phút
    300_000L   // Lần 4+: 5 phút max
};

private final AtomicInteger consecutiveFailures = new AtomicInteger(0);
private volatile CircuitState circuitState = CircuitState.CLOSED;
private volatile long circuitOpenTime = 0;
private volatile int backoffIndex = 0;
```

Logic circuit breaker:

```java
public boolean isCircuitBroken() {
    if (circuitState == CircuitState.CLOSED) return false;
    if (circuitState == CircuitState.OPEN) {
        // Check if backoff period has elapsed → transition to HALF_OPEN
        long elapsed = System.currentTimeMillis() - circuitOpenTime;
        long currentBackoff = BACKOFF_DURATIONS[
            Math.min(backoffIndex, BACKOFF_DURATIONS.length - 1)];
        if (elapsed >= currentBackoff) {
            circuitState = CircuitState.HALF_OPEN;
            return false; // Allow one trial request
        }
        return true;
    }
    // HALF_OPEN: allow request, will transition based on result
    return false;
}

public void recordSuccess() {
    consecutiveFailures.set(0);
    backoffIndex = 0;
    circuitState = CircuitState.CLOSED;
    circuitOpenTime = 0;
}

public void recordFailure() {
    int failures = consecutiveFailures.incrementAndGet();
    if (failures >= FAILURE_THRESHOLD && circuitState != CircuitState.OPEN) {
        circuitState = CircuitState.OPEN;
        circuitOpenTime = System.currentTimeMillis();
        backoffIndex = Math.min(backoffIndex + 1, BACKOFF_DURATIONS.length - 1);
        GrimAPI.INSTANCE.getPlatformServer().logWarning(
            "[VNAC-Cloud] Circuit breaker OPEN after " + failures
            + " failures. Backoff=" + BACKOFF_DURATIONS[backoffIndex] + "ms");
    }
}

public void resetCircuitBreaker() {
    consecutiveFailures.set(0);
    backoffIndex = 0;
    circuitState = CircuitState.CLOSED;
    circuitOpenTime = 0;
}
```

#### 3.1.2 Response Records

```java
/**
 * Per-model prediction response từ cloud.
 */
public record PredictionResponse(
    double risk,           // 0.0 - 0.985
    double confidence,     // Model uncertainty (0.0-1.0)
    String modelVersion,   // "aim_v1_20260701"
    long serverTimestamp    // Cloud processing time (epoch ms)
) {
    public static final PredictionResponse EMPTY = new PredictionResponse(0.0, 0.0, "", 0L);
}

/**
 * Composite response: tất cả model trong 1 request.
 */
public record CompositeResponse(
    PredictionResponse aim,
    PredictionResponse click,
    PredictionResponse session
) {
    public static final CompositeResponse EMPTY = new CompositeResponse(
        PredictionResponse.EMPTY,
        PredictionResponse.EMPTY,
        PredictionResponse.EMPTY
    );
}
```

#### 3.1.3 Per-Model Endpoints

```java
/**
 * Predict aim risk từ cloud.
 */
public CompletableFuture<PredictionResponse> predictAim(FeatureBridge fb) {
    if (!enabled || baseUrl.isEmpty() || isCircuitBroken()) {
        return CompletableFuture.completedFuture(PredictionResponse.EMPTY);
    }

    float[] features = GrimAPI.INSTANCE.getMlModelManager().extractAimFeatures(fb);
    Map<String, Object> body = new HashMap<>();
    body.put("features", features);
    body.put("player_id", fb.getPlayer().uuid.toString());
    body.put("category", "aim");

    return post("/v1/predict/aim", body, PredictionResponse.class)
        .orTimeout(150, TimeUnit.MILLISECONDS)
        .exceptionally(ex -> {
            recordFailure();
            return PredictionResponse.EMPTY;
        });
}

/**
 * Predict click risk từ cloud.
 */
public CompletableFuture<PredictionResponse> predictClick(FeatureBridge fb) {
    if (!enabled || baseUrl.isEmpty() || isCircuitBroken()) {
        return CompletableFuture.completedFuture(PredictionResponse.EMPTY);
    }

    float[] features = GrimAPI.INSTANCE.getMlModelManager().extractClickFeatures(fb);
    Map<String, Object> body = new HashMap<>();
    body.put("features", features);
    body.put("player_id", fb.getPlayer().uuid.toString());
    body.put("category", "click");

    return post("/v1/predict/click", body, PredictionResponse.class)
        .orTimeout(150, TimeUnit.MILLISECONDS)
        .exceptionally(ex -> {
            recordFailure();
            return PredictionResponse.EMPTY;
        });
}

/**
 * Predict session risk từ cloud.
 */
public CompletableFuture<PredictionResponse> predictSession(FeatureBridge fb) {
    if (!enabled || baseUrl.isEmpty() || isCircuitBroken()) {
        return CompletableFuture.completedFuture(PredictionResponse.EMPTY);
    }

    float[] features = GrimAPI.INSTANCE.getMlModelManager().extractSessionFeatures(fb);
    Map<String, Object> body = new HashMap<>();
    body.put("features", features);
    body.put("player_id", fb.getPlayer().uuid.toString());
    body.put("category", "session");

    return post("/v1/predict/session", body, PredictionResponse.class)
        .orTimeout(150, TimeUnit.MILLISECONDS)
        .exceptionally(ex -> {
            recordFailure();
            return PredictionResponse.EMPTY;
        });
}
```

#### 3.1.4 Composite predictAll (Batch)

```java
/**
 * Gửi tất cả features trong 1 request composite.
 * Async — không block game thread.
 *
 * @return CompositeResponse chứa risk cho 3 model.
 *         Nếu cloud fail, tất cả risk = 0.0 → fallback.
 */
public CompletableFuture<CompositeResponse> predictAll(
        FeatureBridge fb,
        Map<String, Object> whitebox,
        Map<String, Object> runtime) {

    if (!enabled || baseUrl.isEmpty() || isCircuitBroken()) {
        return CompletableFuture.completedFuture(CompositeResponse.EMPTY);
    }

    // Build composite request body
    Map<String, Object> body = new HashMap<>();

    // Features cho từng model
    body.put("aim_features", GrimAPI.INSTANCE.getMlModelManager().extractAimFeatures(fb));
    body.put("click_features", GrimAPI.INSTANCE.getMlModelManager().extractClickFeatures(fb));
    body.put("session_features", GrimAPI.INSTANCE.getMlModelManager().extractSessionFeatures(fb));

    // Context
    body.put("whitebox", whitebox);
    body.put("runtime", runtime);
    body.put("player_id", fb.getPlayer().uuid.toString());
    body.put("server_id", GrimAPI.INSTANCE.getConfigManager().getConfig()
        .getStringElse("VNAC.cloud.server-id", "default"));

    return post("/v1/predict/all", body, CompositeResponse.class)
        .orTimeout(150, TimeUnit.MILLISECONDS)
        .exceptionally(ex -> {
            recordFailure();
            return CompositeResponse.EMPTY;
        });
}
```

#### 3.1.5 Connection Management

```java
/**
 * HTTP Client với connection pool + timeouts.
 * Singleton: tất cả threads chia sẻ 1 client.
 */
private static HttpClient createHttpClient() {
    return HttpClient.newBuilder()
        .version(HttpClient.Version.HTTP_2)           // HTTP/2 nếu server support
        .connectTimeout(Duration.ofMillis(150))         // connect timeout: 150ms
        .executor(Executors.newFixedThreadPool(4, r -> {
            Thread t = new Thread(r, "AC-Cloud-HTTP");
            t.setDaemon(true);
            return t;
        }))
        .build();
}

// Thay thế constructor cũ:
public RemoteInferenceClient() {
    this.gson = new GsonBuilder()
        .registerTypeAdapter(PredictionResponse.class, new PredictionResponseDeserializer())
        .registerTypeAdapter(CompositeResponse.class, new CompositeResponseDeserializer())
        .create();
    this.http = createHttpClient();
    this.mapper = new ObjectMapper(); // For complex JSON

    var config = GrimAPI.INSTANCE.getConfigManager().getConfig();
    this.enabled = config.getBooleanElse("VNAC.cloud.enabled", true);
    this.baseUrl = config.getStringElse("VNAC.cloud.url", "http://localhost:8000");
    this.apiKey = config.getStringElse("VNAC.cloud.api-key", "");
    this.serverId = config.getStringElse("VNAC.cloud.server-id", "default");

    // Start health check background thread
    startHealthCheck();
}

/**
 * POST request với timeout + retry.
 * Retry 1 lần nếu timeout (idempotent requests).
 */
private <T> CompletableFuture<T> post(String path, Object body, Class<T> respClass) {
    try {
        String json = gson.toJson(body);
        HttpRequest req = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl + path))
            .header("Content-Type", "application/json")
            .header("Authorization", "Bearer " + apiKey)
            .header("X-Server-Id", serverId)
            .header("X-Request-Timeout", "150")
            .POST(HttpRequest.BodyPublishers.ofString(json))
            .timeout(Duration.ofMillis(200))  // slightly higher than overall timeout
            .build();

        // First attempt
        return http.sendAsync(req, HttpResponse.BodyHandlers.ofString())
            .thenCompose(resp -> handleResponse(resp, respClass))
            .thenCompose(result -> {
                recordSuccess();
                return CompletableFuture.completedFuture(result);
            })
            .exceptionally(ex -> {
                // Retry 1x on timeout
                if (isTimeoutException(ex)) {
                    try {
                        HttpRequest retryReq = HttpRequest.newBuilder()
                            .uri(URI.create(baseUrl + path))
                            .header("Content-Type", "application/json")
                            .header("Authorization", "Bearer " + apiKey)
                            .POST(HttpRequest.BodyPublishers.ofString(json))
                            .timeout(Duration.ofMillis(200))
                            .build();
                        return http.sendAsync(retryReq, HttpResponse.BodyHandlers.ofString())
                            .thenCompose(resp -> handleResponse(resp, respClass))
                            .get(200, TimeUnit.MILLISECONDS);
                    } catch (Exception retryEx) {
                        throw new CompletionException(retryEx);
                    }
                }
                throw new CompletionException(ex);
            });
    } catch (Exception e) {
        return CompletableFuture.failedFuture(e);
    }
}

private <T> T handleResponse(HttpResponse<String> resp, Class<T> respClass) {
    if (resp.statusCode() == 503) {
        // Service unavailable — server đang quá tải
        recordFailure();
        throw new RuntimeException("Cloud 503: Service Unavailable");
    }
    if (resp.statusCode() != 200) {
        recordFailure();
        throw new RuntimeException("Cloud error: HTTP " + resp.statusCode());
    }
    return gson.fromJson(resp.body(), respClass);
}

private boolean isTimeoutException(Throwable ex) {
    Throwable cause = ex;
    while (cause != null) {
        if (cause instanceof java.net.http.HttpTimeoutException
            || cause instanceof java.util.concurrent.TimeoutException) {
            return true;
        }
        cause = cause.getCause();
    }
    return false;
}
```

#### 3.1.6 Health Check

```java
// Background health check — chạy mỗi 60 giây
private volatile boolean cloudAvailable = false;
private volatile long lastHealthCheckTime = 0;
private ScheduledFuture<?> healthCheckFuture;

private void startHealthCheck() {
    if (!enabled) return;

    healthCheckFuture = GrimAPI.INSTANCE.getScheduler()
        .getGlobalRegionScheduler()
        .runAtFixedRate(GrimAPI.INSTANCE.getGrimPlugin(),
            () -> checkHealth(),
            60L, 60L, TimeUnit.SECONDS);  // every 60s
}

private void checkHealth() {
    try {
        HttpRequest req = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl + "/v1/health"))
            .header("Authorization", "Bearer " + apiKey)
            .timeout(Duration.ofMillis(500))
            .GET()
            .build();

        http.sendAsync(req, HttpResponse.BodyHandlers.ofString())
            .thenAccept(resp -> {
                boolean wasAvailable = cloudAvailable;
                cloudAvailable = (resp.statusCode() == 200);
                lastHealthCheckTime = System.currentTimeMillis();

                if (!wasAvailable && cloudAvailable) {
                    // Cloud vừa online trở lại
                    resetCircuitBreaker();
                    GrimAPI.INSTANCE.getPlatformServer().logInfo(
                        "[VNAC-Cloud] Cloud is back online.");
                } else if (wasAvailable && !cloudAvailable) {
                    GrimAPI.INSTANCE.getPlatformServer().logWarning(
                        "[VNAC-Cloud] Cloud health check failed.");
                }
            })
            .exceptionally(ex -> {
                if (cloudAvailable) {
                    cloudAvailable = false;
                    GrimAPI.INSTANCE.getPlatformServer().logWarning(
                        "[VNAC-Cloud] Cloud health check error: " + ex.getMessage());
                }
                return null;
            });
    } catch (Exception e) {
        if (cloudAvailable) {
            cloudAvailable = false;
        }
    }
}

public boolean isCloudAvailable() {
    return enabled && cloudAvailable && !isCircuitBroken();
}

public boolean isEnabled() { return enabled; }

public void shutdown() {
    if (healthCheckFuture != null) {
        healthCheckFuture.cancel(false);
    }
}
```

#### 3.1.7 Training Endpoint (thay thế local training)

```java
/**
 * Gửi labeled sample lên cloud để online training.
 * Thay thế local autoTrainML trong PunishmentManager.
 *
 * @return true nếu cloud nhận sample thành công
 */
public CompletableFuture<Boolean> submitTrainingSample(
    String category,   // "aim", "click", "session"
    float[] features,
    float label,
    String playerId
) {
    if (!enabled) return CompletableFuture.completedFuture(false);

    Map<String, Object> body = new HashMap<>();
    body.put("category", category);
    body.put("features", features);
    body.put("label", label);
    body.put("player_id", playerId);
    body.put("server_id", serverId);
    body.put("source", "plugin_auto_train");

    return post("/v1/train/sample", body, Object.class)
        .thenApply(r -> true)
        .exceptionally(ex -> false);
}

/**
 * Gửi batch training samples lên cloud.
 */
public CompletableFuture<Boolean> submitTrainingBatch(
    List<TrainingSample> samples
) {
    if (!enabled || samples.isEmpty()) return CompletableFuture.completedFuture(false);

    Map<String, Object> body = new HashMap<>();
    body.put("samples", samples.stream().map(s -> {
        Map<String, Object> sample = new HashMap<>();
        sample.put("category", s.category);
        sample.put("features", s.features);
        sample.put("label", s.label);
        sample.put("player_id", s.playerId);
        return sample;
    }).collect(java.util.stream.Collectors.toList()));

    return post("/v1/train/batch", body, Object.class)
        .thenApply(r -> true)
        .exceptionally(ex -> false);
}

public record TrainingSample(
    String category,
    float[] features,
    float label,
    String playerId
) {}
```

#### 3.1.8 Gradient Ramp-up (Startup grace)

```java
// Gradient ramp-up: khi plugin mới start, cloud chưa sẵn sàng ngay.
// Tăng dần reliance score từ 0.0 → 1.0 trong 30s đầu.
private volatile long pluginStartTime = System.currentTimeMillis();
private static final long RAMP_UP_DURATION_MS = 30_000L; // 30 giây

/**
 * Ramp-up factor cho graceful startup.
 * Trong 30s đầu, factor tăng từ 0.0 → 1.0 (linear).
 * Sau 30s, luôn trả về 1.0.
 */
public double getRampUpFactor() {
    long elapsed = System.currentTimeMillis() - pluginStartTime;
    if (elapsed >= RAMP_UP_DURATION_MS) return 1.0;
    return (double) elapsed / RAMP_UP_DURATION_MS;
}
```

#### 3.1.9 Full Class Structure

```java
package ac.grim.grimac.manager.ml;

import ac.grim.grimac.GrimAPI;
import ac.grim.grimac.manager.player.features.FeatureBridge;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.HashMap;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

public class RemoteInferenceClient {

    // ── Records ─────────────────────────────────────────────────
    public record PredictionResponse(double risk, double confidence,
        String modelVersion, long serverTimestamp) {
        public static final PredictionResponse EMPTY = new PredictionResponse(0,0,"",0L);
    }
    public record CompositeResponse(PredictionResponse aim,
        PredictionResponse click, PredictionResponse session) {
        public static final CompositeResponse EMPTY = new CompositeResponse(
            PredictionResponse.EMPTY, PredictionResponse.EMPTY, PredictionResponse.EMPTY);
    }
    public record TrainingSample(String category, float[] features,
        float label, String playerId) {}

    // ── Circuit Breaker ─────────────────────────────────────────
    public enum CircuitState { CLOSED, OPEN, HALF_OPEN }
    private static final int FAILURE_THRESHOLD = 5;
    private static final long[] BACKOFF = {30_000L, 60_000L, 120_000L, 300_000L};

    private final AtomicInteger consecutiveFailures = new AtomicInteger(0);
    private volatile CircuitState circuitState = CircuitState.CLOSED;
    private volatile long circuitOpenTime = 0;
    private volatile int backoffIndex = 0;

    // ── Connection ──────────────────────────────────────────────
    private final HttpClient http;
    private final Gson gson;
    private final String baseUrl;
    private final String apiKey;
    private final String serverId;
    private final boolean enabled;

    // ── Health ──────────────────────────────────────────────────
    private volatile boolean cloudAvailable = false;
    private volatile long lastHealthCheckTime = 0;
    private ScheduledFuture<?> healthCheckFuture;

    // ── Ramp-up ─────────────────────────────────────────────────
    private final long pluginStartTime = System.currentTimeMillis();
    private static final long RAMP_UP_MS = 30_000L;

    // ── Metrics ─────────────────────────────────────────────────
    private final AtomicLong totalRequests = new AtomicLong();
    private final AtomicLong failedRequests = new AtomicLong();
    private final AtomicLong totalLatencyMs = new AtomicLong();

    // ── Constructor ─────────────────────────────────────────────
    public RemoteInferenceClient() {
        // ... (như đã mô tả ở trên)
    }

    // ── Public API ──────────────────────────────────────────────
    public boolean isEnabled();
    public boolean isCloudAvailable();
    public boolean isCircuitBroken();
    public double getRampUpFactor();
    public void recordSuccess();
    public void recordFailure();
    public void resetCircuitBreaker();
    public void shutdown();

    public CompletableFuture<CompositeResponse> predictAll(
        FeatureBridge fb, Map<String, Object> whitebox, Map<String, Object> runtime);
    public CompletableFuture<PredictionResponse> predictAim(FeatureBridge fb);
    public CompletableFuture<PredictionResponse> predictClick(FeatureBridge fb);
    public CompletableFuture<PredictionResponse> predictSession(FeatureBridge fb);
    public CompletableFuture<Boolean> submitTrainingSample(
        String category, float[] features, float label, String playerId);
    public CompletableFuture<Boolean> submitTrainingBatch(List<TrainingSample> samples);

    // ── Internal ────────────────────────────────────────────────
    private <T> CompletableFuture<T> post(String path, Object body, Class<T> respClass);
    private <T> T handleResponse(HttpResponse<String> resp, Class<T> respClass);
    private boolean isTimeoutException(Throwable ex);
    private void startHealthCheck();
    private void checkHealth();
    private static HttpClient createHttpClient();

    // ── Getters ─────────────────────────────────────────────────
    public long totalRequests() { return totalRequests.get(); }
    public long failedRequests() { return failedRequests.get(); }
    public CircuitState getCircuitState() { return circuitState; }
    public int getBackoffIndex() { return backoffIndex; }
    public boolean isCloudOnline() { return cloudAvailable; }
}
```

### 3.2 MLModelManager.java STRIP

**File đích:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\ml\MLModelManager.java`

**Chiến lược xóa:**

1. **XÓA** fields: `aimModel`, `clickModel`, `sessionModel`
2. **XÓA** methods: `loadModels()`, `saveModels()`, tất cả model loader methods
3. **GIỮ** methods: `extractAimFeatures()`, `extractClickFeatures()`, `extractSessionFeatures()`
4. **GIỮ** fields: `aimOnline`, `sessionOnline` (fallback siêu nhẹ)
5. **THÊM** `isCloudAvailable()` flag
6. **THÊM** `getActiveModelVersion()` cho logging

#### 3.2.1 Stripped MLModelManager

```java
package ac.grim.grimac.manager.ml;

import ac.grim.grimac.GrimAPI;
import ac.grim.grimac.manager.player.features.FeatureBridge;
import ac.grim.grimac.ml.OnlineLogReg;
import org.jetbrains.annotations.NotNull;

/**
 * MLModelManager (stripped) — chỉ giữ feature extraction + OnlineLogReg fallback.
 *
 * LOCAL MODELS REMOVED:
 * - AimModel, ClickModel, SessionModel (GBDT + Ensemble) → replaced by cloud.
 * - loadModels(), saveModels() → kh còn local model weights.
 *
 * GIỮ:
 * - extractAimFeatures(), extractClickFeatures(), extractSessionFeatures()
 *   (vẫn cần features để gửi lên cloud và cho OnlineLogReg fallback).
 * - OnlineLogReg aimOnline, sessionOnline (fallback khi cloud offline).
 *
 * Cloud-first: tất cả ML inference qua RemoteInferenceClient.
 */
public final class MLModelManager {

    // ── Fallback OnlineLogReg (chỉ dùng khi cloud offline) ─────
    private final OnlineLogReg aimOnline;     // 6 aim features
    private final OnlineLogReg sessionOnline;  // 8 session features

    // ── Cloud availability flag ─────────────────────────────────
    private volatile boolean cloudWarmupComplete = false;

    // ── Model version tracking ─────────────────────────────────
    private String activeCloudModelVersion = "unknown";

    public MLModelManager() {
        // OnlineLogReg với learning rate thấp hơn (0.005)
        // để tránh overfit khi training data ít
        this.aimOnline = new OnlineLogReg(6, 0.005f);
        this.sessionOnline = new OnlineLogReg(8, 0.005f);
    }

    // ── Accessors ───────────────────────────────────────────────

    public @NotNull OnlineLogReg getAimOnline() { return aimOnline; }
    public @NotNull OnlineLogReg getSessionOnline() { return sessionOnline; }

    /**
     * Cloud availability convenience — delegate tới RemoteInferenceClient.
     * Trả về true nếu cloud enabled + available + circuit closed.
     */
    public boolean isCloudAvailable() {
        RemoteInferenceClient cloud = GrimAPI.INSTANCE.getRemoteInferenceClient();
        return cloud != null && cloud.isCloudAvailable();
    }

    /**
     * Active model version (từ cloud response gần nhất).
     * Dùng cho logging/diagnostics.
     */
    public String getActiveModelVersion() {
        return activeCloudModelVersion;
    }

    /**
     * Update model version từ cloud response.
     * Gọi khi nhận được CompositeResponse từ cloud.
     */
    public void updateActiveModelVersion(String version) {
        if (version != null && !version.isEmpty()) {
            this.activeCloudModelVersion = version;
        }
    }

    /**
     * Cloud warmup flag — true sau khi plugin chạy ổn định.
     * Dùng cho FusionEngine để quyết dịnh threshold adjustment.
     */
    public boolean isCloudWarmupComplete() {
        return cloudWarmupComplete;
    }

    public void setCloudWarmupComplete(boolean complete) {
        this.cloudWarmupComplete = complete;
    }

    // ── Feature extraction (GIỮ NGUYÊN) ──────────────────────────

    /**
     * Extract 6 features cho aim detection.
     * KHÔNG THAY ĐỔI — vẫn dùng cho cloud và fallback.
     */
    public float @NotNull [] extractAimFeatures(@NotNull FeatureBridge fb) {
        double ping = fb.getPlayer().getTransactionPing();
        double pingNorm = Math.max(1.0, Math.sqrt(ping / 50.0));
        return new float[]{
            (float) (fb.computeYawJerkStdDev() / pingNorm),
            (float) (fb.computePitchJerkStdDev() / pingNorm),
            (float) fb.computeAimSmoothness(),
            (float) fb.computeRotationEntropy(),
            (float) fb.computeGcdError(),
            (float) fb.computeSnapFrequency()
        };
    }

    /**
     * Extract 5 features cho click detection.
     * KHÔNG THAY ĐỔI.
     */
    public float @NotNull [] extractClickFeatures(@NotNull FeatureBridge fb) {
        return new float[]{
            (float) fb.computeCooldownAccuracy(),
            (float) fb.computeMissRatio(),
            (float) fb.computeHitMissRatio(),
            (float) fb.computeCriticalRatio(),
            (float) fb.computePerfectStreak()
        };
    }

    /**
     * Extract 8 features cho session profiling.
     * KHÔNG THAY ĐỔI.
     */
    public float @NotNull [] extractSessionFeatures(@NotNull FeatureBridge fb) {
        return new float[]{
            (float) fb.computeCooldownAccuracy(),
            (float) fb.computeMissRatio(),
            (float) fb.computeMouseSensitivity(),
            (float) fb.computePitchDeltaMean(),
            (float) fb.computeYawDeltaMean(),
            (float) fb.computeGcdConsistency(),
            (float) fb.computeRotationEntropy(),
            (float) fb.computeNormalizedSessionDuration()
        };
    }
}
```

#### 3.2.2 So sánh: Before vs After

| Thành phần | Before | After |
|------------|--------|-------|
| `AimModel aimModel` | field + getter | **XÓA** |
| `ClickModel clickModel` | field + getter | **XÓA** |
| `SessionModel sessionModel` | field + getter | **XÓA** |
| `OnlineLogReg aimOnline` | field + getter | **GIỮ** (LR giảm 0.01→0.005) |
| `OnlineLogReg sessionOnline` | field + getter | **GIỮ** (LR giảm 0.01→0.005) |
| `boolean modelsLoaded` | flag | **XÓA** |
| `loadModels(Path)` | method | **XÓA** |
| `loadModel(...)` | private method | **XÓA** |
| `loadAimModel(...)` | private method | **XÓA** |
| `loadClickModel(...)` | private method | **XÓA** |
| `loadSessionModel(...)` | private method | **XÓA** |
| `extractAimFeatures()` | method | **GIỮ** |
| `extractClickFeatures()` | method | **GIỮ** |
| `extractSessionFeatures()` | method | **GIỮ** |
| `isCloudAvailable()` | — | **THÊM** |
| `getActiveModelVersion()` | — | **THÊM** |
| `updateActiveModelVersion()` | — | **THÊM** |
| `cloudWarmupComplete` | — | **THÊM** |

### 3.3 FeatureBridge.java MODIFY

**File đích:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\player\features\FeatureBridge.java`

**Thay đổi chính:** Method `submitMLInference()` (khoảng line 323-368)

#### 3.3.1 Code thay thế cho submitMLInference()

```java
/**
 * Cloud-first ML inference submission.
 *
 * Priority:
 *   1. Cloud available → predictAll() async → CompositeResponse
 *   2. Cloud circuit broken → skip cloud, fallback
 *   3. No cloud → OnlineLogReg fallback (generic weights)
 *
 * Cloud response được apply thẳng vào FusionEngine.
 * Fallback dùng OnlineLogReg với weights thấp hơn (alert only).
 */
private void submitMLInference() {
    RemoteInferenceClient cloud = GrimAPI.INSTANCE.getRemoteInferenceClient();
    if (cloud == null) {
        fallbackToOnlineLogReg();
        return;
    }

    FusionEngine fusion = player.getFusionEngine();
    MLModelManager ml = GrimAPI.INSTANCE.getMlModelManager();

    // ── Cloud-first path ────────────────────────────────────────
    if (cloud.isEnabled() && !cloud.isCircuitBroken() && cloud.getRampUpFactor() > 0.1) {
        // Build whitebox và runtime context
        Map<String, Object> whitebox = new HashMap<>();
        whitebox.put("certainty", fusion.getLastWhiteboxCertainty());
        whitebox.put("category", fusion.getLastWhiteboxCategory() != null ?
            fusion.getLastWhiteboxCategory().name().toLowerCase() : "unknown");
        whitebox.put("vl", fusion.getLastViolationLevel());
        whitebox.put("flag_count", fusion.getTotalFlagCount());

        Map<String, Object> runtime = new HashMap<>();
        runtime.put("ping", player.getTransactionPing());
        try {
            runtime.put("tps", GrimAPI.INSTANCE.getPlatformServer().getTPS());
        } catch (Exception e) {
            runtime.put("tps", 20.0);
        }
        runtime.put("ramp_up", cloud.getRampUpFactor());

        // Async cloud inference
        cloud.predictAll(this, whitebox, runtime)
            .thenAccept(resp -> {
                if (resp == null || resp == CompositeResponse.EMPTY) {
                    cloud.recordFailure();
                    fallbackToOnlineLogReg();
                    return;
                }

                // Apply cloud results
                if (resp.aim() != null && resp.aim().risk() > 0) {
                    fusion.setBlackboxRisk(resp.aim().risk(),
                        FusionEngine.Category.COMBAT_AIM);
                }
                if (resp.click() != null && resp.click().risk() > 0) {
                    fusion.setBlackboxRisk(resp.click().risk(),
                        FusionEngine.Category.CLICK);
                }
                if (resp.session() != null && resp.session().risk() > 0) {
                    fusion.setBlackboxRisk(resp.session().risk(),
                        FusionEngine.Category.GHOST_PROFILE);
                }

                // Update confidence từ cloud
                double avgConfidence = 0;
                int count = 0;
                if (resp.aim() != null) { avgConfidence += resp.aim().confidence(); count++; }
                if (resp.click() != null) { avgConfidence += resp.click().confidence(); count++; }
                if (resp.session() != null) { avgConfidence += resp.session().confidence(); count++; }
                if (count > 0) {
                    fusion.updateConfidence(avgConfidence / count);
                }

                // Track active model version
                if (resp.aim() != null) {
                    ml.updateActiveModelVersion(resp.aim().modelVersion());
                }

                cloud.recordSuccess();
            })
            .exceptionally(ex -> {
                cloud.recordFailure();
                fallbackToOnlineLogReg();
                return null;
            });
    } else {
        // ── Fallback: OnlineLogReg ───────────────────────────────
        fallbackToOnlineLogReg();
    }
}

/**
 * Fallback inference dùng OnlineLogReg (local, siêu nhẹ).
 * Chỉ dùng khi cloud unavailable hoặc circuit broken.
 *
 * Đặc điểm fallback:
 * - Risk thấp hơn (do generic weights, không per-player)
 * - Chỉ COMBAT_AIM và GHOST_PROFILE (không CLICK riêng)
 * - Không confidence tracking
 */
private void fallbackToOnlineLogReg() {
    MLModelManager ml = GrimAPI.INSTANCE.getMlModelManager();
    if (ml == null) return;

    FusionEngine fusion = player.getFusionEngine();

    // Aim fallback (cần combat context)
    if (combatHistory.size() >= 3) {
        float[] features = ml.extractAimFeatures(this);
        double risk = ml.getAimOnline().predict(features);
        // Scale giảm: fallback risk chỉ dùng để ALERT, không ENFORCE
        risk *= 0.6; // Giảm 40% so với cloud score
        fusion.setBlackboxRisk(risk, FusionEngine.Category.COMBAT_AIM);
    }

    // Session/Ghost fallback (periodic, mỗi 100 ticks)
    if (currentFeatures.getSessionTicks() % 100 == 0 && featureHistory.size() >= 20) {
        float[] features = ml.extractSessionFeatures(this);
        double risk = ml.getSessionOnline().predict(features);
        risk *= 0.6; // Fallback discount
        fusion.setBlackboxRisk(risk, FusionEngine.Category.GHOST_PROFILE);
    }
}
```

#### 3.3.2 Thêm import cần thiết

```java
// Các import mới cho FeatureBridge
import java.util.Map;
import java.util.HashMap;
import ac.grim.grimac.manager.ml.RemoteInferenceClient.CompositeResponse;
import ac.grim.grimac.manager.ml.RemoteInferenceClient;
```

#### 3.3.3 Cập nhật computeProvisionalRisk()

Giữ nguyên `computeProvisionalRisk()` — heuristic risk vẫn chạy để:
1. Cung cấp risk ngay lập tức (không chờ cloud round-trip)
2. Double-check với cloud result
3. Fallback khi cloud không available

Tuy nhiên, thêm flag để tăng HEURISTIC_CAP khi cloud không available:

```java
private void computeProvisionalRisk() {
    double pf = getPingFactor();

    // KHI CLOUD KHÔNG AVAILABLE: heuristics cần nhạy hơn
    // (tuy nhiên không bao giờ vượt 0.80 — vẫn alert only)
    RemoteInferenceClient cloud = GrimAPI.INSTANCE.getRemoteInferenceClient();
    boolean cloudUnavailable = (cloud == null || !cloud.isCloudAvailable());
    double HEURISTIC_CAP = cloudUnavailable ? 0.80 : 0.70;

    // ... (phần còn lại giữ nguyên, sử dụng HEURISTIC_CAP mới)
}
```

### 3.4 FusionEngine.java MODIFY

**File đích:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\FusionEngine.java`

#### 3.4.1 Thêm cloud state

```java
// ── Cloud availability state ──────────────────────────────────
// Được cập nhật mỗi khi evaluate() được gọi.
// Dùng để quyết dịnh threshold adjustment và enforcement rules.
private volatile boolean cloudAvailable = false;
private volatile long lastCloudCheckTime = 0;
private static final long CLOUD_STALE_THRESHOLD = 30_000L; // 30s

/**
 * Kiểm tra cloud availability với caching.
 * Cache trong 30s để tránh gọi RemoteInferenceClient quá nhiều.
 */
private boolean isCloudAvailable() {
    long now = System.currentTimeMillis();
    if (now - lastCloudCheckTime > CLOUD_STALE_THRESHOLD) {
        RemoteInferenceClient cloud = GrimAPI.INSTANCE.getRemoteInferenceClient();
        cloudAvailable = (cloud != null && cloud.isCloudAvailable());
        lastCloudCheckTime = now;
    }
    return cloudAvailable;
}
```

#### 3.4.2 Cập nhật evaluate() — tightening khi cloud offline

Trong method `evaluate()`, thêm logic adjustment sau phần TPS hysteresis (sau line ~407):

```java
// ── CLOUD AVAILABILITY ADJUSTMENT ─────────────────────────────
// Khi cloud unavailable, blackbox risk chỉ từ OnlineLogReg (thấp hơn).
// Điều chỉnh thresholds để bù cho thiếu ML signal.
boolean cloudAvail = isCloudAvailable();
if (!cloudAvail) {
    // Blackbox risk từ fallback đã bị discount 40% → không đủ để ENFORCE
    // Vô hiệu hóa R2 (ML-only alert khi blackbox >= 0.85)
    // vì fallback OnlineLogReg không thể đạt 0.85.
    // Tăng threshold cho R3 (hybrid) và R4 (session accumulation).
    adjustedAlert = adjustedAlert * 1.5;        // 50 → 75
    adjustedSoftMitigate = adjustedSoftMitigate * 1.5; // 150 → 225
    adjustedEnforce = adjustedEnforce * 1.5;      // 300 → 450

    // Giới hạn max action: không ENFORCE từ blackbox khi cloud offline
    // (chỉ ENFORCE từ whitebox deterministic: R1, R6)
    cloudDegradationActive = true;
} else {
    cloudDegradationActive = false;
}
```

Thêm field:

```java
private boolean cloudDegradationActive = false;

/**
 * True nếu FusionEngine đang ở degraded mode (cloud offline).
 * PunishmentManager dùng flag này để hạn chế enforcement actions.
 */
public boolean isCloudDegradationActive() {
    return cloudDegradationActive;
}
```

#### 3.4.3 Cập nhật Rule 2 (ML risk cao) — không ENFORCE khi cloud offline

Trong R2 (khoảng line 483-489), thêm check:

```java
// ── RULE 2: ML risk cần corroboration ──────────────────────────
if (effectiveBlackboxRisk >= 0.85 && whiteboxCertainty < 0.5) {
    if (whiteboxCertainty >= 0.2) {
        accumulateRisk(15, whiteboxCategory);
    }
    // KHI CLOUD OFFLINE: không ALERT từ pure ML risk
    // (vì fallback risk không đáng tin cậy)
    if (cloudDegradationActive) {
        return Action.OBSERVE;
    }
    return Action.ALERT;
}
```

#### 3.4.4 Thêm getter cho PunishmentManager

```java
/**
 * Currently active model version string (từ cloud).
 */
public String getActiveModelVersion() {
    MLModelManager ml = GrimAPI.INSTANCE.getMlModelManager();
    return ml != null ? ml.getActiveModelVersion() : "local-fallback";
}
```

### 3.5 PunishmentManager.java MODIFY

**File đích:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\manager\PunishmentManager.java`

#### 3.5.1 autoTrainML — gửi training sample lên cloud

```java
/**
 * Auto-train ML models: gửi labeled sample lên cloud training API.
 * Thay thế local model training cũ.
 *
 * Khi cloud available, gửi thẳng lên /v1/train/sample.
 * Khi cloud offline, skip training (không local training nữa).
 */
private void autoTrainML(GrimPlayer player, Check check, FusionEngine.Category category) {
    RemoteInferenceClient cloud = GrimAPI.INSTANCE.getRemoteInferenceClient();
    if (cloud == null || !cloud.isEnabled()) return;
    if (!cloud.isCloudAvailable()) return; // skip khi cloud offline

    FeatureBridge fb = player.getFeatureBridge();
    if (fb == null) return;

    MLModelManager ml = GrimAPI.INSTANCE.getMlModelManager();

    // Xác dịnh features + category string
    float[] features = null;
    String catStr = null;
    float label = 1.0f; // cheat

    switch (category) {
        case COMBAT_AIM:
        case WATCHDOG_BOT:
            features = ml.extractAimFeatures(fb);
            catStr = "aim";
            break;
        case CLICK:
            features = ml.extractClickFeatures(fb);
            catStr = "click";
            break;
        default:
            features = ml.extractSessionFeatures(fb);
            catStr = "session";
            break;
    }

    if (features == null || catStr == null) return;

    // Async submit — không block game thread
    cloud.submitTrainingSample(catStr, features, label, player.uuid.toString());
}

/**
 * Weak label — gửi lên cloud với label thấp hơn (0.8).
 */
private void weakLabelML(GrimPlayer player, Check check,
        FusionEngine.Category category, double certainty) {
    RemoteInferenceClient cloud = GrimAPI.INSTANCE.getRemoteInferenceClient();
    if (cloud == null || !cloud.isEnabled()) return;
    if (!cloud.isCloudAvailable()) return; // skip khi cloud offline

    // Guard: skip weak label nếu certainty không đủ cao hoặc tổng flags thấp
    if (certainty < 0.85) return;
    if (player.getFusionEngine().getTotalFlagCount() < 5) return;

    FeatureBridge fb = player.getFeatureBridge();
    if (fb == null) return;

    MLModelManager ml = GrimAPI.INSTANCE.getMlModelManager();

    // Click weak label: cooldownAccuracy > 0.98 + perfectStreak > 20
    double cooldownAcc = fb.computeCooldownAccuracy();
    int perfectStreak = (int) fb.computePerfectStreak();
    if (cooldownAcc > 0.98 && perfectStreak > 20 && category == FusionEngine.Category.CLICK) {
        float[] features = ml.extractClickFeatures(fb);
        cloud.submitTrainingSample("click", features, 0.8f, player.uuid.toString());
    }

    // Aim weak label: smoothness > 0.95 + jerk < 0.05
    double smoothness = fb.computeAimSmoothness();
    double jerk = fb.computeYawJerkStdDev();
    if (smoothness > 0.95 && jerk < 0.05 && category == FusionEngine.Category.COMBAT_AIM) {
        float[] features = ml.extractAimFeatures(fb);
        cloud.submitTrainingSample("aim", features, 0.8f, player.uuid.toString());
    }
}
```

#### 3.5.2 Thêm cloud degradation check trong command filtering

Trong `fusionCommandAllowed()` hoặc trong `handleAlert()`:

```java
// Trong handleAlert(), sau khi fusionAction được xác dịnh:
// ── Cloud Degradation: giảm action khi cloud offline ──────────
if (fusion.isCloudDegradationActive() && fusionAction.getTier() >= FusionEngine.Action.ENFORCE.getTier()) {
    // Cloud offline → không ENFORCE từ blackbox
    // Chỉ ENFORCE từ whitebox deterministic (MOVEMENT/PACKET)
    if (category != FusionEngine.Category.MOVEMENT
            && category != FusionEngine.Category.PACKET
            && category != FusionEngine.Category.WATCHDOG_BOT) {
        fusionAction = FusionEngine.Action.ALERT;
    }
}
```

### 3.6 GrimAPI.java Wiring

**File đích:** `D:\Duancanhan\AC\Grim\common\src\main\java\ac\grim\grimac\GrimAPI.java`

#### 3.6.1 Thêm RemoteInferenceClient field

```java
@Getter
public final class GrimAPI {
    // ... existing fields ...

    // THÊM: RemoteInferenceClient
    private RemoteInferenceClient remoteInferenceClient;

    // ... existing code ...

    public void load(PlatformLoader platformLoader, Initable... platformSpecificInitables) {
        // ... existing init code ...

        this.mlQueue = new BoundedMLQueue();
        // CHANGED: MLModelManager không còn load models từ disk
        this.mlModelManager = new MLModelManager();

        // THÊM: khởi tạo RemoteInferenceClient
        this.remoteInferenceClient = new RemoteInferenceClient();

        // REMOVED: mlDataManager.loadModels() — không còn model files
        // REMOVED: mlDataManager.startAutoSave() — không còn auto-save

        // GIỮ: data collector + anomaly tracker
        this.mlDataManager = new MLDataManager();
        this.dataCollector = new DataCollector();
        this.tickManager.registerAsync(this.dataCollector);
        this.anomalyTracker = new AnomalyTracker();
        this.tickManager.registerAsync(this.anomalyTracker);

        this.initialized = true;
    }

    public void stop() {
        checkInitialized();
        initManager.stop();
        // CHANGED: không save models nữa
        // if (mlDataManager != null) mlDataManager.saveModels(mlModelManager);

        // THÊM: shutdown remote client
        if (remoteInferenceClient != null) remoteInferenceClient.shutdown();

        if (mlQueue != null) mlQueue.shutdown();
        if (watchdogBotManager != null) watchdogBotManager.shutdown();
        if (dataCollector != null) dataCollector.shutdown();
        if (anomalyTracker != null) anomalyTracker.shutdown();
    }
}
```

---

## 4. Graceful Degradation Matrix

| # | Scenario | ML Signal | FusionEngine Behavior | Action | 
|---|----------|-----------|----------------------|--------|
| 1 | **Cloud OK** | LightGBM từ cloud, risk full range [0-0.985] | Normal fusion, tất cả rules active | Bình thường |
| 2 | **Cloud timeout (>150ms)** | OnlineLogReg fallback (risk *= 0.6) | Fusion sees lower BB risk, threshold tightened 1.5x | Alert only, no enforce from BB |
| 3 | **Circuit breaker OPEN** (5 failures) | OnlineLogReg fallback, risk *= 0.6 | `cloudDegradationActive=true`, threshold 1.5x | Alert only |
| 4 | **Cloud 503** (server overload) | OnlineLogReg fallback, retry 1x | Same as timeout | Alert only |
| 5 | **Cloud offline >5 min** | No blackbox signal (risk từ heuristics 0.70 cap) | Whitebox-only: chỉ MOVEMENT/PACKET có ENFORCE | Whitebox deterministic only |
| 6 | **Plugin startup** (0-30s ramp-up) | Ramp-up factor 0.0→1.0 | Fusion tăng dần reliance trên cloud signal | Gradual confidence |
| 7 | **Cloud disabled** (config) | OnlineLogReg fallback permanent | `cloudDegradationActive=true` | Alert only, legacy mode |
| 8 | **Cloud auth fail** (wrong API key) | Circuit breaker tương tự #3 | Same as #3 | Alert only |

### 4.1 Timing expectations

```
Cloud request timeline (normal):
  0ms   → predictAll() gửi request
  50ms  → Cloud nhận, inference
  100ms → Response về plugin
  150ms → Timeout nếu chưa có response

Fallback trigger:
  150ms → Timeout → OnlineLogReg fallback
  5 failures → Circuit breaker OPEN for 30s
  30s   → HALF_OPEN, thử lại
  Success → Circuit CLOSED, trở lại normal
```

### 4.2 Risk score mapping

| Scenario | Aim Risk | Click Risk | Session Risk | Max confidence |
|----------|----------|------------|--------------|----------------|
| Cloud OK | 0.0 - 0.985 | 0.0 - 0.985 | 0.0 - 0.985 | 0.95 |
| Fallback (OLR) | 0.0 - 0.60 | 0.0 (not available) | 0.0 - 0.60 | 0.50 |
| Heuristics only | 0.0 - 0.70 | 0.0 - 0.70 | 0.0 - 0.50 | 0.40 |
| No blackbox | 0.0 | 0.0 | 0.0 | 0.0 |

### 4.3 FusionEngine behavior per scenario

```
                         Cloud OK          Cloud Offline (degraded)
                        ──────────────────────────────────────────────
  R1 (deterministic)      ENFORCE             ENFORCE (whitebox only)
  R2 (BB >= 0.85)         ALERT               OBSERVE (skip pure BB)
  R3 (hybrid)             ASSIST/MITIGATE     OBSERVE (BB too weak)
  R4 (session accum)      ENFORCE             SOFT_MITIGATE (cap)
  R6 (movement/packet)    ENFORCE             ENFORCE (no change)
  R7 (ghost/but)          ALERT               ALERT (no change)
```

---

## 5. Deprecation Plan cho Java Models

### 5.1 File status

| File | Package | Lines | Status | Lý do |
|------|---------|-------|--------|-------|
| `AimModel.java` | `ml` | 172 | **@Deprecated** | Thay bằng cloud endpoint |
| `ClickModel.java` | `ml` | 237 | **@Deprecated** | Thay bằng cloud endpoint |
| `SessionModel.java` | `ml` | 582 | **@Deprecated** | Thay bằng cloud endpoint |
| `GBDT.java` | `ml` | 439 | **@Deprecated** | Backend cho AimModel |
| `ConfidenceModel.java` | `ml` | 931 | **@Deprecated** | Confidence từ cloud response thay thế |
| `OnlineLogReg.java` | `ml` | 429 | **GIỮ** | Dùng làm fallback |
| `MLDataManager.java` | `manager.ml` | 197 | **@Deprecated** | Cloud lưu training data |
| `BoundedMLQueue.java` | `manager` | 127 | **GIỮ** | Vẫn dùng cho fallback, training |

### 5.2 @Deprecated annotation

```java
// AimModel.java
/**
 * @deprecated Replaced by cloud inference endpoint /v1/predict/aim.
 * Giữ source code để tham khảo, nhưng không compile trong build.
 * Sẽ xóa hoàn toàn sau migration period (3 tháng).
 */
@Deprecated
public final class AimModel {
    // ...
}

// ClickModel.java
/**
 * @deprecated Replaced by cloud inference endpoint /v1/predict/click.
 * ClickModel based on OnlineLogReg — model training chuyển lên cloud.
 */
@Deprecated
public final class ClickModel {
    // ...
}

// SessionModel.java
/**
 * @deprecated Replaced by cloud inference endpoint /v1/predict/session.
 * Session ensemble of 5 OnlineLogReg members — chuyển lên cloud.
 */
@Deprecated
public final class SessionModel {
    // ...
}

// GBDT.java
/**
 * @deprecated Only used by AimModel, which is also deprecated.
 * GBDT 30 trees max depth 4 — inference chuyển lên cloud.
 */
@Deprecated
public final class GBDT {
    // ...
}

// ConfidenceModel.java
/**
 * @deprecated Cloud inference trả về confidence score trực tiếp.
 * Local confidence model không cần thiết.
 */
@Deprecated
public final class ConfidenceModel {
    // ...
}

// MLDataManager.java
/**
 * @deprecated Training data storage chuyển lên cloud.
 * Không cần local CSV persistence.
 * Vẫn giữ MLDataManager skeleton cho config reading.
 */
@Deprecated
public final class MLDataManager {
    // ...
}
```

### 5.3 Build changes (build.gradle.kts)

Trong `D:\Duancanhan\AC\Grim\common\build.gradle.kts`:

```kotlin
dependencies {
    // GIỮ NGUYÊN: cloud.core, configuralize, snakeyaml, ...
    // (không thêm dependency mới — Java 11+ HttpClient là built-in)

    // REMOVED (sau migration period):
    // - Có thể remove nếu muốn loại bỏ compile của deprecated files
    // compileOnly(libs.grim.ml) — nếu có
}
```

**NOTE**: Java 11+ `java.net.http.HttpClient` (package `jdk.incubator.http` trong Java 9/10, chuẩn hóa trong Java 11 module `java.net.http`) là built-in, không cần thêm dependency. GrimAC đã chạy Java 17+ (theo build config), nên HttpClient available.

### 5.4 Migration timeline

```
Phase 1: Cloud + Local parallel  (Week 1-2)
  - Deploy cloud backend
  - RemoteInferenceClient rewrite active
  - FeatureBridge cloud-first (fallback to local khi cloud fail)
  - Cả cloud + local đều chạy, so sánh output

Phase 2: Cloud-first, local fallback  (Week 3-4)
  - Bỏ local model inference (AimModel, ClickModel, SessionModel)
  - OnlineLogReg giữ làm fallback
  - FusionEngine cloud degradation active
  - Monitoring: tracking cloud uptime, latency, fallback rate

Phase 3: Remove deprecated code  (Month 2-3)
  - Xóa AimModel.java, ClickModel.java, SessionModel.java
  - Xóa GBDT.java, ConfidenceModel.java
  - Xóa MLDataManager.java (hoặc keep skeleton)
  - Clean up imports và unused methods
  - Giảm BoundedMLQueue thread pool size (ít jobs hơn)
```

---

## 6. Full file inventory

### 6.1 Files to REWRITE

| File | Path | Changes |
|------|------|---------|
| `RemoteInferenceClient.java` | `manager/ml/RemoteInferenceClient.java` | Circuit breaker, per-model endpoints, health check, connection pool |
| `MLModelManager.java` | `manager/ml/MLModelManager.java` | Strip local models, keep feature extraction + OnlineLogReg fallback |

### 6.2 Files to MODIFY

| File | Path | Changes |
|------|------|---------|
| `FeatureBridge.java` | `manager/player/features/FeatureBridge.java` | Cloud-first `submitMLInference()`, `fallbackToOnlineLogReg()` |
| `FusionEngine.java` | `manager/FusionEngine.java` | Cloud degradation, threshold tightening |
| `PunishmentManager.java` | `manager/PunishmentManager.java` | Auto-train gửi cloud API, degradation check |
| `GrimAPI.java` | `GrimAPI.java` | Wire RemoteInferenceClient, remove model loading |

### 6.3 Files to DEPRECATE (giữ source, remove khỏi build sau)

| File | Path |
|------|------|
| `AimModel.java` | `ml/AimModel.java` |
| `ClickModel.java` | `ml/ClickModel.java` |
| `SessionModel.java` | `ml/SessionModel.java` |
| `GBDT.java` | `ml/GBDT.java` |
| `ConfidenceModel.java` | `ml/ConfidenceModel.java` |
| `MLDataManager.java` | `manager/ml/MLDataManager.java` |

### 6.4 Files to KEEP (no changes)

| File | Path | Reason |
|------|------|--------|
| `OnlineLogReg.java` | `ml/OnlineLogReg.java` | Fallback model |
| `BoundedMLQueue.java` | `manager/BoundedMLQueue.java` | Async queue cho fallback + training |
| `AnomalyTracker.java` | `manager/ml/AnomalyTracker.java` | Confidence modifier, không phụ thuộc model |
| `PlayerProfile.java` | `manager/ml/PlayerProfile.java` | Stats tracking, không phụ thuộc model |
| `FeatureVector.java` | `manager/player/features/FeatureVector.java` | Data class |
| `FeatureSnapshot.java` | (inner class FeatureBridge) | Data class |
| `ClickSnapshot.java` | (inner class FeatureBridge) | Data class |
| `CombatSnapshot.java` | (inner class FeatureBridge) | Data class |
| `LagProfile.java` | `manager/player/features/LagProfile.java` | Data class |

---

## 7. Config Changes

### 7.1 Config schema (config.yml / config.yml mới)

```yaml
# ── VNAC Cloud Configuration ──────────────────────────────────
VNAC:
  cloud:
    enabled: true
    url: "http://localhost:8000"
    api-key: "your-api-key-here"
    server-id: "default"
    
    # Connection
    connect-timeout-ms: 150
    request-timeout-ms: 150
    retry-count: 1
    
    # Circuit breaker
    failure-threshold: 5
    backoff-base-ms: 30000  # 30s
    backoff-max-ms: 300000  # 5 min
    
    # Health check
    health-check-interval-seconds: 60
    
    # Ramp-up
    ramp-up-duration-ms: 30000  # 30 giây
    
  # ── Legacy ML (fallback) ─────────────────────────────────────
  ml:
    # Feature extraction vẫn active (cần cho cloud + fallback)
    feature-extraction-enabled: true
```

### 7.2 ConfigManager integration

Trong `BaseConfigManager`, thêm các config key:

```java
// Các key mới
"VNAC.cloud.enabled"          → boolean (default: true)
"VNAC.cloud.url"              → string (default: "http://localhost:8000")
"VNAC.cloud.api-key"          → string (default: "")
"VNAC.cloud.server-id"       → string (default: "default")
"VNAC.cloud.connect-timeout-ms" → int (default: 150)
"VNAC.cloud.request-timeout-ms" → int (default: 150)
"VNAC.cloud.failure-threshold"  → int (default: 5)
"VNAC.cloud.backoff-base-ms"    → int (default: 30000)
"VNAC.cloud.backoff-max-ms"     → int (default: 300000)
"VNAC.cloud.health-check-interval-seconds" → int (default: 60)
"VNAC.cloud.ramp-up-duration-ms" → int (default: 30000)
```

---

## 8. Key Design Decisions

### 8.1 Why BoundedMLQueue is kept

Dù ML inference chuyển lên cloud, `BoundedMLQueue` vẫn cần cho:
1. **Fallback OnlineLogReg inference**: chạy async (không block game thread)
2. **Training sample submission**: `submitTrainingSample()` gọi async từ PunishmentManager
3. **Health check**: health check HTTP request chạy trên executor riêng (không dùng BoundedMLQueue)

Sau Phase 3 (khi deprecated code removed), có thể giảm thread pool size từ `CPUs/2` xuống `max(1, CPUs/4)`.

### 8.2 Why OnlineLogReg instead of heuristics for fallback

OnlineLogReg được chọn làm fallback thay vì heuristics thuần túy vì:
1. **Online training**: có thể cập nhật weights từ labeled samples (weak labels từ PunishmentManager)
2. **Better than heuristics**: dù không bằng GBDT, OLR vẫn cho risk scores calibrated hơn so với hardcoded thresholds
3. **Siêu nhẹ**: chỉ 6 floats cho weights + 1 bias, predict = 6 multiply-adds (dưới 1 microsecond)

### 8.3 Why CompletableFuture instead of blocking HTTP

Cloud-first inference KHÔNG block game thread:
- `predictAll()` trả về `CompletableFuture<CompositeResponse>`
- FeatureBridge dùng `.thenAccept()` để apply result
- Timeout 150ms → fallback tự động
- Exception handling → `recordFailure()` → circuit breaker → fallback

### 8.4 Why 150ms timeout

Timing budget cho inference:
```
0ms    → Game tick bắt đầu
0.01ms → FeatureBridge.tick() collect features
0.001ms→ submitMLInference() → predictAll() async
       │
150ms  → Timeout → CompletableFuture exceptionally
       │   → fallbackToOnlineLogReg() (OLR < 0.001ms)
       │
50ms   → FusionEngine.evaluate() → Action
       │
0.5ms  → Phần còn lại của tick processing
       │
~50ms  → Tổng tick time (khi cloud OK, 20 TPS)
```

150ms là đủ cho cloud round-trip (50-100ms typical) trong khi game tick vẫn chạy bình thường.

### 8.5 Why ramp-up factor

Khi plugin vừa start:
- Cloud backend có thể chưa sẵn sàng (health check đầu tiên chưa chạy)
- Connection pool chưa warm
- SSL handshake lần đầu có thể chậm

Ramp-up factor 30s đảm bảo FusionEngine không dựa vào cloud ngay lập tức.

---

## 9. Import Path Summary

```
Các import paths cho Java files:

Package ac.grim.grimac.manager.ml:
  - RemoteInferenceClient.java         (giữ nguyên)
  - MLModelManager.java                (giữ nguyên)
  - MLDataManager.java                 (giữ nguyên, deprecated)
  - AnomalyTracker.java                (giữ nguyên)
  - PlayerProfile.java                 (giữ nguyên)

Package ac.grim.grimac.manager.player.features:
  - FeatureBridge.java                 (giữ nguyên)

Package ac.grim.grimac.manager:
  - FusionEngine.java                  (giữ nguyên)
  - BoundedMLQueue.java               (giữ nguyên)
  - PunishmentManager.java             (giữ nguyên)

Package ac.grim.grimac.ml:
  - OnlineLogReg.java                  (giữ nguyên, collapse)
  - AimModel.java                      (deprecated)
  - ClickModel.java                    (deprecated)
  - SessionModel.java                  (deprecated)
  - GBDT.java                          (deprecated)
  - ConfidenceModel.java               (deprecated)

Package ac.grim.grimac:
  - GrimAPI.java                       (giữ nguyên)
```

---

## 10. References

- **Current RemoteInferenceClient**: `manager/ml/RemoteInferenceClient.java` (68 lines, thin HTTP client)
- **Current MLModelManager**: `manager/ml/MLModelManager.java` (175 lines, model manager + feature extraction)
- **Current FeatureBridge.submitMLInference()**: `manager/player/features/FeatureBridge.java` lines 323-368
- **Current FusionEngine.evaluate()**: `manager/FusionEngine.java` lines 339-550
- **Current BoundedMLQueue**: `manager/BoundedMLQueue.java` (128 lines)
- **OnlineLogReg (fallback)**: `ml/OnlineLogReg.java` (429 lines)
- **GBDT (deprecated)**: `ml/GBDT.java` (439 lines, 30 trees max depth 4)
- **GrimAPI wiring**: `GrimAPI.java` lines 93-113 (load method)
- **PunishmentManager.autoTrainML**: `manager/PunishmentManager.java` lines 389-436
- **Heartbeat**: `manager/ml/MLDataManager.java` (197 lines, load/save/auto-save)
