---
author: klinh2212112@gmail.com
date: 2026-09-03
status: done
agents: inference.draft, ingest-sync
summary: B2 bước 1 (§4.4) — xử lý theo lô feedback bug/new_feature đã classify, đối chiếu guideline (data/guidelines) để quyết định `solved` + trích `referenced` nguyên văn; gold `solved` gán tay 127 dòng; mục tiêu F1 ≥ 0.70, ưu tiên precision.
---

## Architecture reference

- Module: **`inference.draft` (B2)** — nửa RESOLVE của bước 1 chuỗi §4.4 (guideline). Phần loader guideline từ `.docx` thuộc **`ingest-sync` (Job A)** — nguồn offline thay Confluence cho dev/eval.
- Sections: `docs/architecture.md` §3 *Trách nhiệm từng module* (B2: "bug/new_feature gom theo agent, nạp nguyên văn guideline"), §4.2 *Flow B* (gom theo `agent` → 1 call/agent), **§4.4 Flow D bước 1** (hỏi "tính năng đã tồn tại chưa, ở đâu"; cổng an toàn `source_ref` phân giải ngược được), §4.6 Data layer (`userguide_page(agent PK, page_id, version, title, markdown)`, `feedback_processing.scenario/source_ref`), §5 (LLM Haiku 4.5 qua AI-Gateway — dev thay bằng qwen3-8b local; Test: pytest + mock LLM), §6.1 R6 (tài liệu cũ hơn feedback), R9 (token budget), §6.3 bước 6 ("đo chuỗi §4.4 trên tập gold trước khi bật").
- Impl doc: `docs/impl-phase2-auto-feedback-flow.md` §3.2 (không có hit đạt ngưỡng ⇒ `we_listen`, không được claim), §5 (B2 nhánh knowledge).
- Kế thừa: `docs/2026-08-27/knowledge-layer-batch/plan.md` (whole-content → LLM theo lô, `answerable` gate), `docs/2026-08-31/intent-knowledge-coupling/design.md` (sự thật nằm trong userguide; audit 11 dòng: 5 sai / 5 đúng), `docs/2026-09-03/experiment-tracking-lite/plan.md` (mỗi phương án = 1 function, mỗi run 1 folder).
- Data contract: input = output B1 (`agent, content, label ∈ {bug,new_feature}` + `id`); knowledge = `userguide_page` (dựng từ `data/guidelines/*.docx`, `page_id = docx:<slug>`, `version = "Last updated"` trong file hoặc hash nội dung); output thêm **đúng 2 cột** `solved` (bool) + `referenced` (text, optional). `source_ref` (`page_id@version#heading`) và lý do ghi ở sidecar debug, không đưa vào CSV output theo yêu cầu PM. Không đổi contract §4.6.
- Non-goal (giữ đúng ranh giới): KHÔNG làm bước 2 backlog, KHÔNG changelog (chưa có nguồn), KHÔNG render email/B3, KHÔNG chunk/embed/index tài liệu (nguyên tắc v4.0 whole-content) — embedding chỉ được dùng nếu một phương án thí nghiệm cần *tiền lọc section* và phải ghi rõ là lệch nguyên tắc để PM chốt.

## Problem statement

B1 đã gán nhãn. Với `bug` / `new_feature`, câu trả lời phụ thuộc một sự thật nằm trong tài liệu: *thứ user cần đã có chưa?* (§4.4). Cần một script batch nhận CSV sau B1, gom theo `agent`, nạp nguyên văn guideline của agent đó vào LLM, và trả về cho mỗi feedback:

- `solved = True` **chỉ khi** guideline cho thấy nhu cầu đã được đáp ứng: tính năng đã tồn tại / có hướng dẫn thao tác / có workaround đạt đúng mục tiêu user. Kèm `referenced` = **đoạn nguyên văn** trong tài liệu (để B2 dựng kịch bản "hướng dẫn" + citation).
- `solved = False` khi tài liệu không nói gì, hoặc chỉ ghi nhận đó là *limitation* không có workaround (⇒ rơi xuống bước 2 backlog theo §4.4). `referenced` có thể chứa câu limitation (optional) để PM thấy tài liệu đã biết gap này.

Sai kiểu "nói đã có về thứ chưa có" đắt hơn sai kiểu "bỏ sót" (§4.4) ⇒ **precision ưu tiên hơn recall**. Ngưỡng nghiệm thu PM: **F1(solved=True) ≥ 0.70**.

Chặn cứng: golden hiện (`feedback_gold.csv`) chỉ có nhãn intent, **chưa có nhãn `solved`** ⇒ phải gán gold trước khi đo.

## Requirements

1. Script `python src/03_inference/resolve_guideline.py --in <csv> --out <csv>` — lọc `label ∈ {bug,new_feature}`, gom theo `agent`, K feedback/call, ghi CSV output = input + `solved` + `referenced`; sidecar `<out>.debug.jsonl` (source_ref, heading, match_type, reason, raw LLM).
2. `--eval` chạy trên gold, in P/R/F1 của `solved=True`, tỉ lệ `referenced` verbatim, tỉ lệ trùng heading với gold.
3. LLM qwen3-8b qua LM Studio (`http://localhost:1234/v1`, OpenAI-compatible), temperature 0, hàm `chat_json` inject được để test offline.
4. Cổng an toàn (§4.4): `referenced` do LLM trả **phải tìm được nguyên văn** (chuẩn hoá khoảng trắng/case) trong page của agent; không tìm được ⇒ `solved=False`, `referenced=""`. `solved=True` mà không có quote ⇒ hạ về False.
5. Test offline (`src/04_tests/test_resolve_guideline.py`): loader docx (13 page, map agent), gate quote, batch align theo index, canvas-designer (không tài liệu) luôn False.
6. Hồ sơ thí nghiệm: `src/05_experiments/run_resolve_experiment.py` + `runs_resolve/index.md`; dừng sau 3 lần thử không cải thiện, chốt phương án tốt nhất.

## Decisions made

- **D1 — Định nghĩa `solved` (gold + model dùng chung).** `True` ⇔ guideline cho thấy nhu cầu đã được đáp ứng (feature tồn tại / how-to / workaround đạt mục tiêu). Limitation không workaround ⇒ `False` (`match_type=limitation`, quote optional). Tài liệu im lặng ⇒ `False` (`match_type=none`). Bug kỹ thuật (crash, 502, network error, font vỡ) ⇒ `False` trừ khi tài liệu ghi đúng hành vi đó là *by design* kèm cách làm đúng.
- **D2 — Gold `solved`: `data/golden/feedback_gold_solved.csv`** — 127 dòng `bug`/`new_feature` của `feedback_gold.csv` (id giữ `fb_<i:04d>`), cột `id, agent, label, content, solved, match_type, referenced, rationale`. Gán bởi **2 labeler độc lập** (đọc cùng bản dump markdown của 13 docx) + **adjudication** dòng bất đồng bởi PM-proxy (ghi lý do). Kappa giữa 2 labeler ghi vào Results. Nhãn intent giữ nguyên từ gold — không sửa lại intent trong scope này (dù coupling design đã chỉ ra 5/11 dòng lệch).
- **D3 — Map agent → tài liệu viết tay** (coupling design §2.1: fuzzy hỏng ở `tai`/`tai-studio`): `tai` → *TÀI (Super Agent)* + *TÀI Studio — User guide* + **GenUI** (bổ sung khi adjudicate gold: GenUI mô tả chính giao diện chat của TÀI — token meter, toggle EN/VI, @mention; 4 dòng `tai` có câu trả lời ở đó) + *Office 365*; `tai-studio` → *TÀI Studio — User guide* + *GenUI*; agent còn lại → `slugify(title)` như `userguide_store.py`; `the-canvas-designer` → không có ⇒ luôn `False`.
- **D4 — Loader docx** (`src/02_knowledge/guideline_docx.py`, module ingest-sync): docx → markdown giữ heading (`#`/`##`/`###`), bảng → hàng `|`; `version` = dòng "Last updated: …" nếu có, không thì hash nội dung. Ra `UserguidePages` (tái dùng contract `userguide_page`) + lưu `out/guideline_store.json`. Đây là **nguồn offline cho dev/eval**; production vẫn Confluence qua MCP (§5).
- **D5 — LLM dev = qwen3-8b LM Studio, no-think mặc định** (`/no_think`, temperature 0); Haiku 4.5 (§5) là target production — prompt viết model-agnostic, JSON schema chặt.
- **D6 — Gate quote verbatim** thay cho `page_id@version` đơn thuần: `source_ref` tự dựng từ page + heading chứa quote — LLM không được tự đặt `source_ref`. Đây là hiện thực cụ thể của "chỉ tin cái khoá tra ngược được" (§4.4).
- **D7 — Metric chính = F1 trên lớp `solved=True`**, báo kèm precision/recall, confusion 2×2, `quote_verbatim_rate`, `heading_match_rate` (dự đoán True đúng + heading trùng gold). Điều kiện dừng: 3 phương án liên tiếp không tăng F1 ⇒ dừng, chốt phương án F1 cao nhất (hòa ⇒ precision cao hơn thắng).

## Implementation approach

1. `guideline_docx.py`: `load_guidelines(dir) -> UserguidePages`, `dump_markdown(dir, out_md)`; CLI `--dump` cho labeler đọc.
2. Gold: dump markdown → 2 labeler độc lập → merge + adjudicate → `feedback_gold_solved.csv` + README cập nhật.
3. `resolve_guideline.py`: `Resolution` dataclass; `resolve_batch(feedbacks, pages, llm, batch_size)`; `verify_quote(quote, page) -> (ok, heading)`; `evaluate_gold()`; CLI.
4. Test offline với fake LLM.
5. Thí nghiệm (mỗi cái 1 function trong `run_resolve_experiment.py`):
   - `A0 whole_page_nothink`: baseline whole-page, K=10/call, no-think.
   - `A1 whole_page_think`: bật reasoning Qwen3 (chậm hơn, kỳ vọng precision tăng).
   - `A2 two_pass_verify`: A-tốt-nhất + lượt 2 hỏi lại từng dòng `solved=True` ("quote này có thực sự giải quyết feedback không?") — tăng precision.
   - `A3 per_item`: 1 feedback/call (mất batch, đo xem batch có làm giảm chất lượng không).
   Dừng theo D7.
6. CHANGELOG + Results ghi vào plan này.

## Acceptance

| # | Tiêu chí | Kiểm |
|---|---|---|
| G-1 | Loader dựng 13 page, mọi agent trong gold (trừ canvas-designer) map được | pytest |
| G-2 | Quote không có trong page ⇒ `solved=False`, `referenced=""` | pytest (fake LLM bịa quote) |
| G-3 | Output CSV = input + đúng 2 cột, thứ tự dòng giữ nguyên | pytest |
| G-4 | F1(solved=True) ≥ 0.70 trên `feedback_gold_solved.csv`, precision ≥ recall | run hồ sơ |
| G-5 | Mọi `referenced` của dòng `solved=True` là verbatim trong tài liệu | metric `quote_verbatim_rate = 1.0` |

## Results (2026-09-03, qwen3-8b @ LM Studio, gold 127 dòng / 12 dương)

### Gold `solved`
2 labeler độc lập → **kappa(solved) = 0.89**, bất đồng 5/127; adjudication 9 dòng (5 bất đồng + 4 dòng `tai` đổi do mở rộng map thêm GenUI). Kết quả: **12 True / 22 limitation / 93 none**. Lớp dương chỉ 12 ⇒ **mỗi dòng ≈ 8 điểm F1** — con số dưới đây có sai số lớn, đọc kèm tp/fp/fn.

### Thí nghiệm (`src/05_experiments/runs_resolve/index.md`)

| # | approach | P | R | F1 | tp/fp/fn | thời gian |
|---|---|---:|---:|---:|---|---|
| A0 | whole_page_nothink (baseline) | 0.50 | 0.17 | 0.25 | 2/2/10 | 95s |
| A1 | whole_page_think | 0.80 | 0.33 | 0.47 | 4/1/8 | 254s |
| A6 | evidence_nothink | 0.56 | 0.42 | 0.48 | 5/4/7 | 138s |
| A6' | evidence_think | 0.50 | 0.50 | 0.50 | 6/6/6 | 305s |
| **A8** | evidence_think + **anchor gate** | 0.57 | 0.67 | **0.62** (max) | 8/6/4 | 304s |
| **A9** | A8 + **verify pass** — **CHỐT** | **1.00** | 0.42 | 0.59 | 5/0/7 | 368s |
| A10 | decide_think + anchor | 0.55 | 0.50 | 0.52 | 6/5/6 | 274s |
| A11 | A10 + verify | 1.00 | 0.25 | 0.40 | 3/0/9 | 299s |

`quote_verbatim_rate = 1.00` ở mọi run (gate D6 giữ đúng G-5).

### Điều kiện dừng (D7)
Sau A8 (0.62), ba lần thử liên tiếp A9 / A10 / A11 không vượt ⇒ **dừng**. Chốt **A9** thay vì A8: chênh F1 0.03 nhỏ hơn 1 dòng gold, trong khi precision 1.00 vs 0.57 là 6 dòng FP — PM ưu tiên precision, và FP ở đây = email khẳng định "tính năng đã có" về thứ chưa có (kiểu sai đắt nhất §4.4). **Mục tiêu F1 ≥ 0.70 (G-4) CHƯA đạt** (0.59; A8 0.62).

### Bài học
- **Gate strict là nút thắt lớn nhất vòng 1**: LLM chép quote kèm "...", gộp heading + text, bỏ bullet ⇒ TP thật bị rớt (`quote_not_found`). Gate v2 "anchor" (đoạn chung dài nhất ≥ 40 ký tự, trả về dòng tài liệu THẬT) nâng F1 0.50 → 0.62 mà vẫn verbatim.
- **json_schema structured output triệt tiêu reasoning của Qwen3** (`<think>` rỗng, 12 token). think=True phải bỏ `response_format` và tự parse — nếu không "think" chỉ là no-think chậm hơn.
- **Evidence-first prompt** (trích passage cho MỌI dòng rồi mới phân loại quan hệ) tăng recall rõ so với prompt "decide" (A0 118/127 dòng không trích gì).
- **Verify pass** đưa precision lên 1.00 nhưng đang hạ oan 3 TP (fb_0054, fb_0090, fb_0107) với `reason` KHẲNG ĐỊNH tính năng có nhưng `confirmed=false` — JSON tự do ở think-mode không nhất quán. Đây là đòn bẩy rõ nhất còn lại (chưa thử vì đã chạm luật dừng).
- FN cố hữu: fb_0093 (LLM bịa "× to remove" — gate chặn đúng), fb_0070/0084 (Image Input node — model coi "reference" ≠ "edit"), fb_0004 (token meter vs "out of credits").
- FP lặp ở nhiều run: fb_0061, fb_0074 (gold False theo precision-first nhưng doc có câu gần đúng), fb_0035 ("nút copy không hoạt động" — bug về tính năng đã có, model trả "copy có trong doc"), fb_0139/0046 (suy diễn xa).

### ⚠ Caveat lặp lại (đo sau khi chốt)
Chạy lại đúng cấu hình A9 trên cùng 127 dòng (run output chính thức `src/03_inference/out/resolve_guideline/gold192_resolved.csv`): **4 TP / 2 FP / 8 FN** (P 0.67, R 0.33) so với run thí nghiệm 5/0/7. `temperature=0` nhưng think-mode không ép schema ⇒ đầu ra không lặp lại tuyệt đối (LM Studio/llama.cpp sampling). Với 12 dương, dao động ±1–2 dòng là ±10–15 điểm ⇒ **precision 1.00 là số của một run, không phải cam kết**; muốn số tin cậy phải chạy ≥3 seed và báo trung bình, và R8 (draft phải deterministic) cần seed cố định / no-think + schema ở production.

### Việc tiếp theo (ngoài scope này)
1. Sửa verify pass: ép reason trước verdict, hoặc verify ở no-think + schema; kỳ vọng lấy lại 3 TP ⇒ F1 ≈ 0.75 tại P 1.00.
2. Đo lặp ≥3 lần / seed cố định để có khoảng tin cậy; đo lại bằng LLM production (Haiku 4.5 §5) — số qwen3-8b chỉ là chỉ báo dev.
3. Gold: PM review 2 dòng ranh giới (fb_0061, fb_0074) và nhóm `bug` về tính năng đã có (fb_0035) — cần quy ước rõ trong D1.
4. Bước 2 backlog (§4.4) + changelog khi có nguồn.
