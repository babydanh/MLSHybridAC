# Nguyên Tắc Thiết Kế

## Nguyên tắc cốt lõi

### Whitebox nắm sự thật

Nếu hành vi vi phạm vật lý vanilla, packet ordering, world collision, reach geometry hoặc server-authoritative state, thì whitebox phải là lớp quyết định chính.

### Blackbox nắm nghi vấn

Nếu hành vi không thể kết luận bằng công thức tuyệt đối mà chỉ là "giống cheat", thì blackbox chỉ được phép sinh risk, không được tự ý thay thế truth.

### Fusion nắm leo thang

Risk từ nhiều nguồn phải đi qua một lớp fusion tập trung. Không để từng model tự ban hành punishment riêng.

### Ưu tiên false positive thấp

Hệ thống sẽ thất bại nếu nó bắt nhầm người chơi giỏi. Ưu tiên chống false positive trước khi theo đuổi recall tối đa.

### Chỉ async cho phân tích nặng

ML, FFT, sequence analysis, graph analysis hoặc cross-session profiling không được block game thread.

### Khả năng giải thích quan trọng hơn hào nhoáng

Mỗi layer mới phải để lại audit trail:

- lý do flag
- feature nào tăng risk
- whitebox check nào corroborate
- confidence ở mức nào

### Rollout tăng dần

Mỗi detector mới phải qua 4 mức:

1. observe
2. alert
3. soft-mitigate
4. enforce

## Nguyên tắc cho plan

- Mỗi cheat family phải có owner layer rõ ràng.
- Mỗi feature phải có lý do tồn tại.
- Mỗi cơ chế punish phải có rollback.
- Mỗi thành phần học từ MLS hoặc BakiVF phải được chuyển hóa thành ý tưởng, không bê nguyên code.
