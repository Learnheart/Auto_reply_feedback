---
author: klinh2212112@gmail.com
date: 2026-08-26
status: in-progress  # code xong; verify OFFLINE OK (catalog load + 7 routing test PASS). End-to-end cần LM Studio + Databricks SSO.
agents: inference.classify, inference.draft
summary: Inference 2 bước — (1) phân loại feedback vào Intent Catalog bằng exemplar cosine + threshold routing; (2) sinh câu trả lời cá nhân hoá theo action_type (answer_from_kb → userguide RAG; known_gap → đối chiếu backlog; ack_only/unclassified → ack trung tính)
---

## Problem statement

Phần còn thiếu của inference là **biến một feedback thô thành một câu trả lời cá nhân hoá**. Bài toán chia đúng 2 bước:

1. **Phân loại (B1 classify).** So feedback với bộ **category đã chốt** (Intent Catalog, tham chiếu
   `src/01_intent_classification/out/20260826_092038_llm/step2b_merge_review.md` — 8 intent thô) để biết feedback
   thuộc intent nào, kèm confidence và cờ định tuyến.
2. **Trả lời (B2 draft — phần nội dung).** Tuỳ **action_type** của intent:
   - `answer_from_kb` (user *hiểu nhầm* về app) → gọi **knowledge layer** lấy userguide → tìm hướng dẫn/gợi ý → trả lời cách làm.
   - `known_gap` (bug / idea) → **đối chiếu backlog** của team: khớp một ticket → trả lời "team sẽ phát triển"
     (kèm mốc suy từ `status`); không khớp → trả lời "team đã ghi nhận và sẽ cải thiện TÀI Studio".
   - `ack_only` / `flag=unclassified` → ack trung tính, không RAG, không backlog.

Đầu vào bước 1 đã có: engine exemplar-cosine (`src/03_inference/embedding_test.py`). Đầu vào bước 2 đã có:
knowledge layer (`src/02_knowledge/` — Scholar `ask` cho userguide RAG, `fetch_backlog` cho backlog). Việc của
phase này là **nối 2 bước** thành một pipeline đọc được Intent Catalog thật và định tuyến theo `action_type`.

## Architecture reference

- **Module:** `inference.classify` (B1) + `inference.draft` (B2 — phần *nội dung* câu trả lời; render HTML/deliver
  là Phase 2 §3/§6, KHÔNG thuộc scope này).
- **Sections:** `docs/architecture.md` §3 *Trách nhiệm từng module* (`inference.classify`, `inference.draft`),
  §4.2 *Flow B — inference hằng ngày*, §4.3 *Threshold routing (3 vùng)*, §5 *Technology Stack* (embedding qwen3, LLM draft).
- **Impl doc:** `docs/impl-phase2-auto-feedback-flow.md` §3.2 *Chọn template theo (action_type, rag_hit)*,
  §5 *B2 draft* (nhánh `unclassified` bỏ RAG/backlog).
- **Catalog contract:** `docs/method-offline-intent-analysis.md` §10 (schema `intents.yaml`) — nạp từ
  `src/01_intent_classification/out/20260826_092038_llm/catalog_a.yaml` (`intent_id`, `label`, `description`,
  `action_type`, `supporting_feedback_ids`).
- **Data contract:** §4.5 `intent_catalog` (đọc-only), `feedback_processing` (`intent_id`, `confidence`, `flag`).
  Exemplar vector suy từ `supporting_feedback_ids` → text feedback (map `fb_<i:04d>` = row index trong
  `data/sample/feedback/feedback_extracted.csv`, khớp `step1_clustering.load_feedback`).

### Lệch kiến trúc (khai báo theo rule 3.6 — spike, chưa productionize)

Giống 2 spike đã có (`build_knowledge_layer.py`, `mcp_atlassian_test.py`), phase này **vẫn dùng đường spike**,
KHÔNG phải stack production §5. Chưa productionize ⇒ chưa cập nhật §3/§5, chỉ khai báo:

| §5 quy định | Spike này dùng | Vì sao |
|---|---|---|
| Embedding = Databricks Model Serving `qwen3` | LM Studio local (`text-embedding-qwen3-embedding-0.6b`) | Chạy offline khi dev; cùng họ model |
| Knowledge layer = Databricks Vector Search | Scholar `ask` (đã ingest userguide+backlog) | Theo hướng knowledge-layer-scholar đã chốt |
| `feedback_processing` = bảng Delta | dataclass in-memory + xuất JSON/CSV | Chưa có Delta ở môi trường dev |
| exemplar_vectors nằm trong `intent_catalog` (frozen) | suy runtime từ `supporting_feedback_ids` | Catalog v1 chưa gắn cột exemplar_vectors; giữ nguồn sự thật ở catalog YAML |

Nếu chốt productionize ⇒ DỪNG, cập nhật §3/§4.5/§5 + CHANGELOG trước.

## Requirements

- **R1.** Nạp Intent Catalog từ YAML → objects có `intent_id, label, description, action_type, exemplars, threshold_*`.
  Exemplar = resolve `supporting_feedback_ids` (tối đa `k` id đầu) → content feedback thật.
- **R2. B1 classify:** embed feedback (tách mệnh đề) → max cosine tới exemplar mọi intent → `intent_id` + `confidence`.
  Routing 3 vùng §4.3: `c ≥ high` → `ok`; `low ≤ c < high` → `low_confidence`; `c < low` → `unclassified`
  (KHÔNG đoán nhãn, giữ `best_intent_id`/`best_confidence` cho pool).
- **R3. B2 respond — định tuyến theo `action_type`** (đúng bảng impl §3.2):
  - `answer_from_kb` + có hit userguide → trả lời cách làm + gợi ý (nội dung từ knowledge).
  - `answer_from_kb` + 0 hit → **suy giảm**, ack "we listen", KHÔNG khẳng định đã giải quyết (guard R6).
  - `known_gap` → đối chiếu backlog: khớp → "sẽ phát triển" + mốc từ `status`; không khớp → "đã ghi nhận, sẽ cải thiện".
  - `ack_only` / `unclassified` → ack trung tính; bỏ RAG + backlog (impl §5).
- **R4.** Backlog match = semantic (embed feedback vs `summary+description` từng issue), có ngưỡng → tránh keyword.
- **R5.** Pipeline `infer(feedback) → InferenceResult` gộp classification + response, có thể chạy batch trên CSV.
- **R6.** Mọi module có docstring `Architecture: docs/architecture.md §...` (rule 3.5). Unit-test được phần
  deterministic (routing/threshold/chọn template) không cần LM Studio/Scholar thật.

## Decisions made

- **D1. Định tuyến CHỈ theo `action_type`** (không đoán theo keyword). Catalog v1 hiện chỉ có `known_gap` + `ack_only`
  ⇒ nhánh `answer_from_kb` được wire đầy đủ & test bằng catalog synthetic, sẽ tự kích hoạt khi PM gắn intent
  `action_type: answer_from_kb`. Không tự chế intent answer_from_kb, không sửa catalog (giữ nguồn sự thật).
- **D2. known_gap dùng backlog *có cấu trúc*** (`fetch_backlog` + cosine), KHÔNG dùng Scholar free-text — vì cần
  `jira_key`/`status` xác định để suy mốc và trích dẫn ticket. `answer_from_kb` mới dùng Scholar `ask` (cần văn xuôi).
- **D3. Ngưỡng theo từng nhãn** giữ như engine hiện có; catalog chưa calibrate ⇒ mặc định `high=0.60`, `low=0.45`
  (chừa param, calibrate ở Phase 1 holdout sau — §6.3 bước 4).
- **D4. LLM sinh *text*, không HTML** (impl §3.1). Scope này dừng ở `PersonalizedResponse` (các field text VI);
  render HTML + INTERNAL block + deliver là Phase 2 §3/§6, không làm ở đây.

## Implementation approach

```
src/03_inference/
  catalog.py    # R1: load catalog YAML + resolve exemplars từ feedback CSV → list[CatalogIntent]
  classify.py   # R2 (B1): reuse encoder/normalize/split_clauses của embedding_test → Classification
  knowledge.py  # R3/R4 adapter: userguide_answer() → scholar.ask; backlog_match() → fetch_backlog + cosine
  respond.py    # R3 (B2): route(action_type, flag, rag_hit, backlog_hit) → PersonalizedResponse
  pipeline.py   # R5: infer() = classify → respond; CLI chạy batch CSV (+ --dry-run không gọi mạng)
  tests_respond.py  # R6: test routing thuần (không mạng)
```

Thứ tự: `catalog` → `classify` → `knowledge` → `respond` → `pipeline` → test. Verify: unit-test routing chạy
offline; end-to-end thật cần LM Studio (embedding) + Databricks SSO (Scholar/MCP) nên chỉ chạy được ở máy đã login.
