---
author: klinh2212112@gmail.com
date: 2026-08-25
status: done
agents: inference.classify
summary: Sinh bộ dữ liệu feedback giả lập thay cho Feedback datalake (chưa có quyền truy cập) để chạy được P1.A step 0-3.
---

# Sample feedback fixture — dữ liệu giả lập thay Feedback datalake

## Architecture reference

- **Module:** *không có module mới.* Đây là **dev fixture đứng thay SOURCE LAYER → "Feedback datalake"** (§2 Input), tức là input của `inference.classify` (B1). Không có dòng code nào trong `src/afr/` ở deliverable này.
- **Sections:** `docs/architecture.md` §2 Overview → Input (bảng nguồn *Feedback datalake*: `feedback_id`, `user_email`, `content`, `agent`, `created_at`), §2 Assumptions A4 (≥500 mẫu lịch sử) và A5 (PII), §4.5 Data layer, §6.1 R1 (`unclassified_rate`).
- **Impl doc:** `docs/method-offline-intent-analysis.md` §2 (Data audit / Preprocess), §4 (Cluster / noise rate).
- **Data contract:** schema của nguồn *Feedback datalake* trong §2. Fixture giữ **đúng tên trường** của nguồn thật; không thêm/bớt trường nào vào contract.

## Problem statement

Phase 1 (P1.A) mở đầu bằng Step 0 — data audit trên `<feedback_datalake>` — và mọi bước sau (embed → cluster → LLM merge → chọn exemplar → calibrate) đều ăn từ bảng đó. Hiện **chưa có quyền truy cập bảng feedback thật**, nên toàn bộ P1.A bị chặn ngay từ dòng SQL đầu tiên.

Cần một bộ dữ liệu giả lập đủ giống thật để:
1. Viết và chạy thử được notebook 00–03 (audit, embed, cluster, merge) mà không phải chờ quyền.
2. Có sẵn code path đọc đúng schema, để khi có quyền chỉ đổi nguồn đọc, không đổi logic.

## Requirements

| # | Yêu cầu | Vì sao |
|---|---|---|
| F1 | Có 3 trường user yêu cầu: email người gửi, agent app, nội dung feedback | Yêu cầu trực tiếp |
| F2 | Tên trường **khớp §2 Input**: `feedback_id`, `user_email`, `agent`, `content`, `created_at` | Rule 7 — data contract là ràng buộc cứng. `feedback_id` còn là idempotency key (§4.5), `created_at` cần cho anti-join + O6 |
| F3 | ≥ 500 dòng "sạch" | Kiểm chứng A4 → quyết định HDBSCAN path hay Direct-LLM path (Step 0) |
| F4 | Trộn VI/EN, có cả câu lẫn hai thứ tiếng trong một feedback | Step 0 đo tỉ lệ VI/EN để xác nhận cần embedding đa ngôn ngữ |
| F5 | Có dòng rác < 10 ký tự và dòng lạc đề | Step 1 lọc `length(trim(content)) < 10`; dòng lạc đề tạo ra dân số noise cho Step 3 |
| F6 | Có bản trùng lặp chính xác | Step 0 đo tỉ lệ trùng, Step 1 dedup exact |
| F7 | Phân bố theo `agent` lệch, có agent ra sau với ít dữ liệu | Mô phỏng R1: agent mới = nguồn `unclassified` chính |
| F8 | Deterministic (seed cố định) | Chạy lại notebook nhiều vòng dò tham số cluster mà dữ liệu không đổi |
| F9 | Không chứa PII thật | Mọi email/tên đều sinh máy; tránh mọi ràng buộc của A5 lên fixture |

## Decisions made

| # | Quyết định | Lý do / trade-off |
|---|---|---|
| D1 | Fixture nằm ở `data/sample/`, generator ở `scripts/`, **không** nằm trong `src/afr/` | `src/afr/` chỉ chứa module production trong bảng §3. Fixture là công cụ dev, sẽ bị xóa khi có quyền vào bảng thật. Đặt vào `src/afr/` là tạo module ngoài kiến trúc (vi phạm rule 2) |
| D2 | Định dạng chính là **JSONL**, kèm bản CSV để PM/PO mở bằng Excel | Feedback nhiều dòng, dấu phẩy, emoji — JSONL không phải escape gì. CSV chỉ là bản tiện đọc, không phải nguồn sự thật |
| D3 | File dữ liệu chính **không có cột nhãn intent** | Bảng thật không có nhãn. Có cột nhãn trong cùng file thì sớm muộn có người join nhầm vào lúc cluster và tự đánh lừa mình |
| D4 | Nhãn nhóm ẩn (`latent_theme`) xuất ra **file sidecar riêng** `feedback_sample_labels.jsonl` | Dùng để sanity-check chất lượng clustering lúc dev (cụm HDBSCAN có trùng nhóm sinh không). **Không** được dùng thay cho 150–200 nhãn tay ở Step 7 — nhãn sinh máy thì calibration đo chính cái generator, không đo dữ liệu thật |
| D5 | 12 nhóm chủ đề ẩn + 1 nhóm noise, tỉ trọng noise ~12% | Step 3 chờ số cụm 15–40 và noise < 35%. 12 nhóm cho HDBSCAN over-segment ra khoảng đó; noise 12% là mức lạc quan có chủ ý, xem "Rủi ro" bên dưới |
| D6 | Danh sách agent là **placeholder cần PM xác nhận** | Chỉ chắc chắn 3 cái xuất hiện trong `template/`: TÀI Chat, The Translator, The Powerpoint-er. Số còn lại do tôi đặt để có phân bố agent |

## Implementation approach

```
scripts/gen_sample_feedback.py       # generator, deterministic theo --seed
data/sample/
├── feedback_sample.jsonl            # 650 dòng, schema đúng §2 Input  ← nguồn chính
├── feedback_sample.csv              # cùng dữ liệu, để mở bằng Excel
└── feedback_sample_labels.jsonl     # sidecar: feedback_id → latent_theme (chỉ dùng lúc dev)
```

Schema mỗi dòng `feedback_sample.jsonl`:

```json
{
  "feedback_id": "fb_00001",
  "user_email": "phuongntt2@techcombank.com.vn",
  "agent": "The Powerpoint-er",
  "content": "Chưa chuyển thể data trong Excel thành chart trong PPT được.",
  "created_at": "2026-05-14T09:23:00"
}
```

Cách sinh:
1. 12 phrase bank theo chủ đề (mỗi bank có template VI, EN và vài template trộn VI/EN), điền slot `feature` / `fmt` / `agent`.
2. Bốc chủ đề theo trọng số lệch (long tail), bốc agent theo phân bố lệch riêng của từng chủ đề.
3. `user_email` từ pool ~120 user sinh máy theo pattern Techcombank, có vài power user gửi nhiều lần.
4. `created_at` rải trong 6 tháng tính ngược từ 2026-08-24, lệch về giờ hành chính và ngày trong tuần.
5. Chèn ~3% bản trùng lặp chính xác; dòng rác ngắn được bốc từ nhóm noise nên trùng nhau tự nhiên.
6. Đánh lại `feedback_id` sau khi sắp theo `created_at` để id tăng dần theo thời gian như bảng thật.

Chạy: `python scripts/gen_sample_feedback.py` (mặc định 650 dòng, seed 20260825).

Kết quả với tham số mặc định (generator tự in bản rút gọn của câu SQL Step 0):

| Chỉ số | Giá trị |
|---|---|
| Tổng dòng | 650 |
| User phân biệt | 112 |
| Dòng < 10 ký tự (Step 1 lọc bỏ) | 45 |
| Bản trùng chính xác | 65 (~10%, chủ yếu là dòng rác lặp) |
| **Dòng sạch sau Step 1** | **570 → thỏa F3, đi nhánh HDBSCAN** |
| Nhóm noise ẩn | 10.5% |
| Cửa sổ thời gian | 2026-02-26 → 2026-08-24 |

650 dòng thô, không phải 520: cần dư ra để sau khi lọc dòng ngắn và dedup vẫn còn trên 500.

## Rủi ro phải nói thẳng

- **Fixture không kiểm chứng được A4.** A4 hỏi *dữ liệu lịch sử thật* có ≥500 mẫu không. Dữ liệu tôi sinh ra luôn có đủ số lượng theo tham số, nên Step 0 chạy trên fixture chỉ kiểm chứng **code của query**, không kiểm chứng giả định. Step 0 phải chạy lại trên bảng thật.
- **Noise rate của fixture là số vô nghĩa với R1.** Impl doc §2 Step 3 nói noise rate offline là *ước lượng ngày-0 cho `unclassified_rate`*. Trên fixture, noise rate chính là tham số tôi đặt (~12%), không phải tính chất của dữ liệu. **Không được** dùng nó để chốt ngưỡng hành động với PM (mục §5.1 "Cần chốt").
- **Không được để fixture đi tiếp vào Step 6/7.** Exemplar phải là feedback thật (R3, tiêu chí P1-2: mỗi exemplar truy được về `feedback_id` thật). Catalog build từ dữ liệu sinh máy sẽ trượt qua test nhưng vô dụng ở production.

⇒ Fixture chỉ phục vụ **viết và chạy thử code** của Step 0–4. Cửa chặn review gate (Step 5) và mọi thứ sau nó vẫn chờ dữ liệu thật.

## Next steps

1. Xác nhận danh sách agent với PM (D6) — sửa `AGENTS` trong generator nếu lệch.
2. Notebook `00_data_audit.py` chạy được câu SQL/pandas Step 0 trên fixture.
3. Xin quyền truy cập bảng feedback thật — đây vẫn là đường găng của cả Phase 1.
