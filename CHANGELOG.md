# Changelog

Mọi thay đổi logic đáng kể của dự án được ghi ở đây.
Định dạng theo [Keep a Changelog](https://keepachangelog.com/), version theo [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `[classify]` Generator dữ liệu feedback giả lập `scripts/gen_sample_feedback.py` + fixture
  `data/sample/feedback_sample.{jsonl,csv}` (650 dòng) và sidecar nhãn nhóm ẩn
  `data/sample/feedback_sample_labels.jsonl`. Đứng thay nguồn *Feedback datalake*
  (`docs/architecture.md` §2 Input) khi chưa có quyền truy cập bảng thật, để chạy được
  Step 0–4 của P1.A. Deterministic theo seed; schema khớp data contract
  (`feedback_id`, `user_email`, `agent`, `content`, `created_at`).
  Kế hoạch: `docs/2026-08-25/sample-feedback-fixture/plan.md`.
- `[all]` Khởi tạo `CHANGELOG.md`.
