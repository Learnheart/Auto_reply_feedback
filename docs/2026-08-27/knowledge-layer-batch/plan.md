---
author: klinh2212112@gmail.com
date: 2026-08-27
status: in-progress
agents: inference.draft, ingest-sync
summary: Knowledge layer thống nhất 2 nguồn (userguide + backlog) theo cùng khuôn snapshot-in-memory → whole-content cho LLM → trả lời theo lô (batch prompting); backlog bỏ cosine, nạp cả danh sách.
---

# Knowledge Layer — batch, snapshot-in-memory, whole-content → LLM

## 1. Vấn đề / nhu cầu

Cần lớp knowledge trả lời feedback từ **2 nguồn Atlassian (đọc qua MCP server)**: **Confluence userguide** (intent `how_to`) và **Jira backlog** (intent `request_feature` + `report_bug`). Bản v3.1 (`docs/2026-08-26/knowledge-retrieval-strategy/plan.md`) đã chuyển userguide sang whole-page routing nhưng **backlog vẫn cosine + embedding** (class `BacklogIndex`), và `pipeline.py` xử lý **từng feedback một** (batch userguide đã viết nhưng chưa wire).

User chốt một luồng cập nhật, thống nhất cả hai nguồn về cùng một khuôn và tối ưu chi phí bằng batch prompting.

## 2. Luồng (4 bước, user chốt)

1. **Lọc** feedback đã classify về nhóm cần knowledge: `action_type ∈ {answer_from_kb, known_gap}` — tức 3 intent `how_to` (userguide), `request_feature` + `report_bug` (backlog).
2. **Query MCP một lần** để lấy knowledge khớp: userguide **lọc theo `agent`** feedback comment; backlog = **toàn bộ backlog hiện hành** (open, non-Done, `sprint is EMPTY`).
3. Giữ knowledge dưới dạng **snapshot in-memory**, fetch một lần và tái dùng cho **mọi feedback trong run**.
4. Nạp **toàn bộ nội dung doc vào LLM** (page userguide / cả danh sách backlog) trả lời **từng feedback theo lô (batch prompting)** để tối ưu chi phí.

## 3. Quyết định đã chốt (session 2026-08-27)

- **Backlog → whole-set cho LLM.** Bỏ hẳn cosine `BacklogIndex` + embedding; nạp cả danh sách backlog vào prompt, đối xứng userguide whole-page.
- **Phạm vi = cả 3 intent cần knowledge**: `how_to` → userguide; `request_feature` + `report_bug` → backlog. Mọi `known_gap` đều tra backlog.
- **Snapshot = in-memory theo run** (fetch một lần, tái dùng trong run). Persist lâu dài vẫn dùng store JSON/Delta sẵn có; **không** thêm lớp cache xuyên run ở scope này.

## Architecture reference

- **Module:** `inference.draft` (B2 — nửa RETRIEVE + GENERATE); knowledge fetch lúc khởi động run (spike làm live như hiện tại), khái niệm thuộc `ingest-sync` (Job A).
- **Sections:** `docs/architecture.md` §3 (Trách nhiệm từng module — note Knowledge layer v3.1/**v3.2**), §4.2 (Flow B — B2 retrieve whole-content → LLM theo lô), §4.5 (Data layer — `userguide_page`, `backlog_ref` cột `embedding` unused), §5 (Technology Stack — hàng *Userguide store* + *Backlog store (v3.2)*; embedding chỉ còn cho B1).
- **Impl doc:** `docs/impl-phase2-auto-feedback-flow.md` §3.2 (chọn template theo `(action_type, hit)`), §5 (B2).
- **Kế thừa / thay:** `docs/2026-08-26/knowledge-retrieval-strategy/plan.md` (userguide whole-page giữ nguyên); **thay** item 3 phần "BacklogIndex không đổi" — backlog nay whole-set → LLM.
- **Data contract:** `userguide_page(agent PK, page_id, version, title, markdown, ...)` giữ nguyên; `backlog_ref` cột `embedding` **không sinh/dùng** (whole-set → LLM).
- **Lệch kiến trúc có chủ đích (rule 3.6):** §3/§4.5/§5 gốc quy định knowledge layer = Vector Search / cosine. Bản này thống nhất whole-content → LLM cho cả hai nguồn. `architecture.md` + plan v3.1 + `CHANGELOG.md` cập nhật **TRƯỚC** khi code land (đã làm trong task này).

## 4. Cách làm (`src/03_inference/`)

### `knowledge.py`
- **Giữ nguyên:** `answer_from_userguide`, `answer_from_userguide_batch`, `UserguideAnswer` (đã whole-page + batch + gate `answerable`).
- **Bỏ:** class `BacklogIndex` (cosine + `encoder` + `from_jira`) và phụ thuộc `numpy`/`normalize` cho backlog.
- **Giữ `BacklogMatch`** (fields `hit, jira_key, summary, status, issuetype, score`; `score=0.0` không dùng ở nhánh LLM) để `respond.py` không đổi.
- **Thêm `answer_from_backlog_batch(feedbacks, backlog_items, *, llm=None, batch_size=DEFAULT_BATCH_SIZE) -> list[BacklogMatch]`** (đối xứng `answer_from_userguide_batch`): dựng listing backlog đánh số **một lần** (`[B0] summary — status`, kèm description); mỗi lô ≤ `batch_size` feedback → 1 call Sonnet với `(cả danh sách backlog + feedback đánh số)`; prompt `_BACKLOG_BATCH_SYS` trả `{"matches":[{"index":i,"backlog_ref":j|null}]}`. **Tự** resolve `j → backlog_items[j]` (không tin LLM echo field). Missing/`null`/out-of-range ⇒ `hit=False`. Reuse `reply_scenarios.chat_json`, inject được để test offline. Log size-guard nếu danh sách backlog quá dài.
- **Thêm `KnowledgeSnapshot` + `build_snapshot(...)`** — snapshot in-memory theo run: `userguide_pages: UserguidePages | None` + `backlog_items: list[dict]`, fetch/load một lần.

### `pipeline.py`
- Dựng snapshot **một lần** lúc khởi động (userguide pages + backlog list; backlog không cần encoder nữa — encoder chỉ còn cho classify).
- **Thêm `infer_batch(feedbacks) -> list[InferenceResult]`**: (1) classify tất cả; (2) phân nhóm index theo `action_type`; (3) userguide: gom index `answer_from_kb` **theo `agent`** → `answer_from_userguide_batch`/agent; (4) backlog: gom `known_gap` → một `answer_from_backlog_batch`; (5) `respond(cls, userguide=…, backlog=…)`/feedback. Giữ `infer()` per-item cho back-compat/test; `main()` chạy qua `infer_batch`, bỏ `BacklogIndex.from_jira`.

### `respond.py`
- Không đổi (interface `BacklogMatch` giữ nguyên). Chỉ verify.

### `tests_respond.py`
- Bỏ `BacklogIndex`/`_BowEncoder`/4 test cosine; thêm test offline cho `answer_from_backlog_batch` (matched → hit + jira_key/status đúng; null/missing → hit=False; out-of-range → hit=False an toàn; `batch_size` chia đúng số call). Giữ mọi test userguide + respond.

### Hazard sửa kèm
`import mcp_atlassian_test` nhưng file là `mcp_atlassian_call.py` (nay chỉ resolve qua `.pyc` cũ). Làm import robust khi snapshot gọi `fetch_backlog`/`fetch_userguide`.

## 5. Acceptance

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| B-1 | `answer_from_backlog_batch` matched → `hit=True`, jira_key/status resolve từ danh sách; null/missing/out-of-range → `hit=False` | test offline (inject llm) |
| B-2 | `batch_size` chia đúng số call, kết quả align theo `index` | test offline |
| B-3 | `infer_batch` gom userguide 1 call/agent + backlog 1 lô; template `respond` đúng (`we_resolved`/`we_listen`/neutral); guard `hit=False → we_listen` giữ | smoke inject llm trên ~5 feedback trộn |
| B-4 | Snapshot fetch userguide + backlog **một lần**/run, tái dùng | `pipeline.py --limit 20` (đếm fetch) |
| B-5 | `tests_respond.py` (userguide + respond) vẫn pass | pytest |

## 6. Rủi ro

- **Token/call tăng theo (số backlog × K feedback).** Backlog nhỏ (~chục issue) nên chấp nhận; nếu phình to: tiền lọc (JQL theo agent/keyword) hoặc quay lại cosine cho backlog. Log size-guard.
- **LLM đối chiếu sai (false-positive "team sẽ làm").** Prompt buộc chỉ match khi hạng mục THỰC SỰ là việc feedback đề cập; `backlog_ref=null` khi không chắc ⇒ ghi nhận chung, không hứa mốc.
