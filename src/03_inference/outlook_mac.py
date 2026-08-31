"""OutlookMacSink — tạo draft THẲNG vào Outlook for Mac qua AppleScript. macOS-only, KHÔNG cần Azure.

Module: inference.deliver (B3) — sink thay thế khi KHÔNG có quyền đăng ký app Azure/Graph.
Architecture: docs/architecture.md §5 (Email delivery — fallback ngoài Graph). Impl: deliver.py §6 (DraftSink).
Plan: docs/2026-08-27/ack-reply-eml/plan.md.

Vì sao đường này:
- Không đăng ký được app Azure ⇒ Graph (và MCP-qua-Graph) đều tắc.
- Outlook for Mac (>=16, NSAppleScriptEnabled) cho set `content` = **HTML content of a message** (Outlook.sdef)
  ⇒ tạo draft GIỮ NGUYÊN email thương hiệu song ngữ + style, khác AppleScript kiểu cũ chỉ set text.

Khác GraphSink/EmlSink:
- Chạy trên MÁY có Outlook desktop đang đăng nhập (không unattended/Databricks được).
- Logo `cid:tai_logo` → **data-URI** (AppleScript không gắn inline attachment theo Content-ID).
- Draft nằm ở **Drafts** của account đang đăng nhập (không route được vào folder-theo-category như Graph);
  block INTERNAL GIỮ trong body (PM đọc intent/flag rồi XOÁ trước khi Send — như GraphSink).

Chạy: python deliver.py --outlook-mac           # 1 draft demo
      python pipeline.py --outlook-mac --ack-only --limit N
"""

from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
from pathlib import Path

from deliver import Draft, DraftRef, _load_logo_b64

# osacompile check được; đọc HTML từ FILE (tránh giới hạn arg + lỗi escape); nhận argv (an toàn injection, UTF-8 OK).
_APPLESCRIPT = r'''
on run argv
    set theSubject to item 1 of argv
    set htmlPath to item 2 of argv
    set toAddr to item 3 of argv
    set ccRaw to item 4 of argv
    set theContent to (read (POSIX file htmlPath) as «class utf8»)
    tell application "Microsoft Outlook"
        set newMsg to make new outgoing message with properties {subject:theSubject, content:theContent}
        if toAddr is not "" then
            make new to recipient at newMsg with properties {email address:{address:toAddr}}
        end if
        if ccRaw is not "" then
            set AppleScript's text item delimiters to ","
            repeat with a in (text items of ccRaw)
                set aa to (contents of a) as string
                if aa is not "" then
                    make new cc recipient at newMsg with properties {email address:{address:aa}}
                end if
            end repeat
            set AppleScript's text item delimiters to ""
        end if
        return (id of newMsg) as string
    end tell
end run
'''


def _inline_logo_as_data_uri(html: str) -> str:
    """Thay src=cid:tai_logo bằng data-URI (AppleScript không có MIME part để resolve cid)."""
    b64 = _load_logo_b64()
    if not b64:
        return html
    return html.replace("cid:tai_logo", f"data:image/png;base64,{b64}")


class OutlookMacSink:
    """Tạo draft trong Outlook for Mac. `ensure_folder` no-op (draft luôn vào Drafts)."""

    def __init__(self, cc: list[str] | None = None):
        if sys.platform != "darwin":
            raise RuntimeError("OutlookMacSink chỉ chạy trên macOS (cần Outlook for Mac).")
        self.cc = cc or []

    def ensure_folder(self, name: str) -> str:
        return "Drafts"   # Outlook Mac AppleScript đặt draft vào Drafts; không route folder-category.

    def deliver(self, draft: Draft) -> DraftRef:
        html = _inline_logo_as_data_uri(draft.html_body)   # INTERNAL block GIỮ trong body (PM xoá trước Send)
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(html)
            html_path = f.name
        try:
            proc = subprocess.run(
                ["osascript", "-", draft.subject, html_path, draft.to_email or "", ",".join(self.cc)],
                input=_APPLESCRIPT, capture_output=True, text=True, timeout=60,
            )
        finally:
            Path(html_path).unlink(missing_ok=True)
        if proc.returncode != 0:
            raise RuntimeError(f"osascript lỗi (rc={proc.returncode}): {proc.stderr.strip()[:400]}")
        msg_id = proc.stdout.strip() or None
        return DraftRef(message_id=msg_id, location="Outlook:Drafts")


if __name__ == "__main__":
    # smoke test: tạo 1 draft demo trong Outlook (nhớ xoá sau khi kiểm).
    from deliver import _demo_response, build_draft
    from render_email import CC_LIST

    resp, fid, to = _demo_response()
    d = build_draft(resp, fid, to)
    ref = OutlookMacSink(cc=list(CC_LIST)).deliver(d)
    print(f"✅ Tạo draft trong Outlook Drafts: id={ref.message_id}")
    print("   Mở Outlook → Drafts để kiểm (song ngữ + logo + block INTERNAL để xoá).")
