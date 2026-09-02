# Changelog

Mọi thay đổi logic đáng kể của dự án được ghi ở đây.
Định dạng theo [Keep a Changelog](https://keepachangelog.com/), version theo [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `[inference.deliver]` `[inference.draft]` **B3 deliver — `src/03_inference/build_email.py` + bank câu mẫu `src/03_inference/email_templates.yaml`: biến `(label, flag, best_label, solved, referenced)` sau B1+B2 thành file `.eml` song ngữ VI/EN và ghi vào `REVIEW_DIR/<nhãn>/<feedback_id>.eml` + `manifest.csv`.** `scenario` là khoá chọn template chứ không phải `label` (§4.6 đã bỏ `email_template_id` vì lý do này): `bug`/`new_feature` + `solved=True` ⇒ `how_to_answer` (template `we_resolved`, box xanh = quote guideline **nguyên văn** + dòng citation `source_ref` đọc từ sidecar `.debug.jsonl` của B2); `solved=False` ⇒ `we_listen`, **không claim** (impl §3.2); `praise` ⇒ `thank_you`; `complain` ⇒ `apology`; không suy được nhãn ⇒ `neutral_ack`. `flag=unclassified` ⇒ **nội dung dựng theo `best_label`, file vẫn vào folder `unclassified`** (§4.3) — `pick_scenario()` và `pick_folder()` tách rời vì đây là hai quyết định độc lập. `known_gap` có trong YAML nhưng **chưa route tới được** (bước 2 backlog của §4.4 chưa hiện thực). Box đỏ chứa feedback **nguyên văn**, giống nhau ở cả nửa VI và EN (không dịch lời user, không tóm tắt bằng LLM — bản này KHÔNG gọi LLM). Render theo `template/skill_create_email.md`: `X-Unsent: 1`, logo `src/assets/tai_logo.png` nhúng MIME `cid:tai_logo`, màu `#e53e3e`/`#e8f5e9`, UTF-8 thẳng thay HTML entity (impl §3.4); thêm **block INTERNAL** (label/flag/confidence/scenario/source_ref + cảnh báo low_confidence / unclassified / no_source) để PM đọc rồi xoá trước khi gửi (§4.5). **Lint style** (impl §3.3: em-dash, emoji, casing `TÀI Studio`, `cid:`) chỉ quét phần copy do template sinh ra — bỏ qua block INTERNAL và 2 box verbatim, vì lời user và quote tài liệu (`User Guide — TÀI`) không được sửa. Idempotency = tên file `<feedback_id>.eml` (`--overwrite` để ép), `manifest.csv` giữ đúng tên cột `feedback_processing` §4.6 để migrate Delta sau. Toàn bộ câu chữ nằm trong YAML cho admin sửa, **1 message/kịch bản**, VI và EN cùng nội dung (bỏ picker-theo-hash 4 biến thể của `reply_samples.yaml` để output deterministic). **Runner `src/03_inference/run_pipeline.py`** = Job B chạy local: B1 → B2 → B3, mỗi chặng ghi artifact trước khi chặng sau chạy (retry từng chặng, §4.2); `--skip-b2` chạy được không cần LLM. Fixture `data/sample/feedback_e2e_demo.csv` (25 dòng = 5 case × 5 nhãn, chọn từ gold, ưu tiên dòng B1 dự đoán đúng để demo phủ đủ 5 folder). **Chạy thật e2e** (`out/pipeline/e2e_demo/`): 25 feedback → 25 `.eml`, phân bố 5/5/5/5/5, 0 lỗi lint; B2 `solved=True` 1/10 ⇒ đúng 1 email `we_resolved` có citation `docx:powerpointer@2026-05-28#Step 4: Slide Edition`, 5 email trong `unclassified/` dựng theo `best_label` (4 `we_listen` + 1 `apology`). Test `src/04_tests/test_build_email.py` (28 PASS: bảng scenario, folder độc lập template, `solved=False` không có box xanh, `.eml` parse ngược đủ header + part `image/png` `Content-ID: <tai_logo>`, placeholder thiếu ⇒ raise, lint bắt/bỏ qua đúng vùng, idempotency, contract manifest). Plan: `docs/2026-09-03/build-email-eml/plan.md`.

- `[inference.draft]` `[ingest-sync]` **B2 bước 1 chuỗi §4.4 — `src/03_inference/resolve_guideline.py`: batch feedback `bug`/`new_feature` sau B1, đối chiếu guideline theo `agent`, ra CSV = input + đúng 2 cột `solved` (bool) + `referenced` (quote nguyên văn).** Gom theo `agent` (§4.2), lô 10 feedback/call, nạp NGUYÊN VĂN page (không chunk/embed — nguyên tắc v4.0); LLM dev = **qwen3-8b qua LM Studio** (OpenAI-compatible, `chat_json` inject được để test offline; Haiku 4.5 §5 là target prod). **Cổng an toàn D6** (hiện thực "chỉ tin khoá tra ngược được" §4.4): `solved=True` chỉ khi quote LLM trả tìm được **nguyên văn** trong page của agent; `source_ref = page_id@version#heading` do CODE dựng từ vị trí quote, ghi ở sidecar `<out>.debug.jsonl` (kèm match_type `how_to|limitation|none`, reason, gate). Gate v2 **anchor**: quote lệch nhẹ ("...", gộp heading, bỏ bullet) ⇒ lấy đoạn chung dài nhất ≥ 40 ký tự và trả về **dòng tài liệu thật** (vẫn verbatim); quote bịa vẫn bị chặn. **Verify pass** (lượt 2 hỏi lại từng dòng True). Loader offline **`src/02_knowledge/guideline_docx.py`** (Job A): 13 docx `data/guidelines/` → `UserguidePages` (contract `userguide_page` §4.6, `page_id=docx:<slug>`, `version` = "Last updated" hoặc hash), giữ heading + bảng; map viết tay `tai` → Super Agent + overview + **GenUI** + Office 365, `tai-studio` → overview + GenUI, `the-canvas-designer` không có ⇒ luôn False. **Gold mới `data/golden/feedback_gold_solved.csv`** (127 dòng bug/new_feature, cột `solved/match_type/referenced/rationale`): 2 labeler độc lập (`data/golden/solved_labelers/`, kappa 0.89) + adjudication 9 dòng trong `scripts/make_feedback_gold_solved.py` (deterministic; mọi `referenced` được kiểm nguyên văn). Runner `src/05_experiments/run_resolve_experiment.py` + hồ sơ `runs_resolve/` (11 approach đăng ký, 8 đã chạy). **Kết quả (gold 12 dương ⇒ ±8 điểm/dòng)**: baseline no-think F1 0.25 → evidence-first + think 0.50 → + anchor gate **0.62** (P 0.57) → + verify **P 1.00 / R 0.42 / F1 0.59**. Ba lần thử sau mốc 0.62 không vượt ⇒ dừng theo luật PM; **chốt cấu hình có verify** (precision 1.00, 0 FP) làm mặc định CLI vì FP = email nói "đã có" về thứ chưa có. **Mục tiêu F1 ≥ 0.70 chưa đạt.** Phát hiện kỹ thuật: `response_format=json_schema` làm LM Studio bỏ reasoning Qwen3 (think phải bỏ schema, tự parse sau `</think>`); verify pass đang hạ oan 3 TP với reason khẳng định nhưng `confirmed=false` — đòn bẩy kế tiếp. ⚠️ **Không lặp lại tuyệt đối**: chạy lại cùng cấu hình chốt trên cùng 127 dòng ra 4 TP/2 FP (P 0.67) so với 5/0 ở run thí nghiệm — think-mode không ép schema, temperature 0 vẫn dao động; precision 1.00 là số một run, cần đo ≥3 lần (và fix seed/no-think+schema cho R8) trước khi tin. Test offline `src/04_tests/test_resolve_guideline.py` (18 PASS: loader 13 page/map agent, gate strict/anchor/bịa, batch align, verify demote, LLM lỗi không claim, contract CSV output). Plan + Results: `docs/2026-09-03/guideline-resolve-batch/plan.md`.

### Changed

- `[inference.deliver]` **`docs/architecture.md` §2/§4.3: folder cho nhánh `flag=unclassified` đổi tên `draft/` → `unclassified/`**, và tên 5 folder chuyển thành **config** (`src/03_inference/email_templates.yaml` khối `folders`) thay vì hằng số. `draft/` mô tả trạng thái đúng với cả 5 folder nên không phân biệt được gì; `unclassified/` nói đúng *vì sao* file nằm đó. Cập nhật architecture TRƯỚC khi code theo rule #3.6 của `CLAUDE.md`.

- `[inference.classify]` **`classify.py` chuyển MẶC ĐỊNH sang cấu hình tốt nhất đã đo (contrastive λ=0.3).** Trước đó code lõi vẫn chạy đường positive-only (49.0%) dù best approach là contrastive (51.6%) — negative exemplar chỉ dùng khi truyền tay, và nhánh CLI classify một câu thậm chí **không build negative index**. Nay: hằng `DEFAULT_CONTRASTIVE_LAMBDA = 0.3`; `evaluate_golden(contrastive_lambda=...)` mặc định bật; CLI cả hai nhánh (`--eval` và classify câu lẻ) đi đường contrastive, thêm cờ `--no-contrastive` (về baseline) và `--lambda X`; docstring viết lại (v2 10 mẫu/nhãn + negative + ghi chú instruct prefix đã đo âm ⇒ không bật). **Bảo toàn hồ sơ thí nghiệm**: 5 approach lịch sử trong `run_experiment.py` ghim `contrastive_lambda=None` tường minh — chạy lại `exemplar_v2_hf` cho đúng 49.0%/0.48/42-124-26 như run gốc. `exemplar_cosine_databricks` đổi thành **`best_databricks`** (cấu hình best trên encoder production, chờ auth — đây mới là run chốt số thật; số HF chỉ là chỉ báo dev theo R2). Verify: CLI mặc định 51.6%, `--no-contrastive` 49.0%, classify câu lẻ đúng 4/4 nhãn; 22 test PASS. ⚠️ Lưu ý phát sinh khi verify: input tiếng Việt **không dấu** ("app bao loi khong dung duoc") bị match sai hoàn toàn (ra `new_feature` thay vì `bug`) — exemplar và gold đều có dấu; cần đánh giá riêng nếu feedback thật có dòng không dấu.

- `[all]` **`docs/architecture.md` v3.3 → v4.0 — Lakebase → classify 5 nhãn → knowledge 3 nguồn qua MCP → `.eml` local (user chốt 2026-09-02).** ⚠️ **BREAKING data contract** (§4.6), chưa migrate code. Bảy thay đổi mức module: (1) **nguồn feedback Delta datalake → Lakebase** (Postgres, đọc SQL lát cắt `WHERE created_at::date = D-1`) ⇒ idempotency vắt qua hai hệ (rủi ro mới R8). (2) **Taxonomy → 5 nhãn đã chốt** `bug`/`new_feature`/`praise`/`complain`/`unclassified`; bỏ `how_to` khỏi B1 — hướng dẫn cách dùng nay là *một nhánh kết quả của B2*, không phải một nhãn (theo `docs/2026-08-31/intent-knowledge-coupling/design.md`). (3) **Knowledge 2 → 3 nguồn, tất cả qua MCP-Atlassian**: guideline theo `agent` · **changelog (mới)** · backlog — thêm bảng `changelog_ref`. (4) **§4.4 MỚI — chuỗi phân giải có thứ tự** `guideline+changelog → backlog → we_listen`: tính năng đã tồn tại ⇒ hướng dẫn cách dùng; chưa có nhưng trong backlog ⇒ "đã ghi nhận, đang phát triển/xử lý"; cả hai miss ⇒ ghi nhận chung. Lý do thứ tự: nói "đang phát triển" về tính năng ĐÃ CÓ là kiểu sai đắt hơn hẳn. Cổng an toàn: chỉ coi là khớp khi `source_ref` (`page_id@version` | `jira_key`) **phân giải ngược được trong snapshot** — LLM echo nội dung không được tin. (5) **Delivery: Microsoft Graph/Outlook → file `.eml` trong folder local** (`REVIEW_DIR/<nhãn>/<feedback_id>.eml`, `unclassified` → `draft/` với template theo nhãn score cao nhất); `.eml` từ *phương án suy giảm* lên **đường chính** — không cần Azure app registration, một cơ chế auth duy nhất (Databricks). (6) **Gỡ Job C `outcome-sync` + objective outcome + objective leak-detection**; số job **3 → 2**. Đây là **mất mát thật**, ghi thẳng ở R4 (không còn cơ chế phát hiện rò rỉ block INTERNAL — đề xuất tách sidecar `<id>.internal.md`, **chờ PM chốt trước khi code B3**) và R5 (hệ thống chạy mù về chất lượng — đề xuất quy ước thủ công `_sent/`/`_rejected/`). (7) **Nhịp batch `n-1`**, nhánh `bug`/`new_feature` gom **theo `agent`** ⇒ context guideline từ `O(số feedback)` về `O(số agent)` (riêng `the-powerpoint-er` gánh 74/192 fb trong tập mẫu). Data contract đổi: `intent_id → label`, `exemplar_vectors → sample_vectors`, `draft_ref → eml_path`, thêm `best_label`/`agent`/`scenario`/`source_ref`/`embedding_model_name`, **bỏ `outcome`/`edit_distance`/`outcome_at`**, bỏ `backlog_ref.embedding`, thêm bảng `changelog_ref`. Rủi ro mới: R8 (idempotency hai hệ), R9 (ngân sách token khi nạp cả 3 nguồn — đo `prompt_tokens`, cảnh báo ở 60% context window). Code `src/03_inference` (`graph_client.py`, `outlook_mac.py`, `deliver.py`, `respond.py`, `pipeline.py`) **chưa migrate** — Graph trở thành di sản ngoài kiến trúc. Plan: `docs/2026-09-02/architecture-v4-local-eml-mcp/plan.md`.

### Removed

- `[ingest-sync]` **Xóa code chết `src/02_knowledge/scholar_test.py` (đường Scholar managed-RAG v3.0).** Không file nào `import scholar_test`; v3.1 (whole-page routing `agent → userguide_page`) đã thay hoàn toàn hướng Scholar/Vector Search cho userguide. Kèm: xóa toàn bộ `__pycache__/` trong `src/` (bytecode tự sinh, có `.pyc` mồ côi) + thêm `.gitignore` (`__pycache__/`, `*.pyc`, `*.pyo`) chống tái phát; sửa comment gãy `src/01_intent_classification/2_phase/step1_clustering.py:135` (trỏ file đã xóa → `mcp_atlassian_call.py`, cùng pattern truststore). Cập nhật `docs/architecture/knowledge-layer.md` bỏ box `scholar_test` khỏi component/integration diagram.

### Added

- `[inference.classify]` **Contrastive scoring với negative exemplar ở tầng inference — best mới: λ=0.3 đạt strict 51.6% / answered 59.6% (PM chốt phương pháp 2026-09-03).** `classify.py`: `classify_texts_contrastive` — `score(intent) = max_cos(positives) − λ·max_cos(negatives)`, nhãn = argmax score; **confidence routing = raw cosine POSITIVE của nhãn thắng** (không phải score đã trừ) ⇒ ngưỡng 0.60/0.45 giữ ngữ nghĩa, contrastive chỉ re-rank; encoder giữ nguyên (không train — không đụng R2/§5). Negative = **hard negative theo cặp hay nhầm**, file mới `data/sample/exemplars/intent_exemplar_negatives.csv` (17 dòng sinh mới, `label` = intent bị trừ điểm: `complain`←khuôn bug+feature 6, `new_feature`←khuôn bug khẩu ngữ 4, `praise`←khuôn bug ngắn/misfire 4, `bug`←khuôn chê chất lượng 3) — hiện thực hoá cột "Không phải nhãn này khi" của `intent_explain.md` đúng cách (tách khỏi index dương); leakage guard mở rộng phủ file negative. Kết quả (nền v2, 0.60/0.45): **λ=0.3: 49.0→51.6 strict, 57.1→59.6 answered, macro-F1 0.48→0.51** — `bug→new_feature` 16→12, bug recall 0.39→0.46, new_feature precision 0.64→0.71; λ=0.5 kém hơn (50.5%) ⇒ trừ quá tay có hại, chốt λ=0.3. CHƯA giải được: `bug→complain` vẫn 16, complain precision 0.21 — cần negative sát hơn hoặc λ per-intent (bước sau). `evaluate_golden(contrastive_lambda=...)`; 2 run mới trong `runs/`; test 22 PASS (thêm loader negative, toy lật nhãn, λ=0≡plain). Negative CHƯA vào catalog production — muốn productionize phải sửa contract `intent_catalog` §4.5 trước (rule 3.6). Plan: `docs/2026-09-03/contrastive-negative-scoring/plan.md`.

- `[inference.classify]` **Thử MỘT ngưỡng cố định 0.50 rồi REVERT về 0.60/0.45 trong ngày (PM, 2026-09-03).** Run `exemplar_v2_hf_t50` (v2, high=low=0.50): coverage 69.8%, acc-khi-trả-lời 58.0%, strict 43.2% — phân tích cho thấy gộp một ngưỡng thực chất **nâng cửa abstain 0.45→0.50** (ranh giới gán nhãn là ngưỡng LOW; high chỉ quyết định cờ ⚠), vứt đúng dải điểm tốt của `new_feature` (dải 0.45–0.50: 13 đúng/4 sai = 76% chính xác) ⇒ recall new_feature tụt 0.57→0.37. Quay về **0.60/0.45** (gán nhãn từ 0.45, vùng 0.45–0.60 kèm `low_confidence`); run t50 giữ trong `runs/` làm hồ sơ đối chiếu. Bài học cho bước calibrate: `new_feature` cần low-threshold riêng thấp hơn ⇒ ủng hộ per-intent threshold đúng thiết kế `intent_catalog` §4.5. Mốc so sánh cho các phương án sau = `exemplar_v2_hf` (strict 49.0%, answered 57.1%). Plan: `docs/2026-09-03/experiment-tracking-lite/plan.md` D5.

- `[inference.classify]` **Exemplar v2 + instruct-prefix thử nghiệm + metric 3 tầng — strict accuracy 42.2% → 49.0% (PM chốt 3 việc b/c/d, 2026-09-03).** (b) `intent_exemplars.csv` v2: `complain` viết lại toàn bộ 10 câu chê chất lượng output CỤ THỂ không chứa động từ malfunction ("slide làm ra xấu", "dịch tệ quá", "tóm tắt sơ sài") đúng ví dụ `intent_explain.md`; 3 nhãn kia giữ 5 câu v1 + 5 câu **register khẩu ngữ** ("ko chạy dc", "vô ko nổi", "quá đã") vá domain gap văn phong với gold; 10 mẫu/nhãn × 4 (test contract nới 5→5–15; leakage guard vẫn PASS). Kết quả: bug→complain 28→16 dòng, bug precision 0.64→0.92, new_feature recall (answered) 0.29→0.67; **lộ confusion mới bug→new_feature (16 dòng)** do exemplar khẩu ngữ "chưa xài dc" hút "ko sử dụng được". (c) `classify.py` thêm `query_instruction` — prefix `Instruct: ...\nQuery:` CHỈ phía query (khuôn asymmetric Qwen3, ghép tầng text nên dùng được mọi encoder): đo được **−1.6pp so với v2 ⇒ kết quả ÂM, giữ no-prefix** (tiện thể giữ parity với serving embed thô). (d) `evaluate_golden` tách 3 tầng: strict 5-nhãn (nối lịch sử) · `answered` (confusion 4×4 + P/R/F1 chỉ trên dòng model trả lời và gold thật — acc 57.1% ở v2) · `abstention` (caught 10/29, false_accept 19, false_abstain 16) · **`coverage_curve`** quét ngưỡng 0.30→0.75: phẳng ~58% tới t=0.50 rồi 63.7%@cov47% (t=0.55), 74.4%@cov22% (t=0.60) ⇒ chất lượng xếp hạng là trần, ngưỡng chỉ đánh đổi coverage. 2 run mới trong `runs/index.md` (`exemplar_v2_hf` 49.0%, `exemplar_v2_instruct_hf` 47.4%); test 19 PASS. Plan: `docs/2026-09-03/exemplar-v2-instruct-metrics/plan.md`.

- `[inference.classify]` **Experiment tracking tối giản `src/05_experiments/run_experiment.py` — mỗi phương án B1 là 1 function, mỗi run lưu trọn hồ sơ để review lại (PM chốt 2026-09-03, thay đề xuất Hydra+MLflow).** Registry `APPROACHES = {tên: (function, mô tả)}`; function tự chứa config, trả `(config, metrics)`; thử phương án mới = thêm 1 function, không sửa code lõi (tái dùng `classify.py`). Mỗi run ghi `runs/<ts>_<approach>/`: `config.yaml` (config + **content-hash của golden & exemplar CSV** — data đổi giữa các run vẫn truy lại được + git sha/dirty + version), `metrics.json` (đủ confusion + danh sách dòng sai), `report.txt`, `code_diff.patch` (`git diff HEAD` khi working tree dirty — thay snapshot kiểu Guild AI), và append 1 dòng vào `runs/index.md` (accuracy, macro-F1, phân bố 3 vùng, note) để so nhanh; `runs/` commit vào git như hồ sơ thí nghiệm. Guild AI loại (ngừng maintain, rủi ro Py3.12), W&B loại (cloud — feedback là dữ liệu nội bộ); `hydra-core`/`mlflow` đã lỡ cài trước khi chốt đơn giản hoá — KHÔNG dùng. Đã ghi run đầu: `exemplar_cosine_hf` baseline 42.2% (khớp eval lần 1). 2 phương án đăng ký sẵn: `exemplar_cosine_hf`, `exemplar_cosine_databricks` (chờ auth). Plan: `docs/2026-09-03/experiment-tracking-lite/plan.md`.

- `[inference.classify]` **Fallback encoder HF local + eval lần 1 trên golden: accuracy 42.2% — KHÔNG ĐẠT, đã chẩn đoán nguyên nhân.** `classify.py` thêm `hf_encoder()` (`Qwen/Qwen3-Embedding-0.6B` qua sentence-transformers — cùng base với endpoint §5, tiền lệ v3.3 LM Studio↔Databricks cùng space) + `resolve_encoder(auto|databricks|hf)`: auto probe client Databricks fail-fast (không tốn API call), hỏng ⇒ fallback HF kèm cảnh báo R2; **cache riêng** `src/03_inference/out/hf_embed_cache.json` (prefix `hf:`) — không bao giờ trộn vector 2 encoder trong một phép so cosine; CLI thêm `--hf`/`--databricks`. HF CHỈ cho dev/eval — production B1 vẫn bắt buộc Model Serving. **Eval lần 1** (HF, ngưỡng mặc định 0.60/0.45): 81/192 = 42.2%; per-label recall `bug` 0.29 / `new_feature` 0.29 / `praise` 0.80 / `complain` 0.75 (prec 0.20). Chẩn đoán: (1) exemplar `complain` khuôn "kết quả+không/chưa+tốt" HÚT 28 dòng bug ngắn ("không ra được kết quả" cosine 0.77) — embedding không tách malfunction khỏi chê chất lượng, đúng cảnh báo `intent-knowledge-coupling/design.md`; (2) 25 dòng `new_feature` rơi `unclassified` (conf 0.32–0.45) — 5 exemplar chung chung không phủ nổi độ đa dạng chủ đề; (3) ngưỡng chưa calibrate (chỉ 34/192 vượt 0.60; "No"/"1" lại 0.68–0.70). Test eval giờ CHẠY THẬT qua cache HF: **18/18 PASS**, sàn `MIN_ACCURACY=0.35` (chặn hỏng hẳn, không phải mục tiêu). Deps mới: `sentence-transformers` (+torch); Databricks CLI v1.14.1 tải sẵn chờ SSO. Chi tiết + bảng metric: plan `docs/2026-09-02/intent-classify-embedding-eval/plan.md` §Results.

- `[inference.classify]` **B1 classify bằng embedding matching `src/03_inference/classify.py` + bộ test `src/04_tests/test_intent_classification.py` đo trên golden dataset.** Dựng lại B1 sau khi `src/03_inference` bị dọn: source exemplar = `data/sample/exemplars/intent_exemplars.csv` (5 mẫu/nhãn × 4 nhãn sinh mới — không leakage), confidence = **max cosine tới từng exemplar** (R3, không mean), **routing 3 vùng đúng §4.3** (`c≥0.60→ok` · `0.45≤c<0.60→low_confidence` vẫn gán nhãn · `c<0.45→unclassified` KHÔNG đoán nhãn, giữ `best_label` cho `unclassified_pool.best_intent_id`); ngưỡng mặc định CHƯA calibrate. Encoder tái dùng `embed_texts` của `step1_clustering.py` (qwen3 Databricks + cache đĩa — đúng R2 cùng không gian vector; import qua `importlib` + đăng ký `sys.modules` vì thư mục tên số), **inject được** (callable `texts→(N,dim)`) để test offline không cần mạng. CLI: `--eval` (đo trên `data/golden/feedback_gold.csv`, in accuracy/P/R/F1/confusion/phân bố 3 vùng/danh sách dòng sai) hoặc classify trực tiếp câu bất kỳ. Test 2 tầng (**15 PASS + 3 SKIP**): offline = contract exemplar (4×5, không sink, fail-loud nhãn lạ) + contract golden (192 dòng, 5 nhãn, content nguyên văn nguồn) + **leakage guard** (exemplar trùng/chứa feedback thật ⇒ fail) + routing 3 vùng/biên/max-cosine với fake encoder; eval golden = gated, `pytest.skip` khi thiếu auth Databricks. Máy dev hiện thiếu credential ⇒ eval thật chưa chạy — cache đã phủ 191/192 golden từ Phase 0, chỉ cần 1 call ~21 text trên máy có auth; sàn hồi quy `MIN_ACCURACY=0.50` đặt tạm, chốt lại sau lần eval đầu (plan §Results). Plan: `docs/2026-09-02/intent-classify-embedding-eval/plan.md`.

- `[inference.classify]` **Bộ exemplar SINH MỚI `data/sample/exemplars/intent_exemplars.csv` — source embedding-match cho B1, độc lập hoàn toàn với feedback thật (PM yêu cầu 2026-09-02).** 20 mẫu hand-authored (5/intent × 4 intent `bug`/`new_feature`/`praise`/`complain` — 4 VI + 1 EN mỗi intent) theo định nghĩa `data/golden/intent_explain.md`, chỉ mẫu DƯƠNG, viết **CHUNG CHUNG (topic-neutral)** — neo vào tín hiệu intent ("báo lỗi/treo/không chạy" · "đề xuất bổ sung/xin hỗ trợ thêm" · "cảm ơn/hữu ích" · "chưa tốt/không như mong đợi") thay vì tên tính năng/kịch bản cụ thể, vì exemplar quá cụ thể kéo cosine lệch theo chủ đề — feedback mới về tính năng khác sẽ không match dù cùng intent (PM chốt hướng chung chung 2026-09-02). Động cơ tạo bộ mới: catalog hiện hành resolve exemplar qua `supporting_feedback_ids` → trỏ vào `feedback_extracted.csv` = chính 192 dòng của bộ nhãn vàng ⇒ eval bị **leakage**; bộ này sinh hoàn toàn mới (verify 0 dòng trùng hoặc chứa nhau thực chất với nguồn) ⇒ `feedback_gold.csv` giữ nguyên vai trò holdout để calibrate ngưỡng (§6.3 bước 4). **KHÔNG có exemplar cho `unclassified`** — sink threshold-routing §4.3, `catalog.load_catalog` cũng loại khỏi index. 5 mẫu/intent (PM chốt) = đúng trần 3–5 của R3 và `DEFAULT_MAX_EXEMPLARS=5` trong `catalog.py` ⇒ dùng thẳng khi freeze catalog (Flow A §4.1), không cần bước chọn lọc; bề mặt cùng miền input production (cột `agent` chỉ ngữ cảnh — không embed). Schema `id,agent,content,label`, id `ex_<label>_<nn>` tách hẳn namespace `fb_<idx>`; file tĩnh trong git (không script — hand-authored, sửa qua PR đúng nguyên tắc catalog-as-git-artifact §5). CHƯA wire vào `classify.py`/`catalog.py` (đổi source exemplar là bước riêng theo rule 3.6); CHƯA sinh `exemplar_vectors` (embed thuộc bước freeze, phải cùng model runtime — R2). Kèm `data/sample/exemplars/README.md`. Plan: `docs/2026-09-02/inference-exemplar-samples/plan.md`.

### Changed

- `[inference.classify]` **`data/golden/feedback_gold.csv` v2 — gán tay lại TOÀN BỘ 192 dòng theo hướng dẫn mới `data/golden/intent_explain.md` (PM chốt 2026-09-02).** PM review bản v1 chỉ ra 2 lỗi hệ thống thừa kế từ rule D3 plan 2026-08-31: (1) rule "cắt cụt `…` → `unclassified`" quá tay — "There must be a clear indicator when a person is out of credits...." đã trọn ý nhưng bị regex đuôi ép về `unclassified` (đúng ra `new_feature`); (2) rule "quá ngắn → `unclassified`" bỏ qua tín hiệu thực — "lỗi" là `bug`. `scripts/make_feedback_gold_5label.py` viết lại: đọc **trực tiếp `data/sample/feedback/feedback_extracted.csv`** (content nguyên văn, thứ tự dòng giữ nguyên ⇒ `fb_<idx>` không đổi; đã verify 192/192 dòng content khớp nguồn), bảng tay `LABELS` đủ **192 entry** `idx → (label, rationale)` cho PM review từng dòng. Quy tắc mới theo `intent_explain.md`: dòng cắt cụt gán theo phần nhìn thấy khi ý đã trọn (KHÔNG suy diễn phần thiếu — 36 dòng truncated quay về nhãn thật); câu ngắn tín hiệu rõ gán theo tín hiệu ("lỗi"/"coundn't acess" → `bug`); tie-breaker theo cặp (`bug` vs `new_feature` = sai thiết kế hay muốn khác thiết kế — vd `fb_0112` chart xuất dạng ảnh đổi `bug`→`new_feature`; `new_feature` vs `complain` = có rút được dòng backlog không; vs `unclassified` = có dám soạn reply không). Phân bố mới: `new_feature` 65 / `bug` 62 / `unclassified` 29 / `praise` 20 / `complain` 16 — `unclassified` tụt 65→29 (15.1%), chỉ còn prompt-misfire (15), vô nghĩa, câu hỏi chính sách, và dòng mất phần quyết định. `data/golden/README.md` cập nhật; bộ 6-label `feedback_gold_192.csv` giữ nguyên làm tham chiếu taxonomy cũ (không còn là nguồn derive). Plan: `docs/2026-09-02/feedback-gold-5label/plan.md` §Revision v2.

### Added

- `[inference.classify]` **Nhãn vàng 5-label `data/golden/feedback_gold.csv` + `scripts/make_feedback_gold_5label.py` — bỏ `how_to`, đổi tên nhãn (user chốt 2026-09-02).** Sinh deterministic từ bộ 6-label `feedback_gold_192.csv` (KHÔNG đọc lại CSV gốc — bộ 6-label đã review; sửa nhãn thì sửa ở đó rồi chạy lại 2 script theo thứ tự). Hai phép biến đổi: (1) rename thuần `request_feature → new_feature`, `complaint → complain` — không đổi phán đoán; (2) **10 dòng `how_to` gán lại TỪNG DÒNG theo nội dung** (bảng tay `HOW_TO_RELABEL` kèm rationale): 5 → `new_feature` (`fb_0018`/`fb_0032`/`fb_0059`/`fb_0074`/`fb_0146` — câu hỏi thực chất là xin năng lực chưa có), 2 → `complain` (`fb_0007` bức xúc hạn mức, `fb_0017` "very limited"), 3 → `unclassified` (`fb_0013` hỏi thao tác file sau export, `fb_0085` hỏi chính sách ANTT, `fb_0131` nghi vấn độ tin cậy — câu hỏi cách dùng/chính sách không còn chỗ đứng ⇒ rơi về sink `unclassified_pool` §4.3). Phân bố: `unclassified` 65 / `bug` 49 / `new_feature` 43 / `praise` 19 / `complain` 16 (192 dòng, cột + thứ tự dòng + mapping `fb_<idx>` giữ nguyên). Nhất quán với chẩn đoán `intent-knowledge-coupling/design.md`: `how_to` không tách được ở B1 vì sự thật nằm trong userguide. `feedback_gold_192.csv` giữ nguyên làm bộ tham chiếu 6-label; 62 id bẩn cần loại khi train/eval vẫn áp dụng y nguyên. Lệch tên khi eval catalog cũ: `report_bug → bug`, `request_feature → new_feature`, `complaint → complain`. `data/golden/README.md` cập nhật quan hệ 3 bộ gold. Plan: `docs/2026-09-02/feedback-gold-5label/plan.md`.

- `[inference.classify]` `[inference.draft]` **Design note `docs/2026-08-31/intent-knowledge-coupling/design.md` — how_to / bug / request_feature không tách được ở B1.** Chẩn đoán: ba nhãn này khác nhau ở một **sự thật nằm trong userguide** (tính năng có tồn tại không, có chạy đúng không), không nằm trong feedback; B1 (`classify.py`) chỉ thấy chuỗi ký tự + max-cosine ⇒ **giới hạn thông tin, không phải giới hạn mô hình**. Quy mô: 97/130 dòng sạch (75%) nằm trong ba nhãn này. Bằng chứng: đối chiếu 11 dòng gold tra được trực tiếp trong `data/guidelines/` ⇒ **5 sai / 1 nghi ngờ / 5 đúng** (vd `fb_0008` gold `request_feature` nhưng Translator Limitations ghi rõ *"Upon page refresh… no longer visible"* ⇒ `how_to`; `fb_0040` gold `request_feature` nhưng có *"Regenerate from outline"* ⇒ `how_to`; `fb_0072`/`fb_0112` gold `bug` nhưng là limitation đã ghi) ⇒ **nhãn vàng hiện tại chưa đo được B1**, cần gán lại có đối chiếu tài liệu. Nêu mâu thuẫn kiến trúc: `action_type` chọn MỘT nguồn knowledge theo intent (`how_to→answer_from_kb`, `request_feature`/`report_bug`→`known_gap`) nhưng việc chọn nguồn lại phụ thuộc câu trả lời chưa có ⇒ **vòng lặp phụ thuộc**. So sánh 3 hướng: **H1** B1 gộp 4 nhãn (`capability_gap`/`praise`/`complaint`/`unclassified`) + B2 phân giải theo **chuỗi** userguide→backlog→we_listen (khuyến nghị); **H2** như H1 nhưng tách `bug_explicit`; **H3** giữ 6 nhãn + override ở B2. Audit `data/guidelines/` (13 docx, 78.590 ký tự ~25k token ⇒ cả kho vừa 1 prompt): map `agent→userguide` phải viết tay (fuzzy hỏng ở `tai` 34 fb và `tai-studio` 5 fb do dấu tiếng Việt / 2 file 1 agent), `the-canvas-designer` KHÔNG có tài liệu, tài liệu cũ hơn feedback 1–3 tháng (Powerpoint-er `2026-05-28` gánh 74/192 fb), và `data/guidelines/` chưa wire vào code nào. Bản đọc: https://claude.ai/code/artifact/a5c9575d-6f3f-4afe-a9ba-6d1d4ad4ce46 — **chưa chốt hướng, chưa viết code.**

- `[inference.classify]` **Nhãn vàng 6-label toàn tập `data/golden/feedback_gold_192.csv` + `scripts/relabel_feedback_gold.py`.** Gán lại **toàn bộ 192 dòng** của `data/sample/feedback/feedback_extracted.csv` theo taxonomy 6 label user chốt: `bug` / `request_feature` / `how_to` / `praise` / `complaint` / `unclassified` (49 / 38 / 10 / 19 / 14 / 62). Động cơ: **B1 cho kết quả kém KHÔNG phải do embedding mà do tập nhãn** — cột `category` trong CSV nguồn là lựa chọn của user trên widget (`idea` 96 / `bug` 54 / `other` 25 / `praise` 17), chỉ khớp 61% ở `bug` và 76% ở `praise`, còn `idea` (50% dữ liệu) rải khắp 6 label (vd `fb_0002` "TAI studio ko work" ghi `idea`; `fb_0152` "Chữ và icon quá nhỏ" ghi `praise`). Ranh giới chốt **theo hành động** (plan D2): `bug` = malfunction thật (error/crash/mất data/output sai hợp đồng — gồm cả dịch sót & bịa thực thể), `request_feature` = có nêu hướng cải thiện cụ thể, `complaint` = chê chất lượng chung không nêu cải thiện — vì `bug`/`request_feature` dẫn tới hai `action_type` khác nhau ở B2. CSV xuất ra **đúng 5 cột `agent,user,date,content,label`** — bê nguyên 4 cột dữ liệu từ nguồn + 1 cột nhãn; cột `category` của widget KHÔNG mang sang để không ai nhầm nó là target. Phân tầng 62 dòng `unclassified` (`truncated` 44 — bị cắt `…` lúc extract từ ảnh; `prompt_misfire` 11 — câu lệnh gõ nhầm ô feedback; `meaningless` 7) nằm trong script và chỉ **in ra màn hình** kèm danh sách 62 id cần loại ⇒ **còn 130 dòng sạch để train/eval**; 32.3% `unclassified` là artefact của tập mẫu OCR, KHÔNG phải prior cho `unclassified_rate` production (§ method §4.5). Script deterministic, không gọi LLM (bảng tay `LABELS`, PM sửa trực tiếp), tự in ma trận widget × gold và đối chiếu với bộ legacy. `data/golden/README.md` viết lại: quan hệ 2 bộ gold, nguyên tắc ranh giới, bằng chứng nhiễu. Plan: `docs/2026-08-31/feedback-gold-relabel/plan.md`.

- `[inference.classify]` **`data/golden/golden_intent.csv` (5 label) chuyển thành legacy.** Bị `feedback_gold_192.csv` thay thế; giữ lại để truy vết, không dùng làm target. Đối chiếu (chiếu `bug → complaint`): overlap 58, khớp 48, **xung đột 10** — 8/10 do quy tắc `truncated → unclassified`, chỉ 2 là bất đồng phán đoán thật (`fb_0018` `request_feature`→`how_to`, `fb_0120` "Very quickly" `unclassified`→`praise`).

- `[inference.classify]` **Ghi nhận lệch tên nhãn `report_bug` vs `bug`.** `src/01_intent_classification/out/*/catalog_a.json` dùng `report_bug`; nhãn vàng mới dùng `bug` theo yêu cầu. Khi eval catalog hiện tại phải map `report_bug → bug`; lần regen catalog kế tiếp nên đổi tên về `bug`. Chưa sửa catalog trong lần thay đổi này (thuộc Phase 0, chạy sau khi có nhãn vàng).

- `[inference.classify]` **Golden dataset `data/golden/golden_intent.csv` — kiểm chứng chất lượng classify B1.** 61 dòng nhãn tay (cột `intent` = target), phủ đủ 5 label `request_feature`/`how_to`/`praise`/`complaint`/`unclassified` (taxonomy KHÔNG có `report_bug` — bug gộp vào `complaint`). Nội dung `real` trích nguyên văn từ `feedback_extracted.csv` (id `fb_<idx>` khớp `catalog.load_feedback_index`) + 3 dòng `crafted` cho how_to canonical. Kèm `data/golden/README.md` (định nghĩa 5 label, nguyên tắc gán nhãn ranh giới complaint/request_feature/how_to, map `report_bug→complaint` khi eval). Động cơ: input how-to thật ("làm sao để vẽ diagram từ ảnh") bị B1 gán nhầm `report_bug` ⇒ cần bộ đo chất lượng có ground-truth.

- `[ingest-sync]` **`docs/architecture/knowledge-layer.md` — doc kiến trúc knowledge layer (`src/02_knowledge`).** Một file Markdown 3 view: component diagram (3 layer: orchestration `build_knowledge_layer.py` → store `userguide_store.py` → access `mcp_atlassian_call.py`), 5 sequence diagram (full flow Job A, MCP JSON-RPC round-trip, recursive userguide walk, `agent → page` routing, Jira backlog fetch), integration diagram (trust boundary Databricks/Atlassian). Nêu rõ gap: `fetch_backlog` chưa wire vào Job A; spike JSON vs prod Delta.

### Changed

- `[inference.classify]` **`data/golden/intent_explain.md` — định nghĩa nhãn viết lại theo góc nhìn user + thêm cột contrastive & tie-breaker theo cặp (user chốt 2026-09-02).** `bug` = *ý kiến của user về lỗi của app xảy ra trong quá trình sử dụng* (bỏ liệt kê kỹ thuật crash/mất data/sai hợp đồng); `new_feature` = *gợi ý về tính năng mới*, **gồm cả góp ý cải thiện tính năng đã có khi nêu được thay đổi cụ thể** ("tăng font size") ⇒ bộ gold hiện tại KHÔNG cần gán lại; `praise`/`complain`/`unclassified` giữ nguyên. Thêm cột `Không phải nhãn này khi` + mục *Ranh giới dễ nhầm* (5 tie-breaker theo CẶP nhãn, kèm ví dụ thật trong gold: `"chưa tạo dc 1 slide, mà phải tối thiểu 2 slide"` ⇒ `new_feature` chứ không phải `bug`; `"Tại sao cứ báo tôi bị hết hạn mức"` ⇒ `complain` chứ không phải `bug`) — nhập nhằng là thuộc tính của cặp nhãn, không của từng nhãn. Kèm cảnh báo phạm vi: file này là **hướng dẫn gán nhãn vàng**, B1 runtime (`classify.py`, max-cosine trên `exemplars`) KHÔNG đọc nó (grep 0 tham chiếu) ⇒ **không bê case negative vào `exemplars`** vì index coi mọi exemplar là mẫu dương. Sửa header bảng thiếu 1 cột (rows có 3 cột, header chỉ 2 ⇒ cột ghi chú không render).

- `[inference.draft]` `[inference.classify]` `[shared]` **v3.3 — Haiku 4.5 thay Sonnet làm LLM draft/knowledge chính, embedding classify từ LM Studio local về đúng Databricks Model Serving.** (1) `reply_scenarios.py`: `chat_json` gọi Haiku (`nonprod_ai.tsfai.claude-haiku-4-5-sit-tai`) qua **AI-Gateway MLflow Responses API** (`/ai-gateway/mlflow/v1/responses`; `system→instructions`, `user→input[]`, `max_tokens→max_output_tokens`, `temperature=0`) thay OpenAI `/serving-endpoints`; chữ ký `chat_json` giữ nguyên ⇒ `knowledge.py` (answer_from_kb/known_gap) + scenario generator migrate cùng lúc; tái dùng `_extract_json` (đã strip ```json fence Haiku bọc). Rẻ hơn ~3× (~$2 vs $6/tháng ở 100 fb/ngày). (2) `embedding_test.py`: `DatabricksEncoder` (mirror `LMStudioEncoder`: batch, sort theo index, L2-norm, MRL dim optional) trỏ `/ai-gateway/mlflow/v1/embeddings` model `qwen3-embedding-0-6b` (1024-dim); `LMStudioEncoder` giữ cho test offline. (3) `classify.py`: default encoder `DatabricksEncoder()` ⇒ B1 chạy được trên job/cron, bỏ phụ thuộc LM Studio local. Cùng base qwen3-0.6b ⇒ cùng không gian vector, threshold catalog giữ nguyên (guard §R2). Endpoint đã validate live (profile `tcb-agent-sit`, host `dbc-e8b4e078-ca9e`). **Lệch kiến trúc khai báo TRƯỚC ở `docs/architecture.md` §5 + CROSS-CUTTING** (Haiku promote draft, Sonnet hạ fallback; embedding kéo về đúng §5). Plan: `docs/2026-08-27/model-haiku-embedding-databricks/plan.md`.

### Added

- `[inference.deliver]` **`OutlookMacSink` — tạo draft THẲNG vào Outlook for Mac qua AppleScript (macOS, KHÔNG cần Azure).** Đường cho case KHÔNG có quyền đăng ký app Azure ⇒ Graph/MCP-qua-Graph đều tắc. `outlook_mac.py`: `osascript` set `content` = HTML (Outlook.sdef xác nhận property `content` là "HTML content of a message" ⇒ giữ nguyên email thương hiệu song ngữ + style, khác AppleScript cũ chỉ set text) + `to/cc recipient`; đọc HTML từ file tạm + truyền qua argv (an toàn injection, UTF-8); logo `cid:tai_logo` → **data-URI** (AppleScript không gắn inline theo Content-ID); block INTERNAL GIỮ trong body (PM xoá trước Send, như GraphSink). CLI `deliver.py --outlook-mac`, `pipeline.py --outlook-mac [--ack-only]`. Hạn chế: chỉ chạy trên máy có Outlook desktop đăng nhập (KHÔNG unattended/Databricks), draft vào Drafts (không route folder-category). AppleScript đã osacompile-check (rc=0). Reuse `Draft`/`DraftRef`/`_load_logo_b64` của `deliver.py`.

- `[inference.deliver]` **Đẩy draft THẲNG vào Outlook qua Graph delegated device-code (auth nhẹ, không cần secret/Access Policy).** `graph_client.py`: thêm `GraphDelegatedAuth` (msal `PublicClientApplication` + device-code: admin login 1 lần → `SerializableTokenCache` ra đĩa `~/.tai_graph_token_cache.json` [env `GRAPH_TOKEN_CACHE`, chmod 600] → lần sau `acquire_token_silent`, không login lại; `truststore.inject_into_ssl()` cho mạng công ty MITM TLS; scope delegated `Mail.ReadWrite`). `GraphClient` nhận `mailbox="me"` (ghi Drafts của chính tài khoản delegated) hoặc UPN shared mailbox → `self._root = /me | /users/{UPN}` (thay 3 path cứng), `auth` nới sang `GraphAuth | GraphDelegatedAuth` (cùng interface `.token()`, dùng lại nguyên `GraphSink`). `deliver.py`: `graph_sink_from_delegated_env()` (env `AZ_CLIENT_ID` [+ `AZ_TENANT_ID`='organizations', `SHARED_MAILBOX`='me']) + CLI `--graph-delegated` + §SETUP-DELEGATED. `pipeline.py`: `--graph-delegated [--ack-only]` đẩy batch draft (login 1 lần, cache cho phần còn lại). App-only `GraphAuth` (production/Databricks) giữ nguyên. Cần `pip install msal` + app registration public client (Allow public client flows = YES, delegated Mail.ReadWrite). Kèm `graph_setup_check.py` — tiện ích ĐỘC LẬP (không cần LM Studio/classify) verify auth: login device-code → `GET /me` → liệt kê mailFolders → `--test-draft` tạo 1 draft thật trong folder 'TAI Test'.

- `[inference.draft]` `[inference.deliver]` **Auto-reply .eml hoàn chỉnh cho 3 label không cần knowledge layer (praise / complaint / unclassified).** (1) Bank kịch bản TĨNH song ngữ `src/03_inference/reply_samples.yaml` + loader `reply_samples.py` (`load_bank` + `pick(group, key)` chọn deterministic theo `md5(nội dung feedback)` — idempotent, PM review/sửa trực tiếp; 3 nhóm `thank_you`/`apology`/`neutral_ack`, placeholder `{name}`/`{feedback_summary}`). (2) `respond.py`: `PersonalizedResponse` thêm `body_en`; 3 nhánh ack lấy copy từ bank (thay câu cứng đơn lẻ), điền `{feedback_summary}`, GIỮ `{name}` cho deliver điền. (3) `render_email.py`: nâng `render_html` lên **gold template song ngữ** khớp `template/email_temp.py` (banner `cid:tai_logo`, note "English version below", block VI + separator đỏ "ENGLISH VERSION" + block EN [chỉ render khi có `body_en`], box trích phản hồi, footer đầy đủ support/SharePoint/CC + hằng số `CC_LIST`/`SUPPORT_CONTACTS`/`SHAREPOINT_URL`); giữ nguyên block INTERNAL + `strip_internal_block`. (4) `deliver.py`: `build_draft(..., name)` điền `{name}` (VI="bạn"/EN="there" khi thiếu), CC mặc định từ `CC_LIST`; demo dùng nhánh praise qua bank; `_load_logo_b64()` trỏ asset **`src/assets/tai_logo.png`** (nhúng inline `cid:tai_logo`, fallback path `template/` cũ, thiếu ⇒ None không crash). (5) `pipeline.py`: `--eml OUT_DIR --ack-only` xuất `.eml` theo folder category qua `EmlSink`; `Feedback` + `_load_feedbacks` đọc `user_name`/`user_email` nếu CSV có. `tests_respond.py`: +4 test (praise→thank_you, complaint→apology, unclassified→neutral_ack, song ngữ, `{name}` còn placeholder, pick deterministic) — 24 PASS. Non-goal giữ nguyên: 3 label knowledge (`how_to`/`request_feature`/`report_bug`) và auto-send xử lý sau. Plan: `docs/2026-08-27/ack-reply-eml/plan.md`.

- `[inference.draft]` **Knowledge layer thống nhất 2 nguồn theo khuôn snapshot-in-memory → whole-content cho LLM → batch prompting (v3.2).** `src/03_inference/knowledge.py`: (1) `answer_from_backlog_batch(feedbacks, backlog_items, llm, batch_size)` — nạp **cả danh sách backlog** đánh số vào 1 prompt cho K feedback (`{"matches":[{"index,"backlog_ref"}]}`), tự resolve `backlog_ref → item` (không tin LLM echo field), null/missing/out-of-range ⇒ `hit=False` (ghi nhận chung, không hứa nhầm); (2) `KnowledgeSnapshot` + `build_snapshot()` — snapshot in-memory theo run (userguide pages + backlog list), fetch một lần tái dùng cho mọi feedback. `pipeline.py`: `infer_batch()` lọc feedback về nhóm cần knowledge (`answer_from_kb` + `known_gap`), gom userguide **theo `agent`** (1 call/agent) + backlog **một lô chung**, rồi `respond` per-feedback; `main()` chạy qua batch, bỏ wiring `BacklogIndex`. Phục vụ 3 intent: `how_to` (userguide), `request_feature` + `report_bug` (backlog). `tests_respond.py`: thay 4 test cosine bằng test `answer_from_backlog_batch` offline. Cập nhật `docs/architecture.md` §3/§4.2/§4.5/§5 + plan v3.1 **trước** khi code (rule 3.6). Plan: `docs/2026-08-27/knowledge-layer-batch/plan.md`.

- `[inference.draft]` **Đòn bẩy chi phí/chất lượng cho knowledge query (chưa wire vào pipeline).**
  `src/03_inference/knowledge.py`: (1) `answer_from_userguide_batch()` — gom K feedback CÙNG `agent` vào 1 call
  (page + K feedback → K `{answerable,answer}`, cap `DEFAULT_BATCH_SIZE=6`), cắt token page bị lặp do phân bố
  agent lệch; **serving-agnostic** (không phụ thuộc prompt caching Databricks); mỗi item VẪN giữ gate
  `answerable`, index thiếu ⇒ hit=False (suy giảm we_listen an toàn). (2) `BacklogIndex` thêm `verifier`/`top_k`
  — cosine lấy top-k (recall) → LLM yes/no chốt ứng viên (precision) chặn false-positive "team sẽ làm"; `verifier=None`
  giữ hành vi cũ (top-1 theo ngưỡng). `tests_respond.py`: +7 test offline (18 PASS). Đánh giá đầy đủ + đòn bẩy còn
  lại (POC prompt caching Databricks, đo page-size, model tiering, lọc heading) ở plan; wire vào `pipeline.py`
  chờ kết quả POC. Kế thừa hướng whole-page routing (`docs/2026-08-26/knowledge-retrieval-strategy/plan.md`).

- `[inference.deliver]` **B3 deliver — draft vào folder Outlook theo category (intent), trong shared mailbox
  qua Microsoft Graph (app-only).** `src/03_inference/`: `graph_client.py` (msal `ConfidentialClientApplication`
  client-credentials → bearer app-only + httpx REST: `find/ensure mailFolder`, `create_draft`; `build_message`
  nhúng **`X-Feedback-Id`** qua `singleValueExtendedProperties` PS_PUBLIC_STRINGS — khóa cứng cho outcome-sync
  R5; logo inline `cid:tai_logo` chỉ khi có asset, thiếu thì bỏ qua — B-1). `render_email.py` (PersonalizedResponse
  → HTML thương hiệu + **block INTERNAL trên cùng**, marker `TAI-INTERNAL-DO-NOT-SEND`, `strip_internal_block()`
  idempotent). `deliver.py` (**`DraftSink` Protocol** impl §6 + `GraphSink` primary + `EmlSink` fallback: folder =
  `intent_id` [unclassified → `⚠ Unclassified`], `ensure_folder` idempotent + cache phiên; EmlSink ghi `.eml`
  X-Unsent theo folder-category, **INTERNAL ra file sidecar `.internal.md`, body email SẠCH** — D3 vì nhánh .eml
  không có Job C phát hiện leak; config từ env `AZ_TENANT_ID/AZ_CLIENT_ID/AZ_CLIENT_SECRET/SHARED_MAILBOX`, secret
  KHÔNG hardcode; CLI `--dry-run`/`--eml`/`--cc`; §SETUP hướng dẫn Azure app registration + **Application Access
  Policy scope taistudio@**). `tests_delivery.py` offline 5 test PASS (payload schema + folder map + strip + EmlSink).
  Live Graph cần `pip install msal` + env + **spike ① kiểm X-Feedback-Id sống qua Send** (impl B-2, O4/O5 treo vào).
  Plan: `docs/2026-08-26/deliver-outlook-graph/plan.md`.

- `[inference]` **Module inference 2 bước — classify (B1) → respond (B2, nội dung).** `src/03_inference/`:
  `catalog.py` nạp Intent Catalog (`catalog_a.yaml`) + resolve exemplar từ `supporting_feedback_ids`
  (map `fb_<i:04d>` = row index `feedback_extracted.csv`, khớp `step1_clustering.load_feedback`), bỏ intent
  `unclassified` khỏi tập index (nó là *sink* §4.3). `classify.py` tái dùng encoder/normalize/split_clauses của
  `embedding_test.py`, embed feedback → **max cosine tới exemplar** → intent + confidence, **routing 3 vùng**
  §4.3 (`c≥high`→ok · `low≤c<high`→low_confidence · `c<low`→unclassified, KHÔNG đoán nhãn). `knowledge.py`
  bắc cầu sang `src/02_knowledge/`: `answer_from_userguide()` (Scholar `ask` — nhánh answer_from_kb) +
  `BacklogIndex.match()` (`fetch_backlog` + cosine CÓ CẤU TRÚC giữ jira_key/status — nhánh known_gap).
  `respond.py` **định tuyến theo `action_type`** (đúng bảng impl §3.2): answer_from_kb + rag hit → we_resolved
  (hướng dẫn từ userguide); answer_from_kb + 0 hit → **suy giảm we_listen, KHÔNG claim resolved** (guard R6);
  known_gap khớp backlog → "sẽ phát triển" + mốc suy từ `status`; known_gap không khớp → "đã ghi nhận, sẽ cải
  thiện TÀI Studio"; ack_only → cảm ơn; `flag=unclassified` → ack trung tính (bỏ RAG + backlog, impl §5).
  `pipeline.py` orchestrate + CLI (`--dry-run`/`--notebook`/`--out` JSONL), fetch knowledge theo action_type để
  giữ `respond()` thuần. `tests_respond.py` phủ routing offline (7 test PASS). LƯU Ý **lệch kiến trúc (spike)**:
  dùng LM Studio (embed) + Scholar/MCP (knowledge) thay stack §5 (Model Serving + Vector Search), khai báo ở
  `docs/2026-08-26/inference-classify-respond/plan.md §Lệch kiến trúc` — chưa productionize.
  Plan: `docs/2026-08-26/inference-classify-respond/plan.md`.

### Changed

- `[inference.draft][knowledge]` **Backlog match: cosine embedding → whole-set cho LLM (v3.2).** Bỏ class `BacklogIndex` (cosine top-k + LLM verify + encoder dùng chung với classify) và toàn bộ embedding cho backlog. Corpus backlog nhỏ (~chục issue) ⇒ nạp cả danh sách vào prompt để LLM đối chiếu từng feedback với một hạng mục — đối xứng userguide whole-page, bỏ calibrate ngưỡng cosine. Encoder (`databricks-qwen3-embedding`) nay **chỉ còn phục vụ B1 classify**. `backlog_ref.embedding` (§4.5) không còn sinh/dùng. Đổi lại: token/call tăng theo (số backlog × K feedback) — chấp nhận ở quy mô hiện tại, batch amortize. Thay quyết định "BacklogIndex không đổi" ở `docs/2026-08-26/knowledge-retrieval-strategy/plan.md` item 3. Plan: `docs/2026-08-27/knowledge-layer-batch/plan.md`.

- `[knowledge][inference]` **Knowledge layer chuyển từ Vector Search/Scholar sang định tuyến `agent → userguide_page` + whole-page cho LLM (kiến trúc v3.1).** Feedback đã mang cột `agent` (= tên function) và userguide phân trang theo function ⇒ B2 tra bảng `agent → page` rồi nạp **cả page** cho LLM sinh câu trả lời, **bỏ chunk/embed/index** cho userguide và toàn bộ chunk-change-detection. Change-detection về mức page `version`; **giảm R6** về mặt cấu trúc (không còn index riêng lệch nguồn). `agent` là *prior mềm*: không map được page hoặc LLM báo `answerable=False` ⇒ rơi về `we_listen`. Backlog (`known_gap`) giữ nguyên cosine có cấu trúc. Cập nhật `docs/architecture.md` §3/§4.2/§4.5/§5/§6 **trước** khi code (rule 3.6). Data contract mới: `userguide_page(agent PK, page_id, version, title, markdown, last_modified, synced_at)` (§4.5). Lý do whole-page thắng keyword/text-search: cùng chi phí maintenance nhưng LLM bắc cầu ngữ nghĩa mà BM25 không làm được trên feedback ngắn/informal/VI-EN. Plan: `docs/2026-08-26/knowledge-retrieval-strategy/plan.md`.

- `[intent-catalog]` **STEP 2 rollup về TẦNG THÔ (Tier A) do LLM TỰ SINH nhãn, thay gộp cùng-nghĩa.**
  Bỏ `merge_global` + prompt `MERGE_SYS` (gộp intent cùng nghĩa → 16–24 intent mịn). Thay bằng
  `rollup_to_buckets` + prompt `ROLLUP_SYS`: LLM **tự sinh** một bộ intent thô (ÍT, phủ rộng, mục
  tiêu ~4–8) rồi gán MỖI cụm vào đúng một intent — **KHÔNG định sẵn nhãn** (giữ khách quan, human
  review bảng `step2b` sau). LLM tự đặt `label`/`description`/`action_type` (3 enum §5). Lý do: nhãn
  mịn khiến feedback mới chỉ khác câu chữ dễ bắt sai intent; auto-reply chủ yếu bám `action_type`/
  tầng thô. **Nhãn `unclassified` tường minh** (§4.3 unclassified_pool): case không khớp KHÔNG bị ép
  vào intent — LLM được phép cho cụm vào `unclassified`, `assign_noise` cũng dồn noise-feedback không
  khớp vào đó (id lạ → unclassified). Cụm LLM bỏ sót → `unclassified` (không mất feedback). Sink
  `unclassified` **được giữ qua grounding** (`ground_filter(always_keep=...)`) dù nhỏ. **coverage tính
  RIÊNG feedback vào intent thật** (KHÔNG kể unclassified); `meta` thêm `n_unclassified`,
  `granularity = coarse_llm_generated_tier_a`.
  Plan: `docs/2026-08-26/intent-merge-centroid-gated/plan.md`.
- `[intent-catalog]` **`ROLLUP_SYS` chuyển sang gom theo KỊCH BẢN TRẢ LỜI** (trục scenario), thay vì
  gom theo chủ đề/tính năng. Category giờ = cách hệ thống sẽ trả lời, xác định bởi (a) nguồn tri thức
  cần để trả lời + (b) sắc thái: bug/feature→tra backlog (known_gap); hiểu nhầm cách dùng→userguide
  (answer_from_kb); khen→cảm ơn (ack_only); phàn nàn tiêu cực chung→xin lỗi (ack_only). Prompt
  high-level để LLM **tự phát hiện scenario** + tự đặt nhãn + tự map action_type theo nguồn tri thức;
  `unclassified` cho cụm không rơi vào kịch bản nào. Verify 191 feedback: 5 scenario + unclassified
  (bug_technical_error 77, feature_request_and_ux 67, ai_output_quality_error 15, praise 16,
  vague_negative_sentiment 7 [nhánh xin lỗi], unclassified 9), coverage 0.953. Không scenario
  answer_from_kb nào xuất hiện (dữ liệu chưa có cụm knowledge-gap rõ) — LLM không bịa.
- `[inference.draft]` **`ack_only` tách nhánh trả lời theo SẮC THÁI category** (cảm ơn vs xin lỗi) ở cả
  `respond.py` và `reply_scenarios.py`. Vì `action_type` 3-enum không đủ mịn: `praise` và
  `vague_negative_sentiment` cùng `ack_only` nhưng trả lời NGƯỢC nhau. Route giờ dò marker tiêu cực trên
  `intent_id` (slug scenario LLM đặt, helper `_is_negative_scenario`): tiêu cực → template `we_apologize`
  (xin lỗi + mời nêu chi tiết), còn lại → cảm ơn/ghi nhận. Đúng nguyên tắc "category = kịch bản trả lời"
  (route theo category, không chỉ action_type). `tests_respond.py` vẫn 7 PASS.

### Fixed

- `[inference.classify]` **`catalog.DEFAULT_CATALOG` trỏ tới thư mục không tồn tại (`20260826_092038_llm`)** ⇒ `load_catalog()`/`classify`/`pipeline` mặc định fail `FileNotFoundError`. Trỏ lại catalog 6-label hiện hành `src/01_intent_classification/out/20260826_180647_llm/catalog_a.json` (`report_bug`, `request_feature`, `how_to`, `praise`, `complaint`, `unclassified`).

### Changed

- `[intent-catalog][inference]` **Artifact JSON-only + `step2b` review thành 1 bảng phẳng.** Bỏ
  duplicate json+yaml: `write_catalog` và `write_cluster_labels` (STEP 2) chỉ ghi `.json`; `catalog.py`
  (`DEFAULT_CATALOG_YAML`→`DEFAULT_CATALOG`, đọc `catalog_a.json` bằng `json.loads`), `reply_scenarios.py`
  (đọc json, bỏ ghi yaml), `pipeline.py` help text đổi theo. `step2b_merge_review` giờ là **MỘT bảng
  markdown phẳng** đúng 5 cột `cluster_id | label mịn | action | category | size` (sắp theo category
  rồi size giảm, unclassified cuối) — dễ soi "cụm này có đúng category không", thay cho các sub-table
  nhóm-theo-intent + cột reason/category_trội trước đây; bỏ luôn `step2b_merge_review.json` (dữ liệu máy
  đã có ở `catalog_a.json` + `step2a_cluster_labels.json`). `tests_respond.py` 10 PASS.
- `[intent-catalog]` **`step2b` thêm mục "Cách chia (giải thích)"** trước bảng: mỗi category liệt kê
  `[action]` + số cụm/feedback + _Định nghĩa_ + _Vì sao gộp_ (reason LLM) — trả lại giải thích cách chia
  đã mất khi rút gọn thành bảng phẳng. `review_rows` mang thêm `description` (từ intent LLM sinh).
  Bảng phân cụm thêm cột **`feedback`** (gạch đầu dòng toàn bộ feedback trong cụm, `<br>•`) để review
  tận nội dung; cột đủ: `cluster_id | feedback | label mịn | action | category | size`.

### Changed

- `[intent-catalog]` **Rollup đổi sang gán cụm vào 6 INTENT CỐ ĐỊNH = hướng trả lời (user chốt).**
  Thay "LLM tự sinh nhãn" bằng bộ cố định `SCENARIOS`: `report_bug` (known_gap, xin lỗi+đang xử lý) ·
  `request_feature` (known_gap, cảm ơn+sẽ cân nhắc) · `how_to` (answer_from_kb, hướng dẫn userguide) ·
  `praise` (ack_only, cảm ơn) · `complaint` (ack_only, xin lỗi+hỏi thêm) · `unclassified`. `ROLLUP_SYS`
  giờ phân MỖI cluster vào đúng 1 trong 6 (trả `{cluster_id,intent_id,reason}`), `action_type` suy CỨNG
  từ intent (không LLM chọn); intent_id = nhãn cuối inference route theo. **Không đổi contract**:
  action_type vẫn 3-enum §5. Verify 191 fb: report_bug 69, request_feature 59, **how_to 11** (nhánh
  answer_from_kb trước đây = 0 giờ bắt được usage-limit-hỏi-cơ-chế + how-to slide), praise 14,
  complaint 6, unclassified 3; coverage 0.953. Còn hạn chế cụm hỗn tạp (cluster 16 lẫn copy-button-bug
  trong how_to) — bản chất per-cluster, cần per-feedback mới hết. Plan: `docs/2026-08-26/intent-merge-centroid-gated/plan.md`.

### Fixed

- `[intent-catalog]` **`OUT_DIR` trỏ sai sau khi đổi tên package** `intent_classification/` →
  `src/01_intent_classification/`: `step1_clustering.py` hardcode `REPO_ROOT/"intent_classification"/"out"`
  ⇒ chạy trong layout mới tạo lại `intent_classification/out/` ở repo-root + `embed_cache.json` RỖNG
  ⇒ re-embed lại toàn bộ (tốn tiền). Sửa `OUT_DIR = ROOT.parent / "out"` (bám vị trí module, không
  hardcode tên thư mục). Đã dời output lạc chỗ về `src/01_intent_classification/out/` và gỡ thư mục thừa.

### Added

- `[inference.draft]` **Reply-scenario generator** `src/03_inference/reply_scenarios.py` — sinh
  "kịch bản reply" song ngữ VI/EN cho từng intent (category) trong Intent Catalog. Routing
  **deterministic theo `action_type`** (impl §3.2): `answer_from_kb`→we_resolved (nhánh runtime:
  RAG hit→resolve, 0 hit→we_listen guard R6); `known_gap`→we_listen (backlog: khớp→"sẽ phát triển"
  +mốc, không→"đã ghi nhận"); `ack_only`→we_listen trung tính; `unclassified`→**KHÔNG auto-reply**,
  chuyển PM (sink §4.3/R1). LLM (Sonnet) sinh copy tailored mỗi category theo rule
  `template/skill_create_email.md` (song ngữ, không gạch dài, giữ placeholder
  `{name}`/`{feedback_summary}`/`{timeline}`/`{resolution}` cho B2 điền runtime). Là lớp DESIGN-TIME
  cho `inference.draft` (B2) — KHÔNG gửi email/RAG/backlog (đó là `respond.py`). Output
  `out/<ts>_scenarios/reply_scenarios.{yaml,json,md}`; CLI `--catalog`, `--dry-run`. Reuse
  path/root từ `catalog.py`. Verify trên catalog v1 (8 intent): 6 we_listen/roadmap + 1
  acknowledge + 1 manual (0 we_resolved vì catalog chưa có intent answer_from_kb), 0 gạch dài trong
  copy. Plan: `docs/2026-08-26/reply-scenario-generator/plan.md`.

- `[intent-catalog]` **Hai artifact review tường minh cho STEP 2** (trước đây chỉ còn catalog cuối,
  không soi được cụm→intent): `out/<run>/step2a_cluster_labels.{json,yaml}` (mỗi cụm: label mịn LLM
  đặt + `dominant_category` + size + 3 mẫu) và `out/<run>/step2b_merge_review.{md,json}` (bảng rollup
  nhóm theo intent LLM tự sinh: cụm nào vào intent nào, kèm `category_trội` cross-check + lý do LLM).
  Giúp human review bước gộp dễ hơn.

### Changed

- `[intent-catalog]` **Tách hướng A thành 2 file theo bước** (thay `2_phase/approach_a_cluster_llm.py`,
  đã gỡ): `2_phase/step1_clustering.py` (**STEP 1** — chỉ unsupervised, KHÔNG LLM: load →
  preprocess → embed → UMAP → HDBSCAN leaf → **cluster report bằng cosine similarity**: medoid +
  cohesion (cosine member→medoid, mean/min) + separation (cosine medoid↔medoid tới cụm gần nhất)
  → `out/cluster_report.csv` (per-member) + `out/cluster_summary.csv`; giữ shared helper
  data/embedding/serving-client) và `2_phase/step2_llm_label_merge.py` (**STEP 2** — LLM Sonnet
  đặt tên/gộp/gán noise; **mọi prompt `*_SYS` để ở khối GLOBAL đầu file cho dễ chỉnh**; import
  clustering + helper từ STEP 1; orchestrate `run_approach_a` = STEP 1 → STEP 2). Nội dung hàm
  và prompt giữ nguyên; chỉ đổi path constants sang bám repo-root (`_find_up`) vì file dời vào
  `2_phase/` làm hỏng đường dẫn tương đối cũ. Verify 191 feedback: STEP 1 ra 34 cụm/noise 17%,
  STEP 2 → 24 intent, coverage 100%.
- `[intent-catalog]` **Output không ghi đè kết quả cũ**: mỗi lần chạy ghi vào folder timestamp
  `out/<YYYYmmdd_HHMMSS>_<phase>/` theo **giờ VN** (`Asia/Ho_Chi_Minh`, helper `run_dir(phase)`):
  STEP 1 → `..._clustering/{cluster_report,cluster_summary}.csv`; STEP 2 → `..._llm/catalog_a.{json,yaml}`
  (chạy STEP 2 sinh cả folder `_clustering` lẫn `_llm`). `embed_cache.json` cố tình GIỮ ở
  `out/` gốc (cache, tái dùng — không nhân bản mỗi run). `cluster_report`/`write_catalog` nhận
  tham số `out_dir`.

### Added

- `[ingest-sync]` **Luồng dựng KNOWLEDGE LAYER vào Scholar** — `src/02_knowledge/build_knowledge_layer.py`
  orchestrate 2 client sẵn có (DRY): gom **Confluence userguide** (`fetch_userguide`, cây page
  `395774795` — nay 17 page) + **Jira backlog "FAI. Team 01: Agentic Platform"** (board id `5042`, proxy
  JQL `summary ~ "Agentic Platform"` + `sprint is EMPTY` → 6 issue) → mỗi page/issue thành 1 **text
  source** → tạo/nạp **Scholar notebook** (`scholar_test.create_notebook/add_text_source/wait_ready`) →
  notebook = knowledge layer cho `inference.draft` (B2) query. CLI: `--dry-run` (chỉ fetch+in nguồn),
  `--notebook <id>` (nạp lại), `--ask` (smoke-test RAG), `--backlog-filter`, `--page`. Bổ sung
  `description` (+ helper `_plain_text` rút text từ ADF Jira) vào `fetch_backlog` để source backlog có
  nội dung. Plan: `docs/2026-08-26/knowledge-layer-scholar/plan.md`.
  **Ghi chú kiến trúc (rule 3.6):** Scholar là một **managed vector store** (tự lo chunk/embed/vector
  index/retrieve/citation) ⇒ nhất quán với §5 "Vector store", KHÔNG lệch kiến trúc — chỉ là lựa chọn
  hiện thực thay cho tự dựng Databricks Vector Search + `backlog_ref` Delta. Khi productionize nên ghi
  chú §5 "Vector store = Scholar (managed)" + coi `notebook_id` là handle của knowledge layer. Verify
  SIT (U2M SSO `tcb-agent-sit`): notebook `0250b1fe-de9c-4756-add5-9e2a273bb3f2`, 23 source ready,
  RAG + citation chạy.
- `[ingest-sync]` **Spike lấy userguide Confluence** — thêm `fetch_userguide()` + CLI `userguide`
  vào `src/02_knowledge/mcp_atlassian_test.py` (tái dùng `rpc()`/`_unwrap_search()`). Duyệt **đệ quy**
  cây page qua `get_page_children` (có `visited` chống lặp, `max_depth`, tự phân trang `start` vì
  server giới hạn `limit` 1..50), lấy nội dung từng page qua `get_page`. Response shape: `get_page`
  bọc nội dung ở `metadata.content.value` (markdown khi `convert_to_markdown=True`);
  `get_page_children` trả `{count, results:[{id,title,...}]}`. Root userguide TÀI Studio =
  page `395774795` (space `DataEngineering`) + **10 page con** (mỗi agent 1 page). Verify SIT:
  **11 page**, ~62K ký tự markdown. Trả `page_id, title, space_key, version, markdown` (chỉ ĐỌC,
  không chunk/embed/index). Plan: `docs/2026-08-26/confluence-userguide-fetch/plan.md`.
  **Lệch kiến trúc (rule 3.6):** §2 Input khai userguide đến từ **OneDrive/Microsoft Graph**; thực tế
  userguide đang ở **Confluence** (root page còn trỏ folder SharePoint song song). Nếu Confluence là
  nguồn chính thức ⇒ cập nhật §2 Input (thêm nguồn Confluence: `page_id/version/space`) + §5 và đổi
  điều kiện re-index sang theo `version` page TRƯỚC khi hiện thực `ingest-sync` thật.
- `[ingest-sync]` **Spike lấy backlog Jira tai-studio** — thêm `fetch_backlog()` + CLI `backlog`
  vào `src/knowledge/mcp_atlassian_test.py` (tái dùng client MCP `rpc()`). Phát hiện: "tai-studio"
  **không phải project key** — công việc nằm trong project **`TSFAI`** (TS-AI FOUNDATIONS), issue gắn
  tiền tố `[Tai Studio]`/`[TAI Studio]` ở summary. Hàm tự **phân trang** (không dựa `total` vì server
  MCP luôn trả `-1`; dừng khi trang < page_size, trần `max_pages`), lọc `summary ~` + `statusCategory
  != Done` + `sprint is EMPTY`, mặc định **loại issuetype `Test`** (dự án auto-sinh ~2000 test-case
  `[Tai Studio]`) → backlog sản phẩm còn **9 issue** thật (Story/Epic/Task/Work/Test Plan). Fix 2 bug
  parse response: (1) payload issues nằm ở `content[].text` dạng chuỗi JSON, `structuredContent.result`
  cũng là chuỗi (outputSchema `x-fastmcp-wrap-result`) — phải `json.loads`, đừng lấy thẳng; (2)
  response dùng key `issue_type` (snake_case), không phải `issuetype`. Verify trên SIT (profile
  `tcb-agent-sit`). Plan: `docs/2026-08-26/jira-backlog-fetch/plan.md`.
  **Lệch kiến trúc (ghi rõ, rule 3.6):** architecture §5 quy định production `ingest-sync` dùng Jira
  REST + Azure AD service principal; spike này dùng MCP-Atlassian + U2M SSO — chỉ ĐỌC thử, KHÔNG ghi
  `backlog_ref`. Khi hiện thực job thật phải chuyển stack theo §5 (hoặc cập nhật §5 trước).
- `[all]` **Sửa docstring** `mcp_atlassian_test.py`: ví dụ tool cũ sai tên
  `searchJiraIssuesUsingJql` → `search_issues`; thêm ghi chú yêu cầu **Python ≥ 3.10** (do `truststore`).
- `[intent-catalog]` **Rebuild** module intent classification thành 2 file (1 hướng/1 file, thay
  cho `discovery.py` cũ đã gỡ): `intent_classification/approach_a_cluster_llm.py` (**A** —
  embed qwen3 → UMAP 10D → HDBSCAN over-segment → Sonnet đặt tên cụm → Sonnet gộp toàn cục →
  feed noise cho LLM gán, không bỏ feedback; + shared helpers load/preprocess/embed(+cache)/
  chat_json/grounding/io) và `approach_b_direct_llm.py` (**B** — direct-LLM đọc thẳng theo lô
  → merge liên lô → grounding; import shared từ A; **sinh report so sánh A↔B**). Guardrail
  grounding ≥2 id thật. Đo độ tương đồng bằng canonical nearest-centroid labels → **ARI + NMI**,
  cộng taxonomy alignment (match intent A↔B theo cosine centroid) + granularity/coverage/Gini →
  `out/comparison_report.md`. Plan: `docs/2026-08-26/intent-classification-rebuild/plan.md`.
  Endpoint thật `databricks-claude-*` (KHÁC `-sit-tai` ở architecture §5), auth OAuth profile
  `tcb-agent-sit` + truststore TLS.

### Fixed

- `[intent-catalog]` **Clustering (hướng A) under-resolve thành mega-cluster** ở n=191: HDBSCAN
  mặc định `cluster_selection_method='eom'` (excess-of-mass) gom ~55% feedback vào 1-2 blob to
  (vd 1 cụm 55-56 mẫu "pdf translation"/"dữ liệu outdate") — trái với chủ trương over-segment
  (§4.2 method). Đổi sang **`selection='leaf'`** (lấy cụm ở lá cây phân cấp) + UMAP
  **`n_neighbors=8`** (giữ cấu trúc cục bộ, thay vì 15 nối các chủ đề thành ít blob) + sweep
  ưu tiên NHIỀU cụm sạch trong dải 15–40. Kết quả trên 191 feedback thật: A từ 6 cụm-blob
  (persistence <0.2 toàn bộ) → **34 cụm sạch** (top size ~11–14, không còn mega-blob) → gộp
  còn **22 intent** (coverage 100%, median size 7, Gini 0.28). So với B=32 intent (coverage 79%):
  ARI **0.33**, NMI **0.66**, **22 cặp** intent match — đồng thuận tăng hẳn so với cấu hình eom
  (ARI 0.23, 15 cặp). B (direct-LLM) vẫn over-fragment đuôi (40 feedback rơi khỏi grounding);
  đề xuất dùng A làm xương sống, soi intent chỉ-B cho rare-intent.

- `[intent-catalog]` `intent_classification/discovery.py` — 2 version intent discovery bằng LLM
  (Sonnet `databricks-claude-sonnet-4-6`) cho data nhỏ (n<500, method §2.1): **A** clustering →
  LLM merge + feed cả noise (không bỏ feedback); **B** direct-LLM đọc thẳng theo lô → merge nén
  (LLM nhóm theo idx, union id bằng code). Guardrail grounding ≥1 id thật (giữ rare-intent).
  Cache candidate + retry lỗi mạng. Xuất `out/discovery_{A,B}.yaml`+`.csv`. Plan:
  `docs/2026-08-25/intent-discovery-llm/plan.md`. Kết quả 191 feedback thật: A=22 intent
  (coverage cited 57%, giữ đuôi dài), B=82 intent (coverage 100%, over-fragment median size 1).
  Tên endpoint Claude thật là `databricks-claude-*` (KHÁC `-sit-tai` ghi ở architecture §5).

- `[classify]` Dữ liệu feedback THẬT trích từ ảnh chụp dashboard →
  `data/sample/feedback/feedback_extracted.csv` (192 dòng, schema như dashboard:
  agent/user/category/content/date; đã khử trùng phần chồng khi cuộn) và bản chuẩn hoá theo
  schema pipeline `intent_classification/data/raw/feedback_real.csv`
  (feedback_id/user_email/agent/content/created_at).

### Changed

- `[classify]` `intent_classification/requirements.txt` — pin runtime deps đã verify chạy
  end-to-end trên **conda base** (Python 3.13.12): umap-learn 0.5.12, hdbscan 0.8.44,
  numba 0.67.0, llvmlite 0.49.0, pynndescent 0.6.0 (+ numpy/pandas/openai/databricks-sdk).
  Ghi chú gỡ package rác `umap` 0.1.1 (không phải umap-learn, thiếu class UMAP) chiếm namespace.
- `[classify]` `intent_classification/run_intent_analysis.py` — **đổi input mặc định** sang
  data thật `intent_classification/data/raw/feedback_real.csv` (trước đây là fixture synthetic
  `data/sample/feedback_sample.csv`); vẫn giữ env override `INTENT_DATA_CSV` để chạy lại trên
  fixture khi cần. Đã chạy end-to-end trên 192 feedback thật (191 dùng được): embed qwen3 thật
  191×1024, HDBSCAN ra 9 cụm ứng viên, coverage 75.4% → cập nhật
  `intent_classification/out/review_table.csv`.

- `[intent-catalog]` Method document `docs/method-offline-intent-analysis.md` — quy trình DS
  thuần cho Offline Intent Analysis (Phase 0): audit → embed → cluster (over-segment) → LLM
  merge → **kiểm định taxonomy** (coverage/head-tail, stability ARI/NMI + persistence, MECE)
  → review gate → chọn exemplar + **so công thức scoring** → **calibrate ngưỡng có Wilson CI,
  recall nhánh reject, Cohen's κ** → freeze catalog. Bổ sung so với tài liệu cũ: đính chính
  "noise rate ≠ prior `unclassified_rate`", chặn mù rare-intent, kiểm định lựa chọn embedding.
  Deliverable = `intents.yaml` + validation report (acceptance A-1…A-10).
- `[intent-catalog]` Script `intent_classification/run_intent_analysis.py` — pipeline offline
  chạy-local (functional, chỉ numpy+pandas), in tiến trình từng step: audit → preprocess →
  embed → reduce → cluster (sweep) → stability (ARI) → validation (coverage/Gini/head-tail) →
  review table. Ba khối embed/reduce/cluster là local stand-in (char-ngram → PCA → DBSCAN)
  cắm-rời cho qwen3 → UMAP → HDBSCAN. Xuất `intent_classification/out/review_table.csv`.
  Bám method §2/§3/§4/§6/§7; §5 (LLM merge) + §9 (calibrate) chỉ in như next-step.
- `[intent-catalog]` Doc `docs/techstack-intent-classification.md` — review techstack bước
  Intent Classification: giải thích thuật toán (embedding, UMAP/PCA, HDBSCAN/DBSCAN, cosine,
  exemplar scoring, ARI/NMI/silhouette/Gini/Wilson CI/Cohen's κ), cách dùng LLM (Sonnet/Haiku/
  qwen3 + structured output + guardrail), và phương pháp đánh giá 3 tầng. Đối chiếu stack
  production ⇄ stand-in local + map tới từng hàm trong script.
- `[classify]` Generator dữ liệu feedback giả lập `scripts/gen_sample_feedback.py` + fixture
  `data/sample/feedback_sample.{jsonl,csv}` (650 dòng) và sidecar nhãn nhóm ẩn
  `data/sample/feedback_sample_labels.jsonl`. Đứng thay nguồn *Feedback datalake*
  (`docs/architecture.md` §2 Input) khi chưa có quyền truy cập bảng thật, để chạy được
  Step 0–4 của P1.A. Deterministic theo seed; schema khớp data contract
  (`feedback_id`, `user_email`, `agent`, `content`, `created_at`).
  Kế hoạch: `docs/2026-08-25/sample-feedback-fixture/plan.md`.
- `[all]` Khởi tạo `CHANGELOG.md`.

### Changed

- `[intent-catalog]` Script `run_intent_analysis.py`: **bỏ stand-in cho embed & reduce**, dùng
  thẳng production — embedding `databricks-qwen3-embedding-0-6b` qua Model Serving (OpenAI-compat,
  auth OAuth theo profile `tcb-agent-sit` qua databricks-sdk, có cache đĩa `out/embed_cache.npz`),
  `umap.UMAP(n_components=10, metric=cosine)`, và `hdbscan.HDBSCAN(min_cluster_size, min_samples,
  metric=euclidean)` — **bỏ hết stand-in**: không còn char-ngram TF-IDF / PCA / DBSCAN. Sweep đổi
  từ `eps` → `min_cluster_size {5,8,12,20}`, chọn theo số cụm + noise + persistence trung vị;
  review table thêm cột `persistence`. Medoid/mẫu chuyển sang euclidean trên không gian UMAP.
  Deps runtime: `openai`, `umap-learn`, `hdbscan`, `databricks-sdk`. Kết quả fixture: 24 cụm,
  noise 15.3%, coverage 84.7% (trước đó DBSCAN collapse còn 2 cụm).
- `[intent-catalog]` Đổi rule tiền xử lý (script + method §2.2): **giữ hết feedback của user**,
  chỉ bỏ feedback **không có nội dung có nghĩa** (rỗng / chỉ số / ký hiệu / emoji — không chứa
  chữ cái nào, `any(ch.isalpha())`). **Bỏ lọc theo độ dài** (feedback ngắn vẫn là intent thật,
  R1) và **bỏ dedup exact** (trùng lặp là feedback thật, chỉ báo cáo tỉ lệ). Fixture: 650 → 640
  (bỏ 10), giữ 58 bản trùng thay vì cắt.
- `[intent-catalog]` Đề xuất đổi data contract `intent_catalog` (§4.5): exemplar lưu dạng
  **text trong git** thay vì `exemplar_vectors` (triệt R2 — vector chết cứng theo model);
  thêm `scoring` (max|top2_mean|prototype) và `stability` vào schema catalog. Cần đồng bộ
  `docs/architecture.md` §4.5 trước khi implement (rule 3.6).
- `[all]` Repoint tham chiếu `docs/impl-phase1-intent-classification.md` → `method-offline-intent-analysis.md`
  ở `CLAUDE.md`, `docs/impl-phase2-auto-feedback-flow.md`, `docs/2026-08-25/sample-feedback-fixture/plan.md`.

### Fixed

- `[intent-catalog]` `load_feedback` vá bug `NaN → "nan"`: content NaN bị `astype(str)` thành
  chuỗi `"nan"` (có chữ cái → lọt filter `isalpha`, tạo cụm rác). Đổi thành `fillna("")` để
  chuỗi rỗng bị gạt như content vô nghĩa ở STEP 1. Fixture: bỏ 14 dòng (trước 10).

### Changed (tiếp)

- `[intent-catalog]` Nới trần cluster `TARGET_CLUSTERS` 40 → 60 (ưu tiên over-segment) và thêm
  `persistence_hist()` — in phân bố cụm theo độ bền persistence ở STEP 4 (bins mong manh→vững +
  tỉ lệ cụm `<0.1`). Lưu ý: tiêu chí chọn (max median persistence) vẫn ưu tiên cụm bền nên với
  fixture hiện tại chọn mcs=12 (26 cụm) thay vì mcs=8 (48 cụm) dù trần đã nới.

### Removed

- `[intent-catalog]` `docs/impl-phase1-intent-classification.md` — trộn lẫn phần phân tích DS
  (P1.A) với đặc tả code module runtime `classify` (P1.B). Phần DS chuyển sang method doc mới;
  phần module runtime `inference.classify` (B1) sẽ đặc tả riêng ở tài liệu production khi tới scope.
