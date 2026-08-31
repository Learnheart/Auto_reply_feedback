---
author: klinh2212112@gmail.com
date: 2026-08-26
status: in-progress
agents: inference.draft
summary: Script sinh "kịch bản reply" song ngữ VI/EN cho từng intent (category) trong Intent Catalog — routing deterministic theo action_type (§3.2), copy tailored do LLM sinh theo rule email; unclassified → manual. Lớp template design-time cho inference.draft (B2).
---

# Reply-scenario generator — kịch bản reply cho từng category

## Problem statement

Có bộ **category đã chốt** (`catalog_a.yaml`, 8 intent thô + `unclassified`). Cần một **kịch bản
reply cho từng category** để: (1) PM review giọng/nhánh trả lời trước khi wire runtime; (2) làm
lớp template mà `inference.draft` (B2) sẽ điền `{feedback_summary}`/`{timeline}` lúc chạy.

Đây là bước design-time bổ trợ cho `respond.py` (runtime, per-feedback) trong plan
`docs/2026-08-26/inference-classify-respond/plan.md` — KHÔNG thay thế nó.

## Architecture reference

- **Module:** `inference.draft` (B2) — *phần nội dung/template* câu trả lời. Render HTML + deliver
  là Phase 2 (§3/§6), KHÔNG thuộc scope.
- **Sections:** `docs/architecture.md` §3 (`inference.draft`), §4.3 Threshold routing (nhánh
  `unclassified`), §5 (LLM draft Sonnet).
- **Impl doc:** `docs/impl-phase2-auto-feedback-flow.md` §3.2 *Chọn template theo (action_type,
  rag_hit)*, §5 *B2 draft* (nhánh `unclassified` bỏ RAG/backlog).
- **Catalog contract:** `docs/method-offline-intent-analysis.md` §5 (`action_type` → template) + §10.
  Nạp từ `src/01_intent_classification/out/20260826_092038_llm/catalog_a.yaml` (khớp `catalog.py`).
- **Template rule:** `template/skill_create_email.md` — 2 email type `we_listen`/`we_resolved`,
  song ngữ VI/EN, style (no em dash, warm, footer/contacts cố định), `template/email_temp.py` (HTML mẫu).

## Decisions

| # | Quyết định | Lý do |
|---|---|---|
| F1 | **Routing deterministic theo `action_type`** (không đoán keyword): answer_from_kb→we_resolved; known_gap→we_listen; ack_only→we_listen trung tính; `unclassified`→**không auto-reply** (manual PM). | Đúng §3.2 impl + guard §4.3/R1. |
| F2 | **`we_resolved` là quyết định PER-FEEDBACK**, không per-category — cần RAG userguide hit cụ thể. Ở tầng category chỉ mô tả nhánh; catalog hiện 0 intent answer_from_kb ⇒ mọi kịch bản là we_listen/ack. | Tránh hứa "đã giải quyết" khi chưa có KB answer (guard R6). |
| F3 | **LLM sinh copy song ngữ tailored** mỗi category (opening/framing/next-step/closing) theo rule `skill_create_email.md`; giữ `{name}`/`{feedback_summary}`/`{timeline}` làm placeholder cho B2 điền. | "generate kịch bản" — tailored theo bản chất category; nguồn text = LLM (D4 plan cha). |
| F4 | **`unclassified` KHÔNG sinh copy** — chỉ đánh dấu `route=manual_pm`. | Sink §4.3; auto-reply pool này = nhiễu (R1). |
| F5 | Output `out/<ts>_scenarios/reply_scenarios.{yaml,md}` (không ghi đè). yaml cho B2 tiêu thụ, md cho human review. | Nhất quán convention out/ + tách máy/người. |

## Implementation

`src/03_inference/reply_scenarios.py`:
- Nạp catalog (raw YAML, giữ CẢ `unclassified`); reuse path/root từ `catalog.py`.
- `route(intent)` → `{email_type, route, tone, note}` theo F1.
- `REPLY_SYS` (rule email nhúng) → LLM sinh `vi`/`en` copy mỗi intent (trừ unclassified). 1 call batch.
- Client Databricks chat tự chứa (convention repo: mỗi file tự giữ client + truststore + OAuth profile).
- Ghi `reply_scenarios.yaml` + `.md`. CLI `--catalog`, `--dry-run` (bỏ LLM, chỉ routing+khung).

## Non-goal

- KHÔNG render HTML/.eml, KHÔNG deliver Graph (Phase 2). KHÔNG gọi RAG/backlog thật (đó là `respond.py`
  runtime per-feedback). KHÔNG sửa catalog. KHÔNG tự chế intent `answer_from_kb`.

## Verification

- `python -m py_compile reply_scenarios.py`; `--dry-run` chạy offline ra khung.
- Chạy thật (Databricks SSO): `reply_scenarios.md` đọc được, mỗi category có nhánh + copy VI/EN đúng
  tone; `unclassified` = manual, không copy.
