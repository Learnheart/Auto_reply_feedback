"""
Module: inference.draft (B2) — LỚP TEMPLATE: sinh kịch bản reply cho từng intent (category).
Architecture: docs/architecture.md §3 inference.draft (B2 nội dung câu trả lời), §4.3 Threshold
              routing (nhánh unclassified), §5 Technology Stack (LLM draft Haiku 4.5 — v3.3).
Impl doc:     docs/impl-phase2-auto-feedback-flow.md §3.2 (template theo action_type, rag_hit), §5.
Catalog:      docs/method-offline-intent-analysis.md §5 (action_type → template), §10.
Template rule: template/skill_create_email.md (we_listen/we_resolved, song ngữ VI/EN, style).
Plan:         docs/2026-08-26/reply-scenario-generator/plan.md

Đọc Intent Catalog (category đã chốt) → routing DETERMINISTIC theo action_type → LLM sinh copy
song ngữ VI/EN tailored mỗi category (giữ {name}/{feedback_summary}/{timeline} cho B2 điền runtime)
→ out/<ts>_scenarios/reply_scenarios.{json,md}.

Đây là lớp DESIGN-TIME cho B2, KHÔNG gửi email, KHÔNG gọi RAG/backlog (đó là respond.py runtime).
`we_resolved` là quyết định per-feedback (cần KB answer) ⇒ ở tầng category chỉ mô tả nhánh.
`unclassified` = sink §4.3 ⇒ KHÔNG auto-reply (PM xử tay, R1).

Chạy:  python reply_scenarios.py            # sinh thật (cần Databricks SSO)
       python reply_scenarios.py --dry-run  # chỉ routing + khung, không gọi LLM
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from catalog import DEFAULT_CATALOG, REPO_ROOT  # reuse path/root (DRY, khớp catalog loader)

try:
    from zoneinfo import ZoneInfo
    _VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:  # noqa: BLE001
    _VN_TZ = None

CHAT_MODEL = "nonprod_ai.tsfai.claude-haiku-4-5-sit-tai"   # v3.3: Haiku 4.5 qua AI-Gateway Responses (thay Sonnet)
CHAT_MODEL_FALLBACK = "databricks-claude-sonnet-4-6"        # Sonnet — bật lại nếu Haiku giảm chất lượng (architecture §5)
RESPONSES_PATH = "/ai-gateway/mlflow/v1/responses"         # MLflow Responses API (khác OpenAI /serving-endpoints)
PROFILE = os.environ.get("DATABRICKS_PROFILE", "tcb-agent-sit")
OUT_ROOT = Path(__file__).resolve().parent / "out"
UNCLASSIFIED_ID = "unclassified"


# ── Routing deterministic theo action_type (F1, impl §3.2) ───────────────────
@dataclass
class Route:
    email_type: str | None   # we_resolved | we_listen | None(=manual)
    route: str               # kb_then_fallback | backlog_check | ack_neutral | manual_pm
    tone: str                # resolve | roadmap | acknowledge | escalate
    note: str                # nhánh runtime B2 sẽ chạy


# ack_only KHÔNG đủ mịn để phân cảm-ơn vs xin-lỗi. Category (= kịch bản, intent_id do LLM đặt theo
# scenario) mới là nguồn sự thật — dò marker tiêu cực trên slug (khớp respond._is_negative_scenario).
_NEGATIVE_MARKERS = (
    "negative", "complaint", "apolog", "dissatisf", "unhappy", "frustrat", "angry",
    "tieu_cuc", "phan_nan", "xin_loi", "buc_xuc", "that_vong", "kem",
)


def _is_negative_scenario(intent_id: str) -> bool:
    return any(m in (intent_id or "").lower() for m in _NEGATIVE_MARKERS)


def route_of(intent_id: str, action_type: str) -> Route:
    """Map (intent, action_type) → nhánh reply. §3.2 impl + guard §4.3/R1.

    ack_only tách theo SẮC THÁI category: tiêu cực → xin lỗi (apology); còn lại → cảm ơn.
    """
    if intent_id == UNCLASSIFIED_ID:
        return Route(None, "manual_pm", "escalate",
                     "Sink §4.3 — KHÔNG auto-reply, chuyển PM xử tay (R1).")
    if action_type == "answer_from_kb":
        return Route("we_resolved", "kb_then_fallback", "resolve",
                     "Runtime: RAG userguide hit → we_resolved (hướng dẫn cách làm); "
                     "0 hit → hạ về we_listen, KHÔNG khẳng định đã giải quyết (guard R6).")
    if action_type == "known_gap":
        return Route("we_listen", "backlog_check", "roadmap",
                     "Runtime: khớp backlog → 'team sẽ phát triển' + mốc từ status; "
                     "không khớp → 'đã ghi nhận, sẽ cải thiện'.")
    # ack_only: phân sắc thái theo category
    if _is_negative_scenario(intent_id):
        return Route("we_apologize", "apology", "apology",
                     "Feedback tiêu cực chung → xin lỗi + mời nêu chi tiết; bỏ RAG/backlog.")
    return Route("we_listen", "ack_neutral", "acknowledge",
                 "Ack trung tính (cảm ơn/khen), bỏ RAG + backlog (impl §5).")


# ── LLM chat client tự chứa (convention repo: mỗi file tự giữ client) ─────────
# v3.3: AI-Gateway MLflow Responses API (Haiku). Khác OpenAI chat: system→`instructions`,
# user→`input:[{role,content:[{type:"input_text",text}]}]`, max_tokens→`max_output_tokens`.
# Dùng httpx + truststore (mạng công ty MITM CA nội bộ) + token U2M từ profile — cùng khuôn mcp_atlassian_call.
_HTTP = None
_HOST = None
_TOKEN = None


def _gateway():
    """(httpx.Client base=host, token) trỏ AI-Gateway Databricks (OAuth profile + truststore TLS)."""
    global _HTTP, _HOST, _TOKEN
    if _HTTP is not None:
        return _HTTP, _TOKEN
    import httpx
    import truststore

    host = os.environ.get("DATABRICKS_HOST")
    token = os.environ.get("DATABRICKS_TOKEN")
    if not (host and token):
        from databricks.sdk import WorkspaceClient

        cfg = WorkspaceClient(profile=PROFILE).config
        host = cfg.host
        token = cfg.authenticate().get("Authorization", "").replace("Bearer ", "")

    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    _HTTP = httpx.Client(base_url=host.rstrip("/"), verify=ctx, timeout=120)
    _HOST, _TOKEN = host, token
    return _HTTP, _TOKEN


def _responses_text(data: dict) -> str:
    """Rút text từ Responses API: gom mọi `output[].content[].type=="output_text"`. `error` ⇒ raise."""
    if data.get("error"):
        raise RuntimeError(f"AI-Gateway responses error: {data['error']}")
    parts = [
        c.get("text", "")
        for item in data.get("output", [])
        for c in (item.get("content") or [])
        if c.get("type") == "output_text"
    ]
    text = "".join(parts)
    if not text:
        raise RuntimeError(f"Responses API không có output_text (status={data.get('status')}): {str(data)[:300]}")
    return text


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _extract_json(text: str) -> Any:
    t = _FENCE.sub("", text.strip())
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        for op, cl in (("{", "}"), ("[", "]")):
            a, b = t.find(op), t.rfind(cl)
            if 0 <= a < b:
                try:
                    return json.loads(t[a : b + 1])
                except Exception:  # noqa: BLE001
                    pass
        raise ValueError(f"Không parse được JSON từ LLM:\n{text[:400]}")


def chat_json(system: str, user: str, *, retries: int = 3, max_tokens: int = 8000) -> Any:
    """Gọi Haiku qua AI-Gateway Responses → parse JSON. Chữ ký GIỮ NGUYÊN (knowledge.py phụ thuộc)."""
    client, token = _gateway()
    payload = {
        "model": CHAT_MODEL,
        "max_output_tokens": max_tokens,
        "temperature": 0,
        "instructions": system,      # system prompt của Responses API nằm ở field riêng
        "input": [{"role": "user", "content": [{"type": "input_text", "text": user}]}],
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.post(RESPONSES_PATH, headers=headers, json=payload)
            resp.raise_for_status()
            return _extract_json(_responses_text(resp.json()))
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 2 ** attempt
            print(f"[chat] lỗi (thử {attempt + 1}/{retries}): {repr(e)[:150]} — chờ {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"chat_json thất bại sau {retries} lần: {last}")


# ── Prompt sinh copy song ngữ (F3, rule template/skill_create_email.md) ───────
REPLY_SYS = (
    "Bạn viết KỊCH BẢN reply email song ngữ (Tiếng Việt + English) cho feedback sản phẩm TÀI Studio "
    "(viết ĐÚNG 'TÀI Studio', không 'Tai/Tài Studio'). Với mỗi INTENT (category) được đưa, sinh một "
    "kịch bản trả lời theo đúng `tone` chỉ định:\n"
    "- tone=roadmap (known_gap): ghi nhận feedback, nói team sẽ cải thiện/phát triển; KHÔNG hứa mốc "
    "cứng — để placeholder {timeline}. KHÔNG khẳng định đã giải quyết.\n"
    "- tone=acknowledge (ack_only, khen): cảm ơn/ghi nhận ngắn gọn, ấm áp, không hứa hẹn tính năng.\n"
    "- tone=apology (ack_only, tiêu cực): xin lỗi vì trải nghiệm chưa tốt, mời user nêu chi tiết cụ "
    "thể để hỗ trợ, trấn an; KHÔNG hứa mốc, KHÔNG cảm ơn kiểu khen.\n"
    "- tone=resolve (answer_from_kb): nói vấn đề có thể xử lý được, chừa {resolution} để điền cách làm.\n"
    "QUY TẮC VĂN PHONG (bắt buộc): KHÔNG dùng dấu gạch dài (—) trong nội dung; giọng ấm, tự nhiên, "
    "không robot; KHÔNG emoji/icon. Giữ nguyên các placeholder: {name}, {feedback_summary}, {timeline}, "
    "{resolution}. Mỗi ngôn ngữ gồm: greeting, body (2-3 câu, nhắc {feedback_summary}), closing.\n"
    'Trả về DUY NHẤT JSON: {"scenarios":[{"intent_id":str,'
    '"vi":{"greeting":str,"body":str,"closing":str},'
    '"en":{"greeting":str,"body":str,"closing":str}}]}'
)


@dataclass
class Scenario:
    intent_id: str
    label: str
    action_type: str
    email_type: str | None
    route: str
    tone: str
    note: str
    vi: dict[str, str] = field(default_factory=dict)
    en: dict[str, str] = field(default_factory=dict)


def load_intents(catalog_path: Path) -> list[dict]:
    """Nạp raw catalog JSON — GIỮ cả `unclassified` (khác catalog.load_catalog vốn bỏ sink)."""
    raw = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    return raw.get("intents", [])


def build_scenarios(intents: list[dict], *, dry_run: bool) -> list[Scenario]:
    scen: dict[str, Scenario] = {}
    to_generate: list[dict] = []
    for it in intents:
        iid = it["intent_id"]
        r = route_of(iid, it.get("action_type", "ack_only"))
        scen[iid] = Scenario(
            intent_id=iid, label=it.get("label", iid),
            action_type=it.get("action_type", "ack_only"),
            email_type=r.email_type, route=r.route, tone=r.tone, note=r.note,
        )
        if r.route != "manual_pm":       # unclassified không sinh copy (F4)
            to_generate.append({"intent_id": iid, "label": it.get("label", iid),
                                "description": it.get("description", ""), "tone": r.tone})

    if dry_run or not to_generate:
        print(f"[dry-run] {len(scen)} scenario (routing only, {len(to_generate)} cần LLM)")
        return list(scen.values())

    listing = "\n".join(
        f'- intent_id={g["intent_id"]} | tone={g["tone"]} | "{g["label"]}" — {g["description"][:180]}'
        for g in to_generate
    )
    data = chat_json(REPLY_SYS, "Các intent cần sinh kịch bản:\n" + listing)
    for s in data.get("scenarios", []):
        iid = str(s.get("intent_id", "")).strip()
        if iid in scen:
            scen[iid].vi = {k: str(v).strip() for k, v in (s.get("vi") or {}).items()}
            scen[iid].en = {k: str(v).strip() for k, v in (s.get("en") or {}).items()}
    print(f"[A] LLM sinh copy cho {sum(1 for s in scen.values() if s.vi)}/{len(to_generate)} intent")
    return list(scen.values())


# ── Ghi artifact ──────────────────────────────────────────────────────────────
def _order(scen: list[Scenario]) -> list[Scenario]:
    """Sắp: intent thật trước, unclassified cuối; trong nhóm theo email_type rồi label."""
    return sorted(scen, key=lambda s: (s.intent_id == UNCLASSIFIED_ID,
                                       s.email_type or "zzz", s.label))


def write_scenarios(scen: list[Scenario], out_dir: Path, catalog_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    scen = _order(scen)
    payload = {
        "meta": {"catalog": str(catalog_path), "n_scenarios": len(scen), "chat_model": CHAT_MODEL},
        "scenarios": [
            {"intent_id": s.intent_id, "label": s.label, "action_type": s.action_type,
             "email_type": s.email_type, "route": s.route, "tone": s.tone, "note": s.note,
             "vi": s.vi, "en": s.en}
            for s in scen
        ],
    }
    (out_dir / "reply_scenarios.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2))

    md = ["# Kịch bản reply theo category (Tier A)\n",
          "> Routing deterministic theo `action_type` (§3.2). `we_resolved` là quyết định "
          "**per-feedback** (cần RAG hit), tầng category chỉ mô tả nhánh. `{name}`/"
          "`{feedback_summary}`/`{timeline}`/`{resolution}` do B2 điền runtime.\n",
          f"**{len(scen)} category · catalog:** `{Path(catalog_path).parent.name}/catalog_a.json`\n"]
    for s in scen:
        et = s.email_type or "— (KHÔNG auto-reply)"
        md.append(f"\n## {s.label}  \n"
                  f"`{s.intent_id}` · action_type=`{s.action_type}` · email_type=**{et}** · "
                  f"tone=`{s.tone}` · route=`{s.route}`\n")
        md.append(f"> {s.note}\n")
        if not s.vi and not s.en:
            md.append("_(không sinh copy — chuyển PM xử tay)_\n")
            continue
        md.append("**VI**  \n"
                  f"{s.vi.get('greeting','')}\n\n{s.vi.get('body','')}\n\n{s.vi.get('closing','')}\n")
        md.append("**EN**  \n"
                  f"{s.en.get('greeting','')}\n\n{s.en.get('body','')}\n\n{s.en.get('closing','')}\n")
    (out_dir / "reply_scenarios.md").write_text("\n".join(md))
    rel = out_dir.relative_to(REPO_ROOT)
    print(f"[write] {rel}/reply_scenarios.{{json,md}}  ({len(scen)} scenario)")


def run(catalog_path: Path, *, dry_run: bool) -> None:
    intents = load_intents(catalog_path)
    print(f"[load] {len(intents)} intent từ {Path(catalog_path).name}")
    scen = build_scenarios(intents, dry_run=dry_run)
    ts = datetime.now(_VN_TZ).strftime("%Y%m%d_%H%M%S")
    write_scenarios(scen, OUT_ROOT / f"{ts}_scenarios", catalog_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sinh kịch bản reply cho từng category (Intent Catalog).")
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG,
                    help="Đường dẫn catalog_a.json (mặc định = catalog frozen trong catalog.py).")
    ap.add_argument("--dry-run", action="store_true", help="Chỉ routing + khung, không gọi LLM.")
    args = ap.parse_args()
    run(args.catalog, dry_run=args.dry_run)
