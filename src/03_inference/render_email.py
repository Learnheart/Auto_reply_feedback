"""Render PersonalizedResponse → (subject, HTML) song ngữ VI/EN + block INTERNAL cho PM.

Module: inference.deliver (B3) — lớp RENDER.
Architecture: docs/architecture.md §4.2 (draft HTML), §6.1 R4 (INTERNAL nằm trong body, phát hiện > ngăn chặn).
Impl: docs/impl-phase2-auto-feedback-flow.md §5 (block INTERNAL trên cùng, marker TAI-INTERNAL-DO-NOT-SEND), §3.
Template rule: template/skill_create_email.md + template/email_temp.py (gold song ngữ, footer, style).
Plan: docs/2026-08-27/ack-reply-eml/plan.md.

Khớp gold template `email_temp.py`: banner cid:tai_logo, note "English version below", block VI, separator
đỏ "ENGLISH VERSION", block EN (chỉ render khi có body_en — nhánh known_gap/KB chưa có EN thì VI-only),
footer đầy đủ (support contacts + link SharePoint + chữ ký team). LLM/bank sinh TEXT, template ráp HTML
(markup không vỡ được — impl §3.1); autoescape thủ công nội dung động.
"""

from __future__ import annotations

import html as _html

from respond import PersonalizedResponse

# Marker khóa cứng để Job C grep (impl §5). KHÔNG dùng chữ "INTERNAL" trần (xuất hiện trong văn thường).
INTERNAL_MARKER = "TAI-INTERNAL-DO-NOT-SEND"

# Subject hằng số cho MỌI email (skill:15). Phân biệt draft bằng folder + tên người nhận, không bằng subject.
SUBJECT = "[TÀI Studio] Your TÀI Studio feedback"

# Cấu hình footer/CC theo template/skill_create_email.md (nguồn sự thật về địa chỉ liên hệ).
CC_LIST = [
    "romeo.olympia@techcombank.com.vn",
    "anhdt26@techcombank.com.vn",
    "duongntt31@techcombank.com.vn",
    "thucnm@techcombank.com.vn",
]
SUPPORT_CONTACTS = [
    "anhdt26@techcombank.com.vn",
    "duongntt31@techcombank.com.vn",
    "thucnm@techcombank.com.vn",
]
SHAREPOINT_URL = (
    "https://techcombank.sharepoint.com/sites/AITransformationHub/SitePages/"
    "T%C3%A0i_Studio.aspx"
)

_RED = "#e53e3e"


def _paras(text: str) -> str:
    """Text nhiều đoạn (\\n\\n) → các <p> đã escape (autoescape: nội dung động không inject được HTML)."""
    paras = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    return "\n".join(f'<p style="margin:0 0 12px;">{_html.escape(p)}</p>' for p in paras)


# giữ tên cũ cho tương thích ngược (test/khác import _p_vi)
_p_vi = _paras
_p_en = _paras


def _feedback_box(feedback: str, *, vi: bool) -> str:
    """Box trích phản hồi gốc (neutral, viền đỏ trái) — cho cả praise/complaint không gây cảm giác 'lỗi'."""
    if not (feedback or "").strip():
        return ""
    label = "Phản hồi của bạn:" if vi else "Your feedback:"
    return (
        f'<p style="margin:0 0 6px;font-weight:600;">{label}</p>'
        f'<div style="background:#f8f9fa;border-left:4px solid {_RED};padding:12px 16px;margin:0 0 16px;'
        f'border-radius:4px;font-style:italic;">{_html.escape(feedback.strip())}</div>'
    )


def render_internal_block(resp: PersonalizedResponse, feedback_id: str) -> str:
    """Block INTERNAL đặt TRÊN CÙNG body — PM đọc & quyết định, rồi XÓA trước khi Send (R4/R6)."""
    cites = ", ".join(resp.citations) if resp.citations else "—"
    return (
        f'<div style="background:#fffbe6;border:2px dashed {_RED};padding:12px 16px;margin:0 0 20px;'
        f'font-size:12px;color:#663c00;">'
        f"<strong>{INTERNAL_MARKER}</strong> — PM đọc rồi XÓA khối này trước khi gửi.<br/>"
        f"feedback_id: {_html.escape(feedback_id)}<br/>"
        f"intent: {_html.escape(str(resp.intent_id))} · action: {_html.escape(str(resp.action_type))} · "
        f"flag: {_html.escape(resp.flag)} · template: {_html.escape(resp.template)}<br/>"
        f"citations: {_html.escape(cites)}<br/>"
        f"note: {_html.escape(resp.internal_note)}"
        f"</div>"
    )


def _footer_html() -> str:
    contacts = "<br/>".join(
        f'<a href="mailto:{c}" style="color:#1a73e8;text-decoration:none;">{c}</a>' for c in SUPPORT_CONTACTS
    )
    return f"""\
  <div style="padding:20px 32px;background:#f8f9fa;border-top:2px solid {_RED};font-size:13px;color:#666666;line-height:1.8;">
    <p style="margin:0 0 8px;"><strong>Nếu bạn cần hỗ trợ thêm / If you need further assistance:</strong></p>
    <p style="margin:0 0 12px;">{contacts}</p>
    <p style="margin:0 0 12px;"><a href="{SHAREPOINT_URL}" style="color:#1a73e8;text-decoration:none;">Khám phá thêm về TÀI Studio / Discover more about TÀI Studio</a></p>
    <p style="margin:0;">Trân trọng / Best regards,<br/><strong>Team TÀI Studio</strong><br/>AI Foundation | Techcombank</p>
  </div>"""


def render_html(
    resp: PersonalizedResponse,
    feedback_id: str,
    *,
    include_internal: bool = True,
    show_feedback_box: bool = True,
) -> str:
    """PersonalizedResponse → HTML email song ngữ (khung thương hiệu + block INTERNAL trên cùng).

    Có `body_en` ⇒ render đủ VI + separator + EN (gold). Không có ⇒ VI-only (nhánh known_gap/KB Phase sau).
    """
    internal = render_internal_block(resp, feedback_id) if include_internal else ""
    has_en = bool((resp.body_en or "").strip())
    lang_note = (
        f'<div style="text-align:right;padding:12px 32px 0;font-size:12px;color:#888888;font-style:italic;">'
        f"English version below</div>"
        if has_en
        else ""
    )
    fb_vi = _feedback_box(resp.feedback, vi=True) if show_feedback_box else ""

    en_section = ""
    if has_en:
        fb_en = _feedback_box(resp.feedback, vi=False) if show_feedback_box else ""
        en_section = f"""\
  <div style="margin:0 32px;border-top:2px solid {_RED};padding-top:8px;text-align:center;">
    <span style="background:#ffffff;padding:0 12px;font-size:12px;color:{_RED};font-weight:600;position:relative;top:-18px;">ENGLISH VERSION</span>
  </div>
  <div style="padding:12px 32px 24px;line-height:1.7;color:#333333;font-size:14px;">
    {fb_en}
    {_paras(resp.body_en)}
  </div>"""

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:20px;background:#f5f5f5;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;">
  {internal}
  <div style="padding:24px 32px 0;text-align:center;">
    <img src="cid:tai_logo" style="height:48px;width:auto;" alt="TÀI Studio" />
  </div>
  {lang_note}
  <div style="padding:24px 32px;line-height:1.7;color:#333333;font-size:14px;">
    {fb_vi}
    {_paras(resp.body_vi)}
  </div>
{en_section}
{_footer_html()}
</div>
</body>
</html>"""


def strip_internal_block(html: str) -> str:
    """Bỏ block INTERNAL khỏi HTML — chạy TRƯỚC lint/outcome-sync (impl §3.3/§5). Cắt theo cặp marker div.

    Tối giản: cắt <div ...INTERNAL_MARKER...> tới </div> đầu tiên. Body PM đã xóa tay ⇒ không còn marker,
    hàm này idempotent (không có marker thì trả nguyên).
    """
    i = html.find(INTERNAL_MARKER)
    if i == -1:
        return html
    start = html.rfind("<div", 0, i)
    end = html.find("</div>", i)
    if start == -1 or end == -1:
        return html
    return html[:start] + html[end + len("</div>"):]
