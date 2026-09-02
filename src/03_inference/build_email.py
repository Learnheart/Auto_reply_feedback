"""
Module: inference.deliver (B3) + lát chọn-template của inference.draft (B2)
Architecture: docs/architecture.md
              §2 Overview/Output (cây thư mục `<REVIEW_DIR>/<nhãn>/<feedback_id>.eml`,
                 body HTML song ngữ + block INTERNAL),
              §3 Trách nhiệm từng module (B3: "render .eml (MIME, logo inline, song ngữ) và ghi
                 vào folder theo nhãn trong REVIEW_DIR; ghi eml_path — retry được độc lập"),
              §4.2 Flow B (B3 đọc draft chưa xuất → mkdir folder theo nhãn → ghi <feedback_id>.eml),
              §4.3 Flow C (flag=unclassified ⇒ template theo best_label, file vào folder unclassified),
              §4.4 Flow D (guideline hit ⇒ kịch bản "hướng dẫn"; hết chuỗi ⇒ we_listen),
              §4.5 Flow E (PM mở Outlook, xoá block INTERNAL, gửi tay — hệ thống dừng ở đây),
              §4.6 Data layer (feedback_processing.scenario/source_ref/draft_status/eml_path),
              §5 (.eml qua email.mime, logo cid:, REVIEW_DIR + tên folder ở config)
Impl doc: docs/impl-phase2-auto-feedback-flow.md §3.1 (LLM KHÔNG emit HTML — template render),
          §3.2 (chọn template theo (action_type, rag_hit); không hit ⇒ we_listen, KHÔNG claim),
          §3.3 (style rules → lint assert), §3.4 (UTF-8 thẳng thay HTML entity)
Template spec: template/skill_create_email.md · instance mẫu: template/email_temp.py
Copy config: src/03_inference/email_templates.yaml (admin sửa câu chữ, không sửa code)
Plan: docs/2026-09-03/build-email-eml/plan.md (D1 scenario-là-khoá, D2 box đỏ verbatim,
      D3 box xanh = quote guideline + source_ref, D5 lint bỏ qua vùng verbatim, D6 idempotency)

Đầu vào : CSV sau B2 (`resolve_guideline.py`) — cột `content` bắt buộc; `id, agent, user, label,
          flag, confidence, best_label, solved, referenced` là tuỳ chọn. Sidecar
          `<in>.debug.jsonl` (nếu có) cấp `source_ref` cho citation.
Đầu ra  : `<REVIEW_DIR>/<folder>/<feedback_id>.eml` + `<REVIEW_DIR>/manifest.csv`
          (đúng tên cột `feedback_processing` §4.6 để migrate sang Delta sau).

KHÔNG gọi LLM. Toàn bộ quyết định ở đây là bảng tra + template.

Chạy:
  python src/03_inference/build_email.py --in <b2_resolved.csv> --out-dir <REVIEW_DIR>
  ... --overwrite          # mặc định bỏ qua file đã tồn tại (idempotency theo feedback_id, D6)
  ... --no-internal        # bỏ block INTERNAL (chỉ dùng khi soi layout)
  ... --config <path.yaml> # đổi bank câu mẫu
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import io
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from string import Formatter
from typing import Any, Iterable

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
DEFAULT_CONFIG = _HERE.parent / "email_templates.yaml"

KNOWLEDGE_LABELS = ("bug", "new_feature")          # nhánh cần guideline (§4.4)
ACK_LABELS = {"praise": "thank_you", "complain": "apology"}
SINK_LABEL = "unclassified"
LOW_FLAG = "low_confidence"

# Màu chốt trong template/skill_create_email.md — không đổi ở đây, đổi là vỡ golden test.
RED = "#e53e3e"
GREEN = "#2e7d32"


# ── Config ───────────────────────────────────────────────────────────────────
def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    import yaml  # lazy: test render không cần yaml nếu truyền dict sẵn
    with io.open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key in ("meta", "folders", "scenarios"):
        if key not in cfg:
            raise ValueError(f"{path.name}: thiếu khối '{key}'")
    return cfg


# ── Chọn scenario + folder (plan D1) ─────────────────────────────────────────
def effective_label(label: str, flag: str, best_label: str) -> str:
    """Nhãn dùng để DỰNG NỘI DUNG (§4.3): flag=unclassified ⇒ lấy best_label (score cao nhất).

    Khác với nhãn dùng để CHỌN FOLDER — xem pick_folder(). Hai quyết định độc lập.
    """
    label = (label or "").strip()
    best_label = (best_label or "").strip()
    if flag == SINK_LABEL or label in ("", SINK_LABEL):
        return best_label if best_label and best_label != SINK_LABEL else ""
    return label


def pick_scenario(label: str, flag: str, best_label: str, solved: bool | None) -> str:
    """Bảng quyết định plan §3 D1 → giá trị của feedback_processing.scenario (§4.6)."""
    eff = effective_label(label, flag, best_label)
    if eff in ACK_LABELS:
        return ACK_LABELS[eff]
    if eff in KNOWLEDGE_LABELS:
        # §4.4: chỉ solved=True (quote guideline qua được cổng anchor) mới được claim.
        # Bước 2 backlog chưa hiện thực ⇒ chưa route tới `known_gap` (plan D1).
        return "how_to_answer" if solved else "we_listen"
    return "neutral_ack"


def pick_folder(label: str, flag: str, best_label: str, folders: dict) -> str:
    """Vị trí file. flag=unclassified ⇒ LUÔN vào folder unclassified dù template dựng theo nhãn nào
    (NOTE của user + §4.3: nội dung theo best_label, vị trí theo trạng thái phân loại)."""
    if flag == SINK_LABEL or (label or "").strip() in ("", SINK_LABEL):
        return folders[SINK_LABEL]
    return folders.get(label.strip(), folders[SINK_LABEL])


# ── Điền placeholder: thiếu key ⇒ FAIL LOUD (plan D4) ────────────────────────
class MissingPlaceholder(KeyError):
    pass


def fill(text: str, values: dict[str, str]) -> str:
    for _, key, _, _ in Formatter().parse(text or ""):
        if key is not None and key not in values:
            raise MissingPlaceholder(
                f"câu mẫu dùng {{{key}}} nhưng không có giá trị: {text[:70]!r}")
    return (text or "").format(**values)


# ── Người nhận ───────────────────────────────────────────────────────────────
_NAME_TAIL = re.compile(r"\d+$")


def display_name(row: dict) -> str:
    """Tên hiển thị trong lời chào. Ưu tiên cột `user_name`; không có thì lấy local-part email.

    Cố ý KHÔNG đoán tên tiếng Việt đầy đủ từ email (hangtt -> "Hằng"): đoán sai tên người nhận
    tệ hơn là gọi bằng đúng chuỗi họ tự đăng ký.
    """
    name = (row.get("user_name") or "").strip()
    if name:
        return name
    email = (row.get("user") or row.get("user_email") or "").strip()
    local = email.split("@", 1)[0] if email else ""
    local = _NAME_TAIL.sub("", local)
    return local.capitalize() if local else "bạn"


# ── Render HTML ──────────────────────────────────────────────────────────────
def _esc(text: str) -> str:
    """Escape + giữ xuống dòng. Mọi nội dung ĐỘNG đi qua đây (impl §3.1: không inject được)."""
    return html_mod.escape(text or "", quote=False).replace("\n", "<br/>")


def _box(content_html: str, *, bg: str, border: str, verbatim: bool = True) -> str:
    """Box nội dung. `data-verbatim` đánh dấu vùng lint BỎ QUA (plan D5): lời user và quote
    tài liệu là nguyên văn, ta không được sửa em-dash trong đó."""
    mark = ' data-verbatim="1"' if verbatim else ""
    return (f'<div{mark} style="background:{bg};border-left:4px solid {border};'
            f'padding:12px 16px;margin:12px 0;border-radius:4px;">{content_html}</div>')


def _internal_block(ctx: dict, meta: dict) -> str:
    cfg = meta["internal"]
    warns = []
    if ctx["flag"] == SINK_LABEL:
        warns.append(cfg["unclassified_warning"])
    elif ctx["flag"] == LOW_FLAG:
        warns.append(cfg["low_confidence_warning"])
    if ctx["scenario"] != "how_to_answer":
        warns.append(cfg["no_source_warning"])
    rows = [
        ("feedback_id", ctx["feedback_id"]),
        ("agent", ctx["agent"]),
        ("label / flag", f'{ctx["label"] or "-"} / {ctx["flag"] or "-"}'),
        ("confidence", ctx["confidence"]),
        ("best_label", ctx["best_label"] or "-"),
        ("scenario", ctx["scenario"]),
        ("source_ref", ctx["source_ref"] or "(none)"),
    ]
    body = "".join(
        f'<tr><td style="padding:1px 12px 1px 0;color:#777;white-space:nowrap;">{_esc(k)}</td>'
        f'<td style="padding:1px 0;"><code>{_esc(str(v))}</code></td></tr>'
        for k, v in rows)
    warn_html = "".join(f'<div style="margin-top:6px;color:#b34700;font-weight:600;">'
                        f'{_esc(w)}</div>' for w in warns)
    return ('<!--INTERNAL-START-->'
            f'<div id="internal-block" style="margin:16px 32px 0;padding:12px 16px;'
            f'background:#fffbe6;border:1px dashed #d4a017;border-radius:4px;'
            f'font-family:Consolas,monospace;font-size:12px;color:#5a4600;">'
            f'<div style="font-weight:700;margin-bottom:6px;">{_esc(cfg["title"])}</div>'
            f'<table style="border-collapse:collapse;">{body}</table>{warn_html}</div>'
            '<!--INTERNAL-END-->')


def _section(lang: str, copy: dict, ctx: dict, meta: dict, template: str) -> str:
    """Một nửa ngôn ngữ của body. VI và EN dùng CÙNG hàm ⇒ không lệch cấu trúc."""
    L = meta["labels"]
    vals = {"name": ctx["name"], "agent": ctx["agent"] or "TÀI Studio"}
    parts = [f'<p>{_esc(fill(copy["greeting"], vals))}</p>',
             f'<p>{_esc(fill(copy["opening"], vals))}</p>',
             f'<p>{_esc(fill(copy["lead"], vals))}</p>',
             f'<p><strong>{_esc(L[f"feedback_box_{lang}"])}</strong></p>',
             _box(_esc(ctx["feedback_text"]), bg="#fff5f5", border=RED)]
    if template == "we_resolved":
        src = ""
        if ctx["source_ref"]:
            src = (f'<br/><br/><span style="font-size:12px;color:#555;">'
                   f'{_esc(L[f"source_prefix_{lang}"])} <code>{_esc(ctx["source_ref"])}</code></span>')
        parts += [f'<p><strong>{_esc(L[f"resolution_box_{lang}"])}</strong></p>',
                  _box(_esc(ctx["resolution_text"]) + src, bg="#e8f5e9", border=GREEN)]
    parts.append(f'<p>{_esc(fill(copy["closing"], vals))}</p>')
    return "".join(parts)


def render_html(ctx: dict, cfg: dict, *, include_internal: bool = True) -> str:
    meta, sc = cfg["meta"], cfg["scenarios"][ctx["scenario"]]
    template = sc["template"]
    internal = _internal_block(ctx, meta) if include_internal else ""
    return (
        '<!DOCTYPE html>\n<html>\n<head><meta charset="UTF-8"></head>\n'
        '<body style="margin:0;padding:20px;background:#f5f5f5;'
        "font-family:'Segoe UI',Arial,sans-serif;\">\n"
        '<div style="max-width:640px;margin:0 auto;background:#ffffff;'
        'border-radius:8px;overflow:hidden;">\n'
        f'{internal}\n'
        f'<div style="padding:24px 32px 0;text-align:center;">'
        f'<img src="cid:{meta["logo_cid"]}" style="height:48px;width:auto;" '
        f'alt="{_esc(meta["logo_alt"])}" /></div>\n'
        f'<div style="text-align:right;padding:12px 32px 0;font-size:12px;color:#888888;'
        f'font-style:italic;">{_esc(meta["language_note"])}</div>\n'
        f'<div style="padding:24px 32px;line-height:1.7;color:#333333;font-size:14px;">'
        f'{_section("vi", sc["vi"], ctx, meta, template)}</div>\n'
        f'<div style="margin:0 32px;border-top:2px solid {RED};padding-top:8px;text-align:center;">'
        f'<span style="background:#ffffff;padding:0 12px;font-size:12px;color:{RED};'
        f'font-weight:600;position:relative;top:-18px;">{_esc(meta["separator_label"])}</span></div>\n'
        f'<div style="padding:12px 32px 24px;line-height:1.7;color:#333333;font-size:14px;">'
        f'{_section("en", sc["en"], ctx, meta, template)}</div>\n'
        f'{_footer(meta)}\n</div>\n</body>\n</html>\n')


def _footer(meta: dict) -> str:
    f = meta["footer"]
    mails = "<br/>".join(
        f'<a href="mailto:{_esc(m)}" style="color:#1a73e8;text-decoration:none;">{_esc(m)}</a>'
        for m in f["support_emails"])
    return (f'<div style="padding:20px 32px;background:#f8f9fa;border-top:2px solid {RED};'
            f'font-size:13px;color:#666666;line-height:1.8;">'
            f'<p><strong>{_esc(f["support_intro"])}</strong></p><p>{mails}</p>'
            f'<p><a href="{_esc(f["discover_url"])}" style="color:#1a73e8;text-decoration:none;">'
            f'{_esc(f["discover_text"])}</a></p>'
            f'<p style="margin-top:16px;">{_esc(f["signoff"])}<br/>'
            f'<strong>{_esc(f["team"])}</strong><br/>{_esc(f["org"])}</p></div>')


# ── Lint style (impl §3.3, phạm vi thu hẹp theo plan D5) ─────────────────────
_INTERNAL_RE = re.compile(r"<!--INTERNAL-START-->.*?<!--INTERNAL-END-->", re.S)
_VERBATIM_RE = re.compile(r'<div data-verbatim="1".*?</div>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF←-⇿☀-➿️⬀-⯿]")
_WRONG_BRAND_RE = re.compile(r"T[àa]i Studio")


def lintable_text(html: str) -> str:
    """Phần copy DO TEMPLATE SINH RA: bỏ block INTERNAL và 2 box verbatim (lời user + quote
    tài liệu). Lint chỉ được phán xét chữ ta viết, không phán xét chữ ta trích (plan D5)."""
    body = _INTERNAL_RE.sub("", html)
    body = _VERBATIM_RE.sub("", body)
    return html_mod.unescape(_TAG_RE.sub(" ", body))


def lint_html(html: str) -> None:
    text = lintable_text(html)
    if "—" in text:
        raise AssertionError("em-dash trong copy template (skill_create_email.md:100)")
    m = _EMOJI_RE.search(text)
    if m:
        raise AssertionError(f"emoji/icon trong body: {m.group()!r} (skill:104)")
    if "TÀI Studio" not in text:
        raise AssertionError("body không nhắc đúng 'TÀI Studio'")
    m = _WRONG_BRAND_RE.search(text)
    if m:
        raise AssertionError(f"sai casing thương hiệu: {m.group()!r} (skill:6)")
    if "cid:" not in html:
        raise AssertionError("logo không nhúng inline (thiếu cid:)")


# ── Dựng .eml ────────────────────────────────────────────────────────────────
def build_eml(ctx: dict, cfg: dict, *, include_internal: bool = True) -> tuple[str, str]:
    """→ (nội dung .eml, html). Logo nhúng MIME related theo template/skill_create_email.md."""
    meta = cfg["meta"]
    html = render_html(ctx, cfg, include_internal=include_internal)
    lint_html(html)

    msg = MIMEMultipart("related")
    msg["Subject"] = meta["subject"]
    msg["From"] = meta["from"]
    msg["To"] = ctx["to_email"]
    msg["Cc"] = ",".join(meta["cc"])
    msg["X-Unsent"] = "1"                      # Outlook mở ở chế độ compose
    msg.attach(MIMEText(html, "html", "utf-8"))

    logo = REPO_ROOT / meta["logo_path"]
    if not logo.exists():
        raise FileNotFoundError(f"không thấy logo: {logo}")
    img = MIMEImage(logo.read_bytes(), _subtype="png")
    img.add_header("Content-ID", f'<{meta["logo_cid"]}>')
    img.add_header("Content-Disposition", "inline", filename=logo.name)
    msg.attach(img)
    return msg.as_string(), html


# ── Chuẩn bị context từ 1 dòng CSV ───────────────────────────────────────────
def _to_bool(s: Any) -> bool | None:
    s = str(s or "").strip().lower()
    if s in {"true", "1", "yes"}:
        return True
    if s in {"false", "0", "no"}:
        return False
    return None


def build_context(row: dict, cfg: dict, *, row_idx: int = 0,
                  source_ref: str = "") -> dict:
    label = (row.get("label") or "").strip()
    flag = (row.get("flag") or "").strip() or ("ok" if label and label != SINK_LABEL else SINK_LABEL)
    best_label = (row.get("best_label") or "").strip() or (label if label != SINK_LABEL else "")
    solved = _to_bool(row.get("solved"))
    scenario = pick_scenario(label, flag, best_label, solved)
    referenced = (row.get("referenced") or "").strip()
    if scenario != "how_to_answer":
        # Không có quote qua cổng ⇒ KHÔNG có box xanh, KHÔNG có citation (O4/impl §3.2).
        referenced, source_ref = "", ""
    try:
        conf = f'{float(row.get("confidence")):.3f}'
    except (TypeError, ValueError):
        conf = "-"
    return {
        "feedback_id": (row.get("id") or row.get("feedback_id") or f"fb_{row_idx:04d}").strip(),
        "agent": (row.get("agent") or "").strip(),
        "to_email": (row.get("user") or row.get("user_email") or "").strip(),
        "name": display_name(row),
        "label": label,
        "flag": flag,
        "best_label": best_label,
        "confidence": conf,
        "scenario": scenario,
        "source_ref": source_ref,
        "feedback_text": (row.get("content") or "").strip(),
        "resolution_text": referenced,
        "folder": pick_folder(label, flag, best_label, cfg["folders"]),
    }


def load_source_refs(in_csv: Path) -> dict[str, str]:
    """`source_ref` nằm ở sidecar debug của B2, không ở CSV. Không có sidecar ⇒ {} (citation rỗng)."""
    side = in_csv.with_suffix(in_csv.suffix + ".debug.jsonl")
    if not side.exists():
        return {}
    out: dict[str, str] = {}
    with io.open(side, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            key = rec.get("id") or f'#{rec.get("row")}'
            out[key] = rec.get("source_ref", "") or ""
    return out


# ── Runner ───────────────────────────────────────────────────────────────────
MANIFEST_FIELDS = ["feedback_id", "agent", "label", "confidence", "best_label", "flag",
                   "scenario", "source_ref", "draft_status", "eml_path", "delivered_at"]


@dataclass
class DeliverStats:
    written: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    by_folder: dict[str, int] = field(default_factory=dict)


def run_rows(rows: Iterable[dict], out_dir: Path, cfg: dict, *,
             overwrite: bool = False, include_internal: bool = True,
             source_refs: dict[str, str] | None = None) -> DeliverStats:
    source_refs = source_refs or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = DeliverStats()
    manifest: list[dict] = []
    for i, row in enumerate(rows):
        ctx = build_context(row, cfg, row_idx=i,
                            source_ref=source_refs.get(row.get("id", ""), "")
                            or source_refs.get(f"#{i}", ""))
        target = out_dir / ctx["folder"] / f'{ctx["feedback_id"]}.eml'
        rec = {"feedback_id": ctx["feedback_id"], "agent": ctx["agent"], "label": ctx["label"],
               "confidence": ctx["confidence"], "best_label": ctx["best_label"],
               "flag": ctx["flag"], "scenario": ctx["scenario"], "source_ref": ctx["source_ref"],
               "eml_path": str(target.relative_to(out_dir)).replace("\\", "/"),
               "delivered_at": ""}
        if target.exists() and not overwrite:
            stats.skipped += 1
            rec["draft_status"] = "drafted"          # D6: idempotency theo tên file
            manifest.append(rec)
            continue
        try:
            eml, _ = build_eml(ctx, cfg, include_internal=include_internal)
        except Exception as exc:                      # lint fail / thiếu placeholder / thiếu logo
            stats.errors.append((ctx["feedback_id"], f"{type(exc).__name__}: {exc}"))
            rec["draft_status"] = "error"
            rec["eml_path"] = ""
            manifest.append(rec)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with io.open(target, "w", encoding="utf-8", newline="") as f:
            f.write(eml)
        stats.written += 1
        stats.by_folder[ctx["folder"]] = stats.by_folder.get(ctx["folder"], 0) + 1
        rec["draft_status"] = "drafted"
        rec["delivered_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifest.append(rec)

    with io.open(out_dir / "manifest.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(manifest)
    return stats


def run_file(in_csv: Path, out_dir: Path, *, config: Path = DEFAULT_CONFIG,
             overwrite: bool = False, include_internal: bool = True) -> DeliverStats:
    with io.open(in_csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return run_rows(rows, out_dir, load_config(config), overwrite=overwrite,
                    include_internal=include_internal, source_refs=load_source_refs(in_csv))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="B3 deliver — dựng .eml vào REVIEW_DIR theo nhãn")
    ap.add_argument("--in", dest="in_csv", required=True, type=Path)
    ap.add_argument("--out-dir", dest="out_dir", required=True, type=Path)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--no-internal", dest="internal", action="store_false")
    a = ap.parse_args(argv)

    st = run_file(a.in_csv, a.out_dir, config=a.config,
                  overwrite=a.overwrite, include_internal=a.internal)
    print(f"[B3] ghi {st.written} .eml | bỏ qua {st.skipped} (đã có) | lỗi {len(st.errors)}")
    for folder, n in sorted(st.by_folder.items()):
        print(f"       {folder:<14} {n}")
    for fid, err in st.errors:
        print(f"  ERROR {fid}: {err}")
    print(f"  → {a.out_dir}")
    return 1 if st.errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
