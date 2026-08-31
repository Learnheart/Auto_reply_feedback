---
author: klinh2212112@gmail.com
date: 2026-08-27
status: done
agents: inference.classify, inference.draft, shared
summary: Đổi LLM draft/knowledge Sonnet→Haiku 4.5 (AI-Gateway Responses API) và embedding classify LM Studio local→Databricks Model Serving qwen3-0.6b
---

## Problem statement

Hai chỗ gọi model đang lệch mục tiêu chi phí + lệch kiến trúc:

1. **LLM draft/knowledge** (`reply_scenarios.chat_json`, dùng bởi cả scenario generator lẫn `knowledge.py`
   answer_from_kb/known_gap) đang gọi **Sonnet 4.6** qua OpenAI-compatible `/serving-endpoints`. Feedback
   ngắn (đo thực: ~19 token/feedback) + câu trả lời grounded theo template ⇒ không cần suy luận sâu của Sonnet.
   Haiku 4.5 rẻ hơn ~3× (~$0.18 vs $0.54/run 191 feedback; ~$2 vs $6/tháng ở 100 fb/ngày).
2. **Embedding classify (B1)** đang dùng **LM Studio local** (`localhost:1234`, `LMStudioEncoder`) — đây là
   **spike shortcut LỆCH architecture §5** (đã quy định embedding = Databricks Model Serving qwen3-0.6b).
   Phụ thuộc LM Studio chạy tay ⇒ không chạy được trên job/cron.

## Requirements

- R1. `chat_json` gọi Haiku qua **AI-Gateway MLflow Responses API** (`/ai-gateway/mlflow/v1/responses`),
  giữ nguyên chữ ký `chat_json(system, user, *, retries, max_tokens) -> Any` để **knowledge.py + scenario
  generator không đổi** (migrate cả 2 call site qua một client dùng chung — quyết định của user).
- R2. Embedding classify đổi sang `DatabricksEncoder` (Model Serving `qwen3-embedding-0-6b`,
  `/ai-gateway/mlflow/v1/embeddings`), **cùng interface** `encode(texts) -> np.ndarray (N,1024)` L2-norm như
  `LMStudioEncoder` ⇒ `classify.IntentClassifier` chỉ đổi default encoder. Giữ `LMStudioEncoder` cho test offline.
- R3. Không đổi data contract (`Classification`, `PersonalizedResponse`, `UserguideAnswer`, `BacklogMatch`).
- R4. Fail-loud khi thiếu auth/endpoint (không nuốt lỗi thành kết quả rỗng).

## Decisions made

- **D1. Endpoint thật (đã validate live, profile `tcb-agent-sit`, host `dbc-e8b4e078-ca9e`):**
  - Chat: `nonprod_ai.tsfai.claude-haiku-4-5-sit-tai` → `claude-haiku-4-5-20251001`.
  - Embedding: `nonprod_ai.tsfai.qwen3-embedding-0-6b-sit-tai` → 1024-dim.
- **D2. Responses API mapping:** `system → instructions` (field riêng), `user → input:[{role,content:[{type:"input_text",text}]}]`,
  `max_tokens → max_output_tokens`, `temperature=0`. Text kết quả ở `output[0].content[0].text`.
  Model **bọc JSON trong ```json fence** → `_extract_json` hiện tại **đã strip fence** ⇒ tái dùng nguyên.
- **D3. Reuse client HTTP:** dùng `httpx` + `truststore` (mạng công ty MITM CA) + token U2M từ
  `WorkspaceClient(profile).config` — cùng khuôn `mcp_atlassian_call`/`reply_scenarios` cũ.
- **D4. R2-guard (architecture.md §R2):** thresholds trong catalog calibrate ở không gian vector qwen3-0.6b.
  LM Studio và Databricks cùng base model qwen3-embedding-0.6b ⇒ cùng không gian. Validate bằng cách so
  cosine phân bố trước/sau trên vài feedback mẫu (không blocking, cùng model family).
- **D5. Q3 (unclassified) KHÔNG cần build thêm:** `respond()` đã sinh ack `we_listen_neutral`,
  `deliver.folder_for()` đã route vào folder `⚠ Unclassified` cho admin duyệt (không auto-send). Chỉ xác nhận.

## Architecture reference

- Module: `inference.draft` (B2 — chat client), `inference.classify` (B1 — encoder), `shared` (client Model Serving).
- Sections: docs/architecture.md §5 Technology Stack (dòng LLM draft / LLM fallback / Embedding),
  §3 CROSS-CUTTING Model Serving, §4.2 Flow B, §4.3 Threshold routing.
- Impl doc: docs/impl-phase2-auto-feedback-flow.md §5; docs/method-offline-intent-analysis.md §10 (embedding model).
- Data contract: không đổi (§4.5 feedback_processing / backlog_ref).

### Lệch kiến trúc (khai báo theo RULE 6 — cập nhật architecture.md TRƯỚC khi code)

- **Haiku thay Sonnet ở nhánh draft/knowledge:** §5 xếp Sonnet là LLM draft chính, Haiku chỉ "fallback batch
  classify / ack unclassified". Nay chuyển Haiku thành model draft/knowledge **chính** (lý do: chi phí; nội
  dung draft ngắn/template-driven). Trade-off: chất lượng suy luận thấp hơn Sonnet ở câu trả lời KB dài —
  chấp nhận vì có gate `answerable=false → we_listen` chặn bịa. Giữ tên endpoint Sonnet trong config để
  fallback nếu chất lượng giảm. → Cập nhật §5 + CROSS-CUTTING.
- **Embedding LM Studio → Databricks:** đây là kéo code **về đúng** §5 (không phải lệch mới); ghi rõ endpoint
  thật `nonprod_ai.tsfai.qwen3-embedding-0-6b-sit-tai`.
- **API surface mới:** AI-Gateway MLflow Responses/Embeddings (`/ai-gateway/mlflow/v1/*`) thay OpenAI
  `/serving-endpoints`. Ghi chú ở §5.

## Implementation approach

1. `reply_scenarios.py`: thay `_openai_client()`/`chat_json` bằng client Responses API (Haiku). Đổi
   `CHAT_MODEL` → `nonprod_ai.tsfai.claude-haiku-4-5-sit-tai`, thêm `AI_GATEWAY_HOST`. Giữ `_extract_json`.
2. `embedding_test.py`: thêm `DatabricksEncoder` (mirror `LMStudioEncoder`: batch, sort theo index, L2-norm,
   MRL dim optional). Endpoint `/ai-gateway/mlflow/v1/embeddings`.
3. `classify.py`: default encoder `DatabricksEncoder()` (thay `LMStudioEncoder()`); vẫn cho inject để test.
4. Test: (a) `chat_json` trả JSON hợp lệ từ Haiku; (b) `DatabricksEncoder.encode` shape (N,1024) L2-norm ~1;
   (c) `classify` 4 câu mẫu ra flag hợp lý; (d) so cosine LM Studio vs Databricks (D4).

## Acceptance

- [x] `python classify.py` chạy qua Databricks embedding (không cần LM Studio) — 4 câu chạy end-to-end.
- [x] `chat_json`/`knowledge` gọi Haiku ra JSON parse được (live: `{'answerable': True, ...}`).
- [x] `DatabricksEncoder.encode` shape (N,1024), L2-norm = 1.0.
- [x] Không đổi data contract; `tests_respond` + `tests_delivery` = **29 passed**.
- [x] architecture.md §5 + CROSS-CUTTING + CHANGELOG cập nhật TRƯỚC code.

## ⚠ Việc còn treo — R2 calibration (CHƯA verify, cần LM Studio)

Live classify cho confidence **dồn thấp** (nhiều `low_confidence`; vd "mong team thêm tính năng…"
[request_feature] → `complaint` c=0.54; noise "hôm nay trời đẹp" → `praise` c=0.458). Threshold catalog
calibrate ở không gian vector **LM Studio qwen3**; không so được baseline vì LM Studio đang tắt. Hai qwen3
deployment có thể pooling/normalize khác nhau ⇒ cosine lệch scale ⇒ routing sai vùng.

**Cần làm trước khi tin số confidence production:**
1. Bật LM Studio, encode CÙNG tập feedback qua cả 2 encoder, so cosine tới exemplar (D4). Nếu lệch hệ thống.
2. Hoặc re-calibrate `threshold_high/low` trong catalog theo không gian Databricks (chạy lại bước calibrate offline với `DatabricksEncoder`).
3. Thực thi guard §R2: ghi `embedding_model_name` vào catalog + `classify` fail-loud nếu lệch.
