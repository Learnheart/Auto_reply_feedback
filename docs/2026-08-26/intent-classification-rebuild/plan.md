---
author: klinh2212112@gmail.com
date: 2026-08-26
status: in-progress
agents: intent-catalog, inference.classify
summary: Rebuild module intent classification (Phase 0 offline) theo 2 hướng — A) unsupervised clustering → LLM merge/label, B) direct-LLM label — trên feedback THẬT, rồi đo độ tương đồng giữa 2 hướng vào 1 report.
---

# Intent Classification — Rebuild 2 hướng + report so sánh

## Architecture reference

- **Module:** `Offline intent analysis` (§3 Trách nhiệm từng module — "Sinh và chốt bộ intent từ feedback lịch sử, chạy một lần") → sinh ứng viên **Intent Catalog**. Đây là bước khám phá + đặt tên (§5 method), KHÔNG phải module runtime `classify` (B1).
- **Sections:** `docs/architecture.md` §2 Overview (Input; A4 `n<500` → Direct-LLM; A5 PII; A6 taxonomy đóng băng), §3 Phase 0 (Embedding → HDBSCAN → LLM merge → LLM gen intent), §4.3 Threshold routing, §5 Technology Stack (Embedding / LLM / Phân tích offline), §6.1 R1/R2/R3.
- **Impl / method doc:** `docs/method-offline-intent-analysis.md` §2 (audit + tiền xử lý), §3 (embed), §4 (cluster + stability + đọc noise), §5 (LLM đặt tên + gộp + guardrail grounding), §6 (kiểm định taxonomy); `docs/techstack-intent-classification.md` (giải thích thuật toán từng bước).
- **Data contract:** ứng viên intent tiến tới bảng `intent_catalog` (§4.5): `intent_id, label, description, action_type, exemplars(/supporting_feedback_ids), threshold_high/low`. Bước này **chưa** freeze `intents.yaml`, chưa chọn exemplar cuối/calibrate ngưỡng (§8–§9 — làm sau review gate §7).
- **Supersedes:** `docs/2026-08-25/intent-discovery-llm/plan.md` (cùng ý tưởng 2 version; bản này rebuild sạch + thêm trục *đo độ tương đồng A↔B* làm deliverable chính).

## Problem statement

Feedback thật hiện `data/sample/feedback/feedback_extracted.csv` — **192 dòng, 191 dùng được** (1 dòng không có ký tự chữ). Trộn VI/EN, ngắn (median ~60 ký tự), đuôi dài theo `agent` (12 agent; 7 agent có ≤5 feedback). Ở size này HDBSCAN under-resolve (bản trước: A phủ 57%, đuôi dài rơi vào noise; B over-fragment 82 intent size≈1). Method doc §2.1 xếp `n<500` vào **Direct-LLM path**.

Yêu cầu: dựng lại 2 hướng discovery trên **cùng data, cùng schema output**, rồi **đo độ tương đồng giữa 2 hướng** vào 1 report để chọn/đối chiếu:

- **A — clustering → LLM merge/label:** embed (qwen3) → UMAP → HDBSCAN (cố tình over-segment) → LLM đặt tên từng cụm → LLM gộp toàn cục; **feed cả noise cho LLM** để gán/đề xuất → không bỏ feedback nào (D5 bản cũ).
- **B — direct-LLM:** LLM đọc thẳng feedback theo lô → đề xuất intent mỗi lô → gộp liên lô (union id bằng code) → không qua clustering.

## Quyết định đã chốt

| # | Quyết định | Lý do |
|---|---|---|
| D1 | **1 file / 1 hướng.** `approach_a_cluster_llm.py` (A + shared embed/LLM/IO helpers), `approach_b_direct_llm.py` (B, import helpers từ A, và sinh report so sánh). | User chốt layout. Giữ đúng "code chia 2 file"; report là artifact out/, không phải file code. |
| D2 | Cả A và B **xuất cùng schema** ứng viên: `intent_id, label, description, action_type, supporting_feedback_ids`. | So sánh được A↔B; khớp D2 bản cũ (inference độc lập với discovery). |
| D3 | Embedding = `databricks-qwen3-embedding-0-6b`; LLM = `databricks-claude-sonnet-4-6`, temperature 0, structured JSON (parse tolerant, không phụ thuộc `response_format`). | §5 architecture. **Tên endpoint thật là `databricks-claude-*`**, khác `-sit-tai` ghi ở architecture §5 (đã note ở CHANGELOG) — dùng tên thật. Auth OAuth profile `tcb-agent-sit` qua `~/.databrickscfg`, TLS `truststore` (mạng công ty MITM). |
| D4 | **Guardrail grounding:** mỗi intent phải trích ≥2 `feedback_id` THẬT tồn tại; intent không đủ bị loại/gộp. | §5 method — chống LLM bịa intent. |
| D5 | **Không bỏ feedback nào** ở A: noise (`label=-1`) được feed riêng cho LLM gán vào intent gần nhất / đề xuất intent mới. | Giữ rare-intent (R1), tránh mất 20–35% khối lượng vào noise. |
| D6 | **Đo độ tương đồng A↔B** bằng cơ chế *canonical*, công bằng cho cả 2: gán mỗi feedback → intent gần nhất trong mỗi catalog theo cosine tới **centroid embedding của supporting feedback** của intent đó. Trên 2 nhãn/feedback: **ARI + NMI**; cộng **taxonomy alignment** (match intent A↔B bằng cosine ≥ ngưỡng) + so **granularity/coverage/Gini**. | Hai hướng gán feedback theo cơ chế nội bộ khác nhau; muốn so *taxonomy* thì phải chuẩn hoá cách gán về một cơ chế duy nhất, nếu không ARI đo lẫn nhiễu của cách gán. |
| D7 | Cache embedding ra đĩa (key = hash content + model). | Notebook/script chạy nhiều vòng, không trả tiền embed lại. |

## Non-goal bước này (giữ đúng ranh giới §1/§0)

- **Chưa** chọn exemplar cuối (§8), **chưa** calibrate ngưỡng holdout + Wilson CI + Cohen's κ (§9), **chưa** freeze `intents.yaml` + tag (§10) — làm SAU review gate PM (§7).
- **Không** đụng module runtime `classify` (B1), Delta production, Graph, RAG, Jira — thuộc Phase 2, tài liệu riêng.
- Không auto-send, không tạo ticket, không versioning/mapping (non-goal §1 architecture).

## Implementation approach

```
intent_classification/
├── approach_a_cluster_llm.py   # Hướng A + shared: load/preprocess, embed(+cache), chat_json, io
│     load_feedback → preprocess → embed_texts → reduce_dims(UMAP) →
│     cluster(HDBSCAN, feed noise) → label_clusters(LLM) → merge_global(LLM) →
│     assign_noise(LLM) → ground_filter → write out/catalog_a.{yaml,json}
├── approach_b_direct_llm.py    # Hướng B (import shared từ A) + report
│     batch(~40) → propose_intents(LLM) per batch → merge_across_batches(LLM) →
│     ground_filter → write out/catalog_b.{yaml,json}
│     → compare(A,B): canonical assign → ARI/NMI + alignment + granularity →
│       write out/comparison_report.md
└── out/
    ├── catalog_a.yaml / catalog_a.json
    ├── catalog_b.yaml / catalog_b.json
    ├── embed_cache.json           # cache vector theo hash
    └── comparison_report.md
```

- **Shared helpers (trong file A):** `load_feedback()`, `preprocess()` (giữ hết, chỉ bỏ content không có ký tự chữ — `any(ch.isalpha())`, §2.2 method; không dedup, không lowercase, không bỏ dấu), `_openai_client()` (Databricks serving OpenAI-compat + truststore), `embed_texts()` (cache đĩa), `chat_json()` (Sonnet, ép JSON, strip fence, retry), `write_catalog()`.
- **A:** UMAP `n_components=10, metric=cosine, random_state=SEED`; HDBSCAN sweep `min_cluster_size ∈ {5,8,12}` chọn cấu hình nhiều cụm sạch (n nhỏ ⇒ fallback cấu hình tốt nhất); LLM label mỗi cụm (batch để tiết kiệm call) → LLM merge toàn cục → noise feed theo lô cho LLM gán/đề xuất. Không bỏ feedback.
- **B:** chia lô ~40 → mỗi lô Sonnet trả `intents[]` với `supporting_idx` (index trong lô) → gộp liên lô bằng LLM (nhóm theo idx), union `feedback_id` bằng code.
- **Grounding:** cả 2 lọc intent < 2 id thật (gộp id lỏng vào intent gần nhất hoặc drop, ghi rõ trong report).
- **Report (`comparison_report.md`):** (1) tổng quan mỗi hướng (#intent, coverage, Gini, size dist); (2) canonical per-feedback labels → **ARI, NMI**; (3) **taxonomy alignment** A↔B (bảng cặp match + intent chỉ-A / chỉ-B); (4) nhận xét (hướng nào mịn hơn, hướng nào phủ hơn, chỗ hai bên đồng thuận/lệch).

## Acceptance

- [ ] Chạy được cả A và B trên 191 feedback thật; mỗi bên ra danh sách intent + supporting ids đúng schema (D2).
- [ ] 100% intent qua guardrail grounding ≥2 id thật (D4); A không bỏ im lặng feedback nào (D5).
- [ ] `out/comparison_report.md` có: ARI + NMI (D6), bảng alignment A↔B, so granularity/coverage/Gini, và nhận xét chọn hướng.
- [ ] Embedding + LLM gọi qua Databricks serving thật (D3), cache embedding hoạt động (D7).
- [ ] CHANGELOG cập nhật; plan này có `## Architecture reference` (bắt buộc CLAUDE.md §3).
