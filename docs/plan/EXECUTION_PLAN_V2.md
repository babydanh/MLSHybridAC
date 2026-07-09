# Kế Hoạch Thực Thi V2 — Multi-Agent Execution

## Tổng quan
- Mục tiêu: Hoàn thiện hybrid architecture, đưa MLSHybridAC lên production-ready
- Phương pháp: Multi-agent song song (nghiên cứu + implement + verify)
- Tham khảo: MLS architecture, BakiVF remote inference, Grim upstream

## Phase 1: Research & Analysis (3 agents song song)

### Agent A: Nghiên cứu MLS Architecture
- Input: docs/plan/05-hybrid-architecture.md, 08-ml-system.md, 09-fusion-policy.md
- Output: MLS architectural patterns áp dụng được
- Nhiệm vụ: 
  - So sánh FusionEngine hiện tại với MLS fusion
  - Xác định feature groups còn thiếu
  - Đề xuất cấu trúc async ML pipeline

### Agent B: Phân tích Detection Flow Gaps
- Input: Toàn bộ Grim source đã đọc
- Output: Danh sách gaps cụ thể
- Nhiệm vụ:
  - FusionEngine chưa wired vào PunishmentManager
  - FeatureBridge chưa được consume bởi FusionEngine
  - CheckManager còn 110 checks instantiate dư thừa

### Agent C: So sánh Grim Upstream
- Input: Git diff giữa local và upstream Grim
- Output: Các thay đổi cần merge
- Nhiệm vụ:
  - Xác định phần code nào là MLSHybridAC tự viết
  - Xác định phần nào là Grim gốc cần theo dõi upstream

## Phase 2: Core Implementation (4 agents song song)

### Agent D: Fix Infrastructure
- Fix remote URL → push lên GitHub
- Comment unused checks trong CheckManager.java
- Build verify

### Agent E: Wire FusionEngine → PunishmentManager
- FusionEngine.evaluate() được gọi trước mỗi lần punish
- Session risk accumulator kết nối với violation counter
- Grace period cho new players

### Agent F: Consume FeatureBridge
- FeatureBridge data → FusionEngine input
- LagProfile → runtime penalty trong FusionEngine
- Thêm windowed aggregates cho click/combat features

### Agent G: Graphify + Documentation
- Run graphify . --no-viz
- Generate knowledge graph
- Update docs

## Phase 3: Verification (1 agent)
### Agent H: Full Build + Test
- ./gradlew build
- Unit test coverage cho FusionEngine
- Verify không có regression
