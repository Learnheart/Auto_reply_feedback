"""
Module: Offline intent analysis (Phase 0) — Hướng A · STEP 2: LLM đặt tên + rollup cụm
Architecture: docs/architecture.md §3 Phase 0 (LLM merge→LLM gen intent), §5 (LLM Sonnet), §6.1 R1
Method:       docs/method-offline-intent-analysis.md §5 (LLM đặt tên/gộp + guardrail grounding)
Plan:         docs/2026-08-26/intent-merge-centroid-gated/plan.md (Tier-A rollup về tầng category)

STEP 2 tiêu thụ cụm từ STEP 1 (`step1_clustering.py`) rồi dùng LLM (Sonnet):

    clusters → LLM label từng cụm → [ghi step2a_cluster_labels] →
             LLM gán mỗi cụm vào 1 trong 6 intent CỐ ĐỊNH (5 hướng reply + unclassified) →
             [ghi step2b_merge_review] → LLM gán noise → guardrail grounding
             → out/<run>/catalog_a.json  (JSON-only, review ở step2b_merge_review.md)

Intent = HƯỚNG TRẢ LỜI cố định (user chốt): report_bug / request_feature / how_to /
praise / complaint / unclassified. inference route theo intent_id; action_type (3-enum §5)
suy cứng từ intent. Output 2 bước (label cụm / gán intent) tách artifact để human review.

>>> MỌI PROMPT LLM để ở khối GLOBAL ngay dưới đây để dễ chỉnh sửa về sau. <<<

Chạy:  python step2_llm_label_merge.py     # tự chạy STEP 1 clustering rồi STEP 2 LLM
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import numpy as np

from step1_clustering import (  # shared: data / embedding / clustering từ STEP 1
    CHAT_MODEL,
    EMBED_MODEL,
    Feedback,
    OUT_DIR,
    SEED,
    _medoid_order,
    _openai_client,
    run_dir,
    run_step1,
)

# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS (GLOBAL) — chỉnh sửa ở đây, không phải trong hàm
# ══════════════════════════════════════════════════════════════════════════════

LABEL_SYS = (
    "Bạn là data scientist đặt tên intent cho feedback sản phẩm phần mềm (TÀI Studio). "
    "Feedback trộn tiếng Việt và tiếng Anh. Với MỖI cụm feedback được đưa, hãy đặt một "
    "intent ngắn gọn, cụ thể theo NGHĨA (không đặt tên chung chung như 'khác/other'). "
    "action_type chỉ nhận: answer_from_kb (trả lời được từ hướng dẫn sử dụng), "
    "known_gap (thiếu/lỗi tính năng, cần dev), ack_only (ghi nhận, không cam kết). "
    'Trả về DUY NHẤT JSON: {"clusters":[{"cluster_id":int,"label":str,"description":str,'
    '"action_type":str}]}'
)

# Bộ intent CỐ ĐỊNH (user chốt) = 5 HƯỚNG TRẢ LỜI + unclassified. Mỗi intent 1 kịch bản reply
# riêng; action_type (3-enum §5) suy CỨNG từ intent (không để LLM chọn). intent_id là nhãn cuối
# inference dùng; respond.py route bug/feature/praise/complaint qua chính intent_id này.
UNCLASSIFIED_ID = "unclassified"
UNCLASSIFIED_LABEL = "Chưa phân loại / không khớp kịch bản nào"
UNCLASSIFIED_DESC = (
    "Rác/test/1 từ vô nghĩa hoặc không rơi vào 5 hướng trên — pool unclassified, PM xử tay."
)

#             (intent_id,          action_type,      label VI,                      description)
SCENARIOS: list[tuple[str, str, str, str]] = [
    ("report_bug", "known_gap", "Báo lỗi / chức năng hỏng",
     "User báo LỖI: chức năng đang GÃY, sai kết quả, crash, không phản hồi, lỗi kỹ thuật. "
     "Reply: tra backlog xem team đã có/đang xử lý chưa → xin lỗi + 'đang xử lý'."),
    ("request_feature", "known_gap", "Đề xuất / cải thiện tính năng",
     "User đề xuất tính năng MỚI (chưa có) hoặc cải thiện tính năng đã có. "
     "Reply: tra roadmap/backlog → cảm ơn + 'sẽ cân nhắc'."),
    ("how_to", "answer_from_kb", "Chưa biết cách dùng (how-to)",
     "User CHƯA BIẾT / hiểu nhầm CÁCH DÙNG tính năng ĐÃ CÓ, hoặc hỏi cơ chế hoạt động — tính năng "
     "KHÔNG hỏng. Reply: hướng dẫn từ userguide."),
    ("praise", "ack_only", "Khen / phản hồi tích cực",
     "User khen, hài lòng, cảm ơn — không yêu cầu, không phàn nàn. Reply: cảm ơn."),
    ("complaint", "ack_only", "Phàn nàn tiêu cực chung",
     "User phàn nàn tiêu cực CHUNG CHUNG, không nêu lỗi/yêu cầu cụ thể. Reply: xin lỗi + hỏi thêm."),
]
SCENARIO_IDS = [s[0] for s in SCENARIOS]
SCENARIO_ACTION = {s[0]: s[1] for s in SCENARIOS}
SCENARIO_LABEL = {s[0]: s[2] for s in SCENARIOS}
SCENARIO_DESC = {s[0]: s[3] for s in SCENARIOS}

ROLLUP_SYS = (
    "Bạn phân loại CỤM feedback (sản phẩm TÀI Studio) vào ĐÚNG MỘT trong 6 intent CỐ ĐỊNH sau, theo "
    "KỊCH BẢN TRẢ LỜI (cách hệ thống sẽ trả lời) — KHÔNG theo chủ đề/tính năng:\n"
    "- report_bug: chức năng đang GÃY/hỏng/sai/crash/không phản hồi/lỗi kỹ thuật. Vd: 'dịch file báo "
    "network error', 'không gen ra slide', 'app không vào được'.\n"
    "- request_feature: đề xuất tính năng MỚI chưa có, hoặc CẢI THIỆN tính năng đã chạy. Vd: 'cho tải "
    "file Word', 'thêm giao diện tiếng Việt', 'slide đẹp hơn'.\n"
    "- how_to: user CHƯA BIẾT / hiểu nhầm CÁCH DÙNG tính năng ĐÃ CÓ, hoặc hỏi CƠ CHẾ hoạt động — tính "
    "năng KHÔNG hỏng. Vd: 'usage limit tính thế nào, khi nào reset', 'để tạo slide action plan làm thế "
    "nào', 'thêm trang thì STT không nhảy, tôi cần làm gì'.\n"
    "- praise: khen/hài lòng/cảm ơn, không yêu cầu. Vd: 'sản phẩm tuyệt vời'.\n"
    "- complaint: phàn nàn tiêu cực CHUNG CHUNG, không nêu lỗi/yêu cầu cụ thể. Vd: 'càng làm càng "
    "xấu', 'trang rất hỗn'.\n"
    "- unclassified: rác/test/1 từ vô nghĩa, hoặc không rơi vào 5 nhóm trên.\n"
    "TIE-BREAK: đang GÃY→report_bug; CHẠY nhưng muốn thêm/cải thiện→request_feature; CHẠY nhưng user "
    "không biết dùng / hỏi cách→how_to. Cụm có thể lẫn — dựa label mịn + mẫu chọn bản chất TRỘI. "
    "category trội (bug/idea/praise/other) chỉ tham khảo.\n"
    'Trả về DUY NHẤT JSON: {"assignments":[{"cluster_id":int,"intent_id":str,"reason":str}]}. '
    "Mỗi cluster_id xuất hiện đúng MỘT lần; intent_id ngoài 6 giá trị coi là unclassified."
)

ASSIGN_SYS = (
    "Bạn phân loại feedback vào bộ intent CHO SẴN. Với mỗi feedback, chọn intent_id phù hợp nhất "
    "theo nghĩa. Nếu KHÔNG intent nào thực sự khớp, chọn intent_id = \"unclassified\" — ĐỪNG ép. "
    'Trả về DUY NHẤT JSON: {"assignments":[{"idx":int,"intent_id":str}]}'
)


# ── Data model (schema ứng viên, plan D2) ────────────────────────────────────
@dataclass
class Intent:
    intent_id: str
    label: str
    description: str
    action_type: str                       # answer_from_kb | known_gap | ack_only
    supporting_feedback_ids: list[str] = field(default_factory=list)
    source_clusters: list[int] = field(default_factory=list)  # A-only: cụm gốc

    def n(self) -> int:
        return len(self.supporting_feedback_ids)


# ── LLM chat trả JSON (Sonnet, ép JSON, retry) ───────────────────────────────
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _extract_json(text: str) -> Any:
    """Parse JSON tolerant: strip code fence, cắt tới object/array ngoài cùng."""
    t = _FENCE.sub("", text.strip())
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        # tìm { ... } hoặc [ ... ] bao ngoài cùng
        for op, cl in (("{", "}"), ("[", "]")):
            a, b = t.find(op), t.rfind(cl)
            if 0 <= a < b:
                try:
                    return json.loads(t[a : b + 1])
                except Exception:  # noqa: BLE001
                    pass
        raise ValueError(f"Không parse được JSON từ LLM:\n{text[:500]}")


def chat_json(system: str, user: str, *, retries: int = 3, max_tokens: int = 8000) -> Any:
    """Gọi Sonnet, ép trả JSON. Temperature 0. Retry lỗi mạng / JSON hỏng."""
    client = _openai_client()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                max_tokens=max_tokens,
            )
            return _extract_json(resp.choices[0].message.content or "")
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 2 ** attempt
            print(f"[chat] lỗi (thử {attempt + 1}/{retries}): {repr(e)[:160]} — chờ {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"chat_json thất bại sau {retries} lần: {last}")


# ── grounding guardrail (plan D4) ────────────────────────────────────────────
def ground_filter(
    intents: list[Intent], valid_ids: set[str], min_support: int = 2,
    always_keep: frozenset[str] = frozenset(),
) -> list[Intent]:
    """Loại supporting id không tồn tại; drop intent < min_support id thật.

    §5 method — chống LLM bịa intent / bịa feedback_id. `always_keep` = intent_id được GIỮ
    dù dưới ngưỡng (dùng cho pool `unclassified` — sink hợp lệ, không phải intent bịa).
    """
    out: list[Intent] = []
    for it in intents:
        real = [fid for fid in dict.fromkeys(it.supporting_feedback_ids) if fid in valid_ids]
        it.supporting_feedback_ids = real
        if len(real) >= min_support or it.intent_id in always_keep:
            out.append(it)
        else:
            print(f"[grounding] drop intent '{it.label}' — chỉ {len(real)} id thật (<{min_support})")
    return out


# ── io ───────────────────────────────────────────────────────────────────────
def _slug(text: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()
    return t or "intent"


def dedup_intent_ids(intents: list[Intent]) -> None:
    seen: dict[str, int] = {}
    for it in intents:
        base = it.intent_id or _slug(it.label)
        if base in seen:
            seen[base] += 1
            it.intent_id = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
            it.intent_id = base


def write_catalog(intents: list[Intent], name: str, meta: dict[str, Any], out_dir: Path) -> None:
    """Ghi catalog ứng viên ra <out_dir>/<name>.json (JSON-only, không duplicate yaml)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "n_intents": len(intents),
        "intents": [asdict(it) for it in intents],
    }
    (out_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    rel = out_dir.relative_to(OUT_DIR.parent)
    print(f"[write] {rel}/{name}.json  ({len(intents)} intent)")


ACTION_TYPES = {"answer_from_kb", "known_gap", "ack_only"}


def _norm_action(a: str) -> str:
    a = (a or "").strip().lower()
    return a if a in ACTION_TYPES else "ack_only"


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — LLM đặt tên / gộp / gán noise
# ══════════════════════════════════════════════════════════════════════════════

def label_clusters(labels: np.ndarray, items: list[Feedback], vecs: np.ndarray) -> list[Intent]:
    """LLM đặt tên từng cụm (§5a). Gửi tối đa 8 mẫu gần medoid/cụm, batch nhiều cụm/call."""
    cluster_ids = sorted({int(l) for l in labels if l >= 0})
    blocks: list[str] = []
    members: dict[int, list[int]] = {}
    for cid in cluster_ids:
        idxs = [i for i, l in enumerate(labels) if l == cid]
        members[cid] = idxs
        ordered = _medoid_order(idxs, vecs)[:8]
        samples = "\n".join(f"  - {items[i].content}" for i in ordered)
        blocks.append(f"[cluster_id={cid}] (size={len(idxs)})\n{samples}")

    intents: list[Intent] = []
    BATCH = 12
    for i in range(0, len(cluster_ids), BATCH):
        chunk_ids = cluster_ids[i : i + BATCH]
        user = "Các cụm feedback:\n\n" + "\n\n".join(blocks[i : i + BATCH])
        data = chat_json(LABEL_SYS, user)
        for c in data.get("clusters", []):
            cid = int(c["cluster_id"])
            if cid not in members:
                continue
            intents.append(
                Intent(
                    intent_id="",
                    label=str(c.get("label", "")).strip(),
                    description=str(c.get("description", "")).strip(),
                    action_type=_norm_action(c.get("action_type", "")),
                    supporting_feedback_ids=[items[j].feedback_id for j in members[cid]],
                    source_clusters=[cid],
                )
            )
    print(f"[A] đặt tên {len(intents)} cụm")
    return intents


def _members_by_cluster(labels: np.ndarray) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for i, l in enumerate(labels):
        out.setdefault(int(l), []).append(i)
    return out


def _dominant_category(member_idxs: list[int], items: list[Feedback]) -> str:
    """Category user gán trội của một cụm (bug/idea/praise/other). '' nếu trống."""
    c = Counter((items[j].category or "").strip().lower() for j in member_idxs if items[j].category)
    return c.most_common(1)[0][0] if c else ""


def write_cluster_labels(
    fine: list[Intent], labels: np.ndarray, items: list[Feedback], vecs: np.ndarray, out_dir: Path
) -> None:
    """Artifact 2a (tường minh cho review): mỗi cụm → label mịn LLM đặt + category trội + mẫu.

    Đây là output bước label_clusters (trước rollup) — trước đây bị nuốt vào catalog cuối.
    JSON-only (không duplicate yaml).
    """
    members = _members_by_cluster(labels)
    rows = []
    for it in fine:
        cid = it.source_clusters[0]
        idxs = members.get(cid, [])
        samples = [items[j].content for j in _medoid_order(idxs, vecs)[:3]] if idxs else []
        rows.append({
            "cluster_id": cid,
            "label": it.label,
            "description": it.description,
            "action_type": it.action_type,
            "size": len(idxs),
            "dominant_category": _dominant_category(idxs, items),
            "samples": samples,
        })
    rows.sort(key=lambda r: -r["size"])
    payload = {"n_clusters": len(rows), "clusters": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "step2a_cluster_labels.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2))
    rel = out_dir.relative_to(OUT_DIR.parent)
    print(f"[write] {rel}/step2a_cluster_labels.json  ({len(rows)} cụm)")


def rollup_to_buckets(
    fine: list[Intent], labels: np.ndarray, items: list[Feedback]
) -> tuple[list[Intent], list[dict]]:
    """Gán MỖI cụm vào 1 trong 6 intent CỐ ĐỊNH (SCENARIOS + unclassified) theo hướng trả lời.

    intent_id/action_type cố định (không LLM tự sinh). LLM chỉ chọn cụm → intent_id nào.
    Trả (intents theo thứ tự SCENARIOS + unclassified cuối, review_rows).
    """
    members = _members_by_cluster(labels)
    by_cluster = {it.source_clusters[0]: it for it in fine if it.source_clusters}

    # listing cho LLM: cluster_id, label mịn, category trội, 2 mẫu
    lines = []
    dom_cat: dict[int, str] = {}
    for cid, it in sorted(by_cluster.items()):
        idxs = members.get(cid, [])
        dom_cat[cid] = _dominant_category(idxs, items)
        samples = "; ".join(items[j].content[:80] for j in idxs[:2])
        lines.append(
            f'- cluster_id={cid} (size={len(idxs)}, category_trội={dom_cat[cid] or "?"}): '
            f'"{it.label}" — {it.description[:120]} | mẫu: {samples}'
        )
    data = chat_json(ROLLUP_SYS, "Các cụm cần phân vào 6 intent cố định:\n" + "\n".join(lines))

    # cid → (intent_id, reason); intent_id lạ / thiếu → unclassified
    assigned: dict[int, tuple[str, str]] = {}
    for a in data.get("assignments", []):
        try:
            cid = int(a.get("cluster_id", -1))
        except (TypeError, ValueError):
            continue
        if cid not in by_cluster:
            continue
        iid = str(a.get("intent_id", "")).strip()
        if iid not in SCENARIO_IDS:
            iid = UNCLASSIFIED_ID
        assigned[cid] = (iid, str(a.get("reason", "")).strip())
    for cid in by_cluster:  # cụm LLM bỏ sót → unclassified (không mất feedback)
        assigned.setdefault(cid, (UNCLASSIFIED_ID, "LLM không gán → unclassified"))

    # bucket cố định: 6 intent luôn khởi tạo, action_type suy cứng từ SCENARIOS
    buckets: dict[str, Intent] = {
        sid: Intent(intent_id=sid, label=SCENARIO_LABEL[sid], description=SCENARIO_DESC[sid],
                    action_type=SCENARIO_ACTION[sid], supporting_feedback_ids=[], source_clusters=[])
        for sid in SCENARIO_IDS
    }
    buckets[UNCLASSIFIED_ID] = Intent(
        intent_id=UNCLASSIFIED_ID, label=UNCLASSIFIED_LABEL, description=UNCLASSIFIED_DESC,
        action_type="ack_only", supporting_feedback_ids=[], source_clusters=[])

    review_rows: list[dict] = []
    for cid, (iid, reason) in sorted(assigned.items()):
        it = by_cluster[cid]
        tgt = buckets[iid]
        tgt.supporting_feedback_ids.extend(it.supporting_feedback_ids)
        tgt.source_clusters.append(cid)
        idxs = members.get(cid, [])
        review_rows.append({
            "intent_label": tgt.intent_id, "action_type": tgt.action_type,
            "description": tgt.description, "cluster_id": cid, "cluster_label": it.label,
            "dominant_category": dom_cat.get(cid, ""), "size": len(idxs), "reason": reason,
            "feedbacks": [items[j].content for j in idxs],
        })
    for it in buckets.values():
        it.supporting_feedback_ids = list(dict.fromkeys(it.supporting_feedback_ids))

    intents = [buckets[sid] for sid in SCENARIO_IDS] + [buckets[UNCLASSIFIED_ID]]
    print(f"[A] rollup {len(by_cluster)} cụm → "
          + ", ".join(f"{sid}={buckets[sid].n()}" for sid in SCENARIO_IDS)
          + f", unclassified={buckets[UNCLASSIFIED_ID].n()}")
    return intents, review_rows


def write_merge_review(review_rows: list[dict], out_dir: Path) -> None:
    """Artifact 2b (review): MỘT bảng phẳng — mỗi dòng = 1 cluster.

    Cột: cluster_id | label mịn | action | category | size. Sắp theo category rồi size giảm
    (cùng category nằm liền nhau, unclassified cuối) để soi "cụm này có đúng category không".
    Markdown-only (dữ liệu máy đã có ở catalog_a.json + step2a_cluster_labels.json).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # thứ tự category = thứ tự SCENARIOS (report_bug → ... → complaint), unclassified cuối
    order_idx = {sid: i for i, sid in enumerate(SCENARIO_IDS)}
    order_idx[UNCLASSIFIED_ID] = len(SCENARIO_IDS)

    def _sort_key(r: dict) -> tuple:
        return (order_idx.get(r["intent_label"], 99), -r["size"], r["cluster_id"])

    rows = sorted(review_rows, key=_sort_key)

    # per-category: định nghĩa cố định + hướng trả lời (giải thích CÁCH CHIA)
    cats: dict[str, dict] = {}
    for r in rows:
        c = cats.setdefault(r["intent_label"], {
            "action": r["action_type"], "description": r.get("description", ""),
            "n_clusters": 0, "n_fb": 0})
        c["n_clusters"] += 1
        c["n_fb"] += r["size"]

    md = ["# Rollup review — cluster → intent (6 hướng cố định)\n",
          f"**{len(rows)} cluster · {len(cats)} intent.** intent_id = hướng trả lời (inference route "
          "theo đây); action_type suy cứng từ intent.\n"]

    # (1) Giải thích cách chia — định nghĩa + hướng reply mỗi intent
    md.append("## Cách chia (giải thích)\n")
    for name, c in cats.items():
        md.append(f"- **{name}**  `[{c['action']}]`  ({c['n_clusters']} cụm · {c['n_fb']} fb)  \n"
                  f"  {c['description'] or '—'}")
    md.append("")

    # (2) Bảng phẳng 1 dòng/cluster (kèm cột feedback: gạch đầu dòng các feedback trong cụm)
    def _cell(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ").strip()

    md.append("## Bảng phân cụm → category\n")
    md.append("| cluster_id | feedback | label mịn | action | category | size |")
    md.append("|---|---|---|---|---|---|")
    for r in rows:
        fbs = "<br>".join(f"• {_cell(c)}" for c in r.get("feedbacks", []))
        lbl = _cell(r["cluster_label"])
        md.append(f"| {r['cluster_id']} | {fbs} | {lbl} | {r['action_type']} "
                  f"| {r['intent_label']} | {r['size']} |")
    (out_dir / "step2b_merge_review.md").write_text("\n".join(md) + "\n")
    rel = out_dir.relative_to(OUT_DIR.parent)
    print(f"[write] {rel}/step2b_merge_review.md  ({len(rows)} cụm, {len(cats)} category)")


def assign_noise(labels: np.ndarray, items: list[Feedback], intents: list[Intent]) -> None:
    """Feed feedback noise (label=-1) cho LLM gán vào intent gần nhất (plan D5).

    Không bỏ feedback nào. LLM trả NONE ⇒ để lại (sẽ vào 'không gán' — vẫn không mất,
    chỉ không thuộc intent nào; report tính vào coverage)."""
    noise_idx = [i for i, l in enumerate(labels) if l < 0]
    if not noise_idx:
        return
    by_id = {it.intent_id: it for it in intents}
    uncl = by_id.get(UNCLASSIFIED_ID)   # sink; id lạ hoặc LLM chọn unclassified → vào đây
    catalog = "\n".join(f'- {it.intent_id}: "{it.label}" — {it.description}' for it in intents)

    BATCH = 40
    assigned = to_uncl = 0
    for i in range(0, len(noise_idx), BATCH):
        chunk = noise_idx[i : i + BATCH]
        fb = "\n".join(f"  idx={j} | {items[j].content}" for j in chunk)
        user = f"Bộ intent cho sẵn:\n{catalog}\n\nFeedback cần gán:\n{fb}"
        data = chat_json(ASSIGN_SYS, user)
        for a in data.get("assignments", []):
            iid = str(a.get("intent_id", "")).strip()
            idx = int(a.get("idx", -1))
            if not (0 <= idx < len(items)):
                continue
            target = by_id.get(iid, uncl)   # không khớp intent nào → unclassified (không ép)
            if target is None:
                continue
            target.supporting_feedback_ids.append(items[idx].feedback_id)
            if target is uncl:
                to_uncl += 1
            else:
                assigned += 1
    # dedup
    for it in intents:
        it.supporting_feedback_ids = list(dict.fromkeys(it.supporting_feedback_ids))
    print(f"[A] gán noise: {assigned} vào intent, {to_uncl} → unclassified / tổng {len(noise_idx)}")


def run_approach_a() -> tuple[list[Intent], list[Feedback]]:
    print("\n=== HƯỚNG A: clustering (STEP 1) → LLM label + gán 6 intent cố định (STEP 2) ===")
    out_dir = run_dir("llm")                    # out/<date_time>_llm (không ghi đè)
    labels, items, vecs = run_step1()          # STEP 1: clustering + cluster report (folder riêng)
    fine = label_clusters(labels, items, vecs)          # label mịn từng cụm
    write_cluster_labels(fine, labels, items, vecs, out_dir)   # artifact 2a (review)
    intents, review = rollup_to_buckets(fine, labels, items)   # gán cụm → 6 intent cố định
    write_merge_review(review, out_dir)                        # artifact 2b (review)
    assign_noise(labels, items, intents)
    valid = {it.feedback_id for it in items}
    intents = ground_filter(intents, valid, always_keep=frozenset({UNCLASSIFIED_ID}))

    # coverage = feedback được gán vào intent THẬT (KHÔNG tính unclassified — đó là pool chưa khớp)
    classified = {fid for it in intents if it.intent_id != UNCLASSIFIED_ID
                  for fid in it.supporting_feedback_ids}
    n_uncl = next((it.n() for it in intents if it.intent_id == UNCLASSIFIED_ID), 0)
    meta = {
        "approach": "A_cluster_llm",
        "granularity": "fixed_reply_scenarios",
        "intents_fixed": SCENARIO_IDS + [UNCLASSIFIED_ID],
        "embedding_model": EMBED_MODEL,
        "chat_model": CHAT_MODEL,
        "n_feedback": len(items),
        "coverage": round(len(classified) / len(items), 4),
        "n_unclassified": n_uncl,
        "seed": SEED,
    }
    write_catalog(intents, "catalog_a", meta, out_dir)
    print(f"[A] xong: {len(intents)} intent (gồm unclassified), "
          f"classified {len(classified)}/{len(items)}, unclassified {n_uncl}")
    return intents, items


if __name__ == "__main__":
    run_approach_a()
