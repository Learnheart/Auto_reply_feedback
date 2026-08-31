---
author: klinh2212112@gmail.com
date: 2026-08-26
status: in-progress
agents: inference.deliver
summary: B3 deliver — đặt email draft vào folder Outlook đặt tên theo category (intent) trong shared mailbox taistudio@ qua Microsoft Graph (service principal app-only), để PM duyệt/gửi
---

## Problem statement

Sau B2 (`respond.py` → `PersonalizedResponse`), cần **đưa draft vào Outlook**: mỗi feedback thành một email
nháp nằm trong **folder đặt tên theo category** (intent) của **shared mailbox `taistudio@techcombank.com.vn`**,
để PM mở, sửa nếu cần, rồi bấm Send (duyệt) hoặc bỏ (từ chối). Đây là `inference.deliver` (B3).

Câu hỏi cốt lõi user hỏi — "connect to Outlook và write email thế nào" — trả lời: **Microsoft Graph API**,
auth bằng **Azure AD service principal (client-credentials, app-only)**, `POST /users/{mailbox}/mailFolders/{id}/messages`
tạo draft trong folder theo intent. Không dùng SMTP (không đặt được draft vào folder + không đọc lại được Sent).

## Architecture reference

- **Module:** `inference.deliver` (B3).
- **Sections:** `docs/architecture.md` §3 *Trách nhiệm từng module* (`inference.deliver`: ensure mailFolder,
  POST draft qua Graph, ghi `draft_ref`, retry độc lập), §4.2 Flow B (B3), §4.5 Data layer
  (`feedback_processing.draft_status`/`draft_ref`), §5 Technology Stack (Microsoft Graph `msal`+`httpx`,
  Azure AD service principal, `.eml` fallback), §6.1 R4/R5 (INTERNAL leak, `X-Feedback-Id` khóa cứng).
- **Impl doc:** `docs/impl-phase2-auto-feedback-flow.md` §6 (`DraftSink` Protocol: `EmlSink` + `GraphSink`),
  §5 (block INTERNAL, marker `TAI-INTERNAL-DO-NOT-SEND`), §1 B-1/B-2/B-3 (asset logo, spike Graph, recipient name).
- **Data contract:** §4.5 `feedback_processing.draft_status` (state machine `NULL→pending_deliver→drafted|error`),
  `draft_ref` = Graph `messageId`. Idempotency key `feedback_id`; `X-Feedback-Id` khóa cứng cho `outcome-sync`.

## Requirements

- **R1.** `DraftSink` Protocol (impl §6): `ensure_folder(name) -> folder_id` (idempotent theo displayName) +
  `deliver(draft) -> DraftRef`. Hai implement: `GraphSink` (primary) + `EmlSink` (fallback, không cần cred).
- **R2. GraphSink app-only:** msal `ConfidentialClientApplication.acquire_token_for_client(['.../.default'])`
  → bearer; httpx gọi Graph trên `/users/{SHARED_MAILBOX}`. Config (tenant/client id/secret/mailbox) từ **env**,
  KHÔNG hardcode secret.
- **R3.** Folder theo **category = intent_id** (unclassified → folder `⚠ Unclassified`). `ensure_folder` idempotent:
  tìm theo `displayName`, thiếu thì tạo. Cache id trong phiên để không query lại.
- **R4.** Tạo draft: `POST /users/{mbx}/mailFolders/{id}/messages` với `subject` (hằng số, skill:15), `body` HTML,
  `toRecipients` = user feedback, `singleValueExtendedProperties` nhúng **`X-Feedback-Id`** (khóa cứng R5).
  Logo inline `cid:tai_logo` qua `fileAttachment isInline` NẾU có asset (B-1: `icon TAI.png` còn thiếu) — thiếu thì bỏ qua, không crash.
- **R5. Idempotency (impl §6):** chỉ deliver khi `draft_status == pending_deliver`; đọc trạng thái trước khi POST
  ⇒ retry sau 429 không tạo draft thứ hai. Trả `DraftRef(message_id, web_link)` để ghi `draft_ref`, set `drafted`.
- **R6.** Block INTERNAL đặt TRÊN CÙNG body, marker `TAI-INTERNAL-DO-NOT-SEND` (Job C grep). Render tách
  `strip_internal_block()` được (cho lint/outcome-sync sau).
- **R7.** Test offline (không cần cred): build message payload đúng schema + map folder-name + `EmlSink` ghi file.
  Live Graph cần env creds + `pip install msal` (chưa cài) ⇒ có `--dry-run` in payload không gửi.

## Decisions made

- **D1. App-only (service principal), KHÔNG delegated** (user chọn). Cần Azure app registration + **`Mail.ReadWrite`
  APPLICATION permission** + **Application Access Policy** giới hạn app chỉ vào `taistudio@` (nếu không, app-only có
  quyền ghi MỌI mailbox — bảo mật ngân hàng bắt buộc scope). Ghi rõ trong §Setup của module.
- **D2. Folder = `intent_id`** (category), không map lại tên. Đơn giản, khớp yêu cầu "folder với category name".
  `unclassified`/None → `⚠ Unclassified`. Cho override bằng dict config nếu sau muốn tên đẹp (how_to_usage...).
- **D3. `EmlSink` giữ làm fallback vĩnh viễn** (impl §6 / A2). Đi `.eml` thì INTERNAL ra **file sidecar**
  `<feedback_id>.internal.md`, body sạch (impl §5 — vì không có Job C phát hiện leak ở nhánh .eml).
- **D4. Render tối thiểu tại đây** (`render.py`): wrap `PersonalizedResponse.body_vi` vào khung HTML thương hiệu
  (reuse cấu trúc `template/email_temp.py`). Render layer đầy đủ (song ngữ + golden test + lint) là Phase 2 §3,
  làm sau; B3 chỉ cần một body HTML hợp lệ để POST.
- **D5. `X-Feedback-Id`** qua `singleValueExtendedProperties` PS_PUBLIC_STRINGS
  (`"id": "String {00020329-0000-0000-C000-000000000046} Name X-Feedback-Id"`). **Spike ① (impl B-2)** phải kiểm
  property sống qua Send TRƯỚC khi tin vào outcome-sync (O4/O5 treo vào đây).

## Implementation approach

```
src/03_inference/delivery/
  graph_client.py  # R2: msal token (app-only) + httpx Graph REST: get/create mailFolder, create draft message
  render.py        # D4/R6: PersonalizedResponse -> (subject, html) + block INTERNAL + strip_internal_block()
  sinks.py         # R1: DraftSink Protocol, Draft/DraftRef, GraphSink, EmlSink (+ sidecar INTERNAL)
  deliver.py       # orchestrate: (response, feedback_meta) -> pick folder -> sink.deliver; CLI (--dry-run/--eml)
  tests_delivery.py# R7: payload schema + folder map + EmlSink, offline
```

Thứ tự: `graph_client` → `render` → `sinks` → `deliver` → test. Verify: test offline PASS; live Graph cần
`pip install msal` + env (`AZ_TENANT_ID`/`AZ_CLIENT_ID`/`AZ_CLIENT_SECRET`/`SHARED_MAILBOX`) + spike ① xác nhận
`X-Feedback-Id` sống qua Send.
