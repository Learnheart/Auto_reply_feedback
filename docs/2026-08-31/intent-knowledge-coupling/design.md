---
author: klinh2212112@gmail.com
date: 2026-08-31
status: draft
agents: inference.classify, inference.draft, unclassified_pool
summary: how_to / bug / request_feature không tách được bằng embedding vì chúng khác nhau ở một sự thật nằm trong userguide, không nằm trong feedback. So sánh 3 hướng xử lý để chốt.
---

## Architecture reference

- Module: `inference.classify` (B1) và `inference.draft` (B2) — `docs/architecture.md` §3 *Trách nhiệm từng module*; artifact liên quan: **Intent Catalog** (input tĩnh).
- Sections: `docs/architecture.md` §3 (note *Knowledge layer v3.1/v3.2*), §4.2 *Flow B — Inference hằng ngày*, §4.3 *Flow C — Threshold routing*, §4.5 *Data layer* (`intent_catalog`, `feedback_processing`, `userguide_page`), §6.1 R1/R6.
- Impl doc: `docs/impl-phase2-auto-feedback-flow.md` §3.2 (bảng chọn template theo `(action_type, rag_hit)`), §5 (`answer_from_kb` → userguide; `known_gap` → backlog).
- Method: `docs/method-offline-intent-analysis.md` §6 *Kiểm định taxonomy*, §9 *Calibrate ngưỡng*, §9.4 *Global vs per-intent*.
- Data contract: `intent_catalog.intent_id/action_type`, `feedback_processing.intent_id/confidence/flag` (§4.5).

> Tài liệu này **chỉ so sánh phương án**, chưa chốt. Sau khi chọn hướng sẽ có `plan.md` riêng, và nếu hướng được chọn làm lệch kiến trúc thì `docs/architecture.md` phải cập nhật TRƯỚC (CLAUDE.md rule 3.6).

---

## 1. Vấn đề

`how_to`, `bug`, `request_feature` **không khác nhau ở câu chữ**. Chúng khác nhau ở một **sự thật về sản phẩm**: *tính năng đó có tồn tại không, và nó có đang chạy đúng không?*

Sự thật đó nằm trong userguide. Nó **không nằm trong feedback**.

B1 hiện tại (`src/03_inference/classify.py`) nhận vào đúng một chuỗi ký tự, embed nó, rồi lấy max-cosine tới exemplar. Nó không có đường nào chạm tới userguide. Vậy nên khi ta yêu cầu nó phân biệt ba nhãn này, ta đang yêu cầu nó suy ra một sự thật không có trong input.

Ba câu sau có bề mặt ngôn ngữ gần như đồng nhất — embedding sẽ đặt chúng cạnh nhau — nhưng nhãn đúng khác nhau hoàn toàn:

| Câu | Nhãn đúng | Vì sao |
|---|---|---|
| "The translator không có lịch sử" | `how_to` | Tài liệu ghi rõ hành vi này ở mục Limitations, có workaround |
| "The brainstormer không có lịch sử" | `request_feature` | Thật sự chưa có — tài liệu xác nhận |
| "The imaginator không có lịch sử" | `bug` | Có History panel trong tài liệu mà user không thấy |

Đây là **giới hạn thông tin, không phải giới hạn mô hình**. Đổi sang embedding mạnh hơn, thêm exemplar, chỉnh ngưỡng khéo hơn — không cái nào cứu được, vì thông tin quyết định không tồn tại trong thứ ta đưa vào mô hình.

### 1.1 Quy mô

Trên tập nhãn vàng `data/golden/feedback_gold_192.csv`:

| Nhãn | n | Phụ thuộc userguide? |
|---|---:|---|
| `bug` | 49 | ✅ |
| `request_feature` | 38 | ✅ |
| `how_to` | 10 | ✅ |
| `praise` | 19 | ❌ quyết định được từ câu chữ |
| `complaint` | 14 | ❌ quyết định được từ câu chữ |
| **Tổng dòng sạch** | **130** | **97/130 = 75% phụ thuộc userguide** |

Ba phần tư dữ liệu dùng được nằm trong đúng ba nhãn B1 không thể tách.

### 1.2 Bằng chứng: nhãn vàng hiện tại sai có hệ thống

Tôi gán 192 dòng đó **mà không đọc userguide** — đúng cái lỗi B1 đang mắc. Đối chiếu lại 11 dòng có thể tra trực tiếp trong `data/guidelines/`:

| id | agent | Feedback | Userguide nói gì | Gold hiện tại | Đúng ra |
|---|---|---|---|---|---|
| `fb_0008` | translator | "không có lịch sử… refresh lại thì mất luôn" | Limitations: *"Upon page refresh, the progress information or translated file is no longer visible"* + Tips: *"Cancel a long translation by refreshing the page"* | `request_feature` | **`how_to`** |
| `fb_0040` | powerpoint-er | "ấn re-generate… muốn quay lại version đầu nhưng ko được" | Step 4: *"click 'Regenerate from outline' to restore the initial generated version"* | `request_feature` | **`how_to`** |
| `fb_0072` | powerpoint-er | "slide vừa gen xong, không thể edit file được" | Limitations: *"only inline content updates are supported… For advanced adjustments, required export and download the PowerPoint file for local editing"* | `bug` | **`how_to`** |
| `fb_0112` | powerpoint-er | "cần xuất chart dạng chart, hiện xuất ảnh không sửa được" | Limitations: *"no custom animations or complex charts"* | `bug` | **`request_feature`** |
| `fb_0105` | powerpoint-er | "hãy tạo slide theo mẫu trình bày của TCB" | Features: *"Branded templates — Slides use Techcombank's visual identity"* + Limitations: *"Adding templates directly is not available"* | `unclassified` (prompt_misfire) | **`how_to`** |
| `fb_0113` | brainstormer | "session đã complete và ko mở lại được" | Limitations: *"Each session is independent"* | `bug` | ⚠️ nghi ngờ — tài liệu nói về memory, chưa nói về mở lại session |
| `fb_0059` | powerpoint-er | "I don't see my past ppt presentation here" | *"The homepage displays all previously saved presentations, click 'Open'"* | `how_to` | ✅ đúng |
| `fb_0097` | brainstormer | "Add a function to add files docx/pptx/pdf" | Limitations: *"No file upload support — text-based interaction only"* | `request_feature` | ✅ đúng |
| `fb_0081`, `fb_0137`, `fb_0143` | powerpoint-er | xin thêm hình ảnh vào slide | Limitations: *"Image insertion is not supported"* | `request_feature` | ✅ đúng |

**5 sai / 1 nghi ngờ / 5 đúng.**

Đây **không phải mẫu ngẫu nhiên** — tôi chọn đúng những dòng tra được trực tiếp trong tài liệu. Nhưng chính tập đó là nhóm `capability_gap`, tức là nhóm đang bàn. Tỉ lệ sai ~45% trong nhóm này là con số đáng tin để ra quyết định.

Hệ quả: **không thể đo B1 bằng bộ nhãn vàng hiện tại.** Cần một lượt gán lại có đối chiếu userguide trước khi bất kỳ con số accuracy nào có nghĩa.

### 1.3 Vì sao kiến trúc hiện tại tự mâu thuẫn

`action_type` trong catalog chọn **một** nguồn knowledge theo intent:

```
how_to          -> answer_from_kb  (userguide)
request_feature -> known_gap       (backlog)
report_bug      -> known_gap       (backlog)
```

Nhưng việc *chọn nguồn nào* lại phụ thuộc câu trả lời mà ta chưa có. Ta cần userguide để biết đây là `how_to`, nhưng chỉ tra userguide sau khi đã kết luận là `how_to`. **Vòng lặp phụ thuộc.**

---

## 2. Nền tảng: userguide có gì

13 file trong `data/guidelines/`, tổng **78.590 ký tự (~25k token)**.

Con số này quan trọng: **cả kho tài liệu nhét vừa một prompt.** Nghĩa là mọi phương án dưới đây đều rẻ — không cần vector search, không cần chunk, và nếu muốn còn không cần cả routing `agent → page`.

### 2.1 Ba vấn đề của nguồn tài liệu

**(a) Map `agent → userguide` phải viết tay.** Khớp fuzzy hỏng ở đúng hai agent nhiều feedback nhất:

| agent | n fb | File đúng | Vì sao fuzzy hỏng |
|---|---:|---|---|
| `tai` | 34 | `User Guide — TÀI (Super Agent).docx` | Dấu tiếng Việt (TÀI) |
| `tai-studio` | 5 | `TÀI Studio — User guide.docx` + `TÀI Studio GenUI.docx` | Hai file cho một agent |
| `the-canvas-designer` | 2 | **không có** | Chưa viết tài liệu |

`the-canvas-designer` không có userguide ⇒ theo v3.1 sẽ luôn rơi `we_listen`, bất kể phương án nào.

**(b) Tài liệu cũ hơn feedback 1–3 tháng.** Feedback mới nhất là `2026-08-24`:

| Userguide | Last updated | Lệch | n fb |
|---|---|---:|---:|
| The Powerpoint-er | 2026-05-28 | **~3 tháng** | **74** |
| The Translator | 2026-05-25 | ~3 tháng | 33 |
| TÀI (Super Agent) | 2026-05-28 | ~3 tháng | 34 |
| The Brainstormer | 2026-06-22 | ~2 tháng | 17 |
| The Summarizer | 2026-07-15 | ~1.5 tháng | 16 |
| The Imaginator | 2026-07-10 | ~1.5 tháng | 4 |
| TÀI Studio GenUI | 2026-08-13 | 11 ngày | — |
| The Scholar | 2026-08-14 | 10 ngày | 2 |
| The AI Coach / The Whiteboarder | **không ghi** | ? | 2 |

Agent nhiều feedback nhất lại có tài liệu cũ nhất. Đây là rủi ro nền của **cả ba phương án**: nếu tài liệu lệch sản phẩm, hệ thống sẽ trả lời sai một cách tự tin.

**(c) `data/guidelines/` chưa được wire vào code nào.** `grep -rn "guidelines" src/ scripts/` không ra kết quả. Knowledge layer hiện fetch từ Confluence qua MCP (`src/02_knowledge/mcp_atlassian_call.py`). Phải chốt: đây là nguồn thay thế, hay chỉ là bản offline để phát triển?

---

## 3. Ba hướng tiếp cận

Cả ba đều xuất phát từ cùng một nhận định ở §1 và chỉ khác nhau ở **đặt bước phân loại tinh ở đâu**.

---

### Hướng 1 — Hai tầng, B1 gộp còn 4 nhãn ⭐ khuyến nghị

#### Cơ chế

B1 chỉ quyết định **dạng phát ngôn** — thứ nằm trong câu chữ và embedding làm tốt:

| Nhãn B1 | Nghĩa | n (trong 130 dòng sạch) |
|---|---|---:|
| `capability_gap` | Có vướng mắc về một tính năng: hỏi cách dùng / báo không làm được / xin thêm | 97 |
| `praise` | Khen | 19 |
| `complaint` | Chê chất lượng chung, không nhắm tính năng cụ thể | 14 |
| `unclassified` | Vô nghĩa / không chắc | — |

B2 phân giải `capability_gap` bằng knowledge, theo **chuỗi** thay vì chọn một nguồn:

```
capability_gap
   │
   ├─ answer_from_userguide_batch(agent → page)
   │     hit=True  ─────────────────────────► how_to
   │        │                                 (trả lời + trích tài liệu)
   │        └─ verdict=documented_limitation ► how_to
   │                                           (giải thích + workaround)
   │     hit=False
   │        ▼
   ├─ answer_from_backlog_batch(cả danh sách)
   │     hit=True  ─────────────────────────► request_feature | bug
   │                                           (đang trong backlog + trạng thái)
   │     hit=False
   │        ▼
   └─ we_listen  (ghi nhận chung, không hứa mốc — gate an toàn giữ nguyên)
```

Bảng phân giải đầy đủ:

| Userguide | Backlog | → intent cuối | Reply |
|---|---|---|---|
| Có tính năng, có hướng dẫn | — | `how_to` | Trích hướng dẫn |
| Có, là **limitation đã ghi** | — | `how_to` | Giải thích + workaround |
| Không có trong tài liệu | Có | `request_feature` | "Đang trong backlog" + trạng thái |
| Không có trong tài liệu | Không | `request_feature` | Ghi nhận roadmap |
| Tài liệu nói có, user báo lỗi kỹ thuật | Có/Không | `bug` | Xin lỗi + tra backlog |
| Không map được page / LLM không trả lời được | Không | — | `we_listen` |

#### Cần sửa gì

| Việc | Chi tiết |
|---|---|
| Catalog | 4 intent thay 6. Chọn lại exemplar. `action_type` mới `resolve_capability`. |
| Calibrate | Chạy lại `method §9` — holdout, ngưỡng per-intent. 4 nhãn ít hơn ⇒ mỗi nhãn nhiều mẫu hơn ⇒ thực ra **dễ** hơn hiện tại. |
| `knowledge.py` | Prompt userguide trả thêm field `verdict: documented_feature \| documented_limitation \| not_in_doc`. |
| `respond.py` | Nhánh `resolve_capability`: userguide → backlog → we_listen. Gate `hit=False ⇒ we_listen` giữ nguyên, chỉ chèn thêm một bậc trước khi suy giảm. |
| `feedback_processing` | **Thêm cột `resolved_intent`** bên cạnh `intent_id`. ⚠️ Đây là đổi data contract ⇒ `architecture.md` §4.5 phải cập nhật TRƯỚC (rule 3.6). |
| Nhãn vàng | Gán lại 97 dòng `capability_gap` có đối chiếu userguide; file gold tách 2 cột (thô đo B1, tinh đo B2). |

#### Ưu

- **Mỗi quyết định nằm ở nơi có thông tin để ra quyết định đó.** Đây là lý do chính, các lợi ích khác đều là hệ quả.
- **B1 trở nên đo được.** 4 nhãn tách nhau rõ ở bề mặt ⇒ cosine có nghĩa ⇒ ngưỡng calibrate được thật (§9).
- **`unclassified_rate` đo được thật.** Chỉ số này là "điều kiện sống" của giả định A6 (taxonomy đóng băng, §6.1 R1). Hiện tại nó bị nhiễu bởi ranh giới how_to/bug vốn đã lẫn — sửa xong mới biết drift thật hay không.
- **Giải quyết vấn đề mẫu ít.** `how_to` hiện chỉ 10 mẫu — quá ít để đặt ngưỡng per-intent (§9.4). Gộp vào `capability_gap` thì hết vấn đề.
- **Chi phí LLM gần như không đổi.** Kho tài liệu 78.6k chars, batch prompting v3.2 đã amortize context trên K feedback/call.
- **Khớp code sẵn có.** `answer_from_userguide_batch` và `answer_from_backlog_batch` đều đã tồn tại; chỉ nối chuỗi lại thay vì chọn một.

#### Nhược

- Phải **regen catalog + calibrate lại ngưỡng** — công việc Phase 0, không phải sửa vài dòng.
- **Đổi data contract** (`resolved_intent`) ⇒ phải sửa `architecture.md` trước khi code.
- **Dồn rủi ro vào chất lượng userguide.** Tài liệu Powerpoint-er cũ 3 tháng mà gánh 74/192 feedback. Tài liệu sai ⇒ trả lời sai một cách tự tin — nguy hiểm hơn im lặng.
- PM phải đọc hai tầng nhãn khi review draft.

#### Chọn khi

Còn ở Phase 0, chưa freeze catalog, chấp nhận đầu tư một lần cho đúng. **Đây là tình trạng hiện tại của dự án.**

---

### Hướng 2 — Hai tầng, B1 giữ `bug_explicit` tách riêng

#### Cơ chế

Như Hướng 1, nhưng B1 có 5 nhãn: tách `bug_explicit` khỏi `capability_gap`.

Định nghĩa phải **đo được**, nếu không lại rơi vào đúng cái bẫy đang gỡ. Tiêu chí: câu chứa **tín hiệu lỗi hệ thống tường minh**, tức thứ nhìn thấy ở bề mặt:

- mã lỗi — `"Translation request failed (502)"` (`fb_0184`)
- tên lỗi hệ thống — `"LLM: structured output failed"` (`fb_0111`), `"network error"` (`fb_0109`, `fb_0116`)
- crash / mất phản hồi — `"Trả kết quả xong tự crash"` (`fb_0156`)
- không truy cập được — `"lỗi truy cập k vào đc"` (`fb_0191`), `"coundn't acess"` (`fb_0185`)

Nhóm này đi thẳng `known_gap` (tra backlog), bỏ qua userguide. Ước lượng **15–20 dòng** trong 130.

#### Ưu

- Reply được ngay, không cần userguide ⇒ nhanh hơn, ít gọi LLM hơn.
- Reply cho lỗi hệ thống khác hẳn về giọng (xin lỗi + đang xử lý, không trích tài liệu) ⇒ template sạch hơn.
- Vẫn giữ nguyên tinh thần tầng 2 cho phần còn lại.

#### Nhược

- **Thêm một ranh giới phải calibrate, và ranh giới này cũng mờ.** "không dịch được" có explicit không? "lỗi" thì sao? Ta vừa gỡ một ranh giới mờ, giờ thêm lại một cái.
- **Mẫu quá ít.** 15–20 dòng không đủ để đặt ngưỡng per-intent đáng tin (§9.4).
- **Nhược nghiêm trọng nhất:** câu có chữ "lỗi" nhưng thực chất là limitation đã ghi sẽ bị bắt vào `bug_explicit` và **bỏ qua userguide**. Chính là `fb_0072` — *"slide vừa gen xong, nhưng không thể edit file được"* — nghe như lỗi, thực ra tài liệu đã ghi rõ kèm workaround. Hướng này tái tạo đúng lỗi ban đầu, chỉ trên một tập nhỏ hơn.

#### Chọn khi

Volume lỗi hệ thống lớn và cần tiết kiệm LLM call. Ở mức ~100 fb/ngày (A1), khoản tiết kiệm không đáng so với rủi ro.

---

### Hướng 3 — Giữ 6 nhãn, override ở B2

#### Cơ chế

Không đụng taxonomy. B1 vẫn đoán 6 nhãn như hiện tại. B2 chạy knowledge; nếu userguide mâu thuẫn thì đổi nhãn trước khi render email, ghi cả hai vào block INTERNAL cho PM.

```
B1: how_to (c=0.62)
  └─► B2 đọc userguide → không có tính năng
        └─► OVERRIDE thành request_feature
              INTERNAL: "intent=how_to nhưng đã đổi sang request_feature
                         vì userguide không có tính năng này"
```

#### Ưu

- **Rẻ nhất.** Không regen catalog, không calibrate lại, triển khai được ngay.
- Không đổi data contract nếu chỉ ghi override vào `internal_note`.
- **Đảo ngược được.** Thử, thấy không ổn thì bỏ, không mất gì.

#### Nhược

- **B1 confidence trở thành số vô nghĩa cho 3 nhãn** — mà confidence chính là trục routing của §4.3 (`ok` / `low_confidence` / `unclassified`). Ta sẽ route dựa trên một con số đo sai.
- **`unclassified_rate` bị nhiễu.** Chỉ số giám sát A6/R1 không còn phân biệt được: unclassified tăng vì drift thật, hay vì ranh giới how_to/bug vốn đã lẫn?
- **Tỉ lệ override cao thì "override" không còn là override.** Spot-check §1.2 gợi ý ~45% nhóm capability bị sửa. Khi gần một nửa bị sửa, tầng "sửa" mới là tầng phân loại chính — chỉ là không được gọi tên. Kiến trúc nói dối về chính nó, và mọi người đọc nó sẽ hiểu sai hệ thống làm gì.
- **Không bao giờ đo được B1.** Output cuối luôn bị B2 sửa ⇒ không biết B1 tốt hay xấu ⇒ không biết có nên cải thiện nó không.
- PM đọc INTERNAL thấy "intent nói X nhưng gửi Y" ở gần một nửa số email.

#### Chọn khi

Cần chạy production gấp, chấp nhận nợ kỹ thuật, **và có kế hoạch cụ thể chuyển sang Hướng 1 sau**. Nếu không có kế hoạch đó thì nợ này không trả được — vì càng chạy lâu, catalog và ngưỡng càng bám rễ.

---

## 4. So sánh

| Tiêu chí | H1 — 4 nhãn | H2 — 5 nhãn | H3 — override |
|---|---|---|---|
| Đặt quyết định đúng chỗ có thông tin | ✅ | ✅ phần lớn | ❌ |
| B1 đo được | ✅ | ✅ | ❌ |
| `unclassified_rate` (A6/R1) tin được | ✅ | ✅ | ❌ |
| Ngưỡng calibrate được (§9.4) | ✅ nhãn ít, mẫu nhiều | ⚠️ `bug_explicit` chỉ 15–20 mẫu | ❌ |
| Phải regen catalog | ✅ có | ✅ có | ❌ không |
| Phải calibrate lại ngưỡng | ✅ có | ✅ có | ❌ không |
| Đổi data contract | ✅ có (`resolved_intent`) | ✅ có | ❌ không |
| Phải sửa `architecture.md` trước | ✅ có | ✅ có | ⚠️ nhẹ |
| Triển khai được ngay | ❌ | ❌ | ✅ |
| Đảo ngược được | ⚠️ khó | ⚠️ khó | ✅ |
| Rủi ro tài liệu cũ | cao | cao | cao |
| PM đọc dễ | ⚠️ 2 tầng | ⚠️ 2 tầng | ❌ override khó hiểu |

**Khuyến nghị: Hướng 1.**

Lý do quyết định không phải là nó nhiều ưu điểm hơn, mà là: dự án **đang ở Phase 0, catalog chưa freeze, ngưỡng chưa calibrate**. Chi phí lớn nhất của H1 (regen + calibrate) là việc **dù sao cũng phải làm**. Trả bây giờ thì rẻ; trả sau khi đã freeze và chạy production thì đắt hơn nhiều.

H3 hấp dẫn khi đã có hệ thống chạy và không muốn đụng vào. Ở đây chưa có gì để bảo vệ.

---

## 5. Rủi ro nền — đúng cho cả ba hướng

**R-A · Userguide cũ hơn sản phẩm.** Powerpoint-er gánh 74/192 feedback với tài liệu cũ 3 tháng. Cả ba hướng đều tin vào tài liệu ⇒ tài liệu sai thì hệ thống trả lời sai một cách tự tin. Trả lời sai tự tin **tệ hơn im lặng**.

*Giảm thiểu:* trước khi triển khai, đối chiếu tay khoảng 20 feedback với userguide tương ứng (như §1.2 đã làm) và đo tỉ lệ tài liệu lệch. Nếu >20% thì phải cập nhật tài liệu trước, không phải sửa classifier trước.

**R-B · `the-canvas-designer` không có userguide.** Luôn rơi `we_listen`. Cần hoặc viết tài liệu, hoặc chấp nhận và ghi rõ.

**R-C · Map `agent → page` phải viết tay.** Khớp tự động hỏng ở `tai` (34 fb) và `tai-studio` (5 fb) vì dấu tiếng Việt và một agent hai file. Cần bảng cứng, có test.

**R-D · Nhãn vàng phải làm lại.** 97 dòng `capability_gap` phải gán lại có đối chiếu tài liệu. Không có bước này thì mọi con số accuracy sau đó đều vô nghĩa — kể cả để so ba hướng với nhau.

---

## 6. Cần chốt

1. **Chọn hướng** — H1 / H2 / H3.
2. **Vai trò `data/guidelines/`** — nguồn offline để phát triển (Confluence vẫn là nguồn thật), hay thay luôn Confluence cho nhánh userguide? Ảnh hưởng `ingest-sync` (Job A) và §3.
3. **Ai xác nhận độ đúng của userguide?** R-A là rủi ro lớn nhất và nó nằm ngoài tầm code.
4. **Nhãn vàng gán lại: tay hay LLM-assisted?** 97 dòng, có tài liệu kèm — LLM đề xuất + người duyệt là khả thi (đúng tinh thần method §7 *Review gate*).
