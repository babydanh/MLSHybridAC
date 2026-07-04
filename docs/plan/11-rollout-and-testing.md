# Kế Hoạch Rollout & Kiểm Thử Chi Tiết

Quy trình phát triển và đưa vào vận hành hệ thống Hybrid Anticheat được chia làm 5 Phase rõ ràng. Tuyệt đối không nhảy cóc các phase để bảo vệ server khỏi tình trạng False Positive hàng loạt.

---

## 📅 Sơ đồ Roadmap Phát Triển & Rollout

```text
Phase 0: Core Setup ──➔ Phase 1: Feature Bridge ──➔ Phase 2: Shadow Mode ──➔ Phase 3: Watchdog Bot ──➔ Phase 4: Production
(Compile, Animation)    (RAM Buffers, Queue)       (Async ML, Metrics)      (Dụ Aura, Corroboration)  (Adaptive Ban)
```

---

## 1. Chi Tiết Các Phase Phát Triển (Phân Chia Task)

### 🔴 Phase 0: Grim Core & Animation Stabilization
*Tập trung vào tính ổn định của Core, tích hợp và cấu hình hệ thống hoạt cảnh Ban.*

*   **Các Task lập trình cụ thể**:
    1.  [x] Kiểm tra tương thích hạt `ParticleCompat` trên phiên bản 1.21.11.
    2.  [x] Xóa bỏ/Dọn dẹp các dependency không dùng tới (WorldGuardCompat) để compile thành công module Bukkit.
    3.  [x] Tương thích hóa group name và package Java (giữ nguyên cấu trúc `ac.grim.grimac` của core để tránh vỡ dependency).
    4.  [ ] Tối ưu hóa memory footprint của `BanAnimationEngine` khi chạy hiệu ứng nặng (Lightning, Spiral particles).
    5.  [ ] Viết unit test giả lập cho lệnh `/bananimation` trên server Folia và Paper.
*   **Tiêu chí đầu ra (Exit Criteria)**:
    - Module Bukkit compile thành công hoàn toàn mà không có bất kỳ warning/error nào về internal API.
    - Chạy thử nghiệm animation trên Folia không gây tụt TPS hoặc rò rỉ bộ nhớ (memory leak).

---

### 🟠 Phase 1: Bridge Feature Extraction & RAM Buffers
*Tạo lập cơ sở dữ liệu trên RAM và trích xuất vector đặc trưng.*

*   **Các Task lập trình cụ thể**:
    1.  [ ] Thiết lập cấu trúc dữ liệu `PlayerData` với các `EvictingQueue` rolling buffers thô (40 ticks position, 50 clicks...).
    2.  [ ] Tạo `FeatureBridge` thu thập và đóng gói dữ liệu thô + Facts đầu ra của Grim thành `FeatureVector`.
    3.  [ ] Code lớp tính toán chỉ số mạng `LagProfile` (đo lường ping jitter và packet loss dựa trên Transaction RTT).
    4.  [ ] Thiết lập Thread Local Storage để cô lập bộ nhớ `PlayerData` cho từng người chơi.
*   **Tiêu chí đầu ra (Exit Criteria)**:
    - Feature extraction chạy bất đồng bộ hoàn tất trong < 1ms per window.
    - Không xảy ra xung đột luồng (thread race conditions) khi truy cập lịch sử packet.

---

### 🟡 Phase 2: Shadow Mode / Dry-Run (Quan sát không phạt)
*Tích hợp Blackbox ML Service và đánh giá độ chính xác ngầm.*

*   **Các Task lập trình cụ thể**:
    1.  [ ] Nhúng ONNX Runtime vào Java Virtual Machine để chạy local model (GBDT cho Aim, LogReg cho Click).
    2.  [ ] Tạo hàng đợi bất đồng bộ có giới hạn (Bounded Queue - max 500 tasks) để giao tiếp với model.
    3.  [ ] Viết thuật toán `BayesianFusion` để kết hợp Facts của Grim và Risk của ML.
    4.  [ ] Tích hợp ghi bằng chứng JSON (`EvidencePacket`) ngầm xuống SQLite/MySQL.
    5.  [ ] Thiết lập kênh cảnh báo Alert ngầm chỉ hiển thị cho Staff và ghi log để đo đạc False Positive.
*   **Tiêu chí đầu ra (Exit Criteria)**:
    - Hệ thống ML chạy liên tục 48 tiếng trên môi trường test/staging có người chơi thật.
    - Latency trung bình của local inference < 3ms.
    - Đo đạc tỷ lệ cảnh báo sai (False Positive Rate) dưới 0.1%.

---

### 🟢 Phase 3: Watchdog Bot Integration & Corroboration
*Kích hoạt Bot mồi nhử dụ các client KillAura tự động.*

*   **Các Task lập trình cụ thể**:
    1.  [ ] Viết module spawn Fake NPC (Packet-based) bay xung quanh đầu người chơi ngoài tầm FOV (> 110 độ).
    2.  [ ] Tạo bộ lọc FOV xác định xem người chơi có thực sự nhìn thấy Bot bằng mắt thường trước khi đánh hay không.
    3.  [ ] Code check đếm số lần đánh trúng Bot liên tục (nhấp nhả) và so khớp khoảng cách hình học cự ly đánh.
    4.  [ ] Cấu hình Fusion Engine: Đánh trúng Bot hợp lệ ≥ 3 lần/2s sẽ kích hoạt corroborate nâng cấp Action lên SOFT_MITIGATE.
*   **Tiêu chí đầu ra (Exit Criteria)**:
    - Bot spawn mượt mà trên server (kể cả Folia với đa vùng threaded region).
    - Player bình thường (legit) xoay chuột nhanh không bao giờ bị flag nhầm (tỷ lệ FP cho Watchdog = 0%).
    - Các client cheat phổ biến (LiquidBounce, Meteor, Rise) bị flag 100% khi bật KillAura.

---

### 🔵 Phase 4: Tích Hợp Cấu Hình Phạt (Ban Animation Integration) & Vận Hành
*Liên kết hình phạt của hệ thống với hoạt cảnh Ban để tự động hóa.*

*   **Các Task lập trình cụ thể**:
    1.  [ ] Tích hợp hoạt cảnh ban vào `PunishmentManager.java`. Cho phép cấu hình thay thế lệnh trừng phạt thô trong config:
        ```yaml
        # Cấu hình mẫu trong config.yml
        punishment-commands:
          killaura:
            - "bananimation %player% dramatic_ban ban %player% MLSHybridAC: Killaura Detection"
          speed:
            - "bananimation %player% classic_ban tempban %player% 7d Speed Hack"
        ```
    2.  [ ] Bật hình phạt tự động Tier 1 (Setback/Kick ngay cho các lỗi di chuyển vật lý của Grim).
    3.  [ ] Bật hình phạt Tier 2 (Auto-Ban bằng hoạt cảnh Ban Animation) khi có sự xác nhận của Watchdog Bot hoặc Fusion với `posterior > 0.95`.
    4.  [ ] Tích hợp tính năng Load Shedding tự động hạ cấp/tắt ML khi TPS server tụt xuống dưới 18.
    5.  [ ] Expose đầy đủ các chỉ số Prometheus/JMX (Inference latency, TPS Mode, Active queues) lên Grafana Dashboard.
*   **Tiêu chí đầu ra (Exit Criteria)**:
    - Khi người chơi bị ban bằng lệnh hệ thống, animation tự động kích hoạt mượt mà, sau khi kết thúc animation thì lệnh console ban mới thực thi.
    - TPS của server game luôn giữ vững ở mức ≥ 19.5 trong điều kiện tải nặng thông thường.

---

## 2. Chiến Lược Kiểm Thử (Testing Matrix)

Để đảm bảo chất lượng, mỗi Phase bắt buộc phải vượt qua các bài kiểm tra sau:

### A. Replay Tests (Kiểm thử gói tin thô)
*   **Mục tiêu**: Sử dụng file log packet thô (`.ncp` hoặc định dạng capture packet của Grim) của các cheater đã bị ban để phát lại (replay) qua Ingestion Layer trên server Staging.
*   **Yêu cầu**: Kết quả đầu ra của Fusion Engine ở phiên bản mới phải phát hiện được (flagged) tương đương hoặc sớm hơn phiên bản cũ mà không làm thay đổi các ca người chơi sạch (legit).

### B. Live Adversarial Tests (Thực chiến giả lập)
*   **Mục tiêu**: Thuê/sử dụng tester sử dụng các client cheat phổ biến để phá hoại server test.
*   **Các trường hợp kiểm thử**:
    - Chạy Fly/Speed trong điều kiện ping cao (200ms - 400ms) → Anticheat phải setback mượt mà, không ban nhầm.
    - Sử dụng Wind Charge / Mace smash 1.21 → Validate đúng, không flag lag.
    - Bật bypass KillAura cấu hình mượt (humanized aim) → ML Aim check phải bắt được sau 5-10 giây combat.

### C. Performance Benchmarking
*   **Mục tiêu**: Đo đạc CPU time.
*   **Yêu cầu**: Sử dụng Spark Profiler (`/spark sampler`) trên server:
    - Tổng thời gian xử lý của Anticheat trên Game Thread phải chiếm **< 3%** tổng CPU thời gian xử lý của server tick.
    - Async thread pool không được chiếm quá 15% tài nguyên CPU của hệ thống máy chủ vật lý.
