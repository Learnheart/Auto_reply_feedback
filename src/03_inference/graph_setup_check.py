"""Kiểm tra setup Microsoft Graph (delegated device-code) — ĐỘC LẬP, không cần LM Studio/classify.

Module: inference.deliver (B3) — tiện ích setup/verify auth.
Architecture: docs/architecture.md §5 (Microsoft Graph delivery). Impl: deliver.py §SETUP-DELEGATED.

Dùng để xác nhận AUTH + quyền ghi Outlook TRƯỚC khi chạy pipeline thật. Reuse GraphDelegatedAuth +
GraphClient + build_message (đúng đường mà GraphSink dùng).

Chuẩn bị env (xem §SETUP-DELEGATED trong deliver.py):
    export AZ_CLIENT_ID=...            # bắt buộc — client id của app public đã đăng ký
    export AZ_TENANT_ID=...            # tuỳ chọn, mặc định 'organizations'
    export SHARED_MAILBOX=me           # 'me' = Drafts của chính bạn; hoặc UPN shared mailbox có quyền

Chạy (dùng interpreter có đủ deps — ở máy này là /opt/miniconda3/bin/python):
    python graph_setup_check.py                 # login + đọc identity + liệt kê mailFolders
    python graph_setup_check.py --test-draft --to you@techcombank.com.vn
                                                # + tạo 1 DRAFT thật trong folder 'TAI Test' để thấy trong Outlook
"""

from __future__ import annotations

import argparse
import os

from graph_client import GraphClient, GraphDelegatedAuth, build_message


def _auth_from_env() -> tuple[GraphDelegatedAuth, str]:
    client_id = os.environ.get("AZ_CLIENT_ID")
    if not client_id:
        raise SystemExit("❌ Thiếu env AZ_CLIENT_ID. Xem §SETUP-DELEGATED trong deliver.py.")
    auth = GraphDelegatedAuth(
        client_id=client_id,
        tenant_id=os.environ.get("AZ_TENANT_ID", "organizations"),
    )
    mailbox = os.environ.get("SHARED_MAILBOX", "me")
    return auth, mailbox


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify Microsoft Graph delegated setup.")
    ap.add_argument("--test-draft", action="store_true", help="tạo 1 draft thật trong folder 'TAI Test'")
    ap.add_argument("--to", default="", help="địa chỉ To cho draft test (mặc định = chính mình)")
    args = ap.parse_args()

    auth, mailbox = _auth_from_env()
    print(f"→ mailbox đích: {mailbox}  ·  tenant: {auth.tenant_id}")
    print("→ Lấy token (lần đầu sẽ hiện link + mã để đăng nhập)...")
    client = GraphClient(auth, mailbox)

    # 1) identity — xác nhận login đúng tài khoản
    me = client._req("GET", "/me")
    if me.status_code >= 400:
        raise SystemExit(f"❌ GET /me lỗi {me.status_code}: {me.text[:300]}")
    who = me.json()
    upn = who.get("userPrincipalName") or who.get("mail") or "?"
    print(f"✅ Đăng nhập: {who.get('displayName','?')} <{upn}>")

    # 2) quyền đọc mailbox đích — liệt kê vài folder
    fr = client._req("GET", f"{client._root}/mailFolders?$top=10&$select=displayName")
    if fr.status_code >= 400:
        raise SystemExit(
            f"❌ Đọc mailFolders của «{mailbox}» lỗi {fr.status_code}: {fr.text[:300]}\n"
            "   (nếu 403 với shared mailbox: tài khoản chưa có quyền — thử SHARED_MAILBOX=me trước.)"
        )
    names = [f.get("displayName") for f in fr.json().get("value", [])]
    print(f"✅ Đọc được mailbox «{mailbox}». Vài folder: {names[:8]}")

    if not args.test_draft:
        print("\nOK. Auth + đọc mailbox hoạt động. Thêm --test-draft để thử TẠO draft.")
        return

    # 3) ghi — tạo folder 'TAI Test' + 1 draft, xác nhận quyền Mail.ReadWrite end-to-end
    folder_id = client.ensure_folder("TAI Test")
    to_email = args.to or upn
    msg = build_message(
        subject="[TÀI Studio] Graph setup check",
        html_body="<p>Draft test từ graph_setup_check.py — có thể xoá.</p>",
        to_email=to_email,
        feedback_id="setup_check_0000",
        cc=None,
    )
    created = client.create_draft(folder_id, msg)
    print(f"✅ Tạo DRAFT thành công trong folder «TAI Test».")
    print(f"   id={created.get('id')}")
    print(f"   webLink={created.get('webLink')}")
    print("   → Mở Outlook, vào folder 'TAI Test' để thấy draft (xoá sau khi kiểm).")


if __name__ == "__main__":
    main()
