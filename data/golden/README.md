# Golden Dataset — Intent Classification

Bộ dữ liệu vàng (nhãn tay) để **kiểm chứng chất lượng bước 1 (classify B1)**. Cột `intent` là **target**.

- File: `golden_intent.csv` (encoding `utf-8-sig`)
- 61 dòng, phủ đủ **5/5 label**. Nội dung `real` trích nguyên văn từ `data/sample/feedback/feedback_extracted.csv` (id `fb_<i:04d>` khớp index dòng — cùng scheme `catalog.load_feedback_index`); `crafted` là câu hỏi cách dùng canonical thêm vào để chắc coverage `how_to`.

## Cột

| Cột | Ý nghĩa |
|---|---|
| `id` | `fb_<idx>` (dòng gốc trong feedback CSV) hoặc `craft_<n>` |
| `content` | Nội dung feedback |
| `agent` | Agent/function (khoá route userguide ở B2) |
| `orig_category` | Category gốc trong feedback CSV (idea/bug/other/praise) — **để tham chiếu, KHÔNG phải target** |
| `intent` | **TARGET** — 1 trong 5 label |
| `rationale` | Lý do gán nhãn |
| `source` | `real` \| `crafted` |

## Taxonomy 5 label (không có `report_bug`)

| intent | Định nghĩa | Hành động | n |
|---|---|---|---|
| `request_feature` | Xin năng lực mới / cải thiện | roadmap: cảm ơn + sẽ cân nhắc | 15 |
| `how_to` | Câu hỏi cách dùng / khả năng (answerable từ userguide) | userguide, hướng dẫn | 11 |
| `praise` | Phản hồi tích cực | cảm ơn | 13 |
| `complaint` | Hỏng / lỗi / không hài lòng — **bug gộp vào đây** | xin lỗi + hỏi thêm | 16 |
| `unclassified` | Mơ hồ / test / lạc đề | manual review | 6 |

## Nguyên tắc gán nhãn (ranh giới hay nhầm)

- **complaint vs request_feature:** cái gì đó *đang hỏng/kém* → `complaint` ("nút copy không hoạt động"); *xin thêm cái chưa có* → `request_feature` ("có nút sao chép để copy nhanh").
- **how_to vs complaint:** *hỏi cách làm/khả năng* → `how_to` ("làm thế nào để…", "có add nhiều file không"); *báo không dùng được* → `complaint` ("lỗi không dùng được").
- **`orig_category` ≠ `intent`:** category gốc lệch nhiều với intent (vd `praise` category nhưng nội dung là câu hỏi → `how_to`). Đây chính là lý do cần golden set.
- **bug → complaint:** taxonomy này không tách `report_bug`; mọi báo lỗi/hỏng xếp `complaint` (xin lỗi + hỏi thêm).

## Dùng để đánh giá

So `intent` (target) với output classify B1. Model catalog hiện có 6 label (còn `report_bug`) ⇒ khi eval, map `report_bug → complaint` để về cùng taxonomy 5 label.
