# Auto User Feedback Email — Solution Architecture Design

| Field | Value |
|-------|-------|
| **Author** | Solution Architect |
| **Date** | 2026-08-24 |
| **Plan Version** | v3.0 |
| **Status** | Draft |
| **Product** | TÀI Studio (AI Foundation, Techcombank) |
| **Supersedes** | v2.0 (Job-based, discovery-in-system) |

### Changelog vs v2.0

| Thay đổi ở mức module | Lý do |
|---|---|
| **Gỡ `discovery` job ra khỏi ranh giới hệ thống** | Intent analysis chạy **một lần, offline**. Không còn là job có lịch. Databricks Jobs chỉ chứa intent đã chốt. |
| **Gỡ human gate lifecycle (`candidate→active→archived`)** | Không có version thứ hai trong scope này thì không có gì để chuyển trạng thái. Thay bằng **Intent Catalog** — một artifact tĩnh, version bằng git. |
| **`taxonomy_version` / `intent_mapping` → bỏ khỏi Phase 1** | Máy móc versioning chỉ có nghĩa khi refresh. Giữ lại `catalog_version` dạng string để không phải migrate khi re-run vào scope. |
| **`inference` job tách từ 2 → 3 task: `classify` → `draft` → `deliver`** | Tách sinh nội dung (đắt, LLM) khỏi đẩy ra Graph (rẻ, hay lỗi mạng). Graph fail thì retry `deliver` mà không phải trả tiền sinh lại draft. |
| **Thêm `unclassified_pool`** | Taxonomy đóng băng ⇒ không có cơ chế hấp thụ feedback lạ. Bảng này tích lũy chúng làm input sẵn sàng cho scope re-run sau. |
| Số job: **4 → 3** | `ingest-sync`, `inference`, `outcome-sync`. |

---

## 1. Goal & Objective

**Goal:** Tự động sinh email draft trả lời feedback user, phân loại theo bộ intent **đã được phân tích và chốt trước**, đặt vào đúng folder Outlook để PM duyệt và gửi.

**Objectives:**

| # | Objective | Cách đo |
|---|---|---|
| O1 | Intent Catalog được chốt **trước khi** hệ thống chạy production | Artifact tồn tại trong git + Delta, có người ký duyệt |
| O2 | Phân loại feedback mới với confidence đo được | Cosine similarity tới exemplar vector; phân bố 3 vùng ngưỡng |
| O3 | Mỗi feedback đủ điều kiện có đúng 1 draft trong đúng folder | Idempotency theo `feedback_id`; 0 draft trùng |
| O4 | Không rò rỉ thông tin nội bộ ra email user | 0 email trong Sent còn chứa marker `INTERNAL` |
| O5 | Thu được outcome approve / edit / reject | ≥90% draft xác định được outcome sau 7 ngày |
| O6 | Feedback → draft ≤ 24h | `feedback.created_at` → `drafted_at` |
| O7 | Feedback không khớp intent nào được **giữ lại**, không mất | 100% `flag=unclassified` có mặt trong `unclassified_pool` |

**Non-goal scope này:** re-run intent analysis, taxonomy versioning/mapping, auto-send, tự tạo ticket Jira, Databricks App.

---

## 2. Overview

### System boundary

Điểm quan trọng nhất của v3.0: **intent analysis nằm NGOÀI hệ thống.** Nó là một dự án phân tích riêng, đầu ra là một artifact. Hệ thống production nhận artifact đó như một **input tĩnh** — giống như nhận file config, không phải như gọi một service.

### Input

| Nguồn | Định dạng | Trường chính | Nhịp |
|---|---|---|---|
| **Intent Catalog** | YAML trong git + Delta table `intent_catalog` | `intent_id`, `label`, `description`, `action_type`, `email_template_id`, `exemplar_vectors`, `threshold_high`, `threshold_low` | **Một lần** (bàn giao) |
| **Feedback datalake** | Delta (có sẵn) | `feedback_id`, `user_email`, `content`, `agent`, `created_at` | Hàng ngày |
| **OneDrive userguide** | File qua Microsoft Graph | `driveItemId`, `lastModifiedDateTime`, nội dung | Theo lịch / on-change |
| **Jira backlog** | JSON qua Jira REST | `key`, `summary`, `status`, `issuetype` | Theo lịch |

### Output

| Đích | Định dạng | Nội dung |
|---|---|---|
| **Outlook shared mailbox** | Draft HTML trong `mailFolder` theo intent | Block INTERNAL (PM xóa) + thân email VI/EN + citation |
| `feedback_processing` | Delta row | intent, confidence, flag, draft ref, outcome |
| `unclassified_pool` | Delta row | Feedback không khớp intent nào — nguyên liệu cho scope sau |
| `development_insight` / `insight_theme` | Delta row | Insight functional/quality |

### Assumptions & Constraints

| # | Giả định | Nếu sai |
|---|---|---|
| A1 | Volume ~20–100 feedback/ngày | >200/ngày → PM không duyệt xuể bằng Outlook |
| A2 | Xin được Graph `Mail.ReadWrite` trên shared mailbox | Rơi về `.eml`: mất routing folder **và** mất `outcome-sync` |
| A3 | Người duyệt duy nhất là PM | Nhiều người → không có khóa chống trùng ở Outlook |
| A4 | Feedback lịch sử ≥ ~500 mẫu cho phân tích offline | Ít hơn → bỏ HDBSCAN, cho LLM đọc trực tiếp theo lô |
| A5 | PII được phép qua Databricks Model Serving nội bộ | Phải mask trước khi embed/prompt |
| A6 | **Phân bố intent ổn định trong ~6 tháng** | Sai → `unclassified` phình nhanh, phải kéo re-run vào sớm hơn dự kiến |
| A7 | 1 feedback → 1 email (không gộp theo user) | Muốn gộp → đổi khóa idempotency và template |

> **A6 là giả định mới và nguy hiểm nhất của v3.0.** Khi taxonomy đóng băng, hệ thống không có khả năng học nhãn mới. Đo `unclassified_rate` hàng tuần là điều kiện sống của giả định này (§6.1 R1).

---

## 3. High-Level Architecture

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 0 — OFFLINE INTENT ANALYSIS        (một lần · NGOÀI Databricks Jobs)     ║
║  Chạy trong notebook / môi trường phân tích. Không có lịch. Không có SLA.       ║
╚═══════════════════════════════════════════════════════════════════════════════╝
   ┌──────────────┐   ┌──────────┐   ┌───────────┐   ┌────────────┐   ┌─────────┐
   │ Feedback     │──▶│ Embedding│──▶│  HDBSCAN  │──▶│ LLM merge  │──▶│ LLM gen │
   │ lịch sử      │   │  Qwen3   │   │(over-seg) │   │  cụm       │   │ intent  │
   └──────────────┘   └──────────┘   └───────────┘   └────────────┘   └────┬────┘
                                                                            ▼
                                            ┌────────────────────────────────────┐
                                            │  PM + AI team REVIEW & CHỐT         │
                                            │  wording · gộp/tách · template map  │
                                            │  · chọn exemplar · calibrate ngưỡng │
                                            └───────────────┬────────────────────┘
                                                            ▼
                                            ┌────────────────────────────────────┐
                                            │  📦 INTENT CATALOG  (frozen)         │
                                            │  intents.yaml (git) + Delta table   │
                                            │  label · action_type · template_id  │
                                            │  exemplar_vectors · thresholds      │
                                            └───────────────┬────────────────────┘
  ══════════════════════ BÀN GIAO MỘT LẦN ═══════════════════│════════════════════
                                                            ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PRODUCTION — DATABRICKS JOBS               (chỉ chứa intent đã chốt)           ║
╚═══════════════════════════════════════════════════════════════════════════════╝

  SOURCE LAYER
  ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
  │ Feedback     │        │ OneDrive     │        │ Jira backlog │
  │ Datalake     │        │ userguide    │        │              │
  └──────┬───────┘        └──────┬───────┘        └──────┬───────┘
         │                       │                       │
         │                       ▼                       ▼
         │            ┌────────────────────────────────────────────┐
         │            │  JOB A: ingest-sync           (lịch: tuần) │
         │            │  chunk → embed → index KB · sync backlog    │
         │            └───────────────────┬────────────────────────┘
         │                                ▼
         │            ┌────────────────────────────────────────────┐
         │            │  KNOWLEDGE LAYER                            │
         │            │  Vector Search (userguide) · backlog_ref    │
         │            └───────────────────┬────────────────────────┘
         │                                │ retrieve
         ▼                                ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  JOB B: inference                                       (lịch: hàng ngày) │
  │                                                                            │
  │  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐      │
  │  │ TASK B1 classify │───▶│ TASK B2 draft    │───▶│ TASK B3 deliver  │      │
  │  │ embed feedback   │    │ RAG userguide    │    │ ensure mailFolder│      │
  │  │ cosine→exemplar  │    │ + backlog check  │    │ POST draft (Graph)│     │
  │  │ threshold routing│    │ + insight extract│    │ ghi draft_ref     │     │
  │  │ ghi classification│   │ render HTML→Delta│    │                   │     │
  │  └────────┬─────────┘    └─────────┬────────┘    └────────┬─────────┘      │
  └───────────┼────────────────────────┼──────────────────────┼────────────────┘
              │ đọc                    │                      ▼
              ▼                        │           ┌──────────────────────────┐
  ┌────────────────────────┐           │           │ OUTLOOK shared mailbox    │
  │ 📦 intent_catalog       │           │           │  📁 how_to_usage           │
  │    (read-only, tĩnh)   │           │           │  📁 bug_report             │
  └────────────────────────┘           │           │  📁 feature_request        │
                                       │           │  📁 ⚠ unclassified         │
                                       ▼           └────────────┬─────────────┘
                          ┌────────────────────────┐            │
                          │ unclassified_pool      │   PM: xóa block INTERNAL ·
                          │ (tích lũy cho scope    │   annotate · SEND
                          │  re-run sau)           │            │
                          └────────────────────────┘            │
              ┌─────────────────────────────────────────────────┘
              ▼
  ┌────────────────────────────────────┐       ┌─────────────────────────────┐
  │  JOB C: outcome-sync   (2×/ngày)   │──────▶│  DATA LAYER (Delta / UC)     │
  │  poll Drafts + Sent folder         │       │   feedback_processing        │
  │  → sent / edited / rejected        │       │   unclassified_pool          │
  │  → diff draft vs sent              │       │   development_insight        │
  │  → LEAK ALERT nếu Sent có INTERNAL │       │   insight_theme              │
  └────────────────────────────────────┘       │   metrics_event · backlog_ref│
                                               └──────────────┬───────────────┘
                                                              ▼
                                                    SQL dashboard (metrics)

  ┌───────────────────────────────────────────────────────────────────────────┐
  │ CROSS-CUTTING: Model Serving (Sonnet 4.6 · Haiku 4.5 · Qwen3-embedding)    │
  │ Unity Catalog · Secret scopes · structlog · Databricks Asset Bundles       │
  └───────────────────────────────────────────────────────────────────────────┘
```

### Trách nhiệm từng module

| Module | Trách nhiệm (một dòng) | Trong Databricks Job? |
|---|---|---|
| Offline intent analysis | Sinh và chốt bộ intent từ feedback lịch sử — chạy một lần | ❌ Ngoài hệ thống |
| **Intent Catalog** | Artifact tĩnh: định nghĩa intent + exemplar vector + ngưỡng; version bằng git tag | ❌ Input tĩnh |
| `ingest-sync` (Job A) | Đồng bộ userguide → Vector Search, backlog → `backlog_ref`; re-index khi `lastModifiedDateTime` đổi | ✅ |
| `inference.classify` (B1) | Embed feedback mới → cosine tới exemplar → gán intent + confidence → routing 3 vùng | ✅ |
| `inference.draft` (B2) | RAG userguide + đối chiếu backlog + trích insight → render HTML, **ghi vào Delta** (chưa đẩy đi) | ✅ |
| `inference.deliver` (B3) | Đảm bảo `mailFolder` tồn tại, POST draft qua Graph, ghi `draft_ref` — retry được độc lập | ✅ |
| `outcome-sync` (Job C) | Đối soát Drafts/Sent xác định outcome + phát hiện rò rỉ INTERNAL | ✅ |
| `unclassified_pool` | Tích lũy feedback không khớp intent nào — bàn giao cho scope re-run | ✅ (bảng) |
| `shared` (library) | Client Model Serving / Graph / Jira, config, pydantic models, Delta helper | ✅ (dùng chung) |

---

## 4. Data Flow

### 4.1 Flow A — Bàn giao Intent Catalog (một lần)

Phân tích offline kết thúc bằng một artifact được commit vào git và load vào Delta. Sau bước này, phân tích không còn tham gia vận hành.

```
┌──────────┐   ┌─────────────┐   ┌───────────┐   ┌──────────┐   ┌──────────────┐
│ AI team  │   │ Analysis    │   │ PM        │   │  git     │   │ Delta        │
│ (analyst)│   │ notebook    │   │ (approver)│   │ repo     │   │intent_catalog│
└────┬─────┘   └──────┬──────┘   └─────┬─────┘   └────┬─────┘   └──────┬───────┘
     │ chạy phân tích │                │              │                │
     │───────────────>│                │              │                │
     │                │ embed→HDBSCAN→LLM merge→gen   │                │
     │                │────┐           │              │                │
     │                │<───┘ K intent ứng viên        │                │
     │  bảng review   │                │              │                │
     │<───────────────│                │              │                │
     │ trình PM duyệt │                │              │                │
     │──────────────────────────────>  │              │                │
     │                │  chỉnh wording · gộp/tách     │                │
     │                │  · chọn template · duyệt      │                │
     │<─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │              │                │
     │ chọn exemplar (3-5 mẫu/intent) │              │                │
     │ calibrate high/low trên holdout│              │                │
     │────┐           │                │              │                │
     │<───┘           │                │              │                │
     │ commit intents.yaml + vectors  │              │                │
     │───────────────────────────────────────────────>│                │
     │                │                │   CI: load vào Delta          │
     │                │                │              │───────────────>│
     │                │                │              │   ✅ frozen     │
     │<─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
```

> Sau mũi tên cuối, **`intent_catalog` là read-only với toàn bộ production.** Không job nào được ghi vào nó. Muốn đổi intent = sửa git + deploy, không phải sửa dữ liệu.

### 4.2 Flow B — Inference hằng ngày (happy path)

Ba task nối tiếp trong một job. Mỗi task ghi trạng thái vào Delta trước khi task sau chạy, nên retry được từng chặng.

```
┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐ ┌────────┐
│Scheduler│ │B1 classify│ │intent_   │ │B2 draft  │ │Vector   │ │B3      │ │ Delta  │
│  02:00  │ │          │ │catalog   │ │          │ │Search KB│ │deliver │ │ state  │
└────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬────┘ └───┬────┘ └───┬────┘
     │ trigger   │            │            │            │          │          │
     │──────────>│            │            │            │          │          │
     │           │ SELECT feedback chưa xử lý (anti-join state)    │          │
     │           │───────────────────────────────────────────────────────────>│
     │           │            │        M feedback mới  │            │          │
     │           │<───────────────────────────────────────────────────────────│
     │           │ load exemplar vectors + thresholds  │            │          │
     │           │───────────>│            │            │          │          │
     │           │  catalog   │            │            │          │          │
     │           │<───────────│            │            │          │          │
     │           │ embed + max-cosine → intent, confidence         │          │
     │           │────┐       │            │            │          │          │
     │           │<───┘       │            │            │          │          │
     │           │ INSERT classification (flag=ok)      │          │          │
     │           │───────────────────────────────────────────────────────────>│
     │           │ B1 done ──▶│            │            │          │          │
     │           │            │            │ retrieve chunk userguide         │
     │           │            │            │───────────>│          │          │
     │           │            │            │ chunks + citation      │          │
     │           │            │            │<───────────│          │          │
     │           │            │            │ đối chiếu backlog_ref (nội bộ)   │
     │           │            │            │─────────────────────────────────>│
     │           │            │            │   ticket match / none │          │
     │           │            │            │<─────────────────────────────────│
     │           │            │            │ LLM render body VI+EN + INTERNAL │
     │           │            │            │────┐       │          │          │
     │           │            │            │<───┘       │          │          │
     │           │            │            │ UPDATE draft_body_html, insight   │
     │           │            │            │─────────────────────────────────>│
     │           │            │            │ B2 done ──▶│          │          │
     │           │            │            │            │ đọc draft chưa đẩy  │
     │           │            │            │            │<────────────────────│
     │           │            │            │            │ ensure mailFolder   │
     │           │            │            │            │ POST /messages      │
     │           │            │            │            │────┐     │          │
     │           │            │            │            │<───┘ messageId      │
     │           │            │            │            │ UPDATE draft_ref,   │
     │           │            │            │            │ status=drafted      │
     │           │            │            │            │────────────────────>│
```

> **Vì sao tách B2 và B3:** B2 tốn tiền (RAG + Sonnet render), B3 hay lỗi (mạng, throttle Graph). Nếu gộp, một lỗi 429 của Graph buộc bạn sinh lại toàn bộ draft. Tách ra thì retry B3 là đủ, và `draft_body_html` đã nằm an toàn trong Delta.

### 4.3 Flow C — Threshold routing với taxonomy đóng băng

```
                      ┌────────────────────────────┐
                      │ confidence c = max cosine   │
                      │ tới exemplar của intent i   │
                      └─────────────┬──────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       │ c ≥ high                   │ low ≤ c < high             │ c < low
       ▼                            ▼                            ▼
┌────────────────┐        ┌─────────────────────┐      ┌──────────────────────┐
│ flag = ok       │        │ flag = low_confidence│      │ flag = unclassified  │
│ draft đầy đủ    │        │ draft + cờ ⚠ trong   │      │ KHÔNG đoán nhãn      │
│                │        │ block INTERNAL       │      │ ack ngắn, trung tính │
└───────┬────────┘        └──────────┬──────────┘      └──────────┬───────────┘
        ▼                            ▼                            ▼
 📁 <intent folder>          📁 <intent folder>           📁 ⚠ Unclassified
                                                                  │
                                                                  ▼
                                                    ┌──────────────────────────┐
                                                    │  unclassified_pool       │
                                                    │  (Delta, append-only)    │
                                                    │  ┌────────────────────┐  │
                                                    │  │ ⚠ DEAD END scope   │  │
                                                    │  │   này — chờ re-run │  │
                                                    │  └────────────────────┘  │
                                                    └──────────────────────────┘
```

> Trong v2.0, nhánh này quay về Discovery kỳ sau. Trong v3.0 nó **không quay lại đâu cả** — chỉ tích lũy. Đó là cái giá của việc đóng băng taxonomy, và `unclassified_rate` là chỉ số phải theo dõi sát nhất (§6.1 R1).

### 4.4 Flow D — Outcome sync

```
┌─────────┐  ┌──────────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐
│Scheduler│  │ outcome-sync │  │ Graph API│  │  Delta   │  │  Alert  │
│ 12h/18h │  │              │  │(mailbox) │  │  state   │  │ channel │
└────┬────┘  └──────┬───────┘  └────┬─────┘  └────┬─────┘  └────┬────┘
     │ trigger      │               │             │             │
     │─────────────>│               │             │             │
     │              │ đọc draft outcome=pending   │             │
     │              │────────────────────────────>│             │
     │              │   list(feedback_id,draft_ref)             │
     │              │<────────────────────────────│             │
     │              │ GET /messages/{draft_ref}   │             │
     │              │──────────────────────────>  │             │
     │              │   200 (còn) hoặc 404 (mất)  │             │
     │              │<──────────────────────────  │             │
     │              │ GET /mailFolders/sentitems  │             │
     │              │  filter X-Feedback-Id       │             │
     │              │──────────────────────────>  │             │
     │              │   sent message | rỗng       │             │
     │              │<──────────────────────────  │             │
     │              │ suy outcome:                │             │
     │              │  200        → pending       │             │
     │              │  404 + Sent → sent          │             │
     │              │  404 + ∅    → rejected      │             │
     │              │────┐                        │             │
     │              │<───┘                        │             │
     │              │ diff(draft_body, sent_body) │             │
     │              │  → edit_distance, edited    │             │
     │              │────┐                        │             │
     │              │<───┘                        │             │
     │              │ UPDATE outcome + metrics_event            │
     │              │────────────────────────────>│             │
     │              │ nếu sent_body chứa "INTERNAL"             │
     │              │──────────────────────────────────────────>│
     │              │                             │  🚨 LEAK    │
```

### 4.5 Data layer

```sql
-- ARTIFACT TĨNH (read-only với mọi job)
intent_catalog(
  intent_id PK, catalog_version,          -- catalog_version = git tag, vd "v1"
  label, description, action_type,
  email_template_id,
  exemplar_vectors ARRAY<ARRAY<FLOAT>>,   -- 3-5 mẫu thật/intent, KHÔNG phải mean
  threshold_high FLOAT, threshold_low FLOAT,
  approved_by, approved_at
)

-- STATE (idempotency key = feedback_id)
feedback_processing(
  feedback_id PK,
  catalog_version,                        -- chừa sẵn cho scope re-run
  intent_id, confidence,
  flag,                                   -- ok | low_confidence | unclassified
  draft_body_html, draft_body_hash,       -- ghi bởi B2, đọc bởi B3
  draft_status,                           -- pending_deliver | drafted | error
  draft_ref,                              -- Graph messageId
  outcome,                                -- pending | sent | edited_sent | rejected
  edit_distance,
  classified_at, drafted_at, delivered_at, outcome_at
)

-- HẤP THỤ DRIFT (append-only, chờ scope sau)
unclassified_pool(
  feedback_id PK, content, agent,
  best_intent_id, best_confidence,        -- intent gần nhất dù dưới ngưỡng
  embedding, created_at
)

-- KNOWLEDGE
backlog_ref(jira_key PK, summary, description, status, issuetype, embedding, synced_at)

-- INSIGHT
development_insight(insight_id PK, feedback_id, agent, contribution_type, subtype,
                    summary, suggested_improvement, user_quote, impact,
                    theme_id, atlassian_ref, status, created_at)
insight_theme(theme_id PK, title, contribution_type, demand_count,
              first_seen, last_seen, priority_score, status)

-- METRICS
metrics_event(event_id PK, feedback_id, event_type, payload, created_at)
```

---

## 5. Technology Stack

| Layer | Techstack | Detail (why this choice) |
|-------|-----------|--------------------------|
| Ngôn ngữ | Python 3.12 | Hệ sinh thái embedding/LLM đầy đủ; khớp Databricks runtime; một ngôn ngữ cho cả 3 job + library phân tích |
| Dependency | `uv` + `pyproject.toml` | Lockfile deterministic, build nhanh trong CI; ra wheel để `python_wheel_task` gọi trực tiếp |
| **Phân tích offline** | Databricks notebook (ad-hoc, không lịch) | Chạy một lần nên không cần đóng gói thành job. Notebook giữ được cả code lẫn kết quả review để audit về sau — quan trọng vì đây là artifact PM đã ký duyệt |
| **Intent Catalog** | YAML trong git + bảng Delta | Git cho phép review qua PR và biết ai đổi gì; Delta cho job đọc nhanh. **Nguồn sự thật là git**, Delta chỉ là bản load — tránh trường hợp ai đó sửa thẳng bảng rồi không ai biết |
| Orchestration | Databricks Jobs / Workflows | Có sẵn, không dựng thêm Airflow. Multi-task DAG cho phép `classify→draft→deliver` retry từng chặng — chính là lý do chọn thay vì gọi tuần tự trong một script |
| Compute | Serverless / job cluster nhỏ | Job chạy rồi tắt, không trả tiền idle. **Không còn HDBSCAN trong production** nên nhu cầu RAM giảm hẳn so với v2.0 |
| LLM (draft + insight) | Model Serving `claude-sonnet-4-6-sit-tai` | Viết email song ngữ có văn phong và trích insight cần suy luận ngữ nghĩa. Endpoint nội bộ ⇒ PII không rời nền tảng |
| LLM (dự phòng batch) | Model Serving `claude-haiku-4-5-sit-tai` | Cho nhánh few-shot classify nếu embedding tỏ ra yếu, hoặc ack ngắn cho `unclassified` — rẻ hơn nhiều ở nơi không cần suy luận sâu |
| Embedding | Model Serving `databricks-qwen3-embedding-0-6b` | Đa ngôn ngữ (feedback VI/EN lẫn lộn). **Bắt buộc dùng đúng model đã dùng lúc phân tích offline** — exemplar vector chỉ có nghĩa trong cùng không gian vector |
| Vector store | Databricks Vector Search | Sync trực tiếp từ Delta nên không phải tự viết pipeline đồng bộ index; nằm trong UC nên thừa hưởng phân quyền |
| Data store | Delta Lake / Unity Catalog | ACID + time travel để truy vết draft sai; UC cho governance và lineage — gần như bắt buộc trong môi trường ngân hàng |
| Schema | `pydantic` v2 | Ép structured output của LLM về schema chặt; fail sớm thay vì ghi rác vào Delta |
| Config | `pydantic-settings` + job parameters | Window, model name, tên folder nằm ở config. Ngưỡng thì nằm trong catalog vì chúng thuộc về intent, không thuộc về run |
| Email delivery | Microsoft Graph API (`msal` + `httpx`) | Lựa chọn duy nhất đặt được draft vào folder theo intent, và là điều kiện tiên quyết để `outcome-sync` đọc Sent |
| Email fallback | `.eml` + `X-Unsent:1` | Nếu A2 sai. Mất routing folder **và** mất outcome tracking — không ngang giá, cần coi là phương án suy giảm |
| Jira | Jira REST API (`httpx`) | Chỉ đọc ở scope này; vài endpoint không đáng kéo SDK nặng |
| Secrets | Databricks secret scopes | Graph client secret, Jira token — không nằm trong code hay notebook |
| Auth (job → external) | Azure AD service principal | Job chạy không có người ngồi sau; tránh phụ thuộc tài khoản cá nhân PM |
| Deploy | Databricks Asset Bundles | 3 job trong một `databricks.yml`, deploy SIT → prod bằng một lệnh; định nghĩa job nằm trong git thay vì chỉnh tay trên UI |
| Test | `pytest` + mock endpoint | Unit test cho routing/threshold/render template — phần logic thuần, không cần LLM thật. Integration mock Graph để CI chạy offline |
| Observability | `structlog` + `metrics_event` + job alert | Log JSON query được; metric nghiệp vụ ghi vào Delta vì đó là dữ liệu sản phẩm chứ không phải debug output |
| Dashboard | Databricks SQL dashboard | Không dựng app ở scope này; SQL dashboard trên `metrics_event` đủ cho O5/O6/`unclassified_rate` với chi phí gần bằng không |

---

## 6. Expert Suggestion

### 6.1 Key risks & limitations

**R1 — Taxonomy đóng băng là nợ kỹ thuật có đồng hồ đếm ngược. Đây là rủi ro số một của v3.0.** Sản phẩm TÀI Studio đang phát triển: thêm agent mới, thêm tính năng, thì feedback về những thứ đó **không tồn tại trong dữ liệu lịch sử** nên không có intent tương ứng. Chúng sẽ rơi hết vào `unclassified`. Hệ thống không hỏng, nó **suy giảm âm thầm** — vẫn chạy, vẫn sinh draft, chỉ là ngày càng nhiều draft vô dụng.
*Giảm thiểu:* đặt `unclassified_rate` lên dashboard ngay từ ngày đầu và định trước một ngưỡng hành động (đề xuất: **vượt 20% trong 2 tuần liên tiếp ⇒ kéo scope re-run vào sprint kế**). Không có ngưỡng định trước thì không ai nhận ra lúc nào là "đủ tệ".

**R2 — Exemplar vector chết cứng theo embedding model.** `exemplar_vectors` trong catalog được sinh bởi một phiên bản `qwen3-embedding` cụ thể. Nếu Databricks nâng cấp endpoint hoặc bạn đổi model, vector cũ nằm ở không gian khác và confidence trở thành số vô nghĩa — mà **không có lỗi nào được ném ra**.
*Giảm thiểu:* ghi `embedding_model_name` + version vào `intent_catalog`; `classify` so sánh với model đang gọi và **fail loud** nếu lệch. Đây là một dòng if, và nó chặn một class lỗi rất khó debug.

**R3 — Dùng exemplar thay vì centroid (khuyến nghị đổi so với thiết kế cũ).** HDBSCAN là density-based nên cụm có thể lõm hoặc kéo dài; điểm trung bình có thể rơi ra ngoài cụm, khiến cosine tới centroid vô nghĩa. Vì taxonomy giờ là artifact do người chốt, bạn có cơ hội tốt hơn: **chọn tay 3–5 feedback thật đại diện nhất mỗi intent** làm exemplar, confidence = max cosine tới các exemplar đó. Vừa robust hơn với cụm phi cầu, vừa dễ giải thích cho PM ("gần với ví dụ này nhất"), vừa dễ vá — thêm một exemplar là một dòng YAML, không phải chạy lại clustering.

**R4 — Block INTERNAL vẫn nằm trong body email thật.** Cơ chế bảo vệ duy nhất là PM nhớ xóa. Thiết kế này bù bằng **phát hiện thay vì ngăn chặn** (`outcome-sync` cảnh báo). Chấp nhận được với một người duyệt ở volume nhỏ; **không** chấp nhận được nếu mở thêm người duyệt hoặc tiến tới auto-send.

**R5 — `outcome-sync` cần khóa cứng, không phải heuristic.** Graph không liên kết draft với message trong Sent sau khi gửi. Khớp bằng `(subject, recipient, thời gian)` sẽ sai khi PM sửa subject. *Giảm thiểu:* nhúng `X-Feedback-Id` vào `singleValueExtendedProperties` của draft và kiểm chứng nó sống sót qua bước Send — **POC việc này trước tiên**, vì O4 và O5 đều treo vào đó.

**R6 — Re-index KB âm thầm sai.** Userguide đổi mà index không đổi ⇒ RAG trả lời sai một cách tự tin, kèm citation trông thuyết phục. Failure mode nguy hiểm nhất vì nó trông giống thành công. *Giảm thiểu:* đưa `lastModifiedDateTime` của chunk vào citation; `ingest-sync` fail loud khi phát hiện lệch.

**R7 — Không có khóa chống trùng ở Outlook.** Nếu A3 sai, hai người có thể cùng gửi một draft. Outlook không giải quyết được ở tầng công cụ.

### 6.2 Trade-offs made & những gì đã cố tình hoãn

| Đánh đổi | Được | Mất | Lý do chấp nhận |
|---|---|---|---|
| Intent analysis offline, không phải job | Production đơn giản hẳn: 3 job thay vì 4, không HDBSCAN/UMAP trong runtime, không lifecycle versioning | Không tự học nhãn mới (R1) | Đúng nguyên tắc: **đừng tự động hóa việc bạn mới làm một lần**. Tự động hóa discovery trước khi biết nó chạy tốt là đầu tư mù |
| Catalog là artifact git, không phải bảng có thể ghi | Review qua PR, biết ai đổi gì, rollback bằng git revert | Đổi intent phải deploy, không sửa nóng được | Trong ngân hàng, "sửa nóng bộ nhãn đang phân loại email gửi khách" là thứ nên khó, không nên dễ |
| Tách `deliver` khỏi `draft` | Retry lỗi Graph không phải trả tiền sinh lại LLM | Thêm một task, thêm một trạng thái | Chi phí gần bằng không, lợi ích hiện ngay lần đầu Graph throttle |
| `unclassified_pool` chỉ tích lũy, không xử lý | Không mất dữ liệu; scope re-run có sẵn input | Chưa tạo ra giá trị gì ở scope này | Bảng append-only là chi phí thấp nhất để giữ cửa mở |
| Hoãn: re-run, versioning, app, auto-send, tự tạo ticket | Scope gọn, ship được | — | Tất cả đều two-way door, mở sau không phải viết lại |

### 6.3 Recommendations & next steps

**Thứ tự triển khai — mỗi bước là một cửa chặn, đừng đi tiếp khi bước trước chưa xong:**

1. **Spike Graph API (2–3 ngày).** Tạo folder, POST draft, gắn `singleValueExtendedProperties`, gửi tay, đọc lại từ Sent xem property còn không. Nếu thất bại thì R4 mất cơ chế phát hiện và R5 mất khóa cứng — **cả thiết kế phải xem lại**. Làm trước khi viết bất cứ logic nào.
2. **Đếm feedback lịch sử.** Một câu SQL kiểm chứng A4. Kết quả quyết định phân tích offline đi đường HDBSCAN hay đường prompt trực tiếp.
3. **Chạy phân tích offline đến khi ra Intent Catalog v1.** Đây là cửa chặn thật: production không có gì để build khi chưa có catalog. Đừng viết `classify` trước bước này — bạn sẽ đoán sai schema.
4. **Calibrate ngưỡng trên holdout, ngay trong bước phân tích.** Vẽ phân bố confidence của mẫu đúng và mẫu sai. Nếu hai phân bố chồng lên nhau, quay lại R3 và đổi cách chọn exemplar — đừng chữa bằng cách vặn ngưỡng.
5. **Chạy shadow một tuần.** Sinh draft nhưng đẩy hết vào folder `_shadow`, PM đọc mà không gửi. So draft của hệ thống với câu trả lời PM tự viết. Đây là cách rẻ nhất để biết chất lượng draft trước khi nó chạm user thật.
6. **Bật production cho 1–2 intent an toàn nhất trước** (thường là `how_to_usage`), phần còn lại vẫn vào `_shadow`. Mở rộng dần theo `edit_distance` từng intent.

**Theo dõi liên tục:** `unclassified_rate` (chỉ số sống còn — R1), `edit_distance` trung bình theo intent (intent nào PM luôn phải sửa = template sai), số leak alert (phải luôn bằng 0), chi phí LLM trên mỗi feedback, tỉ lệ 3 vùng ngưỡng.

**Khi nào quay lại thiết kế này:** (a) `unclassified_rate` vượt ngưỡng đã định ⇒ kéo scope re-run vào; (b) volume vượt ~200/ngày hoặc có người duyệt thứ hai ⇒ cân nhắc app thay Outlook; (c) một intent đạt approve-không-sửa ổn định trên ngưỡng cao ⇒ mở auto-send riêng nhánh đó.

**Một điều cần chốt trước khi code:** giả định A7 (1 feedback → 1 email). Bạn từng nói tới hướng "gather feedback n-1 để tổng hợp". Nếu ý là **gộp nhiều feedback của cùng một user thành một email**, thì khóa idempotency, template và cả bước classify đều đổi — nên chốt bây giờ, không phải ở tuần thứ sáu.