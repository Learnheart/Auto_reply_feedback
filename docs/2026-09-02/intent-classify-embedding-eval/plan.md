---
author: klinh2212112@gmail.com
date: 2026-09-02
status: in-progress
agents: inference.classify
summary: B1 classify bằng embedding matching (exemplar sinh mới làm source) + bộ test trong src/04_tests đo trên golden dataset feedback_gold.csv.
---

## Architecture reference

- Module: **`inference.classify` (B1)** — `docs/architecture.md` §3 *Trách nhiệm từng module*: "Embed feedback mới → cosine tới exemplar → gán intent + confidence → routing 3 vùng".
- Sections: `docs/architecture.md` §4.2 *Flow B* (B1: load exemplar + thresholds → embed + max-cosine), §4.3 *Flow C — Threshold routing* (3 vùng `ok` / `low_confidence` / `unclassified`; vùng dưới ngưỡng KHÔNG đoán nhãn), §4.5 *Data layer* (`flag: ok | low_confidence | unclassified`), §5 *Technology Stack* (embedding qwen3 — bắt buộc cùng model với lúc sinh exemplar vector), §6.1 R2 (exemplar vector chết theo model), R3 (max cosine tới 3–5 exemplar, không phải mean/centroid), §6.3 bước 4 (calibrate ngưỡng trên holdout).
- Labeling guide: `data/golden/intent_explain.md` (định nghĩa 5 nhãn của golden).
- Data contract: exemplar source = `data/sample/exemplars/intent_exemplars.csv` (plan `docs/2026-09-02/inference-exemplar-samples/plan.md`); holdout = `data/golden/feedback_gold.csv` (192 dòng, 5 nhãn); `fb_<idx:04d>` theo thứ tự dòng.

## Problem statement

Đã có (1) bộ exemplar sinh mới 5 mẫu/nhãn × 4 nhãn độc lập với feedback thật, (2) bộ nhãn vàng 192 dòng `feedback_gold.csv`. Chưa có code B1 nào dùng chúng: `src/03_inference` đã bị dọn (các file classify/catalog cũ đọc `catalog_a.json` — nguồn exemplar bị leakage — không còn), `src/04_tests` rỗng. Cần: một file inference embedding-matching lấy exemplar mới làm source, và bộ test đo nó trên golden dataset.

## Requirements (user 2026-09-02)

- `src/03_inference`: 1 file inference dùng **embedding matching** — exemplar từng nhãn trong `intent_exemplars.csv` làm source.
- `src/04_tests`: các test case cho bước intent classification, dùng `feedback_gold.csv` làm golden dataset.

## Decisions made

- **D1 — `src/03_inference/classify.py`**, routing đúng §4.3: confidence = **max cosine** tới mọi exemplar (R3); `c ≥ high → flag=ok`, `low ≤ c < high → flag=low_confidence` (vẫn gán nhãn, cờ ⚠), `c < low → flag=unclassified` (KHÔNG đoán nhãn ⇒ so với gold, dự đoán = `unclassified`). Ngưỡng mặc định `high=0.60, low=0.45` (kế thừa bản classify cũ, CHƯA calibrate — calibrate là bước sau trên chính bộ đo này).
- **D2 — Tái dùng `embed_texts` của `step1_clustering.py`** (qwen3 `databricks-qwen3-embedding-0-6b` qua Model Serving, L2-norm, cache đĩa `src/01_intent_classification/out/embed_cache.json`) — đúng R2: exemplar và feedback phải cùng không gian vector; cache chung nghĩa là 192 feedback đã embed từ Phase 0 không tốn tiền embed lại. Import qua `importlib` (tên thư mục bắt đầu bằng số, không import thường được); top-level import của step1 nhẹ (numpy).
- **D3 — Encoder injectable**: `classify_texts(texts, index, encoder=...)` nhận callable `texts → (N,dim)` ⇒ unit test offline dùng fake encoder deterministic, không mạng, không tiền; eval thật mới gọi qwen3.
- **D4 — Test 2 tầng trong `src/04_tests/test_intent_classification.py`**:
  - *Offline (luôn chạy, không mạng):* contract exemplar CSV (đúng 4 nhãn × 5 mẫu, không có `unclassified`, id `ex_<label>_<nn>`); contract golden CSV (192 dòng, nhãn ∈ 5-set); **leakage guard** (không content exemplar nào trùng/chứa nhau với content golden — giữ tính golden vĩnh viễn, fail khi ai đó thêm exemplar chép từ feedback thật); logic routing 3 vùng + max-cosine với vector giả.
  - *Eval trên golden (cần embedding thật):* classify cả 192 dòng, in report (accuracy tổng, precision/recall/F1 từng nhãn, confusion, phân bố 3 vùng), assert sàn hồi quy. Không có auth/mạng ⇒ `pytest.skip`, không fail CI.
- **D5 — Eval nằm trong `classify.py` (`--eval`)**, test gọi lại hàm đó — một nguồn sự thật cho metric, chạy tay được ngoài pytest.
- **D6 — Sàn hồi quy đặt SAU khi chạy eval lần đầu** (dưới con số quan sát một biên an toàn) — đặt trước là đoán mò. Kết quả lần đầu ghi vào mục Results bên dưới.
- **D7 — Fallback encoder HF local (user yêu cầu 2026-09-02): `Qwen/Qwen3-Embedding-0.6B` qua sentence-transformers.** Máy dev không có credential Databricks ⇒ thêm `hf_encoder()` + `resolve_encoder(mode)`: `databricks` | `hf` | `auto` (probe client Databricks fail-fast, không tốn API call; hỏng ⇒ fallback HF kèm cảnh báo). **Ràng buộc R2**: HF fallback dùng **cache riêng** (`src/03_inference/out/hf_embed_cache.json`, key prefix `hf:`) và embed lại TOÀN BỘ text trong run — không bao giờ trộn vector Databricks với vector HF trong cùng một phép so cosine. Cùng base qwen3-0.6b nên cùng không gian vector về nguyên tắc (tiền lệ v3.3: LM Studio ↔ Databricks coi là cùng space), nhưng serving có thể lệch nhẹ (dtype/pooling) ⇒ **HF chỉ cho dev/eval local; production B1 vẫn bắt buộc Model Serving (§5)** — số đo HF là chỉ báo, con số chốt phải đo lại bằng encoder production.

## Implementation approach

1. `src/03_inference/classify.py`: `load_exemplars` → `build_index` (embed 20 exemplar) → `classify_texts` (max-cosine + routing) → `evaluate_golden` (metrics thuần Python, không sklearn) + CLI (`--eval` | classify 1 câu).
2. `src/04_tests/test_intent_classification.py` + `src/04_tests/conftest.py` (helper importlib nạp module từ thư mục tên số).
3. Chạy offline tests → chạy eval thật → chốt sàn hồi quy → cập nhật plan (Results) + CHANGELOG.

## Results

- **Offline tests: 15/15 PASS** (contract exemplar/golden, leakage guard, routing 3 vùng, max-cosine, build_index).
- Deps đã cài thêm vào env local: `truststore`, `databricks-sdk`, `openai`, `httpx`, `sentence-transformers` (+torch). Databricks CLI v1.14.1 tải về `%LOCALAPPDATA%\databricks-cli\` (chưa login — cần SSO tương tác).

### Eval lần 1 — 2026-09-02, encoder HF fallback (D7), ngưỡng mặc định high=0.60/low=0.45

**accuracy 81/192 = 42.2%** — KHÔNG ĐẠT. Phân bố 3 vùng: ok 34 · low_confidence 101 · unclassified 57.

| label | prec | recall | f1 | support | predicted |
|---|---:|---:|---:|---:|---:|
| bug | 0.64 | 0.29 | 0.40 | 62 | 28 |
| new_feature | 0.86 | 0.29 | 0.44 | 65 | 22 |
| praise | 0.64 | 0.80 | 0.71 | 20 | 25 |
| complain | 0.20 | 0.75 | 0.32 | 16 | 60 |
| unclassified | 0.28 | 0.55 | 0.37 | 29 | 57 |

**Chẩn đoán (3 nguyên nhân, theo mức nặng):**

1. **`complain` hút nhầm `bug` (28/62 dòng bug → complain).** Exemplar complain toàn khuôn "kết quả + không/chưa + tốt" — cosine gần các câu bug ngắn kiểu "không ra được kết quả" (0.77!), "Không phản hồi" (0.70), "lỗi không dùng được" (0.68). Phủ định + danh từ chung giống nhau, embedding không phân biệt được *malfunction* với *chê chất lượng* — đúng cảnh báo của `docs/2026-08-31/intent-knowledge-coupling/design.md`.
2. **`new_feature` recall 0.29 — 25 dòng rơi xuống `unclassified`** (conf 0.32–0.45): feature request thật rất đa dạng chủ đề, 5 exemplar chung chung không phủ nổi; max-cosine điển hình chỉ ~0.4.
3. **Ngưỡng 0.60/0.45 không khớp phân bố cosine thực** (chỉ 34 dòng vượt 0.60; câu cực ngắn vô nghĩa như "No"/"1" lại cosine 0.68–0.70 với exemplar ngắn ⇒ ngưỡng không cứu được nhóm này).

**Hàm ý:** exemplar "chung chung hoá" trade-off sai hướng cho cặp bug/complain — cần exemplar bug bám *triệu chứng malfunction* (error/treo/crash) tách khỏi khuôn "chê kết quả", cân nhắc thêm số exemplar/nhãn hoặc per-intent threshold khi calibrate; và con số này là HF fallback — cần đo lại bằng encoder production trước khi kết luận cuối. `MIN_ACCURACY` trong test đặt 0.35 (chặn hỏng hẳn, không phải mục tiêu chất lượng).

## Non-goals

- KHÔNG calibrate ngưỡng trong lần này (chỉ đo với ngưỡng mặc định; calibrate = bước riêng §6.3-4).
- KHÔNG dựng lại B2/B3 (draft/deliver), KHÔNG đụng catalog `catalog_a.json`.
- KHÔNG sinh/ghi `exemplar_vectors` vào catalog frozen.
