# Kịch bản reply theo category (Tier A)

> Routing deterministic theo `action_type` (§3.2). `we_resolved` là quyết định **per-feedback** (cần RAG hit), tầng category chỉ mô tả nhánh. `{name}`/`{feedback_summary}`/`{timeline}`/`{resolution}` do B2 điền runtime.

**6 category · catalog:** `20260826_102555_llm/catalog_a.yaml`


## vague_negative_sentiment  
`vague_negative_sentiment` · action_type=`ack_only` · email_type=**we_apologize** · tone=`apology` · route=`apology`

> Feedback tiêu cực chung → xin lỗi + mời nêu chi tiết; bỏ RAG/backlog.

**VI**  
Chào {name},

Chúng tôi thành thật xin lỗi vì trải nghiệm chưa được như kỳ vọng của bạn. Chúng tôi đã ghi nhận phản hồi của bạn về {feedback_summary} và rất muốn hiểu rõ hơn để có thể hỗ trợ bạn tốt hơn. Nếu bạn có thể mô tả cụ thể hơn về tình huống bạn gặp phải, chúng tôi sẽ xem xét ngay và tìm cách cải thiện.

TÀI Studio luôn lắng nghe và mong muốn đồng hành cùng bạn. Bạn có thể phản hồi trực tiếp tại đây hoặc liên hệ đội hỗ trợ bất cứ lúc nào bạn cần.

**EN**  
Hi {name},

We are truly sorry to hear that your experience has not been what you hoped for. We have noted your feedback about {feedback_summary} and would genuinely like to understand more so we can support you better. If you are able to share more details about what happened, we will look into it right away.

TÀI Studio is always here to listen and we want to make things right for you. Feel free to reply here or reach out to our support team at any time.


## ai_output_quality_error  
`ai_output_quality_error` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

**VI**  
Chào {name},

Cảm ơn bạn đã chia sẻ phản hồi này với chúng tôi. Chúng tôi đã ghi nhận vấn đề liên quan đến {feedback_summary} và hiểu rằng chất lượng đầu ra của AI ảnh hưởng trực tiếp đến trải nghiệm làm việc của bạn. Đội ngũ TÀI Studio đang xem xét để cải thiện độ chính xác và tính đầy đủ của kết quả, và chúng tôi kỳ vọng sẽ có những cập nhật tích cực vào khoảng {timeline}.

Phản hồi cụ thể như của bạn rất có giá trị để chúng tôi tiếp tục nâng cao chất lượng sản phẩm. Cảm ơn bạn đã đồng hành cùng TÀI Studio.

**EN**  
Hi {name},

Thank you for sharing this with us. We have taken note of your feedback regarding {feedback_summary} and fully understand how AI output quality directly impacts your workflow. The TÀI Studio team is reviewing this to improve accuracy and completeness, and we hope to have meaningful updates around {timeline}.

Detailed feedback like yours is incredibly valuable in helping us raise the bar on quality. Thank you for being part of the TÀI Studio journey.


## bug_technical_error  
`bug_technical_error` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

**VI**  
Chào {name},

Cảm ơn bạn đã báo cáo về vấn đề này. Chúng tôi đã ghi nhận phản hồi của bạn liên quan đến {feedback_summary} và đã chuyển thông tin đến đội kỹ thuật để xem xét. Đây là điều chúng tôi đang theo dõi và sẽ tiếp tục cải thiện trong thời gian tới, dự kiến vào khoảng {timeline}.

Nếu bạn gặp thêm bất kỳ sự cố nào khác, đừng ngần ngại liên hệ lại với chúng tôi. Đội ngũ TÀI Studio luôn ở đây để lắng nghe bạn.

**EN**  
Hi {name},

Thank you for taking the time to report this. We have noted your feedback regarding {feedback_summary} and have passed it along to our technical team for review. This is something we are actively tracking and plan to address in an upcoming update, tentatively around {timeline}.

If you run into any other issues in the meantime, please do not hesitate to reach out. The TÀI Studio team is always here to help.


## feature_request_and_ux_improvement  
`feature_request_and_ux_improvement` · action_type=`known_gap` · email_type=**we_listen** · tone=`roadmap` · route=`backlog_check`

> Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; không khớp → 'đã ghi nhận, sẽ cải thiện'.

**VI**  
Chào {name},

Cảm ơn bạn đã dành thời gian chia sẻ ý kiến. Chúng tôi đã ghi nhận đề xuất của bạn về {feedback_summary} và sẽ đưa vào danh sách phát triển để đội ngũ TÀI Studio cân nhắc trong các giai đoạn tiếp theo. Chúng tôi chưa thể xác nhận mốc thời gian cụ thể, nhưng dự kiến sẽ có thêm thông tin vào khoảng {timeline}.

Những góp ý như thế này giúp TÀI Studio ngày càng phù hợp hơn với nhu cầu thực tế của bạn. Chúng tôi rất trân trọng sự đóng góp của bạn.

**EN**  
Hi {name},

Thank you for taking the time to share your thoughts. We have logged your suggestion regarding {feedback_summary} and will bring it to the TÀI Studio team for consideration in our upcoming development cycles. We are not able to confirm a specific timeline just yet, but we expect to have more clarity around {timeline}.

Input like yours plays a real role in shaping where TÀI Studio goes next. We truly appreciate you sharing it with us.


## praise_positive_feedback  
`praise_positive_feedback` · action_type=`ack_only` · email_type=**we_listen** · tone=`acknowledge` · route=`ack_neutral`

> Ack trung tính (cảm ơn/khen), bỏ RAG + backlog (impl §5).

**VI**  
Chào {name},

Cảm ơn bạn rất nhiều vì đã chia sẻ cảm nhận tích cực này. Chúng tôi rất vui khi biết rằng {feedback_summary} đã mang lại trải nghiệm tốt cho bạn. Điều đó thực sự là nguồn động lực lớn cho cả đội ngũ TÀI Studio.

Chúng tôi sẽ tiếp tục cố gắng để mang đến những trải nghiệm ngày càng tốt hơn. Cảm ơn bạn đã tin tưởng và đồng hành cùng TÀI Studio.

**EN**  
Hi {name},

Thank you so much for taking the time to share this. We are really glad to hear that {feedback_summary} made a positive difference for you. It genuinely means a lot to everyone on the TÀI Studio team.

We will keep working hard to make the experience even better. Thank you for your trust and for being with TÀI Studio.


## Chưa phân loại / không khớp kịch bản nào  
`unclassified` · action_type=`ack_only` · email_type=**— (KHÔNG auto-reply)** · tone=`escalate` · route=`manual_pm`

> Sink §4.3 — KHÔNG auto-reply, chuyển PM xử tay (R1).

_(không sinh copy — chuyển PM xử tay)_
