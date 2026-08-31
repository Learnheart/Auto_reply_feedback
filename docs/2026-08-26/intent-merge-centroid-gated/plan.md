---
author: klinh2212112@gmail.com
date: 2026-08-26
status: in-progress
agents: intent-catalog
summary: Đổi bước gộp của hướng A (STEP 2) từ "gộp intent cùng nghĩa" (16–24 intent mịn) sang rollup về TẦNG THÔ (Tier A) do LLM TỰ SINH nhãn (~4–8 intent, không định sẵn), kèm 2 artifact review tường minh cho bước label và bước rollup.
---

# Rollup intent về tầng thô (Tier A, LLM tự sinh) + output STEP 2 tường minh

> **Ghi chú:** bản đầu của doc này đề xuất *centroid-gated merge* (gộp theo ngưỡng cosine).
> Đã **superseded** sau thảo luận với user: cosine chỉ đo tương đồng chủ đề (⟂ trục
> bug/feature/praise) nên không phải đòn bẩy đúng. User chốt gom thẳng về **tầng category**.

## Architecture reference

- **Module:** `Offline intent analysis` (§3 Phase 0). Chỉ đụng **bước gộp** của hướng A trong
  `src/01_intent_classification/2_phase/step2_llm_label_merge.py`. KHÔNG đụng runtime `classify` (B1),
  không đụng STEP 1 clustering, không đụng hướng B.
- **Sections:** `docs/architecture.md` §3 Phase 0 (Embedding → HDBSCAN → **LLM merge** → LLM gen
  intent), §5 (LLM Sonnet). Rollup thay thế đúng ô "LLM merge".
- **Impl / method doc:** `docs/method-offline-intent-analysis.md` §5b (LLM gộp). Tier-A rollup là
  một biến thể của §5b: thay vì gộp cặp cùng-nghĩa, gán mỗi cụm vào bộ coarse cố định.
- **Data contract:** giữ schema `intent_id, label, description, action_type,
  supporting_feedback_ids, source_clusters` (không đổi). `action_type` vẫn 3 giá trị §5
  (answer_from_kb/known_gap/ack_only) — Tier A chỉ dùng known_gap + ack_only. Không sửa
  `architecture.md`.

## Problem statement

STEP 2 hiện gộp cụm "cùng nghĩa" ⇒ ra 16–24 intent **khá mịn**. Hai vấn đề (user chốt):

1. **Nhãn quá mịn → bắt sai intent.** Feedback mới chỉ khác câu chữ dễ trượt giữa 2 intent sát
   nhau (vd `translation_quality` ↔ `file_translation_error`). Với mục tiêu **auto-reply**, reply
   template chủ yếu bám `action_type`/tầng thô ⇒ không cần độ mịn đó.
2. **Bước gộp không review được.** `label_clusters → merge_global` chạy liền, chỉ còn catalog cuối;
   không thấy cụm nào gộp vào đâu, label mới là gì.

## Decisions

| # | Quyết định | Lý do |
|---|---|---|
| E1 (cũ) | ~~LLM tự sinh bộ intent thô~~ → **superseded bởi E1c**. | — |
| E1b | **Trục gom = KỊCH BẢN TRẢ LỜI**, không phải chủ đề/tính năng. | User: "việc chia category nên depend vào scenario để trả lời câu hỏi". |
| **E1c** | **Bộ intent CỐ ĐỊNH = 5 hướng trả lời + unclassified** (user chốt): `report_bug`/`request_feature`/`how_to`/`praise`/`complaint`/`unclassified`. Rollup = gán MỖI cluster vào đúng 1 (hằng `SCENARIOS`), `action_type` suy cứng từ intent (report_bug,request_feature→known_gap; how_to→answer_from_kb; praise,complaint→ack_only). intent_id = nhãn cuối inference route theo. | Action 3-enum quá thô: bug vs feature (cùng known_gap) và praise vs complaint (cùng ack_only) reply KHÁC nhau; how_to (answer_from_kb) bị nuốt = 0. Cố định hoá đúng các hướng reply thật. KHÔNG đổi contract action_type. |
| E2 | **`action_type` do LLM chọn** trong 3 enum §5 (answer_from_kb/known_gap/ack_only). | Buckets không cố định nữa ⇒ action_type đi cùng nhãn LLM sinh. |
| E3 | LLM nhận `category trội` mỗi cụm làm **tín hiệu tham khảo**; bảng review hiện `category_trội` làm **cross-check** cho human. | Trục category (user gán) ⟂ trục cluster (chủ đề); human soi lệch qua cột cross-check. |
| E4 | **Nhãn `unclassified` tường minh** (§4.3 unclassified_pool): case không khớp KHÔNG ép vào intent — LLM được cho cụm vào `unclassified`; `assign_noise` dồn noise không khớp / id lạ vào đó; cụm LLM bỏ sót → `unclassified`. Sink giữ qua grounding (`always_keep`). coverage tính RIÊNG feedback vào intent thật; `meta.n_unclassified`. | User: "vẫn nên để 1 nhãn cho unclassify... không nên cố đưa hết vào intent như thế dễ gây noise". |
| E5 | **Hai artifact review**: `step2a_cluster_labels` (label mịn/cụm) + `step2b_merge_review` (bảng rollup nhóm theo intent LLM tự sinh). | Yêu cầu #2 — human review dễ. |

## Implementation (đã code)

`src/01_intent_classification/2_phase/step2_llm_label_merge.py`:
- Prompt: bỏ `MERGE_SYS`; thêm `ROLLUP_SYS` (LLM tự sinh bộ intent thô ~4–8, tự đặt nhãn +
  action_type; cho phép cụm không khớp vào `"unclassified"`); sửa `ASSIGN_SYS` (không khớp → `unclassified`).
- Hằng reserved: `UNCLASSIFIED_ID/LABEL/DESC` + `_UNCLASSIFIED_ALIASES`.
- Hàm: bỏ `merge_global`; thêm `rollup_to_buckets` (parse intent LLM sinh; cụm LLM đánh dấu/bỏ sót →
  sink `unclassified`), `write_cluster_labels` (2a), `write_merge_review` (2b, nhóm động, unclassified
  xuống cuối), helper `_members_by_cluster` / `_dominant_category`. `ground_filter` thêm `always_keep`.
- `assign_noise`: noise không khớp / id lạ → `unclassified` (không ép).
- `run_approach_a`: label → ghi 2a → rollup (LLM) → `dedup_intent_ids` → ghi 2b → assign_noise →
  `ground_filter(always_keep={unclassified})`; coverage tính riêng (không kể unclassified),
  `meta.n_unclassified` + `granularity = coarse_llm_generated_tier_a`.

## Non-goal

- Không calibrate ngưỡng runtime (§4.3), không two-level taxonomy, không đụng hướng B / `classify`.
- Không đổi data contract hay `architecture.md`.

## Verification (KHÔNG tự chạy — user chạy để review)

- `python -m py_compile step2_llm_label_merge.py` — pass (không gọi endpoint).
- User chạy `python step2_llm_label_merge.py`, kiểm: `catalog_a` còn ~4–8 intent thô (LLM tự sinh),
  coverage cao; `step2b_merge_review.md` đọc được (mỗi intent liệt kê cụm + category_trội + lý do),
  soi cụm `[chưa gom]` nếu có.
