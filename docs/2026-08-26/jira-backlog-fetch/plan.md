---
author: klinh2212112@gmail.com
date: 2026-08-26
status: done
agents: ingest-sync
summary: Spike helper lấy toàn bộ backlog Jira dự án tai-studio (TSFAI) qua MCP-Atlassian, tự phân trang
---

## Problem statement

Cần kéo backlog Jira của dự án **tai-studio** để đối chiếu feedback (đầu vào cho `inference.draft` B2:
"đối chiếu backlog") và để `ingest-sync` nạp `backlog_ref`. Kiểm tra cho thấy:

- "tai-studio" **không phải project key**. Công việc nằm trong project key **`TSFAI`**
  (`TS-AI FOUNDATIONS`), issue gắn tiền tố `[Tai Studio]` ở `summary`.
- Tool MCP `search_issues` (JQL) lấy được, nhưng:
  - trường `total` server **luôn trả `-1`** (không tính tổng) ⇒ không dùng để biết còn bao nhiêu;
  - `limit` tối đa **50/lần** ⇒ muốn lấy hết phải tự phân trang qua `start_at`;
  - JQL sai bị **nuốt lỗi** (trả `total:-1, issues:[]` giống hệt "không có quyền").

Script `mcp_atlassian_test.py` hiện chỉ in **một trang** (`cmd_call`), chưa gom hết backlog.

## Requirements

- R1. Một hàm `fetch_backlog(...)` trả về **toàn bộ** issue backlog tai-studio (tự phân trang tới
  khi trang trả về < page_size), không phụ thuộc `total`.
- R2. Định nghĩa "backlog" mặc định: `project = TSFAI AND summary ~ "Tai Studio"
  AND statusCategory != Done AND sprint is EMPTY` — cho phép override qua tham số.
- R3. Trả list dict sạch, field bám data contract `backlog_ref` (§4.5):
  `jira_key, summary, status, issuetype` (+ `priority` để tiện triage; **không** embed/synced_at —
  đó là việc của job ingest thật, không phải spike).
- R4. Có CLI `python mcp_atlassian_test.py backlog [name_filter]` để dump nhanh.
- R5. Không đoán "hết trang" bằng `total` (luôn -1); dừng khi `len(issues) < page_size`, có trần
  an toàn số trang để không lặp vô hạn.

## Decisions made

- **Đặt trong `src/knowledge/mcp_atlassian_test.py`**, tái dùng `rpc()` sẵn có (DRY) thay vì viết
  client MCP mới. Đây là **spike** đọc-thử, đúng tinh thần §6.3 ("spike trước khi viết logic").
- Lọc backlog bằng `summary ~ "Tai Studio"` (tín hiệu tốt nhất hiện có) thay vì label/epic — vì
  toàn bộ issue quan sát được đều mang tiền tố này; để tham số hoá cho lần sau.
- Phân trang: vòng lặp `start_at += page_size`, dừng khi trang < page_size; trần `max_pages`.

## Architecture reference

- Module: `ingest-sync` (Job A) — "backlog → `backlog_ref`" (§3 *Trách nhiệm từng module*). Đây là
  **nửa đọc (fetch)** của module, ở dạng spike; nửa ghi (embed → `backlog_ref` Delta) thuộc job
  production, ngoài scope spike này.
- Sections: docs/architecture.md §2 Input (dòng *Jira backlog* — `key, summary, status, issuetype`),
  §3 *Trách nhiệm từng module* (`ingest-sync`), §4.5 Data layer (`backlog_ref`), §5 Technology Stack
  (dòng *Jira*).
- Impl doc: docs/impl-phase2-auto-feedback-flow.md (B2 "đối chiếu backlog").
- Data contract: `backlog_ref(jira_key PK, summary, description, status, issuetype, embedding, synced_at)`
  — spike chỉ đọc `jira_key/summary/status/issuetype` (+priority), không ghi bảng.

### Điểm lệch kiến trúc (ghi rõ, không im lặng — rule 3.6)

- **Transport & auth:** §5 quy định production `ingest-sync` gọi **Jira REST API (`httpx`)** với
  **Azure AD service principal** (job không có người ngồi sau). Spike này gọi qua **MCP-Atlassian**
  bằng **U2M SSO token** (profile `tcb-agent-sit`) — vì mục đích là *kiểm chứng lấy được dữ liệu
  gì* bằng danh tính của dev, chưa phải job.
- **Không đổi data contract, không thêm module.** Vì chỉ là spike đọc-thử nằm trong `src/knowledge/`
  (cùng chỗ `mcp_atlassian_test.py`/`scholar_test.py`), **chưa** cần cập nhật `architecture.md`.
  Khi hiện thực `ingest-sync` thật: phải chuyển sang Jira REST + service principal theo §5 (hoặc,
  nếu chọn giữ MCP, DỪNG và cập nhật §5 trước — rule 3.6).

## Implementation approach

1. Thêm helper `fetch_backlog(name_filter, project, include_done, only_backlog_sprint, page_size,
   max_pages) -> list[dict]` vào `mcp_atlassian_test.py`: dựng JQL từ tham số, gọi `rpc("tools/call",
   ...search_issues)` theo trang, gom `issues`, phẳng hoá field, dừng khi trang ngắn.
2. Thêm `cmd_backlog(name_filter)` in bảng gọn + tổng số lấy được; nối vào `main()` với lệnh
   `backlog`.
3. Cập nhật docstring đầu file (thêm lệnh `backlog`) và sửa ví dụ tool cũ sai tên
   (`searchJiraIssuesUsingJql` → `search_issues`).
4. Verify: chạy `python3.13 mcp_atlassian_test.py backlog` trên SIT, đối chiếu số issue.
5. Cập nhật `CHANGELOG.md` (`Added [ingest-sync]`).
