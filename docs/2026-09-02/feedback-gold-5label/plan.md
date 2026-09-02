---
author: klinh2212112@gmail.com
date: 2026-09-02
status: done
agents: inference.classify, unclassified_pool
summary: Bộ nhãn vàng 5-label data/golden/feedback_gold.csv — v2 gán tay lại toàn bộ 192 dòng trực tiếp từ feedback_extracted.csv theo hướng dẫn data/golden/intent_explain.md.
---

## Architecture reference

- Module: **Offline intent analysis** + **Intent Catalog** (`docs/architecture.md` §3 *Trách nhiệm từng module* — cả hai `❌ Ngoài hệ thống / Input tĩnh`). Tiêu thụ downstream: `inference.classify` (B1).
- Sections: `docs/architecture.md` §2 *Input*, §3 *Trách nhiệm từng module*, §4.1 *Flow A — Bàn giao Intent Catalog*, §4.3 *Flow C — Threshold routing*, §4.5 *Data layer* (`intent_catalog`, `unclassified_pool`)
- Impl doc: `docs/method-offline-intent-analysis.md` §6 *Kiểm định taxonomy*, §9.1 *Bộ holdout*
- Data contract: artifact tĩnh cho §9 calibrate, không phải bảng Delta mới. Khoá dòng: thứ tự dòng giữ nguyên như `feedback_gold_192.csv` ⇒ vẫn map `fb_<idx:04d>` theo `catalog.load_feedback_index`.

## Problem statement

Bộ hiện hành `data/golden/feedback_gold_192.csv` dùng taxonomy 6 label (`bug`, `request_feature`, `how_to`, `praise`, `complaint`, `unclassified`). Yêu cầu mới (user 2026-09-02): chuyển sang **5 label** — bỏ `how_to`, tập nhãn còn lại là `bug`, `new_feature`, `praise`, `complain`, `unclassified`. Điều này liên quan trực tiếp tới chẩn đoán trong `docs/2026-08-31/intent-knowledge-coupling/design.md`: `how_to` không tách được ở B1 vì sự thật phân biệt nằm trong userguide, không nằm trong feedback.

Hệ quả kéo theo:

1. 10 dòng đang mang `how_to` phải được **gán lại từng dòng** vào 1 trong 5 nhãn còn lại (không map máy móc cả nhóm về một nhãn).
2. Tên nhãn đổi theo yêu cầu: `request_feature → new_feature`, `complaint → complain`. (`bug`, `praise`, `unclassified` giữ nguyên.)

## Requirements

- Xuất file mới `data/golden/feedback_gold.csv` **song song** với `feedback_gold_192.csv` — không sửa, không xoá bộ 6-label.
- Giữ nguyên 192 dòng, đúng 5 cột `agent,user,date,content,label`, thứ tự dòng như bộ 6-label (map được `fb_<idx>`).
- Script deterministic, không gọi LLM, nhãn gán lại nằm trong bảng tay để PM review/sửa (cùng convention `scripts/relabel_feedback_gold.py`).

## Decisions made

### D1 — Taxonomy 5 label (user chốt 2026-09-02)

| label | Định nghĩa (kế thừa D1 plan 2026-08-31, đổi tên) |
|---|---|
| `bug` | Tính năng ĐÃ CÓ nhưng hỏng khi dùng: error/crash/không phản hồi/mất dữ liệu/output sai hợp đồng chức năng |
| `new_feature` | (= `request_feature` cũ) Đóng góp/cải thiện có nêu hướng cụ thể, hoặc xin năng lực chưa có |
| `praise` | Khen ngợi nói chung |
| `complain` | (= `complaint` cũ) Chê chất lượng chung chung, không nêu cải thiện, không phải malfunction |
| `unclassified` | Không mang ý nghĩa, chưa chắc chắn, HOẶC câu hỏi cách dùng/chính sách không có chỗ đứng trong 4 nhãn trên |

### D2 — Gán lại 10 dòng `how_to` theo NỘI DUNG từng dòng

Nguyên tắc: câu hỏi **xin năng lực chưa có** → `new_feature`; câu hỏi kèm **bức xúc/chê**, không nêu cải thiện → `complain`; câu hỏi thuần cách dùng/chính sách (không suy được intent sản phẩm) → `unclassified` (sink cho PM, đúng vai `unclassified_pool` §4.3).

| id | content (tóm tắt) | how_to → | Lý do |
|---|---|---|---|
| `fb_0007` | "Tại sao cứ báo tôi bị hết hạn mức không sử dụng được" | `complain` | Bức xúc vì bị hạn mức chặn sử dụng — phàn nàn, không nêu cải thiện, không xác nhận được malfunction |
| `fb_0013` | "STT của slide không nhảy theo… tôi cần làm gì" | `unclassified` | Hỏi thao tác trên file sau khi export (ngoài hợp đồng chức năng sản phẩm) — câu hỏi cách dùng thuần |
| `fb_0017` | "Searching for previous chats is very limited. Is this keyword match…?" | `complain` | Mở đầu bằng chê "very limited", không nêu hướng cải thiện cụ thể |
| `fb_0018` | "Tài có thể tạo format dựa trên dữ liệu file excel có sẵn đưa vào ko" | `new_feature` | Xin năng lực nhận input excel — cùng họ `fb_0014`/`fb_0041`/`fb_0057` (đều `new_feature`) |
| `fb_0032` | "có giao diện tiếng việt không ạ?" | `new_feature` | Xin giao diện tiếng Việt — cùng họ `fb_0107` "Cần phiên bản tiếng việt" (`new_feature`) |
| `fb_0059` | "I don't see my past ppt presentation here" | `new_feature` | Chưa có nơi lưu/lịch sử sản phẩm đã tạo — cùng họ `fb_0008`/`fb_0153` (`new_feature`) |
| `fb_0074` | "Có add được nhiều file tham khảo không nhỉ?" | `new_feature` | Xin upload nhiều file — cùng họ `fb_0057` (`new_feature`) |
| `fb_0085` | "up chứng từ lên… có bị tính vi phạm an ninh thông tin không?" | `unclassified` | Câu hỏi chính sách/compliance, không phải feedback về sản phẩm |
| `fb_0131` | "làm sao tôi biết được bạn đang dịch đúng" | `unclassified` | Nghi vấn về độ tin cậy, không xin năng lực cụ thể, không chê cụ thể |
| `fb_0146` | "Có thể kết hợp powerpointer với translator được không?" | `new_feature` | Xin năng lực phối hợp 2 agent — chưa tồn tại |

Phân bố sau gán lại: `bug` 49 · `new_feature` 43 (38+5) · `praise` 19 · `complain` 16 (14+2) · `unclassified` 65 (62+3). Tổng 192.

### D3 — Đổi tên nhãn là RENAME thuần, không đổi phán đoán

`request_feature → new_feature` và `complaint → complain` áp cho toàn bộ dòng còn lại; nội dung phán đoán của bộ 6-label giữ nguyên. Lệch tên với các artifact khác (`catalog_a.json` dùng `report_bug`/`request_feature`) ghi nhận ở CHANGELOG — khi eval catalog cũ map `report_bug → bug`, `request_feature → new_feature`, `complaint → complain`.

### D4 — Nguồn đọc là `feedback_gold_192.csv`, không phải CSV gốc

Bộ 6-label đã là ground truth được review; script 5-label chỉ transform trên nó (rename + 10 dòng gán lại) ⇒ mọi sửa đổi tương lai ở bộ 6-label chạy lại script là lan sang bộ 5-label. `feedback_gold_192.csv` giữ nguyên làm bộ tham chiếu 6-label (cùng cách `golden_intent.csv` được giữ làm legacy).

## Implementation approach

1. `scripts/make_feedback_gold_5label.py` — deterministic, không LLM:
   - đọc `data/golden/feedback_gold_192.csv` (utf-8-sig), index dòng = `fb_<idx>`
   - `RENAME`: `request_feature → new_feature`, `complaint → complain`
   - `HOW_TO_RELABEL`: bảng tay `idx → (label mới, rationale)` cho đúng 10 dòng D2
   - assert: 192 dòng, không còn `how_to`, mọi label ∈ 5 nhãn, đủ 10 dòng how_to được gán lại
   - xuất `data/golden/feedback_gold.csv` đúng 5 cột; in phân bố nhãn + danh sách 10 dòng gán lại
2. Cập nhật `data/golden/README.md`: bộ 5-label thành hiện hành, quan hệ 3 file gold.
3. Cập nhật `CHANGELOG.md`.

## Revision v2 — 2026-09-02 (gán lại toàn bộ theo `intent_explain.md`)

**Trigger:** PM review bản v1 và chỉ ra hai lỗi hệ thống, đều thừa kế từ rule D3 của plan 2026-08-31:

1. Rule "truncated → `unclassified`" quá tay: *"There must be a clear indicator when a person is out of credits...."* bị regex đuôi `...` ép về `unclassified` dù phần nhìn thấy đã trọn ý (rõ ràng là `new_feature`).
2. Rule "quá ngắn → `unclassified`" bỏ qua tín hiệu thực: *"lỗi"* tuy 1 từ nhưng không mơ hồ — user báo app lỗi ⇒ `bug`.

PM đã chốt hướng dẫn gán nhãn mới tại **`data/golden/intent_explain.md`** — đây là nguồn chuẩn thay cho bảng D1/D2 v1 ở trên.

### Quyết định v2

- **D1v2 — Nguồn đọc là `data/sample/feedback/feedback_extracted.csv`** (yêu cầu PM: feedback phải được lấy đầy đủ từ file golden gốc), không derive từ `feedback_gold_192.csv` nữa. Content copy nguyên văn, thứ tự dòng giữ nguyên ⇒ `fb_<idx:04d>` không đổi.
- **D2v2 — Gán tay TOÀN BỘ 192 dòng theo `intent_explain.md`**, dùng tie-breaker theo cặp trong đó:
  - `bug` vs `new_feature`: app hành xử sai thiết kế ⇒ `bug`; đúng thiết kế nhưng user muốn khác ⇒ `new_feature`.
  - `new_feature` vs `complain`: rút được một dòng backlog ⇒ `new_feature`.
  - vs `unclassified`: "sau khi đọc có dám soạn reply không?".
- **D3v2 — Dòng bị cắt cụt (`…`/`...`) KHÔNG tự động `unclassified`.** Gán theo phần nhìn thấy khi ý đã được phát biểu trọn (không suy diễn phần thiếu); chỉ giữ `unclassified` khi phần quyết định nằm đúng chỗ bị cắt (vd `fb_0182` "nên bổ sung tính năng sau:…", `fb_0169` "chưa dùng được vì …").
- **D4v2 — Câu ngắn tín hiệu rõ gán theo tín hiệu**: "lỗi" / "coundn't acess" ⇒ `bug`. `unclassified` chỉ còn cho: prompt gõ nhầm ô feedback, nội dung thật sự vô nghĩa ("1", "uew", "Test feedback", "No"), câu hỏi chính sách không phải feedback sản phẩm, và dòng mất phần quyết định.
- **D5v2 — Không còn how_to**: câu hỏi năng lực ⇒ `new_feature`; câu hỏi kèm bức xúc ⇒ `complain` (vd `fb_0007` hạn mức — ví dụ chốt trong `intent_explain.md`); câu hỏi chính sách/không suy được intent ⇒ `unclassified`.

### Phân bố v2 (192 dòng)

| label | n | % | v1 |
|---|---:|---:|---:|
| `new_feature` | 65 | 33.9% | 43 |
| `bug` | 62 | 32.3% | 49 |
| `unclassified` | 29 | 15.1% | 65 |
| `praise` | 20 | 10.4% | 19 |
| `complain` | 16 | 8.3% | 16 |

`unclassified` giảm 65 → 29 chủ yếu do bỏ rule truncated (36 dòng cắt cụt được gán theo phần nhìn thấy).

### Hiện thực v2

`scripts/make_feedback_gold_5label.py` viết lại: đọc `feedback_extracted.csv`, bảng tay `LABELS` đủ 192 entry `idx → (label, rationale)` để PM review/sửa từng dòng, assert đủ dòng + đúng tập nhãn, xuất `data/golden/feedback_gold.csv` 5 cột như cũ, in phân bố + danh sách `unclassified`.

## Non-goals

- KHÔNG sửa/xoá `feedback_gold_192.csv`, `golden_intent.csv`, `scripts/relabel_feedback_gold.py`.
- KHÔNG regen `catalog_a.json`, KHÔNG đổi code B1/B2 theo taxonomy mới (làm sau khi chốt hướng ở `intent-knowledge-coupling/design.md`).
- KHÔNG calibrate ngưỡng.
