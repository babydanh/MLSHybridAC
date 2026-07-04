# Grim Anticheat Development Guidelines & Rule Skills

This document defines the rules, architecture, shortcuts, and **known pitfalls** for AI coding assistants working on the Grim Anticheat codebase. Follow these rules strictly to ensure the codebase remains clean, compile-safe, and compatible with both Bukkit and Folia.

---

## 🛠️ Build & Runtime Environment

1. **Gradle Wrapper**: Always use `./gradlew` (or `gradlew.bat` on Windows CMD). Do not run global `gradle` command.
2. **Java / JDK Version**: Grim targets **Java 21 to 25**. Make sure the environment variables are set to Java 21+ (Java 25 is preferred for modern runServer tasks).
3. **Quick test compile** (chỉ test compile module bukkit, không full build):
   ```bash
   ./gradlew :bukkit:compileJava -x test
   ```
4. **Full build** (đóng gói JAR, chạy khi cần output cuối):
   ```bash
   ./gradlew build -x test
   ```
5. **Build Output**: The final Bukkit plugin JAR will be located at:
   `Grim/bukkit/build/libs/GrimAC-bukkit-all.jar` (or with `shadow` suffix).

---

## 📐 Project Architecture

The project follows a cross-platform multi-module architecture:

1. **`:common` Module**:
   - Contains all Core logic, Packet listeners, and Heuristic checks.
   - **CRITICAL**: Do NOT import any Bukkit APIs (`org.bukkit.*`), Fabric APIs, or platform-specific classes here.
   - All player interactions must go through the platform abstraction layer (e.g., `GrimPlayer`, `PlatformPlayer`).
2. **`:bukkit` Module**:
   - Implements Spigot/Paper/Folia support.
   - Handles commands, Bukkit listeners, particle effects, and Bukkit scheduling.
3. **`:fabric` Module**:
   - Handles Fabric server support.

---

## 📦 Dependency Management (`libs.versions.toml`)

- **Rule**: Do not hardcode dependency versions in `build.gradle.kts` files.
- **Shortcuts**: All dependencies are managed in `Grim/libs.versions.toml`.
  - To add a dependency, declare it under `[versions]` and `[libraries]` inside `libs.versions.toml`.
  - Reference it in `build.gradle.kts` using `libs.dependencyName` (e.g. `libs.paper.api`, `libs.placeholderapi`).

---

## 🎬 Ban Animation System (Integrated)

We have integrated the data-driven **Ban Animation Engine** inside the Bukkit module:

1. **Package Location**: `ac.grim.grimac.platform.bukkit.animation`
2. **Sub-packages**:
   - `...animation.engine` — AnimationManager, AnimationPresets, BanAnimationConfig, AnimationConfigLoader
   - `...animation.compat` — ParticleCompat, EffectCompat, ParticlePacketCompat, ServerVersion, VersionAdapter
   - `...animation.scheduler` — SchedulerManager, ScheduledTask, SchedulerAdapter, BukkitSchedulerAdapter, FoliaSchedulerAdapter, ServerType
   - `...animation.handlers` — AlertHandler, BanHandler, RawHandler
3. **How to Trigger**:
   Use the console command:
   ```text
   /bananimation <player> <animation_name> <command...>
   ```
4. **Configurations**:
   - Animation YAML files loaded from `plugins/GrimAC/animations/` folder.
   - Presets: `classic_ban.yml`, `dramatic_ban.yml`, `rainbow_ban.yml`.

---

## ⚠️ Known Pitfalls — Các Lỗi Đã Gặp & Cách Tránh

### Pitfall 1: Refactoring Package Tự Động Bỏ Sót Reference Trong `implements`

**Vấn đề xảy ra:**
Khi script Python thực hiện find-replace `wtf.mlsac.scheduler.` → `ac.grim.grimac...scheduler.` trong các file, nó chỉ sửa được các dòng `import` hoặc dòng code thông thường. Tuy nhiên, khai báo `implements` ở dòng class definition bị sót vì nó không có từ khóa `import`:

```java
// File: FoliaScheduledTask.java
// LỖI — còn tham chiếu package cũ trong `implements`
public class FoliaScheduledTask implements wtf.mlsac.scheduler.ScheduledTask {
```

**Fix đúng:**
```java
public class FoliaScheduledTask implements ac.grim.grimac.platform.bukkit.animation.scheduler.ScheduledTask {
```

**Quy tắc:**
> Khi refactor package bằng script, **phải** tìm thêm các pattern:
> - `implements OldPackage.ClassName`
> - `extends OldPackage.ClassName`
> - `throws OldPackage.ExceptionClass`
> - Các tham chiếu fully-qualified trong code body (không phải import)

---

### Pitfall 2: Copy File Từ Repo Ngoài Bỏ Sót Subdirectory

**Vấn đề xảy ra:**
Khi clone repo `mls-network-plugin` và copy các file từ `penalty/`, chúng ta đã bỏ qua subdirectory `penalty/handlers/` chứa các class:
- `AlertHandler.java`
- `BanHandler.java`
- `RawHandler.java`

Dẫn đến `PenaltyExecutor.java` import chúng nhưng không tìm thấy file:
```
error: package ac.grim.grimac.platform.bukkit.animation.handlers does not exist
```

**Quy tắc:**
> Trước khi copy file từ repo ngoài, **phải** dùng `list_dir` để liệt kê **toàn bộ** cấu trúc thư mục bao gồm subdirectories, không chỉ nhìn file ở root folder. Sau đó đảm bảo copy cả subdirectory tree.

---

### Pitfall 3: Import Class Của Thư Viện Ngoài Không Có Trong Build

**Vấn đề xảy ra:**
File `WorldGuardCompat.java` từ repo MLS import WorldGuard và WorldEdit:
```java
import com.sk89q.worldedit.bukkit.BukkitAdapter;
import com.sk89q.worldguard.WorldGuard;
```
Nhưng `build.gradle.kts` của Grim không có WorldGuard/WorldEdit là dependency → compile error.

**Fix:** Xóa `WorldGuardCompat.java` (hoặc làm stub không import gì) vì Grim không dùng WorldGuard.

**Quy tắc:**
> Khi thêm file từ repo ngoài vào dự án, **phải** kiểm tra từng `import` trong file đó rồi đối chiếu với `libs.versions.toml` và `build.gradle.kts` của module tương ứng. Nếu dependency không có → hoặc thêm vào build, hoặc xóa/stub file đó.

---

### Pitfall 4: Enum `Particle` Bị Đổi Tên Từ 1.20.5+

**Vấn đề xảy ra:**
Paper API 1.20.5+ đổi tên nhiều `Particle` enum:

| Tên cũ (pre-1.20.5) | Tên mới (1.20.5+) |
|---|---|
| `Particle.REDSTONE` | `Particle.DUST` |
| `Particle.SMOKE_LARGE` | `Particle.LARGE_SMOKE` |
| `Particle.EXPLOSION_LARGE` | `Particle.EXPLOSION` |
| `Particle.EXPLOSION_HUGE` | `Particle.EXPLOSION_EMITTER` |
| `Particle.SPELL_WITCH` | `Particle.WITCH` |
| `Particle.SPELL_MOB` | `Particle.ENTITY_EFFECT` |

Dùng tên cũ gây `cannot find symbol` trên Paper 1.21.

**Fix đúng:** Dùng `ParticleCompat` wrapper đã có sẵn trong project:
```java
// Thay vì:
particle = Particle.REDSTONE;
// Dùng:
particle = ParticleCompat.getDustParticle();

// Thay vì:
particle = Particle.SMOKE_LARGE;
// Dùng:
particle = ParticleCompat.getParticle("LARGE_SMOKE");
```

**So sánh bằng tên thay vì bằng enum:**
```java
// Sai — Particle.REDSTONE có thể không tồn tại:
if (p.particleType == Particle.REDSTONE)

// Đúng — so sánh tên:
if (p.particleType != null && (p.particleType.name().equals("REDSTONE") || p.particleType.name().equals("DUST")))
```

**Quy tắc:**
> Không bao giờ dùng `Particle.XXX` enum constant trực tiếp với tên cũ pre-1.20.5. Luôn dùng `ParticleCompat` wrapper hoặc so sánh bằng `.name()` để tương thích đa phiên bản.

---

### Pitfall 5: Interface Có Method Không Implement

**Vấn đề xảy ra:**
File `ActionHandler.java` (interface) khai báo method `getActionType()`, nhưng không có class nào implement method này → compile error toàn bộ handler chain.

**Quy tắc:**
> Khi tạo interface, chỉ khai báo method mà **tất cả** implementor đều thực sự cần implement. Nếu method là optional, dùng `default` method với implementation rỗng hoặc `UnsupportedOperationException`. Kiểm tra trước khi commit.

---

### Pitfall 6: `SchedulerManager` Dùng Reflection Với Package Cũ

**Vấn đề xảy ra:**
Trong `SchedulerManager.java`, class `FoliaSchedulerAdapter` được load bằng reflection:
```java
// LỖI — vẫn là package cũ:
Class.forName("wtf.mlsac.scheduler.FoliaSchedulerAdapter")
```
Script regex find-replace thông thường không tìm được chuỗi này vì nó là string literal trong code, không phải import statement.

**Fix:**
```java
Class.forName("ac.grim.grimac.platform.bukkit.animation.scheduler.FoliaSchedulerAdapter")
```

**Quy tắc:**
> Sau khi refactor package, **phải** tìm kiếm chuỗi package cũ trong toàn bộ string literals bằng `grep_search`:
> ```
> grep "wtf.mlsac" /path/to/project --include="*.java"
> ```
> Đặc biệt chú ý: `Class.forName()`, `getResourceAsStream()`, log messages, config strings.

---

## ⚡ Code Conventions & Shortcuts

1. **Lombok**:
   - The project uses Lombok extensively. Use annotations like `@Getter`, `@Setter`, `@RequiredArgsConstructor`, and `@Nullable` to minimize boilerplate.
2. **Adventure API (MiniMessage)**:
   - Do NOT use legacy chat colors (e.g. `§c` or `ChatColor.RED`) for player messages unless required by legacy APIs.
   - Use Adventure MiniMessage formats (e.g., `<red>Failed check</red>`) and process via `MessageUtil.miniMessage(text)`.
3. **Scheduler & Multithreading**:
   - For Bukkit/Folia compatibility, always use `PlatformScheduler` or the animation-specific `SchedulerManager.getAdapter()`.
   - Never block the main/primary server thread with expensive network requests — run them asynchronously.
4. **Particle API**:
   - Luôn dùng `ParticleCompat` cho tất cả particle spawning để tương thích 1.16–1.21.x.
   - Không hardcode tên Particle enum cũ (pre-1.20.5).
5. **Kiểm tra trước khi copy file ngoài**:
   - `list_dir` toàn bộ cấu trúc repo nguồn.
   - Kiểm tra từng import xem có dependency nào không có trong Grim build không.
   - Chạy `grep_search` cho package cũ sau khi refactor để đảm bảo không còn sót.
