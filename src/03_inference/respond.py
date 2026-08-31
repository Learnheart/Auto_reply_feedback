"""B2 respond — định tuyến theo action_type → câu trả lời cá nhân hoá (phần TEXT).

Module: inference.draft (B2) — nửa GENERATE (chỉ nội dung text; render HTML/deliver là Phase 2 §3/§6).
Architecture: docs/architecture.md §3 (inference.draft), §4.3 (flag unclassified → ack trung tính).
Impl: docs/impl-phase2-auto-feedback-flow.md §3.2 (bảng chọn template theo (action_type, rag_hit)),
  §5 (nhánh unclassified bỏ RAG + backlog).
Plan: docs/2026-08-26/inference-classify-respond/plan.md (R3, D1, D4).

`respond()` THUẦN & test được offline: nhận Classification + kết quả knowledge ĐÃ fetch sẵn
(UserguideAnswer / BacklogMatch), quyết định template + sinh body. Pipeline lo phần fetch (biết
action_type nào cần gọi gì) để respond không phụ thuộc mạng.

Luật cứng (impl §3.2): answer_from_kb mà KHÔNG có rag hit ⇒ suy giảm về we_listen, KHÔNG khẳng định
"đã giải quyết" (nếu không là nói dối user một cách tự tin — failure mode R6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from classify import FLAG_LOW, FLAG_UNCLASSIFIED, Classification
from knowledge import BacklogMatch, UserguideAnswer
from reply_samples import (
    GROUP_APOLOGY,
    GROUP_NEUTRAL,
    GROUP_THANK_YOU,
    join_copy,
    pick,
)

# template (impl §3.2). Trục thật chỉ 2 khung + biến thể trung tính; KHÔNG per-intent.
TPL_RESOLVED = "we_resolved"          # có câu trả lời cụ thể (userguide)
TPL_LISTEN = "we_listen"              # ghi nhận + có định hướng (backlog / roadmap)
TPL_NEUTRAL = "we_listen_neutral"     # ack trung tính, không hứa mốc (praise / unclassified)
TPL_APOLOGY = "we_apologize"          # ack_only sắc thái TIÊU CỰC → xin lỗi (khác cảm ơn)

# ack_only KHÔNG đủ mịn để phân cảm-ơn vs xin-lỗi. Category (= kịch bản) mới là nguồn sự thật:
# intent_id do LLM đặt theo scenario (vd 'vague_negative_sentiment') → dò marker tiêu cực trên slug.
_NEGATIVE_MARKERS = (
    "negative", "complaint", "apolog", "dissatisf", "unhappy", "frustrat", "angry",
    "tieu_cuc", "phan_nan", "xin_loi", "buc_xuc", "that_vong", "kem",
)


def _is_negative_scenario(intent_id: str | None) -> bool:
    """ack_only nhánh xin lỗi? Dò marker tiêu cực trên intent_id (slug scenario của LLM)."""
    return any(m in (intent_id or "").lower() for m in _NEGATIVE_MARKERS)


@dataclass
class PersonalizedResponse:
    feedback: str
    intent_id: str | None
    action_type: str | None
    flag: str
    template: str
    body_vi: str
    body_en: str = ""                                     # song ngữ (nhánh ack); known_gap/KB để rỗng (Phase 2)
    citations: list[str] = field(default_factory=list)   # userguide markers / jira_key
    internal_note: str = ""                               # giải thích định tuyến cho PM (block INTERNAL)


# ── Copy nhánh ack lấy từ bank tĩnh (reply_samples.yaml) ──────────────────────
_SUMMARY_MAX = 160


def _summarize(feedback: str) -> str:
    """Rút gọn feedback để nhét vào {feedback_summary} (PM soát lại). Gộp khoảng trắng + cắt + bỏ dấu cuối."""
    s = " ".join((feedback or "").split()).strip().rstrip(".!?…")
    return (s[:_SUMMARY_MAX].rstrip() + "…") if len(s) > _SUMMARY_MAX else s


def _ack_bodies(group: str, feedback: str) -> tuple[str, str]:
    """Chọn 1 mẫu bank (deterministic theo nội dung) → (body_vi, body_en), điền {feedback_summary}.

    GIỮ NGUYÊN {name} để deliver.build_draft điền (respond không biết recipient).
    """
    sample = pick(group, feedback)
    summary = _summarize(feedback)
    vi = join_copy(sample["vi"]).replace("{feedback_summary}", summary)
    en = join_copy(sample["en"]).replace("{feedback_summary}", summary)
    return vi, en


# ── status Jira → cụm mốc thời gian (known_gap khớp backlog) ─────────────────
def _timeline_from_status(status: str | None) -> str:
    s = (status or "").lower()
    if any(k in s for k in ("progress", "development", "doing", "đang")):
        return "hiện đang được nhóm phát triển"
    if any(k in s for k in ("review", "testing", "qa", "uat")):
        return "đang trong giai đoạn kiểm thử trước khi phát hành"
    if any(k in s for k in ("to do", "todo", "backlog", "open", "new")):
        return "đã nằm trong kế hoạch phát triển của nhóm"
    return "đang được nhóm xem xét để đưa vào phát triển"


def respond(
    cls: Classification,
    *,
    userguide: UserguideAnswer | None = None,
    backlog: BacklogMatch | None = None,
) -> PersonalizedResponse:
    """Classification (+ knowledge đã fetch) → PersonalizedResponse. Không gọi mạng ở đây."""
    low = " Phản hồi ở vùng chưa chắc chắn, cần soát kỹ." if cls.flag == FLAG_LOW else ""

    # 1) unclassified: không đoán nhãn, không RAG, không backlog (§4.3 + impl §5). Ack trung tính từ bank.
    if cls.flag == FLAG_UNCLASSIFIED or cls.action_type is None:
        vi, en = _ack_bodies(GROUP_NEUTRAL, cls.feedback)
        return PersonalizedResponse(
            feedback=cls.feedback,
            intent_id=None,
            action_type=None,
            flag=cls.flag,
            template=TPL_NEUTRAL,
            body_vi=vi,
            body_en=en,
            internal_note=f"flag=unclassified · best={cls.best_intent_id}@{cls.best_confidence} · "
            f"vào unclassified_pool, KHÔNG đoán nhãn.",
        )

    action = cls.action_type

    # 2) answer_from_kb: user hiểu nhầm cách dùng → trả lời hướng dẫn từ userguide.
    if action == "answer_from_kb":
        if userguide and userguide.hit:
            return PersonalizedResponse(
                feedback=cls.feedback,
                intent_id=cls.intent_id,
                action_type=action,
                flag=cls.flag,
                template=TPL_RESOLVED,
                body_vi=(
                    "Cảm ơn bạn đã phản hồi cho TÀI Studio. Về vấn đề bạn gặp, đây là hướng dẫn giúp bạn "
                    f"thực hiện:\n\n{userguide.answer.strip()}\n\n"
                    "Nếu vẫn chưa thuận tiện, bạn cứ phản hồi lại để nhóm hỗ trợ thêm nhé."
                ),
                citations=[f"userguide:{userguide.page_id}@{userguide.version}"] if userguide.page_id else [],
                internal_note=f"answer_from_kb + rag_hit=True · intent={cls.intent_id} · c={cls.confidence}.{low}",
            )
        # 0 hit ⇒ suy giảm, KHÔNG claim resolved (guard impl §3.2).
        return PersonalizedResponse(
            feedback=cls.feedback,
            intent_id=cls.intent_id,
            action_type=action,
            flag=cls.flag,
            template=TPL_LISTEN,
            body_vi=(
                "Cảm ơn bạn đã phản hồi cho TÀI Studio. Nhóm đã ghi nhận nội dung bạn gặp và đang rà soát "
                "để hướng dẫn bạn chính xác nhất. Nhóm sẽ phản hồi lại bạn trong thời gian sớm."
            ),
            internal_note=f"answer_from_kb + rag_hit=False ⇒ suy giảm we_listen (không claim resolved).{low}",
        )

    # 3) known_gap: bug / idea → đối chiếu backlog team.
    if action == "known_gap":
        if backlog and backlog.hit:
            timeline = _timeline_from_status(backlog.status)
            return PersonalizedResponse(
                feedback=cls.feedback,
                intent_id=cls.intent_id,
                action_type=action,
                flag=cls.flag,
                template=TPL_LISTEN,
                body_vi=(
                    "Cảm ơn bạn đã phản hồi cho TÀI Studio. Nội dung bạn đề cập trùng với một hạng mục "
                    f"{timeline}. Nhóm sẽ thông báo lại khi tính năng sẵn sàng. Rất cảm ơn bạn đã góp phần "
                    "giúp TÀI Studio tốt hơn."
                ),
                citations=[backlog.jira_key] if backlog.jira_key else [],
                internal_note=f"known_gap + backlog_hit={backlog.jira_key} ({backlog.status}, "
                f"score={backlog.score}) · intent={cls.intent_id}.{low}",
            )
        # không khớp backlog ⇒ ghi nhận chung, không hứa mốc.
        return PersonalizedResponse(
            feedback=cls.feedback,
            intent_id=cls.intent_id,
            action_type=action,
            flag=cls.flag,
            template=TPL_LISTEN,
            body_vi=(
                "Cảm ơn bạn đã phản hồi cho TÀI Studio. Nhóm đã ghi nhận góp ý của bạn và sẽ đưa vào xem xét "
                "để tiếp tục cải thiện TÀI Studio. Rất mong bạn tiếp tục đồng hành cùng nhóm."
            ),
            internal_note=f"known_gap + backlog_hit=False (score="
            f"{backlog.score if backlog else 'n/a'}) ⇒ ghi nhận chung.{low}",
        )

    # 4) ack_only → phân theo SẮC THÁI của category (= kịch bản): tiêu cực → xin lỗi; còn lại → cảm ơn.
    #    (action_type ack_only chung cho cả praise lẫn negative; category mới quyết cách trả lời.)
    #    Copy lấy từ bank tĩnh (reply_samples.yaml), chọn deterministic theo nội dung feedback.
    if _is_negative_scenario(cls.intent_id):
        vi, en = _ack_bodies(GROUP_APOLOGY, cls.feedback)
        return PersonalizedResponse(
            feedback=cls.feedback,
            intent_id=cls.intent_id,
            action_type=action,
            flag=cls.flag,
            template=TPL_APOLOGY,
            body_vi=vi,
            body_en=en,
            internal_note=f"ack_only + scenario TIÊU CỰC ⇒ xin lỗi · intent={cls.intent_id} · c={cls.confidence}.{low}",
        )
    vi, en = _ack_bodies(GROUP_THANK_YOU, cls.feedback)
    return PersonalizedResponse(
        feedback=cls.feedback,
        intent_id=cls.intent_id,
        action_type=action,
        flag=cls.flag,
        template=TPL_NEUTRAL,
        body_vi=vi,
        body_en=en,
        internal_note=f"ack_only + khen/ghi nhận ⇒ cảm ơn · intent={cls.intent_id} · c={cls.confidence}.{low}",
    )
