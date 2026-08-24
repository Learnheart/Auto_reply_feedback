"""
Build .eml file with embedded icon TAI.png for Outlook compose.
Run: python build_eml.py
Output: email/feedback_phuongntt2.eml
"""
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "email")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Config
FROM_EMAIL = "taistudio@techcombank.com.vn"
TO_EMAIL = "phuongntt2@techcombank.com.vn"
CC_LIST = "romeo.olympia@techcombank.com.vn,anhdt26@techcombank.com.vn,duongntt31@techcombank.com.vn,thucnm@techcombank.com.vn"
SUBJECT = "[T\u00c0I Studio] Your T\u00c0I Studio feedback"
IMAGE_PATH = os.path.join(SCRIPT_DIR, "icon TAI.png")

HTML_BODY = """\
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;">

<!-- Banner -->
<div style="padding:24px 32px 0;text-align:center;">
  <img src="cid:tai_logo" style="height:48px;width:auto;" alt="T&Agrave;I Studio" />
</div>

<!-- Language note -->
<div style="text-align:right;padding:12px 32px 0;font-size:12px;color:#888888;font-style:italic;">
  English version below
</div>

<!-- Vietnamese -->
<div style="padding:24px 32px;line-height:1.7;color:#333333;font-size:14px;">
  <p>Xin ch&agrave;o Ph&#432;&#417;ng,</p>

  <p>Ph&#7843;n h&#7891;i c&#7911;a b&#7841;n r&#7845;t quan tr&#7885;ng v&#7899;i ch&uacute;ng t&ocirc;i!</p>

  <p>Ch&uacute;ng t&ocirc;i vui m&#7915;ng th&ocirc;ng b&aacute;o r&#7857;ng nhu c&#7847;u c&#7911;a b&#7841;n hi&#7879;n &#273;&atilde; c&oacute; th&#7875; &#273;&#432;&#7907;c x&#7917; l&yacute; theo 2 c&aacute;ch sau.</p>

  <p><strong>Ph&#7843;n h&#7891;i ban &#273;&#7847;u:</strong></p>
  <div style="background:#fff5f5;border-left:4px solid #e53e3e;padding:12px 16px;margin:12px 0;border-radius:4px;">
    The Powerpoint-er: Ch&#432;a chuy&#7875;n th&#7875; data trong Excel th&agrave;nh chart trong PPT &#273;&#432;&#7907;c.
  </div>

  <p><strong>K&#7871;t qu&#7843; x&#7917; l&yacute;:</strong></p>
  <div style="background:#e8f5e9;border-left:4px solid #2e7d32;padding:12px 16px;margin:12px 0;border-radius:4px;">
    C&oacute; 2 c&aacute;ch &#273;&#7875; bi&#7871;n d&#7919; li&#7879;u th&agrave;nh chart:<br/><br/>
    <strong>C&aacute;ch 1:</strong> Prompt y&ecirc;u c&#7847;u t&#7841;o chart t&#7841;i m&#7909;c <strong>Enhance</strong> trong Powerpoint-er.<br/>
    <strong>C&aacute;ch 2:</strong> S&#7917; d&#7909;ng c&acirc;u l&#7879;nh <strong>&quot;Create HTML report&quot;</strong> tr&ecirc;n m&agrave;n h&igrave;nh T&Agrave;I Chat &#273;&#7875; t&#7841;o b&aacute;o c&aacute;o d&#7841;ng chart t&#7915; d&#7919; li&#7879;u.
  </div>

  <p>Ch&uacute;ng t&ocirc;i hy v&#7885;ng b&#7841;n s&#7869; ti&#7871;p t&#7909;c s&#7917; d&#7909;ng T&Agrave;I Studio v&agrave; &#273;&oacute;ng g&oacute;p &yacute; ki&#7871;n. M&#7895;i ph&#7843;n h&#7891;i c&#7911;a b&#7841;n &#273;&#7873;u t&#7841;o n&ecirc;n s&#7921; kh&aacute;c bi&#7879;t!</p>
</div>

<!-- Separator -->
<div style="margin:0 32px;border-top:2px solid #e53e3e;padding-top:8px;text-align:center;">
  <span style="background:#ffffff;padding:0 12px;font-size:12px;color:#e53e3e;font-weight:600;position:relative;top:-18px;">ENGLISH VERSION</span>
</div>

<!-- English -->
<div style="padding:12px 32px 24px;line-height:1.7;color:#333333;font-size:14px;">
  <p>Hi Ph&#432;&#417;ng,</p>

  <p>Your feedback counts!</p>

  <p>We're happy to let you know that your request can now be handled in two ways.</p>

  <p><strong>Original feedback:</strong></p>
  <div style="background:#fff5f5;border-left:4px solid #e53e3e;padding:12px 16px;margin:12px 0;border-radius:4px;">
    The Powerpoint-er: Cannot convert Excel data into charts inside a PPT.
  </div>

  <p><strong>Resolution:</strong></p>
  <div style="background:#e8f5e9;border-left:4px solid #2e7d32;padding:12px 16px;margin:12px 0;border-radius:4px;">
    There are 2 ways to turn your data into charts:<br/><br/>
    <strong>Option 1:</strong> Use a prompt in the <strong>Enhance</strong> section of Powerpoint-er to request chart generation.<br/>
    <strong>Option 2:</strong> Use the <strong>&quot;Create HTML report&quot;</strong> command on the T&Agrave;I Chat screen to generate a visual chart-based report from your data.
  </div>

  <p>We hope you'll continue using T&Agrave;I Studio and sharing your thoughts. Every piece of feedback makes a difference!</p>
</div>

<!-- Footer -->
<div style="padding:20px 32px;background:#f8f9fa;border-top:2px solid #e53e3e;font-size:13px;color:#666666;line-height:1.8;">
  <p><strong>N&#7871;u b&#7841;n c&#7847;n h&#7895; tr&#7907; th&ecirc;m / If you need further assistance:</strong></p>
  <p>
    <a href="mailto:anhdt26@techcombank.com.vn" style="color:#1a73e8;text-decoration:none;">anhdt26@techcombank.com.vn</a><br/>
    <a href="mailto:duongntt31@techcombank.com.vn" style="color:#1a73e8;text-decoration:none;">duongntt31@techcombank.com.vn</a><br/>
    <a href="mailto:thucnm@techcombank.com.vn" style="color:#1a73e8;text-decoration:none;">thucnm@techcombank.com.vn</a>
  </p>
  <p><a href="https://techcombank.sharepoint.com/sites/AITransformationHub/SitePages/T%C3%A0i_Studio.aspx" style="color:#1a73e8;text-decoration:none;">Kh&aacute;m ph&aacute; th&ecirc;m v&#7873; T&Agrave;I Studio / Discover more about T&Agrave;I Studio</a></p>
  <p style="margin-top:16px;">
    Tr&acirc;n tr&#7885;ng / Best regards,<br/>
    <strong>Team T&Agrave;I Studio</strong><br/>
    AI Foundation | Techcombank
  </p>
</div>

</div>
</body>
</html>
"""


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

    output_path = os.path.join(OUTPUT_DIR, "feedback_phuongntt2.eml")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(msg.as_string())

    print(f"Done! Email saved to: {output_path}")
    print("Double-click the .eml file to open in Outlook compose mode.")


if __name__ == "__main__":
    build_eml()