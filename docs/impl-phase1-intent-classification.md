# Phase 1 — Intent Classification

| Field | Value |
|-------|-------|
| **Date** | 2026-08-25 |
| **Depends on** | `docs/architecture.md` v3.0 (§3 Phase 0, §4.1, §4.3, §6.1 R2/R3) |
| **Blocks** | Toàn bộ Phase 2 (`docs/impl-phase2-auto-feedback-flow.md`) |
| **Deliverable chính** | `intents.yaml` (Intent Catalog v1, đã ký duyệt) + module `classify` chạy được |

## 0. Phase này giải quyết cái gì

Arch nói rõ: *"Đừng viết `classify` trước bước này, bạn sẽ đoán sai schema"* (§6.3 bước 3). Nên Phase 1 gồm **hai nửa nối tiếp**, không song song:

| | Nửa | Chạy ở đâu | Ra cái gì |
|---|---|---|---|
| **P1.A** | Phân tích offline → chốt catalog | Notebook ad-hoc, không lịch | `intents.yaml` + báo cáo calibration |
| **P1.B** | Module `classify` runtime | Package trong repo, task B1 | Code + test, đọc catalog ở P1.A |

P1.B không được bắt đầu trước khi P1.A qua review gate. Ngược lại, P1.A **không** cần Graph API, không cần Delta production, không cần gì của Phase 2, nên chạy được ngay hôm nay.

**Ngoài scope phase này:** sinh draft, gửi email, RAG userguide, Jira. Toàn bộ ở Phase 2.

---

## 1. Project layout (dựng ở phase này, Phase 2 bồi thêm)

```
auto_feedback_resp/
├── pyproject.toml               # uv, python 3.12
├── intents.yaml                 # 📦 CATALOG — nguồn sự thật, review qua PR
├── notebooks/
│   ├── 00_data_audit.py         # P1.A step 0
│   ├── 01_embed.py              # step 2
│   ├── 02_cluster.py            # step 3
│   ├── 03_llm_merge.py          # step 4
│   ├── 04_review_table.py       # step 5 — export bảng cho PM
│   ├── 05_exemplar_select.py    # step 6
│   └── 06_calibrate.py          # step 7
├── src/afr/
│   ├── config.py                # pydantic-settings
│   ├── models.py                # pydantic: Feedback, Intent, Classification, Flag
│   ├── catalog.py               # load intents.yaml → Catalog (+ embed exemplar)
│   ├── llm/
│   │   ├── base.py              # Embedder / Chat Protocol
│   │   ├── serving.py           # Databricks Model Serving
│   │   └── fake.py              # deterministic, cho pytest
│   ├── store/
│   │   ├── base.py              # StateStore Protocol
│   │   ├── local.py             # parquet + sqlite (dev)
│   │   └── delta.py             # Delta / UC (prod)
│   └── jobs/
│       └── classify.py          # TASK B1
└── tests/
    ├── test_routing.py          # biên ngưỡng — không cần LLM
    └── test_catalog.py          # validate intents.yaml
```

`Embedder` và `StateStore` là Protocol có hai implement (thật / fake, local / Delta) vì §5 yêu cầu *"unit test cho routing/threshold, phần logic thuần, không cần LLM thật"* — không tách interface thì không test offline được.

---

## 2. P1.A — Phân tích offline

### Step 0 — Data audit (kiểm chứng A4)

Một câu SQL quyết định đường đi, làm trước mọi thứ khác:

```sql
SELECT
  agent,
  count(*)                                      AS n,
  count(DISTINCT user_email)                    AS users,
  sum(CASE WHEN length(trim(content)) < 10 THEN 1 ELSE 0 END) AS too_short,
  percentile(length(content), array(0.1, 0.5, 0.9))           AS len_pct,
  min(created_at), max(created_at)
FROM <feedback_datalake>
GROUP BY agent
ORDER BY n DESC
```

| Kết quả | Đường đi |
|---|---|
| `n` sạch ≥ 500 | **HDBSCAN path** (step 3) |
| `n` sạch < 500 | **Direct-LLM path**: chia lô 50, Sonnet đọc từng lô đề xuất intent, gộp liên lô. Bỏ step 2–3. |

Đo thêm, vì cả ba ảnh hưởng thiết kế: tỉ lệ VI/EN lẫn lộn (xác nhận cần model đa ngôn ngữ), tỉ lệ trùng lặp chính xác, phân bố theo `agent` (agent mới ra sau này = nguồn `unclassified` chính, R1).

### Step 1 — Preprocess

Bỏ `length(trim(content)) < 10`, dedup exact. **Không dịch, không lowercase, không bỏ dấu** — qwen3 đa ngôn ngữ, chuẩn hoá là làm nghèo tín hiệu. Giữ nguyên văn để step 6 chọn exemplar (exemplar phải là feedback thật, đọc được).

Với A5: nếu PII không được phép qua Model Serving thì mask **trước** khi embed, và cùng hàm mask đó phải chạy ở runtime B1 — lệch một chỗ là lệch không gian vector.

### Step 2 — Embed và cache

```python
# notebooks/01_embed.py
MODEL = "databricks-qwen3-embedding-0-6b"
# ghi lại đủ bộ ba, cả ba đi vào catalog để R2 kiểm được
meta = {"model_name": MODEL, "endpoint_version": ..., "dim": len(vecs[0])}
```

Ghi ra Delta `feedback_embedding(feedback_id, embedding, model_name, embedded_at)`. Notebook sẽ chạy lại nhiều lần trong lúc dò tham số cluster; không cache thì trả tiền embed lại mỗi vòng.

### Step 3 — Cluster, cố tình over-segment

```python
umap.UMAP(n_neighbors=15, n_components=10, metric="cosine")   # 10 chiều, không phải 2
hdbscan.HDBSCAN(min_cluster_size=8, min_samples=3, metric="euclidean")
```

`n_components=10`, không phải 2 — 2 chiều chỉ để vẽ hình cho người xem, cluster trên đó là mất thông tin.

**Vì sao over-segment:** step 4 để LLM *gộp* cụm. LLM gộp khá tin cậy, *tách* thì không. Nên thà 40 cụm sạch rồi gộp còn hơn 12 cụm lẫn rồi phải tách bằng tay.

Sweep `min_cluster_size ∈ {5,8,12,20}`, chọn theo hai tiêu chí: số cụm nằm trong 15–40, và noise (`label = -1`) < 35%.

> **Noise rate ở đây là con số quý nhất của cả step này.** Điểm không vào cụm nào chính là dân số `unclassified` tự nhiên của dữ liệu. Nó là **ước lượng ngày-0 cho `unclassified_rate`** ở production. Nếu offline đã 40% noise thì ngưỡng hành động 20% ở R1 là không thực tế, phải chốt lại ngưỡng với PM trước khi chạy, không phải sau tuần thứ hai.

### Step 4 — LLM merge + đặt tên (Sonnet 4.6)

Hai prompt, cả hai ép structured output bằng pydantic:

**4a, mỗi cụm:** đưa 8 mẫu gần medoid nhất + size cụm → trả về `label`, `description`, `action_type`, `confidence_in_naming`.

**4b, toàn cục:** đưa toàn bộ label ứng viên + 3 mẫu mỗi cụm → trả về các nhóm nên gộp, kèm lý do.

Luật cứng: **LLM không được sinh intent không có cụm đỡ.** Mọi intent đều truy được về ≥1 cụm và ≥N feedback thật. Không có luật này thì catalog sẽ có intent nghe hay mà không bao giờ khớp gì.

`action_type` đề xuất 3 giá trị (chốt với PM ở step 5) — nó là trục quyết định template ở Phase 2:

| `action_type` | Nghĩa | Template Phase 2 |
|---|---|---|
| `answer_from_kb` | Trả lời được từ userguide | `we_resolved` |
| `known_gap` | Đã có/nên có ticket, chưa xong | `we_listen` |
| `ack_only` | Ghi nhận, không cam kết gì | `we_listen` (biến thể trung tính) |

### Step 5 — Review gate (PM + AI team)

Export một bảng, mỗi dòng một intent ứng viên: `size`, `% tổng`, 8 feedback mẫu nguyên văn, label/description/action_type do LLM đề xuất, và **cột trống để PM sửa**.

PM quyết: wording, gộp/tách, `action_type`, tên folder Outlook. Ghi lại `approved_by` + `approved_at` vào catalog. Đây là cửa chặn thật, không phải bước duyệt hình thức.

### Step 6 — Chọn exemplar (R3)

Mỗi intent 3–5 feedback **thật**, không phải centroid. Chọn tự động rồi người phủ quyết:

1. Lấy medoid của cụm làm exemplar #1.
2. Farthest-point sampling: mỗi lần thêm điểm xa nhất so với tập đã chọn, tới khi đủ 5.
3. Người đọc, gạch bỏ cái nào tối nghĩa / lẫn intent khác, không thay bằng cái khác.

Bước 2 quan trọng: chọn 5 mẫu gần nhau thì confidence chỉ cao với một kiểu diễn đạt duy nhất. Cần phủ được độ trải của cụm.

### Step 7 — Calibrate ngưỡng

**Đây là chỗ dễ bị cắt nhất và không được cắt.** Không có holdout thì `confidence` chỉ là một số float không ai biết nghĩa gì, và cả O2 rỗng.

- Gán nhãn tay **150–200 feedback**, lấy mẫu phân tầng qua các cụm **và cả vùng noise** (thiếu noise thì không đo được nhánh `unclassified`).
- Mỗi mẫu: tính `c = max cosine` tới exemplar, lấy intent thắng.
- Vẽ hai phân bố `c`: nhóm đoán đúng và nhóm đoán sai.

| Ngưỡng | Chọn theo | Vì sao |
|---|---|---|
| `threshold_high` | precision ≥ 0.90 trong vùng `c ≥ high` | Vùng này ra draft đầy đủ, gửi cho user thật, sai là tốn uy tín |
| `threshold_low` | ≤ 5% mẫu đúng-được bị rơi xuống `unclassified` | Vùng này là dead-end (§4.3), rơi oan là mất luôn |

> **Giới hạn phải nói thẳng:** ngưỡng *per-intent* như schema `intent_catalog` cho phép cần ~30 mẫu holdout mỗi intent. 15 intent × 30 = 450 nhãn tay, gấp đôi ngân sách thực tế. **Đề xuất: V1 dùng một cặp ngưỡng global**, chỉ override per-intent cho intent nào có ≥30 mẫu holdout. Schema không đổi, chỉ là đa số row mang cùng giá trị. Ghi rõ trong catalog intent nào đã calibrate riêng, intent nào đang ăn ngưỡng global.

Nếu hai phân bố chồng nhiều: **quay lại step 6 đổi exemplar, đừng vặn ngưỡng.** Chồng nhau nghĩa là exemplar không phân biệt được intent, vặn ngưỡng chỉ chọn kiểu sai mình muốn.

### Step 8 — Freeze

`intents.yaml` commit vào git, tag `catalog-v1`. CI load vào Delta `intent_catalog`. Sau đó Delta là read-only với mọi job.

**Khác một chỗ so với §4.5, và đây là đề xuất đổi thiết kế:** catalog chứa **exemplar dạng text**, không phải `exemplar_vectors`.

```yaml
embedding:
  model_name: databricks-qwen3-embedding-0-6b   # bắt buộc khớp lúc runtime
  dim: 1024

defaults:                    # ngưỡng global, xem giới hạn ở step 7
  threshold_high: 0.72
  threshold_low: 0.55

catalog_version: v1
approved_by: <PM>
approved_at: 2026-XX-XX

intents:
  - intent_id: how_to_usage
    label: "Hướng dẫn sử dụng"
    description: "User không biết cách dùng một tính năng đã có"
    action_type: answer_from_kb
    folder: how_to_usage
    # threshold_high/low: bỏ trống = ăn defaults; điền = đã calibrate riêng
    exemplars:
      - feedback_id: fb_00412        # truy vết về feedback thật
        text: "Không biết cách xuất file PPT ra PDF"
      - feedback_id: fb_01087
        text: "Làm sao để đổi ngôn ngữ output của The Translator?"
```

| | Text trong git, embed lúc load | Vector trong git (§4.5 nguyên bản) |
|---|---|---|
| Review qua PR | Đọc được, PM duyệt được | Diff là hàng nghìn float, không ai duyệt |
| R2 (vector chết cứng theo model) | **Biến mất** — vector luôn sinh bởi model đang chạy | Còn nguyên, cần check fail-loud |
| Chi phí | ~50–75 embed call lúc job khởi động | 0 |
| Kích thước repo | KB | MB |

Đổi lấy vài chục embed call mỗi lần job chạy để triệt tiêu một class lỗi *"không có lỗi nào được ném ra"* (R2) là đáng. Check `model_name` vẫn giữ, nhưng giờ nó chỉ còn là lưới an toàn thứ hai chứ không phải phòng tuyến duy nhất.

---

## 3. P1.B — Module `classify` (task B1)

```python
# src/afr/models.py
class Flag(StrEnum):
    OK = "ok"
    LOW_CONFIDENCE = "low_confidence"
    UNCLASSIFIED = "unclassified"

class Classification(BaseModel, frozen=True):
    feedback_id: str
    catalog_version: str
    flag: Flag
    intent_id: str | None      # None khi UNCLASSIFIED — KHÔNG đoán nhãn (§4.3)
    confidence: float
    best_intent_id: str        # luôn có, kể cả UNCLASSIFIED → vào pool
```

```python
# src/afr/catalog.py
def load_catalog(path: Path, embedder: Embedder) -> Catalog:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    # R2 — fail loud, một dòng if chặn một class lỗi rất khó debug
    if embedder.model_name != raw["embedding"]["model_name"]:
        raise CatalogModelMismatch(
            f"catalog dùng {raw['embedding']['model_name']}, "
            f"runtime đang gọi {embedder.model_name}"
        )

    for intent in raw["intents"]:                      # embed một lần / job run
        intent["vectors"] = embedder.embed([e["text"] for e in intent["exemplars"]])
    return Catalog.model_validate(raw)
```

```python
# src/afr/jobs/classify.py
def classify_one(vec: Vector, catalog: Catalog) -> Classification:
    best, c = max(
        ((i, max(cosine(vec, e) for e in i.vectors)) for i in catalog.intents),
        key=lambda t: t[1],
    )
    hi, lo = catalog.thresholds_for(best.intent_id)     # per-intent, fallback defaults

    if   c >= hi: flag = Flag.OK
    elif c >= lo: flag = Flag.LOW_CONFIDENCE
    else:         flag = Flag.UNCLASSIFIED

    return Classification(
        intent_id=None if flag is Flag.UNCLASSIFIED else best.intent_id,
        best_intent_id=best.intent_id,
        confidence=c, flag=flag, ...
    )
```

**Ghi state, một transaction:**

```python
store.insert_classification(rows)                      # feedback_processing
store.append_unclassified_pool(                        # O7 = 100%
    [to_pool_row(r, vec) for r, vec in zip(rows, vecs) if r.flag is Flag.UNCLASSIFIED]
)
```

Hai điểm chốt lại chỗ arch để hở:

- **B1 ghi `unclassified_pool`, không phải B2.** Vì embedding đang nằm trong tay B1, và như vậy O7 không phụ thuộc việc B2 có chạy xong hay không.
- **Cùng một transaction với `insert_classification`.** Tách ra thì một lần job chết giữa hai lệnh là mất vĩnh viễn một feedback khỏi pool mà không ai biết, mà pool là append-only nên không có cách nào phát hiện về sau.

Chọn feedback chưa xử lý bằng anti-join trên `feedback_processing.feedback_id` (§4.2) — `feedback_id` là idempotency key, chạy lại job hai lần không sinh row trùng.

---

## 4. Acceptance criteria

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| P1-1 | `intents.yaml` có trong git, tag `catalog-v1`, có `approved_by`/`approved_at` | `git show catalog-v1:intents.yaml` |
| P1-2 | Mọi intent có 3–5 exemplar, mỗi exemplar truy được về `feedback_id` thật | `test_catalog.py` |
| P1-3 | Báo cáo calibration: 2 phân bố confidence, precision vùng `high` ≥ 0.90 | Notebook 06 output |
| P1-4 | Báo cáo phân bố 3 vùng trên holdout + noise rate offline (prior cho `unclassified_rate`) | Notebook 06 output |
| P1-5 | Đổi `model_name` trong catalog ⇒ job fail ngay, không chạy tiếp | Test R2 |
| P1-6 | Test biên: `c` đúng bằng `high` → `ok`; đúng bằng `low` → `low_confidence` | `test_routing.py` |
| P1-7 | `flag=unclassified` ⇒ `intent_id IS NULL` **và** có row trong pool. Không ngoại lệ. | Test invariant + query O7 |
| P1-8 | Chạy `classify` 2 lần trên cùng input ⇒ số row không đổi | Test idempotency |

## 5. Cần chốt trước khi bắt đầu

1. **Ngưỡng hành động của `unclassified_rate`.** R1 đề xuất 20%/2 tuần. Nhưng noise rate ở step 3 mới cho biết 20% có thực tế không. Chốt lại với PM **sau step 3, trước khi lên production** — không phải để tới lúc dashboard đã đỏ.
2. **`action_type` 3 giá trị** ở step 4 đủ chưa. Nó quyết định template Phase 2, đổi sau là đổi cả hai phase.
3. **A5 (PII qua Model Serving).** Câu trả lời quyết định có cần hàm mask hay không, và hàm đó phải dùng chung giữa notebook và B1.
4. **Ai gán 150–200 nhãn holdout, khi nào.** Đây là hạng mục công-người lớn nhất của phase và là thứ duy nhất làm `confidence` có nghĩa.
