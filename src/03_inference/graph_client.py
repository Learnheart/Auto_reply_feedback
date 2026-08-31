"""Microsoft Graph client (app-only) cho B3 deliver — token + REST tối thiểu.

Module: inference.deliver (B3) — nửa TRANSPORT.
Architecture: docs/architecture.md §5 (Microsoft Graph `msal`+`httpx`, Azure AD service principal),
  §4.2 Flow B3 (ensure mailFolder → POST draft), §6.1 R5 (X-Feedback-Id khóa cứng).
Impl: docs/impl-phase2-auto-feedback-flow.md §6 (GraphSink).
Plan: docs/2026-08-26/deliver-outlook-graph/plan.md (R2, D1, D5).

HAI cơ chế auth (cùng interface `.token() -> str`, cùng dùng chung `GraphClient`/`GraphSink`):

- `GraphAuth` — **app-only** (client-credentials): job chạy không người ngồi sau ⇒ service principal.
  CẢNH BÁO: app-only `Mail.ReadWrite` có quyền MỌI mailbox trong tenant. BẮT BUỘC gắn
  **Application Access Policy** giới hạn app chỉ vào shared mailbox `taistudio@` (xem §Setup deliver.py).

- `GraphDelegatedAuth` — **delegated device-code**: admin login MỘT LẦN (mở link + nhập mã), token +
  refresh cache ra đĩa ⇒ các lần sau tự lấy silent, KHÔNG login lại. Nhẹ hơn app-only (public client,
  delegated `Mail.ReadWrite` + `offline_access`, thường không cần admin consent, không cần Access Policy).
  Draft ghi vào Drafts của chính tài khoản đó (`mailbox="me"`) hoặc shared mailbox mà họ có quyền.

Cần: pip install msal   (httpx đã có). msal import LAZY để module vẫn import được khi chưa cài.
"""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass, field
from pathlib import Path

import httpx

try:  # mạng công ty MITM TLS bằng CA nội bộ — dùng truststore nếu có (như các spike khác)
    import truststore

    _SSL_CTX: ssl.SSLContext | bool = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:  # noqa: BLE001
    _SSL_CTX = True

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

# X-Feedback-Id: named MAPI property (PS_PUBLIC_STRINGS) — khóa cứng cho outcome-sync (R5).
# LƯU Ý spike ① (impl B-2): PHẢI kiểm property này sống sót qua bước Send TRƯỚC khi tin outcome-sync.
FEEDBACK_ID_PROP = "String {00020329-0000-0000-C000-000000000046} Name X-Feedback-Id"


@dataclass
class GraphAuth:
    tenant_id: str
    client_id: str
    client_secret: str

    def token(self) -> str:
        """Bearer app-only qua msal client-credentials. Lazy import để chưa cài msal vẫn import module."""
        try:
            import msal
        except ModuleNotFoundError as e:  # pragma: no cover
            raise RuntimeError("Thiếu msal — chạy: pip install msal") from e

        app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise RuntimeError(
                f"Lấy token thất bại: {result.get('error')} — {result.get('error_description', '')[:300]}"
            )
        return result["access_token"]


# scope delegated: resource scope (KHÁC app-only `.default`). msal tự thêm offline_access/openid/profile.
DELEGATED_SCOPES = ["Mail.ReadWrite"]
DEFAULT_CACHE_PATH = Path(
    os.environ.get("GRAPH_TOKEN_CACHE", str(Path.home() / ".tai_graph_token_cache.json"))
)


@dataclass
class GraphDelegatedAuth:
    """Delegated device-code: login 1 lần → cache refresh token ra đĩa → lần sau lấy silent.

    Public client (KHÔNG secret). `tenant_id='organizations'` cho tài khoản công ty (single/multi-tenant
    org). Cache chứa refresh token ⇒ file nhạy cảm, mặc định ~/.tai_graph_token_cache.json (đổi qua env
    GRAPH_TOKEN_CACHE). Lần đầu: hàm IN link+mã rồi CHẶN tới khi admin hoàn tất trên trình duyệt.
    """

    client_id: str
    tenant_id: str = "organizations"
    cache_path: Path = field(default_factory=lambda: DEFAULT_CACHE_PATH)
    scopes: list[str] = field(default_factory=lambda: list(DELEGATED_SCOPES))

    def token(self) -> str:
        try:
            import msal
        except ModuleNotFoundError as e:  # pragma: no cover
            raise RuntimeError("Thiếu msal — chạy: pip install msal") from e

        # Mạng công ty MITM TLS: msal dùng requests ⇒ patch stdlib ssl để tin CA hệ thống (nếu có truststore).
        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:  # noqa: BLE001
            pass

        cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            cache.deserialize(self.cache_path.read_text(encoding="utf-8"))

        app = msal.PublicClientApplication(
            client_id=self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=cache,
        )

        result = None
        accounts = app.get_accounts()
        if accounts:  # có phiên cũ ⇒ thử refresh silent, KHÔNG bắt login lại
            result = app.acquire_token_silent(self.scopes, account=accounts[0])

        if not result:  # lần đầu / refresh hết hạn ⇒ device-code flow (chặn tới khi admin hoàn tất)
            flow = app.initiate_device_flow(scopes=self.scopes)
            if "user_code" not in flow:
                raise RuntimeError(f"Không khởi tạo được device flow: {flow.get('error_description', flow)}")
            print("\n" + "=" * 70)
            print(flow["message"])   # vd: mở https://microsoft.com/devicelogin rồi nhập mã ABCD-EFGH
            print("=" * 70 + "\n")
            result = app.acquire_token_by_device_flow(flow)

        if "access_token" not in result:
            raise RuntimeError(
                f"Lấy token delegated thất bại: {result.get('error')} — "
                f"{result.get('error_description', '')[:300]}"
            )

        if cache.has_state_changed:  # lưu refresh token cho lần chạy sau
            self.cache_path.write_text(cache.serialize(), encoding="utf-8")
            try:
                os.chmod(self.cache_path, 0o600)   # chứa refresh token ⇒ chỉ chủ sở hữu đọc
            except OSError:
                pass
        return result["access_token"]


class GraphClient:
    """Wrapper mỏng quanh Graph REST cho đúng 3 thao tác B3 cần trên 1 shared mailbox."""

    def __init__(self, auth: "GraphAuth | GraphDelegatedAuth", mailbox: str, timeout: float = 30.0):
        self.auth = auth
        self.mailbox = mailbox                    # UPN shared mailbox, hoặc "me" (Drafts tài khoản delegated)
        # delegated ghi vào chính mình ⇒ /me; app-only / shared mailbox ⇒ /users/{UPN}
        self._root = "/me" if mailbox in (None, "", "me") else f"/users/{mailbox}"
        self._token: str | None = None
        self._client = httpx.Client(base_url=GRAPH_BASE, timeout=timeout, verify=_SSL_CTX)

    # -- auth ---------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        if self._token is None:
            self._token = self.auth.token()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _req(self, method: str, path: str, json: dict | None = None) -> httpx.Response:
        resp = self._client.request(method, path, headers=self._headers(), json=json)
        if resp.status_code == 401:                # token hết hạn → làm mới một lần
            self._token = None
            resp = self._client.request(method, path, headers=self._headers(), json=json)
        return resp

    # -- mailFolder ---------------------------------------------------------
    def find_folder(self, display_name: str) -> str | None:
        """Tìm mailFolder con của mailbox theo displayName (idempotency §R3). None nếu chưa có."""
        # $filter theo displayName; phân trang bỏ qua vì mailbox này ít folder.
        path = f"{self._root}/mailFolders?$top=100&$select=id,displayName"
        resp = self._req("GET", path)
        resp.raise_for_status()
        for f in resp.json().get("value", []):
            if f.get("displayName") == display_name:
                return f["id"]
        return None

    def ensure_folder(self, display_name: str) -> str:
        """Trả folder_id, tạo nếu chưa có. Idempotent theo displayName."""
        existing = self.find_folder(display_name)
        if existing:
            return existing
        resp = self._req(
            "POST", f"{self._root}/mailFolders", {"displayName": display_name}
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Tạo folder '{display_name}' lỗi HTTP {resp.status_code}: {resp.text[:400]}")
        return resp.json()["id"]

    # -- draft --------------------------------------------------------------
    def create_draft(self, folder_id: str, message: dict) -> dict:
        """POST message vào folder → tạo DRAFT (chưa gửi). Trả {id, webLink}."""
        resp = self._req(
            "POST", f"{self._root}/mailFolders/{folder_id}/messages", message
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Tạo draft lỗi HTTP {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    def close(self) -> None:
        self._client.close()


def build_message(
    *,
    subject: str,
    html_body: str,
    to_email: str,
    feedback_id: str,
    cc: list[str] | None = None,
    inline_logo_b64: str | None = None,
) -> dict:
    """Dựng JSON message cho Graph create_draft — schema THUẦN, test được offline (R7).

    - `singleValueExtendedProperties` nhúng X-Feedback-Id (khóa cứng outcome-sync, R5).
    - logo inline `cid:tai_logo` chỉ thêm khi có `inline_logo_b64` (B-1: asset còn thiếu ⇒ bỏ qua, không crash).
    """
    msg: dict = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_body},
        "toRecipients": [{"emailAddress": {"address": to_email}}],
        "singleValueExtendedProperties": [{"id": FEEDBACK_ID_PROP, "value": feedback_id}],
    }
    if cc:
        msg["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc]
    if inline_logo_b64:
        msg["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "icon_TAI.png",
                "contentType": "image/png",
                "isInline": True,
                "contentId": "tai_logo",
                "contentBytes": inline_logo_b64,
            }
        ]
    return msg
