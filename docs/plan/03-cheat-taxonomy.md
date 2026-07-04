# Phân Loại Cheat — Cập Nhật Cho 1.21.11

## Mục đích

Taxonomy theo hành vi runtime, không phải danh sách class code. Mỗi entry phải có:
- **Triệu chứng packet/state** mà anticheat có thể quan sát
- **Domain xử lý** chính (whitebox / hybrid / blackbox)
- **Ghi chú về 1.21.11** nếu game version thay đổi cơ chế

---

## 1. Combat Cheats

### 1.1 KillAura

**Triệu chứng:**
- Attack packet gửi mà không có rotation hợp lệ về phía target
- Multi-target: đánh nhiều entity trong cùng một gameseed tick
- Silent aura: rotation không thay đổi nhưng hit entity khác nhau
- Behind-back attack: góc giữa look-direction và target > 90° vẫn hit
- Snap: yaw/pitch thay đổi đột ngột ngay trước hit packet
- Rotation-to-hit delay bất thường (hit đến trước khi rotation ổn định)

**1.21.11 Notes:**
- Attribute system mới (1.21): `generic.attack_damage`, `generic.attack_speed` cần được cập nhật trong expected damage validation
- Mace item (1.21): Heavy blow mechanic — fake smash attack mà không có đủ fall velocity

**Domain:** Whitebox (rotation, reach geometry) + Blackbox (pattern, multi-tick sequence)

---

### 1.2 KillAura Watchdog (Botting Check)

Hệ thống dụ cheat bằng cách spawn các thực thể giả lập (Fake Entities/Bots) bay xung quanh người chơi để phát hiện hành vi tự động tương tác của hack client.

**Triệu chứng:**
- Người chơi gửi packet tương tác tấn công (`PacketPlayInUseEntity`) trúng vào thực thể Watchdog bot.
- Tốc độ tương tác cực nhanh ngay khi bot vừa spawn.

**Quy tắc phòng chống False Positive (Đánh nhầm người chơi giỏi / cố tình đánh thử):**
1. **Bộ lọc FOV (Field of View)**: Bot luôn được spawn ở góc khuất (phía sau lưng hoặc góc đỉnh đầu > 110 độ so với hướng nhìn của người chơi). Nếu người chơi xoay camera hướng về phía bot rồi mới click đánh → **Bỏ qua** (coi là phản xạ tự nhiên). Chỉ flag khi camera hướng đằng trước nhưng packet đánh lại bay ra đằng sau.
2. **Quỹ đạo bay hình học**: Bot di chuyển với vận tốc phi vật lý (vòng tròn liên tục) ở rìa tầm đánh (3.5 - 4.5 blocks). Người chơi thường không thể tracking tay chuẩn xác ở cự ly và tốc độ này.
3. **Mức độ lặp lại (Accumulation)**: Chỉ đánh trúng 1 lần duy nhất → Không phạt. Chỉ flag khi đánh trúng liên tục ≥ 3 lần trong vòng 2 giây khi bot liên tục đổi hướng di chuyển.

**Domain:** Whitebox (packet interaction validation) + Hybrid (trigger khi Aim/Click suspicion tăng cao).

---

### 1.3 Reach

**Triệu chứng:**
- Hit distance > server-calculated max (vanilla 3.0 blocks, sprint-attack 4.0 blocks tương đối)
- Raytrace từ camera to hitbox bị miss nhưng attack packet vẫn đến
- Hitbox edge abuse: hit entity ở góc cực biên liên tục

**1.21.11 Notes:**
- Transaction-based compensation phải dùng: khi server nhận hit, phải lấy entity state tại tick của packet (compensated tick), không phải state hiện tại
- Hit validation cần account cho `entity_collision_box` của entity type, không dùng generic bounding box

**Domain:** Whitebox (geometry + transaction latency compensation)

---

### 1.4 AimAssist

**Triệu chứng:**
- Lock-on: target relative angle không thay đổi khi player di chuyển nhưng target di chuyển mạnh
- Micro-correction phi nhân tính: jerk (thay đổi acceleration) quá nhỏ và quá đều
- Snap-back: rotation về anchor sau mỗi swing quá đều
- Pitch không tự nhiên: humans thường pitch ít hơn yaw khi combat

**Features quan trọng:**
- Yaw jerk distribution — human là Gaussian có tail, cheat là uniform hoặc quá nhọn
- Rotation-to-hit delta: khoảng cách góc giữa look khi attack với target center
- Inter-hit rotation consistency (std dev quá thấp là suspicious)

**Domain:** Blackbox chính — behavioral statistics, sequence model

---

### 1.5 AutoClicker / ClickAutomation

**Triệu chứng:**
- CPS > physical human limit (~16-18 CPS sustained, burst có thể 20-22)
- Interval std dev cực thấp (script đều tick)
- Interval entropy thấp — quá ít variation trong khoảng cách click
- Click pattern lặp lại theo chu kỳ cố định

**1.21.11 Notes:**
- Butterfly clicking và jitter clicking vẫn hợp lệ humanly nhưng có signature riêng — không nên flag bừa
- Attack cooldown 1.21 reset mỗi `generic.attack_speed` ticks — cần tính exact cooldown, không hardcode

**Domain:** Hybrid — packet spacing (whitebox) + statistical modeling (blackbox)

---

### 1.6 Velocity Abuse / Anti-Knockback

**Triệu chứng:**
- Sau khi nhận knockback packet, actual velocity thấp hơn expected
- Partial cancel: nhận 30-70% knockback (legit bypass phổ biến nhất)
- Directional cancel: hủy knockback ngang nhưng giữ vertical

**1.21.11 Notes:**
- Knockback attribute thay đổi theo armor tiers và enchantments (Resistance, Feather Falling không ảnh hưởng knockback ngang)
- Player sprint-cancel technique là legit — cần phân biệt với actual velocity cheat

**Domain:** Whitebox — so sánh expected vs actual velocity vector sau knockback event

---

### 1.7 Criticals

**Triệu chứng:**
- Critical hit được gửi nhưng player onGround tại tick đó
- Spoof fall state: gửi `onGround=false` ngay trước attack rồi `onGround=true` ngay sau
- Impossible vertical transition: không có enough air-time để thực hiện legit crit

**1.21.11 Notes:**
- Wind charge knockback (1.21) tạo ra nhiều edge case vertical motion — cần account
- Mace smash attack là một dạng crit riêng với yêu cầu height ≥ 1.5 block fall

**Domain:** Whitebox — ground state + vertical velocity history

---

### 1.8 Mace / Heavy Weapon (Mới trong 1.21)

**Triệu chứng:**
- Smash attack (mace) khi không có đủ fall distance
- Fake height: spoof server-side về vị trí Y trước khi execute smash
- Kết hợp với Wind Charge để fake fall distance

**Features cần:**
- Pre-attack Y trajectory: tối thiểu phải rơi > 1.5 blocks trước đó
- Accumulated fall velocity so với expected
- Wind Charge usage context (legitimate boosted fall vs spoofed)

**Domain:** Whitebox (physics state) — check mới cần implement

---

### 1.9 CrystalAura

**Triệu chứng:**
- Place + detonate crystal trong cùng một tick hoặc liên tiếp không có animation delay
- Crystal placement ở vị trí không thể trong reach geometry
- Crystal interact packet khi crystal không trong line-of-sight

**Domain:** Whitebox (reach, interaction validity, timing) + Hybrid (pattern)

---

### 1.10 GhostClient / Legit Profile

**Đây là bài toán khó nhất.** Không có single check phát hiện được.

**Triệu chứng tổng hợp:**
- Aim quá ổn định — jitter distribution không khớp human distribution
- Reaction time đến target di chuyển nhanh bất thường
- Hitbox "glue" — tỷ lệ hit extreme khi target di chuyển phức tạp
- Combat-window attack timing đồng đều phi nhân tính
- Không có "bad tick" — human có occasional missed click, delayed reaction

**Domain:** Blackbox + Session-level profile — chỉ alert, không enforce trực tiếp

---

## 2. Movement Cheats — Cập Nhật 1.21.11

### 2.1 Speed

**Triệu chứng:**
- Horizontal velocity vượt max allowed theo attribute và state (sprint, ground, fluid)
- Abuse terrain modifiers: friction, ice, soul sand, honey, slime

**1.21.11 Notes:**
- Attribute `generic.movement_speed` có thể bị modify hợp lệ bởi effects, enchantments
- Wind charge boost là legit horizontal speed boost — cần tracked separately
- Breeze projectile pushback phải được account trong expected velocity

**Domain:** Whitebox — movement prediction engine

---

### 2.2 Fly

**Triệu chứng:**
- Không có downward acceleration khi không có ground, liquid, ladder, climbable, elytra context
- Giữ altitude hoặc chỉ mất độ cao rất ít
- Vertical velocity không khớp prediction

**1.21.11 Notes:**
- Wind charge có thể tạo ra legitimate "fly-like" state thoáng qua — phải track
- Elytra state phức tạp hơn với Vex giáp enchant và slow-falling effect

**Domain:** Whitebox

---

### 2.3 NoFall

**Triệu chứng:**
- Đất tiếp xúc sau fall nhưng fall damage không xảy ra
- Fake ground state packet ngay trước landing
- Impossible state transition: từ high altitude xuống ground không qua expected fall velocity

**Domain:** Whitebox — fall distance tracker, ground state validator

---

### 2.4 Phase / NoClip

**Triệu chứng:**
- Player position nằm trong solid block
- Movement delta cross qua block boundary mà không có hợp lệ gap

**1.21.11 Notes:**
- Block hitbox mới (copper doors, copper trapdoors, trial spawner) cần đầy đủ trong world replica

**Domain:** Whitebox — world replication + collision mesh

---

### 2.5 Blink / Packet Buffering

**Triệu chứng:**
- Position cluster: nhiều position packets cùng đến một lúc sau khoảng im lặng
- Player thoát biến trên server side (không có packets trong quá lâu)
- Sudden position jump không khớp với trajectory

**Domain:** Whitebox (timer, packet rate) + Hybrid (pattern anomaly)

---

### 2.6 Movement cheats mới trong 1.21

**Vaulting / Hop spam:**
- Abuse jump mechanics với crawling hitbox transition
- Vào/ra crawl state liên tục để bypass collision

**Wind Charge teleport:**
- Dùng wind charge timing để "blink" qua block boundaries

**Domain:** Whitebox cần được cập nhật để cover các state mới

---

## 3. Interaction / Player Cheats

### 3.1 Scaffold

**Triệu chứng:**
- Block placement khi rotation không hướng về surface hợp lệ
- Placement trong khi đang nhảy với rotation không tự nhiên
- Tốc độ placement vượt cooldown

**1.21.11 Notes:**
- Hardened clay, copper blocks có hitbox đặc biệt — kiểm tra surface validity theo loại block
- Trial key và vault block placement rules mới

**Domain:** Whitebox (rotation, timing) + Blackbox (pattern)

---

### 3.2 FastBreak

**Triệu chứng:**
- Block break trong thời gian ngắn hơn mining time hợp lệ
- Mining time phụ thuộc: tool, enchantment, material, haste effect, underwater, onGround

**1.21.11 Notes:**
- Efficiency V + Haste II là legit case cần tính chính xác
- Breeze-proof blocks có hardness riêng

**Domain:** Whitebox

---

### 3.3 AutoTotem / Swap Automation

**Triệu chứng:**
- Totem swap xảy ra với reaction time < 50ms sau near-death event
- Inventory slot change packet đến trước death event propagation

**Domain:** Hybrid (packet timing + behavioral)

---

### 3.4 Baritone / Botting

**Triệu chứng:**
- Pathfinding quá đều — không có micro-adjustment tự nhiên
- Navigation không có overshoot correction
- Long-distance path không có dừng/nhìn bất thường

**Domain:** Blackbox + Session (chỉ alert, không auto-ban)

---

### 3.5 InventoryMove

**Triệu chứng:**
- Movement packet đến khi player đang có GUI open
- Container transaction trong khi đang combat bất thường

**Domain:** Whitebox (state conflict check)

---

## 4. Protocol / Packet Cheats

### 4.1 Timer

**Triệu chứng:**
- Packet rate tổng thể nhiều hơn 20 packets/giây sustained
- Movement packet đến nhanh hơn server tick cycle

**Domain:** Whitebox (packet rate monitoring)

---

### 4.2 BadPackets

**Triệu chứng:**
- Impossible state combination: sneak + sprint + jump đồng thời
- Invalid sequence: interact before look
- Out-of-order packets

**1.21.11 Notes:**
- Packet format thay đổi từ 1.20.5+ (slot data format, component-based item serialization)
- New packets: `BUNDLE_DELIMITER`, entity event packets mới cho trial spawner

**Domain:** Whitebox

---

### 4.3 AntiDebug / Flag Suppression

**Mới nhận thức:** Một số cheat client chủ động gây nhiễu detection bằng cách:
- Gửi fake jitter packets để làm rotation stats trông "human"
- Gửi unnecessary ack packets để làm timer check trông sạch

**Cần xử lý bằng:** Statistical model detect manipulation chứ không chỉ threshold check
