inclusion: manual
Skill: TaiStudio Email Feedback Response

Generate professional bilingual (Vietnamese + English) email responses to user feedback for TÀI Studio. Output is a .eml file that opens directly in Outlook compose mode.

Product name is fixed: "TÀI Studio" (uppercase ÀI). Never write "Tài Studio" or "Tai Studio" in email body/subject text.

Trigger Keywords
taistudio email
tai studio email
feedback email
Email Configuration
Field	Value
From	taistudio@techcombank.com.vn
Subject	[TÀI Studio] Your TÀI Studio feedback
CC	romeo.olympia@techcombank.com.vn, anhdt26@techcombank.com.vn, duongntt31@techcombank.com.vn, thucnm@techcombank.com.vn
Input Parameters
Parameter	Required	Description
email_type	Yes	we_listen or we_resolved
recipient_email	Yes	Email of feedback submitter
recipient_name	Yes	Name of feedback submitter
feedback_summary	Yes	Brief summary of feedback
resolution_details	For we_resolved	How the issue was resolved
agent_name	No	Which TÀI Studio agent (e.g., The Translator)
sprint	No	Sprint or timeline info
Email Structure
Logo: Embedded inline via cid:tai_logo (file: icon TAI.png)
Language indicator: "English version below" (italic, right-aligned)
Vietnamese content (first)
Red separator with "ENGLISH VERSION" label (
#e53e3e)
English content (second)
Footer with red top border (
#e53e3e)
Email Type 1: We Listen
Vietnamese
Xin chào {name},

Cảm ơn bạn đã dành thời gian chia sẻ phản hồi về TÀI Studio. Chúng tôi rất trân trọng đóng góp của bạn, và mỗi ý kiến đều giúp chúng tôi cải thiện sản phẩm tốt hơn.

**Tóm tắt phản hồi của bạn:**
[Red box: feedback_summary]

Team TÀI Studio đã ghi nhận phản hồi này. {resolution_timeline}. Chúng tôi sẽ thông báo lại khi tính năng sẵn sàng.

Cảm ơn bạn đã đồng hành cùng TÀI Studio!
English
Hi {name},

Thank you for taking the time to share your feedback about TÀI Studio. We truly value your input, and every piece of feedback helps us improve.

**Your feedback summary:**
[Red box: feedback_summary]

The TÀI Studio team has noted your request. {resolution_timeline}. We'll update you once it's live.

Thank you for being part of the TÀI Studio journey!
Email Type 2: We Resolved
Vietnamese
Xin chào {name},

Phản hồi của bạn rất quan trọng với chúng tôi!

Chúng tôi vui mừng thông báo rằng vấn đề bạn đã phản hồi đã được giải quyết.

**Phản hồi ban đầu:**
[Red box: feedback_summary]

**Kết quả xử lý:**
[Green box: resolution_details]

Chúng tôi hy vọng bạn sẽ tiếp tục sử dụng TÀI Studio và đóng góp ý kiến. Mỗi phản hồi của bạn đều tạo nên sự khác biệt!
English
Hi {name},

Your feedback counts!

We're happy to let you know that the issue you reported has been resolved.

**Original feedback:**
[Red box: feedback_summary]

**Resolution:**
[Green box: resolution_details]

We hope you'll continue using TÀI Studio and sharing your thoughts. Every piece of feedback makes a difference!
Footer (Both Types)
Nếu bạn cần hỗ trợ thêm / If you need further assistance:
- anhdt26
- duongntt31
- thucnm

Khám phá thêm về TÀI Studio / Discover more about TÀI Studio:
https://techcombank.sharepoint.com/sites/AITransformationHub/SitePages/Tài_Studio.aspx

Trân trọng / Best regards,
Team TÀI Studio
AI Foundation | Techcombank
Writing Style Rules
No em dashes (—) anywhere in the email body. Replace with a comma, period, or rewrite the sentence naturally. Em dashes are a known AI writing tell.
Keep tone warm but human — read it aloud before finalizing. If it sounds robotic, rewrite.
Styling Rules
No icons/emojis in email body
Feedback box: background:#fff5f5; border-left:4px solid #e53e3e (red)
Resolution box (we_resolved only): background:#e8f5e9; border-left:4px solid #2e7d32 (green)
Section divider: border-top:2px solid #e53e3e with centered "ENGLISH VERSION" label
Footer top border: 2px solid #e53e3e
Font: Segoe UI, 14px body, 13px footer
Max width: 640px, centered, white background with border-radius 8px
Output Method

Generate a Python script (build_eml.py) that:

Reads icon TAI.png from workspace
Embeds image inline via MIME multipart/related with Content-ID: <tai_logo>
Sets X-Unsent: 1 header (Outlook opens as compose/draft)
Sets From to taistudio@techcombank.com.vn
Outputs .eml file to email/ subfolder
User double-clicks .eml to open Outlook compose window
Build Script Template
python
"""
Build .eml file with embedded logo for Outlook compose.
Run: python build_eml.py
"""
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "email")
os.makedirs(OUTPUT_DIR, exist_ok=True)

FROM_EMAIL = "taistudio@techcombank.com.vn"
TO_EMAIL = "{recipient_email}"
CC_LIST = "romeo.olympia@techcombank.com.vn,anhdt26@techcombank.com.vn,duongntt31@techcombank.com.vn,thucnm@techcombank.com.vn"
SUBJECT = "[TÀI Studio] Your TÀI Studio feedback"
IMAGE_PATH = os.path.join(SCRIPT_DIR, "icon TAI.png")

HTML_BODY = """..."""  # Generated HTML based on email_type and parameters

def build_eml():
    msg = MIMEMultipart("related")
    msg["Subject"] = SUBJECT
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg["Cc"] = CC_LIST
    msg["X-Unsent"] = "1"

    html_part = MIMEText(HTML_BODY, "html", "utf-8")
    msg.attach(html_part)

    with open(IMAGE_PATH, "rb") as f:
        img_data = f.read()
    img_part = MIMEImage(img_data, _subtype="png")
    img_part.add_header("Content-ID", "<tai_logo>")
    img_part.add_header("Content-Disposition", "inline", filename="icon_TAI.png")
    msg.attach(img_part)

    output_path = os.path.join(OUTPUT_DIR, "feedback_{recipient}.eml")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(msg.as_string())

if __name__ == "__main__":
    build_eml()
Important Notes
Outlook X-Unsent: 1 opens email in compose mode — user just clicks Send
Do NOT use anchor links (#id) for "Click here for English version" — Outlook doesn't support in-email anchors. Use visual separator instead.
Do NOT change From account after opening — Outlook resets body content when switching From account
Logo must be embedded via MIME, not ext