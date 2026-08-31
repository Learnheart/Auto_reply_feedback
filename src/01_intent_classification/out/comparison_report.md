# So sánh độ tương đồng — Hướng A (cluster→LLM) vs Hướng B (direct-LLM)

> Bước Offline Intent Analysis (Phase 0). Discovery ứng viên intent — CHƯA freeze catalog,
> CHƯA calibrate ngưỡng (§8–§9 method). Xem `docs/2026-08-26/intent-classification-rebuild/plan.md`.

- Feedback: **191** (đã bỏ content vô nghĩa)
- Embedding: `databricks-qwen3-embedding-0-6b` · LLM: `databricks-claude-sonnet-4-6` · seed 42

## 1. Tổng quan mỗi hướng

| Chỉ số | Hướng A (cluster→LLM) | Hướng B (direct-LLM) |
|---|---|---|
| Số intent | 22 | 32 |
| Coverage (supporting ids) | 100% | 79% |
| Median size | 7 | 3 |
| Intent đuôi nhỏ (≤3 id) | 1 | 16 |
| Feedback KHÔNG được phủ (tail cost) | 0 | 40 |
| Gini (tập trung khối lượng) | 0.2825 | 0.3762 |
| Top-10 size | [26, 16, 12, 11, 11, 11, 11, 10, 10, 8] | [22, 13, 11, 11, 6, 6, 6, 5, 5, 5] |

## 2. Độ tương đồng phân loại (canonical nearest-centroid labels)

Gán mỗi feedback → intent có centroid embedding gần nhất, trong TỪNG catalog (cùng cơ
chế cho A và B, plan D6), rồi so hai cách gán trên toàn bộ feedback:

- **ARI** (Adjusted Rand Index): **0.3319**
- **NMI** (Normalized Mutual Information): **0.6622**

> ARI ~1 = hai hướng chia feedback gần như trùng; ~0 = độc lập như ngẫu nhiên.
> NMI cao mà ARI thấp hơn thường do lệch **độ mịn** (số intent) giữa hai hướng (22 vs 32).

## 3. Taxonomy alignment (match intent A ↔ B, cosine centroid ≥ 0.60)

Khớp được **22** cặp · chỉ có ở A: **0** · chỉ có ở B: **10**.

| A intent | B intent | cosine |
|---|---|---|
| positive_general_feedback (`positive_general_feedback`) | Positive feedback / Compliment (`positive_feedback_compliment`) | 0.981 |
| translation_errors_and_quality_issues (`translation_errors_and_quality_issues`) | Translation incomplete, font error, or file translation bug (`translation_incomplete_font_error_or_file_translation_bug`) | 0.957 |
| broken_font_and_text_display_quality (`broken_font_and_text_display_quality`) | Slide font error / export PPTX font mismatch (`slide_font_error_export_pptx_font_mismatch`) | 0.951 |
| excel_data_input_output_and_chart_export (`excel_data_input_output_and_chart_export`) | Excel/data to chart/PPT conversion not working (`excel_data_to_chart_ppt_conversion_not_working`) | 0.946 |
| outdated_or_missing_knowledge_base_data (`outdated_or_missing_knowledge_base_data`) | Data missing, outdated, or not normalized (`data_missing_outdated_or_not_normalized`) | 0.922 |
| missing_history_and_save_functionality (`missing_history_and_save_functionality`) | Slide version history & management (`slide_version_history_management`) | 0.921 |
| slide_visual_design_and_content_quality (`slide_visual_design_and_content_quality`) | Slide quality & design improvement (`slide_quality_design_improvement`) | 0.919 |
| platform_access_and_llm_structured_output_error (`platform_access_and_llm_structured_output_error`) | Structured output / LLM JSON parsing error (`structured_output_llm_json_parsing_error`) | 0.911 |
| multilingual_ui_and_output_language (`multilingual_ui_and_output_language`) | Vietnamese language interface request (`vietnamese_language_interface_request`) | 0.895 |
| slide_functional_bugs_and_not_editable_after_export (`slide_functional_bugs_and_not_editable_after_export`) | Slide generation not working (`slide_generation_not_working`) | 0.884 |
| vague_negative_or_non_actionable_feedback (`vague_negative_or_non_actionable_feedback`) | Gibberish / unclear / test feedback (`gibberish_unclear_test_feedback`) | 0.883 |
| usage_limit_unclear_and_blocking (`usage_limit_unclear_and_blocking`) | Credit/quota limit indicator missing or unclear (`credit_quota_limit_indicator_missing_or_unclear`) | 0.882 |
| agent_no_response_or_answer_disappears (`agent_no_response_or_answer_disappears`) | App not responding / general error (`app_not_responding_general_error`) | 0.882 |
| summarizer_inaccuracy_and_missing_controls (`summarizer_inaccuracy_and_missing_controls`) | Summarization user control & output length customization (`summarization_user_control_output_length_customization`) | 0.862 |
| slide_ai_hallucination_missing_feedback_loop_and_layout_errors (`slide_ai_hallucination_missing_feedback_loop_and_layout_errors`) | Slide content & structure editing (`slide_content_structure_editing`) | 0.855 |
| homepage_and_ui_layout_improvement (`homepage_and_ui_layout_improvement`) | UI font size too small (`ui_font_size_too_small`) | 0.852 |
| multi_file_and_reference_link_input (`multi_file_and_reference_link_input`) | File upload limitation (`file_upload_limitation`) | 0.845 |
| tcb_specific_slide_template_and_context_requests (`tcb_specific_slide_template_and_context_requests`) | Powerpointer – missing chart/image insertion in slide (`powerpointer_missing_chart_image_insertion_in_slide`) | 0.835 |
| cross_document_comparison_and_competitor_analysis (`cross_document_comparison_and_competitor_analysis`) | Request to add detailed analysis feature (`request_to_add_detailed_analysis_feature`) | 0.834 |
| image_audio_video_input_and_chat_sharing (`image_audio_video_input_and_chat_sharing`) | Request additional agent features / user instruction input (`request_additional_agent_features_user_instruction_input`) | 0.781 |
| upload_file_format_unsupported_or_parse_error (`upload_file_format_unsupported_or_parse_error`) | Translation output language expansion & image translation (`translation_output_language_expansion_image_translation`) | 0.776 |
| output_quality_shallow_and_ignores_instructions (`output_quality_shallow_and_ignores_instructions`) | No result or wrong result (`no_result_or_wrong_result`) | 0.726 |

**Chỉ xuất hiện ở B:** AI hallucination & response quality (`ai_hallucination_response_quality`), Copy button not working / request copy button (`copy_button_not_working_request_copy_button`), Translator does not work for specific content types (`translator_does_not_work_for_specific_content_types`), Translation quality poor (`translation_quality_poor`), Translation custom glossary / terminology (`translation_custom_glossary_terminology`), Export file request (Word, PPTX chart, per-page slide) (`export_file_request_word_pptx_chart_per_page_slide`), Add specific content to slide/document (`add_specific_content_to_slide_document`), Request micro-route statistics (`request_micro_route_statistics`), Integration request: Powerpointer + Translator / Summarizer (`integration_request_powerpointer_translator_summarizer`), Session expired – cannot continue brainstorm (`session_expired_cannot_continue_brainstorm`)

## 4. Nhận xét

- **Đồng thuận ở mức thô, bất đồng ở mức mịn.** Taxonomy alignment cao (22/22 intent của hướng A có cặp tương ứng) nhưng ARI thấp (0.3319) trong khi NMI trung bình (0.6622). Không mâu thuẫn: hai hướng nhìn ra **cùng bộ chủ đề lõi**, nhưng hướng B **cắt nhỏ** các bucket lớn của hướng A thành nhiều intent con ⇒ partition feedback lệch nhau nên ARI tụt, còn thông tin chung (NMI) vẫn giữ.
- **Độ mịn & cái giá đuôi.** Hướng B sinh 32 intent (median size 3) vs hướng A 22 intent (median size 7). Mịn hơn nhưng đuôi bị phân mảnh: 40/191 feedback của hướng B rơi khỏi mọi intent sau guardrail grounding (≥2 id), so với 0/191 ở hướng A. Hướng A giữ phủ cao nhờ feed noise trở lại (plan D5); direct-LLM (B) đẩy nhiều feedback đuôi dài thành nhóm size≈1 rồi bị grounding loại.
- **Khác biệt cần review (PM/AI team, §7 method):** 0 intent chỉ-A và 10 intent chỉ-B là nơi hai phương pháp bất đồng — đọc tay trước. Nhiều intent chỉ-B là chủ đề mịn/hiếm (vd font, copy button, session expired) mà clustering của A gộp vào bucket lớn hơn; đây vừa là ứng viên rare-intent (R1) vừa là rủi ro over-fragment.
- **Đề xuất:** dùng hướng A làm **xương sống** taxonomy (Gini 0.2825, khối lượng tập trung, phủ cao), rồi soi danh sách intent chỉ-B để bổ sung/tách những chủ đề mịn thực sự đáng thành intent riêng.
