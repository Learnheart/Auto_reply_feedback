"""Test routing B2 (respond.py) — thuần offline, KHÔNG cần LM Studio/Scholar/MCP.

Plan: docs/2026-08-26/inference-classify-respond/plan.md (R6).
Phủ đúng bảng impl §3.2: (action_type, rag_hit/backlog_hit, flag) → template + nội dung.
Chạy: python tests_respond.py   (hoặc pytest tests_respond.py)
"""

from __future__ import annotations

from classify import FLAG_LOW, FLAG_OK, FLAG_UNCLASSIFIED, Classification
from knowledge import (
    BacklogMatch,
    UserguideAnswer,
    answer_from_backlog_batch,
    answer_from_userguide,
    answer_from_userguide_batch,
)
from respond import TPL_APOLOGY, TPL_LISTEN, TPL_NEUTRAL, TPL_RESOLVED, respond
from userguide_store import build_from_confluence_pages  # 02_knowledge trên path (knowledge.py insert)


def _cls(action_type, flag=FLAG_OK, intent="some_intent"):
    assigned = None if flag == FLAG_UNCLASSIFIED else intent
    return Classification(
        feedback="feedback thử",
        intent_id=None if assigned is None else intent,
        action_type=None if assigned is None else action_type,
        confidence=0.7,
        flag=flag,
        best_intent_id=intent,
        best_confidence=0.7,
        evidence="feedback thử",
    )


def test_answer_from_kb_hit_resolves():
    ug = UserguideAnswer(hit=True, answer="Bạn vào menu > Tạo mục lục tự động.", page_id="p1", version=3)
    r = respond(_cls("answer_from_kb"), userguide=ug)
    assert r.template == TPL_RESOLVED
    assert "mục lục tự động" in r.body_vi
    assert r.citations == ["userguide:p1@3"]


def test_answer_from_kb_no_hit_degrades_not_resolved():
    # Luật cứng impl §3.2: 0 hit ⇒ we_listen, KHÔNG claim đã giải quyết.
    ug = UserguideAnswer(hit=False, answer="", page_id=None)
    r = respond(_cls("answer_from_kb"), userguide=ug)
    assert r.template == TPL_LISTEN
    assert "giải quyết" not in r.body_vi

    # userguide=None (không gọi được) cũng phải suy giảm, không nổ.
    r2 = respond(_cls("answer_from_kb"), userguide=None)
    assert r2.template == TPL_LISTEN


def test_known_gap_backlog_hit_promises_development():
    bl = BacklogMatch(hit=True, jira_key="TSFAI-123", summary="Upload nhiều file", status="In Progress", score=0.8)
    r = respond(_cls("known_gap"), backlog=bl)
    assert r.template == TPL_LISTEN
    assert "phát triển" in r.body_vi
    assert r.citations == ["TSFAI-123"]


def test_known_gap_no_backlog_hit_acknowledges_improvement():
    bl = BacklogMatch(hit=False, score=0.3)
    r = respond(_cls("known_gap"), backlog=bl)
    assert r.template == TPL_LISTEN
    assert "cải thiện" in r.body_vi
    assert r.citations == []


def test_ack_only_thanks():
    r = respond(_cls("ack_only"))
    assert r.template == TPL_NEUTRAL
    assert "Cảm ơn" in r.body_vi


# ── Bank tĩnh (reply_samples.yaml) — 3 nhánh ack song ngữ + placeholder (plan 2026-08-27) ──
def test_praise_uses_thank_you_bank_bilingual():
    r = respond(_cls("ack_only", intent="praise"))
    assert r.template == TPL_NEUTRAL
    assert r.body_vi and r.body_en                    # song ngữ VI + EN
    assert "{name}" in r.body_vi and "{name}" in r.body_en   # deliver.build_draft điền
    assert "{feedback_summary}" not in r.body_vi      # respond đã điền


def test_complaint_uses_apology_bank():
    r = respond(_cls("ack_only", intent="complaint"))
    assert r.template == TPL_APOLOGY
    assert r.body_en
    assert ("xin lỗi" in r.body_vi.lower()) or ("tiếc" in r.body_vi.lower())


def test_unclassified_uses_neutral_bank_bilingual():
    r = respond(_cls("known_gap", flag=FLAG_UNCLASSIFIED))
    assert r.intent_id is None and r.template == TPL_NEUTRAL
    assert r.body_vi and r.body_en
    assert "{name}" in r.body_vi


def test_ack_pick_is_deterministic():
    # cùng nội dung feedback ⇒ cùng mẫu (idempotent qua nhiều lần chạy).
    a = respond(_cls("ack_only", intent="praise"))
    b = respond(_cls("ack_only", intent="praise"))
    assert a.body_vi == b.body_vi


def test_unclassified_neutral_no_knowledge():
    # flag=unclassified: không đoán nhãn, không RAG, không backlog (§4.3 + impl §5).
    r = respond(_cls("known_gap", flag=FLAG_UNCLASSIFIED))
    assert r.intent_id is None
    assert r.template == TPL_NEUTRAL
    assert r.action_type is None


def test_low_confidence_flag_annotated_internal():
    ug = UserguideAnswer(hit=True, answer="hướng dẫn.", page_id="p9", version=1)
    r = respond(_cls("answer_from_kb", flag=FLAG_LOW), userguide=ug)
    assert "chưa chắc chắn" in r.internal_note


# ── Routing agent→page (whole-page, v3.1) — llm inject để test offline ────────
def _fake_pages():
    raw = [
        {"page_id": "395774795", "title": "TÀI Studio — User guide", "version": 1, "markdown": "overview"},
        {"page_id": "1", "title": "The Translator", "version": 2, "markdown": "Cách đổi ngôn ngữ output..."},
    ]
    return build_from_confluence_pages(raw, "395774795")


def test_route_mapped_agent_answerable_hits():
    pages = _fake_pages()
    llm = lambda fb, title, md: {"answerable": True, "answer": "Vào Settings > Output language."}
    ans = answer_from_userguide("sao đổi ngôn ngữ", "the-translator", pages, llm=llm)
    assert ans.hit is True
    assert ans.page_id == "1" and ans.version == 2      # citation page_id@version


def test_route_mapped_agent_not_answerable_degrades():
    pages = _fake_pages()
    llm = lambda fb, title, md: {"answerable": False, "answer": ""}
    ans = answer_from_userguide("câu hỏi lạc đề", "the-translator", pages, llm=llm)
    assert ans.hit is False                              # ⇒ respond suy giảm we_listen
    r = respond(_cls("answer_from_kb"), userguide=ans)
    assert r.template == TPL_LISTEN and "giải quyết" not in r.body_vi


def test_route_unmapped_agent_no_page_degrades():
    pages = _fake_pages()
    called = []
    llm = lambda *a: called.append(1) or {"answerable": True, "answer": "x"}
    ans = answer_from_userguide("bất kỳ", "some-new-agent", pages, llm=llm)
    assert ans.hit is False and ans.page_id is None
    assert not called                                   # không map được page ⇒ KHÔNG gọi LLM


# ── Batch theo agent (whole-page, plan §Chi phí 1b) — llm inject để test offline ──
def test_batch_answers_align_and_gate():
    pages = _fake_pages()
    fbs = ["đổi ngôn ngữ?", "câu lạc đề", "xuất file thế nào?"]

    def llm(feedbacks, title, md):
        return {"answers": [
            {"index": 0, "answerable": True, "answer": "Vào Settings > Output language."},
            {"index": 1, "answerable": False, "answer": ""},
            {"index": 2, "answerable": True, "answer": "Bấm Export."},
        ]}

    ans = answer_from_userguide_batch(fbs, "the-translator", pages, llm=llm)
    assert [a.hit for a in ans] == [True, False, True]        # gate answerable giữ per-item
    assert ans[0].page_id == "1" and ans[0].version == 2       # citation vẫn đúng page
    assert ans[1].answer == ""


def test_batch_unmapped_agent_all_miss_no_llm():
    pages = _fake_pages()
    called = []
    llm = lambda *a: called.append(1) or {"answers": []}
    ans = answer_from_userguide_batch(["x", "y"], "unknown-agent", pages, llm=llm)
    assert [a.hit for a in ans] == [False, False]
    assert not called                                          # không map page ⇒ KHÔNG gọi LLM


def test_batch_missing_index_is_safe_miss():
    # LLM trả thiếu index ⇒ phần tử đó hit=False (an toàn: respond suy giảm we_listen).
    pages = _fake_pages()
    llm = lambda fbs, t, m: {"answers": [{"index": 0, "answerable": True, "answer": "ok"}]}
    ans = answer_from_userguide_batch(["a", "b"], "the-translator", pages, llm=llm)
    assert [a.hit for a in ans] == [True, False]


def test_batch_respects_batch_size():
    # 3 feedback, batch_size=2 ⇒ 2 lô ⇒ LLM gọi 2 lần; kết quả vẫn theo thứ tự vào.
    pages = _fake_pages()
    calls = []

    def llm(feedbacks, title, md):
        calls.append(len(feedbacks))
        return {"answers": [{"index": i, "answerable": True, "answer": f"a{i}"} for i in range(len(feedbacks))]}

    ans = answer_from_userguide_batch(["a", "b", "c"], "the-translator", pages, llm=llm, batch_size=2)
    assert calls == [2, 1]
    assert [a.answer for a in ans] == ["a0", "a1", "a0"]       # index reset mỗi lô


# ── Backlog whole-set → LLM theo lô (v3.2) — llm inject để test offline ──────────
_ISSUES = [
    {"jira_key": "T-1", "summary": "upload multiple file", "description": "", "status": "In Progress"},
    {"jira_key": "T-2", "summary": "change theme color", "description": "", "status": "To Do"},
]


def test_backlog_batch_matched_resolves_from_list():
    # LLM chỉ trả backlog_ref (chỉ số); ta TỰ resolve jira_key/status từ danh sách (không tin LLM echo).
    llm = lambda fbs, items: {"matches": [{"index": 0, "backlog_ref": 0}]}
    ms = answer_from_backlog_batch(["cho upload nhiều file"], _ISSUES, llm=llm)
    assert ms[0].hit and ms[0].jira_key == "T-1" and ms[0].status == "In Progress"
    # đủ để respond hứa 'sẽ phát triển' + trích ticket.
    r = respond(_cls("known_gap"), backlog=ms[0])
    assert r.template == TPL_LISTEN and r.citations == ["T-1"]


def test_backlog_batch_null_ref_is_miss():
    # backlog_ref=null ⇒ hit=False ⇒ ghi nhận chung, KHÔNG hứa nhầm 'team sẽ làm'.
    llm = lambda fbs, items: {"matches": [{"index": 0, "backlog_ref": None}]}
    ms = answer_from_backlog_batch(["yêu cầu lạ không có trong backlog"], _ISSUES, llm=llm)
    assert ms[0].hit is False
    r = respond(_cls("known_gap"), backlog=ms[0])
    assert r.template == TPL_LISTEN and r.citations == []


def test_backlog_batch_missing_index_is_safe_miss():
    llm = lambda fbs, items: {"matches": [{"index": 0, "backlog_ref": 1}]}   # thiếu index 1
    ms = answer_from_backlog_batch(["a", "b"], _ISSUES, llm=llm)
    assert [m.hit for m in ms] == [True, False]


def test_backlog_batch_out_of_range_ref_is_safe_miss():
    # LLM trả chỉ số ngoài phạm vi ⇒ hit=False (không nổ, không hứa bừa).
    llm = lambda fbs, items: {"matches": [{"index": 0, "backlog_ref": 9}]}
    ms = answer_from_backlog_batch(["x"], _ISSUES, llm=llm)
    assert ms[0].hit is False


def test_backlog_batch_empty_backlog_all_miss_no_llm():
    called = []
    llm = lambda *a: called.append(1) or {"matches": []}
    ms = answer_from_backlog_batch(["x", "y"], [], llm=llm)
    assert [m.hit for m in ms] == [False, False]
    assert not called                                          # backlog rỗng ⇒ KHÔNG gọi LLM


def test_backlog_batch_respects_batch_size():
    # 3 feedback, batch_size=2 ⇒ 2 lô ⇒ LLM gọi 2 lần; kết quả vẫn theo thứ tự vào.
    calls = []

    def llm(feedbacks, items):
        calls.append(len(feedbacks))
        return {"matches": [{"index": i, "backlog_ref": 0} for i in range(len(feedbacks))]}

    ms = answer_from_backlog_batch(["a", "b", "c"], _ISSUES, llm=llm, batch_size=2)
    assert calls == [2, 1]
    assert all(m.hit and m.jira_key == "T-1" for m in ms)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"\n{len(fns)} test PASS")


if __name__ == "__main__":
    _run_all()
