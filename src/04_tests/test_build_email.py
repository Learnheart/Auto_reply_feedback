"""
Module: inference.deliver (B3) — test
Architecture: docs/architecture.md §4.3 (routing → folder), §4.4 (chỉ solved=True mới được claim),
              §5 (Test: đọc lại .eml bằng email.parser, CI chạy offline hoàn toàn)
Impl doc: docs/impl-phase2-auto-feedback-flow.md §3.2 (bảng chọn template), §3.3 (lint style)
Plan: docs/2026-09-03/build-email-eml/plan.md §5 (T1..T6)

Không mạng, không LLM, không embedding: B3 là logic thuần + render.
"""
from __future__ import annotations

import io
from email import policy
from email.parser import Parser

import pytest

from conftest import load_module

be = load_module("src/03_inference/build_email.py", "build_email")
CFG = be.load_config()


def _row(**kw):
    base = {"id": "fb_0001", "agent": "the-powerpoint-er", "user": "hangtt@techcombank.com.vn",
            "content": "không tạo được chart trong slide", "label": "bug", "flag": "ok",
            "confidence": "0.72", "best_label": "bug", "solved": "False", "referenced": ""}
    base.update(kw)
    return base


# ── T1: bảng quyết định scenario (plan D1) ───────────────────────────────────
@pytest.mark.parametrize("label,flag,best,solved,expected", [
    ("bug",          "ok",             "bug",         True,  "how_to_answer"),
    ("bug",          "ok",             "bug",         False, "we_listen"),
    ("bug",          "ok",             "bug",         None,  "we_listen"),
    ("new_feature",  "low_confidence", "new_feature", True,  "how_to_answer"),
    ("new_feature",  "ok",            "new_feature",  False, "we_listen"),
    ("praise",       "ok",             "praise",      None,  "thank_you"),
    ("complain",     "ok",             "complain",    None,  "apology"),
    # flag=unclassified ⇒ nội dung dựng theo best_label (§4.3)
    ("unclassified", "unclassified",   "praise",      None,  "thank_you"),
    ("unclassified", "unclassified",   "bug",         False, "we_listen"),
    ("unclassified", "unclassified",   "",            None,  "neutral_ack"),
])
def test_pick_scenario(label, flag, best, solved, expected):
    assert be.pick_scenario(label, flag, best, solved) == expected


# ── T2: folder độc lập với template ──────────────────────────────────────────
@pytest.mark.parametrize("label,flag,best,folder", [
    ("bug", "ok", "bug", "bug"),
    ("new_feature", "low_confidence", "new_feature", "new_feature"),
    ("praise", "ok", "praise", "praise"),
    ("complain", "ok", "complain", "complain"),
    ("unclassified", "unclassified", "praise", "unclassified"),
    ("unclassified", "unclassified", "bug", "unclassified"),
])
def test_pick_folder(label, flag, best, folder):
    assert be.pick_folder(label, flag, best, CFG["folders"]) == folder


def test_unclassified_dung_template_best_label_nhung_van_o_folder_unclassified():
    """NOTE của user: nội dung theo nhãn score cao nhất, vị trí là folder unclassified."""
    ctx = be.build_context(_row(label="unclassified", flag="unclassified", best_label="praise"), CFG)
    assert ctx["scenario"] == "thank_you"
    assert ctx["folder"] == "unclassified"


# ── T3: solved=False KHÔNG được claim (§4.4, impl §3.2) ──────────────────────
def test_khong_solved_thi_khong_claim():
    ctx = be.build_context(_row(solved="False", referenced="một quote nào đó"), CFG)
    html = be.render_html(ctx, CFG)
    assert ctx["scenario"] == "we_listen"
    assert "#e8f5e9" not in html, "không được render box xanh khi chưa có nguồn"
    assert "đã có thể thực hiện được" not in html
    assert "already available" not in html
    assert ctx["resolution_text"] == "" and ctx["source_ref"] == ""


def test_solved_thi_co_box_xanh_va_citation():
    quote = "| Generate Presentation | Creates PPTX via The Powerpoint-er |"
    ctx = be.build_context(_row(solved="True", referenced=quote), CFG,
                           source_ref="docx:the-powerpoint-er@2026-05-28#Available Tools")
    html = be.render_html(ctx, CFG)
    assert ctx["scenario"] == "how_to_answer"
    assert "#e8f5e9" in html
    assert "docx:the-powerpoint-er@2026-05-28" in html
    assert "Nguồn:" in html and "Source:" in html


# ── T4: .eml đọc ngược được (§5) ─────────────────────────────────────────────
def test_eml_parse_nguoc():
    ctx = be.build_context(_row(), CFG)
    eml, html = be.build_eml(ctx, CFG)
    msg = Parser(policy=policy.default).parse(io.StringIO(eml))
    assert msg["From"] == CFG["meta"]["from"]
    assert msg["To"] == "hangtt@techcombank.com.vn"
    assert [a.addr_spec for a in msg["Cc"].addresses] == CFG["meta"]["cc"]
    assert msg["Subject"] == CFG["meta"]["subject"]
    assert msg["X-Unsent"] == "1"

    parts = list(msg.walk())
    types = [p.get_content_type() for p in parts]
    assert "text/html" in types and "image/png" in types
    img = next(p for p in parts if p.get_content_type() == "image/png")
    assert img["Content-ID"] == f'<{CFG["meta"]["logo_cid"]}>'
    assert len(img.get_payload(decode=True)) > 0
    assert f'cid:{CFG["meta"]["logo_cid"]}' in html


def test_song_ngu_va_block_internal():
    ctx = be.build_context(_row(), CFG)
    html = be.render_html(ctx, CFG)
    assert CFG["meta"]["separator_label"] in html            # VI ... separator ... EN
    assert "Xin chào" in html and "Hi " in html
    assert "INTERNAL" in html and "<!--INTERNAL-START-->" in html
    # nội dung feedback nguyên văn, xuất hiện ở CẢ hai nửa (plan D2: không dịch lời user)
    assert html.count("không tạo được chart trong slide") == 2
    assert "INTERNAL" not in be.render_html(ctx, CFG, include_internal=False)


# ── T5: placeholder thiếu ⇒ fail loud (plan D4) ──────────────────────────────
def test_placeholder_thieu_thi_raise():
    with pytest.raises(be.MissingPlaceholder):
        be.fill("Xin chào {name}, về {sprint}", {"name": "An"})
    assert be.fill("Xin chào {name}", {"name": "An"}) == "Xin chào An"


# ── T6: lint chỉ phán xét copy template, bỏ qua vùng verbatim (plan D5) ──────
def test_lint_bo_qua_em_dash_trong_vung_verbatim():
    quote = "User Guide — TÀI (Super Agent): bảng Available Tools liệt kê đủ chức năng."
    ctx = be.build_context(_row(solved="True", referenced=quote,
                                content="lỗi — không mở được file"), CFG,
                           source_ref="docx:taisuperagent@2026-05-28#Available Tools")
    be.lint_html(be.render_html(ctx, CFG))   # không được raise
    assert "—" not in be.lintable_text(be.render_html(ctx, CFG))


def test_lint_bat_em_dash_trong_copy_template():
    bad = {**CFG, "scenarios": {**CFG["scenarios"],
                                "we_listen": {**CFG["scenarios"]["we_listen"],
                                              "vi": {**CFG["scenarios"]["we_listen"]["vi"],
                                                     "closing": "Cảm ơn bạn — rất nhiều."}}}}
    ctx = be.build_context(_row(), bad)
    with pytest.raises(AssertionError, match="em-dash"):
        be.lint_html(be.render_html(ctx, bad))


def test_lint_bat_sai_casing_thuong_hieu():
    bad = {**CFG, "scenarios": {**CFG["scenarios"],
                                "we_listen": {**CFG["scenarios"]["we_listen"],
                                              "vi": {**CFG["scenarios"]["we_listen"]["vi"],
                                                     "opening": "Cảm ơn bạn đã dùng Tài Studio."}}}}
    ctx = be.build_context(_row(), bad)
    with pytest.raises(AssertionError, match="casing"):
        be.lint_html(be.render_html(ctx, bad))


# ── D6: idempotency theo tên file ────────────────────────────────────────────
def test_idempotency_khong_ghi_de(tmp_path):
    rows = [_row(id="fb_0001"), _row(id="fb_0002", label="praise", best_label="praise")]
    st1 = be.run_rows(rows, tmp_path, CFG)
    assert st1.written == 2 and st1.skipped == 0
    st2 = be.run_rows(rows, tmp_path, CFG)
    assert st2.written == 0 and st2.skipped == 2
    st3 = be.run_rows(rows, tmp_path, CFG, overwrite=True)
    assert st3.written == 2
    assert (tmp_path / "bug" / "fb_0001.eml").exists()
    assert (tmp_path / "praise" / "fb_0002.eml").exists()
    assert (tmp_path / "manifest.csv").exists()


def test_manifest_dung_ten_cot_feedback_processing(tmp_path):
    be.run_rows([_row()], tmp_path, CFG)
    import csv
    with io.open(tmp_path / "manifest.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["feedback_id"] == "fb_0001"
    assert rows[0]["scenario"] == "we_listen"
    assert rows[0]["draft_status"] == "drafted"
    assert rows[0]["eml_path"] == "bug/fb_0001.eml"


def test_ten_nguoi_nhan_khong_bia():
    assert be.display_name({"user": "hangtt@techcombank.com.vn"}) == "Hangtt"
    assert be.display_name({"user": "phuongntt2@techcombank.com.vn"}) == "Phuongntt"
    assert be.display_name({"user_name": "Phương", "user": "x@y.z"}) == "Phương"
    assert be.display_name({}) == "bạn"
