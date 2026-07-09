# Cập Nhật Cho 1.9 PVP

## Sự khác biệt 1.9+ vs 1.8

| Khía cạnh | 1.8 | 1.9+ |
|---|---|---|
| Attack cooldown | Không có | Có (0.5s-1.6s tùy weapon) |
| CPS tối đa | 18-20 | ~3-4 (sword) |
| Click timing | Variable | **Phải chờ cooldown** |
| Criticals | Nhảy + click | Nhảy + click (đúng cooldown) |
| Shield | Không | Có |

## ClickModel 1.9+ (sửa)

**Feature cũ (1.8) sẽ bỏ:**
- `CPS` (vô nghĩa với 1.9+, cooldown giới hạn)
- `burstRatio` (burst click không tồn tại trong 1.9+)

**Feature mới cho 1.9+:**

```
f1: cooldownAccuracy    — Độ chính xác của interval so với cooldown chuẩn
                          Human: ±50-200ms, Bot: <5ms
f2: missRatio           — Tỷ lệ bỏ lỡ cơ hội tấn công (cooldown đã reset nhưng không click)
                          Human: 10-30%, Bot: 0-2%
f3: hitMissRatio        — Tỷ lệ trúng/thất bại khi target trong tầm
                          Human: 60-85%, Bot: 95-100%
f4: criticalRatio       — Tỷ lệ crits (nhảy + attack đúng timing)
                          Human: 20-50%, Bot: 70-100%
f5: perfectCooldownStreak— Số lần attack liên tiếp đúng cooldown
                          Human: 2-5, Bot: 20+
```

## AimModel 1.9+ (giữ nguyên)
Rotation analysis không thay đổi giữa 1.8 và 1.9+.

## SessionModel (cập nhật)
- Bỏ CPS-based features
- Thêm "shieldUsePattern" — cách sử dụng shield
- Thêm "weaponSwitchSpeed" — tốc độ switch item

## FusionEngine (giữ nguyên)
Không cần sửa.
