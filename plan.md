# Kế hoạch triển khai dự án AntiCheat (AC)

## Giai đoạn 0: Khởi tạo (Tuần 1)

- [x] Clone Grim core từ https://github.com/GrimAnticheat/Grim
- [ ] Fork lên GitHub cá nhân
- [ ] Build thành công: `./gradlew build`
- [ ] Test trên server local: plugin load được, không crash
- [ ] Đọc hiểu cấu trúc thư mục:
  ```
  common/src/main/java/ac/grim/
  ├── checks/        ← Các check phát hiện
  ├── data/          ← PlayerData, transaction
  ├── prediction/    ← Prediction engine (phần xịn nhất)
  ├── util/          ← Math, compatibility
  ├── manager/       ← Punishment, alert, violation
  └── event/         ← Packet listener
  ```

**Mốc:** Có build JAR chạy được trên server Paper 1.21

---

## Giai đoạn 1: Tinh gọn core (Tuần 2-3)

### 1.1. Đổi tên package
```
ac/grim/... → ac/youname/... (tuỳ chỉnh)
```

### 1.2. Rà soát check — giữ lại 20-30 check thiết yếu

**Giữ:**
```yaml
combat:
  - reach              # Reach prediction (tốt nhất thế giới)
  - killaura           # KillAura pattern
  - autoclicker        # Click analysis
  - velocity           # Anti-knockback

movement:
  - fly                # Fly prediction engine
  - speed              # Speed limit
  - noground           # Ground spoof
  - noglide            # Glide check
  - noscaffold         # Scaffold walk

packet:
  - timer              # Timer (tốt nhất, 1.005x)
  - badpackets         # Packet validation

player:
  - nogravity          # Gravity consistency
```

**Có thể bỏ (nếu không cần):**
- Scrutinize (quá nặng)
- Prediction guard phụ (trùng với main prediction)

### 1.3. Thêm lag compensation (nếu Grim chưa đủ)

Grim đã có transaction system tốt. Chỉ cần kiểm tra mọi check đã dùng ping compensation chưa. Nếu check nào dùng threshold cứng → sửa lại.

**Mốc:** Build JAR ~15-20 check, TPS >= 19.8 trên server 50 players

---

## Giai đoạn 2: Animation Engine (Tuần 4)

Gắp từ MLSAC sang:

```
MLSAC/src/main/java/wtf/mlsac/penalty/
├── BanAnimationEngine.java
├── BanAnimation.java
├── engine/AnimationConfigLoader.java
├── engine/AnimationManager.java
├── engine/AnimationPresets.java
├── engine/BanAnimationConfig.java
resources/animations/*.yml
resources/ANIMATION_GUIDE.txt
```

Việc:
- [ ] Copy animation files vào project
- [ ] Tích hợp penalty system của Grim với animation engine
- [ ] Thêm config: `penalties.animation.enabled`, `penalties.animation.type`
- [ ] Test animation: classic, dramatic, rainbow

**Mốc:** Ban animation chạy được khi flag player

---

## Giai đoạn 3: AI/ML (Tuần 5-6, không bắt buộc)

Gắp từ BakiVF:

```
BakiVF/ai_service.py              → Python microservice
BakiVF/RemoteModelClient.java     → Java client gọi AI
BakiVF/RemoteAIClient.java        → Fallback client
```

Việc:
- [ ] Copy ai_service.py vào `src/main/resources/python/`
- [ ] Copy RemoteModelClient.java vào package AC
- [ ] Implement feature collector (lấy feature từ Grim data)
- [ ] Export feature → ai_service.py → nhận risk score
- [ ] Tích hợp kết quả vào penalty decision

**Mốc:** Chạy được AI local model trên server dev

---

## Giai đoạn 4: Config & Release (Tuần 7)

- [ ] Config.yml hoàn chỉnh (kế thừa từ MLSAC)
- [ ] Messages.yml tùy chỉnh
- [ ] Auto-update (nếu cần)
- [ ] Permission system
- [ ] GitHub Actions build CI
- [ ] Release script

**Mốc:** Release v1.0.0

---

## Kiến trúc thư mục dự kiến

```
AC/Grim/                          
├── common/src/main/java/ac/
│   ├── core/                     # Core engine (kế thừa Grim)
│   ├── checks/                   # Tinh gọn 20-30 check
│   ├── animation/                # Animation engine (từ MLSAC)  ← mới
│   ├── ml/                       # AI/ML client (từ BakiVF)    ← mới
│   └── config/                   # Config loader
├── bukkit/                       # Bukkit module
├── fabric/                       # Fabric module
├── build.gradle.kts
└── README.md
```

---

## Timeline tổng

| Giai đoạn | Thời gian | Kết quả |
|-----------|-----------|---------|
| 0 — Setup | 1 tuần | Build được, chạy được |
| 1 — Core | 2 tuần | 20-30 check, TPS >= 19.8 |
| 2 — Animation | 1 tuần | Ban animation đẹp |
| 3 — ML | 2 tuần | AI phụ trợ (optional) |
| 4 — Release | 1 tuần | Plugin hoàn chỉnh |
| **Tổng** | **~7 tuần** | |

---

## Rủi ro & Giảm thiểu

| Rủi ro | Giải pháp |
|--------|-----------|
| Grim update breaking code | Theo dõi upstream, merge cẩn thận |
| Animation engine crash | Test kỹ, fallback về kick thường |
| AI model chưa train | Chạy hybrid: chỉ dùng AI làm advisory |
| TPS drop | Async ML pipeline (BakiVF có sẵn) |
