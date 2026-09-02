---
author: klinh2212112@gmail.com
date: 2026-09-03
status: done
agents: inference.classify
summary: Ba cải thiện B1 do PM chốt — (b) exemplar v2 (complain viết lại, 10 mẫu/nhãn, trộn register), (c) instruct prefix Qwen3-Embedding phía query, (d) tách abstention khỏi metric + đường coverage–accuracy.
---

## Architecture reference

- Module: **`inference.classify` (B1)** + **Intent Catalog** (source exemplar) — `docs/architecture.md` §3.
- Sections: §4.3 (routing/abstention `unclassified`), §6.1 R3 (exemplar), §6.3 bước 4 (calibrate — đường coverage–accuracy chính là công cụ cho bước này), §5 (embedding qwen3).
- Labeling guide: `data/golden/intent_explain.md` (ví dụ complain: "slide chưa đẹp", "dịch quá tệ").
- Experiment log: `src/05_experiments/runs/` (plan `docs/2026-09-03/experiment-tracking-lite/plan.md`).

## Problem statement (từ eval baseline 42.2% + run hạ ngưỡng 43.8%)

1. Exemplar `complain` v1 toàn khuôn generic "kết quả + không/chưa + tốt" ⇒ hút 28–33 dòng `bug`. Thiếu câu chê chất lượng output cụ thể đúng ví dụ guide.
2. **Domain gap về register**: exemplar là văn phong chuẩn, gold là khẩu ngữ/viết tắt ("ko work", "chưa tạo dc", "k phản hồi").
3. `embed_texts` embed text thô — dòng Qwen3-Embedding được train với prefix `Instruct: {task}\nQuery: {text}` ở phía query; bỏ prefix thường mất vài điểm. Rẻ, thử trước khi động scoring.
4. Bảng metric gộp `unclassified` (gold "không đọc được ý") với abstention của model vào một ô confusion ⇒ P/R 4 nhãn thật bị trộn với abstention rate, một điểm ngưỡng đơn lẻ nói được rất ít.

## Decisions made (PM chốt 2026-09-03)

- **D1 (b) — Exemplar v2**: `complain` viết lại toàn bộ 10 câu — chê chất lượng output cụ thể (slide xấu, dịch lủng củng, tóm tắt sơ sài, lan man…) **không chứa động từ malfunction**; 3 nhãn còn lại giữ 5 câu v1 + thêm 5 câu **register khẩu ngữ** ("ko chạy dc", "vô ko nổi", "quá đã", "cho xin thêm nút…") ⇒ 10 mẫu/nhãn × 4 = 40. Vẫn giữ ràng buộc độc lập với gold (leakage guard trong test tự kiểm). Test contract nới 5 → 5–15 mẫu/nhãn.
- **D2 (c) — Instruct prefix phía QUERY, exemplar giữ nguyên không prefix** (đúng khuôn asymmetric của dòng Qwen3-Embedding: query có instruct, document không). Prefix ghép ở tầng text trước khi embed ⇒ dùng được cho cả encoder HF lẫn Databricks (không phụ thuộc server có hỗ trợ tham số instruction hay không). Instruction: tiếng Anh theo khuyến nghị model card.
- **D3 (d) — `evaluate_golden` tách 3 tầng metric** (giữ nguyên các key cũ để run cũ/test so sánh được):
  - *(strict)* accuracy 5-nhãn như cũ — nối tiếp lịch sử run;
  - *(i)* chất lượng phân loại **khi model trả lời**: confusion 4×4 + P/R/F1 chỉ trên dòng model không abstain VÀ gold có nhãn thật; abstention báo riêng (`caught` = gold-unclassified bị chặn đúng, `false_abstain` = có nhãn thật mà bỏ phiếu trắng, `false_accept` = gold-unclassified bị gán nhãn);
  - *(ii)* **đường coverage–accuracy**: quét ngưỡng abstain 0.30→0.75 bước 0.05, mỗi điểm ghi coverage + accuracy-trên-dòng-trả-lời (cả bản tính gold-unclassified-là-sai lẫn bản chỉ xét gold thật) ⇒ chọn ngưỡng theo trade-off thay vì một điểm 0.60/0.45.
- **D4 — Hai run tách bạch để quy công**: `exemplar_v2_hf` (chỉ b) rồi `exemplar_v2_instruct_hf` (b+c), cùng ngưỡng 0.60/0.45 với baseline.

## Implementation approach

1. `data/sample/exemplars/intent_exemplars.csv` v2 (40 dòng) + cập nhật README.
2. `classify.py`: tham số `query_instruction` (classify_texts + evaluate_golden); evaluate_golden thêm khối `answered` / `abstention` / `coverage_curve` + in report 3 tầng.
3. `src/04_tests`: nới contract số mẫu/nhãn; leakage guard giữ nguyên (tự kiểm bộ v2).
4. `run_experiment.py`: đăng ký 2 approach mới (D4), chạy cả hai, ghi run.
5. CHANGELOG.

## Results (2026-09-03, HF encoder, ngưỡng 0.60/0.45)

| run | strict 5-nhãn | acc khi trả lời (gold thật) | ghi chú |
|---|---:|---:|---|
| baseline v1 | 42.2% | — | tham chiếu |
| **(b) exemplar v2** | **49.0%** (+6.8) | **57.1%** | bug precision 0.64→0.92, praise F1 0.79, new_feature F1 0.65 |
| (b)+(c) v2 + instruct | 47.4% (−1.6 vs v2) | 54.8% | **instruct prefix LÀM GIẢM nhẹ — kết quả âm, GIỮ no-prefix** (cũng giữ parity với serving embed text thô, R2) |

- **(b) ăn điểm rõ**: bug không còn bị complain hút ồ ạt nhờ complain exemplar đổi khuôn (bug→complain 28 → 16 dòng); register khẩu ngữ giúp new_feature recall 0.29 → 0.67 (answered).
- **Lỗi còn lại sau v2** (đọc từ confusion 4×4): (1) `complain` vẫn over-predict — 42 dự đoán cho 16 support, precision 0.19; (2) `bug` recall answered chỉ 0.39 — 56 dòng bug chia đôi sang complain (16) và **new_feature (16 — confusion MỚI: exemplar khẩu ngữ "chưa xài dc…" hút câu bug "ko sử dụng được")**; (3) câu cực ngắn khẩu ngữ dính chùm ("k phản hồi" → praise 0.60).
- **(d) đường coverage–accuracy (run v2)**: phẳng ~58% (acc trên dòng gold thật) suốt t=0.30→0.50 (coverage 99%→70%), chỉ nhích lên 63.7% ở t=0.55 (coverage 47%) và 74.4% ở t=0.60 (coverage 22%). Kết luận: **chất lượng xếp hạng là trần, ngưỡng chỉ đánh đổi coverage** — đúng nghi vấn "một điểm đơn lẻ nói được rất ít"; ngưỡng đáng cân nhắc nếu chấp nhận coverage ~50% là quanh 0.55.
- Abstention (v2): bắt đúng 10/29 gold-unclassified, 19 lọt lưới, 16 dòng nhãn thật bị bỏ phiếu trắng oan.
- Bước kế tiếp hợp lý: contrastive scoring với negative exemplar cho cặp complain↔bug và new_feature↔bug (đo trên nền v2).

## Non-goals

- KHÔNG contrastive scoring / negative exemplar (bước sau, đo trên nền v2).
- KHÔNG chốt ngưỡng mới trong lần này — coverage–accuracy là dữ liệu để chốt ở run kế.
