---
author: klinh2212112@gmail.com
date: 2026-09-02
status: done
agents: ingest-sync, inference.classify, inference.draft, inference.deliver, outcome-sync, shared
summary: Cập nhật docs/architecture.md lên v4.0 — nguồn feedback Lakebase, knowledge 3 nguồn qua MCP-Atlassian nạp thẳng vào LLM, chuỗi guideline→backlog, delivery .eml local thay hoàn toàn Microsoft Graph, bỏ Job C outcome-sync, batch n-1 theo agent.
---

# Architecture v4.0 — Lakebase → classify 5 nhãn → knowledge qua MCP → .eml local

## Architecture reference

- Module: `ingest-sync` (Job A), `inference.classify` (B1), `inference.draft` (B2), `inference.deliver` (B3), `unclassified_pool`, `shared` — §3 *Trách nhiệm từng module*
- Sections: `docs/architecture.md` §2 Overview / System boundary, §3 High-Level Architecture, §4.2 Flow B, §4.3 Threshold routing, §4.4 Knowledge resolution, §4.5 Data layer, §5 Technology Stack, §6 Risks
- Impl doc: `docs/impl-phase2-auto-feedback-flow.md` §3.2 (chọn template theo `action_type` + hit); `docs/architecture/knowledge-layer.md` (Job A qua MCP-Atlassian)
- Data contract: `feedback_processing`, `unclassified_pool`, `userguide_page`, `backlog_ref`, **`changelog_ref` (mới)** — §4.5

> Đây là thay đổi **kiến trúc trước, code sau** theo rule 3.6: architecture.md được cập nhật TRƯỚC, code trong `src/03_inference` migrate theo sau.

## 1. Problem statement

Kiến trúc v3.3 mô tả một luồng đã lệch với hướng đi thật của sản phẩm ở 5 điểm:

1. Nguồn feedback ghi là "Feedback datalake (Delta)" — thực tế đọc từ **Lakebase**.
2. Taxonomy trong doc còn là bộ intent cũ (`how_to` / `report_bug` / `request_feature` / …), trong khi nhãn vàng đã chốt **5 nhãn**: `bug` · `new_feature` · `praise` · `complain` · `unclassified` (`data/golden/intent_explain.md`, PM chốt 2026-09-02).
3. Knowledge chỉ có 2 nguồn (userguide + backlog) và thứ tự phân giải chưa được định nghĩa. Thực tế cần **3 nguồn** (guideline theo agent · changelog · backlog chung project) lấy qua **MCP-Atlassian**, và cần một **chuỗi ưu tiên** rõ ràng.
4. Delivery treo vào Microsoft Graph + Outlook shared mailbox, kéo theo cả Job C `outcome-sync`. Thực tế **không xin được Azure app registration** ⇒ đường đi thật là ghi **file `.eml` vào folder trên máy** cho user review.
5. Nhịp chạy chưa nêu: hệ thống chạy **batch n-1** (xử lý feedback ngày D-1), và nhánh `bug`/`new_feature` gom **theo từng agent** để amortize context guideline.

## 2. Requirements

| # | Yêu cầu |
|---|---------|
| R-1 | Feedback đọc từ **Lakebase**, cắt theo ngày D-1 (batch n-1) |
| R-2 | Classify bằng **vector embedding**: cosine feedback ↔ sample có sẵn của từng nhãn (5 nhãn) |
| R-3 | `bug` / `new_feature` ⇒ query **guideline (theo agent) · changelog · backlog (chung project)** qua **MCP** |
| R-4 | Tài liệu nội bộ **nạp nguyên văn vào LLM làm context** — KHÔNG vector DB / retriever |
| R-5 | Reply theo **kịch bản gắn với nhãn**, xuất **`.eml`** vào folder tương ứng trên máy để user review |
| R-6 | `bug`/`new_feature` xử lý **theo lô của từng agent** |

## 3. Decisions (đã chốt với user 2026-09-02)

| # | Câu hỏi | Quyết định |
|---|---------|-----------|
| D-1 | Thứ tự phân giải knowledge cho `bug`/`new_feature` | **Guideline/changelog TRƯỚC, backlog SAU.** Tính năng đã tồn tại ⇒ hướng dẫn cách dùng (user hiểu nhầm). Chưa có ⇒ tra backlog ⇒ "đang phát triển/xử lý". Cả hai miss ⇒ `we_listen` (ghi nhận chung) |
| D-2 | Số phận Microsoft Graph + Job C `outcome-sync` | **`.eml` local thay thế HOÀN TOÀN Graph.** Gỡ Graph / `GraphSink` / `OutlookMacSink` / Job C và objective outcome khỏi architecture |
| D-3 | Nguồn guideline + changelog | **Cả 3 nguồn qua MCP-Atlassian** (Confluence userguide theo agent · Confluence changelog · Jira backlog) |
| D-4 | Định dạng file draft | `.eml` (user viết ".iml" — hiểu là `.eml`, khớp `EmlSink` đã có trong `src/03_inference/pipeline.py`) |
| D-5 | Phạm vi "chung project" vs "theo agent" | backlog = **chung project**; guideline = **theo agent**; changelog = **chung project** (giả định — đánh dấu A9 trong doc để PM xác nhận) |
| D-6 | Nhịp | batch **n-1**: mỗi run xử lý feedback có `created_at` thuộc ngày D-1 |

## 4. Implementation approach (chỉ tài liệu ở bước này)

`docs/architecture.md` v3.3 → **v4.0**:

1. **Header + Changelog vs v3.3** — bảng thay đổi mức module; giữ bảng lịch sử v2.0.
2. **§1** — Goal đổi đích (folder `.eml` local); objectives: gỡ O5 outcome-tracking (không còn cơ chế đo), thêm objective *grounding* (mọi khẳng định "đã có"/"đang làm" phải có citation `page/version` hoặc `jira_key`); non-goal thêm: auto-send, đẩy thẳng vào mailbox, vector DB cho tài liệu nội bộ.
3. **§2** — Input: Lakebase + 3 nguồn MCP-Atlassian + Intent Catalog. Output: cây folder `.eml` theo nhãn. Assumptions: bỏ A2 (Graph), thêm A8 (Lakebase là nguồn sự thật của feedback), A9 (changelog chung project), A10 (máy chạy batch có quyền ghi folder review).
4. **§3** — Vẽ lại sơ đồ: 3 job → **2 job** (`ingest-sync`, `inference`); bảng trách nhiệm module bỏ dòng `outcome-sync`, sửa mô tả B2/B3.
5. **§4** — 4.2 Flow B viết lại (batch n-1, gom theo agent); 4.3 routing 5 nhãn → folder, `unclassified` → `draft/` với template theo nhãn score cao nhất; **4.4 MỚI — chuỗi phân giải knowledge** (guideline → changelog → backlog → we_listen); 4.5 Flow outcome-sync **xoá**, thay bằng vòng review thủ công; 4.6 Data layer: `draft_ref` → `eml_path`, bỏ `outcome`/`edit_distance`, thêm bảng `changelog_ref`.
6. **§5** — thêm Lakebase, MCP-Atlassian; gỡ Graph/`msal`/Jira REST/Azure AD SP; `.eml` từ fallback → đường chính.
7. **§6** — R4 (leak INTERNAL) nâng mức vì mất cơ chế phát hiện + đề xuất sidecar `.internal.md`; R5 đổi thành *mất vòng phản hồi chất lượng*; R7 đổi thành *trùng file khi chạy nhiều máy*; thêm R8 (Lakebase ↔ Delta split), R9 (token budget 3 nguồn whole-content); §6.2/§6.3 cập nhật theo.

**Không đụng code trong lần này.** Code `src/03_inference` (`graph_client.py`, `outlook_mac.py`, `deliver.py`, `respond.py`, `pipeline.py`) migrate ở plan sau.

## 5. Follow-up đã biết

- `docs/architecture/knowledge-layer.md` chưa có nguồn **changelog** và chưa mô tả chuỗi D-1 ⇒ cập nhật ở phase wiring Job A.
- `docs/impl-phase2-auto-feedback-flow.md` còn treo vào Graph spike (B-2) ⇒ viết lại khi migrate code.
- `intent_catalog.action_type` cần đổi theo taxonomy 5 nhãn (`bug`/`new_feature` → `knowledge_chain`; `praise`/`complain` → `ack_only`; `unclassified` → `draft_review`).
