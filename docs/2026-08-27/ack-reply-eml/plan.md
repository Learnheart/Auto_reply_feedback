---
author: klinh2212112@gmail.com
date: 2026-08-27
status: in-progress
agents: inference.draft, inference.deliver
summary: Hoàn thiện auto-reply .eml cho 3 label không cần knowledge layer (praise, complaint, unclassified) — sample bank tĩnh + gold template song ngữ + batch export .eml.
---

## Problem statement

Luồng auto-feedback đã xong bước detect intent (catalog
`src/01_intent_classification/out/20260826_180647_llm/catalog_a.json`, 6 label). Ba label
`report_bug`, `request_feature`, `how_to` cần knowledge layer (làm sau). Ba label còn lại
`praise`, `complaint`, `unclassified` KHÔNG cần knowledge layer — cần chốt end-to-end tới `.eml`
để admin paste vào Outlook (chưa có luồng đẩy thẳng Graph trong scope này).

Khoảng trống hiện tại:
1. `respond.py` mỗi nhánh ack chỉ có **1 câu cứng** → email trùng lặp, robot.
2. `render_email.py` chỉ VI, tối giản → chưa khớp gold template song ngữ `template/email_temp.py`.
3. Chưa có flow batch nối `pipeline → EmlSink` để xuất hàng loạt `.eml`.
4. `DEFAULT_CATALOG` trong `catalog.py` trỏ tới thư mục không tồn tại (`092038_llm`).
5. Thiếu asset `template/icon TAI.png` (logo).

## Requirements

- Sample bank cảm ơn (praise) / xin lỗi (complaint) / ack trung tính (unclassified) **có sẵn**,
  PM review được, song ngữ VI+EN, KHÔNG gọi LLM lúc chạy.
- Email `.eml` khớp gold template `template/email_temp.py` + `template/skill_create_email.md`
  (song ngữ, box feedback, footer đầy đủ CC/support/SharePoint, logo `cid:tai_logo`, `X-Unsent:1`).
- Batch: từ feedback CSV → classify → respond → `.eml` theo folder category.
- Tuân style rule skill: KHÔNG em-dash, ấm/tự nhiên, KHÔNG emoji, viết đúng "TÀI Studio".

## Decisions made (chốt với user 2026-08-27)

1. **Sample bank YAML tĩnh**, chọn xoay vòng deterministic theo nội dung feedback (idempotent).
2. **Gold template song ngữ đầy đủ** (nâng `render_email.py`).
3. **Unclassified vẫn draft ack trung tính an toàn** (khớp §4.3 "ack ngắn, trung tính" → folder ⚠ Unclassified).

## Architecture reference
- Module: `inference.draft` (B2 — `respond.py`), `inference.deliver` (B3 — `render_email.py` + `EmlSink` trong `deliver.py`)
- Sections: docs/architecture.md §3 (Trách nhiệm module: inference.draft, inference.deliver),
  §4.2 Flow B (draft → deliver), §4.3 Threshold routing (ack_only: praise→acknowledge, complaint→apology,
  unclassified→ack trung tính → folder ⚠ Unclassified + unclassified_pool), §5 (Email fallback .eml + X-Unsent:1)
- Impl doc: docs/impl-phase2-auto-feedback-flow.md §3.2 (template theo action_type), §5 (nhánh ack), §6 (DraftSink: EmlSink)
- Data contract: feedback_processing §4.5 (idempotency — ở đây dùng deterministic pick theo nội dung feedback)
- Template rule: template/skill_create_email.md, template/email_temp.py

## Implementation approach

| # | File | Thay đổi |
|---|------|----------|
| 1 | `src/03_inference/reply_samples.yaml` (NEW) | Bank song ngữ 3 nhóm `thank_you`/`apology`/`neutral_ack`, mỗi mẫu `vi/en → {greeting,body,closing}`, placeholder `{name}`/`{feedback_summary}` |
| 2 | `src/03_inference/reply_samples.py` (NEW) | `load_bank()` + `pick(group, key)` chọn `hash(key)%n` (deterministic, idempotent) |
| 3 | `src/03_inference/respond.py` (EDIT) | thêm `body_en`; 3 nhánh ack lấy copy từ bank, điền `{feedback_summary}`, giữ `{name}` |
| 4 | `src/03_inference/render_email.py` (EDIT) | gold template song ngữ (VI + separator + EN + box feedback + footer), giữ block INTERNAL + `strip_internal_block` |
| 5 | `src/03_inference/deliver.py` (EDIT) | `build_draft(..., name)` điền `{name}`; CC mặc định từ `render_email.CC_LIST` |
| 6 | `src/03_inference/catalog.py` (EDIT) | fix `DEFAULT_CATALOG` → `20260826_180647_llm/catalog_a.json` |
| 7 | `src/03_inference/pipeline.py` (EDIT) | `--eml OUT_DIR --ack-only`: export `.eml` nhánh ack; đọc `user_email`/`user_name` nếu có |
| 8 | `src/03_inference/tests_respond.py` (EDIT) | test praise→thank_you, complaint→apology, unclassified→neutral_ack, `body_en` có nội dung, `{name}` còn placeholder |

## Non-goals (giữ ranh giới architecture)
- KHÔNG đẩy thẳng Outlook qua Graph (dùng `.eml` fallback — §5).
- KHÔNG xử lý `report_bug`/`request_feature`/`how_to` (cần knowledge layer — phase sau).
- KHÔNG auto-send, KHÔNG tạo ticket Jira.

## Dependency
- Asset `template/icon TAI.png` do user cấp; thiếu thì email vẫn render (logo None graceful).

## Verification
1. `python reply_samples.py` — self-test pick deterministic mỗi nhóm.
2. `python -m pytest tests_respond.py` — routing + copy + song ngữ + placeholder.
3. `python deliver.py --eml <scratch>` — 1 `.eml` demo, kiểm song ngữ/footer/logo/INTERNAL-sidecar.
4. `python pipeline.py --eml <OUT> --ack-only --limit 10` (cần LM Studio embed) — folder `.eml` theo category.
5. Mở `.eml` bằng Outlook → compose mode (X-Unsent:1), render đúng.
