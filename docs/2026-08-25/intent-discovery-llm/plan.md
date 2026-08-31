---
author: klinh2212112@gmail.com
date: 2026-08-25
status: in-progress
agents: intent-catalog
summary: Hai version discovery intent bằng LLM (A: clustering → LLM merge, B: direct-LLM) cho data nhỏ (~192 feedback), cùng xuất một catalog ứng viên.
---

# Intent Discovery bằng LLM — 2 version (A: cluster→merge, B: direct)

## Architecture reference

- **Module:** `Offline intent analysis` (§3) → sinh Intent Catalog. Đây là bước §5 (LLM merge + đặt tên) của method doc, mở rộng cho nhánh **Direct-LLM path** khi `n < 500` (§2.1 method, A4 architecture).
- **Sections:** `docs/architecture.md` §2 A4 (n<500 → Direct-LLM), §3 Phase 0, §4.3 Threshold routing, §5 (LLM Sonnet/Haiku), §6.1 R1.
- **Method doc:** `docs/method-offline-intent-analysis.md` §2.1 (đường đi theo n), §5 (LLM merge + guardrail grounding), §8–9 (exemplar + calibrate — sau bước này).
- **Data contract:** ứng viên intent → tiến tới `intent_catalog` (§4.5): `intent_id, label, description, action_type, exemplars, threshold_*`.

## Problem statement

Data thật hiện ~192 feedback (191 dùng được). Ở size này HDBSCAN under-resolve: sweep không cấu hình nào đạt tiêu chí, fallback ra 9 cụm, **noise 24.6%** (~47 feedback mất khỏi bước đặt tên), 7 agent có ≤5 feedback → intent đuôi dài rơi hết vào noise. ⇒ cần discovery **do LLM dẫn**, không để clustering làm driver mất mát.

Xây **2 version** để so sánh trên cùng data, cùng schema output:
- **A — clustering → LLM merge:** HDBSCAN pre-group + **feed cả noise** cho LLM gộp/gán (không bỏ feedback nào).
- **B — direct-LLM:** LLM đọc thẳng toàn bộ feedback theo lô, đề xuất intent, gộp liên lô.

## Quyết định đã chốt

| # | Quyết định | Lý do |
|---|---|---|
| D1 | **Inference = Hybrid** (cosine exemplar chính + Haiku few-shot fallback cho vùng `low_confidence`) | User chốt. Khớp "Haiku dự phòng" §5 architecture; giữ confidence rõ cho `unclassified_rate` (R1) |
| D2 | Cả A và B **xuất cùng schema catalog ứng viên** | Inference độc lập cách discovery. Vì hybrid ⇒ mỗi intent cần `label`+`description` (cho LLM fallback) **và** về sau exemplar+ngưỡng (cho cosine) |
| D3 | LLM discovery dùng `claude-sonnet-4-6-sit-tai` (suy luận đặt tên/gộp), structured JSON, temperature 0 | §5 — đặt tên/gộp cần suy luận ngữ nghĩa |
| D4 | **Guardrail grounding:** mỗi intent phải trích ≥2 `feedback_id` THẬT tồn tại; intent không đủ bị loại | §5 method — chống LLM bịa intent |
| D5 | **Không bỏ feedback nào** ở version A: noise points được feed riêng để LLM gán/đề xuất | Ràng buộc đã thống nhất với user |

## Ngoài scope bước này

- Exemplar selection (§8), calibrate ngưỡng (§9) — làm SAU khi chốt danh sách intent.
- Runtime `classify` (B1) + Haiku fallback thật — thuộc production, tài liệu riêng.
- Freeze `intents.yaml` + tag — sau review gate (§7).

## Implementation approach

```
intent_classification/
├── run_intent_analysis.py       # đã có: audit→embed→reduce→cluster→validation
└── discovery.py                 # MỚI: 2 version discovery bằng LLM
    ├── shared: _chat_json(), schema validate, grounding guardrail, ghi YAML+CSV
    ├── version A: cluster (tái dùng run_intent_analysis) + noise → 1–2 call Sonnet
    └── version B: batch ~40 feedback → Sonnet mỗi lô → 1 call merge liên lô
out/
├── discovery_A.yaml / discovery_A.csv      # intent ứng viên (đường A)
└── discovery_B.yaml / discovery_B.csv      # intent ứng viên (đường B)
```

- Tái dùng `embed_texts` (cache), `reduce_dims`, `cluster`, `_openai_client` từ `run_intent_analysis.py`.
- Chat qua OpenAI-compat client, model Sonnet; prompt ép **chỉ JSON**, parse tolerant (strip fence). Không phụ thuộc `response_format` (endpoint Claude có thể không hỗ trợ).
- Output mỗi version: `intents[]` = `{intent_id, label, description, action_type, supporting_feedback_ids}`; kèm CSV cho PM đọc; in bảng so sánh A vs B (số intent, nhãn, coverage feedback).

## Acceptance

- [ ] Chạy được cả A và B trên 191 feedback thật, mỗi bên ra danh sách intent + supporting ids.
- [ ] 100% intent qua guardrail grounding (≥2 id thật).
- [ ] Không feedback nào bị bỏ im lặng ở A (noise được feed).
- [ ] In bảng so sánh A vs B để chọn hướng.
