---
author: klinh2212112@gmail.com
date: 2026-08-26
status: done
agents: ingest-sync
summary: Spike lấy toàn bộ tài liệu userguide TÀI Studio trên Confluence (page 395774795 + con) qua MCP-Atlassian
---

## Problem statement

Ngoài backlog Jira, `ingest-sync` cần nạp **userguide** (nguồn kiến thức cho RAG ở `inference.draft`
B2). Userguide TÀI Studio nằm trên Confluence:

- Root page: `395774795` — "TÀI Studio — User guide", space `DataEngineering`.
  Link: https://techcombank.atlassian.net/wiki/spaces/DataEngineering/pages/395774795
- Có **10 page con** (mỗi agent 1 page: Summarizer, Powerpoint-er, Translator, Vaulter,
  Brainstormer, AI Visionary, Resume Evaluator, Graphics Designer, TÀI Super Agent, LLM Tracker).
  Cây **phẳng** (con không có cháu) — nhưng helper vẫn duyệt đệ quy cho bền vững.

Cần một cách lấy **tất cả** page trong cây này kèm nội dung (markdown), tự phân trang + đệ quy.

## Requirements

- R1. `fetch_userguide(root_page_id)` trả list page (gồm cả root) với nội dung markdown.
- R2. Duyệt **đệ quy** con (`get_page_children`), có `visited` chống lặp và `max_depth`/`max_pages`.
- R3. Phân trang children qua `start` (server giới hạn `limit` 1..50); không dựa số đếm phía server
      để quyết dừng — dừng khi trang trả về < limit.
- R4. Nội dung page lấy từ `get_page` → `metadata.content.value` (markdown, `convert_to_markdown=True`).
- R5. CLI `python mcp_atlassian_test.py userguide [root_page_id]` in cây + độ dài nội dung; hỗ trợ
      dump JSON để bước ingest/RAG dùng lại.
- R6. Trả list dict: `page_id, title, space_key, version, markdown` (bám nguồn KB, không ghi Delta).

## Decisions made

- Đặt cùng `src/02_knowledge/mcp_atlassian_test.py`, tái dùng `rpc()` + `_unwrap_search()` (DRY).
- Response `get_page` bọc nội dung ở `metadata.content.value`; `get_page_children` trả
  `{count, results:[{id,title,...}]}` — helper đọc theo đúng shape này.
- Đệ quy có `max_depth` (mặc định 5) + `visited` set; phân trang children tới khi trang ngắn.

## Architecture reference

- Module: `ingest-sync` (Job A) — "Đồng bộ userguide → Vector Search" (§3 *Trách nhiệm từng module*).
  Đây là **nửa đọc (fetch)** nguồn userguide, dạng spike; nửa chunk→embed→index Vector Search thuộc
  job production, ngoài scope spike.
- Sections: docs/architecture.md §2 Input (dòng *OneDrive userguide*), §3 (`ingest-sync`),
  §4.5 Data layer (KNOWLEDGE — Vector Search userguide), §5 Technology Stack.
- Impl doc: docs/impl-phase2-auto-feedback-flow.md (B2 RAG userguide).
- Data contract: userguide → Vector Search (chunk + citation). Spike chỉ đọc page (markdown),
  KHÔNG chunk/embed/ghi index.

### Điểm lệch kiến trúc (ghi rõ — rule 3.6)

- **Nguồn userguide:** §2 Input khai userguide đến từ **OneDrive qua Microsoft Graph**
  (`driveItemId`, `lastModifiedDateTime`). Thực tế userguide đang ở **Confluence** (space
  `DataEngineering`) — và root page còn trỏ tới một folder SharePoint/OneDrive, nên hai nguồn có thể
  song song. Spike này lấy từ **Confluence qua MCP-Atlassian + U2M SSO**.
- **Hệ quả nếu Confluence là nguồn chính thức:** phải cập nhật §2 Input (thêm nguồn Confluence:
  `page_id`, `version`, space) và §5 (thêm Confluence REST/MCP) TRƯỚC khi hiện thực `ingest-sync`
  thật; đồng thời `re-index khi lastModifiedDateTime đổi` (§3) chuyển sang theo `version` của page.
- Chưa đổi data contract, chưa thêm module ⇒ chưa sửa `architecture.md` ở bước spike này.

## Implementation approach

1. Thêm `fetch_userguide(root_page_id, max_depth, page_size, max_pages)` + `_page_markdown()` +
   `_iter_children()` vào `mcp_atlassian_test.py`.
2. Thêm `cmd_userguide(root_page_id)` in cây (title + len markdown) và lệnh `userguide` trong `main()`.
3. Verify trên SIT: `python3.13 src/02_knowledge/mcp_atlassian_test.py userguide` → 11 page, có nội dung.
4. Cập nhật docstring đầu file (thêm lệnh `userguide`) + `CHANGELOG.md` (`Added [ingest-sync]`).
