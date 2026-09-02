---
author: klinh2212112@gmail.com
date: 2026-09-03
status: done
agents: inference.draft, inference.deliver
summary: B3 deliver — dựng email song ngữ VI/EN từ (label, solved, referenced) sau B1+B2, render .eml (logo inline cid:tai_logo, X-Unsent) và ghi vào REVIEW_DIR/<nhãn>/<feedback_id>.eml; câu mẫu tách ra YAML cho admin config; kèm runner chạy full luồng B1→B2→B3.
---

## Architecture reference

- Module: **`inference.deliver` (B3)** — render `.eml` + ghi vào folder theo nhãn. Kèm **lát mỏng của `inference.draft` (B2)**: chọn `scenario` + điền template tĩnh (KHÔNG gọi LLM ở bước này — LLM đã tiêu ở B2 bước 1 `resolve_guideline.py`).
- Sections: `docs/architecture.md`
  - §2 *Overview → Output* (cây thư mục `<REVIEW_DIR>/<nhãn>/`, `.eml` RFC 5322 HTML song ngữ + block INTERNAL),
  - §3 *Trách nhiệm từng module* (B3: "render `.eml` (MIME, logo inline, song ngữ) và ghi vào folder theo nhãn trong `REVIEW_DIR`; ghi `eml_path` — retry được độc lập"),
  - §4.2 *Flow B* (B2 ghi `draft_body_html` → B3 đọc draft chưa xuất → mkdir folder theo nhãn → ghi `<feedback_id>.eml`),
  - §4.3 *Flow C* (routing 3 vùng; `flag=unclassified` ⇒ dựng template theo `best_label`, file rơi vào folder `unclassified`),
  - §4.4 *Flow D* (bước 1 guideline hit ⇒ kịch bản "hướng dẫn"; không hit ⇒ rơi xuống, hết chuỗi ⇒ `we_listen`),
  - §4.5 *Flow E* (vòng review thủ công: PM mở Outlook, xoá block INTERNAL, gửi tay),
  - §4.6 *Data layer* (`feedback_processing.scenario ∈ {how_to_answer, known_gap, we_listen, thank_you, apology, neutral_ack}`, `source_ref`, `draft_body_html`, `eml_path`, `draft_status`),
  - §5 *Technology Stack* (Email output = `.eml` qua `email.message`/`email.mime`, logo `cid:`, config `REVIEW_DIR` + tên folder ở config; Test: đọc lại `.eml` bằng `email.parser`, CI offline).
- Impl doc: `docs/impl-phase2-auto-feedback-flow.md` §3.1 (LLM **không bao giờ** emit HTML — template render), **§3.2** (bảng chọn template theo `(action_type, rag_hit)`; không hit ⇒ `we_listen`, biến thể trung tính bỏ câu `{resolution_timeline}`), **§3.3** (style rules → lint assert), §3.4 (golden-file test; quyết định UTF-8 thẳng thay HTML entity).
- Template spec: `template/skill_create_email.md` (subject/from/cc cố định, cấu trúc logo → "English version below" → VI → separator ENGLISH VERSION → EN → footer; màu `#e53e3e` / `#e8f5e9`; không em-dash, không emoji, viết đúng "TÀI Studio"). Instance mẫu: `template/email_temp.py`.
- Data contract: `feedback_processing` §4.6 — file này ghi các cột `scenario`, `source_ref`, `draft_body_html` (in-memory), `eml_path`, `draft_status`. Chưa có Delta ở môi trường dev ⇒ **manifest CSV** giữ đúng tên cột để migrate 1-1 sau.
- Kế thừa: `docs/2026-09-03/guideline-resolve-batch/plan.md` (B2 bước 1 sinh `solved` + `referenced` + sidecar `source_ref`), `docs/2026-09-02/intent-classify-embedding-eval/plan.md` + `docs/2026-09-03/contrastive-negative-scoring/plan.md` (B1 sinh `label`/`flag`/`confidence`/`best_label`).

---

## 1. Problem statement

Luồng hiện có dừng ở CSV:

```
classify.py            resolve_guideline.py                (thiếu)
feedback ──B1──▶ label ──────B2 bước 1─────▶ solved + referenced ──▶ ??? ──▶ email
                 flag                        source_ref (sidecar)
```

Không có gì biến `(label, flag, solved, referenced)` thành thứ PM mở được. Architecture đã chốt đích đến là **file `.eml` nằm trong folder mang tên nhãn** (§2 Output), nhưng chưa có code nào ghi ra. Hệ quả: không demo được end-to-end, và cũng không kiểm được rằng chuỗi §4.4 thực sự đổi được *nội dung* email chứ không chỉ đổi một cột boolean trong CSV.

Thứ hai: câu chữ email đang **nằm cứng trong code mẫu** (`template/email_temp.py` hard-code nguyên một feedback của một người). PM/admin muốn sửa một câu phải sửa Python. `reply_samples.yaml` đã đi đúng hướng cho nhánh ack nhưng chỉ phủ 3 kịch bản tĩnh, không phủ `how_to_answer` / `we_listen`, và mỗi case có 4 biến thể (picker theo hash) — nhiều hơn mức cần cho bản này.

---

## 2. Requirements

| # | Yêu cầu | Nguồn |
|---|---|---|
| R-1 | Nhận đầu vào là output của `resolve_guideline.py` (CSV + sidecar `.debug.jsonl`), không đòi thêm cột nào mới | luồng hiện có |
| R-2 | Mỗi feedback ⇒ đúng 1 file `.eml`, tên `<feedback_id>.eml`, đặt trong `REVIEW_DIR/<folder theo nhãn>/` | §2 Output, O3 |
| R-3 | `.eml` mở được ở Outlook compose: `X-Unsent: 1`, `From`/`To`/`Cc` đúng spec, logo nhúng inline `cid:tai_logo` từ `src/assets/tai_logo.png` | `template/skill_create_email.md` |
| R-4 | Body HTML **song ngữ**: VI trước, separator "ENGLISH VERSION", EN sau. Nội dung VI và EN nói **cùng một điều** | user + spec |
| R-5 | Toàn bộ câu chữ nằm trong **1 file YAML** admin sửa được; mỗi kịch bản **đúng 1 message** (không biến thể) | user |
| R-6 | `flag=unclassified` ⇒ dựng template theo `best_label`, nhưng file ghi vào folder `unclassified` | §4.3 + user NOTE |
| R-7 | `solved=True` ⇒ template `we_resolved` kèm citation; `solved=False` ⇒ `we_listen`, **không được claim** đã giải quyết | §4.4, impl §3.2 |
| R-8 | Block INTERNAL trong body (label/flag/confidence/scenario/source_ref) để PM đọc rồi xoá trước khi gửi | §2 Output, §4.5 |
| R-9 | Lint style chạy trên output trước khi ghi file: không em-dash, không emoji, đúng casing "TÀI Studio", có `cid:tai_logo` | impl §3.3 |
| R-10 | Chạy được full luồng bằng 1 lệnh: CSV feedback ⇒ folder `.eml` | user (target) |

**Không làm trong bản này** (bám non-goal §1 + ranh giới §4.5): auto-send, đọc ngược mailbox, bước 2 backlog của chuỗi §4.4 (chưa có `backlog_ref` snapshot ⇒ scenario `known_gap` chưa sinh được), LLM tóm tắt lại feedback.

---

## 3. Decisions

### D1 — `scenario` là khoá chọn template, không phải `label`

`label` trả lời *feedback nói về cái gì*; `scenario` trả lời *ta nói lại cái gì*. Hai thứ không 1-1: cùng `label=bug`, hit guideline thì là "hướng dẫn cách dùng", không hit thì là "đã ghi nhận". §4.6 đã đặt sẵn cột `scenario` tách khỏi `label`, và §4.6 ghi rõ đã "bỏ `email_template_id`" khỏi `intent_catalog` vì *template chọn theo `scenario`, không theo nhãn*.

Bảng quyết định (hiện thực §4.3 + §4.4 + impl §3.2), `L` = `best_label` nếu `flag=unclassified`, ngược lại `label`:

| `L` | `solved` | `scenario` | Template | Folder |
|---|---|---|---|---|
| `bug` / `new_feature` | `True` | `how_to_answer` | `we_resolved` (box xanh = quote guideline + citation) | `bug` / `new_feature` |
| `bug` / `new_feature` | `False` | `we_listen` | `we_listen` | `bug` / `new_feature` |
| `praise` | – | `thank_you` | ack | `praise` |
| `complain` | – | `apology` | ack | `complain` |
| không xác định được `L` | – | `neutral_ack` | ack trung tính | `unclassified` |
| **bất kỳ, khi `flag=unclassified`** | – | *theo bảng trên với `L=best_label`* | *như trên* | **`unclassified`** (ghi đè) |

Dòng cuối là NOTE của user và cũng đúng §4.3: "dựng template theo `best_label` (score cao nhất)" nhưng file đi vào folder chờ duyệt. Nội dung và vị trí là **hai quyết định độc lập** — đó là lý do tách hàm `pick_scenario()` khỏi `pick_folder()`.

`known_gap` có mặt trong enum §4.6 và trong YAML, nhưng **chưa route tới được** vì bước 2 backlog chưa hiện thực. Giữ chỗ, không xoá, và ghi rõ ở đây để không ai tưởng là quên.

### D2 — Feedback trong box đỏ là **nguyên văn**, không tóm tắt

§4.6 `DraftContent` (impl §3.1) có `feedback_summary_vi/en` do LLM sinh. Bản này **không gọi LLM**: box đỏ chứa `content` nguyên văn của user.

Lý do: tóm tắt là một cơ hội nữa để bịa, và nó nằm ngay cạnh câu "vấn đề bạn đã phản hồi đã được giải quyết". Quote nguyên văn thì user tự nhận ra đúng feedback của mình; sai sót duy nhất có thể xảy ra là quote xấu, không phải quote sai. Đổi lại: feedback dài sẽ làm box đỏ dài. Chấp nhận ở scale ~100 fb/ngày; khi bật LLM summarize thì chỉ thay đúng 1 hàm `feedback_box_text()`.

Hệ quả cho R-4: box đỏ giống hệt nhau ở phần VI và EN (không dịch feedback của user). Đây là *cố ý* — dịch lại lời user rồi hiển thị như lời user là sai.

### D3 — Box xanh (`we_resolved`) = quote guideline nguyên văn + `source_ref`

`referenced` từ B2 đã đi qua cổng anchor (chỉ tồn tại nếu tìm được nguyên văn trong page). Đưa thẳng vào box xanh, kèm dòng citation `Nguồn / Source: <source_ref>`. Không diễn giải lại.

Đây là hiện thực O4 ở tầng hiển thị: mọi khẳng định "tính năng đã có" trong email đều **kèm sẵn bằng chứng** để PM đối chiếu trong 2 giây thay vì phải mở lại tài liệu.

### D4 — YAML: 1 message / scenario, VI và EN cùng nội dung

Theo yêu cầu user. Bỏ cơ chế picker-theo-hash của `reply_samples.yaml` (4 biến thể/case): biến thể chỉ có giá trị khi nhiều user cùng nhận email trong một ngày và so bì nhau — chưa phải vấn đề hiện tại, và nó làm output không deterministic nên golden-file test (impl §3.4) khó viết.

Khoá placeholder giữ nguyên quy ước file cũ: `{name}`, `{feedback_summary}`, `{resolution_details}`, `{agent}`. Placeholder không có giá trị ⇒ **fail loud**, không render chuỗi rỗng.

File: `src/03_inference/email_templates.yaml`. Nội dung gồm 3 khối:
- `meta` — from / subject / cc / logo / footer (support emails, sharepoint link, ký tên),
- `folders` — map nhãn → tên thư mục (chỗ duy nhất đổi `unclassified` ↔ `draft`),
- `scenarios` — 6 kịch bản, mỗi kịch bản `{template, vi:{...}, en:{...}}`.

### D5 — Lint bỏ qua vùng verbatim

impl §3.3 yêu cầu assert `"—" not in body`. Nhưng box đỏ chứa lời user và box xanh chứa quote tài liệu (`User Guide — TÀI (Super Agent)` có em-dash trong chính tiêu đề). Nếu lint quét cả hai thì hoặc là ta sửa lời user (không được), hoặc là lint luôn đỏ (vô dụng).

⇒ Lint quét **phần copy do template sinh ra**: strip block INTERNAL + strip nội dung 2 box verbatim, rồi mới assert. Luật giữ nguyên, phạm vi thu hẹp đúng chỗ ta kiểm soát được.

### D6 — Idempotency = tên file

§4.6 chốt khoá idempotency là `feedback_id`. Chưa có Delta ở dev ⇒ khoá đó nằm ở **tên file** `<feedback_id>.eml`. Mặc định `--skip-existing` (chạy lại không ghi đè, đếm `skipped`), `--overwrite` để ép. Manifest `manifest.csv` ở gốc `REVIEW_DIR` giữ đúng tên cột `feedback_processing` để migrate sang Delta là một câu `COPY INTO`.

### D7 — Runner là Job B, không phải module thứ 4

`run_pipeline.py` không có trách nhiệm nghiệp vụ riêng: nó gọi B1 → B2 → B3 theo đúng §4.2 Flow B, mỗi chặng ghi artifact ra đĩa trước khi chặng sau chạy (retry được từng chặng, đúng lý do tách task trong §4.2). Ở production nó bị thay bằng multi-task DAG của Databricks Jobs; ở dev nó là cùng một DAG chạy tuần tự trong 1 process.

---

## 4. Implementation

### 4.1 File mới

| File | Module | Nội dung |
|---|---|---|
| `src/03_inference/email_templates.yaml` | config | `meta` + `folders` + 6 `scenarios` (VI/EN) |
| `src/03_inference/build_email.py` | `inference.deliver` (B3) + lát chọn-template của B2 | `pick_scenario` · `pick_folder` · `render_html` · `lint_html` · `build_eml` · `run_file` · CLI |
| `src/03_inference/run_pipeline.py` | `inference` (Job B) | B1 → B2 → B3, CLI 1 lệnh |
| `data/sample/feedback_e2e_demo.csv` | fixture | 5 case × 5 nhãn = 25 dòng, agent có guideline thật |
| `src/04_tests/test_build_email.py` | test | routing scenario/folder · lint · `.eml` parse ngược · placeholder thiếu ⇒ raise |

### 4.2 Contract giữa các bước

```
data/sample/feedback_e2e_demo.csv          (agent, user, date, content[, id])
        │  B1  classify.py: classify_texts_contrastive()
        ▼
out/pipeline/<run>/b1_classified.csv       + label, flag, confidence, best_label
        │  B2  resolve_guideline.py: run_file()   [chỉ label ∈ {bug,new_feature}]
        ▼
out/pipeline/<run>/b2_resolved.csv         + solved, referenced
out/pipeline/<run>/b2_resolved.csv.debug.jsonl   → source_ref, match_type, gate
        │  B3  build_email.py: run_file()
        ▼
out/pipeline/<run>/review/<folder>/<id>.eml
out/pipeline/<run>/review/manifest.csv     feedback_id, label, flag, confidence,
                                           best_label, agent, scenario, source_ref,
                                           draft_status, eml_path
```

### 4.3 Cấu trúc HTML (bám `template/skill_create_email.md`)

Giữ nguyên khung của `template/email_temp.py`: max-width 640, nền `#f5f5f5`, card trắng radius 8, logo `cid:tai_logo` cao 48px, dòng "English version below" italic phải, separator `#e53e3e` với nhãn "ENGLISH VERSION", footer border-top `#e53e3e`. Khác 2 điểm theo impl §3.4: **UTF-8 thẳng** thay HTML entity, và **block INTERNAL** chèn trên cùng (nền vàng, viền đứt) để PM không bỏ sót.

---

## 5. Test / nghiệm thu

| # | Kiểm | Cách |
|---|---|---|
| T1 | `pick_scenario` phủ hết bảng D1 | unit, tham số hoá |
| T2 | `flag=unclassified` ⇒ folder `unclassified` dù `best_label` là gì | unit |
| T3 | `solved=False` ⇒ HTML **không** chứa câu "đã được giải quyết" / "has been resolved" | unit (chặn R-7 hồi quy) |
| T4 | `.eml` parse ngược bằng `email.parser`: đủ From/To/Cc/Subject/X-Unsent, có part `image/png` với `Content-ID: <tai_logo>` | unit |
| T5 | Placeholder thiếu ⇒ raise | unit |
| T6 | Lint bắt em-dash trong copy template nhưng bỏ qua em-dash trong box verbatim | unit |
| T7 | **E2E**: 25 feedback ⇒ 25 `.eml` phân bố đúng 5 folder, manifest 25 dòng, 0 lỗi lint | chạy thật `run_pipeline.py` |

Nghiệm thu của user: **mở được output sau khi chạy end-to-end** — cây thư mục `review/` + mở thử 1 `.eml`.

---

## 6. Lệch kiến trúc cần ghi nhận (rule #6 CLAUDE.md)

`docs/architecture.md` §2 vẽ folder cho nhánh unclassified là `draft/`. User chốt tên `unclassified/`. Tên `unclassified/` nói đúng *vì sao* file nằm đó (không phân loại được), còn `draft/` mô tả trạng thái đúng với **cả 5** folder nên không phân biệt được gì. ⇒ Cập nhật `architecture.md` §2 + §4.3 sang `unclassified/` **trước khi** code, và ghi chú tên folder do `email_templates.yaml:folders` quyết định. Ghi vào `CHANGELOG.md`.
