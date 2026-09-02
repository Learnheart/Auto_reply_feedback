---
author: klinh2212112@gmail.com
date: 2026-09-03
status: done
agents: inference.classify
summary: Contrastive scoring ở tầng inference — negative exemplar trừ điểm intent hay bị nhầm, encoder giữ nguyên; đo trên nền exemplar v2 @ 0.60/0.45.
---

## Architecture reference

- Module: **`inference.classify` (B1)** — `docs/architecture.md` §3; mở rộng công thức confidence, KHÔNG đổi encoder/stack (§5) hay routing 3 vùng (§4.3).
- Sections: §6.1 R3 (exemplar-based, giải thích được cho PM — negative cũng là dòng CSV review được), R2 (không train/không đổi model ⇒ không đụng không gian vector).
- Labeling guide: `data/golden/intent_explain.md` — cột **"Không phải nhãn này khi"** chính là đặc tả negative; lưu ý đầu file chỉ cấm đưa nó vào index *như mẫu dương* — tách thành negative ở tầng scoring là cách hợp lệ.
- Mốc so sánh: run `exemplar_v2_hf` (strict 49.0%, answered 57.1%, ngưỡng 0.60/0.45) — `runs/index.md`.

## Problem statement

Sau exemplar v2 còn 2 cặp lẫn hệ thống (confusion 4×4): `bug→complain` 16 + `new_feature→complain` 15 (complain over-predict, precision 0.19) và `bug→new_feature` 16 (exemplar khẩu ngữ "chưa xài dc" hút "ko sử dụng được"); thêm nhóm câu ngắn dính `praise` ("k phản hồi"→praise 0.60). Positive-only max-cosine không có cơ chế "đẩy ra".

## Decisions made (PM chốt phương pháp 2026-09-03)

- **D1 — Công thức**: `score(intent) = max_cos(positives) − λ · max_cos(negatives của intent)`; nhãn = argmax score. **Confidence cho routing = raw max_cos positive của nhãn thắng** (không phải score đã trừ) ⇒ ngưỡng 0.60/0.45 giữ nguyên ngữ nghĩa, so sánh được với mốc v2; contrastive chỉ RE-RANK nhãn.
- **D2 — Negative = hard negative theo cặp hay nhầm**, file riêng `data/sample/exemplars/intent_exemplar_negatives.csv` (schema `id,agent,content,label` — `label` là intent BỊ TRỪ điểm khi feedback gần câu đó): `complain` ← khuôn bug + khuôn feature-request (6); `new_feature` ← khuôn bug khẩu ngữ "ko dùng dc/báo lỗi" (4); `praise` ← khuôn bug ngắn + prompt-misfire + complain (4); `bug` ← khuôn chê chất lượng (3). Không bắt buộc nhãn nào cũng có negative (bug precision đã 0.9+). Negative cũng phải **độc lập với gold** — leakage guard mở rộng sang file này.
- **D3 — λ quét 2 điểm: 0.3 và 0.5** (2 run riêng để so). Không fine-tune encoder (đã loại từ thảo luận trước — lệch R2/§5 và không có data train hợp lệ).
- **D4 — Encoder + exemplar positive giữ nguyên v2** để quy công đúng cho negative scoring.

## Implementation approach

1. `intent_exemplar_negatives.csv` (17 dòng, sinh mới).
2. `classify.py`: `load_negatives` + `build_neg_index` (tái dùng `ExemplarIndex`), `classify_texts_contrastive(texts, index, neg_index, encoder, lam, ...)`; `evaluate_golden(..., contrastive_lambda=None)` — có λ thì đi đường contrastive.
3. Test offline: loader negative (nhãn lạ/sink fail-loud), toy contrastive (gần negative ⇒ đổi nhãn thắng; λ=0 ≡ plain), leakage guard phủ file negative.
4. `run_experiment.py`: approach `contrastive_neg_hf_l03`, `contrastive_neg_hf_l05`; chạy, so mốc v2.
5. CHANGELOG + Results.

## Results (2026-09-03, HF encoder, ngưỡng 0.60/0.45, nền exemplar v2)

| run | strict | answered (gold thật) | macro-F1 | ghi chú |
|---|---:|---:|---:|---|
| v2 (mốc, positive-only) | 49.0% | 57.1% | 0.48 | |
| **contrastive λ=0.3** | **51.6%** | **59.6%** | **0.51** | ✅ best hiện tại |
| contrastive λ=0.5 | 50.5% | 59.0% | 0.51 | trừ mạnh hơn không tốt hơn |

- **Ăn điểm đúng chỗ nhắm một phần**: `bug→new_feature` 16 → 12 (negative "ko dùng dc/báo lỗi" của new_feature phát huy), bug recall (answered) 0.39 → 0.46, new_feature precision 0.64 → 0.71.
- **Chỗ chưa ăn**: `bug→complain` vẫn 16 dòng và `complain` vẫn over-predict (43 dự đoán/15 support, precision 0.21) — negative khuôn bug của complain chưa đủ gần các câu bug ngắn đang bị hút ("không ra được kết quả" họ hàng); cần soi các dòng đó xem chúng gần positive complain nào để viết negative sát hơn, hoặc tăng λ riêng cho complain (per-intent λ) thay vì λ chung.
- λ=0.5 kém hơn λ=0.3 một chút ⇒ trừ quá tay bắt đầu hại các dòng vốn đúng. Giữ **λ=0.3** làm mặc định thí nghiệm.
- Abstention λ=0.3: caught 12/29, false_abstain 17 (nhỉnh hơn v2: 10/29, 16).

### Wire vào code lõi (2026-09-03, PM yêu cầu)

`classify.py` nay **mặc định chạy cấu hình này**: `DEFAULT_CONTRASTIVE_LAMBDA = 0.3`, `evaluate_golden` và cả hai nhánh CLI (`--eval`, classify câu lẻ) đi đường contrastive; `--no-contrastive` / `--lambda X` để tắt/chỉnh. Trước đó code lõi vẫn là positive-only dù best là contrastive — nhánh classify câu lẻ thậm chí không build negative index.

Để hồ sơ thí nghiệm không bị lệch, 5 approach lịch sử trong `run_experiment.py` ghim `contrastive_lambda=None` tường minh; chạy lại `exemplar_v2_hf` tái lập đúng 49.0%/0.48/42-124-26. `exemplar_cosine_databricks` → **`best_databricks`** (best config trên encoder production, chờ auth).

**Phát hiện phụ khi verify**: input tiếng Việt **không dấu** bị match sai hẳn ("app bao loi khong dung duoc" → `new_feature` conf 0.61, khớp một exemplar tiếng Anh), trong khi bản có dấu ra đúng `bug` (0.64). Exemplar và gold đều có dấu ⇒ chưa phủ register không dấu. Nếu feedback production có dòng không dấu, cần thêm exemplar không dấu hoặc bước chuẩn hoá — chưa xử lý trong scope này.

## Non-goals

- KHÔNG fine-tune/contrastive learning trên encoder.
- KHÔNG đổi ngưỡng (0.60/0.45 giữ nguyên theo quyết định revert cùng ngày).
- KHÔNG đưa negative vào catalog frozen production trong lần này — đây là thí nghiệm; muốn productionize phải cập nhật data contract `intent_catalog` (§4.5) trước theo rule 3.6.
