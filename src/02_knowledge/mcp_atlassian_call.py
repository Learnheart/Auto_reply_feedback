"""Gọi Atlassian MCP server (Jira/Confluence) trên Databricks Apps.

Module: ingest-sync (Job A) — nửa ĐỌC backlog (spike).
Architecture: docs/architecture.md §3 Trách nhiệm từng module (ingest-sync: backlog -> backlog_ref),
  §2 Input (Jira backlog), §4.5 Data layer (backlog_ref), §5 Technology Stack (Jira).
Plan: docs/2026-08-26/jira-backlog-fetch/plan.md
LƯU Ý lệch kiến trúc: §5 quy định production ingest-sync dùng Jira REST + service principal;
  spike này dùng MCP-Atlassian + U2M SSO token để kiểm chứng dữ liệu. Đọc-thử, KHÔNG ghi backlog_ref.

Tái hiện flow của tai-studio (infra/discovery/tools.py): JSON-RPC 2.0 qua HTTP,
initialize -> tools/list -> tools/call. Khác biệt duy nhất: thay vì service-principal
token, script này dùng token U2M lấy từ profile SSO của bạn:

    databricks auth login --profile tcb-agent-sit

Cách dùng:
    python mcp_atlassian_call.py list                       # liệt kê tool server cung cấp
    python mcp_atlassian_call.py describe <tool_name>       # xem inputSchema của 1 tool
    python mcp_atlassian_call.py call <tool_name> '<json>'  # gọi tool
    python mcp_atlassian_call.py backlog                    # lấy TOÀN BỘ backlog tai-studio (TSFAI)
    python mcp_atlassian_call.py backlog "Tai Studio"       # đổi filter theo summary
    python mcp_atlassian_call.py userguide                  # lấy cây userguide Confluence (root 395774795)
    python mcp_atlassian_call.py userguide <PAGE_ID>        # đổi page gốc
    # ví dụ call:
    python mcp_atlassian_call.py call search_issues '{"jql":"project = TSFAI ORDER BY created DESC","limit":20}'

Cần: pip install httpx databricks-sdk truststore   (yêu cầu Python >= 3.10 do truststore)
"""

from __future__ import annotations

import json
import ssl
import sys

import httpx
import truststore
from databricks.sdk import WorkspaceClient

# Mạng công ty chặn SSL bằng CA nội bộ; truststore đọc CA đã cài trong OS keychain
# nên không bị CERTIFICATE_VERIFY_FAILED như certifi mặc định.
SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

# ── Config ──────────────────────────────────────────────────────────────────
PROFILE = "tcb-agent-sit"
WORKSPACE_ID = "7474658044456999"  # sit.properties: DATABRICKS_WORKSPACE_ID
MCP_URL = f"https://mcp-atlassian-{WORKSPACE_ID}.aws.databricksapps.com/mcp"


# ── Auth ────────────────────────────────────────────────────────────────────
def get_token() -> str:
    """Bearer token của user từ profile SSO (U2M OAuth)."""
    # WorkspaceClient đọc profile trong ~/.databrickscfg; nếu token OAuth hết hạn
    # nó tự refresh qua flow đã login bằng `databricks auth login`.
    cfg = WorkspaceClient(profile=PROFILE).config
    return cfg.authenticate().get("Authorization", "").replace("Bearer ", "")


def build_headers(token: str, user_email: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        # Ta chính là user (U2M), nên forward chính token này để mcp-atlassian
        # dùng làm identity gọi sang Atlassian.
        "X-Forwarded-Access-Token": token,
        "X-Original-Forwarded-Access-Token": token,
    }
    if user_email:
        headers["X-Forwarded-Email"] = user_email
        headers["X-User-Email"] = user_email
    return headers


# ── MCP JSON-RPC ────────────────────────────────────────────────────────────
def parse_sse(text: str) -> dict:
    """Response có thể là SSE (data: {...}) hoặc JSON thuần."""
    for line in text.strip().split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(text)


def mcp_init(client: httpx.Client, headers: dict) -> str | None:
    resp = client.post(
        MCP_URL,
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcp-test", "version": "1.0"},
            },
        },
    )
    resp.raise_for_status()
    return resp.headers.get("mcp-session-id")


def rpc(method: str, params: dict) -> dict:
    """initialize -> gắn session-id -> gọi method."""
    token = get_token()
    headers = build_headers(token)
    with httpx.Client(timeout=60, verify=SSL_CTX) as client:
        if sid := mcp_init(client, headers):
            headers["Mcp-Session-Id"] = sid
        resp = client.post(
            MCP_URL,
            headers=headers,
            json={"jsonrpc": "2.0", "id": "2", "method": method, "params": params},
        )
        if resp.status_code in (401, 403):
            print(f"[AUTH {resp.status_code}] {resp.text[:500]}", file=sys.stderr)
            resp.raise_for_status()
        return parse_sse(resp.text)


# ── Commands ────────────────────────────────────────────────────────────────
def cmd_list() -> None:
    result = rpc("tools/list", {})
    tools = result.get("result", {}).get("tools", [])
    if not tools:
        print("Không có tool nào (hoặc bị chặn auth). Raw:", json.dumps(result, indent=2))
        return
    print(f"{len(tools)} tools:\n")
    for t in tools:
        ann = t.get("annotations") or {}
        flags = []
        if ann.get("readOnlyHint"):
            flags.append("read-only")
        if ann.get("destructiveHint"):
            flags.append("DESTRUCTIVE")
        tag = f"  [{', '.join(flags)}]" if flags else ""
        print(f"• {t['name']}{tag}")
        if desc := t.get("description"):
            print(f"    {desc.strip().splitlines()[0][:120]}")


def cmd_describe(name: str) -> None:
    result = rpc("tools/list", {})
    tools = result.get("result", {}).get("tools", [])
    for t in tools:
        if t["name"] == name:
            print(json.dumps(t, indent=2, ensure_ascii=False))
            return
    print(f"Không tìm thấy tool '{name}'. Chạy `list` để xem tên hợp lệ.")


def cmd_call(name: str, args_json: str) -> None:
    args = json.loads(args_json) if args_json else {}
    result = rpc("tools/call", {"name": name, "arguments": args})
    if "error" in result:
        print("MCP error:", json.dumps(result["error"], indent=2, ensure_ascii=False))
        return
    content = result.get("result", {}).get("content", [])
    text = "\n".join(c.get("text", "") for c in content)
    print(text if text else json.dumps(result, indent=2, ensure_ascii=False))


def _plain_text(desc) -> str:
    """Jira description có thể là str (markdown) hoặc ADF dict {type:doc,content:[...]}.

    Rút text phẳng: nếu là dict thì đệ quy gom mọi node `text`; nếu str thì trả nguyên.
    """
    if not desc:
        return ""
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        # một số response bọc {"value": <adf|str>}
        if "value" in desc and len(desc) == 1:
            return _plain_text(desc["value"])
        parts: list[str] = []
        if desc.get("type") == "text" and isinstance(desc.get("text"), str):
            parts.append(desc["text"])
        if desc.get("type") == "hardBreak":
            parts.append("\n")
        for child in desc.get("content", []) or []:
            parts.append(_plain_text(child))
        # block-level -> xuống dòng để đoạn không dính vào nhau
        if desc.get("type") in ("paragraph", "heading", "listItem", "blockquote", "codeBlock"):
            parts.append("\n")
        return "".join(parts)
    return str(desc)


# ── Backlog tai-studio ──────────────────────────────────────────────────────
# "tai-studio" KHÔNG phải project key: công việc nằm trong project TSFAI
# (TS-AI FOUNDATIONS), issue gắn tiền tố "[Tai Studio]" ở summary.
BACKLOG_PROJECT = "TSFAI"
BACKLOG_NAME_FILTER = "Tai Studio"  # khớp summary ~ "..."


def fetch_backlog(
    name_filter: str = BACKLOG_NAME_FILTER,
    project: str = BACKLOG_PROJECT,
    include_done: bool = False,
    only_backlog_sprint: bool = True,
    exclude_types: tuple[str, ...] = ("Test",),
    page_size: int = 50,
    max_pages: int = 80,
) -> list[dict]:
    """Lấy TOÀN BỘ issue backlog tai-studio, tự phân trang.

    Không dựa vào `total` (server MCP luôn trả -1) — dừng khi trang trả về < page_size.
    `max_pages` là trần an toàn chống lặp vô hạn (80 * 50 = 4000 issue).

    `name_filter` khớp qua JQL `summary ~` (text-index, khớp cả "[Tai Studio]" lẫn
    "[TAI Studio]"). `exclude_types` loại issuetype không phải backlog sản phẩm — mặc định
    bỏ "Test" (dự án này auto-sinh HÀNG NGHÌN test-case `[Tai Studio]`); truyền `()` để lấy cả.
    Trả list dict phẳng: jira_key, summary, status, issuetype, priority.
    """
    clauses = [f"project = {project}"]
    if name_filter:
        clauses.append(f'summary ~ "{name_filter}"')
    if not include_done:
        clauses.append("statusCategory != Done")
    if only_backlog_sprint:
        clauses.append("sprint is EMPTY")
    for t in exclude_types:
        clauses.append(f"issuetype != {t}")
    jql = " AND ".join(clauses) + " ORDER BY created DESC"

    page_size = max(1, min(page_size, 50))  # server giới hạn 1..50
    out: list[dict] = []
    for page in range(max_pages):
        result = rpc(
            "tools/call",
            {
                "name": "search_issues",
                "arguments": {
                    "jql": jql,
                    "limit": page_size,
                    "start_at": page * page_size,
                    "fields": "summary,status,issuetype,priority,description",
                },
            },
        )
        if "error" in result:
            print("MCP error:", json.dumps(result["error"], indent=2, ensure_ascii=False), file=sys.stderr)
            break
        # tools/call bọc payload dưới structuredContent (envelope FastMCP) hoặc content[].text.
        data = _unwrap_search(result)
        issues = data.get("issues", [])
        for it in issues:
            # response dùng snake_case `issue_type`; chừa cả `issuetype` cho chắc.
            itype = it.get("issue_type") or it.get("issuetype") or {}
            out.append(
                {
                    "jira_key": it.get("key"),
                    "summary": it.get("summary", ""),
                    "status": (it.get("status") or {}).get("name"),
                    "issuetype": itype.get("name"),
                    "priority": (it.get("priority") or {}).get("name"),
                    "description": _plain_text(it.get("description")),
                }
            )
        if len(issues) < page_size:  # trang ngắn => hết dữ liệu (total không đáng tin)
            break
    else:
        print(f"[cảnh báo] chạm trần {max_pages} trang; có thể còn issue chưa lấy.", file=sys.stderr)
    return out


def _unwrap_search(result: dict) -> dict:
    """Rút payload issues từ response tools/call.

    FastMCP bọc kết quả (x-fastmcp-wrap-result): payload {total,issues,...} nằm ở
    content[].text dạng chuỗi JSON. structuredContent.result cũng là CHUỖI JSON (không
    phải dict) do outputSchema khai result:string — nên phải json.loads, đừng lấy thẳng.
    """
    res = result.get("result", {})
    for c in res.get("content", []):
        text = c.get("text")
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
    sc = res.get("structuredContent")
    if isinstance(sc, dict):
        inner = sc.get("result", sc)
        if isinstance(inner, str):
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                return {}
        if isinstance(inner, dict):
            return inner
    return {}


def cmd_backlog(name_filter: str = BACKLOG_NAME_FILTER) -> None:
    items = fetch_backlog(name_filter=name_filter)
    if not items:
        print(f"Không lấy được issue nào (filter summary ~ '{name_filter}', project {BACKLOG_PROJECT}).")
        print("Nhắc: JQL sai bị nuốt lỗi -> rỗng. Kiểm tra lại tên filter/quyền truy cập.")
        return
    print(f"{len(items)} issue backlog (project {BACKLOG_PROJECT}, summary ~ '{name_filter}'):\n")
    for it in items:
        pri = f"  ({it['priority']})" if it.get("priority") else ""
        print(f"• {it['jira_key']}  [{it['status']}]  {it['issuetype'] or ''}{pri}")
        print(f"    {it['summary'][:100]}")


# ── Confluence userguide TÀI Studio ─────────────────────────────────────────
# Root page "TÀI Studio — User guide" (space DataEngineering); mỗi agent 1 page con.
USERGUIDE_ROOT = "395774795"


def _page_markdown(page_id: str) -> dict:
    """get_page -> {page_id, title, space_key, version, markdown}.

    Response bọc nội dung ở metadata.content.value (markdown khi convert_to_markdown=True).
    """
    data = _unwrap_search(
        rpc("tools/call", {"name": "get_page", "arguments": {
            "page_id": page_id, "convert_to_markdown": True}})
    )
    meta = data.get("metadata", data)  # get_page bọc dưới 'metadata'
    return {
        "page_id": meta.get("id", page_id),
        "title": meta.get("title", ""),
        "space_key": (meta.get("space") or {}).get("key"),
        "version": meta.get("version"),
        "markdown": ((meta.get("content") or {}).get("value")) or "",
    }


def _iter_children(parent_id: str, page_size: int, max_pages: int) -> list[dict]:
    """Liệt kê con trực tiếp của 1 page, tự phân trang (dừng khi trang < page_size)."""
    kids: list[dict] = []
    for page in range(max_pages):
        data = _unwrap_search(
            rpc("tools/call", {"name": "get_page_children", "arguments": {
                "parent_id": parent_id, "limit": page_size,
                "start": page * page_size, "include_content": False}})
        )
        results = data.get("results", [])
        kids.extend(results)
        if len(results) < page_size:
            break
    return kids


def fetch_userguide(
    root_page_id: str = USERGUIDE_ROOT,
    max_depth: int = 5,
    page_size: int = 50,
    max_pages: int = 40,
) -> list[dict]:
    """Lấy TOÀN BỘ page trong cây userguide (gồm root), kèm nội dung markdown.

    Duyệt đệ quy con qua get_page_children (có `visited` chống lặp, `max_depth` chặn sâu),
    lấy nội dung từng page qua get_page. Trả list dict: page_id, title, space_key, version, markdown.
    """
    page_size = max(1, min(page_size, 50))  # server giới hạn 1..50
    out: list[dict] = []
    visited: set[str] = set()

    def walk(pid: str, depth: int) -> None:
        if pid in visited or depth > max_depth:
            return
        visited.add(pid)
        out.append(_page_markdown(pid))
        for child in _iter_children(pid, page_size, max_pages):
            cid = child.get("id")
            if cid:
                walk(str(cid), depth + 1)

    walk(str(root_page_id), 0)
    return out


def cmd_userguide(root_page_id: str = USERGUIDE_ROOT) -> None:
    pages = fetch_userguide(root_page_id)
    if not pages:
        print(f"Không lấy được page nào từ root {root_page_id} (kiểm tra id/space/quyền).")
        return
    total_chars = sum(len(p["markdown"]) for p in pages)
    print(f"{len(pages)} page trong cây userguide (root {root_page_id}), tổng {total_chars} ký tự:\n")
    for p in pages:
        print(f"• {p['page_id']}  v{p['version']}  [{p['space_key']}]  {p['title']}")
        print(f"    markdown: {len(p['markdown'])} ký tự")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "list":
        cmd_list()
    elif args[0] == "describe" and len(args) >= 2:
        cmd_describe(args[1])
    elif args[0] == "call" and len(args) >= 2:
        cmd_call(args[1], args[2] if len(args) >= 3 else "")
    elif args[0] == "backlog":
        cmd_backlog(args[1] if len(args) >= 2 else BACKLOG_NAME_FILTER)
    elif args[0] == "userguide":
        cmd_userguide(args[1] if len(args) >= 2 else USERGUIDE_ROOT)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
