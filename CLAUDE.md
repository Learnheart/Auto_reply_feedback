# Agent Registry

> Each agent is a standalone App under `src/agents/`.
> How orchestrator connect with sub agent
> Each agent owns its own `AGENT.md` with full details (routes, env vars, architecture, deps).

---

## 🛑 IMPORTANT RULES

> **These rules are non-negotiable. AI agents and human contributors MUST follow them. Do NOT skip any step.**

### 1. Documentation-First: Plans BEFORE Code

All plans, design documents, and implementation specs **MUST** be stored in the `docs/` folder **BEFORE any implementation begins**. No exceptions.

```
docs/
└── YYYY-MM-DD/
    └── <feature-name>/
        ├── plan.md           # Implementation plan (REQUIRED — write FIRST)
        ├── design.md         # Technical design (if needed)
        └── notes.md          # Research notes, decisions (if needed)
```

Every doc **MUST** start with this metadata block:

```markdown
---
author: <name or email>
date: YYYY-MM-DD
status: draft | in-progress | done | abandoned
agents: <comma-separated agent IDs affected>
summary: <one-line description of what this is about>
---
```

- **ALWAYS** create `docs/YYYY-MM-DD/<feature-name>/plan.md` BEFORE writing any code
- Use the date the work started (ISO format: `YYYY-MM-DD`)
- Use kebab-case for feature names
- Every feature, enhancement, or bugfix that involves a plan MUST have a corresponding `docs/` entry
- The plan must include: metadata block, problem statement, requirements, decisions made, and implementation approach
- If you are an AI agent: **stop and create the plan document first**, then proceed with implementation

### 2. Changelog — Track Every Change

- **ALWAYS** update `CHANGELOG.md` when making any logic change
- Follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`
  - **MAJOR** — breaking changes (API contract changes, data model changes, removed features)
  - **MINOR** — new features, new agents, new shared components
  - **PATCH** — bug fixes, prompt tuning, styling tweaks, doc updates
- Group entries under: `Added`, `Changed`, `Fixed`, `Removed`
- Tag each entry with the affected agent(s) in brackets, e.g. `[summarizer]`, `[shared]`, `[all]`
- If you are an AI agent: **update CHANGELOG.md as part of every commit**
- **Enforced by Kiro hook**: `.kiro/hooks/check-changelog.sh` blocks `git commit` if `CHANGELOG.md` is not staged

---

### 3. Architecture-First — Mọi dòng code PHẢI tham chiếu kiến trúc

`docs/architecture.md` là **nguồn sự thật duy nhất** về ranh giới module, data flow, data layer và tech stack. Code không được đi trước kiến trúc.

**Bắt buộc trước khi code:**

1. **ĐỌC `docs/architecture.md` trước tiên** — cụ thể là §2 (Overview / System boundary), §3 (High-Level Architecture + bảng *Trách nhiệm từng module*), §4 (Data Flow + Data layer), §5 (Technology Stack). Kèm theo đó, đọc doc implementation của phase đang làm:
   - `docs/impl-phase1-intent-classification.md`
   - `docs/impl-phase2-auto-feedback-flow.md`
2. **Định vị module.** Mọi file code MỚI phải ánh xạ đúng **một** module đã có trong bảng *Trách nhiệm từng module* (`ingest-sync`, `inference.classify`, `inference.draft`, `inference.deliver`, `outcome-sync`, `unclassified_pool`, `shared`, Intent Catalog). Không tự ý đặt file ngoài các module này.
3. **Giữ đúng ranh giới hệ thống.** Những thứ architecture đã tuyên bố là *ngoài hệ thống* hoặc *non-goal* (offline intent analysis, taxonomy versioning/mapping, auto-send, auto-tạo ticket Jira, Databricks App) **KHÔNG được implement** trong scope này.
4. **Trích dẫn trong tài liệu.** `docs/YYYY-MM-DD/<feature>/plan.md` phải có mục:
   ```markdown
   ## Architecture reference
   - Module: <tên module trong §3>
   - Sections: docs/architecture.md §<x.y> <tiêu đề>, §<x.y> <tiêu đề>
   - Impl doc: docs/impl-phase<N>-<...>.md §<mục>
   - Data contract: <bảng Delta / model pydantic liên quan, §4.5>
   ```
5. **Trích dẫn trong code.** Mỗi module/file chính mở đầu bằng docstring trỏ về kiến trúc:
   ```python
   """
   Module: inference.classify (B1)
   Architecture: docs/architecture.md §3 Trách nhiệm từng module, §4.3 Threshold routing
   Impl: docs/impl-phase1-intent-classification.md §3
   """
   ```
6. **Không lệch kiến trúc trong im lặng.** Nếu hiện thực cần khác architecture (thêm module, đổi data contract, đổi thứ tự flow, đổi stack) thì:
   - **DỪNG code**,
   - cập nhật `docs/architecture.md` trước (nêu rõ lý do + trade-off),
   - ghi vào `CHANGELOG.md`,
   - rồi mới code theo bản đã cập nhật.
7. **Data contract là ràng buộc cứng.** Tên bảng, tên trường, kiểu dữ liệu, khoá idempotency (`feedback_id`) phải khớp §4.5 Data layer. Muốn đổi ⇒ đi theo bước 6.

**Checklist bắt buộc trước mỗi lần commit code:**

- [ ] Đã đọc phần architecture liên quan
- [ ] File/code nằm đúng module trong §3
- [ ] Docstring có dòng `Architecture: docs/architecture.md §...`
- [ ] `plan.md` có mục `## Architecture reference`
- [ ] Không implement thứ nằm trong non-goal
- [ ] Nếu có lệch: `architecture.md` đã được cập nhật TRƯỚC

> Nếu bạn là AI agent: **không được viết code khi chưa trích dẫn được mục cụ thể trong `docs/architecture.md`.** Không tìm thấy chỗ đứng cho đoạn code trong kiến trúc ⇒ đó là tín hiệu phải sửa kiến trúc trước, không phải cứ thế viết.

---
