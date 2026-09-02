# Intent Exemplars — source cho embedding match (B1)

> Thư mục có 2 file: `intent_exemplars.csv` (POSITIVE — mô tả dưới đây; hiện là bản v2:
> complain viết lại + 10 mẫu/nhãn + trộn register khẩu ngữ) và
> `intent_exemplar_negatives.csv` (NEGATIVE cho contrastive scoring — `label` là intent
> BỊ TRỪ điểm khi feedback gần câu đó: `score = max_cos(pos) − λ·max_cos(neg)`, λ=0.3.
> Đây là cách hợp lệ đưa cột "Không phải nhãn này khi" của `intent_explain.md` vào hệ
> thống — tách khỏi index dương. Plan: `docs/2026-09-03/contrastive-negative-scoring/plan.md`.
> Cả hai file đều phải độc lập với gold — leakage guard trong test phủ cả hai.)

`intent_exemplars.csv` — **20 mẫu SINH MỚI** (5/intent × 4 intent, khớp trần R3 và `DEFAULT_MAX_EXEMPLARS=5`) làm nguồn exemplar cho
`inference.classify` (B1): embed feedback mới → **max cosine tới exemplar** → intent + confidence
(`docs/architecture.md` §4.3, §6.1 R3). Plan: `docs/2026-09-02/inference-exemplar-samples/plan.md`.

## Vì sao phải sinh mới

Catalog hiện hành (`catalog_a.json`) resolve exemplar qua `supporting_feedback_ids` → trỏ vào
`data/sample/feedback/feedback_extracted.csv` — chính là 192 dòng đã thành nhãn vàng
`data/golden/feedback_gold.csv`. Exemplar lấy từ đó ⇒ eval trên bộ gold bị **leakage** (feedback
trong index cũng là feedback đem đo). Bộ này độc lập hoàn toàn (0 dòng trùng hoặc chứa nhau với
nguồn — câu chữ đều mới) ⇒ bộ gold giữ nguyên vai trò holdout.

## Quy tắc đã theo (chốt 2026-09-02)

- **Định nghĩa nhãn**: `data/golden/intent_explain.md`. Chỉ mẫu **DƯƠNG** — không đưa
  "Không phải nhãn này khi" vào exemplar (lưu ý đầu file guide: index coi mọi exemplar là mẫu dương).
- **KHÔNG có exemplar cho `unclassified`** — nó là *sink* threshold-routing (§4.3): feedback rơi
  vào đó vì dưới ngưỡng, không phải vì trúng exemplar. `catalog.load_catalog` cũng loại nó khỏi index.
- **Viết CHUNG CHUNG (topic-neutral), neo vào tín hiệu intent thay vì chủ đề**: không nêu tên
  tính năng/kịch bản cụ thể — mẫu quá cụ thể kéo cosine lệch theo chủ đề, feedback mới về tính
  năng khác sẽ không match dù cùng intent. Anchor nằm ở pattern: `bug` = "báo lỗi/treo/không
  chạy/mất nội dung", `new_feature` = "đề xuất bổ sung/nên cho phép/xin hỗ trợ thêm",
  `praise` = "cảm ơn/hữu ích/hài lòng", `complain` = "chưa tốt/không như mong đợi/cần cải thiện".
- **Cùng miền bề mặt với input production**: VI/EN trộn ~3:1, độ dài từ 1 cụm từ tới 2 câu,
  cột `agent` phủ các agent thật (chỉ ngữ cảnh review, không embed).

## Schema

| Cột | Ý nghĩa |
|---|---|
| `id` | `ex_<label>_<nn>` — namespace tách hẳn `fb_<idx>` của feedback thật |
| `agent` | Agent giả định (ngữ cảnh review, phủ đều agent) — **không embed** |
| `content` | Text exemplar — trường DUY NHẤT đi vào embedding |
| `label` | 1 trong 4: `bug` / `new_feature` / `praise` / `complain` |

## Cách dùng

- **Freeze catalog** (Flow A §4.1): dùng thẳng 5 mẫu/intent làm exemplar (R3: `exemplar_vectors`
  là 3–5 mẫu, KHÔNG phải mean) → embed bằng đúng model runtime
  (`qwen3-embedding-0-6b`, R2) → calibrate ngưỡng trên holdout = `data/golden/feedback_gold.csv`.
- Sửa/thêm exemplar = sửa CSV qua PR (catalog-as-git-artifact, §5). Chưa wire vào
  `classify.py` — chuyển source exemplar là bước riêng (đổi contract theo rule 3.6).
