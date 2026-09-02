---
author: klinh2212112@gmail.com
date: 2026-09-02
status: done
agents: inference.classify
summary: Bộ exemplar SINH MỚI data/sample/exemplars/intent_exemplars.csv làm source embedding-match cho B1 — độc lập hoàn toàn với feedback thật để giữ tính golden của bộ eval.
---

## Architecture reference

- Module: **Intent Catalog** (`docs/architecture.md` §3 *Trách nhiệm từng module* — `❌ Input tĩnh`). Tiêu thụ downstream: `inference.classify` (B1) — "embed feedback mới → cosine tới exemplar".
- Sections: `docs/architecture.md` §2 *Input* (Intent Catalog: `exemplar_vectors`), §4.1 *Flow A* (bước "chọn exemplar 3-5 mẫu/intent"), §4.3 *Flow C — Threshold routing* (`unclassified` = sink dưới ngưỡng, KHÔNG có exemplar), §4.5 *Data layer* (`intent_catalog.exemplar_vectors ARRAY — 3-5 mẫu thật/intent, KHÔNG phải mean`), §6.1 **R3** (exemplar thay centroid, chọn tay 3–5 mẫu/intent).
- Labeling guide: `data/golden/intent_explain.md` — định nghĩa 5 nhãn; lưu ý đầu file: **exemplar chỉ chứa mẫu DƯƠNG**, không bê cột "Không phải nhãn này khi" vào.
- Impl code: `src/03_inference/catalog.py` (`CatalogIntent.exemplars`, `DEFAULT_MAX_EXEMPLARS=5`, bỏ `unclassified` khỏi index), `src/03_inference/classify.py` (max-cosine).
- Data contract: nguồn exemplar dạng text trong git (đề xuất đã ghi CHANGELOG: exemplar lưu text thay `exemplar_vectors` — triệt R2); file này là **source để chọn/embed**, chưa phải catalog frozen.

## Problem statement

B1 classify cần exemplar để embedding-match, nhưng catalog hiện hành (`catalog_a.json`) resolve exemplar qua `supporting_feedback_ids` → **trỏ thẳng vào `feedback_extracted.csv`** — chính là 192 dòng đã trở thành bộ nhãn vàng `feedback_gold.csv`. Nếu exemplar lấy từ đó thì eval trên bộ gold bị **rò rỉ (leakage)**: feedback trong index cũng là feedback đem đo ⇒ accuracy ảo, bộ gold mất tính golden.

## Requirements (user chốt 2026-09-02)

- Sinh **mới hoàn toàn** một bộ sample làm source cho embedding match — không trích, không paraphrase từ bất kỳ feedback nào trong `feedback_extracted.csv` / `feedback_gold*.csv`.
- Tuân theo định nghĩa nhãn + tie-breaker của `data/golden/intent_explain.md`.
- Theo architecture: exemplar là mẫu DƯƠNG, phục vụ máy đo cosine của B1.

## Decisions made

- **D1 — Chỉ 4 intent có exemplar: `bug`, `new_feature`, `praise`, `complain`.** `unclassified` là sink threshold-routing (§4.3): feedback rơi vào đó vì *dưới ngưỡng*, không phải vì trúng exemplar; `catalog.load_catalog` cũng loại nó khỏi index. Sinh exemplar cho `unclassified` là sai kiến trúc.
- **D2 — 5 mẫu/intent (20 dòng), user chốt 2026-09-02** (thay bản đầu 10/intent): đúng trần 3–5 của R3 và `DEFAULT_MAX_EXEMPLARS=5` trong `catalog.py` ⇒ dùng thẳng làm exemplar khi freeze catalog, không cần bước chọn lọc trung gian. Mỗi intent 4 VI + 1 EN, phủ các pattern chính của nhãn (vd `bug`: error/nút không chạy/treo/crash/mất nội dung).
- **D3 — Exemplar viết CHUNG CHUNG (topic-neutral), neo vào tín hiệu intent thay vì chủ đề** (user chốt 2026-09-02, thay bản đầu viết theo kịch bản cụ thể): mẫu quá cụ thể (dark mode, tỉ lệ 16:9, timeout PDF…) kéo cosine lệch theo **chủ đề** — feedback mới về tính năng khác sẽ không match dù cùng intent. Bản chung chung giữ anchor ở **pattern intent**: `bug` = "báo lỗi/treo/không chạy/mất nội dung", `new_feature` = "đề xuất bổ sung/nên cho phép/xin hỗ trợ thêm", `praise` = "cảm ơn/hữu ích/hài lòng", `complain` = "chưa tốt/không như mong đợi/cần cải thiện" — không nêu tên tính năng hay kịch bản riêng. Vẫn giữ: trộn VI/EN (~3:1), độ dài từ 1 cụm từ tới 2 câu, cột `agent` phủ các agent thật (chỉ làm ngữ cảnh, không embed).
- **D4 — File tĩnh trong git, không script generator.** Nội dung là hand-authored theo guide (giống bảng `LABELS`), không có logic để tái sinh — script chỉ thêm gián tiếp. Sửa exemplar = sửa CSV qua PR (đúng nguyên tắc catalog-as-git-artifact §5).
- **D5 — Schema `id,agent,content,label`** — content là trường duy nhất được embed (khớp `CatalogIntent.exemplars`); `agent` giữ làm ngữ cảnh review + phủ đều agent; id scheme `ex_<label>_<nn>` tách hẳn namespace `fb_<idx>` để không bao giờ nhầm với feedback thật.

## Implementation approach

1. `data/sample/exemplars/intent_exemplars.csv` — 20 dòng hand-authored (5/intent × 4 intent), utf-8-sig.
2. `data/sample/exemplars/README.md` — mục đích, quy tắc sinh, ràng buộc độc lập, cách dùng.
3. Verify độc lập: đối chiếu content với 192 dòng `feedback_extracted.csv` — 0 trùng/chứa nhau thực chất (chỉ còn match giả kiểu chuỗi con tầm thường với dòng nguồn cực ngắn "GOOD"/"1"/"No"/"lỗi").
4. Cập nhật `CHANGELOG.md`.

## Non-goals

- KHÔNG wire vào `classify.py`/`catalog.py` (catalog hiện hành vẫn đọc `catalog_a.json`; chuyển source exemplar là bước riêng, đổi contract phải theo rule 3.6).
- KHÔNG sinh `exemplar_vectors` (embed thuộc bước freeze catalog — phải cùng model runtime, R2).
- KHÔNG calibrate ngưỡng (cần holdout — chính là `feedback_gold.csv`, giờ đã sạch leakage để làm việc đó).
