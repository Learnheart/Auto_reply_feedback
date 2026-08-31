"""B3 deliver — đặt draft vào folder Outlook đặt tên theo category (intent), trong shared mailbox.

Module: inference.deliver (B3).
Architecture: docs/architecture.md §3 (inference.deliver), §4.2 Flow B3, §4.5 (draft_status/draft_ref).
Impl: docs/impl-phase2-auto-feedback-flow.md §6 (DraftSink Protocol: GraphSink + EmlSink).
Plan: docs/2026-08-26/deliver-outlook-graph/plan.md (R1, R3, R5, D2, D3).

═══════════════════════════════════════════════════════════════════════════════════════════════
 SETUP GRAPH (app-only) — làm MỘT LẦN với Azure admin (D1):
   1. Azure AD → App registrations → New registration (single tenant). Ghi lại Application (client) ID
      + Directory (tenant) ID.
   2. Certificates & secrets → New client secret. Ghi lại VALUE (chỉ hiện một lần).
   3. API permissions → Microsoft Graph → APPLICATION permissions → Mail.ReadWrite (+ Mail.Send nếu sau
      này auto-send) → Grant admin consent.
   4. BẢO MẬT BẮT BUỘC: Application Access Policy giới hạn app chỉ vào taistudio@ (nếu không app-only
      có quyền ghi MỌI mailbox). PowerShell Exchange Online:
        New-ApplicationAccessPolicy -AppId <client_id> -PolicyScopeGroupId <group chứa taistudio@> \\
          -AccessRight RestrictAccess -Description "TAI Studio auto-reply deliver"
   5. Điền env (đừng commit secret):
        export AZ_TENANT_ID=...  AZ_CLIENT_ID=...  AZ_CLIENT_SECRET=...
        export SHARED_MAILBOX=taistudio@techcombank.com.vn
   6. pip install msal
   7. python deliver.py --dry-run   # in payload, KHÔNG gửi — kiểm trước
      python deliver.py             # tạo draft thật vào folder theo intent

 Spike ① (impl B-2, LÀM TRƯỚC khi tin outcome-sync): tạo 1 draft, gửi tay, đọc lại từ Sent xem
 X-Feedback-Id (singleValueExtendedProperties) còn sống không. O4/O5 treo vào đây.
───────────────────────────────────────────────────────────────────────────────────────────────
 SETUP-DELEGATED (device-code) — NHẸ, chạy được ngay không cần secret/Access Policy:
   1. Azure AD → App registrations → New registration. Ghi Application (client) ID + tenant ID.
      Authentication → Advanced settings → "Allow public client flows" = YES.
   2. API permissions → Microsoft Graph → DELEGATED → Mail.ReadWrite (offline_access thường mặc định).
      Admin consent: delegated Mail.ReadWrite thường KHÔNG cần (tuỳ policy tenant).
   3. Điền env (KHÔNG có secret):
        export AZ_CLIENT_ID=...   [AZ_TENANT_ID=... mặc định 'organizations']
        export SHARED_MAILBOX=me  # "me" = Drafts của chính admin; hoặc UPN shared mailbox có quyền
   4. pip install msal
   5. python deliver.py --graph-delegated
      → lần đầu IN link https://microsoft.com/devicelogin + mã, admin nhập rồi login; token cache ra
        ~/.tai_graph_token_cache.json (đổi qua GRAPH_TOKEN_CACHE) ⇒ lần sau tự chạy silent, không login lại.
   Batch: python pipeline.py --graph-delegated --ack-only --limit N
═══════════════════════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import base64
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from graph_client import GraphAuth, GraphClient, GraphDelegatedAuth, build_message
from render_email import CC_LIST, SUBJECT, render_html, strip_internal_block
from respond import PersonalizedResponse

# category → folder: mặc định = intent_id (yêu cầu "folder với category name"). None/unclassified → sink folder.
UNCLASSIFIED_FOLDER = "⚠ Unclassified"


def folder_for(resp: PersonalizedResponse) -> str:
    """Tên folder Outlook cho draft = intent_id (category). unclassified/None → folder cảnh báo."""
    return resp.intent_id or UNCLASSIFIED_FOLDER


@dataclass
class Draft:
    feedback_id: str
    to_email: str
    subject: str
    html_body: str
    folder: str


@dataclass
class DraftRef:
    message_id: str | None      # Graph messageId → ghi feedback_processing.draft_ref
    web_link: str | None = None
    location: str | None = None  # đường dẫn .eml (nhánh EmlSink)


def build_draft(
    resp: PersonalizedResponse,
    feedback_id: str,
    to_email: str,
    name: str | None = None,
) -> Draft:
    """PersonalizedResponse → Draft (render HTML + chọn folder). Điền {name} runtime (respond để trống).

    name=None ⇒ VI dùng "bạn", EN dùng "there" (không biết tên người nhận). Có tên ⇒ dùng cho cả hai.
    """
    vi_name = name or "bạn"
    en_name = name or "there"
    filled = replace(
        resp,
        body_vi=(resp.body_vi or "").replace("{name}", vi_name),
        body_en=(resp.body_en or "").replace("{name}", en_name),
    )
    return Draft(
        feedback_id=feedback_id,
        to_email=to_email,
        subject=SUBJECT,
        html_body=render_html(filled, feedback_id),
        folder=folder_for(filled),
    )


# ── Protocol (impl §6) ───────────────────────────────────────────────────────
class DraftSink(Protocol):
    def ensure_folder(self, name: str) -> str: ...
    def deliver(self, draft: Draft) -> DraftRef: ...


# ── GraphSink (primary) ──────────────────────────────────────────────────────
def _load_logo_b64() -> str | None:
    """Đọc logo TÀI → base64 cho inline cid:tai_logo. Asset thiếu ⇒ None, không crash (B-1)."""
    for p in (
        Path(__file__).resolve().parents[1] / "assets" / "tai_logo.png",   # src/assets/tai_logo.png
        Path(__file__).resolve().parents[2] / "template" / "icon TAI.png",  # fallback cũ
        Path(__file__).resolve().parents[2] / "template" / "icon_TAI.png",
    ):
        if p.exists():
            return base64.b64encode(p.read_bytes()).decode()
    return None


class GraphSink:
    """Đẩy draft vào shared mailbox qua Graph. `ensure_folder` idempotent + cache id trong phiên (R3/R5)."""

    def __init__(self, client: GraphClient, cc: list[str] | None = None):
        self.client = client
        self.cc = cc or []
        self._logo_b64 = _load_logo_b64()
        self._folder_cache: dict[str, str] = {}

    def ensure_folder(self, name: str) -> str:
        if name not in self._folder_cache:
            self._folder_cache[name] = self.client.ensure_folder(name)
        return self._folder_cache[name]

    def deliver(self, draft: Draft) -> DraftRef:
        folder_id = self.ensure_folder(draft.folder)
        message = build_message(
            subject=draft.subject,
            html_body=draft.html_body,
            to_email=draft.to_email,
            feedback_id=draft.feedback_id,
            cc=self.cc,
            inline_logo_b64=self._logo_b64,
        )
        created = self.client.create_draft(folder_id, message)
        return DraftRef(message_id=created.get("id"), web_link=created.get("webLink"))

    def build_payload(self, draft: Draft) -> dict:
        """Payload Graph mà KHÔNG gửi — cho --dry-run/spike/test (R7)."""
        return build_message(
            subject=draft.subject,
            html_body=draft.html_body,
            to_email=draft.to_email,
            feedback_id=draft.feedback_id,
            cc=self.cc,
            inline_logo_b64=self._logo_b64,
        )


# ── EmlSink (fallback vĩnh viễn, không cần cred — impl §6 / A2) ───────────────
class EmlSink:
    """Ghi .eml (X-Unsent:1) vào folder-theo-category trên đĩa. INTERNAL ra file sidecar, body SẠCH (D3)."""

    def __init__(self, out_dir: Path, cc: list[str] | None = None, from_email: str = "taistudio@techcombank.com.vn"):
        self.out_dir = Path(out_dir)
        self.cc = cc or []
        self.from_email = from_email

    def ensure_folder(self, name: str) -> str:
        d = self.out_dir / _safe_dirname(name)
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def deliver(self, draft: Draft) -> DraftRef:
        from email.mime.image import MIMEImage
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        folder = Path(self.ensure_folder(draft.folder))
        # Nhánh .eml KHÔNG có Job C phát hiện leak ⇒ đưa INTERNAL ra sidecar, body email SẠCH (impl §5).
        clean_html = strip_internal_block(draft.html_body)

        msg = MIMEMultipart("related")
        msg["Subject"] = draft.subject
        msg["From"] = self.from_email
        msg["To"] = draft.to_email
        if self.cc:
            msg["Cc"] = ",".join(self.cc)
        msg["X-Unsent"] = "1"
        msg["X-Feedback-Id"] = draft.feedback_id
        msg.attach(MIMEText(clean_html, "html", "utf-8"))

        logo_b64 = _load_logo_b64()
        if logo_b64:
            img = MIMEImage(base64.b64decode(logo_b64), _subtype="png")
            img.add_header("Content-ID", "<tai_logo>")
            img.add_header("Content-Disposition", "inline", filename="icon_TAI.png")
            msg.attach(img)

        eml_path = folder / f"{draft.feedback_id}.eml"
        eml_path.write_text(msg.as_string(), encoding="utf-8")
        # sidecar INTERNAL cạnh .eml (nội dung nội bộ tách khỏi body gửi user)
        (folder / f"{draft.feedback_id}.internal.md").write_text(draft.html_body, encoding="utf-8")
        return DraftRef(message_id=None, location=str(eml_path))


def _safe_dirname(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_⚠" else "_" for c in name).strip() or "unclassified"


# ── Config từ env ────────────────────────────────────────────────────────────
def graph_sink_from_env(cc: list[str] | None = None) -> GraphSink:
    """Dựng GraphSink từ env (AZ_TENANT_ID/AZ_CLIENT_ID/AZ_CLIENT_SECRET/SHARED_MAILBOX). Secret KHÔNG hardcode."""
    missing = [k for k in ("AZ_TENANT_ID", "AZ_CLIENT_ID", "AZ_CLIENT_SECRET") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Thiếu env: {missing}. Xem §SETUP trong deliver.py.")
    auth = GraphAuth(
        tenant_id=os.environ["AZ_TENANT_ID"],
        client_id=os.environ["AZ_CLIENT_ID"],
        client_secret=os.environ["AZ_CLIENT_SECRET"],
    )
    mailbox = os.environ.get("SHARED_MAILBOX", "taistudio@techcombank.com.vn")
    return GraphSink(GraphClient(auth, mailbox), cc=cc)


def graph_sink_from_delegated_env(cc: list[str] | None = None) -> GraphSink:
    """Dựng GraphSink delegated device-code từ env (AZ_CLIENT_ID [+ AZ_TENANT_ID, SHARED_MAILBOX]).

    KHÔNG cần client secret. `SHARED_MAILBOX` mặc định "me" (Drafts của tài khoản đăng nhập); đặt UPN
    shared mailbox nếu tài khoản đó có quyền. Login 1 lần (in link+mã), token cache lại cho lần sau.
    """
    client_id = os.environ.get("AZ_CLIENT_ID")
    if not client_id:
        raise RuntimeError("Thiếu env AZ_CLIENT_ID (public client app-registration). Xem §SETUP-DELEGATED.")
    auth = GraphDelegatedAuth(
        client_id=client_id,
        tenant_id=os.environ.get("AZ_TENANT_ID", "organizations"),
    )
    mailbox = os.environ.get("SHARED_MAILBOX", "me")
    return GraphSink(GraphClient(auth, mailbox), cc=cc)


# ── Demo / CLI ───────────────────────────────────────────────────────────────
def _demo_response() -> tuple[PersonalizedResponse, str, str]:
    """1 response mẫu praise (song ngữ, qua bank tĩnh — KHÔNG cần classify/embed/LLM) để smoke-test deliver."""
    from classify import FLAG_OK, Classification
    from respond import respond

    cls = Classification(
        feedback="TÀI Studio dùng rất ổn, tạo slide nhanh và đẹp, cảm ơn team nhiều",
        intent_id="praise",
        action_type="ack_only",
        confidence=0.72,
        flag=FLAG_OK,
        best_intent_id="praise",
        best_confidence=0.72,
        evidence="dùng rất ổn",
    )
    return respond(cls), "fb_0000", "hangtt@techcombank.com.vn"


def main() -> None:
    ap = argparse.ArgumentParser(description="B3 deliver — draft vào folder Outlook theo category.")
    ap.add_argument("--dry-run", action="store_true", help="in payload Graph, KHÔNG gửi (không cần cred)")
    ap.add_argument("--eml", metavar="OUT_DIR", help="đi nhánh EmlSink: ghi .eml vào OUT_DIR/<category>/")
    ap.add_argument("--graph-delegated", action="store_true",
                    help="đẩy draft qua Graph DELEGATED (device-code login 1 lần) thay app-only secret")
    ap.add_argument("--outlook-mac", action="store_true",
                    help="tạo draft THẲNG vào Outlook for Mac qua AppleScript (macOS, KHÔNG cần Azure)")
    ap.add_argument("--cc", default="", help="CC list, phẩy ngăn cách (mặc định rỗng — xem §10.1 impl)")
    args = ap.parse_args()

    cc = [c.strip() for c in args.cc.split(",") if c.strip()] or list(CC_LIST)
    resp, feedback_id, to_email = _demo_response()
    draft = build_draft(resp, feedback_id, to_email)
    print(f"feedback_id={feedback_id}  →  folder «{draft.folder}»  to={to_email}")

    if args.eml:
        ref = EmlSink(Path(args.eml), cc=cc).deliver(draft)
        print(f"✅ .eml ghi tại: {ref.location}  (INTERNAL ở sidecar cùng thư mục)")
        return

    if args.outlook_mac:
        from outlook_mac import OutlookMacSink

        ref = OutlookMacSink(cc=cc).deliver(draft)
        print(f"✅ draft tạo trong Outlook Drafts: id={ref.message_id} (mở Outlook để kiểm)")
        return

    if args.dry_run:
        import json

        sink = GraphSink.__new__(GraphSink)      # không cần cred: chỉ build payload
        sink.cc = cc
        sink._logo_b64 = _load_logo_b64()
        payload = sink.build_payload(draft)
        payload["body"]["content"] = payload["body"]["content"][:200] + " …(cắt)"
        print("Graph payload (dry-run):\n" + json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n→ sẽ POST /users/{os.environ.get('SHARED_MAILBOX','taistudio@techcombank.com.vn')}"
              f"/mailFolders/<{draft.folder}>/messages")
        return

    sink = graph_sink_from_delegated_env(cc=cc) if args.graph_delegated else graph_sink_from_env(cc=cc)
    ref = sink.deliver(draft)
    print(f"✅ draft tạo: id={ref.message_id}\n   web={ref.web_link}")


if __name__ == "__main__":
    main()
