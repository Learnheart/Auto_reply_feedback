# Kịch bản reply theo category (Tier A)

> Routing deterministic theo `action_type` (§3.2). `we_resolved` là quyết định **per-feedback** (cần RAG hit), tầng category chỉ mô tả nhánh. `{name}`/`{feedback_summary}`/`{timeline}`/`{resolution}` do B2 điền runtime.

**6 category · catalog:** `20260826_102555_llm/catalog_a.json`


## vague_negative_sentiment  
`vague_negative_sentiment` · action_type=`ack_only` · email_type=**we_apologize** · tone=`apology` · route=`apology`

> Feedback tiêu cực chung → xin lỗi + mời nêu chi tiết; bỏ RAG/backlog.

_(không sinh copy — chuyển PM xử tay)_


## ai_output_quality_error  
`ai_output_quality_error` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## bug_technical_error  
`bug_technical_error` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## feature_request_and_ux_improvement  
`feature_request_and_ux_improvement` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## praise_positive_feedback  
`praise_positive_feedback` · action_type=`ack_only` · email_type=**we_listen** · tone=`acknowledge` · route=`ack_neutral`

> Ack trung tính (cảm ơn/khen), bỏ RAG + backlog (impl §5).

_(không sinh copy — chuyển PM xử tay)_


## Chưa phân loại / không khớp kịch bản nào  
`unclassified` · action_type=`ack_only` · email_type=**— (KHÔNG auto-reply)** · tone=`escalate` · route=`manual_pm`

> Sink §4.3 — KHÔNG auto-reply, chuyển PM xử tay (R1).

_(không sinh copy — chuyển PM xử tay)_
