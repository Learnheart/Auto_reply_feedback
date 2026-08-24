# Phase 2 — Auto Feedback Flow

| Field | Value |
|-------|-------|
| **Date** | 2026-08-25 |
| **Depends on** | Phase 1 đã qua acceptance (`docs/impl-phase1-intent-classification.md`) · `docs/architecture.md` v3.0 §4.2/§4.4 · `template/skill_create_email.md` |
| **Deliverable** | Job A `ingest-sync` · task B2 `draft` · B3 `deliver` · Job C `outcome-sync` · dashboard |

## 0. Phase này giải quyết cái gì

Phase 1 dừng ở `feedback_processing` có `intent_id` + `confidence` + `flag`. Phase 2 biến row đó thành một email draft nằm trong đúng folder Outlook, rồi đọc ngược lại xem PM đã làm gì với nó.

Điểm đáng chú ý sau khi đọc `template/`: **template thật chỉ có 2 loại (`we_listen`, `we_resolved`), không phải một template mỗi intent như §4.5 giả định qua `email_template_id`.** Nên trục thật là:

```
action_type (+ RAG hit)  ──▶  chọn template   (2 lựa chọn)
intent_id                ──▶  chọn folder     (N lựa chọn)
```

Đây là simplification tốt, và nó có nghĩa `intent_catalog.email_template_id` nên đổi thành `action_type` → template map trong config, thay vì một cột per-intent. Ít chỗ để lệch hơn.

---

## 1. Chặn cứng phải xử lý trước khi code

| # | Vấn đề | Trạng thái |
|---|---|---|
| **B-1** | `template/email_temp.py:20` đọc `icon TAI.png` nhưng **file không có trong repo**. Script hiện tại crash ở `open(IMAGE_PATH)`. | Cần asset. Logo bắt buộc embed qua MIME, không được link ngoài (skill note cuối). |
| **B-2** | Spike Graph API (§6.3 bước 1) chưa làm. Chưa biết `singleValueExtendedProperties` có sống qua bước Send không. | O4 và O5 treo vào đây. Làm trước mọi logic. |
| **B-3** | Feedback datalake có `user_email`, **không có tên người**. Template bắt buộc `recipient_name`. | Xem §3. |

**B-3 làm rõ:** ba lựa chọn, không lựa chọn nào miễn phí:

| Cách | Được | Mất |
|---|---|---|
| Graph `GET /users/{email}` → `displayName`, cache vào bảng `user_ref` | Tên đúng, có sẵn nếu đã xin Graph | Cần thêm scope `User.Read.All` — xin cùng lúc với `Mail.ReadWrite` |
| Suy từ prefix email (`phuongntt2` → ?) | Không xin gì | Không đáng tin. `phuongntt2` → "Phương" là đoán, và đoán sai tên người trong email gửi khách là lỗi nhìn thấy ngay |
| Bỏ tên, chào trung tính (`Xin chào bạn,` / `Hi there,`) | Không bao giờ sai | Lạnh hơn, ngược với "tone warm but human" của skill |

**Đề xuất:** Graph lookup + cache, fallback về chào trung tính khi không tra được. Xin `User.Read.All` chung một lần với B-2, đừng để thành vòng xin phép thứ hai.

---

## 2. Thứ tự triển khai

Mỗi bước là một cửa chặn. Bước 1 và 2 không phụ thuộc Phase 1, làm song song với nó được.

```
 ①  Spike Graph API (2-3 ngày)  ────────────────┐   ← B-2, làm trước tiên
 ②  Render layer + golden test  ────────────────┤   ← thuần deterministic
                                                 │
 ③  Job A ingest-sync (KB + backlog) ───────────┤   ← B2 cần index mới chạy được
                                                 ▼
 ④  B2 draft  ──▶  ⑤ B3 deliver  ──▶  ⑥ Job C outcome-sync
                                                 │
 ⑦  metrics_event + SQL dashboard  ◀─────────────┘
 ⑧  Shadow run 1 tuần (folder _shadow)
 ⑨  Bật production cho 1 intent an toàn nhất
```

Bắt đầu ở ② chứ không ở ④, vì render layer là phần duy nhất test được đầy đủ không cần LLM, không cần Graph, không cần Delta. Nó cũng là phần PM soi kỹ nhất.

---

## 3. ② Render layer

### 3.1 Luật cứng: LLM sinh **text**, template sinh **HTML**

```python
class DraftContent(BaseModel):          # structured output của LLM
    greeting_name: str
    feedback_summary_vi: str
    feedback_summary_en: str
    resolution_vi:  str | None          # None ⇒ dùng we_listen
    resolution_en:  str | None
    resolution_timeline: str | None     # cho we_listen
    citations: list[Citation]
    insight: InsightDraft | None
```

LLM **không bao giờ** được emit HTML. Nó điền các field trên, template render. Ba lý do: markup không vỡ được, style không drift khỏi spec `#e53e3e`/`#e8f5e9`, và nội dung LLM luôn đi qua `autoescape` nên không inject được gì vào body.

### 3.2 Chọn template — theo `(action_type, rag_hit)`, không chỉ `action_type`

| `action_type` | RAG có hit? | Template | Ghi chú |
|---|---|---|---|
| `answer_from_kb` | ✅ | `we_resolved` | `resolution_details` = câu trả lời + citation |
| `answer_from_kb` | ❌ | `we_listen` | **Suy giảm, không được claim** |
| `known_gap` | – | `we_listen` | `resolution_timeline` từ `backlog_ref.status` |
| `ack_only` | – | `we_listen` (biến thể trung tính) | Không hứa mốc thời gian |
| `flag=unclassified` | – | `we_listen` (biến thể trung tính) | Ack ngắn, Haiku 4.5 (§5) |

Dòng thứ hai là dòng quan trọng nhất. `we_resolved` nói nguyên văn *"vấn đề bạn đã phản hồi đã được giải quyết"*. Đó là một khẳng định. Nếu RAG không tìm được gì trong userguide mà vẫn render `we_resolved`, hệ thống đang nói dối user một cách tự tin — đúng failure mode R6, chỉ tệ hơn vì nó chạm tới khách. **Không có RAG hit đạt ngưỡng ⇒ tự động rơi về `we_listen`.** Đây là một dòng if, không phải một tính năng.

Biến thể trung tính cho `unclassified` / `ack_only`: giữ nguyên khung `we_listen` nhưng **bỏ câu chứa `{resolution_timeline}`**. Câu gốc *"Team TÀI Studio đã ghi nhận phản hồi này. {timeline}. Chúng tôi sẽ thông báo lại khi tính năng sẵn sàng"* hứa hai thứ mà nhánh `unclassified` không có cơ sở nào để hứa.

### 3.3 Style rules → lint check, không phải hướng dẫn

`template/skill_create_email.md:99-108` có các luật mà LLM sẽ vi phạm không đều. Biến hết thành assert chạy trên output trước khi ghi Delta:

```python
def lint(html: str, content: DraftContent) -> None:
    body = strip_internal_block(html)
    assert "—" not in body,                    "em dash là AI tell (skill:100)"
    assert not EMOJI_RE.search(body),          "không icon/emoji trong body (skill:104)"
    assert "TÀI Studio" in body
    assert not re.search(r"T[àa]i Studio", body), "sai casing thương hiệu (skill:6)"
    assert "cid:tai_logo" in html
```

Vi phạm ⇒ retry LLM một lần rồi fail row đó, **không** ghi ra. Rẻ, và nó chặn đúng loại lỗi mà con người không soi nổi trên 100 draft/ngày.

### 3.4 Golden-file test

Port `template/email_temp.py` thành `src/afr/render/templates.py` (jinja2, autoescape on). Chốt một golden file: render với input đã biết ⇒ so byte-for-byte với HTML kỳ vọng. Đây là hàng rào duy nhất chống việc ai đó sửa CSS làm vỡ layout Outlook mà không ai thấy.

Hai quyết định nhỏ khi port:

- **HTML entity vs UTF-8.** File mẫu escape toàn bộ tiếng Việt thành entity (`Ph&#432;&#417;ng`). Không template hoá nổi kiểu đó. Mà `MIMEText(html, "html", "utf-8")` + `<meta charset="UTF-8">` đã đủ. **Đề xuất: chuyển UTF-8 thẳng, verify trong spike ①** trên Outlook desktop + OWA. Entity là belt-and-braces của thời Outlook cũ.
- **Sample lệch spec.** `template/email_temp.py:45` viết *"nhu cầu của bạn hiện đã có thể được xử lý theo 2 cách"*, còn skill chốt *"vấn đề bạn đã phản hồi đã được giải quyết"*. Lấy **skill làm spec**, sample chỉ là một instance.

---

## 4. ③ Job A `ingest-sync`

| Nguồn | Ra | Điểm cần cẩn thận |
|---|---|---|
| OneDrive userguide | Vector Search index | Chunk **phải** mang `driveItemId` + `lastModifiedDateTime` + heading của section |
| Jira | `backlog_ref` | `embedding` của `summary + description` để B2 đối chiếu bằng semantic, không phải keyword |

`lastModifiedDateTime` trong chunk metadata không phải để cho đẹp — nó là thứ đi vào citation, và là thứ cho phép R6 fail loud: file đổi mà index không đổi ⇒ so `lastModifiedDateTime` của chunk với của driveItem, lệch thì job fail, không im lặng chạy tiếp. R6 là failure mode nguy hiểm nhất của cả hệ vì nó *trông giống thành công*.

---

## 5. ④ B2 `draft`

```
đọc feedback_processing WHERE draft_status IS NULL
  │
  ├─ flag ∈ {ok, low_confidence}
  │    ├─ RAG: Vector Search top-k userguide → chunks + citation
  │    ├─ backlog: cosine(feedback.embedding, backlog_ref.embedding) → ticket | none
  │    ├─ Sonnet 4.6 → DraftContent (structured, pydantic)
  │    ├─ insight extract → development_insight
  │    └─ render + lint → draft_body_html, draft_body_hash
  │
  └─ flag = unclassified
       ├─ SKIP RAG, SKIP backlog          ← không có intent thì không có gì để tra
       ├─ Haiku 4.5 → ack ngắn trung tính
       └─ render (we_listen trung tính) + lint

UPDATE draft_body_html, draft_body_hash, draft_status='pending_deliver', drafted_at
```

Nhánh `unclassified` cố tình bỏ RAG: không có intent thì không có truy vấn có nghĩa để đưa vào Vector Search, và một câu trả lời RAG cho câu hỏi hệ thống không hiểu chính là cách tạo ra draft vô dụng mà R1 cảnh báo.

`draft_body_hash` ghi ở đây, dùng ở Job C để tính `edit_distance`.

### Block INTERNAL

Nội dung tối thiểu cho PM ra quyết định: `feedback_id` · `intent_id` + `confidence` + `flag` · template đã chọn · citation kèm `lastModifiedDateTime` · Jira match nếu có · insight đã trích · cờ ⚠ khi `low_confidence`.

Ba luật đặt block:

1. **Đặt trên cùng body.** PM cuộn xuống đọc email thì thấy nó trước, không thể lỡ.
2. **Marker là một token tìm được:** `TAI-INTERNAL-DO-NOT-SEND`. Job C grep đúng token này. Đừng dùng chữ `INTERNAL` trần — nó xuất hiện trong văn bản thường được.
3. **`strip_internal_block()` phải chạy trước `lint()`** (§3.3), nếu không mọi luật style sẽ bị block INTERNAL làm nhiễu.

> **R4 hở một chỗ arch chưa nói:** cơ chế phát hiện leak nằm ở Job C, mà Job C **chỉ tồn tại ở nhánh Graph**. Đi nhánh `.eml` (fallback A2) thì block INTERNAL nằm trong body **và không có gì phát hiện leak cả** — R4 mất sạch lưới an toàn. Nhánh `.eml` nên đưa toàn bộ nội dung INTERNAL ra **file sidecar** `out/<feedback_id>.internal.md` cạnh file `.eml`, body email sạch hoàn toàn. Mất tiện lợi (PM mở 2 file), nhưng triệt tiêu cả class lỗi thay vì đi phát hiện nó.

---

## 6. ⑤ B3 `deliver`

```python
class DraftSink(Protocol):
    def ensure_folder(self, name: str) -> str: ...
    def deliver(self, draft: Draft) -> DraftRef: ...
```

| Implement | Khi nào | Ghi chú |
|---|---|---|
| `EmlSink` | Mặc định V1, và fallback vĩnh viễn nếu A2 sai | Dùng lại nguyên `MIMEMultipart("related")` + `X-Unsent: 1` + `cid:tai_logo` của `template/email_temp.py`. Không có folder routing, không có Job C. |
| `GraphSink` | Bật bằng config sau khi ① xong | `ensure_folder` idempotent theo tên · `POST /messages` · gắn `X-Feedback-Id` vào `singleValueExtendedProperties` |

Hai sink sau một Protocol tốn thêm khoảng một file. Đổi lại V1 chạy được ngay hôm nay bằng `.eml` mà không phải viết lại B3 khi Graph được duyệt, và giữ được đường lùi khi A2 sai.

**Idempotency:** đọc `draft_status` trước khi POST, chỉ xử lý `pending_deliver`. Retry B3 sau lỗi 429 không tạo draft thứ hai. Đây chính là lý do §4.2 tách B2/B3 — `draft_body_html` đã nằm an toàn trong Delta, retry không phải trả tiền LLM lại.

State machine, một chiều, không có vòng:

```
NULL ──B2──▶ pending_deliver ──B3 ok──▶ drafted ──JobC──▶ sent | edited_sent | rejected
                    │
                    └──B3 fail──▶ error   (retry được, không mất draft_body_html)
```

---

## 7. ⑥ Job C `outcome-sync`

Theo §4.4. Suy outcome: `200` → pending · `404` + có trong Sent → sent · `404` + Sent rỗng → rejected.

Khớp draft ↔ sent message **bắt buộc bằng `X-Feedback-Id`**, không bằng heuristic. Với hệ này lý do còn mạnh hơn R5 nói: **subject là hằng số** cho mọi email (`[TÀI Studio] Your TÀI Studio feedback`, skill:15). Khớp bằng `(subject, recipient, thời gian)` không chỉ *sai khi PM sửa subject* mà là **không khả thi ngay từ đầu** — mọi draft có subject giống nhau y hệt.

Leak alert: `sent_body` chứa `TAI-INTERNAL-DO-NOT-SEND` ⇒ alert ngay. Metric này phải luôn bằng 0.

---

## 8. ⑦ Metrics

| Metric | Nguồn | Bẫy |
|---|---|---|
| `unclassified_rate` | `feedback_processing.flag` | Chỉ số sống còn (R1). So với noise rate offline ở Phase 1 step 3 để biết có drift thật hay chỉ là baseline |
| `edit_distance` theo intent | Job C | **Loại `flag='unclassified'` khỏi phép tính.** PM viết lại gần hết ack trung tính nên nhánh này luôn có distance cao, tính chung sẽ kéo lệch tín hiệu "intent nào template sai" |
| leak count | Job C | Luôn phải 0 |
| phân bố 3 vùng | `flag` | So với phân bố holdout Phase 1. Lệch nhiều ⇒ ngưỡng đã hết đúng |
| chi phí LLM / feedback | `metrics_event` | Tách Sonnet (nhánh ok) vs Haiku (nhánh unclassified) |

---

## 9. Acceptance criteria

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| P2-1 | Golden-file test render pass cho cả `we_listen`, `we_resolved`, biến thể trung tính | pytest |
| P2-2 | `lint()` chặn được em dash, emoji, sai casing "TÀI Studio" | pytest, input vi phạm cố ý |
| P2-3 | `action_type=answer_from_kb` + RAG 0 hit ⇒ render `we_listen`, **không** `we_resolved` | pytest |
| P2-4 | Draft mở được trong Outlook, logo hiện, layout không vỡ (desktop + OWA) | Kiểm tay ở ① |
| P2-5 | `X-Feedback-Id` sống sót qua Send | Spike ① — nếu fail, cả O4 + O5 phải thiết kế lại |
| P2-6 | Chạy B3 hai lần ⇒ 1 draft, không phải 2 | Test idempotency |
| P2-7 | B3 fail 429 ⇒ retry chỉ B3, không gọi lại LLM | Test, đếm số lần gọi mock |
| P2-8 | `mailFolder` per intent tồn tại, draft nằm đúng folder theo `intent_id` | Query Graph |
| P2-9 | Body email không chứa `TAI-INTERNAL-DO-NOT-SEND` sau khi PM xoá block ⇒ Job C không alert; còn chứa ⇒ alert | Test cả hai chiều |
| P2-10 | Feedback → draft ≤ 24h (O6) | `created_at` → `drafted_at` |

## 10. Cần chốt trước khi bắt đầu

1. **CC list.** Skill chốt CC 4 người nội bộ trên **mọi** email. Ở 20–100 feedback/ngày (A1) là 80–400 email/ngày vào 4 inbox đó, và một lần leak R4 là leak tới user **cộng** 4 đồng nghiệp. Với volume tự động, đề xuất bỏ CC hoặc chỉ CC shared mailbox. Đây là quyết định của PM, không phải của code.
2. **`.eml` hay Graph cho V1.** Quyết định sau spike ①. Đi `.eml` thì chấp nhận mất O5 hoàn toàn và phải làm sidecar INTERNAL (§5).
3. **`User.Read.All`** cho B-3, xin cùng lượt với `Mail.ReadWrite`.
4. **Subject hằng số.** Tốt cho user, nhưng PM sẽ thấy 30 draft subject giống nhau trong một folder. Nếu khó dùng, cách rẻ nhất là để folder + tên người nhận làm việc phân biệt, đừng đổi subject.
5. **A7 (1 feedback → 1 email).** Arch nhắc ở dòng cuối và tôi nhắc lại: nếu ý định thật là gộp nhiều feedback cùng user thành một email, thì idempotency key, template và cả B1 đều đổi. Chốt bây giờ, không phải ở tuần thứ sáu.
