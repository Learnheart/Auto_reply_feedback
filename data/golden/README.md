# Golden Dataset — Intent Classification

Thư mục này có **ba** bộ nhãn vàng. Bộ hiện hành là `feedback_gold.csv` (5 label, không có `how_to`).

| File | Taxonomy | n | Trạng thái |
|---|---|---|---|
| **`feedback_gold.csv`** | **5 label**: `bug` / `new_feature` / `praise` / `complain` / `unclassified` | 192 | ✅ **Hiện hành** |
| `feedback_gold_192.csv` | 6 label (có `how_to`; tên cũ `request_feature`/`complaint`) | 192 | 📌 Tham chiếu — taxonomy cũ, KHÔNG còn là nguồn của bộ 5 label |
| `golden_intent.csv` | 5 label cũ (bug gộp vào `complaint`) | 61 (subset) | ⚠️ Legacy — giữ để truy vết |

---

## `feedback_gold.csv` — bộ hiện hành (5 label, v2)

**Định nghĩa nhãn + tie-breaker: [`intent_explain.md`](intent_explain.md)** — nguồn chuẩn khi gán/review nhãn.

Gán tay **toàn bộ 192 dòng, đọc trực tiếp từ `data/sample/feedback/feedback_extracted.csv`** (content copy nguyên văn, thứ tự dòng giữ nguyên ⇒ dòng thứ `i` = `fb_<i:04d>`). Sinh bởi `scripts/make_feedback_gold_5label.py` (deterministic, không LLM — nhãn nằm trong bảng tay `LABELS` đủ 192 entry kèm rationale, PM sửa trực tiếp rồi chạy lại). Plan: `docs/2026-09-02/feedback-gold-5label/plan.md` (Revision v2).

| label | n | % |
|---|---:|---:|
| `new_feature` | 65 | 33.9% |
| `bug` | 62 | 32.3% |
| `unclassified` | 29 | 15.1% |
| `praise` | 20 | 10.4% |
| `complain` | 16 | 8.3% |

Khác biệt phương pháp so với bộ 6 label (`feedback_gold_192.csv`):

- **KHÔNG còn rule "cắt cụt → `unclassified`"** — dòng kết thúc `…`/`...` được gán theo phần nhìn thấy khi ý đã phát biểu trọn (không suy diễn phần thiếu). Vd `fb_0004` "There must be a clear indicator when a person is out of credits...." → `new_feature`. Chỉ giữ `unclassified` khi phần quyết định nằm đúng chỗ bị cắt (`fb_0182` "nên bổ sung tính năng sau:…").
- **Câu ngắn tín hiệu rõ gán theo tín hiệu** — `fb_0009` "lỗi" → `bug`, `fb_0185` "coundn't acess" → `bug`.
- **Không có `how_to`** — hỏi năng lực chưa có → `new_feature`; hỏi kèm bức xúc → `complain` (`fb_0007`); hỏi chính sách/không suy được intent → `unclassified`.
- `unclassified` (29 dòng) giờ chỉ gồm: prompt gõ nhầm ô feedback (15), vô nghĩa/quá ngắn ("1", "uew", "No", "Test feedback"), câu hỏi chính sách (`fb_0056`, `fb_0085`), và dòng mất phần quyết định do cắt cụt. Chạy script để in danh sách kèm rationale.

```bash
python scripts/make_feedback_gold_5label.py  # tái sinh feedback_gold.csv + in phân bố & danh sách unclassified
```

---

## `feedback_gold_192.csv` — bộ tham chiếu 6 label

Gán lại toàn bộ 192 dòng của `data/sample/feedback/feedback_extracted.csv`.
Sinh bởi `scripts/relabel_feedback_gold.py` (deterministic, không gọi LLM — nhãn nằm trong bảng tay `LABELS`, PM sửa trực tiếp trong script rồi chạy lại).
Plan: `docs/2026-08-31/feedback-gold-relabel/plan.md`.

### Cột — đúng 5, không hơn

| Cột | Ý nghĩa |
|---|---|
| `agent` | Agent/function (khoá route userguide ở B2) — copy từ nguồn |
| `user` | Copy từ nguồn |
| `date` | Copy từ nguồn |
| `content` | Nội dung feedback, nguyên văn — copy từ nguồn |
| `label` | **TARGET** — 1 trong 6 label, gán tay |

Thứ tự dòng giữ nguyên như CSV nguồn ⇒ dòng thứ `i` ở đây khớp dòng thứ `i` ở `feedback_extracted.csv` (`fb_<i:04d>` theo scheme `catalog.load_feedback_index`).

Cột `category` gốc của widget **không** được mang sang — nó nhiễu tới mức gây nhầm là target (xem mục bằng chứng bên dưới).

### Taxonomy 6 label

| label | Định nghĩa | n | % |
|---|---|---:|---:|
| `bug` | Tính năng **đã có** nhưng hỏng khi dùng: error/crash/không phản hồi/mất dữ liệu/output sai hợp đồng chức năng | 49 | 25.5% |
| `request_feature` | Đóng góp/cải thiện — **có nêu hướng cải thiện cụ thể**, hoặc xin năng lực chưa có | 38 | 19.8% |
| `how_to` | Hỏi về tính năng **đã có** mà user chưa biết dùng | 10 | 5.2% |
| `praise` | Khen ngợi nói chung | 19 | 9.9% |
| `complaint` | Phàn nàn nói chung — chê chất lượng, **không** nêu cải thiện, **không** phải malfunction | 14 | 7.3% |
| `unclassified` | Không mang ý nghĩa hoặc chưa chắc chắn trong phán đoán | 62 | 32.3% |

### Nguyên tắc gán nhãn (ranh giới hay nhầm)

- **bug vs complaint vs request_feature** — quyết định lớn nhất, ~45 dòng nằm ở đây (nhóm "chê chất lượng output của AI"). Chốt **theo hành động**:

  | Ví dụ | label |
  |---|---|
  | "Translation request failed (502)", "nút copy không hoạt động", "lỗi font khi export" | `bug` |
  | "bổ sung hình ảnh cho slide đẹp hơn", "TĂNG FONT SIZE LÊN" | `request_feature` |
  | "Slide tạo chưa đẹp", "dịch quá tệ", "càng làm càng xấu" | `complaint` |

  Lý do: `bug` và `request_feature` dẫn tới hai `action_type` khác nhau ở B2 (tra backlog `known_gap` vs roadmap). Trộn chúng làm hỏng nhánh reply. `complaint` là nhánh không có action — xin lỗi + hỏi thêm.
- **how_to vs request_feature** — hỏi *tính năng đã có* → `how_to` ("Có add được nhiều file tham khảo không nhỉ?"); xin *cái chưa có* → `request_feature`.
- **Chất lượng output sai lệch dữ liệu → `bug`, không phải `complaint`.** Dịch sót ("chỉ dịch 10% văn bản"), bịa thực thể ("bịa ra MIK trong khi là Masterise"), chèn code vào bản dịch — đây là output sai hợp đồng chức năng, không phải "chê đẹp/xấu".
- **`category` widget ≠ `label`.** Đây là lý do phải có bộ này — xem mục dưới.

### 62 dòng `unclassified` KHÔNG đồng nhất

Phân tầng nằm trong `scripts/relabel_feedback_gold.py`, **không ghi ra CSV** (giữ file gọn). Chạy script để in danh sách id:

| Nguyên nhân | n | Nghĩa |
|---|---:|---|
| `truncated` | 44 | Nội dung bị cắt cụt bằng `…` lúc extract từ ảnh (`data/sample/feedback/image*.png`). Mất phần đuôi quyết định nhãn. Phát hiện tự động bằng regex đuôi. |
| `prompt_misfire` | 11 | Câu lệnh gửi agent bị gõ nhầm vào ô feedback (vd `fb_0064` "Tôi muốn gộp ba target vào 1 bảng…"). Danh sách index: hằng `PROMPT_MISFIRE`. |
| `meaningless` | 7 | Vô nghĩa/quá ngắn: "1", "uew", "Test feedback", "No". Hằng `MEANINGLESS`. |

> ⚠️ **32.3% `unclassified` là con số của tập mẫu bẩn, KHÔNG phải prior cho `unclassified_rate` production.**
> `docs/method-offline-intent-analysis.md` §4.5 đã cảnh báo đúng nhầm lẫn này.
> Cách gỡ: lấy `content` đầy đủ từ Delta thay vì OCR ảnh ⇒ 44 dòng `truncated` quay về nhãn thật, `unclassified` tụt xuống ~9%.
> Khi train/eval: loại 62 id script in ra ⇒ còn **130 dòng sạch**.

### Bằng chứng: `category` của widget không dùng làm ground truth được

Ma trận `category` (widget, ở file nguồn) × `label` (gold):

| widget | bug | complaint | how_to | praise | request_feature | unclassified | **khớp** |
|---|---:|---:|---:|---:|---:|---:|---:|
| `idea` (96) | 10 | 7 | 5 | 5 | **28** | 41 | — |
| `bug` (54) | **33** | 3 | 4 | 0 | 3 | 11 | **61%** |
| `other` (25) | 6 | 4 | 0 | 1 | 6 | 8 | — |
| `praise` (17) | 0 | 0 | 1 | **13** | 1 | 2 | **76%** |

Chỉ 2/4 giá trị widget có đối ứng trực tiếp, và cả hai đều dưới 80%. `idea` (chiếm 50% dữ liệu) rải khắp 6 label. Đo embedding với cột này thì mọi metric đều vô nghĩa.

---

## `golden_intent.csv` — legacy (5 label)

61 dòng, taxonomy cũ **không tách `bug`** (mọi báo lỗi xếp vào `complaint`). Giữ lại để truy vết, **không dùng làm target mới**.

Đối chiếu với bộ 6 label (chiếu `bug → complaint` để về cùng 5 label): **overlap 58 dòng, khớp 48, xung đột 10**.

| id | legacy | gold6 | Nguyên nhân |
|---|---|---|---|
| `fb_0039`, `fb_0091`, `fb_0141`, `fb_0190` | `request_feature` | `unclassified` | Dòng `truncated` — legacy đoán nhãn từ phần đầu câu |
| `fb_0024`, `fb_0046`, `fb_0056` | `how_to` | `unclassified` | Dòng `truncated` |
| `fb_0009` ("lỗi") | `complaint` | `unclassified` | Quá ngắn, không đủ cơ sở |
| `fb_0018` | `request_feature` | `how_to` | **Bất đồng thật** — "Tài có thể giúp tạo format dựa trên dữ liệu file excel có sẵn đưa vào ko" là câu hỏi khả năng |
| `fb_0120` ("Very quickly") | `unclassified` | `praise` | **Bất đồng thật** — khen tốc độ |

8/10 xung đột là do quy tắc `truncated → unclassified`, chỉ 2 là bất đồng phán đoán thật.

---

## Lệch tên nhãn cần biết

`src/01_intent_classification/out/*/catalog_a.json` dùng **`report_bug`**, bộ này dùng **`bug`**.
Khi eval catalog cũ: map `report_bug → bug`. Lần regen catalog kế tiếp nên đổi tên về `bug` cho thống nhất.

## Chạy lại

```bash
python scripts/relabel_feedback_gold.py
```

CSV xuất ra chỉ 5 cột. Mọi thứ còn lại (id, category widget, cờ chất lượng, lý do gán nhãn) chỉ **in ra màn hình**: phân bố nhãn, 62 id cần loại khi train/eval, ma trận widget × gold, và danh sách xung đột với `golden_intent.csv`.

---

## `feedback_gold_solved.csv` — gold `solved` cho B2 bước 1 (guideline resolve)

127 dòng `bug`/`new_feature` của `feedback_gold.csv` (id `fb_<i:04d>` giữ nguyên), thêm nhãn **đã được tài liệu giải quyết chưa** — đối chiếu 13 docx trong `data/guidelines/`. Sinh bởi `scripts/make_feedback_gold_solved.py` (deterministic, không LLM). Plan: `docs/2026-09-03/guideline-resolve-batch/plan.md`.

| Cột | Ý nghĩa |
|---|---|
| `solved` | **TARGET** — `True` chỉ khi guideline cho thấy thứ user cần ĐÃ CÓ (feature tồn tại / how-to / workaround đạt mục tiêu) |
| `match_type` | `how_to` (solved) · `limitation` (doc ghi nhận là hạn chế, không workaround ⇒ solved=False) · `none` |
| `referenced` | Quote **nguyên văn** trong page của agent (kiểm bằng gate `verify_quote`), rỗng nếu `none` |
| `rationale` | Lý do ngắn |

| | n |
|---|---:|
| `solved=True` | 12 |
| `limitation` | 22 |
| `none` | 93 |

Quy trình: 2 labeler độc lập (`solved_labelers/labels_A.csv`, `labels_B.csv`, cùng rubric precision-first) → **kappa(solved) = 0.89**, 5 dòng bất đồng → adjudication trong bảng `ADJUDICATIONS` của script. Map agent → page: `tai` đọc thêm page **GenUI** (câu trả lời cho token meter / toggle EN-VI nằm ở đó) ⇒ 4 dòng `tai` đổi nhãn so với labeler. `the-canvas-designer` không có tài liệu ⇒ luôn `False`.

> Lớp dương chỉ 12 dòng ⇒ mỗi dòng sai ≈ 8 điểm F1. Đọc kết quả kèm precision/recall, đừng chỉ nhìn F1.
