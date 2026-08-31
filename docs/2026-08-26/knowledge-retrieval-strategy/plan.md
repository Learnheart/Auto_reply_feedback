---
author: klinh2212112@gmail.com
date: 2026-08-26
status: in-progress
agents: ingest-sync, inference.draft
summary: Knowledge layer chuyển từ Vector Search/Scholar sang định tuyến theo `agent` → nạp cả page userguide của function cho LLM (whole-page context), bỏ chunk/embed cho userguide.
---

# Knowledge Retrieval Strategy — `agent`-routed whole-page → LLM

## Architecture reference

- **Module:** `ingest-sync` (Job A — dựng KNOWLEDGE LAYER) + `inference.draft` (B2 — nửa RETRIEVE).
- **Sections:** `docs/architecture.md` §3 (Trách nhiệm từng module + khối KNOWLEDGE LAYER), §4.2 (Flow B — bước B2 retrieve), §4.5 (Data layer — thay index Vector Search bằng store `userguide_page`), §5 (Technology Stack — bỏ Vector Search + Scholar cho userguide), §6.1 (R6).
- **Impl doc:** `docs/impl-phase2-auto-feedback-flow.md` §4 (Job A `ingest-sync`), §5 (B2 `draft`).
- **Data contract:** store mới `userguide_page(agent, page_id, version, title, markdown, last_modified)` (§4.5); `backlog_ref` giữ nguyên; `feedback_processing` không đổi.
- **Lệch kiến trúc có chủ đích (rule 3.6):** §3/§4.5/§5 đang quy định knowledge layer = Databricks Vector Search. Bản này thay bằng whole-page routing. `architecture.md` + `CHANGELOG.md` cập nhật **TRƯỚC** khi code land.

## 1. Vấn đề

`architecture.md` quy định knowledge layer = Vector Search (chunk → embed → semantic retrieval). Điều này bắt buộc **detect chunk changes** mỗi khi tài liệu đổi, và tái embed — chi phí vận hành liên tục. Spike hiện tại đã lệch: userguide đi qua **Scholar** (managed RAG), backlog đi qua **cosine tự embed**.

Mục tiêu: bỏ gánh nặng chunk-maintenance và định tuyến truy xuất theo từng feedback, mà **không** hy sinh chất lượng câu trả lời trên feedback ngắn/informal/VI-EN.

## 2. Hai sự thật quyết định thiết kế

1. **Feedback đã mang sẵn khóa định tuyến.** `data/sample/feedback/feedback_extracted.csv` có cột `agent` với giá trị chính là tên function (`the-powerpoint-er`, `the-translator`, `the-summarizer`, `the-brainstormer`, `the-imaginator`, `the-ai-visionary`, `the-scholar`, `the-canvas-designer`, `the-whiteboarder`, `the-ai-coach`; `tai`/`tai-studio` = mức nền tảng). Route feedback → function là **tra bảng, không phải semantic match**.
2. **Userguide phân trang theo function.** Confluence root + page con, mỗi page có `version` (`mcp_atlassian_test.fetch_userguide`). `agent → page` là map tự nhiên; change-detection ở mức **page** thay vì chunk.

Lưu ý trục: **intent là type-scoped, không phải function-scoped** (`how_to_usage`, `action_type=answer_from_kb` cắt ngang mọi agent — `method-offline-intent-analysis.md:273`). Intent chọn *kiểu phản hồi*; `agent` chọn *tài liệu*. Không gộp hai trục.

## 3. Quyết định (đã chốt với PM/user)

Route theo `agent` → nạp **cả page userguide** của function đó cho Sonnet làm context → LLM sinh câu trả lời. **Không embedding, không chunk, không vector index** cho userguide.

- `agent` là **prior mềm, không phải cổng cứng**: không có page cho agent, hoặc LLM báo không trả lời được từ tài liệu ⇒ rơi về `we_listen` (tái dùng nhánh `hit=False` sẵn có).
- Backlog (`known_gap`) **giữ nguyên** — cosine có cấu trúc. **[SIÊU HÌNH — v3.2, `docs/2026-08-27/knowledge-layer-batch/plan.md`]** Quyết định này đã bị thay: backlog nay cũng **whole-set → LLM** (bỏ cosine/embedding), đối xứng với userguide whole-page. Item 3 phần "BacklogIndex không đổi" bên dưới **không còn hiệu lực**.

**Vì sao whole-page thắng "text search" ở cùng chi phí maintenance:** keyword/BM25 thua trên feedback ngắn informal VI-EN (vocab mismatch → miss; trùng từ phổ biến → trả lời sai tự tin). Whole-page → LLM cùng mức maintenance (không embedding) nhưng để LLM bắc cầu ngữ nghĩa. Đồng thời **giảm R6 về mặt cấu trúc**: không có index riêng để lệch nguồn — page đọc lúc inference *chính là* nguồn, và `version` của nó đi vào citation.

## 4. Cách làm

1. **Map `agent → page` (config nhỏ, mới).** Dict từ ~12 giá trị `agent` sang `page_id`. Verify phủ hết giá trị `agent` trong feedback; `tai`/`tai-studio` → page root/overview; agent chưa map ⇒ `hit=False`.
2. **Job A `build_knowledge_layer.py` — bỏ nạp Scholar cho userguide.** Fetch page userguide một lần → store `userguide_page(agent, page_id, version, title, markdown, last_modified)` (Delta ở prod; JSON cache ở spike). Không chunk/embed/notebook. Giữ nguyên fetch backlog Jira.
3. **`knowledge.py` — viết lại adapter userguide.** `answer_from_userguide(feedback, agent, pages, llm) -> UserguideAnswer`: tra `agent → page`; gọi Sonnet với `(feedback + markdown cả page)`, ép **structured output** `{answerable: bool, answer: str}` (pydantic — khớp convention impl §3.1). `answerable=False ⇒ hit=False` (thay `_looks_like_no_answer` string-match). `UserguideAnswer` thêm `page_id`+`version`, bỏ `thread_id`. `BacklogIndex` không đổi.
4. **`pipeline.py` — dẫn `agent` xuyên suốt.** `_load_feedbacks` trả `(content, agent)`; nạp store `userguide_page` một lần lúc khởi động (song song cách backlog embed một lần); `infer(feedback, agent)` cho nhánh `answer_from_kb`.
5. **`respond.py` — chỉ đổi citation.** Body + guard `answer_from_kb + hit=False → we_listen` giữ nguyên; citation đổi `userguide:{thread_id}` → `userguide:{page_id}@{version}`.

## 5. Luồng cập nhật knowledge (chốt câu hỏi auto/manual trước đó)

- **Sửa nội dung page có sẵn → AUTO**, Job A bắt qua `version`.
- **Function mới → thêm page mới + một dòng trong map `agent → page`** (manual, tối thiểu).
- Không tái embed ở cả hai trường hợp.

## 6. Rủi ro cần theo dõi

- **Page quá dài → tốn token.** Đo char/page bằng `python src/02_knowledge/build_knowledge_layer.py --dry-run`. Nếu page rất lớn (>~8k token): tiền lọc theo heading H2 (route tới section, vẫn không embedding) hoặc chấp nhận chi phí (20–100/ngày là thấp). Mặc định giữ whole-page + log size-guard.
- **`agent` sai / feedback cross-cutting.** Prior mềm + fallback `we_listen` (đã có).
- **`tai`/`tai-studio` nền tảng.** Map về page overview; không trả lời được ⇒ `we_listen`.

## 7. Acceptance

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| K-1 | Map `agent → page` phủ mọi `agent` distinct trong feedback (kể cả `tai`/`tai-studio`) | script đối chiếu CSV ↔ map |
| K-2 | `answer_from_kb` lấy đúng page của function, Sonnet trả lời grounded, citation `page_id@version` | `pipeline.py --limit 20` |
| K-3 | Feedback cross-cutting/wrong-agent ⇒ `answerable=False` ⇒ `we_listen` (không trả lời sai tự tin) | test có chủ đích |
| K-4 | Sửa 1 page Confluence ⇒ chạy lại Job A ⇒ citation phản ánh `version` mới (R6) | kiểm tay |
| K-5 | `tests_respond.py` vẫn pass; thêm case routed `hit=False → we_listen` | pytest |
