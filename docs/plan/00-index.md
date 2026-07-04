# Chỉ Mục Kế Hoạch AntiCheat

Bộ tài liệu này định hướng xây dựng anticheat Minecraft theo hướng:

- `Grim` làm whitebox core
- học phong cách `MLS` ở mức kiến trúc hybrid và ML ngoài luồng
- không sao chép code từ nguồn đóng hoặc giấy phép không rõ
- ưu tiên false positive thấp, khả năng mở rộng, và khả năng debug

Thứ tự đọc để dễ hiểu:

1. [01-vision-and-goals.md](D:/Duancanhan/AC/docs/plan/01-vision-and-goals.md)
2. [02-design-principles.md](D:/Duancanhan/AC/docs/plan/02-design-principles.md)
3. [03-cheat-taxonomy.md](D:/Duancanhan/AC/docs/plan/03-cheat-taxonomy.md)
4. [04-grim-capability-map.md](D:/Duancanhan/AC/docs/plan/04-grim-capability-map.md)
5. [05-hybrid-architecture.md](D:/Duancanhan/AC/docs/plan/05-hybrid-architecture.md)
6. [06-detection-matrix.md](D:/Duancanhan/AC/docs/plan/06-detection-matrix.md)
7. [07-feature-spec.md](D:/Duancanhan/AC/docs/plan/07-feature-spec.md)
8. [08-ml-system.md](D:/Duancanhan/AC/docs/plan/08-ml-system.md)
9. [09-fusion-policy.md](D:/Duancanhan/AC/docs/plan/09-fusion-policy.md)
10. [10-runtime-and-performance.md](D:/Duancanhan/AC/docs/plan/10-runtime-and-performance.md)
11. [11-rollout-and-testing.md](D:/Duancanhan/AC/docs/plan/11-rollout-and-testing.md)
12. [12-legal-and-sourcing.md](D:/Duancanhan/AC/docs/plan/12-legal-and-sourcing.md)

Nguyên tắc sử dụng:

- File nào cũng phải ưu tiên tính thực chiến hơn lý thuyết.
- Không xem ML là thứ thay thế whitebox.
- Mọi quyết định có thể auto-punish phải truy vết được nguồn gốc rõ ràng.
- MLS chỉ được dùng làm nguồn học ý tưởng kiến trúc, không xem là nguồn để sao chép code.
