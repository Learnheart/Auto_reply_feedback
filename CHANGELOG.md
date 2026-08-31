# Changelog

Mọi thay đổi logic đáng kể của dự án được ghi ở đây.
Định dạng theo [Keep a Changelog](https://keepachangelog.com/), version theo [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed

- `[ingest-sync]` **Xóa code chết `src/02_knowledge/scholar_test.py` (đường Scholar managed-RAG v3.0).** Không file nào `import scholar_test`; v3.1 (whole-page routing `agent → userguide_page`) đã thay hoàn toàn hướng Scholar/Vector Search cho userguide. Kèm: xóa toàn bộ `__pycache__/` trong `src/` (bytecode tự sinh, có `.pyc` mồ côi) + thêm `.gitignore` (`__pycache__/`, `*.pyc`, `*.pyo`) chống tái phát; sửa comment gãy `src/01_intent_classification/2_phase/step1_clustering.py:135` (trỏ file đã xóa → `mcp_atlassian_call.py`, cùng pattern truststore). Cập nhật `docs/architecture/knowledge-layer.md` bỏ box `scholar_test` khỏi component/integration diagram.

### Added

- `[inference.classify]` **Golden dataset `data/golden/golden_intent.csv` — kiểm chứng chất lượng classify B1.** 61 dòng nhãn tay (cột `intent` = target), phủ đủ 5 label `request_feature`/`how_to`/`praise`/`complaint`/`unclassified` (taxonomy KHÔNG có `report_bug` — bug gộp vào `complaint`). Nội dung `real` trích nguyên văn từ `feedback_extracted.csv` (id `fb_<idx>` khớp `catalog.load_feedback_index`) + 3 dòng `crafted` cho how_to canonical. Kèm `data/golden/README.md` (định nghĩa 5 label, nguyên tắc gán nhãn ranh giới complaint/request_feature/how_to, map `report_bug→complaint` khi eval). Động cơ: input how-to thật ("làm sao để vẽ diagram từ ảnh") bị B1 gán nhầm `report_bug` ⇒ cần bộ đo chất lượng có ground-truth.

- `[ingest-sync]` **`docs/architecture/knowledge-layer.md` — doc kiến trúc knowledge layer (`src/02_knowledge`).** Một file Markdown 3 view: component diagram (3 layer: orchestration `build_knowledge_layer.py` → store `userguide_store.py` → access `mcp_atlassian_call.py`), 5 sequence diagram (full flow Job A, MCP JSON-RPC round-trip, recursive userguide walk, `agent → page` routing, Jira backlog fetch), integration diagram (trust boundary Databricks/Atlassian). Nêu rõ gap: `fetch_backlog` chưa wire vào Job A; spike JSON vs prod Delta.

### Changed

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
