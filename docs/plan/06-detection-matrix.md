# Ma Trận Phát Hiện — Cập Nhật Đầy Đủ 1.21.11

## Mục đích

File này ánh xạ từng cheat family sang chiến lược phát hiện, mức độ tin cậy, loại bằng chứng cần thiết, và mức phạt cao nhất cho phép (punishment ceiling).

---

## Quy ước

| Ký hiệu | Nghĩa |
|---|---|
| ✅ Strong | Check có thể kết luận độc lập với độ chắc chắn cao |
| 🔶 Partial | Check đóng góp tín hiệu nhưng cần corroboration |
| ❌ No | Layer này không phù hợp cho domain này |
| 🔴 High | Có thể ban trực tiếp khi bằng chứng đủ tin cậy |
| 🟡 Medium | Cần corroboration hoặc lịch sử vi phạm trong session |
| 🟠 Low | Alert/Observe trước, không tự động ban sớm |

---

## 1. Combat Cheats

| Cheat | Whitebox | Blackbox | Hybrid | Enforcement Ceiling | Điều kiện thực thi hình phạt |
|---|---|---|---|---|---|
| **Reach** | ✅ Strong | ❌ | Optional | 🔴 High | Khoảng cách hit hình học phi lý, bù ping hợp lệ |
| **KillAura (Geometry)** | 🔶 Partial | ✅ Strong | ✅ Yes | 🟡 Medium | Cần rotation + timing + multi-target evidence |
| **KillAura (Watchdog Bot)**| ✅ Strong | ❌ | ✅ Yes | 🔴 High | Đánh trúng bot ≥3 lần/2 giây khi bot ở sau lưng (>110°) |
| **Hitbox abuse** | ✅ Strong | 🔶 Partial | ✅ Yes | 🔴 High | Tấn công ở góc không thể, raytrace miss nhưng hit |
| **AimAssist** | ❌ | ✅ Strong | ✅ Yes | 🟠 Low | Chỉ cảnh báo staff, phân tích biểu đồ phân phối góc |
| **AutoClicker** | 🔶 Partial | ✅ Strong | ✅ Yes | 🟠 Low | Cần entropy thấp + CPS limit + interval consistency |
| **Velocity** | ✅ Strong | 🔶 Partial | Optional | 🔴 High | Expected vs actual velocity delta vượt ngưỡng cho phép |
| **Criticals** | ✅ Strong | ❌ | Optional | 🔴 High | Nhảy crit nhưng gói tin báo onGround=true đồng thời |
| **Mace (1.21)** | ✅ Strong | ❌ | Optional | 🔴 High | Thực hiện smash damage nhưng Y fall < 1.5 blocks |
| **CrystalAura** | 🔶 Partial | ✅ Strong | ✅ Yes | 🟡 Medium | Tốc độ phá + đặt tinh thể phi lý, sai khoảng cách |
| **GhostClient** | ❌ | ✅ Strong | ✅ Yes | 🟠 Low | Chỉ phát cảnh báo staff, phân tích profile tổng thể |

---

## 2. Movement Cheats

| Cheat | Whitebox | Blackbox | Hybrid | Enforcement Ceiling | Điều kiện thực thi hình phạt |
|---|---|---|---|---|---|
| **Speed** | ✅ Strong | ❌ | ❌ | 🔴 High | horizontal velocity > expected max theo attributes |
| **Fly** | ✅ Strong | ❌ | ❌ | 🔴 High | Di chuyển chiều Y đi ngược lại trọng lực & state |
| **NoFall** | ✅ Strong | ❌ | ❌ | 🔴 High | Fall distance tích lũy > 3 nhưng không nhận damage |
| **Phase** | ✅ Strong | ❌ | ❌ | 🔴 High | Tọa độ player đi vào trong block cứng |
| **Jesus** | ✅ Strong | ❌ | ❌ | 🔴 High | Di chuyển trên chất lỏng vượt tốc độ/vật lý cho phép |
| **Step** | ✅ Strong | ❌ | ❌ | 🔴 High | Leo độ cao > 0.6 block mà không có thuộc tính Step |
| **Spider** | ✅ Strong | ❌ | ❌ | 🔴 High | Đi thẳng đứng lên tường không có thang/dây leo |
| **Blink** | ✅ Strong | 🔶 Partial | Optional | 🟡 Medium | Packet buffering, cluster tọa độ nhảy vọt |
| **Wind Hop (1.21)** | ✅ Strong | ❌ | ❌ | 🔴 High | Nhảy cao bất thường không khớp wind charge context |

---

## 3. Interaction / Player Cheats

| Cheat | Whitebox | Blackbox | Hybrid | Enforcement Ceiling | Điều kiện thực thi hình phạt |
|---|---|---|---|---|---|
| **Scaffold** | ✅ Strong | ✅ Strong | ✅ Yes | 🟡 Medium–High | Góc nhìn không hướng vào bề mặt block đặt nhưng vẫn đặt |
| **FastBreak** | ✅ Strong | ❌ | Optional | 🔴 High | Mining speed vượt tốc độ phá block lý thuyết |
| **FastPlace** | ✅ Strong | 🔶 Partial | Optional | 🟡 Medium | Đặt block liên tục vượt giới hạn cooldown |
| **InventoryMove** | ✅ Strong | ❌ | ❌ | 🔴 High | Vừa di chuyển vừa click mở GUI container bất hợp lý |
| **AutoTotem** | 🔶 Partial | ✅ Strong | ✅ Yes | 🟡 Medium | Phản xạ đổi totem < 50ms khi gần chết |
| **Freecam** | ✅ Strong | 🔶 Partial | Optional | 🔴 High | Camera di chuyển ra xa cơ thể người chơi thực tế |
| **Baritone** | 🔶 Partial | ✅ Strong | ✅ Yes | 🟠 Low (Alert) | Đường đi đồng đều hoàn hảo, không có overshoot |
| **Nuker** | ✅ Strong | ✅ Strong | ✅ Yes | 🟡 Medium | Phá nhiều block xung quanh cùng lúc |

---

## 4. Protocol / Packet Cheats

| Cheat | Whitebox | Blackbox | Hybrid | Enforcement Ceiling | Điều kiện thực thi hình phạt |
|---|---|---|---|---|---|
| **Timer** | ✅ Strong | ❌ | ❌ | 🔴 High | Packet rate tổng thể > 20 packets/s liên tục |
| **BadPackets** | ✅ Strong | ❌ | ❌ | 🔴 High | Trạng thái bất khả thi (sprint + sneak cùng lúc) |
| **AckFlood (1.21.11)** | ✅ Strong | 🔶 Partial | Optional | 🟡 Medium | Gửi quá nhiều fake ack packets suppress check |
| **PacketOrder** | ✅ Strong | ❌ | ❌ | 🔴 High | Sai lệch thứ tự packet giao dịch/di chuyển |

---

## Ràng Buộc Kiểm Chứng (Corroboration)

1. **Watchdog Bot**: Chỉ thực thi phạt khi đáp ứng đủ bộ lọc False Positive (Đánh trúng bot liên tục khi bot bay sau lưng người chơi ở khoảng cách rìa tầm đánh).
2. **AutoClicker / Click Automation**: Cần cả Entropy thấp + CPS đỉnh cao + Lặp lại chu kỳ để ban.
3. **Ghost Client**: Tuyệt đối không auto-ban, chỉ hiển thị alert và ghi bằng chứng cho staff.
4. **Blink**: Yêu cầu xác minh jitter ping trước khi đưa ra hành động soft setback.
