---
author: klinh2212112@gmail.com
date: 2026-08-25
status: draft
agents: intent-catalog, inference.classify
summary: Review techstack bước Intent Classification (Phase 0 offline) — giải thích thuật toán, cách dùng LLM, và phương pháp đánh giá; đối chiếu stack production với stand-in local trong script.
---

# Techstack Review — Intent Classification (Phase 0 Offline)

| Field | Value |
|-------|-------|
| **Loại tài liệu** | Reference / techstack explainer |
| **Đối tượng** | Data scientist / reviewer |
| **Bám theo** | `docs/method-offline-intent-analysis.md`, script `intent_classification/run_intent_analysis.py` |

## Architecture reference

- **Module:** `Offline intent analysis` → Intent Catalog (§3 Trách nhiệm từng module).
- **Sections:** `docs/architecture.md` §5 Technology Stack (dòng Embedding / LLM / Phân tích offline), §3 Phase 0, §4.3 Threshold routing, §6.1 R2/R3.
- **Method doc:** `docs/method-offline-intent-analysis.md` §3 (embed), §4 (cluster + stability), §6 (validation), §8 (exemplar + scoring), §9 (calibrate).
- **Data contract:** `intent_catalog` (§4.5) — `embedding.model_name`, `dim`, `scoring`, `exemplars`, `threshold_high/low`.

> **Đọc kèm bảng "hai làn" (§1).** Có hai stack song song: (a) **production** trên Databricks — cái sẽ chốt catalog thật; (b) **stand-in local** trong script — thuật toán rẻ hơn cùng *hình dạng*, để chạy được offline khi chưa có Model Serving/UMAP/HDBSCAN. Mọi mục dưới đây nói rõ đang bàn cái nào.

---

## 1. Bản đồ techstack

Script **dùng thẳng thuật toán production** cho embed/reduce/cluster (không còn stand-in). Chỉ hai khối cần dịch vụ ngoài / công-người (LLM merge, calibrate ngưỡng) là còn ngoài script.

| Vai trò trong pipeline | Thuật toán (production) | Hàm trong script | Trong script? |
|---|---|---|---|
| **Embedding** (text → vector) | `databricks-qwen3-embedding-0-6b` (Model Serving, OpenAI-compat, OAuth profile) | `embed_texts()` | ✅ (có cache đĩa) |
| **Giảm chiều** | `umap.UMAP(n_components=10, metric=cosine)` | `reduce_dims()` | ✅ |
| **Clustering** | `hdbscan.HDBSCAN(min_cluster_size, min_samples, metric=euclidean)` + sweep `min_cluster_size` | `cluster()`, `cluster_sweep()` | ✅ |
| **Đo độ gần / medoid** | euclidean trên không gian UMAP | `medoid()`, `review_table()` | ✅ |
| **Đánh giá cụm** | ARI (stability + intrinsic), coverage, Gini, `cluster_persistence` | `adjusted_rand_index()`, `stability()`, `validation()` | ✅ |
| **Đặt tên & gộp cụm** | LLM `claude-sonnet-4-6-sit-tai` (structured output) | — | ❌ (in "next step") |
| **Fallback / ack ngắn** | LLM `claude-haiku-4-5-sit-tai` | — | ❌ |
| **Exemplar scoring** | cosine max / top2-mean / prototype tới exemplar | — | ❌ (§8) |
| **Calibrate ngưỡng** | holdout tay + Wilson CI + Cohen's κ | — | ❌ (§9) |
| **Điều phối** | Databricks Notebook (không lịch) / 1 file `.py` functional | `main()` | ✅ |

Deps runtime: `openai`, `umap-learn`, `hdbscan`, `databricks-sdk`. Auth: OAuth theo profile `~/.databrickscfg` (mặc định `tcb-agent-sit`) hoặc PAT env `DATABRICKS_HOST/TOKEN`.

> **Lịch sử:** bản đầu dùng stand-in local (char-ngram TF-IDF → PCA → DBSCAN) để chạy khi env thiếu lib/Model Serving. Đã gỡ bỏ. Các giải thích PCA/DBSCAN/TF-IDF ở §2 giữ lại làm nền khái niệm nhưng **không còn trong code**.

---

## 2. Thuật toán — giải thích

### 2.1 Embedding — biến text thành vector

**Ý tưởng chung.** Mọi bước sau (cluster, cosine, ngưỡng) làm việc trên **vector số**, không trên chữ. Embedding là ánh xạ `text → R^d` sao cho hai feedback *nghĩa gần nhau* thì vector *gần nhau* theo cosine. Chất lượng embedding là trần chất lượng của cả pipeline — cluster không thể tốt hơn không gian vector mà nó đứng trên.

**Production — qwen3-embedding-0-6b.** Model transformer đa ngôn ngữ (quan trọng vì feedback trộn VI/EN, §2.1 method), xuất vector `dim=1024`. Đặc tính cốt lõi: nó *hiểu ngữ nghĩa* — "không xuất được PDF" và "nút tải file không phản hồi" sẽ gần nhau dù không chung một từ. Ràng buộc cứng (R2): **exemplar chỉ có nghĩa trong cùng một không gian vector** ⇒ model dùng lúc phân tích offline phải trùng model lúc runtime, nếu không cosine thành số vô nghĩa.

**Stand-in — char-ngram hashing TF-IDF.** Không có transformer local, script mô phỏng bằng đại số văn bản thuần:
1. Cắt mỗi feedback thành **char n-gram** độ dài 3–5 (ví dụ `"xuất"` → `xuấ`, `uất`, `xuất`…). Char-level ⇒ an toàn đa ngôn ngữ, không cần tách từ tiếng Việt.
2. **Hashing trick:** băm mỗi n-gram vào 1 trong 1024 bucket (`blake2b`, xác định) → vector đếm tần suất `tf`. Bounded dim, không cần dựng từ điển.
3. **TF-IDF:** nhân `tf` với `idf = log((N+1)/(df+1)) + 1` để hạ trọng số n-gram phổ biến khắp nơi (ít phân biệt), nâng n-gram hiếm (đặc trưng).
4. **L2-normalize:** đưa vector về độ dài 1 ⇒ cosine = tích vô hướng, tính nhanh.

Hạn chế cần nói thẳng: đây là tương đồng **bề mặt ký tự**, không phải ngữ nghĩa. Hai câu cùng nghĩa mà khác chữ sẽ *không* gần nhau như với qwen3. Do đó **con số cluster từ stand-in chỉ để thấy pipeline chạy**, không phản ánh chất lượng taxonomy thật.

### 2.2 Giảm chiều — vì sao và bằng gì

**Vì sao giảm chiều trước khi cluster.** Ở 1024 chiều, khoảng cách bị "curse of dimensionality" — mọi điểm gần như cách đều nhau, mật độ mất ý nghĩa, clustering density-based hoạt động kém. Nén xuống ~10 chiều giữ lại cấu trúc chính, khôi phục khái niệm "cụm đặc". **10 chiều, không phải 2** — 2D chỉ để vẽ cho người xem; cluster trên 2D là vứt thông tin (§4.1 method).

**Production — UMAP** (Uniform Manifold Approximation and Projection). Học **manifold phi tuyến:** dựng đồ thị k-láng-giềng (tham số `n_neighbors` cân bằng cấu trúc cục bộ ↔ toàn cục), rồi tối ưu một bố cục chiều thấp sao cho topology của đồ thị được bảo toàn. Giữ cụm *cong/lõm* tốt hơn phương pháp tuyến tính. **Là stochastic** ⇒ bắt buộc cố định `random_state` để tái lập (và để đo stability §4.3).

**Stand-in — PCA** (Principal Component Analysis) qua SVD. Là phép **tuyến tính:** tìm các trục (thành phần chính) giữ phương sai lớn nhất, chiếu dữ liệu lên top-10 trục. `X_centered = U·S·Vᵀ`, thành phần = hàng của `Vᵀ`, tỉ lệ phương sai giữ = `s_i² / Σs²`. Rẻ, xác định, nhưng **không** bắt được manifold cong như UMAP — đó là cái giá của stand-in. Sau chiếu vẫn L2-normalize để cluster bằng cosine.

### 2.3 Clustering — nhóm không cần biết trước số nhóm

**Yêu cầu đặc thù.** Ta *không biết trước* có bao nhiêu intent, và cần một cơ chế **để lại điểm ngoài cụm làm "noise"** — chính là dân số `unclassified` tự nhiên (R1). Điều này loại KMeans (buộc chọn k, gán mọi điểm vào cụm). Cần **density-based**.

**Production — HDBSCAN** (Hierarchical DBSCAN). Cơ chế:
- Định nghĩa "mật độ" qua *mutual reachability distance*, dựng cây khoảng cách (MST) rồi **cây phân cấp cụm** theo nhiều mức mật độ cùng lúc — không phải chọn một bán kính duy nhất.
- Trích cụm theo **độ bền (`cluster_persistence`)**: cụm "sống" qua một dải mật độ rộng thì bền, đáng làm intent; cụm chớp tắt là artifact.
- Tham số: `min_cluster_size` (số điểm tối thiểu để gọi là cụm), `min_samples` (độ bảo thủ khi phán noise). Điểm không thuộc cụm nào → nhãn **−1 (noise)**.
- Ưu điểm vs DBSCAN: chịu được **cụm mật độ khác nhau**, không cần chọn `eps`, còn cho *xác suất thành viên*.

**Stand-in — DBSCAN cosine.** Một mức mật độ, hai tham số:
- `eps` = bán kính (theo **cosine distance** `1 − cos`); `min_samples` = số láng giềng tối thiểu.
- **Core point:** có ≥ `min_samples` điểm trong bán kính `eps`. Cụm = tập các điểm *density-connected* (nối nhau qua chuỗi core point). Điểm không với tới được → **noise −1**.
- Vì DBSCAN nhạy `eps`, script **sweep** `eps ∈ {0.10…0.30}` (`cluster_sweep`) và chọn cấu hình cho **số cụm trong dải 12–40** và **noise < 35%** (§4.2). Độ phức tạp `O(N²)` do tính ma trận cosine đầy đủ — chấp nhận được ở N~600, sẽ là HDBSCAN `~O(N log N)` ở production.

**Vì sao cố tình over-segment.** Cả hai đường đều chỉnh tham số để ra **nhiều cụm nhỏ sạch** thay vì ít cụm lẫn. Lý do (§4.2, §5 method): bước sau để **LLM *gộp*** cụm — LLM gộp đáng tin, *tách* thì không. Thà 40 cụm sạch rồi gộp còn hơn 12 cụm lẫn rồi phải tách tay.

### 2.4 Đo tương đồng & routing — cosine + exemplar

**Cosine similarity.** `cos(u,v) = u·v / (‖u‖‖v‖)`; với vector đã L2-norm thì `cos = u·v`. Đo *hướng* chứ không *độ lớn* — phù hợp text vì độ dài feedback không nên ảnh hưởng "cùng chủ đề hay không". `medoid` của cụm = điểm có tổng cosine tới các điểm khác lớn nhất (đại diện "trung tâm" thật, luôn là một feedback có thật — khác centroid ảo).

**Exemplar scoring (production, §8.2).** Ở runtime không cluster lại; thay vào đó mỗi intent giữ **3–5 exemplar** (feedback thật) và confidence của feedback mới = độ gần tới các exemplar đó. Ba công thức cần so trên holdout để chọn:
- `max cosine` — gần nhất tới *một* exemplar. Dễ giải thích, nhưng high-variance (một exemplar lạ chi phối).
- `top-2 mean` — trung bình 2 cosine cao nhất. Giảm variance.
- `prototype` — cosine tới **trung bình các exemplar vector**. Ổn định nhất; vẫn né lỗi "centroid cụm lõm" vì đây là mean của vài điểm đã chọn tay *trong* cụm.

**Threshold routing 3 vùng (§4.3 architecture).** Với confidence `c` và intent thắng:

| Điều kiện | Flag | Hành vi |
|---|---|---|
| `c ≥ threshold_high` | `ok` | Draft đầy đủ, gán intent |
| `threshold_low ≤ c < threshold_high` | `low_confidence` | Draft + cờ ⚠, chờ PM |
| `c < threshold_low` | `unclassified` | **Không đoán nhãn**, ack trung tính, vào `unclassified_pool` |

---

## 3. Cách sử dụng LLM

LLM **không** làm việc phân loại số học (đó là việc của embedding + cosine). LLM chỉ vào ở những chỗ cần **suy luận ngôn ngữ**, và luôn bị ép output có cấu trúc.

### 3.1 Model nào, ở đâu

| Model (Model Serving nội bộ) | Dùng ở | Vì sao model này |
|---|---|---|
| `claude-sonnet-4-6-sit-tai` | §5 gộp + đặt tên cụm; (Phase 2) viết email + trích insight | Cần suy luận ngữ nghĩa & văn phong; đắt hơn nên chỉ dùng nơi thật cần |
| `claude-haiku-4-5-sit-tai` | Nhánh fallback few-shot classify; ack ngắn cho `unclassified` | Rẻ, nhanh; đủ cho việc không cần suy luận sâu |
| `qwen3-embedding-0-6b` | Toàn bộ embedding | Không phải chat model — là "LLM-family" sinh vector; đa ngôn ngữ |

Tất cả qua **endpoint nội bộ** ⇒ thoả A5 (PII không rời nền tảng). Nếu PII không được phép cả nội bộ → mask **trước** khi prompt/embed, và cùng hàm mask dùng lại ở runtime.

### 3.2 LLM đặt tên & gộp cụm (§5 method) — hai prompt

- **5a, mỗi cụm:** đưa 8 feedback gần medoid + kích thước cụm → LLM trả `label`, `description`, `action_type`, `confidence_in_naming`.
- **5b, toàn cục:** đưa toàn bộ label ứng viên + 3 mẫu/cụm → LLM đề xuất *nhóm nào nên gộp* + lý do. (Chỉ gộp — không tách; §2.3.)

**Structured output bằng pydantic.** Mọi lời gọi ép LLM trả về đúng schema pydantic (`Intent`, v.v.), validate ngay. Sai schema ⇒ fail sớm, không ghi rác vào catalog. Đây là lý do `pydantic v2` nằm trong stack (§5 architecture).

**Guardrail cứng:** *LLM không được sinh intent không có cụm đỡ.* Mọi intent phải truy về ≥1 cụm và ≥N feedback thật (trục **Grounding**, §1 method). Chặn "intent nghe hay mà không bao giờ khớp gì" — một failure mode kinh điển khi để LLM tự do đặt taxonomy.

**Ranh giới quan trọng:** con người (PM + AI team) là **review gate** sau LLM (§7). LLM đề xuất, người chốt wording/gộp-tách/`action_type`/folder và ký duyệt. LLM không tự quyết taxonomy.

---

## 4. Cách đánh giá

Đánh giá chia 3 tầng: **chất lượng cụm** (cấu trúc có thật không), **chất lượng taxonomy** (đủ & phân biệt không), **chất lượng ngưỡng** (confidence có nghĩa không). Mỗi chỉ số kèm: định nghĩa, cách đọc, cửa chặn.

### 4.1 Chất lượng cụm

- **ARI — Adjusted Rand Index** *(có trong script)*. Đo mức trùng khớp giữa **hai cách phân cụm**, đã hiệu chỉnh may rủi. Công thức trên bảng contingency `n_ij` (`a_i`,`b_j` = tổng hàng/cột, `N` tổng):
  `ARI = (Σ C(n_ij,2) − E) / (½[ΣC(a_i,2)+ΣC(b_j,2)] − E)`, với `E = ΣC(a_i,2)·ΣC(b_j,2) / C(N,2)`.
  Miền ~[−0.5, 1]: **1 = trùng khớp hoàn toàn, 0 = ngẫu nhiên**. Hai công dụng:
  - **Intrinsic eval (§3 method):** ARI giữa cụm và nhãn nhóm ẩn `latent_theme` của fixture → pipeline có phục hồi nổi cấu trúc *đã biết* không. (Đang skip vì thiếu sidecar — §12.5.)
  - **Stability (§4.3 method):** ARI giữa các lần cluster khi đổi seed UMAP / `min_cluster_size` / `min_samples`. ARI thấp ở biến thể *lân cận* ⇒ cụm mong manh, đừng chốt thành intent.
- **NMI — Normalized Mutual Information.** `NMI = I(U;V) / mean(H(U),H(V))`, miền [0,1]. Bổ trợ ARI (nhạy khác nhau với số cụm lệch).
- **`cluster_persistence` (HDBSCAN, production).** Độ bền cụm dọc dải mật độ; cao = cụm đậm, đáng làm intent. Ghi vào catalog để review gate thấy cụm nào vững.
- **Silhouette (production).** `s(i) = (b−a)/max(a,b)`, `a`=khoảng cách nội cụm trung bình, `b`=tới cụm gần nhất khác. ∈[−1,1]; đại diện **separability** — hai cụm quá gần ⇒ ứng viên gộp.

### 4.2 Chất lượng taxonomy *(có trong script)*

- **Coverage.** % feedback vào một cụm (hoặc runtime: `c ≥ threshold_low`). Phủ thấp ⇒ taxonomy bỏ sót nhiều.
- **Head/tail + Gini.** `Gini = Σ(2i−n−1)·x₍i₎ / (n·Σx)` trên kích thước cụm đã sắp; 0 = đều, →1 = vài cụm gánh tất. Cho biết ROI tập trung ở đâu (nếu 3 intent gánh 80% thì phần còn lại phần lớn trang trí).
- **MECE / khoảng trống.** Separability (§4.1) bắt chồng lấn; đọc tay vùng noise bắt **khoảng trống** — chủ đề thật nhưng < `min_cluster_size` bị nuốt (chặn mù rare-intent, §4.4 method).

### 4.3 Chất lượng ngưỡng — calibration (§9 method, production)

Đây là chỗ biến `confidence` từ "một số float" thành đại lượng có nghĩa; **không được cắt**.

- **Holdout 150–200 nhãn tay**, lấy mẫu phân tầng qua cụm **và vùng noise** (thiếu noise thì không đo được nhánh reject).
- Vẽ **hai phân bố** của `c`: nhóm LLM/embedding đoán **đúng** vs **sai**. Chồng nhiều ⇒ exemplar không phân biệt được intent → quay lại §8 đổi exemplar/công thức, **đừng vặn ngưỡng**.
- Đặt ngưỡng theo hai mục tiêu đối nghịch:

| Ngưỡng | Chọn theo | Vì sao |
|---|---|---|
| `threshold_high` | **precision ≥ 0.90** trong vùng `c ≥ high` | Vùng này gửi user thật, sai là tốn uy tín |
| `threshold_low` | ≤ 5% mẫu **đúng** rơi xuống `unclassified` | Vùng dead-end, rơi oan là mất luôn |

- **Wilson 95% CI** cho precision. Với ~10 mẫu/intent, "precision 0.90" trần trụi có khoảng tin cậy khổng lồ; báo cáo CI thay điểm. Wilson ổn định hơn khoảng normal ở n nhỏ / p cực trị:
  `center = (p̂ + z²/2n)/(1+z²/n)`, `nửa rộng = z/(1+z²/n)·√(p̂(1−p̂)/n + z²/4n²)`.
- **Recall của nhánh reject**, không chỉ precision vùng high — `threshold_low` phải bắt được cả cái *thật sự lạ*, không chỉ tránh rơi oan.
- **Cohen's κ (IAA).** Hai annotator gán chồng ~30 mẫu; `κ = (p_o − p_e)/(1 − p_e)` (`p_o` đồng thuận quan sát, `p_e` đồng thuận may rủi). **κ ≥ 0.6** mới tin holdout để đặt ngưỡng 0.90 — calibrate trên nhãn nhiễu là calibrate lên nhiễu.
- **Global vs per-intent.** Per-intent cần ~30 mẫu/intent (×15 = 450 nhãn, gấp đôi ngân sách). V1 dùng **một cặp ngưỡng global**, override per-intent chỉ cho intent có đủ ≥30 mẫu.

> **Đính chính thường gặp:** noise rate của clustering **≠** prior của `unclassified_rate` — hai cơ chế khác (density thấp vs cosine-dưới-ngưỡng). Prior đúng cho R1 lấy từ **phân bố 3 vùng trên holdout §4.3**, không từ noise rate §2.3.

---

## 5. Đối chiếu nhanh với script

| Step console | Hàm | Thuật toán | Bàn ở mục |
|---|---|---|---|
| STEP 0 audit | `audit()` | thống kê mô tả, phát hiện VI/EN | §2.1 |
| STEP 1 preprocess | `preprocess()` | giữ hết feedback, chỉ bỏ content vô nghĩa (`isalpha`) | §2.1 method |
| STEP 2 embed | `embed_texts()` | **qwen3 Databricks** (Model Serving) + cache | §2.1 |
| STEP 3 reduce | `reduce_dims()` | **UMAP** 10D metric cosine | §2.2 |
| STEP 4 cluster | `cluster_sweep()` | **HDBSCAN** euclidean + sweep `min_cluster_size` | §2.3 |
| STEP 5 stability | `stability()` | ARI qua seed UMAP / min_cluster_size / min_samples | §4.1 |
| STEP 6 validation | `validation()` | coverage, Gini, head/tail, ARI-vs-latent | §4.2 |
| STEP 7 review table | `review_table()` | medoid + 8 mẫu gần nhất + persistence → CSV | §2.4, §3.2 |
| NEXT | *(in text)* | LLM merge §5, exemplar §8, calibrate §9 | §3, §4.3 |

---

## 6. Đánh giá tổng — điểm mạnh & giới hạn của techstack

**Hợp lý:**
- Chuỗi *embedding → giảm chiều → density clustering → LLM đặt tên* là pipeline chuẩn cho topic discovery từ short text (họ BERTopic). Density-based + noise `−1` đúng nhu cầu (cần `unclassified`, không ép mọi điểm vào cụm).
- Phân vai đúng: **số học phân loại** (embedding/cosine, rẻ, tái lập) tách khỏi **suy luận ngôn ngữ** (LLM, đắt, chỉ đặt tên/gộp), và con người là chốt chặn cuối.
- Exemplar-based scoring + threshold routing giải thích được cho PM và vá được bằng một dòng YAML.

**Giới hạn phải nhớ:**
- **Stand-in ≠ production.** Char-ngram/PCA/DBSCAN chỉ đúng *hình dạng* pipeline; số cụm/coverage hiện tại **không** dùng để chốt taxonomy. Chốt thật phải chạy qwen3 + UMAP + HDBSCAN.
- **qwen3-0.6B là model nhỏ** — nền của mọi thứ downstream; cần intrinsic eval (ARI-vs-latent) xác nhận trước khi tin.
- **Ngân sách nhãn mỏng** (10–13 mẫu/intent) khiến precision per-intent có CI rộng → V1 global threshold là quyết định thực dụng, không phải lý tưởng.
- **R2 chết cứng embedding:** đã giảm thiểu bằng lưu exemplar dạng text + check `model_name`, nhưng vẫn là ràng buộc phải canh mỗi lần Databricks nâng cấp endpoint.
