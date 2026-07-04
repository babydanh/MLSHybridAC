# Pháp Lý Và Nguồn Gốc

## Mục đích

File này đặt ra ranh giới rõ ràng về nguồn code và cách học ý tưởng.

## Grim

- Dùng Grim làm upstream whitebox core.
- Khi sửa đổi, phải theo dõi thay đổi để merge hoặc fork có kỷ luật.
- Cần ghi rõ phạm vi code giữ nguyên và code tự viết thêm.

## Cảm hứng từ MLS

MLS được dùng làm nguồn học ở mức:

- plugin mỏng
- backend inference riêng
- ý tưởng cross-server và dashboard
- phân tách game-thread và analysis layer

Không được:

- sao chép code nếu không chấp nhận hệ quả license
- đưa ra khẳng định không chứng minh được về model hoặc dataset closed backend

## BakiVF

Từ local source đã xem, BakiVF có nhiều ý tưởng hữu ích:

- remote inference client
- feature extraction
- async ML pipeline
- fusion-like AI layer

Tuy nhiên:

- license không rõ ràng trong nguồn đã xem
- không nên copy code trực tiếp
- chỉ nên học ý tưởng kiến trúc và tự viết lại

## Nguyên tắc sourcing

- học ý tưởng, không copy implementation
- file plan và code mới phải ghi rõ ý tưởng nào đến từ upstream nào
- nếu một thành phần cần dựa trên code GPL thì phải đánh giá hệ quả cho toàn bộ dự án

## Nguyên tắc phát biểu trong tài liệu

Phần nào xác nhận được từ source thì ghi là fact.
Phần nào là suy luận thì ghi là inference.
Không viết marketing claims khi chưa có benchmark hoặc dữ liệu production.
