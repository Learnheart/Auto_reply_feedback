---
author: klinh2212112@gmail.com
date: 2026-08-25
status: draft
agents: intent-catalog, inference.classify
summary: Method document (thuần DS) cho Offline Intent Analysis — quy trình phân tích ngoài hệ thống để khám phá, kiểm định và chốt Intent Catalog v1.
---

# Offline Intent Analysis — Method Document

| Field | Value |
|-------|-------|
| **Loại tài liệu** | Method / DS methodology (không phải impl doc phần mềm) |
| **Depends on** | `docs/architecture.md` v3.0 §2 (Input, A4/A5/A6), §3 Phase 0, §4.1, §4.3, §6.1 (R1/R2/R3) |
| **Blocks** | Runtime module `inference.classify` (B1) và toàn bộ Phase 2 — cả hai đọc artifact do tài liệu này sinh ra |
| **Deliverable duy nhất** | `intents.yaml` (Intent Catalog v1, đã ký duyệt) **+ báo cáo kiểm định** (validation report) đi kèm |
| **Supersedes** | `docs/impl-phase1-intent-classification.md` (đã xoá — trộn lẫn phần phân tích DS với phần code module runtime) |

> **Ranh giới đọc trước:** tài liệu này mô tả *một tiến trình phân tích data science chạy một lần, ngoài Databricks Jobs* (§3 Phase 0). Nó **không** đặc tả module code `classify` chạy trong production — module đó là sản phẩm phần mềm, đọc catalog này như input tĩnh, và được đặc tả riêng ở tài liệu production. Ở đây không có `src/afr/...`, không có acceptance của phần mềm; chỉ có phương pháp, thí nghiệm, và tiêu chí chấp nhận của **artifact catalog**.

## Architecture reference

- **Module:** `Offline intent analysis` (§3 Trách nhiệm từng module — "Sinh và chốt bộ intent từ feedback lịch sử, chạy một lần") → sinh artifact **Intent Catalog**.
- **Sections:** `docs/architecture.md` §2 Overview → System boundary + Input + Assumptions (A4, A5, A6), §3 High-Level Architecture → Phase 0, §4.1 Bàn giao Intent Catalog, §4.3 Threshold routing, §6.1 R1/R2/R3.
- **Impl doc kế tiếp:** `docs/impl-phase2-auto-feedback-flow.md` (tiêu thụ catalog ở runtime).
- **Data contract:** bảng `intent_catalog` (§4.5) — nhưng tài liệu này **đề xuất đổi** `exemplar_vectors ARRAY<ARRAY<FLOAT>>` → exemplar dạng **text** trong git (xem §10, lý do R2). Đây là lệch kiến trúc *có chủ đích*; đã ghi vào `architecture.md`/`CHANGELOG.md` trước khi áp dụng.
- **Nguồn dữ liệu:** *Feedback datalake* (§2 Input: `feedback_id`, `user_email`, `agent`, `content`, `created_at`). Khi chưa có quyền: fixture `data/sample/feedback_sample.csv` (xem `docs/2026-08-25/sample-feedback-fixture/plan.md`).

---

## 0. Vấn đề, và tại sao đây là một tiến trình DS chứ không phải một task code

Hệ thống production đóng băng taxonomy (§3, A6). Nghĩa là **chất lượng của toàn bộ sản phẩm bị chặn trên bởi chất lượng của một artifact được sinh một lần** — Intent Catalog. Nếu catalog sai (thiếu intent, intent chồng lấn, ngưỡng vô nghĩa), production vẫn chạy trơn tru và vẫn sinh draft — chỉ là sinh draft sai một cách tự tin. Không có vòng lặp học nào sửa lại.

Do đó bài toán này **không phải** "cluster xong rồi đặt tên". Nó là: *sản xuất một taxonomy kèm bằng chứng định lượng rằng nó đúng, đủ, ổn định, và ngưỡng của nó có ý nghĩa thống kê* — trước khi ký đóng băng. Đầu ra bắt buộc gồm hai thứ, thiếu một là chưa xong:

1. `intents.yaml` — artifact.
2. **Validation report** — tập số liệu chứng minh artifact đáng tin (§1 định nghĩa "đáng tin" là gì).

Đây là điểm khác biệt cốt lõi so với tài liệu cũ (`impl-phase1`): tài liệu cũ coi đây là "viết module classify"; thực chất phần khám phá + kiểm định taxonomy mới là công việc, và nó thuần DS.

### Non-goal của tài liệu này

- Module runtime `classify` (B1), Delta production, Graph, RAG, Jira — thuộc production, đặc tả nơi khác.
- Re-run / versioning / taxonomy mapping — non-goal của scope (§1 architecture).

---

## 1. "Catalog đáng tin" nghĩa là gì — tiêu chí đo được

Định nghĩa trước, phân tích sau. Một catalog v1 chỉ được đem ký khi **tất cả** các trục dưới đây có số liệu, không phải chỉ "PM đọc thấy hợp lý".

| Trục | Câu hỏi DS | Chỉ số | Cửa chặn đề xuất |
|---|---|---|---|
| **Coverage** | Taxonomy phủ được bao nhiêu % khối lượng feedback? | Tỉ lệ feedback có `max cosine ≥ threshold_low` trên holdout | Báo cáo bắt buộc; PM chốt mức chấp nhận |
| **Head/tail** | Bao nhiêu intent gánh phần lớn khối lượng? | Đường cong tích luỹ % theo intent; chỉ số Gini | Báo cáo bắt buộc |
| **Stability** | Cụm có thật không hay là artifact của một cấu hình? | ARI/NMI giữa các seed & các `min_cluster_size`; `cluster_persistence` HDBSCAN | Mỗi intent v1 truy về ≥1 cụm có persistence trên ngưỡng và ổn định qua ≥2 cấu hình |
| **Separability** | Các intent có phân biệt được ở không gian vector không? | Chồng lấn của 2 phân bố confidence (đúng vs sai) trên holdout; silhouette liên cụm | Precision vùng `high` ≥ 0.90 (§9) |
| **Reject quality** | Nhánh `unclassified` có bắt đúng cái lạ không? | Precision **và** recall của nhánh reject trên holdout | ≤5% mẫu đúng rơi nhầm xuống unclassified (§9) |
| **Label quality** | Nhãn con người có nhất quán không? | Cohen's κ giữa 2 annotator trên tập chồng | κ ≥ 0.6 mới tin holdout để đặt ngưỡng |
| **Grounding** | Mọi intent có gốc dữ liệu thật không? | Mỗi intent ≥ N feedback thật đỡ; mỗi exemplar truy về `feedback_id` | Bắt buộc, không ngoại lệ |

> Bảy trục này là "acceptance của artifact" — xem lại đầy đủ ở §11. Chúng lái toàn bộ các bước 2–10.

---

## 2. Nền dữ liệu — audit & tiền xử lý

### 2.1 Data audit (kiểm chứng A4, quyết định đường đi)

Một truy vấn quyết định nhánh, làm trước mọi thứ:

```sql
SELECT agent,
       count(*)                                                   AS n,
       count(DISTINCT user_email)                                 AS users,
       sum(CASE WHEN length(trim(content)) < 10 THEN 1 ELSE 0 END) AS too_short,
       percentile(length(content), array(0.1,0.5,0.9))            AS len_pct,
       min(created_at), max(created_at)
FROM <feedback_datalake>              -- dev: data/sample/feedback_sample.csv (650 dòng)
GROUP BY agent ORDER BY n DESC
```

| Kết quả (n sạch) | Đường đi |
|---|---|
| ≥ 500 | **HDBSCAN path** (§4) — khám phá cấu trúc bằng clustering |
| < 500 | **Direct-LLM path** — chia lô ~50, LLM đề xuất intent theo lô, gộp liên lô; bỏ §4. §6–§11 giữ nguyên |

Đo thêm ba đại lượng vì cả ba lái thiết kế: **tỉ lệ VI/EN lẫn lộn** (xác nhận cần embedding đa ngôn ngữ), **tỉ lệ trùng exact** (báo cáo, nhưng KHÔNG dùng để bỏ — xem §2.2), **phân bố theo `agent`** (agent ra sau = nguồn `unclassified` chính, R1 — cần biết trước để đọc kỹ vùng noise ở §4.4).

### 2.2 Tiền xử lý

- **Nguyên tắc: giữ hết feedback của user.** Chỉ loại feedback **không có nội dung có nghĩa** — rỗng, chỉ khoảng trắng, chỉ số, chỉ ký hiệu/emoji (không chứa một chữ cái nào). Tiêu chí: `any(ch.isalpha())` trên content (Unicode, gồm tiếng Việt & mọi ngôn ngữ).
- **KHÔNG lọc theo độ dài.** Feedback ngắn vẫn là intent thật (`"lag quá"`, `"lỗi 500"`, `"crash rồi"`) — nhất là từ agent mới/ít dữ liệu (R1). Ngưỡng độ dài cứng cắt nhầm chính những intent hiếm.
- **KHÔNG dedup exact.** Trùng lặp là feedback thật của user (mỗi feedback là một sự kiện), giữ lại để không mất tín hiệu nhu cầu. Chỉ **báo cáo** tỉ lệ trùng ở §2.1.
- **Không dịch, không lowercase, không bỏ dấu** — qwen3 đa ngôn ngữ, chuẩn hoá làm nghèo tín hiệu và làm exemplar (§8) khó đọc.
- **PII (A5):** nếu PII không được phép qua Model Serving → mask **trước** khi embed. Hàm mask này về sau phải dùng chung y hệt ở runtime B1; lệch một ký tự là lệch không gian vector. Ghi rõ hàm mask vào validation report để runtime tái sử dụng.

---

## 3. Biểu diễn — embedding và **kiểm định lựa chọn embedding**

Model: `databricks-qwen3-embedding-0-6b` (§5 architecture — đa ngôn ngữ, và **bắt buộc** trùng model dùng ở runtime).

Ghi cache ra `feedback_embedding(feedback_id, embedding, model_name, endpoint_version, dim, embedded_at)` — notebook chạy lại nhiều vòng dò tham số, không cache thì trả tiền embed lại mỗi vòng.

> **Bổ sung DS (không có trong tài liệu cũ):** cả pipeline đứng trên chất lượng không gian vector này, nhưng model 0.6B là model nhỏ. **Kiểm định embedding trước khi tin nó:**
>
> - **Intrinsic eval trên fixture:** fixture có nhãn nhóm ẩn `latent_theme` (sidecar). Cluster trên embedding rồi đo **ARI/NMI giữa cụm và `latent_theme`**. Nếu pipeline không phục hồi nổi cấu trúc *đã biết* của dữ liệu giả lập, nó sẽ không phục hồi nổi cấu trúc *chưa biết* của dữ liệu thật. Đây là smoke test bắt buộc trong lúc dev.
>   *(Lưu ý phụ thuộc: sidecar `feedback_sample_labels.jsonl` mà changelog mô tả hiện chưa có trên đĩa — cần regenerate từ `scripts/gen_sample_feedback.py` trước khi chạy eval này.)*
> - Nếu ngân sách cho phép: so nhanh qwen3-0.6B với một embedding lớn hơn trên **cùng holdout §9**, chọn theo separability, không theo cảm giác.

---

## 4. Khám phá cấu trúc — over-segment rồi để người/LLM gộp

### 4.1 Giảm chiều

```python
umap.UMAP(n_neighbors=15, n_components=10, metric="cosine", random_state=SEED)
```

`n_components=10`, không phải 2 — 2 chiều chỉ để vẽ cho người xem; cluster trên 2D là vứt thông tin. **`random_state` cố định** vì UMAP là stochastic và §4.3 cần đo lại được.

### 4.2 Clustering (cố tình over-segment)

```python
hdbscan.HDBSCAN(min_cluster_size=8, min_samples=3, metric="euclidean")
```

Metric `euclidean` trên output UMAP là đúng (UMAP đã dùng cosine để dựng manifold). **Vì sao over-segment:** LLM *gộp* cụm khá tin, *tách* thì không (§5). Thà 40 cụm sạch rồi gộp còn hơn 12 cụm lẫn rồi tách tay.

Sweep `min_cluster_size ∈ {5,8,12,20}`; chọn cấu hình cho số cụm 15–40 và noise (`label=-1`) < 35%.

### 4.3 Kiểm định độ ổn định của cụm — **bổ sung DS quan trọng**

Tiêu chí "số cụm 15–40, noise <35%" là tiêu chí *hình thức*, không phải *độ tin cậy*. Một cụm chỉ xuất hiện ở đúng một cấu hình là **artifact**, không phải intent. Bắt buộc đo:

- **`cluster_persistence`** (HDBSCAN cấp sẵn) cho mỗi cụm — độ "đậm" của cụm. Cụm persistence thấp là ứng viên yếu.
- **ARI/NMI giữa các lần phân cụm** khi đổi `SEED` (UMAP) và đổi `min_cluster_size`. Cặp cấu hình lân cận mà ARI thấp ⇒ cấu trúc không ổn định, đừng chốt taxonomy trên đó.
- Kết quả vào validation report: bảng `cluster_id → size, persistence, có ổn định qua ≥2 cấu hình không`. Đây là input cho cửa chặn **Stability** ở §1.

### 4.4 Đọc vùng noise, đừng chỉ đếm — **chặn mù rare-intent**

`min_cluster_size=8` nghĩa là **mọi chủ đề thật < 8 mẫu trong lịch sử tan vào noise và không bao giờ thành intent.** Với agent ra sau (ít dữ liệu, F7/R1), đây chính là nơi intent quan trọng-nhưng-hiếm biến mất *tại thời điểm khám phá* — tách bạch hoàn toàn với drift tương lai của R1.

⇒ Lấy mẫu **đọc tay vùng `label=-1`** (không chỉ đếm %). Nếu thấy chủ đề mạch lạc lặp lại nhưng nhỏ, cân nhắc: hạ `min_cluster_size`, hoặc tạo intent thủ công có gốc dữ liệu, hoặc ghi nhận là "known blind spot" trong report để PM quyết.

### 4.5 Đính chính một điểm khái niệm: **noise rate ≠ prior của `unclassified_rate`**

Tài liệu cũ nói noise rate của HDBSCAN là "ước lượng ngày-0 cho `unclassified_rate`". **Sai về cơ chế:**

- Noise ở clustering = điểm **density thấp** (không đủ hàng xóm gần trong không gian UMAP).
- `unclassified` ở production = **max cosine tới 3–5 exemplar < `threshold_low`**.

Hai classifier khác nhau — một điểm có thể là noise HDBSCAN nhưng vẫn cosine cao tới một exemplar, và ngược lại. Vậy **prior đúng cho R1 phải lấy từ phân bố 3 vùng trên holdout ở §9** (đúng cơ chế runtime), không phải từ noise rate §4. Noise rate chỉ là *một tín hiệu lỏng* về mức độ "khó" của dữ liệu. Ghi rõ điều này để PM không chốt ngưỡng hành động R1 trên con số sai.

---

## 5. Đặt tên & gộp cụm (LLM — Sonnet 4.6)

Hai prompt, cả hai ép structured output bằng pydantic:

- **5a — mỗi cụm:** 8 mẫu gần medoid + size → `label`, `description`, `action_type`, `confidence_in_naming`.
- **5b — toàn cục:** toàn bộ label ứng viên + 3 mẫu/cụm → các nhóm nên gộp + lý do. (LLM gộp, không tách — xem §4.2.)

**Luật cứng:** LLM **không** được sinh intent không có cụm đỡ. Mọi intent truy được về ≥1 cụm và ≥N feedback thật (trục **Grounding**, §1). Thiếu luật này catalog sẽ có intent nghe hay mà không bao giờ khớp gì.

`action_type` — trục quyết định template ở Phase 2, đề xuất 3 giá trị (chốt với PM ở §7):

| `action_type` | Nghĩa | Template Phase 2 |
|---|---|---|
| `answer_from_kb` | Trả lời được từ userguide | `we_resolved` |
| `known_gap` | Đã/nên có ticket, chưa xong | `we_listen` |
| `ack_only` | Ghi nhận, không cam kết | `we_listen` (biến thể trung tính) |

---

## 6. Kiểm định taxonomy — **trục lớn nhất, gần như vắng mặt ở tài liệu cũ**

Trước khi đưa PM review, taxonomy ứng viên phải kèm số liệu ở ba câu hỏi:

1. **Coverage & head/tail.** Trên toàn bộ dữ liệu (hoặc holdout): đường cong % tích luỹ theo intent, chỉ số Gini. Nếu 80% khối lượng nằm ở 2–3 intent thì phần còn lại phần lớn là trang trí — ảnh hưởng trực tiếp ROI và cách PM ưu tiên template.
2. **Stability.** Đưa bảng persistence + ARI/NMI từ §4.3 lên. Đánh dấu intent nào "vững", intent nào "mong manh".
3. **MECE (chồng lấn & khoảng trống).** Đo separability liên cụm (silhouette hoặc khoảng cách medoid-medoid). Hai cụm quá gần ⇒ ứng viên gộp; nhắc chéo với đề xuất 5b của LLM. Vùng noise lớn + đọc tay (§4.4) ⇒ khoảng trống taxonomy.

Đầu ra của §6 là "taxonomy ứng viên **đã gắn số**", không phải danh sách tên trơn.

---

## 7. Review gate (PM + AI team) — cửa chặn của con người

Export một bảng, mỗi dòng một intent ứng viên: `size`, `% tổng`, **persistence & stability flag (§4.3)**, 8 feedback mẫu nguyên văn, `label/description/action_type` do LLM đề xuất, và **cột trống để PM sửa**.

PM quyết: wording, gộp/tách, `action_type`, tên folder Outlook. Ghi `approved_by` + `approved_at`. Đây là cửa chặn thật. So với tài liệu cũ, bảng review giờ có thêm cột stability để PM không chốt nhầm một cụm mong manh thành intent chính thức.

---

## 8. Chọn exemplar **và chọn công thức scoring** (R3)

### 8.1 Chọn exemplar (3–5 feedback thật/intent, không phải centroid)

HDBSCAN density-based ⇒ cụm lõm/kéo dài ⇒ centroid rơi ngoài cụm ⇒ cosine tới centroid vô nghĩa. Vì taxonomy là artifact do người chốt, ta chọn tay:

1. Medoid của cụm = exemplar #1.
2. **Farthest-point sampling** tới khi đủ 5 — phủ độ trải của cụm, tránh 5 mẫu cùng một kiểu diễn đạt.
3. Người đọc, gạch bỏ mẫu tối nghĩa / lẫn intent khác (không thay bằng mẫu khác).

### 8.2 So công thức scoring — **bổ sung DS**

`confidence = max_e cosine(x, e)` với 3–5 exemplar là classifier **high-variance**: một exemplar "lạ" chi phối toàn bộ quyết định của intent, và farthest-point sampling (cố ý lấy điểm rìa) *làm nặng thêm* rủi ro chồng lấn với intent khác. Trước khi chốt, **so ba công thức trên cùng holdout §9** và chọn cái tách hai phân bố tốt nhất:

| Công thức | Ý tưởng | Đánh đổi |
|---|---|---|
| `max cosine` | 1-NN với k nhỏ | Dễ giải thích ("gần ví dụ này nhất"); high-variance |
| `top-2 mean` | trung bình 2 cosine cao nhất | Giảm variance, robust với 1 exemplar nhiễu |
| `prototype` | cosine tới **mean của các exemplar vector** | Ổn định nhất; vẫn né lập luận "centroid cụm lõm" vì mean của 3–5 điểm đã chọn tay nằm trong cụm |

Vẫn giữ danh sách exemplar text để giải thích cho PM dù chọn công thức nào. Ghi công thức đã chọn vào catalog (để runtime dùng đúng công thức).

---

## 9. Calibrate ngưỡng — **chỗ dễ bị cắt nhất, không được cắt**

Không có holdout thì `confidence` chỉ là một float không ai biết nghĩa, và O2 rỗng.

### 9.1 Bộ holdout

- Gán nhãn tay **150–200 feedback**, lấy mẫu **phân tầng qua các cụm và cả vùng noise** (thiếu noise thì không đo được nhánh `unclassified`).
- **IAA (bổ sung):** cho **2 annotator** cùng gán một tập chồng ~30 mẫu; tính **Cohen's κ**. κ < 0.6 ⇒ nhãn holdout quá nhiễu để đặt ngưỡng 0.90; sửa hướng dẫn gán nhãn trước, đừng calibrate trên nhiễu.

### 9.2 Đặt ngưỡng

Mỗi mẫu: tính `c` theo công thức đã chọn (§8.2), lấy intent thắng. Vẽ **hai phân bố `c`**: nhóm đoán đúng vs đoán sai.

| Ngưỡng | Chọn theo | Vì sao |
|---|---|---|
| `threshold_high` | precision ≥ 0.90 trong vùng `c ≥ high` | Vùng này ra draft đầy đủ gửi user thật; sai là tốn uy tín |
| `threshold_low` | ≤ 5% mẫu **đúng** bị rơi xuống `unclassified` | Vùng dead-end (§4.3); rơi oan là mất luôn |

### 9.3 Báo cáo cả hai phía, kèm CI — **bổ sung DS**

- **CI, không chỉ điểm.** "precision 0.90" trên ~10 mẫu/intent có khoảng tin cậy khổng lồ. Báo cáo **Wilson 95% CI**, không báo cáo điểm trần trụi.
- **Recall của nhánh reject, không chỉ precision vùng high.** `threshold_low` phải cân hai phía: rơi oan mẫu đúng (precision-ish) *và* bắt được mẫu thật-sự-lạ (recall của unclassified). Tối ưu một phía sẽ chọn `threshold_low` thiên lệch.
- **Prior cho R1** = phân bố 3 vùng đo ở đây (đúng cơ chế runtime, §4.5), đây là con số PM dùng để chốt ngưỡng hành động `unclassified_rate`.

### 9.4 Global vs per-intent

Ngưỡng *per-intent* như schema cho phép cần ~30 mẫu holdout/intent ⇒ 15 intent × 30 = 450 nhãn tay (gấp đôi ngân sách). **Đề xuất V1: một cặp ngưỡng global**, override per-intent chỉ cho intent có ≥30 mẫu holdout. Schema không đổi (đa số row cùng giá trị); ghi rõ intent nào calibrate riêng, intent nào ăn global.

> Nếu hai phân bố chồng nhiều: **quay lại §8 đổi exemplar/công thức, đừng vặn ngưỡng.** Chồng nhau = exemplar không phân biệt được intent; vặn ngưỡng chỉ chọn kiểu sai mình muốn.

---

## 10. Freeze — schema catalog

`intents.yaml` commit vào git, tag `catalog-v1`; CI load vào Delta `intent_catalog`; sau đó Delta read-only với mọi job (§4.1).

**Đổi thiết kế so với §4.5 (đã đồng bộ vào architecture.md):** catalog chứa exemplar dạng **text**, không phải `exemplar_vectors`. Lý do — triệt R2 tại gốc: vector luôn được sinh bởi model đang chạy lúc load, không thể "chết cứng ở không gian vector cũ mà không ném lỗi". Đổi lấy ~50–75 embed call lúc job khởi động; check `model_name` vẫn giữ làm lưới an toàn thứ hai.

```yaml
embedding:
  model_name: databricks-qwen3-embedding-0-6b   # bắt buộc khớp runtime (R2)
  dim: 1024
scoring: prototype            # công thức chốt ở §8.2: max | top2_mean | prototype
defaults:                     # ngưỡng global, xem §9.4
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
    stability: { persistence: 0.71, stable_across_configs: true }   # từ §4.3
    # threshold_high/low: trống = ăn defaults; điền = đã calibrate riêng
    exemplars:
      - { feedback_id: fb_00412, text: "Không biết cách xuất file PPT ra PDF" }
      - { feedback_id: fb_01087, text: "Làm sao đổi ngôn ngữ output của The Translator?" }
```

---

## 11. Deliverables & acceptance của artifact

| # | Tiêu chí | Cách kiểm |
|---|---|---|
| A-1 | `intents.yaml` trong git, tag `catalog-v1`, có `approved_by`/`approved_at` | `git show catalog-v1:intents.yaml` |
| A-2 | Mọi intent 3–5 exemplar, mỗi exemplar truy về `feedback_id` thật (**Grounding**) | duyệt YAML + join datalake |
| A-3 | **Validation report** có: coverage %, đường cong head/tail + Gini | notebook §6 |
| A-4 | Report có bảng **stability**: persistence + ARI/NMI qua ≥2 cấu hình; mỗi intent v1 đạt ngưỡng ổn định | notebook §4.3 |
| A-5 | Report có **so 3 công thức scoring** trên holdout, nêu công thức đã chọn + lý do | notebook §8.2 |
| A-6 | Report có 2 phân bố confidence, **precision vùng high ≥ 0.90 kèm Wilson CI** | notebook §9 |
| A-7 | Report có **recall nhánh reject** + phân bố 3 vùng (= prior `unclassified_rate` cho R1) | notebook §9.3 |
| A-8 | Report có **Cohen's κ ≥ 0.6** trên tập chồng 2 annotator | notebook §9.1 |
| A-9 | Report ghi **known blind spots**: chủ đề nhỏ trong vùng noise bị bỏ (§4.4) | notebook §4.4 |
| A-10 | Catalog ghi `embedding.model_name`, `dim`, `scoring` — đủ để runtime kiểm R2 | duyệt YAML |

> A-3…A-9 là phần tài liệu cũ thiếu. Không có chúng, catalog vẫn "chạy được" nhưng không có bằng chứng nó *đúng* — đúng cái rủi ro §0 cảnh báo.

---

## 12. Cần chốt trước khi bắt đầu

1. **Ngưỡng hành động `unclassified_rate` (R1).** Chốt với PM **sau §9** (prior thật), không phải để tới lúc dashboard đỏ. R1 đề xuất 20%/2 tuần — chỉ giữ nếu prior §9 cho thấy thực tế.
2. **`action_type` 3 giá trị (§5)** đủ chưa — nó quyết định template Phase 2; đổi sau là đổi cả hai phase.
3. **A5 (PII qua Model Serving)** — quyết định có cần hàm mask, và hàm đó phải dùng chung notebook ↔ runtime B1.
4. **Ai gán 150–200 nhãn holdout + ai là annotator thứ 2 cho IAA, khi nào** — hạng mục công-người lớn nhất và là thứ duy nhất làm `confidence` có nghĩa.
5. **Regenerate fixture sidecar** `feedback_sample_labels.jsonl` (hiện thiếu trên đĩa) trước khi chạy intrinsic eval §3.

---

## Phụ lục — định nghĩa chỉ số

- **ARI (Adjusted Rand Index):** đo mức trùng khớp giữa hai phân cụm, hiệu chỉnh may rủi. 1 = trùng khớp hoàn toàn, ~0 = ngẫu nhiên. Dùng cho stability (§4.3) và intrinsic eval (§3).
- **NMI (Normalized Mutual Information):** thông tin chung giữa hai phân cụm, chuẩn hoá [0,1]. Bổ trợ ARI.
- **`cluster_persistence` (HDBSCAN):** độ bền của cụm dọc theo hệ phân cấp mật độ; cao = cụm "đậm", đáng làm intent.
- **Silhouette:** một điểm gần cụm của nó so với cụm gần nhất khác cỡ nào; đại diện separability (§6).
- **Cohen's κ:** nhất trí giữa 2 annotator hiệu chỉnh may rủi; ≥0.6 = khá, ≥0.8 = tốt.
- **Wilson 95% CI:** khoảng tin cậy cho tỉ lệ (precision) ổn định ở cỡ mẫu nhỏ — dùng thay khoảng normal vì n/intent bé (§9.3).
- **Gini:** độ tập trung của phân bố khối lượng theo intent; cao = vài intent gánh phần lớn (§6).
