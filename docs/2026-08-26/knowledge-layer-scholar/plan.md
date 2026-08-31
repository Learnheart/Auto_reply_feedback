---
author: klinh2212112@gmail.com
date: 2026-08-26
status: done  # verify SIT OK: notebook 0250b1fe-de9c-4756-add5-9e2a273bb3f2, 23 source ready, RAG + citation chạy
agents: ingest-sync
summary: Luồng dựng knowledge layer — gom Confluence userguide + Jira Agentic Platform backlog, nạp vào Scholar như 1 notebook cho inference
---

## Problem statement

Quá trình inference (trả lời feedback user về sản phẩm) cần một **knowledge layer** gồm 2 nguồn:

1. **Confluence userguide** — cây page `395774795` "TÀI Studio — User guide" (space `DataEngineering`)
   + 10 page con (mỗi agent 1 page). Đã có `fetch_userguide()`.
2. **Jira backlog** — board **"FAI. Team 01: Agentic Platform"** (id `5042`, scrum, project `TSFAI`).
   MCP không có tool lấy thẳng board-backlog ⇒ dùng JQL proxy
   `project = TSFAI AND summary ~ "Agentic Platform" AND statusCategory != Done` (8 epic/story roadmap).

Hai nguồn này được **nạp vào Scholar dưới dạng 1 notebook** → notebook đó chính là knowledge layer để
`inference.draft` (B2) query khi soạn email trả lời.

## Requirements

- R1. `build_knowledge_layer(notebook_id=None, dry_run=False)` gom 2 nguồn → tạo/nạp Scholar notebook.
- R2. Userguide: mỗi page Confluence = 1 text source (title + markdown) → citation theo từng agent.
- R3. Backlog: mỗi issue = 1 text source (key + summary + status + type + description) → citation theo ticket.
- R4. Idempotent-ish: cho phép truyền `--notebook <id>` để nạp lại vào notebook có sẵn; nếu không thì
      tạo notebook mới và IN `notebook_id` để inference dùng lại.
- R5. `--dry-run` chỉ fetch + in nguồn (không đụng Scholar). `--ask "<câu hỏi>"` để smoke-test truy vấn.
- R6. Chờ ingestion `ready` trước khi coi notebook là sẵn sàng (dùng `wait_ready`).

## Decisions made

- Module mới `src/02_knowledge/build_knowledge_layer.py` **orchestrate** 2 client đã có (DRY):
  `mcp_atlassian_test.fetch_userguide` / `.fetch_backlog` (nguồn) + `scholar_test.create_notebook` /
  `.add_text_source` / `.wait_ready` / `.ask` (đích). Không viết lại HTTP/auth.
- Backlog dùng scope **Agentic Platform** (khác spike trước dùng "Tai Studio"): tham số
  `name_filter="Agentic Platform"`. Bổ sung `description` vào `fetch_backlog` để source có nội dung.
- Granularity: 1 source / page và 1 source / issue → citation rõ ràng (thay vì gộp 1 khối lớn).
- Notebook: tạo mới + in id (mặc định); reuse qua `--notebook`. Chưa làm diffing/incremental
  re-index (thuộc job production).

## Architecture reference

- Module: `ingest-sync` (Job A) — "Đồng bộ userguide → Vector Search; backlog → backlog_ref"
  (§3 *Trách nhiệm từng module*). Đây là **bước dựng KNOWLEDGE LAYER** (§3 sơ đồ, khối KNOWLEDGE LAYER).
- Sections: docs/architecture.md §2 Input (Confluence userguide + Jira backlog), §3 (`ingest-sync`,
  KNOWLEDGE LAYER), §4.2 Flow B (B2 "retrieve chunk userguide" + "đối chiếu backlog"), §5 (Vector store).
- Impl doc: docs/impl-phase2-auto-feedback-flow.md (B2 RAG userguide + đối chiếu backlog).

### Ghi chú kiến trúc (rule 3.6)

1. **Knowledge store = Scholar notebook — NHẤT QUÁN với §5 "Vector store".** Scholar về bản chất là một
   **managed vector store**: nó tự lo chunk → embed → vector index → retrieve → citation. Đây chỉ là
   **lựa chọn hiện thực** của "Vector store" (§5) và "KNOWLEDGE LAYER" (§3), KHÔNG phải lệch kiến trúc:
   thay vì tự dựng pipeline Databricks Vector Search + `backlog_ref` Delta, ta dùng Scholar App đóng gói
   sẵn. Ranh giới/luồng (B2 retrieve userguide + đối chiếu backlog) giữ nguyên; chỉ đổi *công nghệ* của
   tầng knowledge. Khi productionize nên ghi chú §5 rằng "Vector store = Scholar (managed)" + thêm khái
   niệm `notebook_id` là handle của knowledge layer (thay `backlog_ref` như một bảng đọc riêng).
2. **Nguồn userguide:** Confluence (không phải OneDrive/Graph như §2) — đã nêu ở
   `docs/2026-08-26/confluence-userguide-fetch/plan.md`.
3. **Auth/transport:** MCP-Atlassian + Scholar HTTPS bằng U2M SSO (`tcb-agent-sit`), không phải Jira
   REST + service principal (§5). Spike đọc, chưa phải job.
4. **Backlog scope là proxy:** board 5042 backlog lấy gần đúng bằng JQL summary-prefix (MCP thiếu tool
   board-backlog). Cần xác nhận filter chuẩn của board trước khi productionize.

## Implementation approach

1. `fetch_backlog`: thêm `description` vào fields + output (source backlog có nội dung).
2. `build_knowledge_layer.py`:
   - `userguide_sources()` → [(title, markdown)] từ `fetch_userguide`.
   - `backlog_sources(name_filter)` → [(title, text)] từ `fetch_backlog` (format key/summary/status/type/desc).
   - `build_knowledge_layer(notebook_id, dry_run, name, name_filter)` → create/reuse notebook, add sources,
     `wait_ready`, return notebook_id.
   - CLI: `--notebook`, `--dry-run`, `--ask`, `--name`.
3. Verify SIT: `--dry-run` (đếm nguồn) → chạy thật (tạo notebook, ready) → `--ask` smoke-test.
4. CHANGELOG `[ingest-sync]`.
