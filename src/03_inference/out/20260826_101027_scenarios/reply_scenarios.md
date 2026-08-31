# Kịch bản reply theo category (Tier A)

> Routing deterministic theo `action_type` (§3.2). `we_resolved` là quyết định **per-feedback** (cần RAG hit), tầng category chỉ mô tả nhánh. `{name}`/`{feedback_summary}`/`{timeline}`/`{resolution}` do B2 điền runtime.

**8 category · catalog:** `20260826_092038_llm/catalog_a.yaml`


## bug_core_function_broken  
`bug_core_function_broken` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## bug_output_quality_and_format  
`bug_output_quality_and_format` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## issue_usage_limit_and_system_policy  
`issue_usage_limit_and_system_policy` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## positive_feedback  
`positive_feedback` · action_type=`ack_only` · email_type=**we_listen** · tone=`acknowledge` · route=`ack_neutral`

> Ack trung tính (cảm ơn/ghi nhận), bỏ RAG + backlog (impl §5).

_(không sinh copy — chuyển PM xử tay)_


## request_new_feature_or_capability  
`request_new_feature_or_capability` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## request_slide_quality_and_edit_improvement  
`request_slide_quality_and_edit_improvement` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## request_ux_and_ui_improvement  
`request_ux_and_ui_improvement` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

_(không sinh copy — chuyển PM xử tay)_


## Chưa phân loại / không khớp intent nào  
`unclassified` · action_type=`ack_only` · email_type=**— (KHÔNG auto-reply)** · tone=`escalate` · route=`manual_pm`

> Sink §4.3 — KHÔNG auto-reply, chuyển PM xử tay (R1).

_(không sinh copy — chuyển PM xử tay)_
