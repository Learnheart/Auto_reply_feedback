"""
Module: inference.draft (B2) — bước 1 chuỗi §4.4: đối chiếu feedback bug/new_feature với GUIDELINE.
Architecture: docs/architecture.md §3 Trách nhiệm từng module (B2: "bug/new_feature gom theo agent,
              nạp nguyên văn guideline cho LLM theo chuỗi §4.4"), §4.2 Flow B (1 call/agent),
              §4.4 Flow D bước 1 (hỏi "tính năng đã tồn tại chưa, ở đâu"; cổng an toàn: chỉ tin
              source_ref phân giải ngược được), §4.6 (userguide_page, feedback_processing.source_ref),
              §5 (LLM: dev = qwen3-8b LM Studio thay Haiku 4.5; Test: pytest + mock LLM), §6.1 R6/R9.
Impl doc: docs/impl-phase2-auto-feedback-flow.md §3.2 (không hit ⇒ we_listen, không được claim), §5.
Plan: docs/2026-09-03/guideline-resolve-batch/plan.md (D1 định nghĩa solved, D5 LLM, D6 gate quote, D7 metric)

Đầu vào: CSV sau B1 (cột `agent, content, label`, tuỳ chọn `id`). Chỉ xử lý `label ∈ {bug, new_feature}`.
Đầu ra: CSV = input + đúng 2 cột `solved` (True/False) + `referenced` (quote nguyên văn | rỗng);
        sidecar `<out>.debug.jsonl` (source_ref, heading, match_type, reason, raw LLM).

Cổng an toàn (D6): `solved=True` CHỈ khi quote LLM trả về TÌM ĐƯỢC NGUYÊN VĂN (chuẩn hoá khoảng
trắng/case/dấu ngoặc) trong page guideline của agent đó. Không tìm được ⇒ solved=False, referenced="".
source_ref = `<page_id>@<version>#<heading>` do CODE dựng từ vị trí quote — LLM không tự đặt.

CẤU HÌNH MẶC ĐỊNH = phương án chốt (run `evidence_think_anchor_verify`, 2026-09-03, gold 127 dòng /
12 dương): prompt evidence-first + reasoning bật + gate anchor + verify pass ⇒ precision 1.00 /
recall 0.42 / F1 0.59. Phương án F1 cao nhất là bỏ verify (0.62) nhưng precision chỉ 0.57 (6 FP/14) —
với email khẳng định "tính năng đã có", PM ưu tiên precision ⇒ chọn bản có verify. Chi tiết:
src/05_experiments/runs_resolve/index.md, plan §Results.

Chạy:
  python src/03_inference/resolve_guideline.py --in <b1_output.csv> --out <resolved.csv>
  python src/03_inference/resolve_guideline.py --eval                # đo trên data/golden/feedback_gold_solved.csv
  Tắt/đổi từng phần: --no-think | --no-verify | --no-anchor | --prompt decide | --batch-size 10 | --fuzzy 0.92
  ... --model qwen/qwen3-8b | --base-url http://localhost:1234/v1
"""
from __future__ import annotations

import csv
import difflib
import importlib.util
import io
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
_KNOWLEDGE_DIR = REPO_ROOT / "src" / "02_knowledge"
GOLD_SOLVED_CSV = REPO_ROOT / "data" / "golden" / "feedback_gold_solved.csv"
GOLD_INTENT_CSV = REPO_ROOT / "data" / "golden" / "feedback_gold.csv"

KNOWLEDGE_LABELS = ("bug", "new_feature")   # nhóm 1 §4.2 — nhánh cần knowledge
DEFAULT_BATCH_SIZE = 10
DEFAULT_MODEL = "qwen/qwen3-8b"
DEFAULT_BASE_URL = "http://localhost:1234/v1"
MIN_QUOTE_CHARS = 15                        # quote ngắn hơn không đủ làm citation
CONTEXT_WARN_CHARS = 40_000                 # R9: ~10k token, cảnh báo khi prompt vượt


# ── Knowledge store (Job A offline loader) ───────────────────────────────────
def _load_knowledge_mod():
    """Nạp src/02_knowledge/guideline_docx.py (thư mục tên số) + userguide_store cùng chỗ."""
    name = "guideline_docx"
    if name in sys.modules:
        return sys.modules[name]
    if str(_KNOWLEDGE_DIR) not in sys.path:
        sys.path.insert(0, str(_KNOWLEDGE_DIR))
    spec = importlib.util.spec_from_file_location(name, _KNOWLEDGE_DIR / "guideline_docx.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def load_pages():
    return _load_knowledge_mod().load_guidelines()


def pages_for_agent(pages, agent: str) -> list:
    return _load_knowledge_mod().pages_for_agent(pages, agent)


# ── Gate quote verbatim (D6) ─────────────────────────────────────────────────
_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "‑": "-", "–": "-", "—": "-", " ": " "})


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "").translate(_QUOTES)).strip().lower()


@dataclass
class QuoteHit:
    ok: bool
    page_id: str = ""
    version: str = ""
    heading: str = ""
    quote: str = ""          # quote đã chuẩn hoá về đúng đoạn trong tài liệu (verbatim)
    score: float = 0.0       # 1.0 = exact; <1 = fuzzy (chỉ khi bật)


_ELLIPSIS = re.compile(r"(\.\.\.|…)")
ANCHOR_MIN_CHARS = 40          # đoạn chung dài nhất (đã chuẩn hoá) phải ≥ 40 ký tự
ANCHOR_MIN_SHORT = 25          # hoặc ≥ 25 ký tự VÀ phủ ≥ 80% quote (quote ngắn)


def _norm_map(s: str) -> tuple[str, list[int]]:
    """Chuẩn hoá như _norm nhưng giữ map: vị trí ký tự chuẩn hoá → vị trí gốc (để cắt lại text thật)."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(s.translate(_QUOTES)):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
        else:
            out.append(ch.lower())
            idx.append(i)
            prev_space = False
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def _anchor_in_section(q: str, sec_text: str) -> tuple[str, int] | None:
    """Đoạn chung dài nhất giữa quote (đã norm) và section. Đạt ngưỡng ⇒ trả (text thật đã mở rộng
    tới biên dòng, độ dài anchor); không ⇒ None."""
    body, idx = _norm_map(sec_text)
    if not body:
        return None
    m = difflib.SequenceMatcher(None, q, body, autojunk=False).find_longest_match(0, len(q), 0, len(body))
    if m.size < ANCHOR_MIN_SHORT or (m.size < ANCHOR_MIN_CHARS and m.size < 0.8 * len(q)):
        return None
    start, end = idx[m.b], idx[m.b + m.size - 1] + 1
    # mở rộng tới biên dòng trong section (dòng = câu/bullet/hàng bảng của tài liệu)
    ls = sec_text.rfind("\n", 0, start) + 1
    le = sec_text.find("\n", end)
    le = len(sec_text) if le == -1 else le
    frag = sec_text[ls:le].strip()
    if frag.startswith("#"):            # không trích heading
        frag = sec_text[start:end].strip()
    return frag, m.size


def verify_quote(quote: str, pages: Sequence, fuzzy: float | None = None,
                 anchor: bool = False) -> QuoteHit:
    """Quote có nằm nguyên văn trong một page của agent không? Trả page/heading chứa nó.

    strict (mặc định): quote (chuẩn hoá khoảng trắng/case/dấu) là substring của một section.
    anchor=True (gate v2): nếu strict trượt, lấy ĐOẠN CHUNG DÀI NHẤT giữa quote và section; đủ dài
        (≥40 ký tự, hoặc ≥25 và phủ ≥80% quote) ⇒ khớp, `quote` trả về = dòng tài liệu THẬT chứa
        anchor (vẫn verbatim). Bù lỗi LLM chép kèm "...", gộp heading, bỏ bullet.
    fuzzy: 0<r<1 = difflib ratio theo dòng (thí nghiệm A4, giữ để đối chiếu).
    """
    q = _ELLIPSIS.sub(" ", quote)
    q = _norm(q)
    if len(q) < MIN_QUOTE_CHARS:
        return QuoteHit(False)
    split_sections = _load_knowledge_mod().split_sections
    for page in pages:
        for sec in split_sections(page.markdown):
            body = _norm(sec.text)
            if q in body:
                return QuoteHit(True, page.page_id, str(page.version), sec.heading, quote.strip(), 1.0)
    if anchor:
        best = QuoteHit(False)
        for page in pages:
            for sec in split_sections(page.markdown):
                hit = _anchor_in_section(q, sec.text)
                if hit and hit[1] > best.score:
                    best = QuoteHit(True, page.page_id, str(page.version), sec.heading, hit[0], float(hit[1]))
        if best.ok:
            best.score = min(best.score / max(len(q), 1), 0.99)   # tỉ lệ quote được phủ (<1 = anchor)
            return best
    if fuzzy:
        best = QuoteHit(False)
        for page in pages:
            for sec in split_sections(page.markdown):
                # so từng dòng/câu — quote LLM thường là 1–3 câu
                for line in sec.text.splitlines():
                    ln = _norm(line)
                    if len(ln) < MIN_QUOTE_CHARS:
                        continue
                    r = difflib.SequenceMatcher(None, q, ln).ratio()
                    if r > best.score and r >= fuzzy:
                        best = QuoteHit(True, page.page_id, str(page.version), sec.heading, line.strip(), r)
        return best
    return QuoteHit(False)


# ── LLM client (dev: LM Studio OpenAI-compatible) ────────────────────────────
ChatJson = Callable[[str, str], dict]   # (system, user) -> dict đã parse


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError(f"LLM không trả JSON: {text[:200]!r}")
    return json.loads(m.group(0))


# JSON schema ép structured output (LM Studio chỉ nhận json_schema|text). Hai schema: lô + verify.
RESULTS_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"index": {"type": "integer"}, "solved": {"type": "boolean"},
                       "quote": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["index", "solved", "quote", "reason"]}}},
    "required": ["results"],
}
RESULTS_SCHEMA_EVIDENCE = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"index": {"type": "integer"}, "quote": {"type": "string"},
                       "relation": {"type": "string", "enum": ["exists", "limitation", "unrelated"]},
                       "solved": {"type": "boolean"}, "reason": {"type": "string"}},
        "required": ["index", "quote", "relation", "solved", "reason"]}}},
    "required": ["results"],
}
VERIFY_SCHEMA = {
    "type": "object",
    "properties": {"confirmed": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["confirmed", "reason"],
}


def lmstudio_chat_json(model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
                       think: bool = False, max_tokens: int = 4000, temperature: float = 0.0,
                       stats: dict | None = None) -> ChatJson:
    """OpenAI-compatible client tới LM Studio. `think=False` ⇒ tắt reasoning Qwen3 (/no_think).
    Schema chọn theo system prompt (VERIFY_PROMPT ⇒ VERIFY_SCHEMA, còn lại RESULTS_SCHEMA)."""
    from openai import OpenAI  # lazy

    client = OpenAI(base_url=base_url, api_key="lm-studio")
    stats = stats if stats is not None else {}
    stats.setdefault("calls", 0)
    stats.setdefault("prompt_tokens", 0)
    stats.setdefault("completion_tokens", 0)
    stats.setdefault("seconds", 0.0)

    def chat(system: str, user: str) -> dict:
        if not think:
            user = user + "\n/no_think"
        schema = (VERIFY_SCHEMA if system is VERIFY_PROMPT
                  else RESULTS_SCHEMA_EVIDENCE if system is SYSTEM_PROMPT_EVIDENCE
                  else RESULTS_SCHEMA)
        # ĐÃ ĐO: response_format json_schema làm LM Studio bỏ qua reasoning (<think> rỗng, 12 token).
        # think=True ⇒ KHÔNG ép schema, để model suy luận rồi tự parse JSON sau </think>;
        # think=False ⇒ ép schema (structured output chặt, nhanh).
        kwargs: dict = {}
        if think:
            kwargs["max_tokens"] = max(max_tokens, 10_000)
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["response_format"] = {"type": "json_schema",
                                         "json_schema": {"name": "resolve", "strict": True, "schema": schema}}
        t0 = time.time()
        resp = client.chat.completions.create(
            model=model, temperature=temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            extra_body={"chat_template_kwargs": {"enable_thinking": think}},
            **kwargs,
        )
        stats["calls"] += 1
        stats["seconds"] += time.time() - t0
        if resp.usage:
            stats["prompt_tokens"] += resp.usage.prompt_tokens or 0
            stats["completion_tokens"] += resp.usage.completion_tokens or 0
        return _extract_json(resp.choices[0].message.content or "")

    return chat


# ── Prompt ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a support analyst for TÀI Studio (an internal AI agent platform). You receive the official USER GUIDE of ONE agent and a numbered list of user feedback items (bug reports / feature requests, in Vietnamese or English).

For EACH feedback decide whether the user guide shows that what the user needs ALREADY EXISTS in the product:
- solved=true ONLY IF the guide explicitly describes the feature, the exact steps to do what the user wants, or a documented workaround that achieves the user's goal. You must copy the supporting passage VERBATIM from the guide into "quote" (1–3 consecutive sentences, exact characters, no translation, no paraphrase).
- solved=false if the guide says nothing relevant, OR the guide lists it as a limitation / "not supported" with no workaround, OR the feedback is a technical failure (crash, error 502, network error, broken font, no response, "does not work") that the guide does not explain as intended behaviour.
- Never infer beyond the text. Never claim a feature exists if the guide does not state it. If unsure, answer solved=false. A false "solved" (telling the user a feature exists when it does not) is far worse than a missed one.
- For solved=false you MAY still put a verbatim "quote" if the guide explicitly documents the limitation the user hit; otherwise leave quote empty.

Answer with ONE JSON object only:
{"results":[{"index":<int>,"solved":<bool>,"quote":"<verbatim or empty>","reason":"<one short sentence>"}]}
Include every index exactly once."""

# Biến thể "evidence-first" (thí nghiệm A6): bắt LLM trích passage LIÊN QUAN NHẤT cho MỌI dòng
# trước, rồi mới phân loại quan hệ. Chống lỗi baseline "không trích gì → False" hàng loạt;
# precision vẫn do gate quote + verify pass giữ.
SYSTEM_PROMPT_EVIDENCE = """You are a support analyst for TÀI Studio (an internal AI agent platform). You receive the official USER GUIDE of ONE agent and a numbered list of user feedback items (bug reports / feature requests, in Vietnamese or English).

Work in two steps for EACH feedback item:
1. "quote": search the guide for the passage MOST related to what the user is asking about (the same feature, action, setting, file type, limitation...). Copy it VERBATIM (1–3 consecutive sentences, exact characters, no translation, no paraphrase). If truly nothing in the guide concerns this topic, use an empty string.
2. "relation": classify how the quote relates to the user's need:
   - "exists": the quote shows the thing the user wants ALREADY EXISTS / can already be done — it names the feature, gives the steps, or gives a documented workaround that achieves the user's goal.
   - "limitation": the quote says this is not supported / a known limit, with no workaround that achieves the goal.
   - "unrelated": the quote is only loosely on-topic, or the feedback is a technical failure (crash, error 502, network error, broken font, no response, "does not work") that the guide does not explain as intended behaviour.
Set "solved": true ONLY when relation is "exists". Never infer beyond the text; if unsure choose "unrelated". A false "solved" (claiming a feature exists when it does not) is far worse than a miss.

Answer with ONE JSON object only:
{"results":[{"index":<int>,"quote":"<verbatim or empty>","relation":"exists|limitation|unrelated","solved":<bool>,"reason":"<one short sentence>"}]}
Include every index exactly once."""

VERIFY_PROMPT = """You are auditing a support answer for TÀI Studio. Given ONE user feedback and ONE passage copied verbatim from the official user guide, decide whether the passage truly shows that what the user asks for already exists / can already be done as described (so we may reply "this feature is available, here is how").
Be strict: the passage must address the SAME need, not merely the same topic. A limitation statement or unrelated feature does NOT confirm.
Answer with ONE JSON object only: {"confirmed": <bool>, "reason": "<one short sentence>"}"""


def build_user_prompt(agent: str, pages: Sequence, items: Sequence[dict]) -> str:
    docs = "\n\n".join(f"<<<USER GUIDE: {p.title} (page {p.page_id}, version {p.version})>>>\n{p.markdown}"
                       for p in pages)
    fb = "\n".join(f"[{i}] ({it['label']}) {it['content'].strip()}" for i, it in enumerate(items))
    return f"AGENT: {agent}\n\n{docs}\n\n<<<FEEDBACK ITEMS>>>\n{fb}\n\nReturn the JSON now."


# ── Resolve ──────────────────────────────────────────────────────────────────
@dataclass
class Resolution:
    solved: bool
    referenced: str = ""
    match_type: str = "none"     # how_to | limitation | none  (limitation = quote hợp lệ nhưng solved=False)
    source_ref: str = ""         # page_id@version#heading — dựng bởi code (D6)
    heading: str = ""
    reason: str = ""
    gate: str = ""               # ok | no_quote | quote_not_found | demoted_by_verify | no_doc | llm_error
    llm_solved: bool | None = None
    quote_score: float = 0.0
    extra: dict = field(default_factory=dict)


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def resolve_batch(feedbacks: Sequence[dict], pages, llm: ChatJson, *,
                  batch_size: int = DEFAULT_BATCH_SIZE, fuzzy: float | None = None,
                  verify: bool = False, prompt_style: str = "decide", anchor: bool = False,
                  log: Callable[[str], None] = print) -> list[Resolution]:
    """feedbacks: dict có `agent, content, label` (chỉ bug/new_feature). Trả Resolution cùng thứ tự.

    Gom theo agent (§4.2) → lô ≤ batch_size → 1 call/lô với NGUYÊN VĂN guideline của agent.
    Gate D6 trên từng dòng; tuỳ chọn `verify`: lượt 2 hỏi lại từng dòng solved=True (precision).
    prompt_style: "decide" (SYSTEM_PROMPT) | "evidence" (SYSTEM_PROMPT_EVIDENCE — trích trước, quyết sau).
    anchor: gate v2 (verify_quote anchor=True).
    """
    system = {"decide": SYSTEM_PROMPT, "evidence": SYSTEM_PROMPT_EVIDENCE}[prompt_style]
    out: list[Resolution | None] = [None] * len(feedbacks)
    by_agent: dict[str, list[int]] = {}
    for i, fb in enumerate(feedbacks):
        by_agent.setdefault((fb.get("agent") or "").strip().lower(), []).append(i)

    for agent, idxs in by_agent.items():
        agent_pages = pages_for_agent(pages, agent)
        if not agent_pages:
            for i in idxs:
                out[i] = Resolution(False, gate="no_doc", reason="agent không có guideline (§4.4 → bước 2)")
            log(f"[resolve] {agent}: KHÔNG có tài liệu → {len(idxs)} dòng solved=False")
            continue
        doc_chars = sum(len(p.markdown) for p in agent_pages)
        if doc_chars > CONTEXT_WARN_CHARS:
            log(f"[resolve] ⚠ R9: guideline của {agent} dài {doc_chars} ký tự (> {CONTEXT_WARN_CHARS})")
        for chunk in _chunks(idxs, batch_size):
            items = [feedbacks[i] for i in chunk]
            try:
                data = llm(system, build_user_prompt(agent, agent_pages, items))
                results = {int(r["index"]): r for r in data.get("results", []) if "index" in r}
            except Exception as e:  # noqa: BLE001 — lỗi LLM ⇒ cả lô False, không được claim
                log(f"[resolve] {agent}: LLM lỗi ({type(e).__name__}: {e}) → lô {len(chunk)} dòng False")
                for i in chunk:
                    out[i] = Resolution(False, gate="llm_error", reason=str(e)[:200])
                continue
            for k, i in enumerate(chunk):
                r = results.get(k)
                if r is None:
                    out[i] = Resolution(False, gate="no_quote", reason="LLM bỏ sót index")
                    continue
                llm_solved = bool(r.get("solved"))
                if prompt_style == "evidence":   # solved chỉ hợp lệ khi relation == exists
                    llm_solved = llm_solved and r.get("relation") == "exists"
                quote = (r.get("quote") or "").strip()
                reason = str(r.get("reason") or "")[:300]
                hit = verify_quote(quote, agent_pages, fuzzy=fuzzy, anchor=anchor) if quote else QuoteHit(False)
                if hit.ok:
                    src = f"{hit.page_id}@{hit.version}#{hit.heading}"
                    if llm_solved:
                        out[i] = Resolution(True, hit.quote, "how_to", src, hit.heading, reason, "ok",
                                            llm_solved, hit.score)
                    else:
                        out[i] = Resolution(False, hit.quote, "limitation", src, hit.heading, reason, "ok",
                                            llm_solved, hit.score)
                elif quote:
                    out[i] = Resolution(False, "", "none", "", "", reason, "quote_not_found", llm_solved,
                                        extra={"llm_quote": quote[:300]})
                else:
                    out[i] = Resolution(False, "", "none", "", "", reason, "no_quote", llm_solved)
            n_true = sum(1 for i in chunk if out[i] and out[i].solved)
            log(f"[resolve] {agent}: lô {len(chunk)} dòng → solved=True {n_true}")

    if verify:
        for i, fb in enumerate(feedbacks):
            r = out[i]
            if r is None or not r.solved:
                continue
            user = (f"FEEDBACK ({fb['label']}): {fb['content'].strip()}\n\n"
                    f"GUIDE PASSAGE (from section \"{r.heading}\"): {r.referenced}\n\nReturn the JSON now.")
            try:
                v = llm(VERIFY_PROMPT, user)
                ok = bool(v.get("confirmed"))
            except Exception as e:  # noqa: BLE001
                ok, v = False, {"reason": f"verify error: {e}"}
            r.extra["verify"] = v
            if not ok:
                r.solved, r.match_type, r.gate = False, "limitation", "demoted_by_verify"
    return [r if r is not None else Resolution(False, gate="llm_error") for r in out]


# ── I/O ──────────────────────────────────────────────────────────────────────
def read_csv(path: Path) -> list[dict]:
    with io.open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_output(rows: list[dict], resolutions: dict[int, Resolution], out_csv: Path) -> None:
    """CSV output = mọi cột input + `solved` + `referenced`; dòng không thuộc nhánh knowledge ⇒ rỗng.
    Sidecar debug JSONL cạnh file."""
    fields = list(rows[0].keys()) if rows else []
    for extra in ("solved", "referenced"):
        if extra not in fields:
            fields.append(extra)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with io.open(out_csv, "w", encoding="utf-8", newline="") as f, \
            io.open(out_csv.with_suffix(out_csv.suffix + ".debug.jsonl"), "w", encoding="utf-8") as dbg:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, row in enumerate(rows):
            r = resolutions.get(i)
            rec = {**row, "solved": "" if r is None else str(r.solved), "referenced": "" if r is None else r.referenced}
            w.writerow(rec)
            if r is not None:
                dbg.write(json.dumps({"row": i, "id": row.get("id", ""), **asdict(r)}, ensure_ascii=False) + "\n")


def run_file(in_csv: Path, out_csv: Path, llm: ChatJson, **kw) -> dict[int, Resolution]:
    rows = read_csv(in_csv)
    idx = [i for i, r in enumerate(rows) if (r.get("label") or "").strip() in KNOWLEDGE_LABELS]
    pages = load_pages()
    res = resolve_batch([rows[i] for i in idx], pages, llm, **kw)
    resolutions = dict(zip(idx, res))
    write_output(rows, resolutions, out_csv)
    return resolutions


# ── Eval trên gold solved (D7) ───────────────────────────────────────────────
def _to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"true", "1", "yes"}


def load_gold_solved(path: Path = GOLD_SOLVED_CSV) -> list[dict]:
    rows = read_csv(path)
    for r in rows:
        r["solved_gold"] = _to_bool(r["solved"])
    return rows


def evaluate_gold(llm: ChatJson, *, gold_csv: Path = GOLD_SOLVED_CSV, verbose: bool = True,
                  llm_stats: dict | None = None, **kw) -> dict:
    """P/R/F1 lớp solved=True (metric chính), confusion 2×2, quote_verbatim_rate, heading_match_rate."""
    gold = load_gold_solved(gold_csv)
    pages = load_pages()
    preds = resolve_batch(gold, pages, llm, log=(print if verbose else (lambda s: None)), **kw)

    tp = fp = fn = tn = 0
    quote_ok = 0
    heading_match = 0
    errors = []
    for g, p in zip(gold, preds):
        gs, ps = g["solved_gold"], p.solved
        if ps and gs:
            tp += 1
            if _norm(g.get("referenced", "")) and (_norm(p.referenced) in _norm(g["referenced"])
                                                    or _norm(g["referenced"]) in _norm(p.referenced)):
                heading_match += 1
        elif ps and not gs:
            fp += 1
            errors.append((g["id"], "FP", g["content"][:70], p.referenced[:80], p.reason[:80]))
        elif not ps and gs:
            fn += 1
            errors.append((g["id"], "FN", g["content"][:70], (p.extra.get("llm_quote") or p.referenced)[:80],
                           f"{p.gate}: {p.reason[:60]}"))
        else:
            tn += 1
        if ps and p.referenced and verify_quote(p.referenced, pages_for_agent(pages, g["agent"])).ok:
            quote_ok += 1
    n_pred = tp + fp
    prec = tp / n_pred if n_pred else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    gates: dict[str, int] = {}
    for p in preds:
        gates[p.gate] = gates.get(p.gate, 0) + 1
    metrics = {
        "n": len(gold), "n_gold_true": tp + fn, "n_pred_true": n_pred,
        "precision": prec, "recall": rec, "f1": f1,
        "accuracy": (tp + tn) / len(gold) if gold else 0.0,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "quote_verbatim_rate": quote_ok / n_pred if n_pred else 1.0,
        "reference_overlap_rate": heading_match / tp if tp else 0.0,
        "gates": gates,
        "llm": dict(llm_stats or {}),
        "errors": errors,
        "predictions": [{"id": g["id"], **asdict(p)} for g, p in zip(gold, preds)],
    }
    if verbose:
        print(f"\n== Eval B2 bước 1 (guideline resolve) trên {gold_csv.relative_to(REPO_ROOT)}: n={len(gold)}")
        print(f"  gold solved=True: {tp + fn} | pred True: {n_pred}")
        print(f"  precision {prec:.3f} | recall {rec:.3f} | F1 {f1:.3f} | acc {metrics['accuracy']:.3f}")
        print(f"  confusion: tp={tp} fp={fp} fn={fn} tn={tn}")
        print(f"  quote verbatim (pred True): {metrics['quote_verbatim_rate']:.2f} | "
              f"trùng đoạn gold (trong TP): {metrics['reference_overlap_rate']:.2f}")
        print(f"  gates: {gates}")
        if llm_stats:
            print(f"  llm: {llm_stats}")
        print(f"\n  sai {len(errors)} dòng (id | loại | content | quote | lý do):")
        for e in errors:
            print("    " + " | ".join(str(x) for x in e))
    return metrics


# ── CLI ──────────────────────────────────────────────────────────────────────
def _pop(argv: list[str], flag: str, default=None, cast=str):
    if flag in argv:
        i = argv.index(flag)
        val = cast(argv[i + 1])
        del argv[i:i + 2]
        return val
    return default


def main(argv: list[str]) -> int:
    argv = list(argv)
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    # mặc định = phương án chốt (xem docstring); cờ --no-* / --think... để thí nghiệm lại
    think = "--no-think" not in argv
    verify = "--no-verify" not in argv
    anchor = "--no-anchor" not in argv
    argv = [a for a in argv if a not in {"--think", "--verify", "--anchor",
                                         "--no-think", "--no-verify", "--no-anchor"}]
    batch = _pop(argv, "--batch-size", DEFAULT_BATCH_SIZE, int)
    fuzzy = _pop(argv, "--fuzzy", None, float)
    model = _pop(argv, "--model", DEFAULT_MODEL)
    base_url = _pop(argv, "--base-url", DEFAULT_BASE_URL)
    prompt_style = _pop(argv, "--prompt", "evidence")
    stats: dict = {}
    llm = lmstudio_chat_json(model=model, base_url=base_url, think=think, stats=stats)
    kw = dict(batch_size=batch, fuzzy=fuzzy, verify=verify, prompt_style=prompt_style, anchor=anchor)
    if "--eval" in argv:
        evaluate_gold(llm, llm_stats=stats, **kw)
        return 0
    in_csv = _pop(argv, "--in", None, Path)
    out_csv = _pop(argv, "--out", None, Path)
    if not in_csv or not out_csv:
        print("Cần --in <csv> --out <csv> hoặc --eval", file=sys.stderr)
        return 2
    res = run_file(in_csv, out_csv, llm, **kw)
    n_true = sum(1 for r in res.values() if r.solved)
    print(f"[resolve] {len(res)} dòng bug/new_feature → solved=True {n_true} | ghi {out_csv} (+ .debug.jsonl)")
    print(f"[resolve] llm: {stats}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main(sys.argv[1:]))
