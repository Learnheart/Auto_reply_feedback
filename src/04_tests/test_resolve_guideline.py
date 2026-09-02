"""
Module: inference.draft (B2) — test offline cho bước 1 §4.4 (guideline resolve) + loader docx (Job A)
Architecture: docs/architecture.md §4.4 (cổng an toàn: chỉ tin khoá tra ngược được), §4.6
              (userguide_page), §5 (pytest + mock LLM, không cần LLM thật)
Plan: docs/2026-09-03/guideline-resolve-batch/plan.md (Acceptance G-1..G-3)

Chạy:  python -m pytest src/04_tests/test_resolve_guideline.py -v
"""
from __future__ import annotations

import csv
import io

import pytest

from conftest import REPO_ROOT, load_module

rg = load_module("src/03_inference/resolve_guideline.py", "b2_resolve_guideline")

GOLD_INTENT_CSV = REPO_ROOT / "data" / "golden" / "feedback_gold.csv"


@pytest.fixture(scope="module")
def pages():
    return rg.load_pages()


# ── G-1: loader docx + map agent ─────────────────────────────────────────────
class TestLoader:
    def test_13_page_tu_docx(self, pages):
        assert len(pages.by_slug) == 13
        for p in pages.by_slug.values():
            assert p.page_id.startswith("docx:")
            assert p.markdown.startswith("#"), p.title
            assert p.version

    def test_moi_agent_trong_gold_map_duoc_tru_canvas(self, pages):
        with io.open(GOLD_INTENT_CSV, encoding="utf-8-sig") as f:
            agents = {r["agent"] for r in csv.DictReader(f) if r["label"] in rg.KNOWLEDGE_LABELS}
        for a in agents:
            docs = rg.pages_for_agent(pages, a)
            if a == "the-canvas-designer":
                assert docs == []
            else:
                assert docs, f"agent {a} không map được tài liệu"

    def test_agent_nen_tang_nap_nhieu_page(self, pages):
        assert [p.page_id for p in rg.pages_for_agent(pages, "tai")] == \
            ["docx:taisuperagent", "docx:taistudiouserguide", "docx:taistudiogenui", "docx:office365en"]
        assert [p.page_id for p in rg.pages_for_agent(pages, "tai-studio")] == \
            ["docx:taistudiouserguide", "docx:taistudiogenui"]

    def test_bang_docx_duoc_giu(self, pages):
        assert "| " in pages.by_slug["taistudiogenui"].markdown


# ── G-2: gate quote ──────────────────────────────────────────────────────────
class TestQuoteGate:
    def test_quote_verbatim_khop_va_ra_heading(self, pages):
        docs = rg.pages_for_agent(pages, "the-powerpoint-er")
        hit = rg.verify_quote('click "Regenerate from outline" to restore the initial generated version', docs)
        assert hit.ok and hit.page_id == "docx:powerpointer" and hit.heading.startswith("Step 4")

    def test_chuan_hoa_khoang_trang_va_dau_ngoac(self, pages):
        docs = rg.pages_for_agent(pages, "the-powerpoint-er")
        assert rg.verify_quote("Click  “REGENERATE FROM OUTLINE”   to restore the initial generated version", docs).ok

    def test_quote_bia_bi_chan(self, pages):
        docs = rg.pages_for_agent(pages, "the-powerpoint-er")
        assert not rg.verify_quote("You can insert images by clicking the Image button", docs).ok

    def test_quote_qua_ngan_bi_chan(self, pages):
        assert not rg.verify_quote("Overview", rg.pages_for_agent(pages, "the-translator")).ok

    def test_ellipsis_cuoi_quote_duoc_bo(self, pages):
        docs = rg.pages_for_agent(pages, "the-powerpoint-er")
        hit = rg.verify_quote("The top bar provides quick editing actions, including adjusting font size...", docs)
        assert hit.ok and hit.score == 1.0

    def test_anchor_gop_heading_van_khop_va_tra_dong_that(self, pages):
        docs = rg.pages_for_agent(pages, "the-brainstormer")
        q = "Output export: At the top-right corner, there are 2 output options: - Copy Output Content"
        assert not rg.verify_quote(q, docs).ok                       # strict trượt (LLM gộp heading)
        hit = rg.verify_quote(q, docs, anchor=True)
        assert hit.ok and hit.heading == "Output export" and 0 < hit.score < 1
        assert hit.quote.startswith("At the top-right corner")     # dòng tài liệu THẬT
        assert rg.verify_quote(hit.quote, docs).ok                  # verbatim

    def test_anchor_khong_cuu_quote_bia(self, pages):
        docs = rg.pages_for_agent(pages, "the-powerpoint-er")
        assert not rg.verify_quote("You can insert images by clicking the Image button on the toolbar",
                                   docs, anchor=True).ok
        # nửa thật nửa bịa, phần chung < 40 ký tự và < 80% quote ⇒ chặn
        assert not rg.verify_quote("You can add/remove slides (+ Add slide / × to remove)", docs, anchor=True).ok

    def test_fuzzy_tra_ve_doan_tai_lieu_that(self, pages):
        docs = rg.pages_for_agent(pages, "the-translator")
        wrong = "Cancel a long translation by refreshing the page (the server continue processing but the UI reset)"
        assert not rg.verify_quote(wrong, docs).ok
        hit = rg.verify_quote(wrong, docs, fuzzy=0.9)
        assert hit.ok and hit.quote.startswith("- Cancel a long translation by refreshing the page")


# ── Batch align + gate trong resolve_batch (fake LLM) ────────────────────────
def _fake_llm(script: dict[int, dict]):
    """LLM giả: trả kết quả theo index trong lô; ghi lại số call + prompt."""
    calls: list[str] = []

    def chat(system: str, user: str) -> dict:
        calls.append(user)
        if system is rg.VERIFY_PROMPT:
            return {"confirmed": "Regenerate" in user, "reason": "test"}
        n = user.count("\n[")  # số item trong lô
        return {"results": [script.get(k, {"index": k, "solved": False, "quote": "", "reason": "-"}) | {"index": k}
                            for k in range(n)]}

    chat.calls = calls  # type: ignore[attr-defined]
    return chat


FB = [
    {"id": "a", "agent": "the-powerpoint-er", "label": "new_feature", "content": "muốn quay lại version đầu"},
    {"id": "b", "agent": "the-powerpoint-er", "label": "new_feature", "content": "cho chèn ảnh vào slide"},
    {"id": "c", "agent": "the-powerpoint-er", "label": "bug", "content": "lỗi 502"},
    {"id": "d", "agent": "the-canvas-designer", "label": "bug", "content": "không mở được"},
]


class TestResolveBatch:
    def test_gate_va_align(self, pages):
        llm = _fake_llm({
            0: {"solved": True, "quote": 'click “Regenerate from outline” to restore the initial generated version', "reason": "r"},
            1: {"solved": True, "quote": "Image insertion is fully supported via the toolbar", "reason": "bịa"},
            2: {"solved": False, "quote": "", "reason": "none"},
        })
        res = rg.resolve_batch(FB, pages, llm, batch_size=10, log=lambda s: None)
        assert [r.solved for r in res] == [True, False, False, False]
        assert res[0].match_type == "how_to" and res[0].source_ref.startswith("docx:powerpointer@2026-05-28#Step 4")
        assert res[1].gate == "quote_not_found" and res[1].referenced == ""   # G-2: quote bịa ⇒ False
        assert res[3].gate == "no_doc"                                       # canvas-designer không tài liệu
        assert len(llm.calls) == 1                                           # 1 call cho cả lô powerpoint-er

    def test_limitation_giu_quote_nhung_solved_false(self, pages):
        llm = _fake_llm({1: {"solved": False, "quote": "Image insertion is not supported — slides contain text and vector graphics only", "reason": "lim"}})
        res = rg.resolve_batch(FB[:3], pages, llm, log=lambda s: None)
        assert res[1].solved is False and res[1].match_type == "limitation" and res[1].referenced

    def test_batch_size_chia_dung_so_call(self, pages):
        llm = _fake_llm({})
        rg.resolve_batch(FB[:3], pages, llm, batch_size=2, log=lambda s: None)
        assert len(llm.calls) == 2

    def test_verify_pass_ha_solved_khi_khong_confirm(self, pages):
        llm = _fake_llm({
            0: {"solved": True, "quote": 'click “Regenerate from outline” to restore the initial generated version', "reason": "r"},
            2: {"solved": True, "quote": "Export requires a modern browser (Chrome, Edge, Firefox)", "reason": "x"},
        })
        res = rg.resolve_batch(FB[:3], pages, llm, verify=True, log=lambda s: None)
        assert res[0].solved is True
        assert res[2].solved is False and res[2].gate == "demoted_by_verify"

    def test_llm_loi_khong_claim(self, pages):
        def boom(system, user):
            raise RuntimeError("down")
        res = rg.resolve_batch(FB[:2], pages, boom, log=lambda s: None)
        assert all(not r.solved and r.gate == "llm_error" for r in res)


# ── G-3: output CSV = input + đúng 2 cột ─────────────────────────────────────
def test_output_csv_contract(tmp_path, pages):
    src = tmp_path / "in.csv"
    with io.open(src, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "agent", "label", "content"])
        w.writeheader()
        w.writerows(FB + [{"id": "p", "agent": "tai", "label": "praise", "content": "hay quá"}])
    out = tmp_path / "out.csv"
    llm = _fake_llm({0: {"solved": True, "quote": 'click “Regenerate from outline” to restore the initial generated version', "reason": "r"}})
    rg.run_file(src, out, llm, log=lambda s: None)
    with io.open(out, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == ["id", "agent", "label", "content", "solved", "referenced"]
    assert [r["id"] for r in rows] == ["a", "b", "c", "d", "p"]        # thứ tự giữ nguyên
    assert rows[0]["solved"] == "True" and rows[0]["referenced"]
    assert rows[4]["solved"] == "" and rows[4]["referenced"] == ""      # praise không đi nhánh knowledge
    assert out.with_suffix(".csv.debug.jsonl").exists()
