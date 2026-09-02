---
author: klinh2212112@gmail.com
date: 2026-09-03
status: done
agents: inference.classify
summary: Experiment tracking tối giản cho B1 — mỗi phương án là 1 function, mỗi run lưu config + metrics + report vào src/05_experiments/runs/ để review lại.
---

## Architecture reference

- Module: **Offline intent analysis** (`docs/architecture.md` §3 — `❌ Ngoài hệ thống`): đây là hạ tầng THÍ NGHIỆM cho các phương án B1, không nằm trong Databricks Job nào. Đối tượng đo: `inference.classify` (B1).
- Sections: `docs/architecture.md` §4.3 (routing 3 vùng — thứ các phương án phải tôn trọng), §6.3 bước 4 (calibrate trên holdout — chuỗi thí nghiệm này phục vụ đúng bước đó), §5 (embedding production; HF fallback chỉ dev/eval — plan `intent-classify-embedding-eval` D7).
- Data contract: holdout = `data/golden/feedback_gold.csv`; source = `data/sample/exemplars/intent_exemplars.csv`. Mỗi run lưu **content-hash của cả hai file** — dữ liệu đổi giữa các run (sẽ sửa exemplar) vẫn truy lại được run nào dùng bản nào.

## Problem statement

Sắp thử nhiều phương án cho B1 (sửa exemplar, contrastive scoring, calibrate ngưỡng…). Cần cơ chế ghi lại *mỗi lần chạy dùng gì và ra số nào* để so sánh, không lẫn giữa các thay đổi.

## Decisions made (user chốt 2026-09-03)

- **D1 — Tối giản, KHÔNG Hydra/MLflow.** Đề xuất ban đầu (Hydra config-group + MLflow tracker) bị user rút gọn vì codebase nhỏ: *mỗi phương án wrap thành 1 function*, kết quả + config lưu file thường. (`hydra-core`, `mlflow` đã lỡ cài vào env trước khi chốt — không dùng, có thể uninstall.)
- **D2 — Registry function**: `src/05_experiments/run_experiment.py` chứa `APPROACHES = {tên: (function, mô tả)}`. Mỗi function tự chứa config của nó và trả `(config_dict, metrics_dict)`. Thử phương án mới = viết thêm 1 function + đăng ký, không sửa code lõi (tái dùng `classify.py` qua importlib).
- **D3 — Mỗi run một folder** `src/05_experiments/runs/<YYYY-MM-DD_HH-MM-SS>_<approach>/`:
  - `config.yaml` — config đã resolve + hash 2 file data + git sha/dirty + version encoder
  - `metrics.json` — accuracy, per-label P/R/F1, confusion, phân bố 3 vùng, danh sách dòng sai
  - `report.txt` — bản in người đọc được (đúng output `evaluate_golden`)
  - `code_diff.patch` — chỉ khi working tree dirty: `git diff HEAD` để tái lập đúng code lúc chạy (thay cho snapshot kiểu Guild AI)
  - `runs/index.md` — bảng append 1 dòng/run (ts, approach, acc, macro-F1, 3 vùng, note) để so nhanh
- **D5 (2026-09-03) — thử MỘT ngưỡng cố định 0.50, rồi REVERT về 0.60/0.45 trong ngày.** Run `exemplar_v2_hf_t50` cho thấy gộp về high=low=0.50 thực chất **nâng cửa abstain 0.45→0.50**: dải confidence 0.45–0.50 bị vứt trong khi nó là đất tốt của `new_feature` (13 đúng / 4 sai = 76% chính xác) ⇒ recall new_feature tụt 0.57→0.37. PM quyết quay về **0.60/0.45** (routing 3 vùng §4.3: gán nhãn từ 0.45, dưới 0.60 kèm cờ ⚠). Run t50 giữ lại làm hồ sơ đối chiếu; bài học ghi nhận cho bước calibrate: `new_feature` cần low-threshold riêng thấp hơn các nhãn khác (per-intent threshold §4.5). Mốc so sánh cho các phương án sau = `exemplar_v2_hf` (strict 49.0%, answered 57.1%).
- **D4 — `runs/` commit vào git** (nó là hồ sơ thí nghiệm, không phải build artifact). Guild AI bị loại (ngừng maintain, rủi ro Python 3.12), W&B bị loại (cloud — feedback là dữ liệu nội bộ ngân hàng).

## Implementation approach

1. `src/05_experiments/run_experiment.py` — registry + runner (capture stdout của eval làm report; yaml/json thuần).
2. Phương án đăng ký ban đầu: `exemplar_cosine_hf` (baseline hiện tại — HF encoder, ngưỡng 0.60/0.45), `exemplar_cosine_databricks` (cùng model, encoder production — chạy khi có auth).
3. Chạy baseline ghi run đầu tiên (tái lập 42.2% từ cache, không tốn API).
4. CHANGELOG.

## Non-goals

- KHÔNG sửa exemplar/threshold trong lần này (đó là các run kế tiếp, mỗi cái một function mới).
- KHÔNG đụng `classify.py` ngoài việc gọi lại nó.
