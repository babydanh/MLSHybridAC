# Đặc Tả Feature — Cập Nhật Kỹ Thuật

## Mục đích

Mỗi feature phải có: tên, unit, nguồn, cửa sổ sampling, consumer (whitebox/blackbox/fusion), chi phí thu thập.

---

## Nhóm 1: Packet & Timing

| Feature | Unit | Nguồn | Window | Consumer | Chi phí |
|---|---|---|---|---|---|
| `packet_rate_total` | packets/s | PacketListener | 1s sliding | Whitebox (Timer) | Thấp |
| `movement_packet_interval` | ms | Position packet delta-t | Per-packet | Whitebox | Thấp |
| `attack_packet_interval` | ms | UseEntityPacket delta-t | Per-packet | Hybrid | Thấp |
| `block_place_interval` | ms | BlockPlacePacket delta-t | Per-packet | Whitebox (FastPlace) | Thấp |
| `block_break_interval` | ms | BlockBreakPacket delta-t | Per-packet | Whitebox (FastBreak) | Thấp |
| `timer_drift` | ticks | Packet count vs expected | 5s window | Whitebox (Timer) | Thấp |
| `burst_packet_window` | count | Packet bursts > 3σ | 200ms window | Hybrid | Thấp |
| `transaction_rtt` | ms | Transaction confirm delta | Per-transaction | Whitebox (Reach compensation) | Thấp |
| `ping_smoothed` | ms | EWM average RTT | 10s window | Fusion (context) | Thấp |
| `ping_jitter` | ms | RTT standard deviation | 10s window | Fusion (context weighting) | Thấp |
| `packet_loss_proxy` | ratio | Missing confirmations | 5s window | Fusion (downweight blackbox) | Thấp |
| `ack_flood_score` | count/s | Unnecessary ack packets | 1s window | Whitebox (flag suppression detection) | Thấp |

---

## Nhóm 2: Movement & Prediction

| Feature | Unit | Nguồn | Window | Consumer | Chi phí |
|---|---|---|---|---|---|
| `horizontal_speed` | blocks/tick | Position delta | Per-tick | Whitebox (Speed) | Thấp |
| `vertical_velocity` | blocks/tick | Y position delta | Per-tick | Whitebox (Fly, NoFall) | Thấp |
| `prediction_offset_h` | blocks | Predicted X/Z vs actual | Per-tick | Whitebox core | Cao |
| `prediction_offset_v` | blocks | Predicted Y vs actual | Per-tick | Whitebox core | Cao |
| `on_ground_transitions` | count | onGround state changes | 10-tick window | Whitebox (NoFall, Criticals) | Thấp |
| `collision_state` | enum | Block collision context | Per-tick | Whitebox (Phase, Speed) | Trung bình |
| `fluid_state` | enum | Water/lava depth context | Per-tick | Whitebox | Trung bình |
| `setback_proximity` | ticks ago | Last correction event | Per-tick | Fusion (recent setback context) | Thấp |
| `fall_distance_accumulated` | blocks | Y fall without ground contact | Per-tick | Whitebox (NoFall, Criticals, Mace) | Thấp |
| `wind_charge_push_context` | boolean+vector | Recent wind charge impact | 10-tick window | Whitebox (Speed, Fly) | Thấp |
| `vehicle_state` | enum | Boat/minecart/horse/... | Per-tick | Whitebox (movement context) | Thấp |
| `crawl_state` | boolean | Crawling hitbox active | Per-tick | Whitebox (Phase, Hop) | Thấp |
| `teleport_context` | ticks ago | Recent server teleport | Per-tick | Whitebox (Blink, Prediction) | Thấp |

---

## Nhóm 3: Combat Geometry

| Feature | Unit | Nguồn | Window | Consumer | Chi phí |
|---|---|---|---|---|---|
| `hit_distance` | blocks | Attack geometry raytrace | Per-attack | Whitebox (Reach) | Cao |
| `target_relative_angle` | degrees | Attack vector vs look | Per-attack | Whitebox (KillAura rotation) | Trung bình |
| `line_of_sight_valid` | boolean | Raytrace result | Per-attack | Whitebox (Hitbox, CrystalAura) | Cao |
| `hitbox_edge_ratio` | 0-1 | % hits near AABB edge | Combat window 5s | Blackbox | Trung bình |
| `attack_while_turning` | boolean | Yaw delta > threshold at attack | Per-attack | Blackbox | Thấp |
| `attack_aim_delta` | degrees | Angle diff look→target at hit | Per-attack | Blackbox | Thấp |
| `multi_target_tick` | count | Entities attacked same tick | Per-tick | Whitebox (KillAura) | Thấp |
| `crystal_place_break_delta` | ms | Crystal place to interact time | Per-crystal | Whitebox (CrystalAura) | Thấp |
| `mace_fall_distance_pre_attack` | blocks | Y distance fallen before smash | Per-attack | Whitebox (Mace) | Thấp |

---

## Nhóm 4: Rotation & Aim

| Feature | Unit | Nguồn | Window | Consumer | Chi phí |
|---|---|---|---|---|---|
| `yaw_delta` | degrees/tick | Look packet yaw diff | Per-tick | Blackbox | Thấp |
| `pitch_delta` | degrees/tick | Look packet pitch diff | Per-tick | Blackbox | Thấp |
| `yaw_acceleration` | degrees/tick² | Yaw delta rate of change | Per-tick | Blackbox | Thấp |
| `pitch_acceleration` | degrees/tick² | Pitch delta rate of change | Per-tick | Blackbox | Thấp |
| `yaw_jerk` | degrees/tick³ | Yaw acc rate of change | Per-tick | Blackbox | Thấp |
| `rotation_jerk_distribution` | histogram | Distribution shape of jerk | 5s window | Blackbox (AimAssist model) | Trung bình |
| `snap_frequency` | count/s | Rotation delta > snap_threshold | 5s window | Blackbox | Thấp |
| `anchor_return_score` | 0-1 | Rotation returns to fixed angle | Combat window | Blackbox | Trung bình |
| `rotation_to_hit_correlation` | 0-1 | Attack sync với rotation settle | Per-attack | Blackbox | Trung bình |
| `target_lock_duration` | ticks | Consecutive ticks within 5° of target | Per-combat | Blackbox | Thấp |
| `human_rotation_deviation_score` | z-score | So sánh với human distribution | Combat window | Blackbox (GhostClient) | Cao |

---

## Nhóm 5: Click Behavior

| Feature | Unit | Nguồn | Window | Consumer | Chi phí |
|---|---|---|---|---|---|
| `cps_current` | clicks/s | Attack packet rate | 1s window | Hybrid | Thấp |
| `cps_max_burst` | clicks/s | Peak CPS in 200ms | 5s window | Hybrid | Thấp |
| `click_interval_mean` | ms | Average time between attacks | 5s window | Blackbox | Thấp |
| `click_interval_stddev` | ms | Std deviation of intervals | 5s window | Blackbox (AutoClicker) | Thấp |
| `click_interval_entropy` | bits | Entropy of interval distribution | 10s window | Blackbox | Trung bình |
| `burst_click_score` | 0-1 | Ratio of burst vs sustained | 5s window | Blackbox | Thấp |
| `silence_gap_ratio` | 0-1 | Gaps > 500ms in active combat | Session | Blackbox | Thấp |
| `attack_cooldown_respect` | boolean | Attack sent before cooldown ready | Per-attack | Whitebox | Thấp |
| `click_pattern_repeat_score` | 0-1 | Detected repeating interval cycle | 30s window | Blackbox (scripting detection) | Cao |

---

## Nhóm 6: Inventory & Interaction

| Feature | Unit | Nguồn | Window | Consumer | Chi phí |
|---|---|---|---|---|---|
| `slot_switch_interval` | ms | HeldItem change delta-t | Per-switch | Hybrid | Thấp |
| `totem_swap_reaction_time` | ms | Near-death to totem swap | Per-event | Hybrid | Thấp |
| `inventory_open_move_state` | boolean | Movement during GUI open | Per-tick | Whitebox | Thấp |
| `place_rotation_delay` | ms | Rotation stable before place | Per-placement | Whitebox | Thấp |
| `break_after_look_delay` | ms | Look stable before break | Per-break | Whitebox | Thấp |
| `container_transaction_combat` | boolean | Container click during combat | Per-event | Hybrid | Thấp |

---

## Nhóm 7: Session Profile

| Feature | Unit | Nguồn | Window | Consumer | Chi phí |
|---|---|---|---|---|---|
| `session_risk_accumulation` | score | Weighted fusion output sum | Session | Fusion | Thấp |
| `target_repeat_ratio` | 0-1 | % attacks on same target | 60s window | Blackbox | Thấp |
| `category_flag_mix` | vector | Combination of check types flagged | Session | Fusion | Thấp |
| `burst_flag_density` | count/min | Flag events per minute | 5min window | Fusion | Thấp |
| `suspicious_streak_length` | ticks | Consecutive suspicious ticks | Per-session | Fusion | Thấp |
| `no_bad_tick_score` | 0-1 | Ratio of "perfect" ticks (no miss, no hesitation) | Combat window | Blackbox (GhostClient) | Trung bình |
| `staff_reviewed_history` | label | Prior ban, false positive, clean verdict | Persistent | Fusion | Thấp |

---

## Cửa Sổ Sampling

| Tên | Độ dài | Mục đích |
|---|---|---|
| per-packet | 1 packet | Kiểm tra đơn lẻ |
| tick | 50ms | Whitebox core |
| micro | 200ms–2s | Burst detection, combat window entry |
| combat | 3–10s | Aim, click, combat geometry |
| session-short | 1–5min | Pattern consistency |
| session-long | 10–60min | Slow drift, ghost profile |

---

## Ràng buộc

- Mỗi feature phải có consumer cụ thể. Không thu thập nếu không dùng.
- Feature dùng trong Whitebox phải sẵn sàng ở hot path (không block).
- Feature dùng trong Blackbox có thể tính async với window delay tối đa 2s.
- Feature dùng trong Fusion phải có fallback nếu không có.
- Feature tracking Wind Charge, Mace là **bắt buộc** từ 1.21.x trở đi.
