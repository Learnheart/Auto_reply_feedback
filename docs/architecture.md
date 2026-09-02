# Auto User Feedback Email — Solution Architecture Design

| Field                  | Value                                    |
| ---------------------- | ---------------------------------------- |
| **Author**       | Solution Architect                       |
| **Date**         | 2026-09-02                               |
| **Plan Version** | v4.0                                     |
| **Status**       | Draft                                    |
| **Product**      | TÀI Studio (AI Foundation, Techcombank) |
| **Supersedes**   | v3.3 (Graph/Outlook delivery · 2 nguồn knowledge) |

### Changelog vs v3.3

| Thay đổi ở mức module | Lý do |
| --- | --- |
| **Nguồn feedback: Delta datalake → `Lakebase`** | Feedback nằm ở Lakebase (Postgres quản trị bởi Databricks), không phải bảng Delta. Job B đọc trực tiếp bằng SQL, cắt theo ngày `D-1`. |
| **Taxonomy: bộ intent cũ → 5 nhãn đã chốt** | `bug` · `new_feature` · `praise` · `complain` · `unclassified`. Bỏ `how_to` — nó không tách được ở B1 vì sự thật nằm trong tài liệu chứ không nằm trong feedback (`docs/2026-08-31/intent-knowledge-coupling/design.md`). Hướng dẫn cách dùng nay là **một nhánh kết quả của B2**, không phải một nhãn của B1. |
| **Knowledge: 2 nguồn → 3 nguồn, tất cả qua MCP-Atlassian** | Thêm **changelog**. `ingest-sync` snapshot cả ba (guideline theo `agent` · changelog chung project · backlog chung project) qua một client MCP duy nhất, thay cho Jira REST + Confluence gọi rời. |
| **Thêm chuỗi phân giải knowledge có thứ tự (§4.4)** | v3.2 có 2 nguồn nhưng không định nghĩa nguồn nào thắng. v4.0 chốt: **guideline/changelog TRƯỚC → backlog SAU → `we_listen`**. Tính năng đã tồn tại thì phải hướng dẫn, không được hứa "đang phát triển". |
| **Delivery: Microsoft Graph / Outlook → file `.eml` trong folder local** | Không xin được Azure app registration. `.eml` từ *phương án suy giảm* (v3.3) trở thành **đường chính**: B3 ghi file vào folder theo nhãn, user mở bằng Outlook desktop để review và gửi tay. |
| **Gỡ Job C `outcome-sync` + objective outcome + objective leak-detection** | Không còn mailbox để poll Drafts/Sent ⇒ không có cách suy `sent / edited / rejected`, cũng không có cách phát hiện rò rỉ block INTERNAL. Đây là **mất mát thật**, ghi ở R4/R5 chứ không giấu đi. |
| Số job: **3 → 2** | `ingest-sync`, `inference`. |
| **Nhịp: batch `n-1`, nhánh knowledge gom theo `agent`** | Mỗi run xử lý feedback của ngày `D-1`. `bug`/`new_feature` gom theo `agent` để guideline của một agent chỉ nạp vào prompt **một lần** cho cả lô. |

<details>
<summary><b>Lịch sử: Changelog v2.0 → v3.3</b> (giữ để truy vết)</summary>

| Thay đổi ở mức module | Lý do |
| --- | --- |
| **Gỡ `discovery` job ra khỏi ranh giới hệ thống** | Intent analysis chạy **một lần, offline**. Không còn là job có lịch. |
| **Gỡ human gate lifecycle (`candidate→active→archived`)** | Không có version thứ hai trong scope thì không có gì để chuyển trạng thái. Thay bằng **Intent Catalog** — artifact tĩnh, version bằng git. |
| **`taxonomy_version` / `intent_mapping` → bỏ khỏi Phase 1** | Máy móc versioning chỉ có nghĩa khi refresh. Giữ `catalog_version` dạng string. |
| **`inference` tách 2 → 3 task: `classify` → `draft` → `deliver`** | Tách sinh nội dung (đắt) khỏi bước đẩy ra ngoài (rẻ, hay lỗi). |
| **Thêm `unclassified_pool`** | Taxonomy đóng băng ⇒ cần chỗ hấp thụ feedback lạ. |

Các mốc trung gian: **v3.1** userguide bỏ Vector Search → whole-page routing theo `agent`; **v3.2** backlog bỏ cosine → whole-set vào LLM, batch prompting; **v3.3** Haiku 4.5 làm model draft chính, embedding kéo từ LM Studio local về Databricks Model Serving.

</details>

---

## 1. Goal & Objective

**Goal:** Tự động sinh **file `.eml`** trả lời feedback user, phân loại theo **5 nhãn đã chốt trước**, đặt vào đúng folder trên máy để user/PM đọc, chỉnh và gửi tay bằng Outlook desktop.

**Objectives:**

| #  | Objective | Cách đo |
| -- | --------- | ------- |
| O1 | Intent Catalog được chốt **trước khi** hệ thống chạy production | Artifact tồn tại trong git + Delta, có người ký duyệt |
| O2 | Phân loại feedback mới theo 5 nhãn với confidence đo được | Cosine similarity tới sample của từng nhãn; phân bố 3 vùng ngưỡng; đối chiếu `data/golden/feedback_gold.csv` |
| O3 | Mỗi feedback đủ điều kiện có đúng 1 file `.eml` trong đúng folder | Idempotency theo `feedback_id` (tên file); 0 file trùng |
| O4 | **Mọi khẳng định về sản phẩm đều có nguồn** — không bịa "đã có tính năng" hay "đang phát triển" | 100% reply nhánh `bug`/`new_feature` có `source_ref` (`page_id@version` hoặc `jira_key`); không có nguồn ⇒ bắt buộc rơi về `we_listen` |
| O5 | Batch `D-1` hoàn tất trước giờ làm việc | `feedback.created_at` → `drafted_at` ≤ 24h |
| O6 | Feedback không khớp nhãn nào được **giữ lại**, không mất | 100% `flag=unclassified` có mặt trong `unclassified_pool` |

> **Đã gỡ khỏi objectives so với v3.3:** "thu được outcome approve / edit / reject" và "0 email trong Sent còn chứa marker `INTERNAL`". Cả hai đo bằng cách đọc ngược mailbox qua Graph — mà v4.0 không còn Graph. Xem R4/R5.

**Non-goal scope này:** re-run intent analysis, taxonomy versioning/mapping, **auto-send**, **đẩy draft thẳng vào mailbox (Graph / Outlook automation)**, **vector DB / retriever cho tài liệu nội bộ**, tự tạo ticket Jira, Databricks App.

---

## 2. Overview

### System boundary

Hai tuyên bố định hình toàn bộ v4.0:

1. **Intent analysis nằm NGOÀI hệ thống.** Nó là dự án phân tích riêng; production nhận đầu ra như một **input tĩnh** (giống file config), không phải như một service.
2. **Không có tầng retrieval cho tài liệu nội bộ.** Guideline, changelog, backlog được **snapshot nguyên văn và nạp thẳng vào prompt** làm context. Không chunk, không embed, không index, không vector DB. Embedding chỉ còn phục vụ **đúng một việc**: đo cosine feedback ↔ sample nhãn ở B1.

Hệ quả: hệ thống kết thúc ở **thư mục file `.eml` trên máy người duyệt.** Nó không chạm mailbox, không gửi email, và không biết chuyện gì xảy ra sau khi user mở file.

### Input

| Nguồn | Định dạng | Trường chính | Nhịp |
| ----- | --------- | ------------ | ---- |
| **Intent Catalog** | YAML trong git + Delta `intent_catalog` | `label`, `description`, `action_type`, `sample_vectors`, `threshold_high`, `threshold_low`, `embedding_model_name` | **Một lần** (bàn giao) |
| **Lakebase — user feedback** | Postgres (Databricks Lakebase), đọc bằng SQL | `feedback_id`, `user_email`, `user_name`, `content`, `agent`, `created_at` | Hàng ngày, lát cắt `D-1` |
| **Confluence — guideline** | Page markdown qua **MCP-Atlassian** | `page_id`, `title`, `version`, `markdown` — **một page ứng một `agent`** | Theo lịch (tuần) / on-change |
| **Confluence — changelog** | Page markdown qua **MCP-Atlassian** | `page_id`, `version`, `markdown` — **chung cả project** | Theo lịch (tuần) |
| **Jira — backlog** | JQL qua **MCP-Atlassian** | `jira_key`, `summary`, `description`, `status`, `issuetype` — **chung cả project** | Theo lịch (ngày) |

> Mẫu guideline thật đang nằm ở `data/guidelines/` (13 file, ~78.6k ký tự ≈ 25k token cho **cả kho**). Cả kho vừa một prompt — đó chính là lý do whole-content thắng retrieval ở quy mô này.

### Output

| Đích | Định dạng | Nội dung |
| ---- | --------- | -------- |
| **Folder review trên máy** | `.eml` (RFC 5322, HTML body song ngữ VI/EN) | Block INTERNAL (user xoá trước khi gửi) + thân email + citation nguồn |
| `feedback_processing` | Delta row | nhãn, confidence, flag, `source_ref`, `eml_path`, trạng thái |
| `unclassified_pool` | Delta row | Feedback không khớp nhãn nào — nguyên liệu cho scope re-run |
| `development_insight` / `insight_theme` | Delta row | Insight functional/quality |

Cây thư mục output — **folder chính là nhãn**:

```
<REVIEW_DIR>/
├── bug/            fb_0007.eml  fb_0031.eml  …
├── new_feature/    fb_0012.eml  …
├── praise/         fb_0004.eml  …
├── complain/       fb_0019.eml  …
└── unclassified/   fb_0088.eml  …   ← template dựng theo nhãn có score cao nhất
```

> Tên 5 folder là **config**, không phải hằng số trong code: `src/03_inference/email_templates.yaml` khối `folders` (§5 dòng Config). Đổi tên folder không phải đổi code.

### Assumptions & Constraints

| #  | Giả định | Nếu sai |
| -- | -------- | ------- |
| A1 | Volume ~20–100 feedback/ngày | >200/ngày → user không duyệt xuể bằng cách mở từng file |
| A2 | **Máy chạy batch có Outlook desktop mở được `.eml`, và có quyền ghi vào `REVIEW_DIR`** | Không mở được `.eml` ⇒ phải xuất HTML/PDF, mất luôn header người nhận |
| A3 | Người duyệt duy nhất là PM | Nhiều người → hai người có thể cùng gửi một file (R7) |
| A4 | Feedback lịch sử ≥ ~500 mẫu cho phân tích offline | Ít hơn → bỏ HDBSCAN, cho LLM đọc trực tiếp theo lô |
| A5 | PII được phép qua Databricks Model Serving nội bộ | Phải mask trước khi embed/prompt |
| A6 | **Phân bố nhãn ổn định trong ~6 tháng** | Sai → `unclassified` phình nhanh, phải kéo re-run vào sớm hơn dự kiến |
| A7 | 1 feedback → 1 email (không gộp theo user) | Muốn gộp → đổi khoá idempotency và template |
| A8 | **Lakebase là nguồn sự thật của feedback; `feedback_id` ổn định, `content` không bị sửa sau khi tạo** | `content` đổi sau khi đã sinh draft ⇒ draft nói về một feedback không còn tồn tại |
| A9 | **Changelog là tài liệu chung cả project** (không tách theo agent) | Nếu tách theo agent ⇒ đổi khoá `changelog_ref` giống `userguide_page` |
| A10 | **Cả 3 nguồn knowledge của một lô vừa context window của model draft** | Backlog/guideline phình ⇒ phải tiền lọc (R9) |

> **A6 vẫn là giả định nguy hiểm nhất.** Taxonomy đóng băng thì hệ thống không học được nhãn mới. Đo `unclassified_rate` hàng tuần là điều kiện sống của nó (§6.1 R1).
>
> **A2 thay cho A2 cũ (Graph `Mail.ReadWrite`).** Rẻ hơn hẳn về mặt xin quyền, đổi lại hệ thống mất hoàn toàn khả năng đọc ngược kết quả (R5).

---

## 3. High-Level Architecture

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 0 — OFFLINE INTENT ANALYSIS        (một lần · NGOÀI Databricks Jobs)    ║
║  Chạy trong notebook / môi trường phân tích. Không có lịch. Không có SLA.      ║
╚═══════════════════════════════════════════════════════════════════════════════╝
   ┌──────────────┐   ┌──────────┐   ┌───────────┐   ┌────────────┐   ┌─────────┐
   │ Feedback     │──▶│ Embedding│──▶│  HDBSCAN  │──▶│ LLM merge  │──▶│ chốt 5  │
   │ lịch sử      │   │  Qwen3   │   │(over-seg) │   │  cụm       │   │ nhãn    │
   └──────────────┘   └──────────┘   └───────────┘   └────────────┘   └────┬────┘
                                                                            ▼
                                            ┌────────────────────────────────────┐
                                            │  PM + AI team REVIEW & CHỐT        │
                                            │  wording · chọn SAMPLE mỗi nhãn    │
                                            │  · calibrate ngưỡng high/low       │
                                            └───────────────┬────────────────────┘
                                                            ▼
                                            ┌────────────────────────────────────┐
                                            │  📦 INTENT CATALOG  (frozen)       │
                                            │  intents.yaml (git) + Delta table  │
                                            │  bug · new_feature · praise ·      │
                                            │  complain · unclassified           │
                                            │  sample_vectors · thresholds       │
                                            └───────────────┬────────────────────┘
  ══════════════════════ BÀN GIAO MỘT LẦN ══════════════════╪════════════════════
                                                            ▼
╔═══════════════════════════════════════════════════════════════════════════════╗
║  PRODUCTION — DATABRICKS JOBS               (chỉ chứa nhãn đã chốt)            ║
╚═══════════════════════════════════════════════════════════════════════════════╝

  SOURCE LAYER
  ┌────────────────────┐      ┌──────────────────────────────────────────────┐
  │  LAKEBASE          │      │  MCP-ATLASSIAN  (Databricks App · JSON-RPC)  │
  │  user_feedback     │      │  Confluence guideline[agent] · changelog     │
  │  (Postgres)        │      │  Jira backlog (chung project)                │
  └─────────┬──────────┘      └─────────────────────┬────────────────────────┘
            │                                        │
            │                       ┌────────────────▼───────────────────────┐
            │                       │  JOB A: ingest-sync       (lịch: ngày) │
            │                       │  snapshot 3 nguồn · refresh khi version│
            │                       │  lệch · KHÔNG chunk/embed/index        │
            │                       └────────────────┬───────────────────────┘
            │                                        ▼
            │                       ┌────────────────────────────────────────┐
            │                       │  KNOWLEDGE STORE (whole-content)       │
            │                       │  userguide_page[agent] · changelog_ref │
            │                       │  · backlog_ref                         │
            │                       └────────────────┬───────────────────────┘
            │  SELECT … WHERE created_at = D-1       │  nạp NGUYÊN VĂN vào prompt
            ▼                                        ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  JOB B: inference — BATCH n-1                     (lịch: hằng ngày, 02:00)   │
  │                                                                              │
  │  ┌──────────────────┐   ┌───────────────────────┐   ┌────────────────────┐   │
  │  │ TASK B1 classify │──▶│ TASK B2 draft         │──▶│ TASK B3 deliver    │   │
  │  │ embed feedback   │   │ bug/new_feature:      │   │ render HTML → .eml │   │
  │  │ cosine → sample  │   │  gom theo AGENT, chuỗi│   │ ghi vào folder theo│   │
  │  │ của 5 nhãn       │   │  guideline→changelog  │   │ nhãn · ghi eml_path│   │
  │  │ threshold routing│   │  →backlog→we_listen   │   │                    │   │
  │  │ ghi classification│  │ praise/complain: kịch │   │                    │   │
  │  │                  │   │  bản tĩnh song ngữ    │   │                    │   │
  │  │                  │   │ unclassified: template│   │                    │   │
  │  │                  │   │  theo nhãn score cao  │   │                    │   │
  │  └────────┬─────────┘   └───────────┬───────────┘   └─────────┬──────────┘   │
  └───────────┼─────────────────────────┼─────────────────────────┼──────────────┘
              │ đọc                     │                         ▼
              ▼                         │            ┌──────────────────────────┐
  ┌────────────────────────┐            │            │  REVIEW_DIR (máy local)  │
  │ 📦 intent_catalog      │            │            │   📁 bug/                │
  │    (read-only, tĩnh)   │            │            │   📁 new_feature/        │
  └────────────────────────┘            │            │   📁 praise/             │
                                        │            │   📁 complain/           │
                                        ▼            │   📁 unclassified/        │
                          ┌────────────────────────┐ └────────────┬─────────────┘
                          │ unclassified_pool      │              │
                          │ (tích luỹ cho scope    │   USER: mở bằng Outlook ·
                          │  re-run sau)           │   xoá block INTERNAL ·
                          └────────────────────────┘   chỉnh · SEND (thủ công)
                                                                  │
                                                                  ✂ HẾT RANH GIỚI
                                                                    HỆ THỐNG
  ┌──────────────────────────────────────┐
  │  DATA LAYER (Delta / UC)             │──▶  SQL dashboard
  │   feedback_processing                │     (unclassified_rate · phân bố nhãn
  │   unclassified_pool                  │      · tỉ lệ hit từng nguồn knowledge)
  │   userguide_page · changelog_ref     │
  │   backlog_ref · development_insight  │
  │   insight_theme · metrics_event      │
  └──────────────────────────────────────┘

  ┌───────────────────────────────────────────────────────────────────────────┐
  │ CROSS-CUTTING: Model Serving (Haiku 4.5 draft · Sonnet 4.6 fallback ·      │
  │                Qwen3-embedding CHỈ cho B1) via AI-Gateway                  │
  │ MCP-Atlassian client · Unity Catalog · Secret scopes · structlog · DAB     │
  └───────────────────────────────────────────────────────────────────────────┘
```

### Trách nhiệm từng module

| Module | Trách nhiệm (một dòng) | Trong Databricks Job? |
| ------ | ---------------------- | --------------------- |
| Offline intent analysis | Sinh và chốt 5 nhãn + sample từ feedback lịch sử — chạy một lần | ❌ Ngoài hệ thống |
| **Intent Catalog** | Artifact tĩnh: định nghĩa 5 nhãn + sample vector + ngưỡng; version bằng git tag | ❌ Input tĩnh |
| `ingest-sync` (Job A) | Snapshot **3 nguồn qua MCP-Atlassian** → `userguide_page` (khoá `agent`), `changelog_ref`, `backlog_ref`; refresh khi `version` lệch | ✅ |
| `inference.classify` (B1) | Đọc feedback `D-1` từ **Lakebase** → embed → cosine tới **sample của 5 nhãn** → gán nhãn + confidence → routing 3 vùng | ✅ |
| `inference.draft` (B2) | Định tuyến theo nhãn: `bug`/`new_feature` gom **theo `agent`**, nạp nguyên văn guideline+changelog+backlog cho LLM theo **chuỗi §4.4**; `praise`/`complain` lấy kịch bản tĩnh; `unclassified` dựng template theo nhãn score cao nhất. Ghi `draft_body_html` + `source_ref` vào Delta (chưa xuất file) | ✅ |
| `inference.deliver` (B3) | Render `.eml` (MIME, logo inline, song ngữ) và **ghi vào folder theo nhãn** trong `REVIEW_DIR`; ghi `eml_path` — retry được độc lập | ✅ |
| `unclassified_pool` | Tích luỹ feedback không khớp nhãn nào — bàn giao cho scope re-run | ✅ (bảng) |
| `shared` (library) | Client Lakebase / MCP-Atlassian / Model Serving, config, pydantic models, Delta helper | ✅ (dùng chung) |

> **Đã gỡ khỏi bảng so với v3.3:** `outcome-sync` (Job C). Không còn mailbox để đối soát ⇒ module này không có đầu vào. Code Graph (`graph_client.py`, `outlook_mac.py`) trở thành di sản, không nằm trong kiến trúc v4.0.

> **Knowledge layer — nguyên tắc v4.0 (kế thừa v3.1/v3.2, mở rộng cho 3 nguồn):** không nguồn nào được chunk/embed/index. Cả ba theo cùng một khuôn — **snapshot một lần/run → nạp toàn bộ nội dung vào prompt → trả lời theo lô**. Guideline định tuyến `agent → page` (feedback đã mang sẵn cột `agent`, chính là tên function); changelog và backlog nạp cả bản. Batch amortize context trên K feedback/call ⇒ cắt token. Gate an toàn giữ nguyên: không nguồn nào khớp ⇒ `we_listen`, không hứa nhầm. Nền: `docs/2026-08-26/knowledge-retrieval-strategy/plan.md` (v3.1), `docs/2026-08-27/knowledge-layer-batch/plan.md` (v3.2), `docs/architecture/knowledge-layer.md` (module Job A).

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
     │                │<───┘ nhãn ứng viên            │                │
     │  bảng review   │                │              │                │
     │<───────────────│                │              │                │
     │ trình PM duyệt │                │              │                │
     │──────────────────────────────>  │              │                │
     │                │  chốt 5 nhãn · wording        │                │
     │                │  · tie-breaker theo cặp       │                │
     │<─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │              │                │
     │ chọn SAMPLE (3-5 mẫu/nhãn)     │              │                │
     │ calibrate high/low trên holdout│              │                │
     │────┐           │                │              │                │
     │<───┘           │                │              │                │
     │ commit intents.yaml + vectors  │              │                │
     │───────────────────────────────────────────────>│                │
     │                │                │   CI: load vào Delta          │
     │                │                │              │───────────────>│
     │                │                │              │   ✅ frozen    │
     │<─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
```

> Sau mũi tên cuối, **`intent_catalog` là read-only với toàn bộ production.** Không job nào được ghi vào nó. Muốn đổi nhãn = sửa git + deploy, không phải sửa dữ liệu.
>
> Định nghĩa 5 nhãn và tie-breaker theo cặp (`bug` vs `new_feature`, `bug` vs `complain`, `new_feature` vs `complain`, `praise` vs `new_feature`, bất kỳ vs `unclassified`): `data/golden/intent_explain.md`. Nhãn vàng để đo O2: `data/golden/feedback_gold.csv`.

### 4.2 Flow B — Inference batch `n-1` (happy path)

Ba task nối tiếp trong một job. Mỗi task ghi trạng thái vào Delta trước khi task sau chạy, nên retry được từng chặng. Toàn bộ run làm việc trên **một lát cắt ngày `D-1`**.

```
┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────┐
│Scheduler│ │ Lakebase │ │B1 classify│ │intent_  │ │B2 draft  │ │B3      │ │ Delta  │
│  02:00  │ │          │ │          │ │catalog   │ │(+ KB     │ │deliver │ │ state  │
│         │ │          │ │          │ │          │ │ snapshot)│ │        │ │        │
└────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ └───┬────┘
     │ trigger (D-1)          │            │            │           │          │
     │───────────────────────>│            │            │           │          │
     │           │ SELECT * FROM user_feedback          │           │          │
     │           │ WHERE created_at::date = D-1         │           │          │
     │           │<───────────│            │            │           │          │
     │           │  M feedback│            │            │           │          │
     │           │───────────>│            │            │           │          │
     │           │            │ anti-join feedback_processing (idempotency)    │
     │           │            │───────────────────────────────────────────────>│
     │           │            │ load sample_vectors + thresholds  │           │
     │           │            │───────────>│            │           │          │
     │           │            │  catalog + embedding_model_name    │          │
     │           │            │<───────────│            │           │          │
     │           │            │ guard: model đang gọi == model trong catalog?  │
     │           │            │ (lệch ⇒ FAIL LOUD, xem R2)         │           │
     │           │            │ embed + max-cosine → nhãn, confidence          │
     │           │            │────┐       │            │           │          │
     │           │            │<───┘       │            │           │          │
     │           │            │ INSERT classification (flag ok|low|unclassified)│
     │           │            │───────────────────────────────────────────────>│
     │           │            │ B1 done ──────────────▶│            │          │
     │           │            │            │           │ đọc KB snapshot       │
     │           │            │            │           │ (guideline·changelog· │
     │           │            │            │           │  backlog — nguyên văn)│
     │           │            │            │           │<──────────────────────│
     │           │            │            │  ┌────────┴─────────┐ │          │
     │           │            │            │  │ NHÓM 1: bug +    │ │          │
     │           │            │            │  │ new_feature      │ │          │
     │           │            │            │  │ GOM THEO `agent` │ │          │
     │           │            │            │  │ → 1 call/agent   │ │          │
     │           │            │            │  │ chuỗi §4.4       │ │          │
     │           │            │            │  ├──────────────────┤ │          │
     │           │            │            │  │ NHÓM 2: praise / │ │          │
     │           │            │            │  │ complain → kịch  │ │          │
     │           │            │            │  │ bản tĩnh (0 LLM) │ │          │
     │           │            │            │  ├──────────────────┤ │          │
     │           │            │            │  │ NHÓM 3: unclass. │ │          │
     │           │            │            │  │ → template theo  │ │          │
     │           │            │            │  │ best_label       │ │          │
     │           │            │            │  └────────┬─────────┘ │          │
     │           │            │            │           │ UPDATE draft_body_html│
     │           │            │            │           │ + source_ref + insight│
     │           │            │            │           │──────────────────────>│
     │           │            │            │           │ B2 done ─▶│          │
     │           │            │            │           │           │ đọc draft chưa xuất
     │           │            │            │           │           │<─────────│
     │           │            │            │           │           │ mkdir folder theo nhãn
     │           │            │            │           │           │ ghi <feedback_id>.eml
     │           │            │            │           │           │────┐     │
     │           │            │            │           │           │<───┘     │
     │           │            │            │           │           │ UPDATE eml_path,
     │           │            │            │           │           │ status=drafted
     │           │            │            │           │           │─────────>│
```

> **Vì sao vẫn tách B2 và B3 khi không còn Graph:** B2 tốn tiền (LLM + cả kho knowledge trong prompt), B3 đụng filesystem (đầy đĩa, path bị khoá, `REVIEW_DIR` chưa mount). Gộp lại thì một lỗi ghi file buộc sinh lại toàn bộ draft. Tách ra thì retry B3 là đủ, và `draft_body_html` đã nằm an toàn trong Delta.
>
> **Vì sao gom theo `agent`:** guideline là whole-page. Không gom thì page của `the-powerpoint-er` bị nạp lại cho từng feedback — mà riêng agent này gánh 74/192 feedback trong tập mẫu. Gom theo agent biến chi phí context từ `O(số feedback)` về `O(số agent)`.

### 4.3 Flow C — Threshold routing trên 5 nhãn

```
                      ┌────────────────────────────┐
                      │ confidence c = max cosine   │
                      │ tới sample của nhãn i       │
                      └─────────────┬──────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       │ c ≥ high                   │ low ≤ c < high             │ c < low
       ▼                            ▼                            ▼
┌────────────────┐        ┌─────────────────────┐      ┌──────────────────────┐
│ flag = ok      │        │ flag = low_confidence│     │ flag = unclassified  │
│ reply đầy đủ   │        │ reply + cờ ⚠ trong  │      │ KHÔNG đoán nhãn      │
│                │        │ block INTERNAL       │     │ dựng template theo   │
│                │        │                      │     │ best_label (score    │
│                │        │                      │     │ cao nhất) — chờ user │
└───────┬────────┘        └──────────┬──────────┘      └──────────┬───────────┘
        ▼                            ▼                            ▼
 📁 <nhãn>/                   📁 <nhãn>/                    📁 unclassified/
 bug · new_feature ·          (kèm cảnh báo)                       │
 praise · complain                                                 ▼
        │                                                ┌──────────────────────┐
        │  ⚠ nhãn `unclassified` thắng max-cosine        │  unclassified_pool   │
        └──────────────────────────────────────────────▶ │  (Delta, append-only)│
           cũng đi vào 📁 unclassified/                   │  ┌────────────────┐  │
                                                         │  │ ⚠ DEAD END     │  │
                                                         │  │ scope này —    │  │
                                                         │  │ chờ re-run     │  │
                                                         │  └────────────────┘  │
                                                         └──────────────────────┘
```

Hai đường dẫn tới `unclassified/` — cần phân biệt vì chúng khác nhau về nguyên nhân:

| Đường | Nghĩa | `best_label` dùng để |
| ----- | ----- | -------------------- |
| `c < low` với mọi nhãn | Feedback ở xa mọi sample — hệ thống **không biết** | Chọn template khởi tạo cho user sửa (không hứa gì) |
| `argmax = unclassified` và `c ≥ low` | Feedback **giống các mẫu vô nghĩa/cắt cụt** đã gán nhãn `unclassified` | Lấy nhãn cao thứ hai làm template |

> Trong v2.0, nhánh này quay về Discovery kỳ sau. Từ v3.0 nó **không quay lại đâu cả** — chỉ tích luỹ. Đó là cái giá của việc đóng băng taxonomy, và `unclassified_rate` là chỉ số phải theo dõi sát nhất (§6.1 R1).

### 4.4 Flow D — Chuỗi phân giải knowledge cho `bug` / `new_feature` **(mới ở v4.0)**

Đây là phần logic mới quan trọng nhất. Hai nhãn `bug` và `new_feature` **không tự quyết định được câu trả lời**: cùng một câu "không tìm thấy nút xoá slide" có thể là *user chưa biết nút nằm ở đâu* (⇒ hướng dẫn) hoặc *tính năng chưa có* (⇒ ghi nhận). Sự thật nằm trong tài liệu, không nằm trong feedback.

Chuỗi chạy **theo lô của một `agent`**, mỗi bước là một cổng: khớp thì dừng, không khớp thì rơi xuống bước sau.

```
   ┌──────────────────────────────────────────────────────────┐
   │  Lô feedback của MỘT agent (nhãn bug | new_feature)      │
   └───────────────────────────┬──────────────────────────────┘
                               ▼
   ┌──────────────────────────────────────────────────────────┐
   │  BƯỚC 1 — GUIDELINE(agent) + CHANGELOG  (chung project)  │
   │  nạp NGUYÊN VĂN vào prompt · 1 call cho cả lô            │
   │  Hỏi: tính năng này ĐÃ TỒN TẠI chưa? có ở đâu?           │
   └───────────────┬──────────────────────────┬───────────────┘
        answerable=true                  answerable=false
        + source_ref=page@version               │
                   ▼                            ▼
   ┌───────────────────────────┐  ┌──────────────────────────────────────────┐
   │ ✅ KỊCH BẢN "HƯỚNG DẪN"   │  │  BƯỚC 2 — BACKLOG (chung project)        │
   │ Giải thích cách sử dụng,  │  │  nạp CẢ DANH SÁCH open/non-Done vào      │
   │ trích đúng đoạn tài liệu  │  │  prompt · LLM đối chiếu từng feedback    │
   │ + citation                │  └──────────────┬───────────────┬───────────┘
   └───────────────────────────┘        hit=true │               │ hit=false
                                    + jira_key   ▼               ▼
                          ┌───────────────────────────┐  ┌────────────────────┐
                          │ ✅ KỊCH BẢN "ĐÃ GHI NHẬN" │  │ ✅ KỊCH BẢN        │
                          │ "chúng tôi đã ghi nhận và │  │    "we_listen"     │
                          │  đang phát triển/xử lý"   │  │ Ghi nhận chung,    │
                          │ mốc thời gian suy từ      │  │ KHÔNG hứa mốc,     │
                          │ Jira status               │  │ KHÔNG khẳng định   │
                          └───────────────────────────┘  └────────────────────┘
```

**Vì sao guideline đi trước backlog.** Hai loại sai không ngang giá nhau. Nói "đang phát triển" về một tính năng **đã có** khiến user chờ một thứ họ đang cầm trong tay — sai vừa vô ích vừa mất uy tín. Nói "để chúng tôi ghi nhận" về một thứ đã nằm trong backlog thì chỉ là nhạt, không sai. Đặt nguồn *mô tả sản phẩm hiện tại* lên trước nguồn *dự định tương lai* là cách chặn kiểu sai đắt hơn.

**Vì sao changelog nằm cùng bước 1.** Changelog trả lời đúng câu hỏi mà guideline hay bỏ sót: *tính năng vừa được thêm, tài liệu chưa kịp cập nhật.* Tài liệu trong `data/guidelines/` đang cũ hơn feedback 1–3 tháng — changelog là thứ bịt đúng khoảng trống đó. Gộp cùng bước 1 vì cả hai cùng trả lời "hiện tại sản phẩm có gì".

**Cổng an toàn (bất biến của O4).** Mỗi bước chỉ được coi là khớp khi LLM trả về **`source_ref` phân giải được** — `page_id@version` cho bước 1, `jira_key` có thật trong snapshot cho bước 2. `source_ref` null, không parse được, hoặc trỏ tới thứ không tồn tại trong snapshot ⇒ coi như **không khớp**, rơi xuống bước sau. B2 không tin LLM echo lại nội dung; nó chỉ tin cái khoá tra ngược được.

### 4.5 Flow E — Vòng review thủ công (ngoài hệ thống)

```
   B3 ghi file                 USER (PM)                      ✂
  ┌───────────┐          ┌────────────────────┐
  │ REVIEW_DIR│──mở──▶  │ Outlook desktop     │
  │ <nhãn>/   │          │ 1. đọc block INTERNAL (context nội bộ)
  │ fb_x.eml  │          │ 2. XOÁ block INTERNAL
  └───────────┘          │ 3. chỉnh câu chữ nếu cần
                          │ 4. Send
                          └────────────────────┘
                                    │
                          ✂ HỆ THỐNG KHÔNG THẤY GÌ TỪ ĐÂY
```

Đây không phải là một module — nó là **chỗ hệ thống kết thúc**. Sau khi B3 ghi file, hệ thống không biết user có gửi không, có sửa gì không, có quên xoá block INTERNAL không. Hai hệ quả phải nhìn thẳng:

- **Không đo được chất lượng draft.** Không có `edit_distance`, không có tỉ lệ approve. Cách thay thế rẻ nhất là quy ước thủ công: user **di chuyển file** sang `_sent/` hoặc `_rejected/` sau khi xử lý, và một job phụ đếm file theo folder. Thô, nhưng có còn hơn không — xem §6.3.
- **Không phát hiện được rò rỉ INTERNAL.** v3.3 bắt bằng cách đọc Sent; v4.0 không có Sent để đọc. Xem R4 và đề xuất tách sidecar.

### 4.6 Data layer

```sql
-- ARTIFACT TĨNH (read-only với mọi job)
intent_catalog(
  label PK,                               -- bug | new_feature | praise | complain | unclassified
  catalog_version,                        -- = git tag, vd "v1"
  description, action_type,               -- knowledge_chain | ack_only | draft_review
  sample_vectors ARRAY<ARRAY<FLOAT>>,     -- 3-5 mẫu THẬT/nhãn, KHÔNG phải mean (R3)
  threshold_high FLOAT, threshold_low FLOAT,
  embedding_model_name STRING,            -- guard R2: B1 fail loud nếu lệch model đang gọi
  approved_by, approved_at
)

-- STATE (idempotency key = feedback_id)
feedback_processing(
  feedback_id PK,                         -- lấy nguyên từ Lakebase
  catalog_version,                        -- chừa sẵn cho scope re-run
  label, confidence,
  best_label, best_confidence,            -- nhãn score cao nhất (dùng khi flag=unclassified)
  flag,                                   -- ok | low_confidence | unclassified
  agent,                                  -- khoá gom lô ở B2
  scenario,                               -- how_to_answer | known_gap | we_listen | thank_you
                                          --   | apology | neutral_ack
  source_ref,                             -- 'page:<id>@<version>' | 'jira:<key>' | NULL (O4)
  draft_body_html, draft_body_hash,       -- ghi bởi B2, đọc bởi B3
  draft_status,                           -- pending_deliver | drafted | error
  eml_path,                               -- đường dẫn file .eml đã ghi (thay draft_ref của v3.3)
  classified_at, drafted_at, delivered_at
)

-- HẤP THỤ DRIFT (append-only, chờ scope sau)
unclassified_pool(
  feedback_id PK, content, agent,
  best_label, best_confidence,            -- nhãn gần nhất dù dưới ngưỡng
  embedding, created_at
)

-- KNOWLEDGE — KHÔNG nguồn nào chunk/embed/index. Snapshot nguyên văn, nạp thẳng vào prompt.
--   change-detection ở mức page `version`; lệch ⇒ ingest-sync refresh (R6 fail-loud).
--   agent chưa map ⇒ B2 coi như không có tài liệu ⇒ rơi xuống bước backlog.
userguide_page(agent PK, page_id, version, title, markdown, last_modified, synced_at)
changelog_ref(page_id PK, version, title, markdown, last_modified, synced_at)  -- chung project
backlog_ref(jira_key PK, summary, description, status, issuetype, synced_at)   -- chung project

-- INSIGHT
development_insight(insight_id PK, feedback_id, agent, contribution_type, subtype,
                    summary, suggested_improvement, user_quote, impact,
                    theme_id, atlassian_ref, status, created_at)
insight_theme(theme_id PK, title, contribution_type, demand_count,
              first_seen, last_seen, priority_score, status)

-- METRICS
metrics_event(event_id PK, feedback_id, event_type, payload, created_at)
```

**Thay đổi data contract so với v3.3** — mọi thay đổi dưới đây là **breaking**, cần migrate bảng trước khi code chạy:

| Bảng | Thay đổi |
| ---- | -------- |
| `intent_catalog` | `intent_id` → `label` (PK); `exemplar_vectors` → `sample_vectors`; bỏ `email_template_id` (template chọn theo `scenario`, không theo nhãn — impl §3.2); thêm `embedding_model_name` (guard R2) |
| `feedback_processing` | `intent_id` → `label`; thêm `best_label`/`best_confidence`, `agent`, `scenario`, `source_ref`; `draft_ref` (Graph messageId) → **`eml_path`**; **bỏ `outcome`, `edit_distance`, `outcome_at`** (không còn nguồn để điền) |
| `unclassified_pool` | `best_intent_id` → `best_label` |
| `backlog_ref` | Bỏ cột `embedding` (đã unused từ v3.2) |
| `changelog_ref` | **Bảng mới** |

---

## 5. Technology Stack

| Layer | Techstack | Detail (why this choice) |
| ----- | --------- | ------------------------ |
| Ngôn ngữ | Python 3.12 | Hệ sinh thái embedding/LLM đầy đủ; khớp Databricks runtime; một ngôn ngữ cho cả 2 job + library phân tích |
| Dependency | `uv` + `pyproject.toml` | Lockfile deterministic, build nhanh trong CI; ra wheel để `python_wheel_task` gọi trực tiếp |
| **Phân tích offline** | Databricks notebook (ad-hoc, không lịch) | Chạy một lần nên không cần đóng gói thành job. Notebook giữ được cả code lẫn kết quả review để audit — quan trọng vì đây là artifact PM đã ký duyệt |
| **Intent Catalog** | YAML trong git + bảng Delta | Git cho phép review qua PR và biết ai đổi gì; Delta cho job đọc nhanh. **Nguồn sự thật là git**, Delta chỉ là bản load |
| **Nguồn feedback (v4.0)** | **Lakebase** (Postgres quản trị bởi Databricks) — đọc bằng SQL, `psycopg` / Databricks SQL connector | Feedback được ghi bởi ứng dụng theo kiểu OLTP; Lakebase là nơi nó nằm. Đọc lát cắt `WHERE created_at::date = D-1` là một câu SQL, không cần pipeline trung gian. **Đổi lại:** state (`feedback_processing`) vẫn ở Delta ⇒ idempotency đọc-ghi vắt qua hai hệ (R8) |
| **Truy cập knowledge (v4.0)** | **MCP-Atlassian** trên Databricks Apps — JSON-RPC 2.0/HTTPS, bearer U2M SSO | Một client duy nhất cho **cả ba nguồn** (Confluence guideline · Confluence changelog · Jira backlog) thay vì Jira REST + Confluence REST + hai kiểu auth. Đã chạy thật: `src/02_knowledge/mcp_atlassian_call.py`. **Đổi lại:** thêm một hop (App có thể chết) và token U2M cần đổi sang service principal khi lên production |
| Orchestration | Databricks Jobs / Workflows | Có sẵn, không dựng thêm Airflow. Multi-task DAG cho phép `classify→draft→deliver` retry từng chặng |
| Compute | Serverless / job cluster nhỏ | Job chạy rồi tắt, không trả tiền idle. Không có HDBSCAN trong production nên nhu cầu RAM thấp |
| LLM (draft + knowledge) | AI-Gateway Responses `nonprod_ai.tsfai.claude-haiku-4-5-sit-tai` | Feedback ngắn + câu trả lời grounded template-driven không cần suy luận sâu; Haiku rẻ hơn ~3× (~$2 vs $6/tháng ở 100 fb/ngày). Gate `source_ref` chặn bịa (§4.4). Gọi qua **AI-Gateway MLflow Responses API** (`/ai-gateway/mlflow/v1/responses`; `system→instructions`, `max_tokens→max_output_tokens`). Endpoint nội bộ ⇒ PII không rời nền tảng |
| LLM (dự phòng chất lượng) | Model Serving `claude-sonnet-4-6-sit-tai` | Bật lại cho nhánh knowledge nếu Haiku giảm chất lượng ở lô có cả 3 nguồn trong prompt (giữ tên endpoint trong config) |
| Embedding | AI-Gateway Embeddings `nonprod_ai.tsfai.qwen3-embedding-0-6b-sit-tai` (1024-dim) | Đa ngôn ngữ (feedback VI/EN lẫn lộn). **Bắt buộc dùng đúng model đã dùng lúc phân tích offline** — sample vector chỉ có nghĩa trong cùng không gian vector (guard R2). **Dùng cho duy nhất B1 classify.** Không nguồn knowledge nào được embed |
| Knowledge store | Bảng Delta `userguide_page` (khoá `agent`) · `changelog_ref` · `backlog_ref` — **whole-content → LLM** | **Không có vector DB trong kiến trúc.** Corpus nhỏ (guideline cả kho ~25k token; backlog vài chục issue) ⇒ nạp thẳng rẻ hơn và đúng hơn dựng index. Bỏ toàn bộ chunk-change-detection; change-detection về mức page `version`. Đổi lại: corpus phình ⇒ phải tiền lọc (R9) |
| Data store | Delta Lake / Unity Catalog | ACID + time travel để truy vết draft sai; UC cho governance và lineage — gần như bắt buộc trong môi trường ngân hàng |
| Schema | `pydantic` v2 | Ép structured output của LLM về schema chặt; fail sớm thay vì ghi rác vào Delta |
| Config | `pydantic-settings` + job parameters | `REVIEW_DIR`, window `D-1`, model name, tên folder nằm ở config. Ngưỡng nằm trong catalog vì chúng thuộc về nhãn, không thuộc về run |
| **Email output (v4.0)** | **`.eml` (RFC 5322) qua `email.message.EmailMessage`**, ghi vào `REVIEW_DIR/<nhãn>/<feedback_id>.eml` | **Đường chính, không còn là fallback.** Không cần app registration, không cần quyền mailbox, chạy được ở mọi môi trường. Logo nhúng inline (`cid:`), body HTML song ngữ theo `template/`. Đổi lại: mất routing folder mailbox và **mất hoàn toàn outcome tracking** (R5) |
| Secrets | Databricks secret scopes | Lakebase credential, token MCP — không nằm trong code hay notebook |
| Auth | Databricks OAuth (U2M cho spike → service principal cho production) | Cả Lakebase, Model Serving và MCP-Atlassian đều nằm sau Databricks identity ⇒ **một cơ chế auth duy nhất**. Đây là lợi ích phụ đáng kể của việc bỏ Graph: không còn Azure AD app registration nào phải xin |
| Deploy | Databricks Asset Bundles | 2 job trong một `databricks.yml`, deploy SIT → prod bằng một lệnh |
| Test | `pytest` + mock endpoint | Unit test cho routing/threshold/chuỗi §4.4/render template — phần logic thuần, không cần LLM thật. Test `.eml` đọc lại bằng `email.parser`, CI chạy offline hoàn toàn |
| Observability | `structlog` + `metrics_event` + job alert | Log JSON query được; metric nghiệp vụ ghi vào Delta vì đó là dữ liệu sản phẩm chứ không phải debug output |
| Dashboard | Databricks SQL dashboard | SQL dashboard trên `metrics_event` đủ cho O5/O6 + `unclassified_rate` + **tỉ lệ hit từng bước của chuỗi §4.4** với chi phí gần bằng không |

> **Đã gỡ khỏi stack so với v3.3:** Microsoft Graph API, `msal`, Azure AD service principal, Jira REST trực tiếp, và dòng "Email fallback `.eml`" (nó lên làm đường chính).

---

## 6. Expert Suggestion

### 6.1 Key risks & limitations

**R1 — Taxonomy đóng băng là nợ kỹ thuật có đồng hồ đếm ngược. Vẫn là rủi ro số một.** Sản phẩm TÀI Studio đang phát triển: thêm agent mới, thêm tính năng, thì feedback về những thứ đó **không tồn tại trong dữ liệu lịch sử** nên không có nhãn tương ứng. Chúng rơi hết vào `unclassified`. Hệ thống không hỏng, nó **suy giảm âm thầm** — vẫn chạy, vẫn sinh `.eml`, chỉ là ngày càng nhiều file vô dụng.
*Giảm thiểu:* đặt `unclassified_rate` lên dashboard ngay từ ngày đầu và định trước ngưỡng hành động (**vượt 20% trong 2 tuần liên tiếp ⇒ kéo scope re-run vào sprint kế**). Không có ngưỡng định trước thì không ai nhận ra lúc nào là "đủ tệ".

**R2 — Sample vector chết cứng theo embedding model.** `sample_vectors` trong catalog được sinh bởi một phiên bản `qwen3-embedding` cụ thể. Nếu Databricks nâng cấp endpoint hoặc bạn đổi model, vector cũ nằm ở không gian khác và confidence trở thành số vô nghĩa — mà **không có lỗi nào được ném ra**.
*Giảm thiểu:* `embedding_model_name` đã nằm trong `intent_catalog` (§4.6); B1 so với model đang gọi và **fail loud** nếu lệch. Một dòng `if`, chặn một class lỗi rất khó debug.

**R3 — Dùng sample thật thay vì centroid.** HDBSCAN là density-based nên cụm có thể lõm hoặc kéo dài; điểm trung bình có thể rơi ra ngoài cụm, khiến cosine tới centroid vô nghĩa. Vì taxonomy là artifact do người chốt, hãy **chọn tay 3–5 feedback thật đại diện nhất mỗi nhãn**, confidence = max cosine tới các sample đó. Robust hơn với cụm phi cầu, dễ giải thích cho PM ("gần với ví dụ này nhất"), dễ vá — thêm một sample là một dòng YAML.
*Bẫy cụ thể:* `data/golden/intent_explain.md` có cột *"Không phải nhãn này khi"*. **Không được bê các case đó vào `sample_vectors`** — index coi mọi sample là mẫu DƯƠNG, thêm negative vào sẽ kéo nhãn sai lại gần.

**R4 — Block INTERNAL nằm trong body email, và v4.0 KHÔNG CÒN cơ chế phát hiện rò rỉ.** v3.3 bù bằng *phát hiện thay vì ngăn chặn* (`outcome-sync` đọc Sent và cảnh báo). Bỏ Graph là bỏ luôn cái lưới đó. Cơ chế bảo vệ còn lại **duy nhất** là user nhớ xoá — không có ai kiểm tra sau lưng.
*Giảm thiểu — cần chốt trước khi code B3:* tách context nội bộ ra **file sidecar** `<feedback_id>.internal.md` nằm cạnh `.eml`, và **không đưa block INTERNAL vào body email nữa**. Rò rỉ lúc đó là bất khả thi về mặt cấu trúc chứ không phụ thuộc trí nhớ người dùng. Chi phí: user phải mở hai file. Đây là đánh đổi đáng làm khi cơ chế phát hiện đã mất — *nhưng nó đổi output contract nên chưa đưa vào §4.6, chờ PM chốt.*

**R5 — Mất hoàn toàn vòng phản hồi chất lượng.** Không còn cách nào biết draft nào được gửi nguyên văn, draft nào bị viết lại, draft nào bị bỏ. Nghĩa là: không đo được chất lượng theo nhãn, không biết template nào sai, không có dữ liệu để cải tiến, và không có tín hiệu nào cho biết chuỗi §4.4 đang trả lời sai. **Hệ thống chạy mù.**
*Giảm thiểu (rẻ, thủ công):* quy ước user **di chuyển file** sang `_sent/` hoặc `_rejected/` sau khi xử lý; một job phụ đếm file theo folder mỗi ngày và ghi `metrics_event`. Không đo được `edit_distance` nhưng ít nhất có tỉ lệ approve/reject. Nếu quy ước này không được tuân thủ thì chấp nhận rằng scope này **không có metric chất lượng nào cả** — và nói thẳng điều đó khi báo cáo, đừng để nó thành một khoảng lặng.

**R6 — Knowledge snapshot cũ hơn thực tế.** Ba nguồn, ba nhịp đồng bộ, ba cách hỏng: guideline cũ ⇒ hướng dẫn sai cách dùng; changelog cũ ⇒ nói "chưa có" về tính năng vừa ra; backlog cũ ⇒ hứa "đang làm" về ticket đã đóng. Nguy hiểm vì **trông giống thành công** — câu trả lời tự tin, có citation đàng hoàng.
*Giảm thiểu:* đưa `version` + `synced_at` vào citation trong block INTERNAL để người duyệt tự thấy tài liệu cũ cỡ nào; `ingest-sync` fail loud khi phát hiện `version` lệch. Bối cảnh thật: tài liệu trong `data/guidelines/` đang cũ hơn feedback 1–3 tháng, và `the-canvas-designer` **không có tài liệu nào** ⇒ mọi feedback của agent đó rơi thẳng xuống bước 2.

**R7 — Không có khoá chống trùng ở tầng file.** Nếu A3 sai (nhiều người duyệt) hoặc batch chạy trên hai máy, hai người có thể cùng gửi một reply. Tên file `<feedback_id>.eml` chống được trùng *trong cùng một thư mục*, nhưng không chống được hai bản sao `REVIEW_DIR` ở hai máy.
*Giảm thiểu:* một `REVIEW_DIR` duy nhất trên share dùng chung; `feedback_processing.draft_status` là khoá thật (anti-join trước khi ghi file).

**R8 — Idempotency vắt qua hai hệ (Lakebase đọc / Delta ghi).** Anti-join "feedback nào đã xử lý" đọc từ Delta nhưng danh sách nguồn đến từ Postgres. Không có transaction nào bao được cả hai. Job chết giữa B3 (file đã ghi, Delta chưa update) ⇒ lần chạy sau sinh lại file đè lên.
*Giảm thiểu:* ghi `.eml` bằng write-tạm-rồi-rename (atomic trong cùng filesystem), và coi việc ghi đè cùng `feedback_id` là **vô hại theo thiết kế** — cùng input, cùng prompt `temperature=0` ⇒ cùng nội dung. Điều kiện: draft phải deterministic; nếu không, R8 trở thành "user thấy hai bản khác nhau".

**R9 — Ngân sách token của whole-content với ba nguồn.** Một call của bước 1 mang guideline(agent) + **cả** changelog; bước 2 mang **cả** backlog. Hôm nay vừa (cả kho guideline ~25k token, backlog vài chục issue). Backlog lên vài trăm issue hoặc changelog tích luỹ một năm thì prompt vỡ — và nó vỡ **âm thầm** bằng cách model bỏ qua phần giữa context trước khi báo lỗi độ dài.
*Giảm thiểu:* đo và log `prompt_tokens` mỗi call ngay từ ngày đầu; đặt ngưỡng cảnh báo ở ~60% context window. Khi chạm ngưỡng, thứ tự tiền lọc rẻ nhất là: cắt changelog theo N tháng gần nhất → lọc backlog theo `agent`/component → lọc guideline theo heading H2.

### 6.2 Trade-offs made & những gì đã cố tình hoãn

| Đánh đổi | Được | Mất | Lý do chấp nhận |
| -------- | ---- | --- | --------------- |
| Intent analysis offline, không phải job | Production đơn giản hẳn: không HDBSCAN/UMAP trong runtime, không lifecycle versioning | Không tự học nhãn mới (R1) | Đúng nguyên tắc: **đừng tự động hoá việc bạn mới làm một lần** |
| Catalog là artifact git, không phải bảng ghi được | Review qua PR, biết ai đổi gì, rollback bằng git revert | Đổi nhãn phải deploy, không sửa nóng được | Trong ngân hàng, "sửa nóng bộ nhãn đang phân loại email gửi khách" là thứ nên khó, không nên dễ |
| Tách `deliver` khỏi `draft` | Retry lỗi ghi file không phải trả tiền sinh lại LLM | Thêm một task, thêm một trạng thái | Chi phí gần bằng không |
| `unclassified_pool` chỉ tích luỹ, không xử lý | Không mất dữ liệu; scope re-run có sẵn input | Chưa tạo ra giá trị gì ở scope này | Bảng append-only là chi phí thấp nhất để giữ cửa mở |
| Whole-content 3 nguồn thay vector DB | Bỏ chunk/embed/index và toàn bộ chunk-change-detection; không có index để lệch nguồn; LLM bắc cầu ngữ nghĩa tốt hơn keyword | Không có passage-precision; token/call tăng theo kích thước corpus (R9) | Corpus nhỏ + feedback đã mang sẵn `agent` ⇒ định tuyến bằng tra bảng là đủ. Dựng vector DB cho ~25k token tài liệu là kỹ thuật thừa |
| **`.eml` local thay Graph (v4.0)** | Không cần Azure app registration; một cơ chế auth duy nhất (Databricks); chạy được ngay, không chờ xin quyền | **Mất outcome tracking (R5) và mất phát hiện rò rỉ INTERNAL (R4)**; mất routing folder trong mailbox | Không xin được quyền thì đây không phải lựa chọn mà là điều kiện. Nhưng nó **không ngang giá** — hệ thống chạy mù về chất lượng. Phải nói rõ khi báo cáo và bù bằng quy ước thủ công ở §6.3 |
| **Chuỗi guideline → backlog (v4.0)** | Chặn được kiểu sai đắt nhất ("đang phát triển" về tính năng đã có) | Mỗi feedback nhánh knowledge tốn tối đa 2 lượt LLM thay vì 1 | Bước 1 khớp thì dừng ⇒ chỉ phần miss mới trả giá lượt hai. Và lượt hai tính theo **lô**, không theo feedback |
| Hoãn: re-run, versioning, app, auto-send, tự tạo ticket | Scope gọn, ship được | — | Tất cả đều two-way door, mở sau không phải viết lại |

### 6.3 Recommendations & next steps

**Thứ tự triển khai — mỗi bước là một cửa chặn:**

1. **Chốt R4 trước khi viết B3.** Block INTERNAL nằm trong body hay tách sidecar `.internal.md`? Câu trả lời quyết định output contract của B3 và cả template render. Đây là quyết định 10 phút chặn một tuần code.
2. **Spike Lakebase (nửa ngày).** Kết nối, đọc thử lát cắt `D-1`, xác nhận tên cột và kiểu `created_at` (timezone!). Rẻ, nhưng sai timezone ở đây làm lệch cả batch — và lệch âm thầm.
3. **Chạy phân tích offline đến khi ra Intent Catalog v1 (5 nhãn).** Cửa chặn thật: production không có gì để build khi chưa có catalog. Đừng viết `classify` trước bước này — bạn sẽ đoán sai schema.
4. **Calibrate ngưỡng trên `data/golden/feedback_gold.csv`.** Vẽ phân bố confidence của mẫu đúng và mẫu sai. Hai phân bố chồng lên nhau ⇒ quay lại R3 đổi cách chọn sample, đừng chữa bằng cách vặn ngưỡng. Chú ý `data/golden/README.md` liệt kê 62 id bẩn (OCR cắt cụt) cần loại khi eval — 32,3% `unclassified` trong tập mẫu là artefact, **không** phải prior cho production.
5. **Wire `changelog_ref` vào Job A.** Hiện `fetch_backlog()` đã chạy nhưng chưa được Job A gọi, và changelog thì chưa có gì cả (`docs/architecture/knowledge-layer.md` §Open Questions). B2 không chạy được chuỗi §4.4 khi thiếu nguồn.
6. **Đo chuỗi §4.4 trên tập gold trước khi bật.** Lấy ~30 feedback `bug`/`new_feature` có nhãn tay, chạy qua chuỗi, và đếm tay: bao nhiêu lần bước 1 trả lời đúng, bao nhiêu lần nó nói "đã có" về thứ chưa có. Bằng chứng cũ đã cho thấy nhãn vàng và tài liệu bất đồng ở 5/11 dòng tra được — đừng cho rằng chuỗi tự đúng.
7. **Chạy shadow một tuần** vào `REVIEW_DIR/_shadow/`. User đọc mà không gửi, và **tự viết câu trả lời của mình** cho ~20 feedback. So sánh tay là cách rẻ nhất để biết chất lượng draft trước khi nó chạm user thật — nhất là khi R5 đã lấy đi mọi cách đo tự động.
8. **Bật production cho nhánh an toàn nhất trước:** `praise` + `complain` (kịch bản tĩnh, không gọi LLM, không thể bịa). `bug`/`new_feature` giữ trong `_shadow` cho tới khi bước 6 cho kết quả chấp nhận được.

**Theo dõi liên tục:** `unclassified_rate` (chỉ số sống còn — R1), **tỉ lệ hit của từng bước chuỗi §4.4** (bước 1 hit quá cao ⇒ nghi model đang bịa "đã có tính năng"; bước 2 hit ~0 ⇒ nghi snapshot backlog hỏng), `prompt_tokens` mỗi call (R9), tỉ lệ 3 vùng ngưỡng, và — nếu quy ước `_sent/`/`_rejected/` được tuân thủ — tỉ lệ approve theo nhãn.

**Khi nào quay lại thiết kế này:** (a) `unclassified_rate` vượt ngưỡng đã định ⇒ kéo scope re-run vào; (b) volume vượt ~200/ngày hoặc có người duyệt thứ hai ⇒ cân nhắc một UI review thay folder file; (c) xin được quyền mailbox ⇒ cân nhắc quay lại Graph **chỉ để lấy lại R4/R5**, không phải để auto-send; (d) corpus knowledge chạm ~60% context window ⇒ tiền lọc theo thứ tự ở R9.

**Một điều cần chốt trước khi code:** giả định A7 (1 feedback → 1 email). Nếu ý định là **gộp nhiều feedback của cùng một user thành một email**, thì khoá idempotency, template và cả bước gom lô ở B2 đều đổi — chốt bây giờ, không phải ở tuần thứ sáu.
