# Execution Plan — Fix Bypass & Detection Gaps

## Phase 1: Subagent A — Watchdog Bot Overhaul

### Vấn đề
- Bot không render skin trên 1.19+ (tablist removed too early)
- Cheat có thể detect bot bằng predictable orbit (4 blocks, 0.1 rad/tick cố định)
- Hit tracking window bị reset sai (dùng spawnTime thay vì firstHitTime)

### Fix
1. spawn(): giữ tablist ADD_PLAYER 1-2 tick trước khi remove → client render skin
2. updateOrbitPosition(): orbit radius jitter 3-5 blocks, random speed 0.08-0.15 rad/tick, bob lên xuống
3. recordHit(): fix window — dùng firstHitTime riêng, không dùng spawnTime
4. isBehindPlayer(): thêm random boolean — thỉnh thoảng spawn bot ờ phía trước (không thể predict)

### Build verify
```bash
cd D:\Duancanhan\AC\Grim && ./gradlew :common:compileJava -x test
```

---

## Phase 2: Subagent B — AutoJump Reset Detection

### Vấn đề
- `combatJumpTicks` và `combatNonJumpTicks` chỉ reset khi combat kết thúc — số liệu thiên lệch
- Threshold `> 0.8` (80%) quá cao — cheat có thể jump 79% và bypass
- Legit player 1.9+ cũng jump 50-60% — nguy cơ false flag

### Fix
1. FeatureBridge.onAttack() reset jump counter sau mỗi attack burst (5s không combat)
2. computeAutoJumpRatio() dùng sliding window 5 giây thay vì toàn bộ session
3. Thêm jumpConsistency — stddev của jump interval. Auto-jump có interval đều (stddev < 50ms). Human không đều (stddev > 100ms)
4. FusionEngine: autoJump risk chỉ dùng cho hybrid (cần whitebox corroboration) — không bao giờ ENFORCE 1 mình

### Safeguard cho legit player
- jumpRatio < 0.7 + jumpConsistency > 100ms → không flag
- Cần combat context: chỉ active khi player đã tấn công trong 5s gần nhất

---

## Phase 3: Subagent C — AutoTotem Overhaul

### Vấn đề
- Chỉ bắt `SWAP_ITEM_WITH_OFFHAND` (phím F) — cheat có thể dùng hotkey (1-9) hoặc inventory click
- Reaction time threshold 100ms quá thấp — chỉ bắt được totem swap cục bộ
- Legit player cũng swap totem khi gần chết — false flag

### Fix
1. Bắt tất cả hình thức swap totem vào offhand:
   - SWAP_ITEM_WITH_OFFHAND (F) — đã có
   - HELD_ITEM_CHANGE (hotkey 1-9) — mới
   - INVENTORY_CLICK (click chuột vào offhand slot) — mới (qua Creative/Inventory packet)
2. Reaction time threshold: 100ms cho F swap, 200ms cho hotkey
3. Cần health drop > 6 HP trong 1 tick trước swap (tránh false flag)
4. FusionEngine: AutoTotem flag → ALERT + CANCEL, không ban

---

## Phase 4: Subagent D — Legit Player Safeguards

### Vấn đề
- computeProvisionalRisk() hard thresholds có thể flag legit player skill cao
- SuspicionCheck accumulate risk từ heuristic — legit player có thể bị setback

### Fix
1. FusionEngine: Rule 4 (accumulate risk) chỉ ENFORCE nếu certainty ≥ 0.6 VÀ combined từ ít nhất 2 category khác nhau
2. Thêm "trusted behavior" tracking: nếu player có history legit dài (1+ giờ không cheat) → giảm sensitivity 50%
3. computeProvisionalRisk(): tất cả heuristic risk phải có threshold động (adaptive baseline) — không dùng số cứng
4. SuspicionCheck: setback chỉ active nếu sessionRisk ≥ 30 VÀ có at least 3 flags từ different checks
5. Grace period: extend từ 60s lên 120s cho movement/packet

### Build verify
```bash
cd D:\Duancanhan\AC\Grim && ./gradlew :common:build
```
