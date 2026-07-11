# Minecraft 1.9+ Anticheat Systems — Comprehensive Technical Reference

> **Disclaimer:** This document is for educational and security research purposes only. Understanding anticheat mechanisms helps server administrators protect their communities and helps security researchers identify vulnerabilities in detection systems.

---

## Table of Contents

1. [Minecraft 1.9+ Combat Changes](#1-minecraft-19-combat-changes)
   - [1.1 Attack Cooldown Mechanic](#11-attack-cooldown-mechanic)
   - [1.2 Shields](#12-shields)
   - [1.3 Dual Wielding](#13-dual-wielding)
   - [1.4 New Movement Mechanics](#14-new-movement-mechanics)
   - [1.5 Impact on Anticheat Detection](#15-impact-on-anticheat-detection)
2. [Anticheat Pipeline & Check Lifecycle Flow](#2-anticheat-pipeline--check-lifecycle-flow)
   - [2.1 Overall Detection Pipeline](#21-overall-detection-pipeline)
   - [2.2 Check Execution Order](#22-check-execution-order-grimac-specific)
   - [2.3 Prediction Engine Pipeline](#23-prediction-engine-pipeline-deep-dive)
   - [2.4 Violation Handling Flow](#24-violation-handling-flow)
3. [Common Cheat Types in 1.9+](#3-common-cheat-types-in-19)
   - [3.1 KillAura / Aimbot](#31-killaura--aimbot)
   - [3.2 Reach](#32-reach)
   - [3.3 Velocity / Anti-Knockback](#33-velocity--anti-knockback)
   - [3.4 Flight](#34-flight)
   - [3.5 Speed](#35-speed)
   - [3.6 NoSlowdown](#36-noslowdown)
   - [3.7 Scaffold](#37-scaffold)
   - [3.8 Criticals](#38-criticals)
   - [3.9 AutoClicker](#39-autoclicker)
   - [3.10 AntiDebuff](#310-antidebuff)
   - [3.11 Inventory Hacks](#311-inventory-hacks)
   - [3.12 AutoTotem](#312-autototem)
   - [3.13 AutoCrystal](#313-autocrystal)
   - [3.14 AnchorAura](#314-anchoraura)
   - [3.15 Phase / NoClip](#315-phase--noclip)
   - [3.16 Jesus / WaterWalk](#316-jesus--waterwalk)
   - [3.17 Blink / Fakelag](#317-blink--fakelag)
   - [3.18 Spider](#318-spider)
   - [3.19 InventoryMove / InvWalk](#319-inventorymove--invwalk)
   - [3.20 AntiHunger](#320-antihunger)
   - [3.21 FastBow / FastUse / FastEat](#321-fastbow--fastuse--fasteat)
   - [3.22 NoWeb](#322-noweb)
   - [3.23 Strafe](#323-strafe)
   - [3.24 GhostHand](#324-ghosthand)
   - [3.25 AutoArmor / AutoTool / ChestStealer](#325-autoarmor--autotool--cheststealer)
   - [3.26 FreeCam / ESP / Tracers](#326-freecam--esp--tracers)
   - [3.27 GodMode / AntiVoid / AntiCactus](#327-godmode--antivoid--anticactus)
   - [3.28 NoPush / SafeWalk / NoRotate](#328-nopush--safewalk--norotate)
   - [3.29 Derp / Headless](#329-derp--headless)
   - [3.30 EntityDesync / BoatFly / HorseFly](#330-entitydesync--boatfly--horsefly)
   - [3.31 Baritone](#331-baritone)
   - [3.32 Crash Exploits](#332-crash-exploits)
   - [3.33 Illegal Items](#333-illegal-items)
   - [3.34 Sprint Direction Validation](#334-sprint-direction-validation)
4. [Anticheat Detection Methods](#4-anticheat-detection-methods)
   - [4.1 KillAura Detection](#41-killaura-detection)
   - [4.2 Reach Detection](#42-reach-detection)
   - [4.3 Velocity Detection](#43-velocity-detection)
   - [4.4 Flight Detection](#44-flight-detection)
   - [4.5 Speed Detection](#45-speed-detection)
   - [4.6 NoSlowdown Detection](#46-noslowdown-detection)
   - [4.7 Scaffold Detection](#47-scaffold-detection)
   - [4.8 Criticals Detection](#48-criticals-detection)
   - [4.9 AutoClicker Detection](#49-autoclicker-detection)
   - [4.10 Timer Detection](#410-timer-detection)
5. [Popular Anticheats in 1.9+](#5-popular-anticheats-in-19)
   - [5.1 GrimAC](#51-grimac)
   - [5.2 Vulcan](#52-vulcan)
   - [5.3 Matrix](#53-matrix)
   - [5.4 Spartan](#54-spartan)
   - [5.5 NoCheatPlus (NCP)](#55-nocheatplus-ncp)
   - [5.6 AAC (Advanced AntiCheat)](#56-aac-advanced-anticheat)
   - [5.7 Comparison: 1.8 vs 1.9+ Anticheats](#57-comparison-18-vs-19-anticheats)
6. [Anti-Bypass Techniques](#6-anti-bypass-techniques)
   - [6.1 Transaction-Based Checks](#61-transaction-based-checks)
   - [6.2 Motion Prediction](#62-motion-prediction)
   - [6.3 Timer Checks](#63-timer-checks)
   - [6.4 Ground Checks](#64-ground-checks)
   - [6.5 Rotation Smoothing Detection](#65-rotation-smoothing-detection)
   - [6.6 Packet Validation](#66-packet-validation)
   - [6.7 Lag Compensation](#67-lag-compensation)
7. [Technical Implementation Details](#7-technical-implementation-details)
   - [7.1 Packet Analysis Server-Side](#71-packet-analysis-server-side)
   - [7.2 Movement Simulation and Prediction](#72-movement-simulation-and-prediction)
   - [7.3 Attack Cooldown Validation](#73-attack-cooldown-validation)
   - [7.4 Shield Interaction Checks](#74-shield-interaction-checks)
   - [7.5 Elytra / Trident Detection](#75-elytra--trident-detection)
   - [7.6 Swimming and Crawling Checks](#76-swimming-and-crawling-checks)

---

## 1. Minecraft 1.9+ Combat Changes

### 1.1 Attack Cooldown Mechanic

Minecraft 1.9 (Combat Update) fundamentally rewrote the PvP system by introducing an **attack cooldown** (also called the "weapon charge" or "tick delay" mechanic). Before 1.9, attacking was instantaneous with no delay between swings. After 1.9:

- Each weapon has a base attack speed (e.g., swords: 1.6, axes: 1.0, pickaxes: 1.2)
- Attack speed is defined as an **attribute** (`generic.attack_speed`) with a default value of 4.0 attacks per second
- After each attack, a cooldown bar appears and the player must wait for it to refill
- Attacking before the cooldown ends deals reduced damage (scaled by `(0.2 * cooldown_progress + 0.2)^2`)

**Server-side implementation:**

```java
// Vanilla Minecraft attack cooldown implementation (simplified)
// Attack strength is calculated as:
float attackStrength = (float) Math.min(1.0, 
    (player.ticksSinceLastSwing + 0.5) / getAttackSpeedTicks(player));

// Damage multiplier:
float damageMultiplier = (0.2f * attackStrength + 0.2f) * (0.2f * attackStrength + 0.2f);
```

The attack speed attribute is converted to ticks: `attackSpeedTicks = (int) Math.round(20.0 / attackSpeed)`. A sword with 1.6 attack speed has a cooldown of approximately 12.5 ticks (625ms).

**Anticheat implications:** Anticheats must validate that players wait for the cooldown before dealing full damage. Cheat clients can spoof cooldown state or ignore it server-side. The server validates via:
1. Tracking `ticksSinceLastAttack` client-side vs server-observed
2. Monitoring the `ATTACK` packet rate compared to expected cooldown
3. Cross-referencing damage events with swing timing

### 1.2 Shields

Shields were introduced in 1.9 as a new defensive tool:

- Shields block up to 100% of incoming damage when raised (right-click)
- Blocking reduces velocity from attacks by ~50%
- Shields have a cooldown after being broken by an axe attack (5 seconds in 1.9)
- Players cannot attack while the shield is raised
- Shields can be disabled by axes with the `disable_shield` enchantment or as a base mechanic
- In 1.9+, blocking with a sword was replaced entirely by shields

**Server-side mechanics:**
- Shield state is tracked via entity metadata (flags for blocking status)
- The `USE_ITEM` packet indicates the shield is raised
- The server validates blocking via `EntityMetadata` updates and packet timing

**Anticheat implications:**
- Shield-toggle cheats can bypass block delay
- AutoShield mods can raise the shield with perfect timing (flagged via packet timing analysis)
- Shield interaction checks must validate cooldown periods after axe attacks
- Players cheating with shields might attack while blocking (impossible in vanilla)

### 1.3 Dual Wielding

1.9 introduced the **off-hand slot**, allowing players to hold items in both hands:

- Main hand: weapon/tool
- Off hand: shield, totem, food, blocks, or any item
- Hotkey press `F` (default) swaps items between hands
- Attack speed is affected by the item in the main hand only
- Off-hand items can have unique effects (e.g., totems prevent death, shields block)

**Anticheat implications:**
- Silent item switching (hotbar to offhand) is detectable via packet analysis
- Totem manipulation (auto-totem) switches items faster than humanly possible
- Packet order validation is required for off-hand interactions
- Dual-wielding changes attack reach and interaction range calculations

### 1.4 New Movement Mechanics

**Elytra (1.9+):**
- Chestplate slot item that allows gliding when falling
- Activated by double-jumping (pressing jump mid-air)
- Speed is determined by pitch angle (looking down increases speed, up slows)
- Firework rockets can boost elytra speed
- Elytra flight has strict horizontal/vertical velocity limits:
  - Max horizontal speed with rocket boost: ~1.33 blocks/tick (26.6 m/s)
  - Max vertical speed with rocket boost: ~0.6 blocks/tick upward, 1.0 downward
  - Gliding without rockets: roughly 0.7 blocks/tick horizontal when pitched at 45 degrees

**Tridents (1.13+):**
- Riptide enchantment allows launching through water/rain
- Channeling strikes lightning during thunderstorms
- Loyalty returns the trident after throwing
- Riptide launches the player ~15 blocks with a velocity of ~1.5 blocks/tick along looking direction

**Swimming (1.13+):**
- Replaced old "swimming" with a new animation and movement
- Players can swim through 1-block gaps using the `swimming` pose
- Swim speed is faster than walking in water (adds 0.03 friction modifier)
- Sprint-swimming (with 1.13+ depth strider) significantly increases speed

**Crawling (1.14+):**
- Players can crawl through 1-block tall gaps by holding sneak while in a 1.5-block space
- Crawling pose has a 0.6 block height hitbox
- Crawling speed is the same as sneaking speed (30% of walk speed)

**Anticheat implications:**
- Elytra must be properly validated with pitch-dependent speed limits
- Riptide trident velocity must match expected launch vectors
- Swimming collision boxes change based on pose
- Crawling requires specific block-above conditions
- All new poses require server-side validation of client-submitted pose metadata

### 1.5 Impact on Anticheat Detection

The 1.9 update introduced several challenges for anticheat development:

| Aspect | Impact |
|--------|--------|
| **Attack cooldown** | Anticheats must track cooldown timing and validate packet timing against expected damage modifiers |
| **Shields** | New vector for bypass — autoblockers and shield-toggle cheats require packet validation |
| **Off-hand** | Dual interaction checks needed; silent switch bypasses require timing analysis |
| **Elytra** | Completely new movement profile — cannot use old flight detection logic |
| **Trident riptide** | Legitimate high-speed movement that mimics speed/flight cheats |
| **Swimming** | Changes player bounding box and movement characteristics |
| **Crawling** | Complex ground-state interaction — players can be "on ground" in tight spaces |
| **Version differences** | Anticheats supporting 1.7-1.21 must handle drastically different movement logic per version |

---

## 2. Anticheat Pipeline & Check Lifecycle Flow

Modern anticheats (GrimAC, Vulcan) use a **multi-phase pipeline** that processes every packet through ordered stages of validation. This section documents the complete lifecycle flow.

### 2.1 Overall Detection Pipeline

```
Client → Network I/O
               ↓
    ┌─────────────────────────────────────────────┐
    │  1. PRE-VIA CHECKS                          │
    │  (trước khi ViaVersion transform packet)    │
    │  • Camera entity compensation               │
    │  • BadPackets A/B/C (basic validation)      │
    │  • PacketOrder B/C/D (ordering)             │
    │  • SelfInteract                             │
    │  • MultiActions A/E                         │
    │  • Vehicle A/B                              │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  2. PRE-PREDICTION CHECKS                   │
    │  (trước khi movement prediction)            │
    │  • Timer / TickTimer / TimerLimit           │
    │  • WatchdogBotCheck                         │
    │  • SuspicionCheck                           │
    │  • AutoCrystal / AnchorAura                 │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  3. POSITION UPDATE + PREDICTION ENGINE     │
    │  • PredictionRunner → MovementCheckRunner   │
    │  • CompensatedCooldown                      │
    │  • PlayerBaseTick (gravity, friction)       │
    │  • PredictionEngine.guessBestMovement()     │
    │  • MovementTicker (player/vehicle)          │
    │  • Collision simulation                     │
    │  • Offset calculation                       │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  4. POST-PREDICTION CHECKS                  │
    │  (sau khi prediction hoàn tất)              │
    │  • OffsetHandler (Simulation)               │
    │  • GroundSpoof / NoFall                     │
    │  • Phase (NoClip detection)                 │
    │  • NoSlow                                   │
    │  • KnockbackHandler / ExplosionHandler      │
    │  • NegativeTimer                            │
    │  • PacketOrder A/E                          │
    │  • MultiInteract A/B                        │
    │  • Elytra C/D/F/J                           │
    │  • GhostBlockDetector                       │
    │  • Post                                     │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  5. ROTATION CHECKS                         │
    │  • AimProcessor                             │
    │  • AimModulo360                             │
    │  • AimDuplicateLook                         │
    │  • AimAssist                                │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  6. VEHICLE CHECKS                          │
    │  • VehiclePredictionRunner                  │
    │  • VehicleA-F (rideable validation)         │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  7. BLOCK PLACE CHECKS                      │
    │  • InvalidPlace A/B                         │
    │  • AirLiquidPlace                           │
    │  • RotationPlace                            │
    │  • (FarPlace, MultiPlace, PositionPlace)    │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  8. BLOCK BREAK CHECKS                      │
    │  • FastBreak / WrongBreak                   │
    │  • RotationBreak / PositionBreakA           │
    │  • (MultiBreak, NoSwingBreak, FarBreak)     │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  9. PACKET CHECKS (general)                 │
    │  • Reach / MaceCheck                        │
    │  • AutoTotem                                │
    │  • ClientBrand detection                    │
    │  • BadPackets D/E +                        │
    │  • AttackCooldownHandler                    │
    │  • PacketEntityReplication                  │
    │  • SetbackBlocker (must be last)            │
    └─────────────────────────────────────────────┘
               ↓
    ┌─────────────────────────────────────────────┐
    │  10. VERDICT & PUNISHMENT                   │
    │  • Violation accumulation (VL)              │
    │  • Setback (teleport về safe position)      │
    │  • Packet cancellation                      │
    │  • Alert / Kick / Ban                       │
    │  • Verbose logging                          │
    └─────────────────────────────────────────────┘
```

### 2.2 Check Execution Order (GrimAC Specific)

The `CheckManager` registers checks into **9 ordered maps**, each executed at a specific phase of the packet lifecycle:

| Phase Map | When It Runs | Count (enabled) |
|-----------|-------------|-----------------|
| `preViaPacketChecks` | Before ViaVersion transforms | ~12 |
| `prePredictionChecks` | Before prediction engine | ~7 |
| `positionChecks` | On position update | 2 |
| `rotationChecks` | On rotation update | 4 |
| `vehicleChecks` | On vehicle position update | 1 |
| `postPredictionChecks` | After prediction completes | ~20 |
| `blockPlaceChecks` | On block placement | 4 |
| `blockBreakChecks` | On block breaking | 4 |
| `packetChecks` | General packet receive/send | ~16 |
| `noneModules` | No listeners, invoked by code | 4 |

**Check type interface hierarchy:**

```
AbstractCheck (interface)
├── PacketCheck          — onPacketReceive / onPacketSend
├── PositionCheck        — onPositionUpdate
├── RotationCheck        — process(RotationUpdate)
├── VehicleCheck         — process(VehiclePositionUpdate)
├── PostPredictionCheck  — onPredictionComplete + PacketCheck
├── BlockBreakCheck      — onBlockBreak + PostPredictionCheck
└── BlockPlaceCheck      — onBlockPlace + RotationCheck + BlockBreakCheck (class)
```

### 2.3 Prediction Engine Pipeline (Deep Dive)

The **prediction engine** is the core of GrimAC. It runs every movement tick:

```
PositionUpdate packet arrives
    ↓
MovementCheckRunner.processAndCheckMovementPacket()
    ↓
├── 1. PlayerBaseTick.doBaseTick()
│     • Apply potion effects (levitation, slow falling)
│     • Apply status effects (blindness, hunger)
│     • Update fall distance
│     • Handle lava/water/fire damage
│
├── 2. PlayerBaseTick.livingEntityAIStep()
│     • Apply gravity: velocity.y -= 0.08
│     • Apply drag: velocity *= 0.98
│     • Apply friction: velocity *= blockFriction (0.6 ground, 0.91 air)
│     • Clamp to terminal velocity
│
├── 3. MovementTickerPlayer.tick() or MovementTicker*.tick()
│     • Handle swimming/crawling pose transitions
│     • Handle elytra flight mechanics
│     • Handle ladder/vine climbing
│     • Handle cobweb slowdown
│     • Handle slime/honey block bouncing
│     • Handle piston push
│     • Handle fluid movement (water/lava)
│
├── 4. PredictionEngine.guessBestMovement()
│     • Try ALL valid input combinations:
│       - forward: -0.98, 0, 0.98
│       - strafe: -0.98, 0, 0.98
│       - jumping: true/false
│       - sneaking: true/false
│       - sprinting: true/false
│     • For each combo → compute expected velocity
│     • Compare to actual velocity
│     • Return best match + offset
│
├── 5. Collision seeking + 0.03 handling
│     • Step-up (0.6 block auto-step)
│     • Wall collision resolution
│     • PointThreeEstimator (Mojang 0.03 desync)
│     • UncertaintyHandler (pistons, vehicle dismount)
│
└── 6. Return PredictionComplete (offset, checked)
    ↓
PostPredictionChecks run:
    • OffsetHandler: accumulate advantage from offset
    • GroundSpoof: validate onGround vs collision
    • Phase: check block intersection
    • NoSlow: check item-use slowdown
    • KnockbackHandler: check velocity response
```

**Six prediction engine variants (switched automatically per player state):**

| Engine | State | Key Differences |
|--------|-------|----------------|
| `PredictionEngineNormal` | Ground/air movement | Standard friction (0.6/0.91), gravity 0.08 |
| `PredictionEngineWater` | 1.13+ swimming | Fluid drag, swim speed modifier (+0.03) |
| `PredictionEngineWaterLegacy` | Pre-1.13 swimming | Old water movement model |
| `PredictionEngineLava` | Lava swimming | Lava drag + slower movement |
| `PredictionEngineElytra` | Elytra gliding | Pitch-dependent speed, rocket boost |
| `PredictionEngineBoat` | Boat riding | Boat-specific friction + rowing |

**Seven rideable prediction engines:** Boat, HappyGhast, NautilusWater, RideableNormal, RideableWater, RideableWaterLegacy, RideableLava

**Ten movement ticker types:** Player, LivingVehicle, Rideable, Horse, Camel, Pig, Strider, Nautilus, HappyGhast

### 2.4 Violation Handling Flow

Each check follows a standard violation lifecycle:

```
Flag event (prediction offset > threshold, etc.)
    ↓
violations += increment (accumulated)
    ↓
├── if violations ≥ setbackVL:
│     • SetbackTeleportUtil.executeViolationSetback()
│     • Player teleported to last safe position
│     • Packets may be cancelled
│
├── if violations ≥ alertVL:
│     • Alert sent to staff (via plugin channel)
│     • Verbose logging
│
├── Every clean tick: violations *= (1 - decay)
│     (decay = 0.005 to 0.5, configurable per check)
│
└── Reset conditions:
      • Player teleported (legitimate)
      • TPS drop below threshold
      • Prediction offset unreliable (> 0.01)
```

**Setback types:**
- **Position setback:** Teleport to last safe position (used for movement cheats)
- **Packet cancellation:** Drop the offending packet before it reaches game logic
- **Block modification:** Revert block changes (scaffold, nuker)

---

## 3. Common Cheat Types in 1.9+

### 3.1 KillAura / Aimbot

**KillAura** (also called ForceField or AutoAttack) automatically attacks entities within range. In 1.9+, KillAura must also handle attack cooldown timing.

**How it works post-1.9:**
- Sends `ATTACK` packets to nearby entities at each attack tick
- Must account for attack cooldown (otherwise deals minimal damage)
- Can filter by entity type (players, mobs, etc.), team status, invisibility
- Rotation smoothing adjusts aim angles toward targets
- In 1.9+, good KillAuras spoof the attack cooldown by:
  - Spreading attacks over the correct tick interval (10-12 ticks for swords)
  - Varying timing slightly to appear human (not exactly every 500ms)
  - Not attacking during shield block or eating

**Aimbot** silently adjusts crosshair rotation toward targets:
- Silent aim: adjusts server-side rotation without changing visible client rotation
- Smooth aim: gradually moves crosshair to target with configurable speed
- Lock aim: instantly snaps to target (highly detectable)
- In 1.9+, aimbots must account for the new hitbox sizes and attack range

### 3.2 Reach

Reach allows attacking entities from beyond the vanilla attack range.

**Vanilla reach:**
- Survival mode: 3.0 blocks (from eye position to target)
- Creative mode: 4.5 blocks (from eye position to target)
- Some entities have extended reach (e.g., Enderman: 3.0, but hitbox extends further)
- Weapon reach bonuses from attributes (rare in vanilla)

**Reach cheats:**
- Client-side reach: modifies `EntityRenderer.getMouseOver()` distance
- Packet-level reach: modifies the entity ID in attack packets (but server validates distance)
- Backtrack reach: attacks exploit timing discrepancies (client position at time of attack vs current position)

### 3.3 Velocity / Anti-Knockback

Velocity reduction modifies how the player responds to knockback:

- **Anti-Knockback:** Sets horizontal velocity to zero or reduces it
- **Vertical velocity reduction:** Reduces upward knockback (harder to detect)
- **Motion prediction bypass:** Modifies velocity only when the anticheat is not looking

**1.9+ specific:**
- Shield blocking reduces knockback by ~50% (legitimate)
- Velocity cheats set knockback reduction to 0-100%
- Horizontal velocity is the most common target
- Vertical velocity reduction helps with combo chains

### 3.4 Flight

Flight allows players to move freely in the air as if in creative mode.

**Types of flight cheats:**
- **Creative flight:** Copies creative-mode flight mechanics (survival mode)
- **Glide:** Reduces downward velocity while falling
- **High jump:** Increased upward velocity
- **Jetpack:** Custom upward velocity (often bound to jump key)
- **Elytra fly:** Exploits elytra mechanics for unlimited flight without rockets
- **Packet fly (spoofflight):** Sends modified movement packets with Y position unchanged

**1.9+ complications:**
- Elytra naturally allows flight-like movement
- Riptide tridents provide legitimate rocket-like boosts
- Levitation potions and Shulker Levitation effect
- Phantoms (1.13+) can boost players upward
- Wind charges (1.21+) add new vertical movement

### 3.5 Speed

Speed cheats increase movement speed beyond vanilla limits.

**Types:**
- **Ground speed:** Overrides `walkSpeed` attribute or movement factor
- **Ice speed:** Exploits ice friction properties 
- **B-hop:** Strafe-jumping to accelerate (legitimate in 1.8, changed in 1.9+)
- **Timer speed:** Speeds up game tick processing
- **Strafe speed:** Modifies friction during directional changes

**1.9+ differences:**
- 1.9+ reduced b-hop acceleration (changed friction model)
- 1.13+ swimming adds new speed vectors
- Soul speed enchantment (1.16+) modifies speed on soul sand/soil
- Speed is calculated from `deltaX^2 + deltaZ^2` per movement tick

### 3.6 NoSlowdown

NoSlowdown removes speed reduction when:
- Using items (eating, drinking, blocking with shield)
- Walking through cobwebs
- Walking through berry bushes (1.17+)
- Walking through powder snow (1.17+)
- Sprinting while using items (impossible in vanilla)
- Walking through water/lava (NoSwimSlowdown variant)

**1.9+ specific:**
- Shield blocking normally reduces speed to 50% (sneaking speed)
- Eating/drinking reduces speed to sneaking speed
- NoSlowdown bypasses these checks, maintaining sprint speed
- Can also affect `AI_OBSTRUCTION` collision checks

### 3.7 Scaffold

Scaffold automatically places blocks beneath the player while walking.

**How it works:**
- Automatically selects blocks from hotbar
- Places blocks at the player's feet or slightly below
- Swing arm continuously with each placement
- Some modules rotate the player's head toward the placement target (highly visible)

**1.9+ specific:**
- Dual-wielding scaffold places with off-hand while main hand has blocks
- Scaffold interacts with the new block placement timing
- Elytra scaffold places while gliding (impossible in vanilla)
- Tower scaffold jumps and places blocks simultaneously

### 3.8 Criticals

Criticals force every attack to be a "critical hit" (jump attack crit):

**Mechanics:**
- Critical hits occur when: player is falling, not on ground, not in water, not on ladder, not riding entity
- Criticals cheats can spoof these conditions
- Mini-jump criticals: very small jump that triggers crit without noticeable movement
- Ground-spoof criticals: sends `onGround=false` for attack packets even when on ground

**1.9+ specific:**
- Attack cooldown at 100% is required for critical hits
- Criticals cheat must also manage cooldown timing
- Shield blocking prevents criticals

### 3.9 AutoClicker

AutoClicker automatically sends left-click (attack) or right-click packets at a set rate.

**Post-1.9 behavior:**
- Must respect attack cooldown for optimal damage
- Can be set to specific CPS (clicks per second)
- Human CPS ranges: 5-12 CPS (average 6-9)
- Cheat CPS ranges: 8-20+ CPS (some go up to 100+)
- Autoclickers vary click patterns to appear human (randomized delays, jitter)
- Some autoclickers simulate mouse button press/release events

### 3.10 AntiDebuff

AntiDebuff removes negative potion effects:

- Sends packets to clear potion effects immediately
- Removes blindness, slowness, poison, weakness, etc.
- Can selectively remove effects while keeping buffs
- Server-side validation checks for suspicious effect removal timing
- Some implementations "eat" the potion by sending consume packets rapidly

### 3.11 Inventory Hacks

Inventory hacks manipulate the inventory GUI:

- **Steal:** Automatically takes items from chests
- **Auto-armor:** Automatically equips best armor from inventory
- **Auto-totem:** Automatically swaps totem to off-hand when breaking
- **ChestStealer:** Rapidly takes all items from a chest
- **InvWalk:** Allows walking while inventory is open

**1.9+ specific:**
- Off-hand management (auto-totem is very common in 1.9+ PvP)
- Shield-equip automation
- Totem-pop detection (totem activates → auto-totem replaces it in <50ms)

### 3.12 AutoTotem

AutoTotem tự động swap Totem of Undying vào off-hand khi nhận damage hoặc trước combat.

**Cách hoạt động:**
- **Reactive swap:** Khi totem pop (kích hoạt) → auto swap totem mới vào off-hand
- **Proactive swap:** Swap totem trước khi nhận damage (predict damage)
- **Silent swap:** Swap qua inventory mà không mở GUI (packet spoof)

**Detection layers (GrimAC AutoTotem):**

| Layer | Phương pháp | Threshold |
|-------|------------|-----------|
| 1. Proactive | Swap totem rồi nhận damage lớn trong < 3s | proactiveWindowMs = 3000ms |
| 2. Reaction-time | Swap sau damage < 300ms (có ping compensation) | reactionMaxMs = 300ms |
| 3. Mode-deviation | Interval swap rơi vào 1-2 giá trị > 60% | modeFreqThreshold = 0.6 |
| 4. Count backstop | > 8 swap trong combat window 30s | countBackstopLimit = 8 |
| 5. Stddev | Độ lệch chuẩn interval < 30ms | stddevMaxMs = 30ms |
| 6. Outlier | > 3 swap < 50ms trong 5 lần gần nhất | outlierMaxMs = 50ms |
| 7. Sequence | Interval đều trong ±20ms > 8 swap | sequenceToleranceMs = 20ms |

```java
// GrimAC AutoTotem proactive buffer logic
private int proactiveBuffer = 0;
if (now - lastProactiveSwapTime < proactiveWindowMs) {
    // Swap xong rồi nhận damage quá nhanh
    if (++proactiveBuffer >= 2) {
        flag("proactive swap → damage in " + (now - lastProactiveSwapTime) + "ms");
    }
}
```

**Grim source:** `checks/impl/totem/AutoTotem.java` | **TotemGuard:** `totemguard/` (8 checks A-H)

### 3.13 AutoCrystal

AutoCrystal tự động đặt + kích nổ End Crystal trong crystal PvP.

**Cách hoạt động:**
- Place crystal: USE_ITEM với item end crystal
- Detonate: INTERACT_ENTITY trên crystal entity
- Cycle: place → detonate → place → detonate liên tục
- Optimizer: Marlow (interval đều), G1ax (vanilla packets, bypass cooldown)

**Detection methods (GrimAC AutoCrystal):**

| Detection | Mô tả | Threshold |
|-----------|-------|-----------|
| Fast cycle | PLACE + DETONATE < 200ms | fastCycleThresholdNs = 200ms |
| Pattern stddev | Độ lệch chuẩn cycle < 10ms | stddevThresholdNs = 10ms |
| Silent place | Rotation USE_ITEM lệch > 90° so với rotation thật | silentPlaceYawThreshold = 90° |
| Silent aim | Attack crystal nhưng rotation không hướng về crystal > 120° | silentAimYawThreshold = 120° |
| Rotation snap | snap > 90° + consecutiveFast >= 5 | rotationSnapThreshold = 90° |
| Cumulative yaw (YawStep bypass) | Yaw thay đổi > 180° qua 3 cycles | cumulativeRotationThreshold = 180° |
| Inhibit (ThunderHack v4) | Place không detonate để break pattern | inhibitPlaceThreshold = 3 |

```java
// Fast cycle detection
if (detonateToPlaceNs < fastCycleThresholdNs) {
    if (++consecutiveFastCycles >= patternConsecutiveFastThreshold) {
        intervals.add(diff);
        if (intervals.size() >= minStddevSamples) {
            double stddev = calculateStddev(intervals);
            if (stddev < stddevThresholdNs) {
                flag("fast+pattern cycle diff=" + diff + "ns");
            }
        }
    }
}
```

**Grim source:** `checks/impl/combat/AutoCrystal.java` | **TruthfulAC:** `truthful_ac/checks/combat/crystal/CrystalAuraA.java`

### 3.14 AnchorAura

AnchorAura tự động charge + kích nổ Respawn Anchor.

**Cách hoạt động:**
- Charge: START_DIGGING với glowstone trong tay (đặt glowstone vào anchor)
- Detonate: INTERACT_ENTITY với tay không (kích nổ)
- AnchorAura: charge + detonate trong < 100ms (human cần 300-500ms)

```java
// GrimAC AnchorAura detection
if (diff < 100) {
    intervals.add(diff);
    if (intervals.size() >= 5) {
        double m = 0; for (long v : intervals) m += v; m /= intervals.size();
        double v = 0; for (long f : intervals) v += (f - m) * (f - m);
        if (Math.sqrt(v / intervals.size()) < 30) { // stddev < 30ms
            flag("anchor aura diff=" + diff + "ms");
        }
    }
}
```

**Grim source:** `checks/impl/combat/AnchorAura.java`

### 3.15 Phase / NoClip

Phase cho phép đi xuyên tường, sàn, trần bằng cách desync position client-server.

**Bypass techniques:**
- **Packet phase:** Gửi position sai để đi xuyên block
- **Vehicle phase:** Dùng vehicle dismount để phase
- **Piston phase:** Dùng piston push để đẩy vào block
- **1.17 dup phase:** Exploit 1.17 duplicate packet bug

**Detection (GrimAC Phase):**
- **Collision check:** So sánh old bounding box vs new bounding box → có overlap với solid block?
- **Exemptions:** Piston push (5-tick window), vehicle dismount (5-tick), 1.17 duplicate packet
- **Lag buffer:** Cho phép 2 frame desync do lag TPS
- **Offset guard:** Skip check khi prediction offset >= 0.01 (unreliable)

```java
// GrimAC Phase check logic
if (newBB.intersectsSolidBlock(world) && !oldBB.intersectsSolidBlock(world)) {
    // Player moved into solid block — possible phase
    if (predictionComplete.getOffset() < OFFSET_UNRELIABLE) {
        flagWithSetback("phase through block");
    }
}
```

**Grim source:** `checks/impl/prediction/Phase.java`, `GhostBlockDetector.java`

### 3.16 Jesus / WaterWalk

Jesus cho phép đi trên mặt nước/lava như đất thường.

**Bypass types:**
- **NCP Jesus:** onGround=true trên liquid surface, không sink
- **Matrix Jesus:** Bypass matrix bằng cách spoof pose
- **Vulcan Jesus:** Jump + không sink pattern
- **Lava Jesus:** Đi trên lava surface

**Detection:**
- Predict Y position; flag nếu không sink trong liquid
- Validate swim state (1.13+ client phải vào swimming pose)
- Kiểm tra onGround=false trên liquid với horizontal speed > 0
- Speed limit: water = 0.20, lava = 0.18 blocks/tick

```java
// PredictionEngineWater — Jesus detection
// If player is in water but not swimming (1.13+), flag
if (!player.isSwimming && player.inWater && player.getClientVersion().isNewerThanOrEquals(V_1_13)) {
    // Player walking on water without swimming pose = Jesus
    offset += 0.05; // Force higher offset
}
```

**Grim source:** `predictionengine/predictions/PredictionEngineWater.java`, `MovementCheckRunner.java`

### 3.17 Blink / Fakelag

Blink suppress movement packets → player đứng im trên client khác → sau đó teleport.

**Cách hoạt động:**
- Suppress movement packets trong N ticks
- Player "đứng im" trên màn hình người khác
- Sau N ticks, gửi toàn bộ position update cùng lúc → teleport effect
- Dùng để tránh hit (player xuất hiện ở vị trí cũ, hit miss)

**Detection (GrimAC Reach + Timer):**
```java
// GrimAC Reach blink detection
double blinkThreshold = inCombat ? 0.3 : 0.5; // Combat tightens threshold
if (positionDelta > blinkThreshold) {
    // Player teleported just before attack — possible blink
    if (player.ping < 200) { // Exempt high ping (>200ms)
        flag("blink: position delta " + positionDelta);
    }
}
```

**Grim source:** `checks/impl/combat/Reach.java` (blink detection module), `checks/impl/timer/Timer.java`

### 3.18 Spider

Spider cho phép leo tường như nhện mà không cần thang/dây leo.

**Detection:**
- Vertical movement mà không có climbable block (ladder, vine, weeping vine)
- Validate climbable collision từ prediction engine
- `handleOnClimbable()` kiểm tra block contact với climbable
- Simulation offset catch nếu di chuyển lên mà không climbable

**Grim source:** `predictionengine/predictions/PredictionEngine.java` (`handleOnClimbable()`)

### 3.19 InventoryMove / InvWalk

InvWalk cho phép di chuyển khi inventory đang mở.

**Detection (TruthfulAC InventoryA):**
```java
// TruthfulAC InventoryA check
if (player.hasOpenInventory() && System.currentTimeMillis() - lastClick < 200) {
    double maxSpeed = isOnGround ? 0.15 : 0.12;
    if (horizontalSpeed > maxSpeed) {
        flag("invwalk: speed=" + horizontalSpeed);
    }
}
```

**Grim source:** `checks/impl/multiactions/MultiActionsA-G` (multi-action validation)

### 3.20 AntiHunger

AntiHunger giảm mất hunger bằng cách spoof onGround flag.

**Detection:**
- GroundSpoof check phát hiện onGround=true khi đang airborne
- Không có AntiHunger check riêng trong Grim
- Detection qua ground spoofing side effect

### 3.21 FastBow / FastUse / FastEat

**FastBow:** Bắn cung full charge ngay lập tức (không cần draw).
**FastUse/Eat:** Dùng item/food nhanh hơn normal.

**Detection:**
- Track time giữa USE_ITEM và RELEASE_USE_ITEM
- Vanilla: food/potion = 32 ticks, bow = ~20 ticks
- FastUse: RELEASE xảy ra quá sớm
- Toggle detection (NoSlow): USE_ITEM → RELEASE → USE_ITEM nhanh bất thường

**Grim source:** `checks/impl/movement/NoSlow.java` (toggle detection)

### 3.22 NoWeb

NoWeb bỏ qua slow effect của cobweb.

**Detection (GrimAC NoSlow - web block):**
```java
// Cobweb check in NoSlow
if (isInsideWeb()) {
    if (predictionComplete.getOffset() > 0.003) {
        if (++webBuffer >= 2) {
            flagWithSetback("web offset=" + predictionComplete.getOffset());
        }
    } else {
        webBuffer = Math.max(0, webBuffer - 1);
    }
}
```

**Grim source:** `checks/impl/movement/NoSlow.java`

### 3.23 Strafe

Strafe tối ưu hóa WASD input để đạt tốc độ tối đa.

**Detection:**
- Simulation offset handler: phát hiện advantage gained từ perfect strafe
- Sustained offset monitor: detect ThunderHack NCP Speed (offset 0.004)
- Rolling 50-tick average của offset values
- Configurable max advantage ceiling

**Grim source:** `checks/impl/prediction/OffsetHandler.java`

### 3.24 GhostHand

GhostHand tương tác với block xuyên tường (open, break, place).

**Detection:**
- Raycast từ eye position đến block interaction position
- Check có solid block occlude line-of-sight không
- Validate block face reachable từ player position
- WrongBreak: kiểm tra player có thể see/reach block face không
- PositionBreakA: validate block break position

**Grim source:** `checks/impl/breaking/WrongBreak.java`, `PositionBreakA.java`, `scaffolding/RotationPlace.java`

### 3.25 AutoArmor / AutoTool / ChestStealer

**AutoArmor:** Tự động equip armor tốt nhất.
**AutoTool:** Tự động chọn tool phù hợp nhất cho block.
**ChestStealer:** Tự động lấy item từ chest.

**Detection:**
- Click window interval analysis (< 50ms → suspicious)
- Consistent pattern detection
- Packet timing + ordering validation
- MultiActions checks catch rapid-click patterns

**Note:** Không có dedicated checks trong Grim. MultiActions + PacketOrder phát hiện gián tiếp.

### 3.26 FreeCam / ESP / Tracers

**FreeCam:** Tách camera khỏi body → tương tác từ vị trí khác.
**ESP:** Hiển thị entity qua tường (client-side render only).
**Tracers:** Vẽ line đến entity (client-side render only).

**Detection:**
- **FreeCam:** Reach + AutoCrystal silent aim detection bắt gián tiếp (interaction từ vị trí sai)
- **ESP/Tracers:** KHÔNG thể detect từ server-side (pure client render)
- FreeCam detection qua raycast validation (interact từ eye position sai)

### 3.27 GodMode / AntiVoid / AntiCactus

**GodMode:** Bất tử (không nhận damage).
**AntiVoid:** Teleport lên khi rơi xuống void (Y < 0).
**AntiCactus:** Tránh damage từ cactus.

**Detection:**
- GodMode: So sánh server-calculated damage vs actual health change
- AntiVoid: Track Y position vs world min build height
- AntiCactus: Validate collision với cactus block
- PacketPlayerRespawn tracking phát hiện respawn abuse

**Grim source:** `events/packets/PacketPlayerRespawn.java`, `BadPacketsM.java`

### 3.28 NoPush / SafeWalk / NoRotate

**NoPush:** Không bị push bởi entity/fluid.
**SafeWalk:** Auto-sneak ở edge block (không fall).
**NoRotate:** Bỏ qua server-forced rotation update.

**Detection:**
- NoPush: Phase check có piston push exemption. Prediction engine handle entity pushing uncertainty
- SafeWalk: Không có dedicated check, prediction engine xử lý edge physics
- NoRotate: Rotation checks (AimModulo360, AimDuplicateLook) validate rotation patterns

### 3.29 Derp / Headless

Derp gửi rotation quái dị (pitch > 90°, yaw oscillate) để confuse đối thủ.

**Detection:**
- BadPacketsE: Impossible pitch values (beyond ±90°)
- BadPacketsA: Invalid rotation states
- AimModulo360: Modulo-360 detection
- Rapid yaw oscillation > 360°/tick → flag

**Grim source:** `checks/impl/badpackets/BadPacketsE.java`, `AimModulo360.java`

### 3.30 EntityDesync / BoatFly / HorseFly

EntityDesync khai thác desync position client-server của vehicle.

**BoatFly:** Điều khiển boat bay lên / speed cao.
**HorseFly:** Exploit horse jumping mechanic để fly.
**Vehicle exploits:** Pig, Strider, Camel variants.

**Detection (GrimAC Vehicle A-F):**

| Check | Phát hiện |
|-------|-----------|
| VehicleA | Impossible input values (forward > 0.98 or sideways > 0.98) |
| VehicleB-F | Additional vehicle movement validation |
| VehiclePredictionRunner | Prediction engine cho vehicles |
| VehicleTimer | Timer check cho vehicle movement |

```java
// VehicleA — flags impossible input values
if (Math.abs(forward) > 0.98 || Math.abs(sideways) > 0.98) {
    flag("vehicle: impossible input f=" + forward + " s=" + sideways);
}
```

**Grim source:** `checks/impl/vehicle/VehicleA-F.java`, `VehiclePredictionRunner.java`, `VehicleTimer.java`

### 3.31 Baritone

Baritone là automated pathfinding bot (không phải cheat nhưng bị cấm trên nhiều server).

**Detection (GrimAC Baritone):**
- Phát hiện qua pattern movement quá optimal
- Movement luôn đạt theoretical maximum efficiency
- Không có human-like hesitation hoặc path correction
- **Grim source:** `checks/impl/baritone/Baritone.java`

### 3.32 Crash Exploits

Các crash exploit gửi packet đặc biệt để crash server hoặc client người khác.

**GrimAC CrashA-I checks:**
- **CrashA:** Invalid book data / sign editing crash
- **CrashB:** Inventory crash exploits
- **CrashC:** Entity interaction crash
- **CrashD-F:** Various protocol-level crash exploits
- **CrashG-I:** Block/position related crash exploits

### 3.33 Illegal Items / Stackable Items

Tạo item invalid: stack > max, enchant bất thường, NBT corrupt.

**Detection:**
- ExploitA: Anvil item name length validation
- BukkitItemResetHandler: Item reset procedures
- ConsumesBlockPlace: Validate consumed items during placement

### 3.34 Sprint Direction Validation

GrimAC có 7 Sprint checks (SprintA-G) để validate sprint state:

| Check | Phát hiện |
|-------|-----------|
| SprintA | Sprint direction vs movement direction mismatch |
| SprintB | Impossible sprint activation/deactivation |
| SprintC | Sprint while using item (NoSlow variant) |
| SprintD | Sprint state desync check |
| SprintE-G | Additional sprint validation |

**Note:** Sprint checks disabled trong CheckManager hiện tại (prediction engine handles sprint).

---
## 4. Anticheat Detection Methods

### 4.1 KillAura Detection

KillAura detection uses multiple techniques:

**A. Multi-Attack Detection**
Checks if a player attacks multiple entities in a single tick:
```java
// GrimAC MultiInteractA check — detects attacking multiple entities per tick
// Key logic: track entity IDs per tick, flag if > 1 entity attacked
// Vanilla: one attack per tick maximum
if (attackedEntitiesThisTick.size() > 1) {
    flag("multi-interact: attacked " + attackedEntitiesThisTick.size() + " entities");
}
```

**B. Rotation Analysis**
Checks for suspicious rotation patterns during attacks:
- **Angle consistency:** All KillAura rotations snap to entity center with unnatural precision
- **No vertical aim variance:** Aimbot always aims at the same Y offset (e.g., body center)
- **GCD (Greatest Common Divisor) analysis:** Look for machine-precision rotation components
- **Smoothness correlation:** Lag-1 autocorrelation of yaw deltas exceeding 0.85

```java
// GrimAC AimAssist check — rotation smoothness detection
// Computes lag-1 Pearson correlation over yaw deltas
private double computeLag1Correlation() {
    // If consecutive yaw deltas are too consistent (r > 0.85), likely aim assist
    // Human aim has natural variance; aim smoothing creates linear interpolation
}
```

**C. Attack Packet Timing**
KillAura sends attack packets at consistent intervals:
- Expected attack rate: every 10-12 ticks for optimal damage
- Instant attacks upon target acquisition (no human reaction delay)
- Consistent CPS regardless of engagement distance or target movement

**D. Entity Validation**
KillAura sometimes attacks:
- Entities behind walls (no raycast check)
- Invisible entities (no visibility validation)
- Entities outside view cone (180 degree rotation limit)

### 4.2 Reach Detection

Reach detection validates the distance between attacker and target:

**A. Euclidean Distance Check**
```java
// Simplified reach check logic
double reach = Math.sqrt(dx * dx + dy * dy + dz * dz);
double maxReach = getVanillaReach(player); // 3.0 for survival, 4.5 for creative

// Add eye height offset
double eyeHeight = player.getEyeHeight(); // 1.62 for standing, varies by pose
double verticalReach = Math.abs(dy); // Must account for entity height

if (reach > maxReach + threshold) {
    flag("reach: " + reach + " blocks, max: " + maxReach);
}
```

**B. GrimAC Reach Implementation Detail:**
GrimAC's Reach check is more sophisticated. From the source code (`Reach.java`):

- Handles both `ATTACK` and `INTERACT_ENTITY` packets
- Supports entities with custom sizes (ender dragon parts, boats, etc.)
- Uses `ReachUtils` to determine maximum reach based on:
  - Client version (ViaVersion compatibility)
  - Server version (1.7 to 1.21+)
  - Entity type (shulkers, boats blacklisted)
  - Game mode (creative gets 4.5 blocks)
  - Weapon attributes (attack range component in 1.21+)
- Implements **combat-aware blink threshold**: Tighter threshold (0.3) during active combat vs standard (0.5) for non-combat
- Tracks `playerAttackQueue` to prevent duplicate flags per entity per tick
- Detects teleport bypass and null entity exploits

**C. Hitbox Expansion Detection**
Validates that hitbox expansions (e.g., from lag compensation) are not exploited:
- `Hitboxes.java` checks for entity hitbox abuse
- Validates that entities cannot be hit beyond their visual hitbox

### 4.3 Velocity Detection

Velocity detection ensures players respond correctly to knockback:

**A. Horizontal Velocity Check**
```java
// Simplified velocity check
double expectedHorizontalKB = applyKnockback(attacker, target);
double actualHorizontalDelta = Math.sqrt(dx * dx + dz * dz);

if (actualHorizontalDelta < expectedHorizontalKB * knockbackThreshold) {
    // Player reduced knockback — possible anti-knockback
    violationLevel += (expectedHorizontalKB - actualHorizontalDelta) / expectedHorizontalKB;
}
```

**B. Transaction-Based Velocity Tracking (GrimAC approach)**
GrimAC uses the transaction system to track exactly when knockback was received:
- Server sends knockback velocity → player must acknowledge via transaction
- Server compares expected velocity vs actual movement in the tick after transaction
- If player moves at full speed when they should be knocked back → velocity cheat flagged

**C. Vertical Velocity Check**
- Validates Y-axis movement matches expected knockback launch
- Anti-knockback often reduces vertical component to stay grounded
- Vertical anti-knockback is harder to detect but more suspicious

**D. False Positive Mitigation:**
- Server lag reduces knockback (TPS < 20)
- Lag spikes can cause velocity to not register properly
- Knockback modifiers from enchants/potions must be accounted for
- Explosion knockback has different mechanics than entity attacks

### 4.4 Flight Detection

Flight detection has evolved significantly in 1.9+ due to legitimate flight-like mechanics:

**A. Movement Simulation Approach (GrimAC method)**
The most robust approach is full movement simulation:

```java
// Simplified movement prediction
// For each movement packet, the server simulates all possible inputs
// and checks if the client's actual movement matches any valid path

Vector3d predictedVelocity = predictionEngine.guessBestMovement(player, input);
Vector3d actualMovement = player.actualMovement;

double offset = predictedVelocity.distance(actualMovement);
if (offset > threshold) {
    // Player moved in a way that cannot be produced by vanilla movement
    flag("simulation offset: " + offset);
}
```

GrimAC's `PredictionEngine` simulates:
- Walking (including different block friction types)
- Sneaking (70% speed, collision box changes)
- Sprinting (130% speed)
- Jumping (various heights based on potion effects)
- Falling (with gravity and terminal velocity)
- Elytra gliding (pitch-dependent speed)
- Swimming/crawling pose
- Ladder/vine climbing
- Levitation effect
- Wind charge (1.21+)

**B. Old Methods (Still Used in Some ACs):**
- **Y-level gain check:** Detect if Y increases without jump/takeoff → flight
- **Vertical motion consistency:** Check if velocity changes follow gravity
- **Jump cooldown:** Detect multiple jumps without landing
- **Creative mode bypass:** Check if flight ability is enabled in survival

**C. Ground-Based Flight Detection:**
- Check if player claims `onGround=true` while Y is significantly different from ground level
- Check if player is "hovering" at a non-vertical-integer Y level without touching ground

### 4.5 Speed Detection

Speed detection validates horizontal movement speed:

**A. Maximum Speed Per-Tick**
```java
// Simplified speed check
double deltaX = currentX - lastX;
double deltaZ = currentZ - lastZ;
double horizontalSpeed = Math.sqrt(deltaX * deltaX + deltaZ * deltaZ);

double maxSpeed = getMaxAllowedSpeed(player)
    // Base: 0.2873 (0.1 * 0.98 * movementFactor)
    // Sprint: 0.373 (0.13 * movementFactor)
    // Sprint + jump: 0.430
    // Potions: speed_amplifier * 0.2 * base
;

if (horizontalSpeed > maxSpeed + threshold) {
    flag("speed: " + horizontalSpeed + " max: " + maxSpeed);
}
```

**B. Friction Analysis**
Checks that friction properly reduces speed:
- Ice: friction = 0.98 (slippery)
- Normal block: friction = 0.6
- Speed should decrease when releasing movement keys
- "Bhop" cheats maintain speed without friction decay

**C. Acceleration Validation**
```java
// Check acceleration is physically plausible
double acceleration = currentSpeed - lastSpeed;
// Max acceleration from sprint: 0.026 blocks/tick^2
// Max acceleration from jump: ~0.09 blocks/tick^2 horizontal
if (acceleration > maxPossibleAcceleration) {
    flag("impossible acceleration: " + acceleration);
}
```

### 4.6 NoSlowdown Detection

NoSlowdown detection validates item usage movement reduction:

**A. Item-Use Speed Check**
```java
// When player is using item (eating, shielding), speed must be reduced
if (player.isUsingItem()) {
    double maxSneakingSpeed = getSneakingSpeed(player); // 30% of walk speed
    double slowMultiplier = getSlowMultiplier(player); // ~0.2 for eating/shielding
    double maxItemUseSpeed = maxSneakingSpeed * slowMultiplier;
    
    if (currentSpeed > maxItemUseSpeed + threshold) {
        flag("noslowdown: speed=" + currentSpeed + " while using item");
    }
}
```

**B. Sprint-While-Using-Item Detection**
- Vanilla: Using an item cancels sprinting
- NoSlow bypass allows sprinting while eating/blocking
- Check `SPRINTING` entity metadata vs item-use state

**C. Cobweb Check**
```java
// Cobweb slows movement to 0.05 blocks/tick (or 20% speed)
if (player.isInsideBlock(BlockTypes.COBWEB)) {
    if (currentSpeed > 0.05 + threshold) {
        flag("noslowdown: cobweb speed=" + currentSpeed);
    }
}
```

### 4.7 Scaffold Detection

Scaffold detection validates block placement patterns:

**A. Block Placement Rotation Check**
```java
// Scaffold bots rotate head downward to place at feet
// Check if player looks at own feet while placing blocks rapidly
if (pitch > 80 && blockPlaceRate > threshold) {
    flag("scaffold: suspicious pitch=" + pitch);
}
```

**B. Invalid Place Location Detection (GrimAC approach)**
GrimAC's `InvalidPlaceA/B` checks validate:
- **AirLiquidPlace:** Checks if blocks are placed in mid-air (no adjacent block to support)
- **RotationPlace:** Checks if the block face placement angle matches the player's rotation
- **AutoBlock:** Detects when blocks are automatically selected from hotbar (instant selection)

```java
// Simplified InvalidPlace check
// Player cannot place a block where there is no existing block to place against
// Scaffold places in mid-air by exploiting edge cases or spoofing face data
if (!hasAdjacentSupport(placedPosition, world)) {
    flag("invalid place: no adjacent support");
}
```

**C. Placement Interval Check**
- Human players place blocks at variable rates
- Scaffold bots place blocks at the maximum allowed rate every tick
- Check average block placement interval over a sliding window

### 4.8 Criticals Detection

Criticals detection validates jump/fali state during attacks:

**A. Ground State Validation**
```java
// Critical hit requires: falling, not on ground, not in water, not on ladder
if (packet.isAttack() && player.clientClaimsLastOnGround == false) {
    // Check if player was actually in falling state
    if (player.onGround || player.inWater || player.onClimbable) {
        flag("criticals: impossible state for crit");
    }
}
```

**B. Mini-Jump Detection**
- Some criticals cheats use tiny jumps (0.0625 blocks or less)
- Check that Y delta during "jump" exceeds minimum jump height (~0.42 blocks for jump from ground)
- Threshold: jump height must exceed 0.0625 blocks to count as legitimate airtime

**C. Cooldown Check**
- Critical hits require attack cooldown >= 100%
- Check cooldown timing when criticals are detected
- If cooldown is below 100% but attack is critical → spoofed state

### 4.9 AutoClicker Detection

AutoClicker detection analyzes click timing patterns:

**A. CPS (Clicks Per Second) Analysis**
```java
// Track attack timestamps in a 1-second sliding window
Deque<Long> attackTimes = player.attackTimestamps;
attackTimes.add(currentTime);
attackTimes.removeIf(t -> t < currentTime - 1000);

int cps = attackTimes.size();
int maxHumanCps = 12; // Highly skilled players can reach 12-14

if (cps > maxHumanCps) {
    flag("autoclicker: " + cps + " cps");
}
```

**B. Click Interval Variance Analysis**
```java
// Human clicks have high variance in intervals
// Autoclickers have consistent intervals
double[] intervals = getClickIntervals(attackTimes);
double stdDev = calculateStdDev(intervals);
double mean = calculateMean(intervals);
double coefficientOfVariation = stdDev / mean;

if (coefficientOfVariation < 0.3) {
    // Too consistent — likely autoclicker
    flag("autoclicker: low variance, CV=" + coefficientOfVariation);
}
```

**C. Burst Pattern Detection**
- Humans click in bursts (variable patterns)
- Autoclickers have uniform patterns
- Check autocorrelation of click intervals
- Check for machine-precision timing (always exactly 100ms apart vs human 95-110ms)

**D. Shannon Entropy Analysis (Advanced)**
```java
// Compute entropy of click distribution over time windows
// Human clicks have higher entropy (more random distribution)
// Autoclickers have lower entropy (patterned distribution)
double entropy = computeClickEntropy(intervals, bins);
if (entropy < humanThreshold) {
    flag("autoclicker: low entropy=" + entropy);
}
```

### 4.10 Timer Detection

Timer detection ensures clients are processing game ticks at the correct speed:

**A. Timer Balance Check**
```java
// Each server tick = 50ms. Client should send ~1 movement packet per 50ms.
// Timer cheat speeds up (1.1x - 10x) or slows down game processing.

long nanosPerTick = 50_000_000; // 50ms
long expectedTime = lastPacketTime + nanosPerTick;
long actualTime = System.nanoTime();

if (actualTime < expectedTime) {
    timerBalance += (expectedTime - actualTime);
} else {
    timerBalance -= (actualTime - expectedTime);
}

// Balance should stay near 0. Overflow positive = too fast (timer speed)
if (timerBalance > maxDriftNanos) {
    flag("timer: " + (timerBalance / 1_000_000) + "ms ahead");
}
```

**B. GrimAC Timer Implementation:**
GrimAC's `Timer.java` uses:
- `timerBalanceRealTime` tracking: expected += 50ms per packet, actual = System.nanoTime()
- When timerBalanceRealTime drifts ahead, the client is processing too fast
- Timer is a hard enforcement check: flags at 0.98 certainty → packet cancel + setback
- Handles lag-compensation (TPS drops cause legitimate client-side catchup)

**C. Clock Drift vs Cheat Distinction**
- Legitimate players can have small clock drift (+/- 100ms)
- Timer speed cheats consistently run ahead (500ms+ drift)
- Server lag causes apparent drift in the opposite direction
- Transaction-based timing provides more accurate measurement than wall-clock time

---

## 5. Popular Anticheats in 1.9+

### 5.1 GrimAC

**Overview:**
GrimAC is one of the most technically sophisticated open-source anticheats for Minecraft 1.7-1.21+. It is known for its movement prediction engine and rigorous packet validation.

**Architecture:**
- **Prediction Engine:** The core of GrimAC. Simulates every possible valid movement for a given input state and compares against client-reported movement. If the actual movement doesn't match any valid predicted movement → flag.
- **Check Categories:** Combat (Reach, Hitboxes, MultiInteract, AimAssist, AnchorAura, AutoCrystal, MaceCheck), Movement (GroundSpoof, Phase, NoFall), Packet (Timer, BadPackets A-Z, PacketOrder A-P), Elytra (A-I), Flight, Breaking, Scaffold, Multiactions, Misc
- **Post-Prediction Checks:** Checks that run after the prediction engine has verified movement validity. OffsetHandler, Phase, GroundSpoof run as PostPredictionChecks.
- **Transaction System:** Every server action (knockback, teleport, velocity change) is tied to a transaction. The client must acknowledge the transaction before the action takes effect. This prevents desync-based cheats.

**Key Technical Details (from source code):**

- **PredictionEngine** (`MovementCheckRunner.java`):
  - `processAndCheckMovementPacket(PositionUpdate data)` is the entry point
  - Handles unloaded chunk teleportation
  - Tracks prediction nano-time averaged over 500/20000 predictions
  - Delegates to vehicle-specific tickers (MovementTickerPlayer, MovementTickerHorse, etc.)
  - Uses multiple prediction engines: PredictionEngineNormal, PredictionEngineBoat, etc.

- **OffsetHandler:**
  - Tracks `advantageGained` — cumulative movement benefit over threshold
  - Sustained offset monitor: ThunderHack v4 bypass detection (0.004 offset threshold living)
  - Rolling 50-tick average of offset values
  - Max ceiling on accumulated advantage
  - Setback at threshold exceedance

- **Reach Check:**
  - Combat-aware blink threshold (0.3 during combat vs 0.5 otherwise)
  - Blink ping exemption (200ms)
  - Entity type blacklist (boats, shulkers)
  - `playerAttackQueue` map for per-entity-per-tick deduplication

- **AimAssist Check:**
  - YawStep detection (15-45 degree per-tick rotation range)
  - Smoothness detection (lag-1 autocorrelation > 0.85)
  - CPS gate (min 8 CPS for smoothness analysis)
  - Exemptions for teleport, vehicle switch, spectator, creative
  - Combat timeout (3 seconds without attack = reset)

- **Phase Check:**
  - Exemptions for piston pushes, vehicle dismounts (5-tick window)
  - 1.17 duplicate packet handling
  - Lag buffer (2 ticks max)
  - Offset unreliable threshold (0.01)

**Strengths:**
- Most comprehensive movement simulation of any open-source AC
- Transaction-based state tracking prevents desync exploits
- Multi-version support with version-specific logic
- Active development and community
- GPLv3 licensed

**Weaknesses:**
- High CPU usage from prediction calculations (~300ns per prediction, 500+ per tick)
- False positives from lag can be challenging
- Complex configuration
- Some checks are resource-intensive for large servers

### 5.2 Vulcan

**Overview:**
Vulcan is a premium anticheat known for its balance of performance and detection. It supports 1.7-1.21+ with separate detection profiles per version.

**Key Features:**
- **Heuristic-based detection:** Unlike GrimAC's simulation approach, Vulcan uses statistical heuristics
- **Configurable checks:** Extensive configuration options
- **AimAssist detection:** One of the first premium ACs with strong aim detection
- **Autoblocker detection:** Catches shield/block hacks
- **Timer prediction:** Uses both transaction and timing analysis

**1.9+ Specifics:**
- Separate combat profiles for 1.9+ (cooldown tracking)
- Elytra check with pitch-dependent speed limits
- Shield interaction validation

### 5.3 Matrix

**Overview:**
Matrix (now rebranded as Matrix AntiCheat / Sparky) is a premium anticheat focused on server performance and comprehensive detection.

**Key Features:**
- **Horizontal/Vertical movement prediction:** Simpler than GrimAC but effective
- **Reach calculation:** Uses both packet-timing and distance checking
- **AutoClicker:** CPS and variance analysis
- **Pattern recognition:** Detects repeatable cheat patterns
- **Performance-focused:** Minimal overhead per check

**1.9+ Specifics:**
- Version-specific movement penalties
- Cooldown-based combat validation
- Shield and elytra detection modules

### 5.4 Spartan

**Overview:**
Spartan is a long-standing premium anticheat with a focus on ease of use and regular updates.

**Key Features:**
- **Heuristic scoring:** Each violation type accumulates a score
- **Self-learning:** Adapts to player behavior patterns
- **Multi-version:** Supports 1.7-1.21+
- **Packet validation:** Strong packet inspection

**Limitations:**
- Historically criticized for false positives
- Less sophisticated movement prediction than GrimAC
- Detection rate lower on advanced bypasses

### 5.5 NoCheatPlus (NCP)

**Overview:**
One of the oldest open-source anticheats, now largely outdated for modern versions but still used on legacy servers.

**Key Features:**
- **Movement checks:** Simple Y-level and speed limit checks
- **Fight checks:** Reach (basic), angle (basic)
- **Block checks:** Scaffold detection (basic)
- **Multi-version support:** Largely abandoned for modern versions

**1.9+ Limitations:**
- No elytra support (false positives on 1.9+ movement)
- Attack cooldown not validated
- Shield interactions not handled
- Glide detection conflicts with elytra
- No swimming/crawling handling
- Generally considered obsolete for 1.9+ servers

### 5.6 AAC (Advanced AntiCheat)

**Overview:**
Advanced AntiCheat (AAC) was a popular premium anticheat that has since declined in use.

**Key Features:**
- **Navigation checks:** Path-finding analysis
- **Combat checks:** Basic KillAura detection
- **Timer check:** Good timer detection for its era

**1.9+ Compatibility:**
- AAC never fully adapted to 1.9+ mechanics
- Elytra causes false flags
- No swimming pose handling
- Cooldown not tracked

### 5.7 Comparison: 1.8 vs 1.9+ Anticheats

| Aspect | 1.8 Anticheats | 1.9+ Anticheats |
|--------|---------------|-----------------|
| **Movement model** | Simple threshold-based | Full simulation/prediction |
| **Combat validation** | Reach + speed check | Reach + cooldown + rotation analysis |
| **KillAura detection** | Multi-aura, angle check | Multi-aura, rotation smoothing, GCD, entropy |
| **Flight detection** | Y-level gain, timer | Movement simulation, elytra profile |
| **Speed detection** | Hard cap per-tick | Friction analysis, acceleration prediction |
| **Ground check** | onGround = true/false | Collision-based ground validation |
| **Timer detection** | Simple drift check | Transaction-anchored timing |
| **Packet validation** | Packet count, order | Full packet state machine (BadPackets A-Z) |
| **False positives** | Less likely (fewer cheats) | More nuanced (more mechanics) |
| **Performance** | Lower overhead | Higher CPU usage (simulation) |

---

## 6. Anti-Bypass Techniques

### 6.1 Transaction-Based Checks

Transactions are the most important anti-bypass mechanism in modern anticheats. The Minecraft protocol includes a transaction confirmation system:

**How it works:**
1. Server sends a `Ping` packet (Play State) with a unique ID
2. Client must respond with a `Pong` packet with the matching ID
3. This provides a round-trip measurement and ensures the client is processing packets

**GrimAC Transaction System:**
- Every action (knockback, teleport, velocity) is tied to a specific transaction
- The anticheat waits for the client to acknowledge the transaction before simulating the next tick
- This prevents cheats from "not seeing" knockback or teleport packets

**Cheat bypass attempts and countermeasures:**
| Bypass | Countermeasure |
|--------|---------------|
| Ignore transaction packets | Flag missing transactions |
| Batch transactions | Validate timing of each transaction response |
| Pre-acknowledge transactions | Track expected vs actual transaction IDs |
| Transaction flooding | Rate-limit and validate transaction order |
| Delayed transaction response | Account for ping; flag consistent delays |

```java
// Simplified transaction-based velocity check
server.sendKnockback(entity, target);
int transactionId = server.sendTransaction(target);
// Wait for transaction acknowledgement
if (acknowledged.get(transactionId)) {
    // Check if velocity was properly applied
    Vector3d expectedVelocity = calculateKnockbackVelocity(entity);
    Vector3d actualDelta = target.getMovementSinceTransaction(transactionId);
    if (actualDelta.distance(expectedVelocity) > threshold) {
        flag("velocity reduction detected");
    }
}
```

### 6.2 Motion Prediction

Motion prediction is the most powerful anti-bypass technique, used by GrimAC and other modern anticheats.

**Concept:**
For each movement packet, the anticheat predicts all possible valid positions the player could reach, then checks if the actual position matches any valid prediction.

**GrimAC Implementation:**
```java
// The prediction engine tries every combination of inputs:
// - forward movement (0, 0.98, -0.98)
// - strafe movement (0, 0.98, -0.98)  
// - jumping (true/false)
// - sneaking (true/false)
// - sprinting (true/false)
// Each combination produces a predicted velocity.
// If the actual velocity doesn't match any predicted velocity within threshold → flag.

public Vector3d guessBestMovement(GrimPlayer player) {
    List<VectorData> possibleMovements = new ArrayList<>();
    
    for (Input input : ALL_VALID_INPUTS) {
        // Apply friction
        Vector3d withFriction = applyFriction(player, input);
        // Apply movement keys
        Vector3d withMovement = applyMovement(withFriction, input);
        // Apply jumping
        Vector3d withJump = applyJump(player, withMovement, input);
        // Apply collisions  
        Vector3d withCollisions = applyCollisions(player, withJump);
        
        possibleMovements.add(new VectorData(withCollisions, input));
    }
    
    // Find the predicted movement closest to actual
    return findBestMatch(possibleMovements, player.actualMovement);
}
```

**Advantages over threshold-based checks:**
- Cannot be bypassed by staying "just under the limit"
- Detects acceleration anomalies
- Naturally handles version differences (separate prediction per version)
- Resistant to edge-case exploitation

### 6.3 Timer Checks

Timer detection has evolved from simple drift checks to multi-layered analysis:

**A. Real-Time Timer Balance (GrimAC method):**
```java
// Track expected vs real time
// Each movement packet should arrive ~50ms apart
long expectedTime = lastMovementNanos + 50_000_000L;
long realTime = System.nanoTime();

timerBalance += (expectedTime - realTime);
// If realTime < expectedTime, balance increases (client is too fast)
// If realTime > expectedTime, balance decreases (client is too slow)
```

**B. Transaction-Validated Timer:**
- Use transaction round-trip time as the clock reference instead of wall clock
- Eliminates clock drift false positives
- More accurate on laggy servers

**C. Server-Tick Timer:**
- Count the number of movements per server tick
- Vanilla: ~1 movement packet per tick (20 per second)
- Timer speed: 2+ movements per tick
- Timer slow: <1 movement per tick

**D. Packet Flow Analysis:**
- Analyze the inter-packet arrival times
- Timer speed causes burst packet patterns
- Timer slow causes gaps between packets
- Statistical analysis of packet timing distribution

### 6.4 Ground Checks

Ground state validation is critical for detecting Flight, Speed, Criticals, and NoFall cheats.

**A. Exempt vs Non-Exempt Ground States:**
```java
// GrimAC exemptOnGround() method — determines when onGround is exempt
// Exempt when on:
// - Slime blocks (bouncing)
// - Honey blocks (sliding)
// - Scaffolding
// - Powder snow
// - Ladders/vines
// - Water
// - Lava
// - Web
// - In vehicle
// - Elytra flying
// - Bed (spawn point)
```

**B. Collision-Based Ground Validation:**
Instead of trusting the client's `onGround` flag, the anticheat performs its own ground detection:
1. Simulate the player's bounding box at the reported position
2. Check if any block collision exists below the player (within 0.5 blocks)
3. Compare server-detected ground with client-claimed ground

```java
// GroundSpoof detection (GrimAC)
if (player.clientClaimsLastOnGround && !serverDetectsOnGround) {
    // Client claims ground but server says no ground below
    // Possible: GroundSpoof (NoFall bypass) or Criticals cheat
    
    if (predictionOffset < OFFSET_UNRELIABLE) {
        // Only flag when prediction is reliable
        flag("ground sprof: claimed onGround but server predicts airborne");
    }
}
```

**C. NoFall Detection:**
NoFall cheats send `onGround=true` during falls to prevent fall damage. Detection:
```java
// NoFall detection (GrimAC GroundSpoof check)
if (player.clientClaimsLastOnGround 
    && fallDistance > nofallMinFallDistance 
    && verticalVelocity < nofallMinVerticalVelocity) {
    // Physically impossible: on ground but falling with accumulated distance
    flagWithSetback("nofall onGround=true fallDist=" + fallDistance);
}
```

### 6.5 Rotation Smoothing Detection

Aim assist and silent aim are detected through rotation analysis:

**A. GCD (Greatest Common Divisor) Analysis:**
Mouse-based rotation involves integer pixel counts divided by sensitivity/DPI. The GCD of rotation components reveals aim assistance:
```java
// GCD analysis approach
double[] yawDeltas = collectYawDeltas(player);
double gcd = findGCD(yawDeltas);
// Vanilla mouse: GCD = sensitivity / DPI ratio (varies by player)
// Silent aim: no consistent GCD (interpolated values)
// Too tiny GCD (< 0.01): indicates programmatic rotation
```

**B. Smoothness Analysis (GrimAC approach):**
```java
// Auto-correlation of yaw deltas
double correlation = computeLag1Correlation(yawDeltas);
// r > 0.85 with CPS > 8 → aim assist
// Humans have r < 0.6 on average
```

**C. YawStep Detection (GrimAC approach):**
```java
// ThunderHack Aura uses 24-35 degree per-tick rotations
// If >80% of combat ticks have yaw delta in [15, 45] → flag
if (inRangeRatio >= 0.8) {
    accumulate buffer;
    if (buffer >= 3) {
        flag("YawStep: suspicious rotation range");
    }
}
```

**D. Raycast/Line-of-Sight Validation:**
- Server validates that the player's rotation actually aligns with the target's hitbox
- Checks that the attack ray (from eye position in looking direction) intersects the target
- KillAura may attack without rotating toward the target (rotations sent separately)
- Validates rotation matches attack (server computes what player should be looking at)

**E. Rotation Bypass Detection:**
- Silent aim rotates client-side without sending rotation packets
- Server compares attack direction vs actual rotation
- If attack hits a target the player isn't looking at → KillAura flagged

### 6.6 Packet Validation

Packet validation verifies that the client sends valid, well-formed packets:

**A. BadPackets Checks (GrimAC):**
GrimAC has 26+ BadPackets checks (A-Z):
- **BadPacketsA:** Too many packets (packet flooding)
- **BadPacketsB:** Spoofed on-ground state
- **BadPacketsC:** Invalid player dig state
- **BadPacketsD:** Invalid use entity data
- **BadPacketsE:** Impossible pitch values (beyond ±90)
- **BadPacketsF:** Invalid item swap actions
- **BadPacketsG:** Mismatched client/server positions
- **BadPacketsH:** Invalid movement key combinations
- **BadPacketsI:** Abnormal rotation
- **BadPacketsJ:** Invalid teleport acknowledges
- **...continues through Z**

**B. Packet Order Validation (GrimAC):**
GrimAC has 16 PacketOrder checks (A-P):
- Validate that packets arrive in expected order
- Detect reordered, duplicated, or missing packets
- Block common exploit chains

**C. Payload Validation:**
- Check that packet fields contain valid values
- Prevent negative coordinates, NaN floats, infinity values
- Validate entity IDs exist and are valid targets
- Check item counts are within valid ranges

**D. Mismatch Detection:**
- Cross-reference data across different packet types
- Example: ATTACK packet + INTERACT_ENTITY packet for same tick are suspicious
- Example: ANIMATION (swing) without matching ATTACK → AutoClicker

### 6.7 Lag Compensation

Lag compensation prevents false positives from network conditions:

**A. Ping-Based Compensation:**
```java
// Adjust expected timing based on player ping
int ping = player.getTransactionPing();
int pingTicks = (int) Math.round(ping / 50.0);
// Allow pingTicks of delay in movement validation
// Higher ping = more tolerance for position/rotation delays
```

**B. TPS-Based Compensation:**
```java
// During server lag (TPS < 20), prediction is unreliable
double tps = GrimAPI.INSTANCE.getPlatformServer().getTPS();
if (tps < 18) {
    // Increase threshold or skip certain checks
    offsetThreshold *= (20.0 / tps); // Scale threshold
}
// Freeze detection below 15 TPS (GrimAC)
// Resume normal detection at 17 TPS (hysteresis)
```

**C. Jitter Compensation:**
- Ping spikes (jitter) can cause false positives
- Track jitter as stdDev of recent ping values
- Increase tolerance windows during jitter spikes
- Penalty for consistent high jitter (indicates proxy/VPN)

**D. Version Compensation:**
```java
// Different Minecraft versions have different movement mechanics
if (clientVersion.isOlderThan(ClientVersion.V_1_9)) {
    // Pre-1.9: no attack cooldown, different sprint mechanics
    usePredictionEngineV1_8();
} else if (clientVersion.isNewerThanOrEquals(ClientVersion.V_1_13)) {
    // 1.13+: swimming, tridents
    usePredictionEngineV1_13();
} else if (clientVersion.isNewerThanOrEquals(ClientVersion.V_1_9)) {
    // 1.9-1.12: shields, elytra
    usePredictionEngineV1_9();
}
```

---

## 7. Technical Implementation Details

### 7.1 Packet Analysis Server-Side

Modern anticheats hook into the server's packet pipeline to intercept and analyze packets before they reach the game logic.

**Packet Hooking Architecture:**
```
Client → Network I/O → PacketInterceptor → Anticheat → Game Logic
                                                    ↓
                                               Packet Cancel (if cheat detected)
```

**Key Packets Analyzed:**

| Packet | Direction | Content |
|--------|-----------|---------|
| `Play.Client.POSITION` | C→S | Player position (x, y, z, onGround) |
| `Play.Client.POSITION_LOOK` | C→S | Position + rotation (yaw, pitch) |
| `Play.Client.LOOK` | C→S | Rotation only (yaw, pitch, onGround) |
| `Play.Client.FLYING` | C→S | onGround only (no position/rotation change) |
| `Play.Client.ATTACK` | C→S | Entity ID to attack |
| `Play.Client.INTERACT_ENTITY` | C→S | Entity ID + action (interact/attack) |
| `Play.Client.USE_ITEM` | C→S | Hand used, position |
| `Play.Client.BLOCK_PLACE` | C→S | Block position, face, hand |
| `Play.Client.ANIMATION` | C→S | Swing arm (hand) |
| `Play.Client.PLAYER_DIGGING` | C→S | Dig action, block position |
| `Play.Client.HELD_ITEM_CHANGE` | C→S | Hotbar slot selection |
| `Play.Client.CLICK_WINDOW` | C→S | Inventory click action |
| `Play.Client.ENTITY_ACTION` | C→S | Entity action (sneak, sprint, jump) |
| `Play.Client.CLIENT_STATUS` | C→S | Status (respawn, stats) |

**PacketEvent System (used by GrimAC via PacketEvents API):**
```java
// Example packet interception
@PacketHandler
public void onPacketReceive(PacketReceiveEvent event) {
    if (event.getPacketType() == PacketType.Play.Client.FLYING) {
        // This is the base movement packet (all movement packets extend it)
        handleMovement(event);
    } else if (event.getPacketType() == PacketType.Play.Client.ATTACK) {
        handleAttack(event);
    }
    // ... additional packet handlers
}
```

**State Machine Per Player:**
Each connected player has a state object that tracks:
- Current position (x, y, z)
- Last position (lastX, lastY, lastZ) 
- Current velocity (clientVelocity x, y, z)
- Rotation (yaw, pitch)
- Movement flags (onGround, inWater, inLava, onClimbable)
- Combat state (lastAttackTime, cooldownRemaining)
- Packet flow statistics (packetsReceived, packetsPerSecond)
- Transaction state (pending transactions, acknowledged transactions)

### 7.2 Movement Simulation and Prediction

Movement simulation is the most technically sophisticated aspect of modern anticheats. GrimAC's implementation is considered the gold standard.

**Simulation Flow:**

```
1. Receive movement packet (Flying/Packet)
2. Extract position, rotation, onGround
3. Calculate actual movement: actualMovement = currentPosition - lastPosition
4. Determine player state: 
   - Grounded? (collision check)
   - In water/lava? (fluid detection)
   - On climbable? (ladder/vine check)
   - In cobweb? 
   - Elytra flying?
   - Under levitation effect?
5. Determine player input:
   - Forward movement? (calculated from rotation delta)
   - Strafe movement?
   - Jumping? (Y delta analysis)
   - Sneaking? (pose/bbox analysis)
   - Sprinting? (speed analysis + metadata)
6. Generate all valid predictions:
   - For each combination of inputs, compute expected velocity
   - Apply friction, acceleration, gravity
   - Apply collisions and block interactions
7. Find best match: 
   - Compare predicted velocities to actual velocity
   - Pick the closest match (minimum offset)
8. Evaluate offset:
   - offset < threshold → valid movement
   - offset > threshold → invalid (cheat or lag)
9. Run post-prediction checks:
   - Phase check (did player move through blocks?)
   - GroundSpoof check (is onGround correct?)
   - NoFall check (is fall damage valid?)
```

**GrimAC Movement Ticker Structure:**
```java
// MovementCheckRunner.processAndCheckMovementPacket()
// → MovementTickerPlayer.tick() (for players)
// → MovementTickerHorse.tick() (for horses)
// → MovementTickerBoat.tick() (for boats)
// etc.

// Each ticker handles the specific movement mechanics of that entity type.
// For example, MovementTickerPlayer handles:
// - Walking/running physics
// - Jump mechanics (jump height, potion effects)
// - Landing mechanics
// - Step-up (0.6 block auto-step)
```

**Friction and Acceleration Model:**
```java
// Minecraft's movement model:
// 1. Apply friction: velocity *= friction (0.91 on ground, 0.98 in air)
// 2. Apply movement acceleration
// 3. Apply gravity: velocity.y -= 0.08 * gravityFactor
// 4. Apply drag: velocity *= 0.98 (air resistance)
// 5. Clamp velocity to terminal velocity
// 6. Apply collisions (wall collisions, floor collisions)

// The anticheat simulates all of this and compares to the client result
```

### 7.3 Attack Cooldown Validation

The attack cooldown system introduced in 1.9 requires server-side validation:

**Expected Attack Timing:**
```java
// Attack speed calculation per weapon type:
// Sword (1.6): cooldown = 20/1.6 = 12.5 ticks (625ms)
// Axe (1.0): cooldown = 20/1.0 = 20 ticks (1000ms)
// Pickaxe (1.2): cooldown = 20/1.2 = 16.67 ticks (833ms)
// Shovel (1.0): cooldown = 20/1.0 = 20 ticks (1000ms)
// Hoe (varies by material): 1.0-4.0 attacks/sec
// Trident (1.1): cooldown = 20/1.1 = 18.18 ticks (909ms)
// Mace (1.21+, 0.6): cooldown = 20/0.6 = 33.33 ticks (1667ms)
```

**Server-Side Cooldown Validation:**
```java
public class AttackCooldownHandler {
    private long lastAttackTime = 0;
    private int expectedCooldownTicks;
    
    public void onAttack(PacketReceiveEvent event) {
        long now = System.currentTimeMillis();
        long elapsed = now - lastAttackTime;
        long expectedCooldown = getCooldownForItem(player.getHeldItem());
        
        // Check 1: Minimum cooldown between attacks
        if (elapsed < expectedCooldown * 0.8) {
            // Player attacked before cooldown expired
            // Could be ignoring cooldown (KillAura/AutoClicker)
            violationLevel += (expectedCooldown - elapsed) / expectedCooldown;
        }
        
        // Check 2: Damage consistency
        // If cooldown was too fast, damage should be reduced
        // But if damage is full, player may be spoofing cooldown
        
        // Check 3: Attack rate over sliding window
        attackTimestamps.add(now);
        attackTimestamps.removeIf(t -> t < now - 5000);
        if (attackTimestamps.size() > getMaxAttacksInWindow()) {
            flag("attack cooldown: " + attackTimestamps.size() + " attacks in 5s");
        }
        
        lastAttackTime = now;
    }
}
```

**Cooldown Bypass Detection:**
- **Spoofed cooldown:** Client reports cooldown as 100% but attacks faster than weapon allows
- **Attack packet spam:** Sends multiple attack packets per tick (only first should count)
- **Ping manipulation:** Uses lag to mask attack timing (transaction-based timing counters this)

### 7.4 Shield Interaction Checks

Shields require specific validation in 1.9+ anticheats:

**Shield State Tracking:**
```java
// Track shield state from entity metadata
// Blocking flag (bit 4 of entity metadata byte 0)
boolean shieldRaised = (entityMetadata & 0x10) != 0;

// Also track off-hand item
ItemStack offHandItem = player.inventory.getOffHand();
boolean hasShield = offHandItem.getType() == ItemTypes.SHIELD;
```

**Shield Bypass Detection:**

1. **Attack-While-Blocking:**
   - Vanilla: Shield must be lowered before attacking
   - Cheat: Player attacks with shield raised
   - Detection: ATTACK packet while metadata shows shield raised

2. **Shield Toggle (Instant Block):**
   - Vanilla: Shield takes 1 tick to raise
   - Cheat: Player can block instantly after attacking
   - Detection: Check raise animation timing vs attack timing

3. **Shield Cooldown Bypass:**
   - Axe attacks disable shields for 5 seconds (1.9 behavior, changed in later versions)
   - Cheat: Player re-raises shield instantly after axe hit
   - Detection: Track shield disable cooldown server-side

4. **AutoShield:**
   - Automatically raises shield when being attacked
   - Detection: Shield raised in direct response to incoming damage (too fast for human reaction)
   - Human reaction time: 200-300ms minimum
   - AutoShield: <50ms shield raise after attack

### 7.5 Elytra / Trident Detection

Elytra presents unique challenges for anticheat systems because it mimics many flight cheat behaviors.

**Elytra State Machine:**
```
State: NOT_FLYING (on ground)
  → Player jumps + holds jump in air → ELYTRA_ACTIVATED
  → Player right-click with firework → ROCKET_BOOST
  → Player looks down → DIVING (acceleration)
  → Player looks up → GLIDING (deceleration)
  → Player hits ground → NOT_FLYING
  → Player hits water → NOT_FLYING (elytra disables in water)
```

**Elytra Speed Validation:**
```java
// Elytra horizontal speed depends on pitch angle
// Looking straight forward (pitch = 0): ~0.2 blocks/tick
// Looking 45 degrees down: ~0.7 blocks/tick
// Looking straight down (pitch = 90): ~1.1 blocks/tick
// With firework rocket boost: +~0.3 blocks/tick (additive)

double pitch = Math.abs(player.pitch);
double expectedSpeed = calculateElytraSpeed(pitch, hasRocketBoost);
double actualHorizontalSpeed = Math.sqrt(dx*dx + dz*dz);

if (actualHorizontalSpeed > expectedSpeed + threshold) {
    // Could be speed cheat while using elytra
    flag("elytra speed: " + actualHorizontalSpeed + " (expected " + expectedSpeed + ")");
}

// Also validate vertical component
// Elytra falling speed is 0.6-1.0 blocks/tick downward (pitch dependent)
// Sudden upward movement is impossible without rocket boost
```

**Trident Riptide Detection:**
```java
// Riptide trident creates a specific velocity profile:
// - Horizontal: ~1.5 * lookingDirection (horizontal component)
// - Vertical: ~1.5 * lookingDirection (vertical component, can be upward!)
// - Lasts for exactly 1 tick (instant launch)
// - Requires rain or water

if (packetContainsRiptideUsage(player)) {
    // Expected launch velocity
    double expectedH = 1.5 * Math.cos(Math.toRadians(player.pitch)) * lookingDirHorizontal;
    double expectedV = 1.5 * Math.sin(Math.toRadians(-player.pitch));
    
    // Apply as instant velocity change (one tick only)
    if (!isCloseToExpected(player.actualMovement, expectedH, expectedV)) {
        // Player modified riptide velocity — possible riptide reach or riptide fly
        flag("riptide velocity mismatch");
    }
}
```

**Elytra GrimAC Checks (A-I):**
GrimAC has 9 dedicated elytra checks (ElytraA through ElytraI) covering:
- ElytraA: Basic speed validation
- ElytraB: Pitch limits during elytra flight
- ElytraC: Firework rocket usage validation
- ElytraD: Vertical velocity validation
- ElytraE: Elytra activation validation
- ElytraF: Elytra + movement interaction
- ElytraG: Elytra packet timing
- ElytraH: Elytra collision validation
- ElytraI: Elytra + pose interaction

### 7.6 Swimming and Crawling Checks

Since 1.13, swimming has changed player movement mechanics significantly:

**Swimming Detection:**
```java
// Player is swimming when:
// 1. In water (or waterlogged block)
// 2. Holding space (jump) while in water
// 3. Pose = SWIMMING (entity metadata)

boolean isSwimming = player.pose == Pose.SWIMMING;
boolean isInWater = player.inWater;
boolean isSprintSwimming = isSwimming && player.isSprinting;

// Sprint swimming speed:
// - Base: walking speed (0.1 * movementFactor)
// - Swim modifier: 0.03 additional factor
// - Sprint modifier: 1.3x multiplier
// - Depth Strider: increases speed further
double maxSwimSpeed = calculateSwimSpeed(player, isSprintSwimming);
```

**Swimming Hitbox Changes:**
```java
// Standing: 0.6 wide x 1.8 tall
// Swimming: 0.6 wide x 0.6 tall (same as crawling)
// 
// Player can swim through 1-block high gaps
// Anticheat must use appropriate hitbox size for collision checks

if (player.pose == Pose.SWIMMING) {
    player.boundingBox = new SimpleCollisionBox(
        player.x - 0.3, player.y, player.z - 0.3,
        player.x + 0.3, player.y + 0.6, player.z + 0.3
    );
} else {
    player.boundingBox = new SimpleCollisionBox(
        player.x - 0.3, player.y, player.z - 0.3,
        player.x + 0.3, player.y + 1.8, player.z + 0.3
    );
}
```

**Crawling Detection:**
```java
// Crawling conditions:
// 1. Head in a block (space above < 2 blocks)
// 2. Holding sneak
// 3. Pose = SWIMMING (same pose as swimming in 1.14+)
// 4. Not in water

boolean isCrawling = player.pose == Pose.SWIMMING && !player.inWater;

if (isCrawling) {
    // Validate that there IS actually a block above the player
    // (why else would they be crawling?)
    double headSpace = getSpaceAbovePlayer(player);
    if (headSpace >= 2.0) {
        // Player is crawling with no reason — possible speed exploit
        // (Crawling changes collision and friction behavior)
        flag("crawling without blocked head");
    }
}

// Crawling speed = sneaking speed (30% of walk speed)
double maxCrawlSpeed = getSneakingSpeed(player);
```

**Pose Transition Validation:**
```java
// Player cannot instantly go from standing to swimming/crawling
// There's a 1-tick transition period where the hitbox changes
// Cheats can abuse this to phase through blocks

if (lastPose != Pose.SWIMMING && currentPose == Pose.SWIMMING) {
    // Must be in water OR have head in block
    if (!player.inWater && headSpace >= 2.0) {
        flag("invalid pose transition: standing → swimming without water or obstruction");
    }
}
```

---

## Appendix: Key References

### Protocol References
- **wiki.vg/Mojang API** — Minecraft protocol specification for all packet types
- **wiki.vg/Entity_metadata** — Entity metadata flags for shields, poses, and status effects
- **wiki.vg/Attribute** — Attribute system (attack speed, movement speed, reach)

### Anticheat Source Code
- **GrimAC** — [https://github.com/GrimAnticheat/Grim](https://github.com/GrimAnticheat/Grim) (GPLv3)
  - Most comprehensive open-source reference for movement prediction
  - Implements full Minecraft movement simulation
- **NoCheatPlus** — [https://github.com/Updated-NoCheatPlus/NoCheatPlus](https://github.com/Updated-NoCheatPlus/NoCheatPlus)
  - Historical reference for basic anticheat approaches
- **AntiAura** — [https://github.com/HTMonkeyGang/AntiAura](https://github.com/HTMonkeyGang/AntiAura)
  - Rotation and aim analysis reference

### Academic/Research References
- The BakiVF Pattern: Anticheat feature extraction design pattern used in production anticheat systems
- Attack cooldown and DPS analysis for 1.9+ PvP mechanics
- Network delay compensation algorithms for real-time game cheat detection

### Version History
- **1.9 (Feb 2016):** Combat Update — attack cooldown, shields, dual wielding, elytra
- **1.11 (Nov 2016):** Off-hand shield toggle improvements
- **1.13 (Jul 2018):** The Update Aquatic — swimming, tridents
- **1.14 (Apr 2019):** Village & Pillage — crawling, crossbows
- **1.16 (Jun 2020):** Nether Update — soul speed enchantment
- **1.17 (Jun 2021):** Caves & Cliffs — powder snow, deeper world
- **1.19 (Jun 2022):** The Wild — swift sneak enchantment
- **1.20 (Jun 2023):** Trails & Tales — new armor trims (cosmetic)
- **1.21 (2024):** Tricky Trials — mace, wind charge, new combat mechanics
