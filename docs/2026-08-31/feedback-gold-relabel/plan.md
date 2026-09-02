---
author: klinh2212112@gmail.com
date: 2026-08-31
status: done
agents: inference.classify, unclassified_pool
summary: Review & gán lại nhãn vàng 6-label cho data/sample/feedback/feedback_extracted.csv — cột `category` gốc là nhãn user-widget nhiễu, không dùng làm ground truth được.
---

## Architecture reference

- Module: **Offline intent analysis** + **Intent Catalog** (`docs/architecture.md` §3 *Trách nhiệm từng module* — dòng "Offline intent analysis" và "Intent Catalog", cả hai `❌ Ngoài hệ thống / Input tĩnh`). Tiêu thụ downstream: `inference.classify` (B1).
- Sections: `docs/architecture.md` §2 *Input* (bảng nguồn — Feedback datalake `feedback_id/content/agent/created_at`), §3 *Trách nhiệm từng module*, §4.1 *Flow A — Bàn giao Intent Catalog*, §4.3 *Flow C — Threshold routing*, §4.5 *Data layer* (`intent_catalog`, `unclassified_pool`)
- Impl doc: `docs/method-offline-intent-analysis.md` §2.1 *Data audit*, §2.2 *Tiền xử lý*, §6 *Kiểm định taxonomy*, §9.1 *Bộ holdout*, §10 *Freeze — schema catalog*
- Data contract: `intent_catalog.intent_id` / `.label` (§4.5). Artifact sinh ra ở đây là **input cho §9 calibrate ngưỡng**, không phải bảng Delta mới. Khoá dòng: `fb_<idx:04d>` — cùng scheme `catalog.load_feedback_index`.

## Problem statement

Bước 1 (intent classification bằng embedding) cho kết quả kém. Audit dữ liệu cho thấy nguyên nhân gốc **không nằm ở embedding** mà ở tập nhãn:

1. **`category` trong `feedback_extracted.csv` không phải nhãn vàng.** Nó là lựa chọn của user trên widget feedback, chỉ có 4 giá trị (`idea` 96, `bug` 54, `other` 25, `praise` 17) và lệch nặng so với nội dung. Ví dụ đã kiểm chứng:
   - `fb_0002` "TAI studio ko work, input file nhưng ko gen ra slide" → widget ghi `idea`, thực chất `bug`
   - `fb_0152` "Chữ và icon trên màn hình quá nhỏ các sếp ơi" → widget ghi `praise`, thực chất `request_feature`
   - `fb_0146` "Có thể kết hợp powerpointer với translator được không?" → widget ghi `praise`, thực chất `how_to`
   - `fb_0122` "thống kê tuyến đường vi mô team phạm hương" → widget ghi `praise`, thực chất là prompt gõ nhầm ô ⇒ `unclassified`
   Đo embedding với tập nhãn này thì mọi metric đều vô nghĩa (§ method `docs/method-offline-intent-analysis.md` §2.1 yêu cầu audit trước khi tin số liệu).
2. **~23% dòng bị cắt cụt.** 44/192 dòng kết thúc bằng `…` do được extract từ ảnh chụp màn hình (`data/sample/feedback/image*.png`), mất phần đuôi mang thông tin quyết định nhãn.
3. **Nhiễu prompt-misfire.** Nhiều dòng là câu lệnh user gõ nhầm vào ô feedback (`fb_0064` "Tôi muốn gộp ba target vào 1 bảng…", `fb_0092` "Bạn có thể so sánh với Đạm Phú Mỹ không?"), không phải feedback về sản phẩm.
4. **Taxonomy lệch tên giữa các artifact.** `src/01_intent_classification/out/*/catalog_a.json` dùng `report_bug`; `data/golden/golden_intent.csv` (61 dòng) lại bỏ hẳn bug, gộp vào `complaint` (5 label). Yêu cầu hiện tại là **6 label có `bug` tách riêng**. Ba nguồn ba taxonomy ⇒ eval không so được.

## Requirements

- Gán lại toàn bộ 192 dòng theo đúng 6 label: `request_feature`, `how_to`, `bug`, `praise`, `complaint`, `unclassified`.
- Giữ nguyên file gốc `feedback_extracted.csv` (không phá dữ liệu nguồn); xuất artifact mới.
- Mỗi dòng có `rationale` ngắn để PM review lại được (§ method §7 *Review gate*).
- Giữ `category` gốc trong artifact dưới tên `source_category` — để tham chiếu, **KHÔNG** phải target.
- Thống nhất tên nhãn cho `catalog_a.json` (`report_bug`) và `golden_intent.csv` (5 label) về 6 label mới.

## Decisions made

### D1 — Định nghĩa 6 label (chốt với user 2026-08-31)

| label | Định nghĩa | Ranh giới |
|---|---|---|
| `bug` | Tính năng ĐÃ CÓ nhưng **hỏng khi dùng**: error/crash/không phản hồi/mất dữ liệu/output sai lệch so với hợp đồng chức năng | "Translation request failed (502)", "nút copy không hoạt động", "lỗi font khi export" |
| `request_feature` | Đóng góp/cải thiện — **có nêu hướng cải thiện cụ thể** hoặc xin năng lực chưa có | "bổ sung hình ảnh cho slide đẹp hơn", "TĂNG FONT SIZE LÊN" |
| `how_to` | Hỏi về tính năng **đã có** mà user chưa biết dùng | "Có add được nhiều file tham khảo không nhỉ?" |
| `praise` | Khen ngợi nói chung | "tuyệt vời", "Very good result" |
| `complaint` | Phàn nàn nói chung — **chê chất lượng, không nêu cải thiện, không phải malfunction** | "Slide tạo chưa đẹp", "dịch quá tệ", "càng làm càng xấu" |
| `unclassified` | Không mang ý nghĩa hoặc chưa chắc chắn | "1", "uew", "Test feedback" |

### D2 — Ranh giới "chê chất lượng output của AI" (nhóm ~45 dòng, quyết định lớn nhất)
Chọn **theo hành động** (user chốt):
- Nêu hướng cải thiện cụ thể ⇒ `request_feature`
- Chê chung chung, không nói cải thiện gì ⇒ `complaint`
- `bug` **chỉ** dành cho malfunction kỹ thuật thật (error, không chạy, crash, mất data, dịch sót/bịa nội dung)

Lý do: `request_feature` và `bug` là hai `action_type` khác nhau ở B2 (`known_gap` tra backlog vs roadmap) — trộn chúng làm hỏng nhánh reply. `complaint` là nhánh không có action, xin lỗi + hỏi thêm.

### D3 — Dữ liệu bẩn ⇒ `unclassified` (user chốt)
- 44 dòng kết thúc bằng `…`/`...` (truncation khi extract từ ảnh) ⇒ `unclassified`, `review_flag=truncated`
- 11 dòng prompt gõ nhầm ô feedback ⇒ `unclassified`, `review_flag=prompt_misfire`
- 7 dòng vô nghĩa/quá ngắn ⇒ `unclassified`, `review_flag=meaningless`

Đánh đổi đã nêu với user: `unclassified` phình lên ~32%. **Đây là con số của tập mẫu bẩn, KHÔNG phải prior cho `unclassified_rate` production** (`docs/method-offline-intent-analysis.md` §4.5 đã cảnh báo đúng nhầm lẫn này). Cách gỡ: lấy lại nội dung đầy đủ từ nguồn Delta thay vì OCR ảnh ⇒ ~44 dòng này quay về nhãn thật.

### D4 — Tên nhãn: `bug`, KHÔNG phải `report_bug`
Theo yêu cầu user. `catalog_a.json` hiện dùng `report_bug` ⇒ cần map `report_bug → bug` khi eval, hoặc rename ở lần regen catalog kế tiếp. Ghi vào CHANGELOG.

### D5 — Không sửa file gốc
`feedback_extracted.csv` giữ nguyên (nó là fixture của nguồn). Artifact mới: `data/golden/feedback_gold_192.csv`. `data/golden/golden_intent.csv` (61 dòng, 5 label) trở thành **legacy** — được đối chiếu để phát hiện xung đột, không xoá.

## Implementation approach

1. `scripts/relabel_feedback_gold.py` — script tái lập được (deterministic, không gọi LLM):
   - đọc `data/sample/feedback/feedback_extracted.csv` (utf-8-sig)
   - `LABELS`: bảng tay `idx → (label, rationale)` cho 130 dòng nội dung sạch
   - phát hiện tự động: `truncated` (regex đuôi `…|...`), `prompt_misfire` + `meaningless` (danh sách index chốt tay)
   - assert: đủ 192 dòng, mọi label ∈ 6 nhãn, không dòng nào thiếu nhãn
   - xuất `data/golden/feedback_gold_192.csv` **đúng 5 cột**: `agent, user, date, content, label` (user chốt 2026-08-31 — bỏ `id`/`source_category`/`review_flag`/`rationale` khỏi CSV cho gọn; thứ tự dòng giữ nguyên nên vẫn map được về `fb_<idx>`)
   - in báo cáo ra màn hình (không ghi file): phân bố nhãn, danh sách 62 id cần loại khi train/eval, ma trận `category widget × label`, xung đột với `golden_intent.csv`
2. Cập nhật `data/golden/README.md`: taxonomy 6 label, quan hệ giữa 2 file gold, quy tắc map `report_bug → bug`, và cách lấy lại 62 id bẩn (chạy script).
3. Cập nhật `CHANGELOG.md`.

## Non-goals

- KHÔNG chạy lại clustering/embedding, KHÔNG regen `catalog_a.json` (thuộc Phase 0, chạy sau khi có nhãn vàng).
- KHÔNG calibrate ngưỡng (§9 method) — cần bộ holdout riêng, làm ở bước sau.
- KHÔNG đụng `intent_catalog` Delta hay bất kỳ module trong Databricks Job.
