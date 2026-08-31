"""Test B3 deliver — offline, KHÔNG cần Azure cred / mạng.

Plan: docs/2026-08-26/deliver-outlook-graph/plan.md (R7).
Phủ: build_message schema (X-Feedback-Id), folder-theo-category, block INTERNAL + strip, EmlSink + sidecar.
Chạy: python tests_delivery.py   (hoặc pytest)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from deliver import UNCLASSIFIED_FOLDER, EmlSink, build_draft, folder_for
from graph_client import FEEDBACK_ID_PROP, build_message
from render_email import INTERNAL_MARKER, SUBJECT, render_html, strip_internal_block
from respond import PersonalizedResponse


def _resp(intent_id="bug_core_function_broken", action="known_gap", flag="ok"):
    return PersonalizedResponse(
        feedback="app lỗi không gen slide",
        intent_id=intent_id,
        action_type=action,
        flag=flag,
        template="we_listen",
        body_vi="Cảm ơn bạn đã phản hồi cho TÀI Studio.\n\nNhóm đã ghi nhận và sẽ cải thiện.",
        citations=["TSFAI-123"],
        internal_note="known_gap + backlog_hit=TSFAI-123",
    )


def test_folder_is_category_name():
    assert folder_for(_resp(intent_id="request_ux_and_ui_improvement")) == "request_ux_and_ui_improvement"


def test_unclassified_routes_to_sink_folder():
    assert folder_for(_resp(intent_id=None, action=None, flag="unclassified")) == UNCLASSIFIED_FOLDER


def test_build_message_embeds_feedback_id_and_recipient():
    msg = build_message(
        subject=SUBJECT, html_body="<p>hi</p>", to_email="u@x.vn", feedback_id="fb_0007"
    )
    assert msg["subject"] == SUBJECT
    assert msg["body"]["contentType"] == "HTML"
    assert msg["toRecipients"][0]["emailAddress"]["address"] == "u@x.vn"
    # X-Feedback-Id là khóa cứng cho outcome-sync (R5)
    prop = msg["singleValueExtendedProperties"][0]
    assert prop["id"] == FEEDBACK_ID_PROP
    assert prop["value"] == "fb_0007"
    # không có logo asset ⇒ không có attachments (B-1 — không crash)
    assert "attachments" not in msg


def test_render_has_internal_block_and_strip_removes_it():
    html = render_html(_resp(), "fb_0007")
    assert INTERNAL_MARKER in html
    assert "fb_0007" in html
    clean = strip_internal_block(html)
    assert INTERNAL_MARKER not in clean
    assert "Team TÀI Studio" in clean          # body thật vẫn còn
    # idempotent: strip lần 2 không đổi
    assert strip_internal_block(clean) == clean


def test_eml_sink_writes_clean_body_and_sidecar():
    with tempfile.TemporaryDirectory() as d:
        draft = build_draft(_resp(intent_id="issue_usage_limit_and_system_policy"), "fb_0011", "u@x.vn")
        ref = EmlSink(Path(d)).deliver(draft)
        eml = Path(ref.location)
        assert eml.exists() and eml.suffix == ".eml"
        # folder = category name
        assert eml.parent.name == "issue_usage_limit_and_system_policy"
        body = eml.read_text(encoding="utf-8")
        assert INTERNAL_MARKER not in body                 # body gửi user PHẢI sạch (D3)
        assert "X-Feedback-Id: fb_0011" in body
        # sidecar giữ nội dung INTERNAL cạnh .eml
        sidecar = eml.parent / "fb_0011.internal.md"
        assert sidecar.exists() and INTERNAL_MARKER in sidecar.read_text(encoding="utf-8")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} test PASS")


if __name__ == "__main__":
    _run_all()
