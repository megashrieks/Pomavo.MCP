"""MCP Server for Pomavo ticket management."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent, ImageContent

from .client import PomavoClient, normalize_markdown, prepare_rich_text

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the MCP server
server = Server("pomavo-mcp")

# ---------------------------------------------------------------------------
# Skills: deep reference material extracted out of individual tool descriptions
# so the tool descriptions stay short. Each skill is a SKILL.md file under
# Pomavo.MCP/skills/<name>/. Tools point at a skill by name; the load_skill tool
# returns the skill body on demand (progressive disclosure). Keep AVAILABLE_SKILLS
# in sync with the folders under skills/.
# ---------------------------------------------------------------------------
SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# Candidate locations for the skills folder, tried in order. This tolerates both
# editable installs (skills at <repo>/Pomavo.MCP/skills, i.e. parents[2]) and layouts
# where the folder is shipped alongside or inside the package, plus an env override.
_SKILL_DIR_CANDIDATES = [
    Path(p)
    for p in [
        os.environ.get("POMAVO_MCP_SKILLS_DIR", ""),
        str(SKILLS_DIR),
        str(Path(__file__).resolve().parent / "skills"),
    ]
    if p
]

AVAILABLE_SKILLS: dict[str, str] = {
    "pomavo-query-language": (
        "Read/filter search DSL used by search_tickets, the execute_query [filter] "
        "prefix, and report chart/variable queries."
    ),
    "pomavo-mutation-dsl": (
        "Bulk mutation DSL (SET / CREATE / LINK / UNLINK / COMMENT) run by execute_query."
    ),
    "pomavo-report-layout": (
        "Screen language (layout tags, chart components, x/y/series/color contract, "
        "<Variable>) for create_report."
    ),
    "pomavo-screen-layout": (
        "Layout language for ticket TEMPLATE SCREENS (Field/Label/Plugin/Row/Column/"
        "Section/Collapsible/Color/Font/Trigger/Text) — the create form, detail view, "
        "preview pane, board card, and sidebar sections."
    ),
    "pomavo-automation": (
        "Building automation rules incrementally: the node catalog, the type system + "
        "assignability, the alias workflow, 'alias.handle' edges, dynamic outputs, and the "
        "trigger/validation rules used by the automation authoring tools."
    ),
}


def _read_skill_body(name: str) -> str | None:
    """Return the full SKILL.md text for a known skill, or None if unknown/missing."""
    if name not in AVAILABLE_SKILLS:
        return None
    for base in _SKILL_DIR_CANDIDATES:
        path = base / name / "SKILL.md"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    logger.warning("Skill file for %s not found in %s", name, _SKILL_DIR_CANDIDATES)
    return None


def _get_request_headers() -> dict[str, str]:
    """Return the current request's headers (lower-cased) if available.

    For HTTP/SSE transports the low-level Server exposes the originating
    Starlette request via ``request_context.request``. Returns an empty
    mapping when no request context is active.
    """
    try:
        ctx = server.request_context
    except LookupError:
        return {}
    request = getattr(ctx, "request", None)
    if request is None:
        return {}
    return {k.lower(): v for k, v in request.headers.items()}


def get_client() -> PomavoClient:
    """Build a per-request Pomavo API client from the incoming request headers.

    Everything the client needs is taken from the HTTP request so a single
    hosted server can serve any tenant/environment without redeploying:
      - ``X-API-Key`` (or ``Authorization: Bearer <key>``)
      - ``X-Org-Short-Name`` -- tenant

    The Pomavo API base URL and effective Host header are resolved server-side
    from deployment config (``POMAVO_API_URL`` and ``POMAVO_PUBLIC_HOST``) so a
    caller cannot point the built-in server at an arbitrary host; the effective
    Host is computed as ``<org-short-name>.<public-host>``. A caller-supplied
    ``X-Pomavo-Api-Url`` / ``X-Pomavo-Host`` is only honoured when the
    corresponding env is unset (legacy / non-containerised deployments).
    Only the SSL policy comes from server-side config (``POMAVO_VERIFY_SSL``),
    since it is an operational property of the deployment, not the caller.
    """
    headers = _get_request_headers()
    api_key = headers.get("x-api-key")
    if not api_key:
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            api_key = auth[7:].strip()
    org = headers.get("x-org-short-name")

    # API URL is server-controlled: the injected env wins, and only when it is
    # absent do we honour a caller-supplied header (legacy / non-containerised).
    api_url = os.environ.get("POMAVO_API_URL") or headers.get("x-pomavo-api-url")

    # Effective Host is computed from the org short name + public domain when the
    # public host is configured, so a caller cannot target an arbitrary vhost;
    # otherwise fall back to any caller-supplied host override.
    public_host = os.environ.get("POMAVO_PUBLIC_HOST", "").strip()
    if public_host and org:
        host_header = f"{org}.{public_host}"
    else:
        host_header = headers.get("x-pomavo-host")

    verify_ssl = os.environ.get("POMAVO_VERIFY_SSL", "true").lower() != "false"
    return PomavoClient(
        api_url=api_url or None,
        api_key=api_key or None,
        org_short_name=org or None,
        verify_ssl=verify_ssl,
        host_header=host_header or None,
    )


def _extract_plain_text(value: str) -> str:
    """Extract plain text from a TipTap JSON string.
    
    If the value looks like TipTap JSON ({"type":"doc",...}), recursively
    extracts text nodes. Otherwise returns the value as-is.
    """
    stripped = value.strip()
    if not (stripped.startswith('{"type":"doc"') or stripped.startswith('{"type": "doc"')):
        return value
    try:
        import json
        doc = json.loads(stripped)
        return _extract_text_from_node(doc).strip()
    except (json.JSONDecodeError, KeyError, TypeError):
        return value


def _extract_text_from_node(node: dict) -> str:
    """Recursively extract text from a TipTap JSON node."""
    if not isinstance(node, dict):
        return ""
    if "text" in node:
        return node["text"]
    content = node.get("content")
    if not isinstance(content, list):
        return ""
    parts = [_extract_text_from_node(child) for child in content if isinstance(child, dict)]
    block_types = {"paragraph", "heading", "bulletList", "orderedList", "listItem", "blockquote", "codeBlock", "tableRow"}
    if node.get("type") in block_types:
        return "".join(parts) + " "
    return "".join(parts)


def _parse_lock_config(config: Any) -> dict[str, Any]:
    """Locks store config as a JSON-encoded string. Return it as a dict (or {})."""
    if isinstance(config, dict):
        return config
    if isinstance(config, str) and config.strip():
        try:
            parsed = json.loads(config)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _build_view_lock_index(locks: list[dict] | None) -> tuple[dict[str, str], list[str]]:
    """Build a (template_field_id -> reason) map for active field.view locks.

    Returns (per_field_reasons, all_field_reasons). A `*` (or missing) fieldId in
    config means the lock hides every field on the ticket.
    """
    per_field: dict[str, str] = {}
    all_fields: list[str] = []
    if not locks:
        return per_field, all_fields
    for lock in locks:
        if not isinstance(lock, dict):
            continue
        if lock.get("deletedAt") or lock.get("DeletedAt"):
            continue
        lock_type = lock.get("lockType") or lock.get("LockType")
        if lock_type != "field.view":
            continue
        reason = lock.get("reason") or lock.get("Reason") or "field is hidden"
        cfg = _parse_lock_config(lock.get("config") or lock.get("Config"))
        field_id = cfg.get("fieldId")
        if not field_id or field_id == "*":
            all_fields.append(reason)
        else:
            per_field.setdefault(field_id, reason)
    return per_field, all_fields


def format_ticket(ticket: Any, field_map: dict[str, str] | None = None, template_name: str | None = None) -> str:
    """Format a ticket for display.
    
    Args:
        ticket: The ticket object
        field_map: Optional mapping of template_field_id -> field label
        template_name: Optional template name (fetched separately)
    """
    display_template = template_name or (ticket.template.name if ticket.template else 'Unknown Template')
    lines = [
        f"**{ticket.sequence_number}** - {display_template}",
        f"Status: {ticket.workflow_state.name if ticket.workflow_state else 'Unknown'}",
        "",
    ]

    # Pull lock metadata off the ticket (Pydantic with extra='allow' keeps unknown fields).
    raw_locks: list[dict] = []
    locks_attr = getattr(ticket, "locks", None) or getattr(ticket, "Locks", None)
    if isinstance(locks_attr, list):
        raw_locks = [l for l in locks_attr if isinstance(l, dict)]
    else:
        # Pydantic may have stashed it in __pydantic_extra__ under the alias.
        extra = getattr(ticket, "model_extra", None) or {}
        for key in ("locks", "Locks"):
            if key in extra and isinstance(extra[key], list):
                raw_locks = [l for l in extra[key] if isinstance(l, dict)]
                break

    view_locked, all_view_locks = _build_view_lock_index(raw_locks)

    # Add fields - parse rich text JSON to plain text for readability
    for field in ticket.fields:
        # Try to get label from: 1) field_map, 2) template_field, 3) fallback to ID
        if field_map and field.template_field_id in field_map:
            label = field_map[field.template_field_id]
        elif field.template_field:
            label = field.template_field.label
        else:
            label = field.template_field_id

        value = _extract_plain_text(field.value) if field.value else ""

        # If the value is empty AND this field (or all fields) is view-locked, annotate it.
        if not value:
            if field.template_field_id in view_locked:
                value = f"<locked: {view_locked[field.template_field_id]}>"
            elif all_view_locks:
                value = f"<locked: {all_view_locks[0]}>"

        lines.append(f"- **{label}**: {value}")

    # Append a Locks section so callers can see why edits or views are blocked.
    if raw_locks:
        active = [l for l in raw_locks if not (l.get("deletedAt") or l.get("DeletedAt"))]
        if active:
            lines.append("")
            lines.append("## Active Locks")
            for lock in active:
                lock_type = lock.get("lockType") or lock.get("LockType") or "?"
                reason = lock.get("reason") or lock.get("Reason") or ""
                lock_id = lock.get("id") or lock.get("Id") or "?"
                cfg = _parse_lock_config(lock.get("config") or lock.get("Config"))
                cfg_str = ""
                if cfg:
                    pieces = [f"{k}={v}" for k, v in cfg.items() if v not in (None, "")]
                    if pieces:
                        cfg_str = f" ({', '.join(pieces)})"
                lines.append(f"- **{lock_type}** [id={lock_id}]{cfg_str}: {reason}")

    return "\n".join(lines)


def format_comments(comments: list[dict], ticket_seq: str) -> str:
    """Format comments for display - full content, no truncation."""
    if not comments:
        return f"## Comments\nNo comments on {ticket_seq}"
    
    lines = ["## Comments\n"]
    for c in comments:
        author_obj = c.get("author", {})
        author = author_obj.get("name") or author_obj.get("displayName", "Unknown")
        content = _extract_plain_text(c.get("content", ""))
        comment_id = c.get("id", "?")
        created = c.get("createdAt", "")[:10] if c.get("createdAt") else ""
        lines.append(f"**{author}** (ID: {comment_id}) - {created}")
        lines.append(f"> {content}")
        lines.append("")
    
    return "\n".join(lines)


def format_links(links: list[dict], ticket_id: int, ticket_seq: str) -> str:
    """Format links for display - full content, no truncation."""
    if not links:
        return f"## Links\nNo links on {ticket_seq}"
    
    lines = ["## Links\n"]
    for link in links:
        link_id = link.get("id", "?")
        # Determine if viewing from source or target perspective
        if link.get("sourceTicketId") == ticket_id:
            # Outward link: this ticket -> target
            direction = link.get("outwardName", "links to")
            other_seq = link.get("targetSequenceNumber", "?")
            other_title = link.get("targetTitle", "")
        else:
            # Inward link: source -> this ticket
            direction = link.get("inwardName", "linked from")
            other_seq = link.get("sourceSequenceNumber", "?")
            other_title = link.get("sourceTitle", "")
        
        lines.append(f"- **{direction}** {other_seq}: {other_title} (Link ID: {link_id})")
    
    return "\n".join(lines)


def format_history(history: list[dict], ticket_seq: str, field_map: dict[str, str] | None = None, state_map: dict[str, str] | None = None) -> str:
    """Format history/audit trail for display - full content, no truncation.
    
    Args:
        history: List of history entries
        ticket_seq: Ticket sequence number for display
        field_map: Optional mapping of template_field_id -> field label
        state_map: Optional mapping of state_id -> state name
    """
    if not history:
        return f"## History\nNo history for {ticket_seq}"
    
    def resolve_field_label(field_id: str, fallback: str = "?") -> str:
        if field_map and field_id in field_map:
            return field_map[field_id]
        return fallback
    
    def resolve_state_name(state_id: str) -> str:
        if state_map and state_id in state_map:
            return state_map[state_id]
        return state_id
    
    lines = ["## History\n"]
    for entry in history:
        # API uses "historyType" as discriminator (not "changeType")
        history_type = entry.get("historyType", "Unknown")
        changed_at = entry.get("changedAt", "")[:19] if entry.get("changedAt") else ""
        author = entry.get("author", {})
        changed_by = author.get("name") or author.get("userName") or author.get("displayName", "System") if author else "System"
        
        if history_type == "Created":
            lines.append(f"- **{changed_at}** - {changed_by} created the ticket")
            # Show initial fields if present
            initial_fields = entry.get("initialFields", [])
            for field in initial_fields:
                # API uses "fieldId" (camelCase from C# FieldId)
                field_id = field.get("fieldId", field.get("templateFieldId", "?"))
                field_label = resolve_field_label(field_id, field.get("fieldLabel", field_id))
                new_value = field.get("newValue", "")
                if new_value:
                    lines.append(f"  - Set **{field_label}**: {new_value}")
        elif history_type == "StateChange":
            from_state_id = entry.get("fromStateId", "?")
            to_state_id = entry.get("toStateId", "?")
            from_state = resolve_state_name(from_state_id)
            to_state = resolve_state_name(to_state_id)
            lines.append(f"- **{changed_at}** - {changed_by} changed status: {from_state} → {to_state}")
        elif history_type == "FieldChange":
            lines.append(f"- **{changed_at}** - {changed_by} changed fields:")
            changed_fields = entry.get("changedFields", [])
            for field in changed_fields:
                # API uses "fieldId" (camelCase from C# FieldId)
                field_id = field.get("fieldId", field.get("templateFieldId", "?"))
                field_label = resolve_field_label(field_id, field.get("fieldLabel", field_id))
                old_value = field.get("oldValue", "(empty)") or "(empty)"
                new_value = field.get("newValue", "(empty)") or "(empty)"
                lines.append(f"  - **{field_label}**: {old_value} → {new_value}")
        elif history_type == "CommentAdded":
            lines.append(f"- **{changed_at}** - {changed_by} added a comment")
        elif history_type == "CommentChanged":
            lines.append(f"- **{changed_at}** - {changed_by} edited a comment")
        elif history_type == "CommentDeleted":
            lines.append(f"- **{changed_at}** - {changed_by} deleted a comment")
        elif history_type == "LinkAdded":
            link_name = entry.get("linkName", "link")
            target = entry.get("targetSequenceNumber", "?")
            lines.append(f"- **{changed_at}** - {changed_by} linked {link_name} {target}")
        elif history_type == "LinkChanged":
            lines.append(f"- **{changed_at}** - {changed_by} changed a link")
        elif history_type == "LinkRemoved":
            link_name = entry.get("linkName", "link")
            target = entry.get("targetSequenceNumber", "?")
            lines.append(f"- **{changed_at}** - {changed_by} removed link {link_name} {target}")
        elif history_type == "AttachmentCreated":
            filename = entry.get("fileName", "file")
            lines.append(f"- **{changed_at}** - {changed_by} added attachment: {filename}")
        elif history_type == "AttachmentDeleted":
            filename = entry.get("fileName", "file")
            lines.append(f"- **{changed_at}** - {changed_by} deleted attachment: {filename}")
        else:
            lines.append(f"- **{changed_at}** - {changed_by}: {history_type}")
    
    return "\n".join(lines)


def format_attachments(attachments: list[dict], ticket_seq: str) -> str:
    """Format attachments for display."""
    if not attachments:
        return f"## Attachments\nNo attachments on {ticket_seq}"
    
    lines = ["## Attachments\n"]
    for att in attachments:
        att_id = att.get("id", "?")
        filename = att.get("fileName", "Unknown")
        content_type = att.get("contentType", "")
        size_bytes = att.get("fileSizeBytes", att.get("sizeBytes", 0))
        # API returns createdByUser (AuthUser with name), not uploadedBy
        created_by_user = att.get("createdByUser", {}) or {}
        uploaded_by = created_by_user.get("name") or att.get("createdBy", "Unknown")
        uploaded_at = att.get("createdAt", "")[:10] if att.get("createdAt") else ""
        
        # Format size
        if size_bytes >= 1024 * 1024:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        elif size_bytes >= 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes} bytes"
        
        lines.append(f"- **{filename}** ({content_type}, {size_str}) - uploaded by {uploaded_by} on {uploaded_at} (ID: {att_id})")
    
    return "\n".join(lines)


def format_search_result(item: Any) -> str:
    """Format a search result item for display."""
    title = item.fields.get("Title") or item.fields.get("title") or ""
    return f"- **{item.sequence_number}** ({item.template_name}): {title} [{item.status}]"


def _format_type_ref(t: Any) -> str:
    """Format a serialized TypeReference ({typeId, typeArgs, isTypeVariable}) as text."""
    if not isinstance(t, dict):
        return str(t)
    tid = t.get("typeId", "?")
    if t.get("isTypeVariable"):
        return tid
    args = t.get("typeArgs") or []
    if args:
        return f"{tid}<{', '.join(_format_type_ref(a) for a in args)}>"
    return tid


def _format_node_types(nodes: list[dict]) -> str:
    """Concise, category-grouped listing of node types from the discovery endpoint."""
    lines = [f"# Node types ({len(nodes)})", ""]
    current_category = None
    for n in nodes:
        category = n.get("category", "")
        if category != current_category:
            lines.append(f"## {category}")
            current_category = category
        desc = n.get("description") or ""
        counts = f"in:{n.get('inputs', 0)} out:{n.get('outputs', 0)} cfg:{n.get('config', 0)}"
        lines.append(f"- `{n.get('id')}` — {n.get('label')}: {desc} ({counts})")
    return "\n".join(lines)


def _format_node_definition(d: dict) -> str:
    """Full node definition: ports, config, type params, docs."""
    lines = [f"# {d.get('label')} (`{d.get('id')}`)"]
    if d.get("category"):
        lines.append(f"Category: {d.get('category')}")
    if d.get("description"):
        lines.append(d.get("description"))
    type_params = d.get("typeParams") or []
    if type_params:
        lines.append("Type params: " + ", ".join(type_params))

    def render_ports(ports: list[dict], header: str) -> None:
        if not ports:
            return
        lines.append("")
        lines.append(header)
        for p in ports:
            mark = " (required)" if p.get("required") else ""
            multi = " (multiple)" if p.get("allowMultiple") else ""
            desc = f" — {p.get('description')}" if p.get("description") else ""
            lines.append(f"- `{p.get('id')}`: {_format_type_ref(p.get('type'))}{mark}{multi}{desc}")

    render_ports(d.get("inputs") or [], "## Inputs")
    render_ports(d.get("outputs") or [], "## Outputs")

    config = d.get("config") or []
    if config:
        lines.append("")
        lines.append("## Config fields")
        for c in config:
            opts = c.get("options") or []
            opts_str = ""
            if opts:
                labels = [o.get("label", o.get("value", "")) if isinstance(o, dict) else str(o) for o in opts]
                opts_str = " options=[" + ", ".join(labels) + "]"
            default = f" default={c.get('defaultValue')}" if c.get("defaultValue") else ""
            lines.append(f"- `{c.get('id')}` ({c.get('fieldType')}): {c.get('label')}{opts_str}{default}")

    if d.get("documentation"):
        lines.append("")
        lines.append("## Documentation")
        lines.append(d.get("documentation"))
    return "\n".join(lines)


def _format_type_definition(t: dict) -> str:
    """Full type definition: kind and properties."""
    lines = [f"# {t.get('name')} (`{t.get('id')}`)", f"Kind: {t.get('kind')}"]
    type_params = t.get("typeParams") or []
    if type_params:
        lines.append("Type params: " + ", ".join(type_params))
    props = t.get("properties") or []
    if props:
        lines.append("")
        lines.append("## Properties")
        for p in props:
            optional = " (optional)" if p.get("optional") else ""
            lines.append(f"- `{p.get('name')}`: {_format_type_ref(p.get('type'))}{optional}")
    members = t.get("unionMembers") or []
    if members:
        lines.append("")
        lines.append("## Union members")
        for m in members:
            lines.append(f"- {_format_type_ref(m)}")
    return "\n".join(lines)


def _format_node_view(n: dict) -> list[str]:
    """Render a single resolved node (alias, type, config, ports, errors) as lines."""
    lines: list[str] = []
    alias = n.get("alias")
    ntype = n.get("type")
    label = n.get("label") or ""
    head = f"- **{alias}** — `{ntype}`" + (f" ({label})" if label else "")
    if not n.get("supported", True):
        head += " [UNSUPPORTED]"
    lines.append(head)
    cfg = n.get("config") or {}
    if cfg:
        lines.append("    config: " + ", ".join(f"{k}={v}" for k, v in cfg.items()))
    ins = n.get("inputs") or []
    if ins:
        parts = []
        for p in ins:
            mark = "*" if p.get("required") else ""
            conn = "=" if p.get("connected") else ""
            parts.append(f"{p.get('id')}{mark}:{p.get('type')}{conn}")
        lines.append("    in:  " + ", ".join(parts))
    outs = n.get("outputs") or []
    if outs:
        lines.append("    out: " + ", ".join(f"{p.get('id')}:{p.get('type')}" for p in outs))
    for handle, message in (n.get("portErrors") or {}).items():
        lines.append(f"    ! {handle}: {message}")
    return lines


def _format_graph_view(view: dict) -> str:
    """Render the alias-addressed resolved automation graph view."""
    lines = [f"# Automation: {view.get('name', '')} (ID: {view.get('id')})"]
    if view.get("description"):
        lines.append(view.get("description"))
    lines.append(f"Enabled: {'yes' if view.get('enabled') else 'no'} | Valid: {'yes' if view.get('isValid') else 'NO'}")

    nodes = view.get("nodes") or []
    edges = view.get("edges") or []

    lines.append("")
    lines.append(f"## Nodes ({len(nodes)})")
    if not nodes:
        lines.append("_(none — add a trigger.* node to start)_")
    for n in nodes:
        lines.extend(_format_node_view(n))

    lines.append("")
    lines.append(f"## Edges ({len(edges)})")
    if not edges:
        lines.append("_(none)_")
    for e in edges:
        lines.append(f"- {e.get('from')} -> {e.get('to')}")

    errors = view.get("errors") or []
    lines.append("")
    if errors:
        lines.append(f"## Problems ({len(errors)}) — fix these before enabling")
        for er in errors:
            alias = er.get("alias")
            lines.append(f"- {(alias + ': ') if alias else ''}{er.get('message')}")
    else:
        lines.append("## Problems: none — the automation is valid.")
    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        # Skills: on-demand reference material for the DSL-heavy tools.
        Tool(
            name="load_skill",
            description=(
                "Load a Pomavo skill: the full reference material for a DSL-heavy tool, "
                "returned as markdown. Load the relevant skill BEFORE writing a query or "
                "report layout, then follow it.\n\n"
                "Available skills:\n"
                "- `pomavo-query-language` \u2014 read/filter search DSL. Load before using "
                "`search_tickets`, writing the `[filter]` prefix of `execute_query`, or "
                "writing report chart/variable queries.\n"
                "- `pomavo-mutation-dsl` \u2014 bulk mutation DSL (SET/CREATE/LINK/UNLINK/"
                "COMMENT). Load before using `execute_query`.\n"
                "- `pomavo-report-layout` \u2014 report layout language (layout tags, chart "
                "components, x/y/series/color contract, `<Variable>`). Load before using "
                "`create_report`.\n"
                "- `pomavo-screen-layout` \u2014 ticket TEMPLATE SCREEN layout language "
                "(Field/Label/Plugin/Row/Column/Section/Collapsible/Color/Font/Trigger/"
                "Text). Load before writing a screen's `layout_code`.\n"
                "- `pomavo-automation` \u2014 incremental automation authoring (node catalog, "
                "type system, alias workflow, `alias.handle` edges, triggers/validation). "
                "Load before using the automation tools (`create_automation`, `add_node`, "
                "`connect_nodes`, etc.)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The skill to load.",
                        "enum": list(AVAILABLE_SKILLS.keys()),
                    },
                },
                "required": ["name"],
            },
        ),
        # Template tools
        Tool(
            name="list_templates",
            description="List all available ticket templates in the organization",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_template",
            description="Get details of a specific template by name or ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Template name (e.g., 'Bug Report', 'Task')",
                    },
                    "id": {
                        "type": "integer",
                        "description": "Template ID",
                    },
                },
                "required": [],
            },
        ),
        # Project tools
        Tool(
            name="list_projects",
            description="List all projects in the organization",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_project",
            description="Get details of a specific project by slug or ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Project slug (e.g., 'app' or 'POMAVO/app')",
                    },
                    "id": {
                        "type": "integer",
                        "description": "Project ID",
                    },
                },
                "required": [],
            },
        ),
        # Iteration tools
        Tool(
            name="create_project",
            description="Create a new project as a sub-project of an existing parent project. Projects are hierarchical: every project lives under a parent (use list_projects to find the parent's numeric ID). Returns the created project's ID and slug path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "parent_project_id": {
                        "type": "integer",
                        "description": "Numeric ID of the parent project this new project is created under (use list_projects to find it)",
                    },
                    "slug": {
                        "type": "string",
                        "description": "Short slug for the project (e.g., 'app'). Combined with the parent path to form the full slug.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable project name",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional project description",
                    },
                    "use_case": {
                        "type": "string",
                        "description": "Optional use case / project type (e.g., 'scrum', 'kanban')",
                    },
                },
                "required": ["parent_project_id", "slug", "name"],
            },
        ),
        Tool(
            name="create_report",
            description="""Create a customizable, project-scoped report: charts and tables built with the Pomavo screen language (layout code) and backed by search-DSL queries. Use list_projects to find the numeric project_id; requires CREATE_REPORT on that project.

Before writing layout_code, call load_skill(name="pomavo-report-layout") for the layout tags, chart components, the x/y/series/color column contract, and the inline <Variable> system.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Numeric ID of the project that owns the report (scopes its permissions; use list_projects to find it)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable report name (shown in the report dropdown)",
                    },
                    "layout_code": {
                        "type": "string",
                        "description": "Screen-language layout code containing chart/table components backed by queries. Call load_skill(name=\"pomavo-report-layout\") for syntax.",
                    },
                    "variables": {
                        "type": "array",
                        "description": "Optional/legacy. Prefer declaring variables inline in layout_code via <Variable name=... type=... default=... /> tags (the report derives its variables from the code). Each: { name, label?, type: 'text'|'select'|'multiselect', options?, optionsQuery?, defaultValue?, defaultValues?, defaultValuesQuery? }.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "label": {"type": "string"},
                                "type": {"type": "string", "enum": ["text", "select", "multiselect"]},
                                "options": {"type": "array", "items": {"type": "string"}},
                                "optionsQuery": {"type": "string"},
                                "defaultValue": {"type": "string"},
                                "defaultValues": {"type": "array", "items": {"type": "string"}},
                                "defaultValuesQuery": {"type": "string"},
                            },
                            "required": ["name"],
                        },
                    },
                },
                "required": ["project_id", "name", "layout_code"],
            },
        ),
        # Automation authoring tools (incremental, alias-addressed)
        Tool(
            name="search_node_types",
            description=(
                "Search the automation node-type catalog (triggers, actions, conditions, "
                "data, tools, schedulers). Returns concise results (id/label/category/"
                "description + port/config counts). Use this to discover which node types "
                "exist before adding nodes. Call load_skill(name=\"pomavo-automation\") first "
                "for the full workflow."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text filter over node id/label/description (e.g. 'comment', 'transition').",
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category path prefix (e.g. 'Triggers', 'Actions', 'Tools.Logical').",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_node_definition",
            description=(
                "Get the full definition of a single automation node type: its input ports, "
                "output ports, config fields (with field types + options), type parameters, "
                "and documentation. Use before adding a node to learn its handles and config."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "description": "Node definition id (e.g. 'trigger.ticket_created', 'action.add_comment').",
                    },
                },
                "required": ["node_type"],
            },
        ),
        Tool(
            name="get_type_definition",
            description=(
                "Get the definition of a single type in the automation type system: its kind "
                "and named properties (for complex types like 'ticket', 'user', 'iteration'). "
                "Useful when planning an Extract Properties (data.extract) node."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "type_id": {
                        "type": "string",
                        "description": "Type id (e.g. 'ticket', 'user', 'list', 'string').",
                    },
                },
                "required": ["type_id"],
            },
        ),
        Tool(
            name="create_automation",
            description=(
                "Create a new, empty automation rule (no nodes yet), owned by a project (or "
                "org-wide when project_id is omitted). Returns the automation id. Then build "
                "the graph incrementally with add_node / connect_nodes. Requires "
                "CREATE_AUTOMATION on the project. Call load_skill(name=\"pomavo-automation\") "
                "for the authoring workflow."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Automation rule name (unique in the org)."},
                    "description": {"type": "string", "description": "Optional description."},
                    "project_id": {
                        "type": "integer",
                        "description": "Numeric project id that owns the automation. Omit for an org-wide rule.",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Whether the rule is active. Keep false while building; enable once valid.",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="get_automation",
            description=(
                "Get the alias-addressed, fully-resolved view of an automation graph: every "
                "node (by alias) with its live resolved input/output ports and types, per-port "
                "errors, hidden config, the edges (as 'alias.handle' → 'alias.handle'), and the "
                "aggregate validation state (isValid + errors). Call this after edits to see "
                "the current state and what still needs fixing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_id": {"type": "integer", "description": "The automation rule id."},
                },
                "required": ["automation_id"],
            },
        ),
        Tool(
            name="add_node",
            description=(
                "Add a node to an automation, addressed by a stable, unique alias you choose "
                "(e.g. 'trigger', 'is_bug', 'comment'). Returns the fresh resolved graph view "
                "so you can see the node's resolved ports and any new errors. Use "
                "search_node_types / get_node_definition to pick the type and valid config."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_id": {"type": "integer", "description": "The automation rule id."},
                    "alias": {
                        "type": "string",
                        "description": "Unique, human-friendly handle for this node within the automation (used in edges).",
                    },
                    "node_type": {
                        "type": "string",
                        "description": "Node definition id (e.g. 'trigger.ticket_created').",
                    },
                    "config": {
                        "type": "object",
                        "description": "Optional initial config values keyed by config field id ({fieldId: value}).",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["automation_id", "alias", "node_type"],
            },
        ),
        Tool(
            name="set_node_config",
            description=(
                "Set or update a node's config values (merges the given keys by default; set "
                "replace=true to overwrite the whole config). Returns the fresh resolved graph "
                "view. Config field ids come from get_node_definition."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_id": {"type": "integer", "description": "The automation rule id."},
                    "alias": {"type": "string", "description": "Alias of the node to update."},
                    "config": {
                        "type": "object",
                        "description": "Config values keyed by config field id ({fieldId: value}).",
                        "additionalProperties": {"type": "string"},
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "When true, replaces the entire config; when false (default), merges the given keys.",
                    },
                },
                "required": ["automation_id", "alias", "config"],
            },
        ),
        Tool(
            name="remove_node",
            description=(
                "Remove a node (by alias) and all edges touching it. Returns the fresh resolved "
                "graph view."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_id": {"type": "integer", "description": "The automation rule id."},
                    "alias": {"type": "string", "description": "Alias of the node to remove."},
                },
                "required": ["automation_id", "alias"],
            },
        ),
        Tool(
            name="connect_nodes",
            description=(
                "Connect a source output to a target input, each referenced as 'alias.handle' "
                "(e.g. from='trigger.ticket', to='comment.ticket'). The connection is "
                "type-checked against the node contracts and HARD-REJECTED with a clear reason "
                "if the source type is not assignable to the target input (or the handle does "
                "not exist / the input already has a connection). Returns the fresh resolved "
                "graph view on success."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_id": {"type": "integer", "description": "The automation rule id."},
                    "from": {
                        "type": "string",
                        "description": "Source output reference: 'sourceAlias.outputHandle'.",
                    },
                    "to": {
                        "type": "string",
                        "description": "Target input reference: 'targetAlias.inputHandle'.",
                    },
                },
                "required": ["automation_id", "from", "to"],
            },
        ),
        Tool(
            name="disconnect_nodes",
            description=(
                "Remove a connection between two node handles, each as 'alias.handle'. Returns "
                "the fresh resolved graph view."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_id": {"type": "integer", "description": "The automation rule id."},
                    "from": {"type": "string", "description": "Source output reference: 'sourceAlias.outputHandle'."},
                    "to": {"type": "string", "description": "Target input reference: 'targetAlias.inputHandle'."},
                },
                "required": ["automation_id", "from", "to"],
            },
        ),
        Tool(
            name="search_nodes",
            description=(
                "Search the node instances WITHIN an automation by alias, type, or label. "
                "Returns matching nodes with their aliases, types, and resolved ports. Use to "
                "recall aliases and handles when the graph is large."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_id": {"type": "integer", "description": "The automation rule id."},
                    "query": {
                        "type": "string",
                        "description": "Free-text filter over node alias/type/label. Omit to list all nodes.",
                    },
                },
                "required": ["automation_id"],
            },
        ),
        Tool(
            name="validate_automation",
            description=(
                "Validate an automation graph and return all outstanding problems: per-port "
                "type errors, required-but-unconnected inputs, missing trigger, cycles, and "
                "unsupported nodes. Returns isValid + a list of errors. Call before enabling a "
                "rule."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "automation_id": {"type": "integer", "description": "The automation rule id."},
                },
                "required": ["automation_id"],
            },
        ),
        Tool(
            name="list_iterations",
            description="List all iterations/sprints for a project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Project ID",
                    },
                    "project_slug": {
                        "type": "string",
                        "description": "Project slug (alternative to project_id)",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_active_iteration",
            description="Get the currently active iteration/sprint for a project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Project ID",
                    },
                    "project_slug": {
                        "type": "string",
                        "description": "Project slug (alternative to project_id)",
                    },
                },
                "required": [],
            },
        ),
        # Ticket tools
        Tool(
            name="create_iteration",
            description="Create a new iteration for a project. By default creates a sprint iteration (optionally named). Set backlog=true to create the project's backlog instead (a project has at most one backlog). Returns the created iteration's ID and name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Project ID to create the iteration in",
                    },
                    "project_slug": {
                        "type": "string",
                        "description": "Project slug (alternative to project_id)",
                    },
                    "custom_name": {
                        "type": "string",
                        "description": "Optional name for the sprint iteration. Ignored when backlog=true.",
                    },
                    "backlog": {
                        "type": "boolean",
                        "description": "When true, create the project's backlog iteration instead of a sprint. Default false.",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_ticket",
            description="Get full details of a specific ticket by ID or sequence number, including comments, links, history, and attachments by default",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Ticket ID",
                    },
                    "sequence_number": {
                        "type": "string",
                        "description": "Ticket sequence number (e.g., 'BUG-123')",
                    },
                    "include_comments": {
                        "type": "boolean",
                        "description": "Include comments (default: true)",
                        "default": True,
                    },
                    "include_links": {
                        "type": "boolean",
                        "description": "Include links to other tickets (default: true)",
                        "default": True,
                    },
                    "include_history": {
                        "type": "boolean",
                        "description": "Include change history/audit trail (default: false)",
                        "default": False,
                    },
                    "include_attachments": {
                        "type": "boolean",
                        "description": "Include attachments (default: true)",
                        "default": True,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="search_tickets",
            description="""Search for tickets using the Pomavo query DSL (filters, @mentions, date literals, in/not in, ORDER BY). Returns a paginated list of matching tickets.

Before writing a query, call load_skill(name="pomavo-query-language") for the full DSL syntax, fields, operators, and examples.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query using the Pomavo DSL. Call load_skill(name=\"pomavo-query-language\") for syntax. Examples: 'status = \"Open\"', 'Assignee = @me order by created_at desc'",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default: 1)",
                        "default": 1,
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Results per page (default: 20, max: 100)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_sprint_tickets",
            description="""Get all tickets in the current active sprint for a project.

Optionally filter by assignee or template type.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project slug (e.g., 'app' or 'POMAVO/app')",
                    },
                    "assignee": {
                        "type": "string",
                        "description": "Filter by assignee username. Use '@me' for current user.",
                    },
                    "template": {
                        "type": "string",
                        "description": "Filter by template type (e.g., 'Bug Report', 'Task')",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status (e.g., 'To Do', 'In Progress', 'Done')",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="create_ticket",
            description="""Create a new ticket. Use get_template first to see available fields for the template.

IMPORTANT: ALL field values including Project and Iteration MUST be passed inside the 'fields' object. There are no top-level parameters for project or iteration.

Required fields:
- 'Title' is always required
- 'Project' (numeric ID like '2') - MUST be included in fields for the permission check to work. Without it, creation will fail with 403.
- 'Iteration' (e.g., 'sprint-4') - include to assign to a sprint

Example fields: { 'Title': 'Fix login bug', 'Project': '2', 'Iteration': 'sprint-4', 'Priority': 'high', 'Assignee': 'username', 'Description': 'Details...' }

Use list_projects to find project IDs. Use list_iterations to find iteration names.

Tag fields (field type 'tag', e.g. the 'Tags' field): pass the value as one or more
concatenated groups in the form '(icon, color, label)' with NO separators between groups.
- label (3rd part) is required and must be unique within the field.
- color (2nd part) must be a hex value like '#ff0000' or '#f00', or left empty.
- icon (1st part) is an optional icon name, or left empty.
Examples: one tag -> '(, #ff0000, urgent)'; multiple -> '(, #ff0000, urgent)(, #22c55e, backend)'.
To clear all tags, pass an empty string. Do NOT pass JSON arrays or comma-separated bare words for tag fields.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "template": {
                        "type": "string",
                        "description": "Template name (e.g., 'Bug Report', 'Task', 'Epic')",
                    },
                    "fields": {
                        "type": "object",
                        "description": "Field values as { fieldLabel: value }. Use get_template to see available fields. Example: { 'Title': 'My ticket', 'Description': 'Details here', 'Priority': 'high', 'Project': '2', 'Iteration': 'sprint-3' }",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["template", "fields"],
            },
        ),
        Tool(
            name="update_ticket",
            description="""Update an existing ticket's fields. For state changes, use the transition_ticket tool instead.

Use get_ticket first to see the template, then get_template to see available fields and their types.

Note: When setting 'Project' or 'Iteration' fields, use the numeric project ID (e.g., '2'). Use list_projects to find IDs.
Consider using set_iteration tool for setting iteration which handles both Project and Iteration fields together.

Tag fields (field type 'tag', e.g. the 'Tags' field): pass the value as one or more
concatenated groups in the form '(icon, color, label)' with NO separators between groups.
- label (3rd part) is required and must be unique within the field.
- color (2nd part) must be a hex value like '#ff0000' or '#f00', or left empty.
- icon (1st part) is an optional icon name, or left empty.
Examples: one tag -> '(, #ff0000, urgent)'; multiple -> '(, #ff0000, urgent)(, #22c55e, backend)'.
To clear all tags, pass an empty string. Do NOT pass JSON arrays or comma-separated bare words for tag fields.
This tool replaces the whole tag field value; to add/remove individual tags, read the current value first (get_ticket) and pass the full new set.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                    "fields": {
                        "type": "object",
                        "description": "Field values as { fieldLabel: value }. Use get_template to see available fields. Example: { 'Description': 'Updated details', 'Priority': 'high' }. For 'Project' field, use numeric ID like '2'.",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["ticket", "fields"],
            },
        ),
        Tool(
            name="set_iteration",
            description="""Set the iteration (sprint) for a ticket. This sets both the project and iteration fields.

Use list_iterations to see available iterations for a project.

IMPORTANT: The 'project' parameter should be the numeric project ID (e.g., '2').
Alternatively, the full slug path (e.g., 'POMAVO/app') is also accepted and will be resolved to an ID.

Use list_projects to see available projects with their IDs.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                    "project": {
                        "type": "string",
                        "description": "Numeric project ID (e.g., '2') or full project slug path (e.g., 'POMAVO/app'). Use list_projects to find IDs.",
                    },
                    "iteration": {
                        "type": "string",
                        "description": "Iteration ID (e.g., 'sprint-3', 'backlog')",
                    },
                },
                "required": ["ticket", "project", "iteration"],
            },
        ),
        Tool(
            name="get_transitions",
            description="Get available state transitions for a ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number",
                    },
                },
                "required": ["ticket"],
            },
        ),
        Tool(
            name="transition_ticket",
            description="""Transition a ticket to a new state by state name. This is the recommended way to change ticket status.

Use this tool when you want to move a ticket to states like:
- "To Do", "In Progress", "Done" (common states)
- "Abandoned", "Won't Do" (terminal states)

The tool will automatically find the correct transition and state ID.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                    "state": {
                        "type": "string",
                        "description": "Target state name (e.g., 'Done', 'Abandoned', 'In Progress')",
                    },
                },
                "required": ["ticket", "state"],
            },
        ),
        # Comment tools
        Tool(
            name="add_comment",
            description="Add a comment to a ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                    "content": {
                        "type": "string",
                        "description": "The comment content (supports markdown)",
                    },
                    "reply_to": {
                        "type": "integer",
                        "description": (
                            "OPTIONAL. Omit this field for a normal top-level comment. "
                            "Only set it when you are explicitly replying to an existing "
                            "comment, and only to a real comment ID you obtained from "
                            "list_comments on THIS ticket. Never guess, default, or "
                            "auto-fill this value (do NOT pass 0 or 1) — an invalid ID "
                            "makes the whole request fail with PARENT_COMMENT_NOT_FOUND."
                        ),
                    },
                },
                "required": ["ticket", "content"],
            },
        ),
        Tool(
            name="edit_comment",
            description="Edit an existing comment on a ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                    "comment_id": {
                        "type": "integer",
                        "description": "The ID of the comment to edit",
                    },
                    "content": {
                        "type": "string",
                        "description": "The new comment content",
                    },
                },
                "required": ["ticket", "comment_id", "content"],
            },
        ),
        Tool(
            name="delete_comment",
            description="Delete a comment from a ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                    "comment_id": {
                        "type": "integer",
                        "description": "The ID of the comment to delete",
                    },
                },
                "required": ["ticket", "comment_id"],
            },
        ),
        Tool(
            name="list_comments",
            description="List all comments on a ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                },
                "required": ["ticket"],
            },
        ),
        # Link tools
        Tool(
            name="list_links",
            description="List all links for a ticket (parent/child, blocks/blocked by, relates to, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                },
                "required": ["ticket"],
            },
        ),
        Tool(
            name="list_link_types",
            description="List available link types that can be used to link tickets",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                },
                "required": ["ticket"],
            },
        ),
        Tool(
            name="link_tickets",
            description="""Create a link between two tickets.

Common link types:
- "blocks" / "is blocked by"
- "parent of" / "child of"  
- "relates to"
- "duplicates" / "is duplicated by"

Use list_link_types to see all available link types and their IDs.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_ticket": {
                        "type": "string",
                        "description": "Source ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                    "target_ticket": {
                        "type": "string",
                        "description": "Target ticket ID or sequence number to link to",
                    },
                    "link_type_id": {
                        "type": "integer",
                        "description": "The template link type ID (use list_link_types to find available types)",
                    },
                },
                "required": ["source_ticket", "target_ticket", "link_type_id"],
            },
        ),
        Tool(
            name="unlink_tickets",
            description="Remove a link between tickets",
            inputSchema={
                "type": "object",
                "properties": {
                    "link_id": {
                        "type": "integer",
                        "description": "The link ID to remove (use list_links to find link IDs)",
                    },
                },
                "required": ["link_id"],
            },
        ),
        Tool(
            name="download_attachment",
            description="Download an attachment and return its content. For images, returns base64-encoded data that can be analyzed. Use get_ticket first to see available attachments and their IDs. Set 'return_presigned_url' to true to get a temporary presigned download URL instead of the file content (useful for large files or handing the link to another system).",
            inputSchema={
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "The attachment ID (GUID) from the ticket's attachments list",
                    },
                    "return_presigned_url": {
                        "type": "boolean",
                        "description": "When true, return a temporary presigned download URL instead of downloading the file content. Defaults to false.",
                    },
                    "expiry_seconds": {
                        "type": "integer",
                        "description": "Lifetime of the presigned URL in seconds (only used when return_presigned_url is true). Defaults to the server default (~900s). Clamped server-side to supported bounds (60s to 7 days).",
                    },
                },
                "required": ["attachment_id"],
            },
        ),
        Tool(
            name="upload_attachment",
            description="""Upload an attachment to a ticket.

Accepts either a file path or base64-encoded file content and uploads it to the specified ticket.
Supports common file types including images (PNG, JPEG, GIF, WebP) and documents.

Use this tool to attach files, screenshots, or documents to tickets.

Set 'return_presigned_url' to true to instead create a pending attachment and return a temporary
presigned PUT URL (no content is uploaded by this tool) that another system can upload the bytes to.
In that mode 'content'/'file_path' are optional; provide 'filename' and 'content_type' explicitly.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket": {
                        "type": "string",
                        "description": "Ticket ID or sequence number (e.g., 'BUG-123')",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file to upload. Use this instead of 'content' for large files.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Base64-encoded file content. Use 'file_path' instead for large files.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "The file name with extension (e.g., 'screenshot.png'). Optional when file_path is provided (derived from path). Required in presigned-url mode when no file_path is given.",
                    },
                    "content_type": {
                        "type": "string",
                        "description": "MIME type of the file (e.g., 'image/png'). If not provided, will attempt to detect from filename.",
                    },
                    "is_manual": {
                        "type": "boolean",
                        "description": "Whether this is a manual attachment (true) or embedded in rich text (false). Defaults to true.",
                    },
                    "return_presigned_url": {
                        "type": "boolean",
                        "description": "When true, do not upload content; instead return a temporary presigned PUT URL for the caller to upload the file bytes to. Defaults to false.",
                    },
                    "expiry_seconds": {
                        "type": "integer",
                        "description": "Lifetime of the presigned URL in seconds (only used when return_presigned_url is true). Defaults to the server default (~900s). Clamped server-side to supported bounds (60s to 7 days).",
                    },
                },
                "required": ["ticket"],
            },
        ),
        Tool(
            name="delete_attachment",
            description="Delete an attachment from a ticket. Use get_ticket first to see available attachments and their IDs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "The attachment ID (GUID) from the ticket's attachments list",
                    },
                },
                "required": ["attachment_id"],
            },
        ),
        # Permissions tools
        Tool(
            name="get_my_permissions",
            description="""Get the current user's effective permissions.

Returns a list of all permissions granted to the current API user, including:
- The action (e.g., CREATE_TICKET, EDIT_TICKET, VIEW_PROJECT)
- The resource scope (e.g., 'urn:pomavo:org:*' for org-wide, 'urn:pomavo:project:2' for specific project)

Use this to understand what operations the current user can perform.""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="grant_permission",
            description="""Grant a permission to a user.

Grants a specific permission action on a resource to a user. Requires EDIT_ORG permission.

Common actions: VIEW_ISSUE, CREATE_ISSUE, EDIT_ISSUE, TRANSITION_ISSUE, MOVE_ISSUE,
ADD_COMMENT, EDIT_COMMENT, DELETE_COMMENT, LIST_COMMENT,
UPLOAD_ATTACHMENT, DOWNLOAD_ATTACHMENT, DELETE_ATTACHMENT,
CREATE_LINK, DELETE_LINK, LIST_LINK,
VIEW_PROJECT, EDIT_PROJECT, DELETE_PROJECT,
EDIT_ORG, LIST_ITERATIONS, FOLLOW_TICKET,
CREATE_INTEGRATION, EDIT_INTEGRATION, DELETE_INTEGRATION

Resource format: 'urn:pomavo:project:<id>' for project-scoped, 'urn:pomavo:org:*' for org-wide.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Username (e.g., 'testbot') or user UUID. Usernames are resolved to UUIDs automatically.",
                    },
                    "action": {
                        "type": "string",
                        "description": "The permission action (e.g., 'VIEW_ISSUE', 'EDIT_TICKET')",
                    },
                    "resource": {
                        "type": "string",
                        "description": "The resource scope (e.g., 'urn:pomavo:project:2' or 'urn:pomavo:project:*')",
                    },
                },
                "required": ["user_id", "action", "resource"],
            },
        ),
        Tool(
            name="revoke_permission",
            description="""Revoke a permission from a user.

Removes a specific permission grant from a user. Requires EDIT_ORG permission.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Username (e.g., 'testbot') or user UUID. Usernames are resolved to UUIDs automatically.",
                    },
                    "action": {
                        "type": "string",
                        "description": "The permission action to revoke",
                    },
                    "resource": {
                        "type": "string",
                        "description": "The resource scope to revoke",
                    },
                },
                "required": ["user_id", "action", "resource"],
            },
        ),
        Tool(
            name="check_permission",
            description="""Check if a user has a specific permission.

Returns true/false indicating whether the user has the given permission.
Non-admin users can only check their own permissions.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID to check",
                    },
                    "action": {
                        "type": "string",
                        "description": "The permission action to check",
                    },
                    "resource": {
                        "type": "string",
                        "description": "The resource scope to check",
                    },
                },
                "required": ["user_id", "action", "resource"],
            },
        ),
        Tool(
            name="get_user_permissions",
            description="""Get all permission grants for a specific user.

Returns detailed grant records including who granted the permission and when.
Requires EDIT_ORG permission to view other users' grants (viewing own grants is always allowed).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "Username (e.g., 'testbot') or user UUID. Usernames are resolved to UUIDs automatically.",
                    },
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="list_all_permission_grants",
            description="""List all permission grants in the organization.

Returns all grants across all users. Requires EDIT_ORG permission.

Useful for auditing who has what permissions.""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="list_available_permissions",
            description="""List all available permission actions grouped by category.

Returns the complete set of permission actions that can be granted, organized by category
(organization, project, issue, comment, attachment, link, template, workflow, integration, user, etc.)
along with resource type definitions.

Useful for discovering what permissions exist before granting them.""",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="execute_query",
            description="""Execute a bulk mutation using the Pomavo DSL: UPDATE (SET), CREATE tickets, LINK/UNLINK, and add COMMENTs across many tickets at once. Modifies data and respects permissions; use LIMIT to cap how many tickets are affected.

Before writing a query, call load_skill(name="pomavo-mutation-dsl") for the full syntax. Its leading [filter] uses the pomavo-query-language skill.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The mutation DSL query to execute. Call load_skill(name=\"pomavo-mutation-dsl\") for full syntax.",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    # Skills are served from local files and need no API client / auth.
    if name == "load_skill":
        skill_name = (arguments or {}).get("name", "")
        body = _read_skill_body(skill_name)
        if body is None:
            available = ", ".join(sorted(AVAILABLE_SKILLS))
            return [
                TextContent(
                    type="text",
                    text=f"Unknown skill '{skill_name}'. Available skills: {available}.",
                )
            ]
        return [TextContent(type="text", text=body)]

    client = get_client()

    try:
        if name == "list_templates":
            templates = await client.list_templates()
            lines = ["# Templates\n"]
            for t in templates:
                prefix = t.sequence_config.prefix if t.sequence_config else ""
                lines.append(f"- **{t.name}** (ID: {t.id}, Prefix: {prefix})")
                if t.description:
                    lines.append(f"  {t.description}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_template":
            template = None
            if "id" in arguments:
                template = await client.get_template(arguments["id"])
            elif "name" in arguments:
                template = await client.get_template_by_name(arguments["name"])
            else:
                return [TextContent(type="text", text="Error: Provide either 'name' or 'id'")]

            if not template:
                return [TextContent(type="text", text="Template not found")]

            lines = [
                f"# {template.name}",
                f"ID: {template.id}",
                f"Description: {template.description or 'N/A'}",
                f"Icon: {template.icon or 'N/A'}",
                f"Color: {template.color or 'N/A'}",
                "",
                "## Fields",
            ]
            for field in template.fields:
                lines.append(f"- **{field.label}** ({field.field_type}) - ID: `{field.id}`")

            if template.workflow:
                lines.append("")
                lines.append("## Workflow States")
                for state in template.workflow.states:
                    lines.append(f"- **{state.name}** ({state.category}) - ID: `{state.id}`")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "list_projects":
            projects = await client.list_projects()
            lines = ["# Projects", "", "Use the full Slug path when setting Project/Iteration fields on tickets.", ""]
            for p in projects:
                path = await client.get_project_path(p)
                lines.append(f"- **{p.name}** (ID: {p.id}, Slug: `{path}`)")
                if p.description:
                    lines.append(f"  {p.description}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_project":
            project = None
            if "id" in arguments:
                project = await client.get_project(arguments["id"])
            elif "slug" in arguments:
                project = await client.get_project_by_slug(arguments["slug"])
            else:
                return [TextContent(type="text", text="Error: Provide either 'slug' or 'id'")]

            if not project:
                return [TextContent(type="text", text="Project not found")]

            path = await client.get_project_path(project)
            lines = [
                f"# {project.name}",
                f"ID: {project.id}",
                f"Slug: {path}",
                f"Description: {project.description or 'N/A'}",
                f"Use Case: {project.use_case}",
            ]
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "create_project":
            parent_project_id = arguments.get("parent_project_id")
            slug = (arguments.get("slug") or "").strip()
            proj_name = (arguments.get("name") or "").strip()
            if not parent_project_id or not slug or not proj_name:
                return [TextContent(type="text", text="Error: 'parent_project_id', 'slug' and 'name' are required")]
            project = await client.create_project(
                parent_project_id=parent_project_id,
                slug=slug,
                name=proj_name,
                description=arguments.get("description"),
                use_case=arguments.get("use_case"),
            )
            path = await client.get_project_path(project)
            lines = [
                f"# Created project: {project.name}",
                f"ID: {project.id}",
                f"Slug: {path}",
            ]
            if project.description:
                lines.append(f"Description: {project.description}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "create_report":
            project_id = arguments.get("project_id")
            report_name = (arguments.get("name") or "").strip()
            layout_code = arguments.get("layout_code") or ""
            if not project_id or not report_name:
                return [TextContent(type="text", text="Error: 'project_id' and 'name' are required")]
            report = await client.create_report(
                project_id=project_id,
                name=report_name,
                layout_code=layout_code,
                variables=arguments.get("variables") or [],
            )
            lines = [
                f"# Created report: {report.get('name', report_name)}",
                f"ID: {report.get('id')}",
                f"Project ID: {report.get('projectId', project_id)}",
            ]
            variables = report.get("variables") or []
            if variables:
                lines.append("Variables: " + ", ".join(v.get("name", "") for v in variables))
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "search_node_types":
            nodes = await client.search_node_types(
                query=arguments.get("query"), category=arguments.get("category")
            )
            return [TextContent(type="text", text=_format_node_types(nodes))]

        elif name == "get_node_definition":
            node_type = (arguments.get("node_type") or "").strip()
            if not node_type:
                return [TextContent(type="text", text="Error: 'node_type' is required")]
            definition = await client.get_node_definition(node_type)
            return [TextContent(type="text", text=_format_node_definition(definition))]

        elif name == "get_type_definition":
            type_id = (arguments.get("type_id") or "").strip()
            if not type_id:
                return [TextContent(type="text", text="Error: 'type_id' is required")]
            type_def = await client.get_type_definition(type_id)
            return [TextContent(type="text", text=_format_type_definition(type_def))]

        elif name == "create_automation":
            auto_name = (arguments.get("name") or "").strip()
            if not auto_name:
                return [TextContent(type="text", text="Error: 'name' is required")]
            rule = await client.create_automation(
                name=auto_name,
                description=arguments.get("description"),
                project_id=arguments.get("project_id"),
                enabled=bool(arguments.get("enabled", False)),
            )
            lines = [
                f"# Created automation: {rule.get('name', auto_name)}",
                f"ID: {rule.get('id')}",
                f"Project ID: {rule.get('projectId')}",
                "",
                "Empty graph. Add a trigger node with add_node, then wire actions with connect_nodes.",
            ]
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_automation":
            automation_id = arguments.get("automation_id")
            if not automation_id:
                return [TextContent(type="text", text="Error: 'automation_id' is required")]
            view = await client.get_automation_graph(automation_id)
            return [TextContent(type="text", text=_format_graph_view(view))]

        elif name == "add_node":
            automation_id = arguments.get("automation_id")
            alias = (arguments.get("alias") or "").strip()
            node_type = (arguments.get("node_type") or "").strip()
            if not automation_id or not alias or not node_type:
                return [TextContent(type="text", text="Error: 'automation_id', 'alias' and 'node_type' are required")]
            view = await client.add_automation_node(
                automation_id=automation_id,
                alias=alias,
                node_type=node_type,
                config=arguments.get("config") or {},
            )
            return [TextContent(type="text", text=f"Added node '{alias}'.\n\n" + _format_graph_view(view))]

        elif name == "set_node_config":
            automation_id = arguments.get("automation_id")
            alias = (arguments.get("alias") or "").strip()
            config = arguments.get("config")
            if not automation_id or not alias or config is None:
                return [TextContent(type="text", text="Error: 'automation_id', 'alias' and 'config' are required")]
            view = await client.update_automation_node_config(
                automation_id=automation_id,
                alias=alias,
                config=config,
                replace=bool(arguments.get("replace", False)),
            )
            return [TextContent(type="text", text=f"Updated config for '{alias}'.\n\n" + _format_graph_view(view))]

        elif name == "remove_node":
            automation_id = arguments.get("automation_id")
            alias = (arguments.get("alias") or "").strip()
            if not automation_id or not alias:
                return [TextContent(type="text", text="Error: 'automation_id' and 'alias' are required")]
            view = await client.remove_automation_node(automation_id, alias)
            return [TextContent(type="text", text=f"Removed node '{alias}'.\n\n" + _format_graph_view(view))]

        elif name == "connect_nodes":
            automation_id = arguments.get("automation_id")
            from_ref = (arguments.get("from") or "").strip()
            to_ref = (arguments.get("to") or "").strip()
            if not automation_id or not from_ref or not to_ref:
                return [TextContent(type="text", text="Error: 'automation_id', 'from' and 'to' are required")]
            view = await client.connect_automation(automation_id, from_ref, to_ref)
            return [TextContent(type="text", text=f"Connected {from_ref} -> {to_ref}.\n\n" + _format_graph_view(view))]

        elif name == "disconnect_nodes":
            automation_id = arguments.get("automation_id")
            from_ref = (arguments.get("from") or "").strip()
            to_ref = (arguments.get("to") or "").strip()
            if not automation_id or not from_ref or not to_ref:
                return [TextContent(type="text", text="Error: 'automation_id', 'from' and 'to' are required")]
            view = await client.disconnect_automation(automation_id, from_ref, to_ref)
            return [TextContent(type="text", text=f"Disconnected {from_ref} -> {to_ref}.\n\n" + _format_graph_view(view))]

        elif name == "search_nodes":
            automation_id = arguments.get("automation_id")
            if not automation_id:
                return [TextContent(type="text", text="Error: 'automation_id' is required")]
            view = await client.get_automation_graph(automation_id)
            query = (arguments.get("query") or "").strip().lower()
            nodes = view.get("nodes") or []
            if query:
                nodes = [
                    n
                    for n in nodes
                    if query in (n.get("alias") or "").lower()
                    or query in (n.get("type") or "").lower()
                    or query in (n.get("label") or "").lower()
                ]
            lines = [f"# Nodes matching '{query}'" if query else "# Nodes", f"({len(nodes)} of {len(view.get('nodes') or [])})", ""]
            if not nodes:
                lines.append("_(no matches)_")
            for n in nodes:
                lines.extend(_format_node_view(n))
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "validate_automation":
            automation_id = arguments.get("automation_id")
            if not automation_id:
                return [TextContent(type="text", text="Error: 'automation_id' is required")]
            view = await client.get_automation_graph(automation_id)
            errors = view.get("errors") or []
            if not errors:
                return [TextContent(type="text", text=f"Automation '{view.get('name')}' (ID {view.get('id')}) is VALID.")]
            lines = [f"Automation '{view.get('name')}' (ID {view.get('id')}) is INVALID — {len(errors)} problem(s):", ""]
            for er in errors:
                alias = er.get("alias")
                lines.append(f"- {(alias + ': ') if alias else ''}{er.get('message')}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "list_iterations":
            project_id = arguments.get("project_id")
            if not project_id and "project_slug" in arguments:
                project = await client.get_project_by_slug(arguments["project_slug"])
                if project:
                    project_id = project.id

            if not project_id:
                return [TextContent(type="text", text="Error: Project not found")]

            iterations = await client.list_iterations(project_id)
            lines = ["# Iterations\n"]
            for i in iterations:
                status = []
                if i.is_active:
                    status.append("✅ ACTIVE")
                if i.is_completed:
                    status.append("✓ Completed")
                if i.is_planned:
                    status.append("📅 Planned")
                if i.is_backlog:
                    status.append("📋 Backlog")

                status_str = " ".join(status) if status else ""
                lines.append(f"- **{i.name}** (ID: `{i.id}`) {status_str}")
                if i.start_date:
                    lines.append(f"  Start: {i.start_date.strftime('%Y-%m-%d')}")
                if i.end_date:
                    lines.append(f"  End: {i.end_date.strftime('%Y-%m-%d')}")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_active_iteration":
            project_id = arguments.get("project_id")
            if not project_id and "project_slug" in arguments:
                project = await client.get_project_by_slug(arguments["project_slug"])
                if project:
                    project_id = project.id

            if not project_id:
                return [TextContent(type="text", text="Error: Project not found")]

            iteration = await client.get_active_iteration(project_id)
            if not iteration:
                return [TextContent(type="text", text="No active iteration found")]

            lines = [
                f"# Active Iteration: {iteration.name}",
                f"ID: `{iteration.id}`",
            ]
            if iteration.start_date:
                lines.append(f"Start: {iteration.start_date.strftime('%Y-%m-%d')}")
            if iteration.end_date:
                lines.append(f"End: {iteration.end_date.strftime('%Y-%m-%d')}")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "create_iteration":
            project_id = arguments.get("project_id")
            if not project_id and "project_slug" in arguments:
                project = await client.get_project_by_slug(arguments["project_slug"])
                if project:
                    project_id = project.id
            if not project_id:
                return [TextContent(type="text", text="Error: Project not found")]

            if arguments.get("backlog"):
                iteration = await client.create_backlog(project_id)
                heading = "Created backlog"
            else:
                iteration = await client.create_iteration(project_id, arguments.get("custom_name"))
                heading = "Created iteration"

            lines = [
                f"# {heading}: {iteration.name}",
                f"ID: `{iteration.id}`",
            ]
            if iteration.start_date:
                lines.append(f"Start: {iteration.start_date.strftime('%Y-%m-%d')}")
            if iteration.end_date:
                lines.append(f"End: {iteration.end_date.strftime('%Y-%m-%d')}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_ticket":
            ticket = None
            ticket_id = arguments.get("id")
            sequence_number = arguments.get("sequence_number")
            if ticket_id:
                ticket = await client.get_ticket(ticket_id)
            elif sequence_number:
                ticket = await client.get_ticket_by_sequence(sequence_number)
            else:
                return [TextContent(type="text", text="Error: Provide either 'id' or 'sequence_number'")]

            # Fetch template to build field name mapping
            field_map: dict[str, str] = {}
            state_map: dict[str, str] = {}
            template = None
            try:
                template = await client.get_template(ticket.template_id)
                if template.fields:
                    field_map = {f.id: f.label for f in template.fields}
                if template.workflow and template.workflow.states:
                    state_map = {s.id: s.name for s in template.workflow.states}
            except Exception:
                pass  # Continue without field names if template fetch fails

            # Get template name for display
            template_name = template.name if template else None

            # Build comprehensive response with all ticket data
            result_parts = [format_ticket(ticket, field_map, template_name)]
            
            # Include comments (default: true)
            if arguments.get("include_comments", True):
                comments = await client.list_comments(ticket.id)
                result_parts.append(format_comments(comments, ticket.sequence_number))
            
            # Include links (default: true)
            if arguments.get("include_links", True):
                links = await client.list_links(ticket.id)
                result_parts.append(format_links(links, ticket.id, ticket.sequence_number))
            
            # Include history (default: false)
            if arguments.get("include_history", False):
                history = await client.get_ticket_history(ticket.id)
                result_parts.append(format_history(history, ticket.sequence_number, field_map, state_map))
            
            # Include attachments (default: true)
            if arguments.get("include_attachments", True) and ticket.client_ticket_id:
                attachments = await client.get_ticket_attachments(ticket.client_ticket_id)
                result_parts.append(format_attachments(attachments, ticket.sequence_number))

            return [TextContent(type="text", text="\n\n".join(result_parts))]

        elif name == "search_tickets":
            query = arguments.get("query", "")
            page = arguments.get("page", 1)
            page_size = min(arguments.get("page_size", 20), 100)

            result = await client.search_tickets(query, page, page_size)

            lines = [
                f"# Search Results",
                f"Found {result.total_count} tickets (page {result.page}/{result.total_pages})",
                "",
            ]
            for item in result.items:
                lines.append(format_search_result(item))

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_sprint_tickets":
            project_slug = arguments.get("project")
            assignee = arguments.get("assignee")
            template_filter = arguments.get("template")
            status_filter = arguments.get("status")

            if not project_slug:
                return [TextContent(type="text", text="Error: 'project' is required")]

            # Get the project by slug
            project = await client.get_project_by_slug(project_slug)
            if not project:
                return [TextContent(type="text", text=f"Error: Project '{project_slug}' not found")]

            # Get the active iteration for the project
            iteration = await client.get_active_iteration(project.id)
            if not iteration:
                return [TextContent(type="text", text=f"Error: No active sprint found for project '{project_slug}'")]

            # Build search query
            query_parts = [f'Iteration = "{iteration.id}"']
            
            if assignee:
                query_parts.append(f'Assignee = {assignee}')
            if template_filter:
                query_parts.append(f'template = "{template_filter}"')
            if status_filter:
                query_parts.append(f'status = "{status_filter}"')

            query = " and ".join(query_parts)
            result = await client.search_tickets(query, page=1, page_size=100)

            lines = [
                f"# {iteration.name} - {project_slug}",
                f"Found {result.total_count} tickets",
                "",
            ]
            for item in result.items:
                lines.append(format_search_result(item))

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "create_ticket":
            template_name = arguments.get("template")
            input_fields = arguments.get("fields", {})

            if not template_name:
                return [TextContent(type="text", text="Error: 'template' is required")]
            if not input_fields:
                return [TextContent(type="text", text="Error: 'fields' is required. Use get_template to see available fields.")]

            # Get the template to look up field IDs and types
            template = await client.get_template_by_name(template_name)
            if not template:
                return [TextContent(type="text", text=f"Error: Template '{template_name}' not found")]

            # Build field maps by label (case-insensitive)
            field_by_label: dict[str, tuple[str, str]] = {}  # label -> (id, field_type)
            field_by_id: dict[str, str] = {}  # id -> field_type
            for field in template.fields:
                field_by_label[field.label.lower()] = (field.id, field.field_type)
                field_by_id[field.id] = field.field_type

            # Map input fields to their IDs, transforming rich-text fields
            fields: dict[str, str] = {}
            for label, value in input_fields.items():
                label_lower = label.lower()
                if label_lower in field_by_label:
                    field_id, field_type = field_by_label[label_lower]
                    
                    # Special handling for Project field - convert slug to ID
                    if label_lower == "project" and value and not str(value).isdigit():
                        project = await client.get_project_by_slug(str(value))
                        if not project:
                            return [TextContent(type="text", text=f"Error: Project '{value}' not found. Use list_projects to see available projects.")]
                        fields[field_id] = str(project.id)
                    # Transform rich-text fields (mentions, ticket refs, markdown normalization)
                    elif field_type == "rich-text":
                        fields[field_id] = prepare_rich_text(str(value))
                    else:
                        fields[field_id] = str(value)
                else:
                    # Assume it's a field ID if not found by label
                    # Still apply rich-text transformation if the field type is rich-text
                    ftype = field_by_id.get(label)
                    if ftype == "rich-text":
                        fields[label] = prepare_rich_text(str(value))
                    else:
                        fields[label] = str(value)

            ticket = await client.create_ticket(template.id, fields)

            return [TextContent(
                type="text",
                text=f"✅ Created ticket **{ticket.sequence_number}**\n\n{format_ticket(ticket)}",
            )]

        elif name == "update_ticket":
            ticket_ref = arguments.get("ticket")
            input_fields = arguments.get("fields", {})
            
            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]
            if not input_fields:
                return [TextContent(type="text", text="Error: 'fields' is required. Use get_template to see available fields.")]

            # Get the ticket to find its ID and template
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            # Get template to find field IDs and types
            template = await client.get_template(ticket.template_id)
            field_by_label: dict[str, tuple[str, str]] = {}  # label -> (id, field_type)
            field_by_id: dict[str, str] = {}  # id -> field_type
            for field in template.fields:
                field_by_label[field.label.lower()] = (field.id, field.field_type)
                field_by_id[field.id] = field.field_type

            # Map input fields to their IDs, transforming rich-text fields
            fields: dict[str, str] = {}
            for label, value in input_fields.items():
                label_lower = label.lower()
                if label_lower in field_by_label:
                    field_id, field_type = field_by_label[label_lower]
                    
                    # Special handling for Project field - convert slug to ID
                    if label_lower == "project" and value and not str(value).isdigit():
                        project = await client.get_project_by_slug(str(value))
                        if not project:
                            return [TextContent(type="text", text=f"Error: Project '{value}' not found. Use list_projects to see available projects.")]
                        fields[field_id] = str(project.id)
                    # Transform rich-text fields (mentions, ticket refs, markdown normalization)
                    elif field_type == "rich-text":
                        fields[field_id] = prepare_rich_text(str(value))
                    else:
                        fields[field_id] = str(value)
                else:
                    # Assume it's a field ID if not found by label
                    # Still apply rich-text transformation if the field type is rich-text
                    ftype = field_by_id.get(label)
                    if ftype == "rich-text":
                        fields[label] = prepare_rich_text(str(value))
                    else:
                        fields[label] = str(value)

            result = await client.update_ticket(
                ticket.id,
                fields=fields,
            )

            return [TextContent(
                type="text",
                text=f"✅ Updated ticket **{ticket.sequence_number}**\n\nResponse: {json.dumps(result)}",
            )]

        elif name == "set_iteration":
            ticket_ref = arguments.get("ticket")
            project_slug = arguments.get("project")
            iteration_id = arguments.get("iteration")
            
            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]
            if not project_slug:
                return [TextContent(type="text", text="Error: 'project' is required")]
            if not iteration_id:
                return [TextContent(type="text", text="Error: 'iteration' is required")]

            # Resolve project - accept either numeric ID or slug
            if project_slug.isdigit():
                project_id = int(project_slug)
            else:
                # Validate slug format if a slug was given
                if "/" not in project_slug:
                    return [TextContent(
                        type="text", 
                        text=f"Error: 'project' must be a numeric ID (e.g., '2') or a full slug path (e.g., 'POMAVO/app'), not just '{project_slug}'. Use list_projects to see available projects."
                    )]

                # Look up project by slug to get the ID
                project = await client.get_project_by_slug(project_slug)
                if not project:
                    return [TextContent(
                        type="text",
                        text=f"Error: Project '{project_slug}' not found. Use list_projects to see available projects."
                    )]
                project_id = project.id

            # Get the ticket to find its ID and template
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            # Get template to find field IDs for Project and Iteration
            template = await client.get_template(ticket.template_id)
            field_by_label: dict[str, str] = {}  # label -> id
            for field in template.fields:
                field_by_label[field.label.lower()] = field.id

            # Check if both Project and Iteration fields exist
            if "project" not in field_by_label:
                return [TextContent(type="text", text="Error: Template does not have a 'Project' field")]
            if "iteration" not in field_by_label:
                return [TextContent(type="text", text="Error: Template does not have an 'Iteration' field")]

            # Set both fields - use project ID instead of slug
            fields = {
                field_by_label["project"]: str(project_id),
                field_by_label["iteration"]: iteration_id,
            }

            result = await client.update_ticket(
                ticket.id,
                fields=fields,
            )

            return [TextContent(
                type="text",
                text=f"✅ Set iteration for **{ticket.sequence_number}** to **{iteration_id}** in project **{project_slug}**",
            )]

        elif name == "get_transitions":
            ticket_ref = arguments.get("ticket")
            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]

            # Get the ticket ID
            if ticket_ref.isdigit():
                ticket_id = int(ticket_ref)
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)
                ticket_id = ticket.id

            transitions = await client.get_available_transitions(ticket_id)

            if not transitions:
                return [TextContent(type="text", text="No transitions available for this ticket")]

            lines = ["# Available Transitions\n"]
            for t in transitions:
                lines.append(f"- **{t.name}** → {t.to_state_name} ({t.to_state_category})")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "transition_ticket":
            ticket_ref = arguments.get("ticket")
            target_state = arguments.get("state")
            
            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]
            if not target_state:
                return [TextContent(type="text", text="Error: 'state' is required")]

            # Get the ticket
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            # Get available transitions
            transitions = await client.get_available_transitions(ticket.id)
            
            if not transitions:
                return [TextContent(type="text", text=f"No transitions available for ticket {ticket.sequence_number}")]

            # Find matching transition by state name (case-insensitive)
            target_lower = target_state.lower()
            matching_transition = None
            for t in transitions:
                if t.to_state_name.lower() == target_lower:
                    matching_transition = t
                    break
            
            if not matching_transition:
                available_states = ", ".join([t.to_state_name for t in transitions])
                return [TextContent(
                    type="text", 
                    text=f"Cannot transition to '{target_state}'. Available states: {available_states}"
                )]

            # Perform the transition
            result = await client.update_ticket(
                ticket.id,
                new_state_id=matching_transition.to_state_id,
            )

            return [TextContent(
                type="text",
                text=f"✅ Transitioned **{ticket.sequence_number}** to **{matching_transition.to_state_name}**",
            )]

        elif name == "list_comments":
            ticket_ref = arguments.get("ticket")
            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]

            # Get the ticket ID
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            comments = await client.list_comments(ticket.id)

            if not comments:
                return [TextContent(type="text", text=f"No comments on {ticket.sequence_number}")]

            lines = [f"# Comments on {ticket.sequence_number}\n"]
            for c in comments:
                author = c.get("author", {}).get("displayName", "Unknown")
                content = c.get("content", "")  # Full content, no truncation
                comment_id = c.get("id", "?")
                created = c.get("createdAt", "")[:10] if c.get("createdAt") else ""
                lines.append(f"**{author}** (ID: {comment_id}) - {created}")
                lines.append(f"> {content}")
                lines.append("")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "add_comment":
            ticket_ref = arguments.get("ticket")
            content = arguments.get("content")
            reply_to = arguments.get("reply_to")

            # Guard against hallucinated/placeholder reply targets: the LLM often fills this with
            # 0 (or another non-positive/bogus value) even for top-level comments. Treat anything
            # that is not a positive integer as "no reply target" so the comment posts normally.
            if reply_to is not None:
                try:
                    reply_to = int(reply_to)
                except (TypeError, ValueError):
                    reply_to = None
                else:
                    if reply_to <= 0:
                        reply_to = None

            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]
            if not content:
                return [TextContent(type="text", text="Error: 'content' is required")]

            # Get the ticket ID
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            # Transform content (mentions, ticket refs, markdown normalization)
            result = await client.add_comment(ticket.id, prepare_rich_text(content), reply_to)

            if "success" in result:
                return [TextContent(
                    type="text",
                    text=f"✅ Comment added to **{ticket.sequence_number}**",
                )]
            else:
                return [TextContent(type="text", text=f"Error: {json.dumps(result)}")]

        elif name == "edit_comment":
            ticket_ref = arguments.get("ticket")
            comment_id = arguments.get("comment_id")
            content = arguments.get("content")

            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]
            if not comment_id:
                return [TextContent(type="text", text="Error: 'comment_id' is required")]
            if not content:
                return [TextContent(type="text", text="Error: 'content' is required")]

            # Get the ticket ID
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            # Transform content (mentions, ticket refs, markdown normalization)
            result = await client.edit_comment(ticket.id, comment_id, prepare_rich_text(content))

            if "success" in result:
                return [TextContent(
                    type="text",
                    text=f"✅ Comment {comment_id} updated on **{ticket.sequence_number}**",
                )]
            else:
                return [TextContent(type="text", text=f"Error: {json.dumps(result)}")]

        elif name == "delete_comment":
            ticket_ref = arguments.get("ticket")
            comment_id = arguments.get("comment_id")

            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]
            if not comment_id:
                return [TextContent(type="text", text="Error: 'comment_id' is required")]

            # Get the ticket ID
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            result = await client.delete_comment(ticket.id, comment_id)

            if "success" in result:
                return [TextContent(
                    type="text",
                    text=f"✅ Comment {comment_id} deleted from **{ticket.sequence_number}**",
                )]
            else:
                return [TextContent(type="text", text=f"Error: {json.dumps(result)}")]

        elif name == "list_links":
            ticket_ref = arguments.get("ticket")
            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]

            # Get the ticket
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            links = await client.list_links(ticket.id)

            if not links:
                return [TextContent(type="text", text=f"No links on {ticket.sequence_number}")]

            lines = [f"# Links for {ticket.sequence_number}\n"]
            for link in links:
                link_id = link.get("id", "?")
                # Determine if viewing from source or target perspective
                if link.get("sourceTicketId") == ticket.id:
                    # Outward link: this ticket -> target
                    direction = link.get("outwardName", "links to")
                    other_seq = link.get("targetSequenceNumber", "?")
                    other_title = link.get("targetTitle", "")
                else:
                    # Inward link: source -> this ticket
                    direction = link.get("inwardName", "linked from")
                    other_seq = link.get("sourceSequenceNumber", "?")
                    other_title = link.get("sourceTitle", "")
                
                lines.append(f"- **{direction}** {other_seq}: {other_title[:50]}{'...' if len(other_title) > 50 else ''} (Link ID: {link_id})")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "list_link_types":
            ticket_ref = arguments.get("ticket")
            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]

            # Get the ticket
            if ticket_ref.isdigit():
                ticket = await client.get_ticket(int(ticket_ref))
            else:
                ticket = await client.get_ticket_by_sequence(ticket_ref)

            link_types = await client.list_link_types(ticket.id)

            if not link_types:
                return [TextContent(type="text", text="No link types available")]

            lines = ["# Available Link Types\n"]
            for lt in link_types:
                lt_id = lt.get("id", "?")
                name = lt.get("name", "Unknown")
                outward = lt.get("outwardName", "")
                inward = lt.get("inwardName", "")
                lines.append(f"- **{name}** (ID: {lt_id})")
                lines.append(f"  - Outward: \"{outward}\"")
                lines.append(f"  - Inward: \"{inward}\"")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "link_tickets":
            source_ref = arguments.get("source_ticket")
            target_ref = arguments.get("target_ticket")
            link_type_id = arguments.get("link_type_id")

            if not source_ref:
                return [TextContent(type="text", text="Error: 'source_ticket' is required")]
            if not target_ref:
                return [TextContent(type="text", text="Error: 'target_ticket' is required")]
            if not link_type_id:
                return [TextContent(type="text", text="Error: 'link_type_id' is required")]

            # Get source ticket
            if source_ref.isdigit():
                source_ticket = await client.get_ticket(int(source_ref))
            else:
                source_ticket = await client.get_ticket_by_sequence(source_ref)

            # Get target ticket
            if target_ref.isdigit():
                target_ticket = await client.get_ticket(int(target_ref))
            else:
                target_ticket = await client.get_ticket_by_sequence(target_ref)

            result = await client.create_link(source_ticket.id, target_ticket.id, link_type_id)

            if "success" in result:
                return [TextContent(
                    type="text",
                    text=f"✅ Linked **{source_ticket.sequence_number}** → **{target_ticket.sequence_number}**",
                )]
            else:
                return [TextContent(type="text", text=f"Error: {json.dumps(result)}")]

        elif name == "unlink_tickets":
            link_id = arguments.get("link_id")

            if not link_id:
                return [TextContent(type="text", text="Error: 'link_id' is required")]

            await client.delete_link(link_id)

            return [TextContent(
                type="text",
                text=f"✅ Link {link_id} removed",
            )]

        elif name == "download_attachment":
            attachment_id = arguments.get("attachment_id")
            return_presigned_url = arguments.get("return_presigned_url", False)
            expiry_seconds = arguments.get("expiry_seconds")

            if not attachment_id:
                return [TextContent(type="text", text="Error: 'attachment_id' is required")]

            # Presigned-URL mode: return a temporary download link instead of the content.
            if return_presigned_url:
                try:
                    url_response = await client.get_attachment_download_url(
                        attachment_id, expiry_seconds=expiry_seconds
                    )
                    if "failure" in url_response:
                        return [TextContent(
                            type="text",
                            text=f"Error getting download URL: {url_response['failure']}",
                        )]
                    success = url_response["success"]
                    download_url = success["downloadUrl"]
                    expires_at = success.get("expiresAt")
                    lines = [
                        f"Presigned download URL for attachment `{attachment_id}`:",
                        "",
                        f"- **URL**: {download_url}",
                    ]
                    if expires_at:
                        lines.append(f"- **Expires At**: {expires_at}")
                    return [TextContent(type="text", text="\n".join(lines))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting download URL: {str(e)}")]

            try:
                import base64
                
                # Download the attachment content
                content = await client.download_attachment(attachment_id)
                
                # Detect if it's an image based on magic bytes
                is_png = content[:8].startswith(b'\x89PNG')
                is_jpeg = content[:3] == b'\xff\xd8\xff'
                is_gif = content[:6] in (b'GIF87a', b'GIF89a')
                is_webp = content[:4] == b'RIFF' and content[8:12] == b'WEBP'
                
                is_image = is_png or is_jpeg or is_gif or is_webp
                
                if is_image:
                    # Determine MIME type
                    if is_png:
                        mime_type = "image/png"
                    elif is_jpeg:
                        mime_type = "image/jpeg"
                    elif is_gif:
                        mime_type = "image/gif"
                    elif is_webp:
                        mime_type = "image/webp"
                    else:
                        mime_type = "image/png"  # fallback
                    
                    # Return as ImageContent for direct analysis
                    content_b64 = base64.b64encode(content).decode('utf-8')
                    
                    return [
                        TextContent(
                            type="text",
                            text=f"Downloaded image attachment ({mime_type}, {len(content)} bytes):",
                        ),
                        ImageContent(
                            type="image",
                            data=content_b64,
                            mimeType=mime_type,
                        ),
                    ]
                else:
                    # For non-images, just return info about the download
                    return [TextContent(
                        type="text",
                        text=f"Downloaded attachment ({len(content)} bytes). Content is not an image and cannot be displayed.",
                    )]
                    
            except Exception as e:
                return [TextContent(type="text", text=f"Error downloading attachment: {str(e)}")]

        elif name == "upload_attachment":
            ticket_ref = arguments.get("ticket")
            content_b64 = arguments.get("content")
            file_path = arguments.get("file_path")
            filename = arguments.get("filename")
            content_type = arguments.get("content_type")
            is_manual = arguments.get("is_manual", True)
            return_presigned_url = arguments.get("return_presigned_url", False)
            expiry_seconds = arguments.get("expiry_seconds")

            if not ticket_ref:
                return [TextContent(type="text", text="Error: 'ticket' is required")]
            if not content_b64 and not file_path:
                if not return_presigned_url:
                    return [TextContent(type="text", text="Error: Either 'content' (base64) or 'file_path' is required")]
                # Presigned-url mode: no content needed, but the caller must describe the file.
                if not filename:
                    return [TextContent(type="text", text="Error: 'filename' is required in presigned-url mode when no 'content'/'file_path' is given")]
                if not content_type:
                    return [TextContent(type="text", text="Error: 'content_type' is required in presigned-url mode when no 'content'/'file_path' is given")]

            try:
                import base64
                import mimetypes
                import os

                content = None
                # Read content from file path or decode base64 (skipped when only requesting a URL)
                if file_path:
                    if not os.path.isfile(file_path):
                        return [TextContent(type="text", text=f"Error: File not found: {file_path}")]
                    with open(file_path, "rb") as f:
                        content = f.read()
                    if not filename:
                        filename = os.path.basename(file_path)
                elif content_b64:
                    if not filename:
                        return [TextContent(type="text", text="Error: 'filename' is required when using base64 content")]
                    try:
                        content = base64.b64decode(content_b64)
                    except Exception:
                        return [TextContent(type="text", text="Error: Invalid base64 content")]

                # Auto-detect content type if not provided
                if not content_type:
                    guessed_type, _ = mimetypes.guess_type(filename)
                    if guessed_type:
                        content_type = guessed_type
                    elif content is not None:
                        # Fallback: detect from magic bytes for common types
                        if content[:8].startswith(b'\x89PNG'):
                            content_type = "image/png"
                        elif content[:3] == b'\xff\xd8\xff':
                            content_type = "image/jpeg"
                        elif content[:6] in (b'GIF87a', b'GIF89a'):
                            content_type = "image/gif"
                        elif content[:4] == b'RIFF' and len(content) > 12 and content[8:12] == b'WEBP':
                            content_type = "image/webp"
                        elif content[:4] == b'%PDF':
                            content_type = "application/pdf"
                        else:
                            content_type = "application/octet-stream"
                    else:
                        content_type = "application/octet-stream"

                # Get the ticket to retrieve client_ticket_id
                if ticket_ref.isdigit():
                    ticket = await client.get_ticket(int(ticket_ref))
                else:
                    ticket = await client.get_ticket_by_sequence(ticket_ref)

                # Presigned-URL mode: create a pending attachment and return the PUT URL
                # without uploading any bytes. The caller uploads the file themselves.
                if return_presigned_url:
                    url_response = await client.get_upload_url(
                        client_ticket_id=ticket.client_ticket_id,
                        filename=filename,
                        content_type=content_type,
                        file_size_bytes=len(content) if content is not None else 0,
                        is_manual=is_manual,
                        expiry_seconds=expiry_seconds,
                    )
                    if "failure" in url_response:
                        return [TextContent(type="text", text=f"Error getting upload URL: {url_response['failure']}")]
                    success = url_response["success"]
                    lines = [
                        f"Presigned upload URL for **{ticket.sequence_number}**",
                        "",
                        f"- **Attachment ID**: {success['attachmentId']}",
                        f"- **Upload URL**: {success['uploadUrl']}",
                        f"- **File Name**: {filename}",
                        f"- **Content Type**: {content_type}",
                    ]
                    if success.get("expiresAt"):
                        lines.append(f"- **Expires At**: {success['expiresAt']}")
                    lines.append("")
                    lines.append(
                        f"Upload the file bytes with an HTTP PUT to the Upload URL, "
                        f"setting the `Content-Type: {content_type}` header."
                    )
                    return [TextContent(type="text", text="\n".join(lines))]

                # Upload the attachment
                result = await client.upload_attachment(
                    client_ticket_id=ticket.client_ticket_id,
                    filename=filename,
                    content=content,
                    content_type=content_type,
                    is_manual=is_manual,
                )
                
                if "failure" in result:
                    return [TextContent(type="text", text=f"Error uploading attachment: {result['failure']}")]
                
                success = result["success"]
                attachment_id = success["attachmentId"]
                file_size = success["fileSizeBytes"]
                
                return [TextContent(
                    type="text",
                    text=f"Uploaded attachment to **{ticket.sequence_number}**\n\n"
                         f"- **Attachment ID**: {attachment_id}\n"
                         f"- **File Name**: {filename}\n"
                         f"- **Content Type**: {content_type}\n"
                         f"- **Size**: {file_size} bytes",
                )]
                
            except Exception as e:
                return [TextContent(type="text", text=f"Error uploading attachment: {str(e)}")]

        elif name == "delete_attachment":
            attachment_id = arguments.get("attachment_id")
            
            if not attachment_id:
                return [TextContent(type="text", text="Error: 'attachment_id' is required")]
            
            try:
                result = await client.delete_attachment(attachment_id)
                
                return [TextContent(
                    type="text",
                    text=f"Attachment `{attachment_id}` deleted successfully.",
                )]
                
            except Exception as e:
                return [TextContent(type="text", text=f"Error deleting attachment: {str(e)}")]

        elif name == "get_my_permissions":
            try:
                permissions = await client.get_my_permissions()
                
                if not permissions:
                    return [TextContent(type="text", text="# My Permissions\n\nNo permissions found for the current user.")]
                
                # Group permissions by action
                by_action: dict[str, list[str]] = {}
                for perm in permissions:
                    action = perm.get("action", "unknown")
                    resource = perm.get("resource", "unknown")
                    if action not in by_action:
                        by_action[action] = []
                    by_action[action].append(resource)
                
                # Try to find current user's UID from the members list
                uid_line = ""
                try:
                    members = await client.search_members("")
                    # Find the member whose permissions match (look for the one with EDIT_ORG or most grants)
                    # Since we can't directly get our UID from the token, we include all members for reference
                    # The grant_permission tool resolves usernames to UUIDs automatically
                except Exception:
                    pass
                
                lines = ["# My Permissions", "", f"Total: {len(permissions)} permissions", ""]
                
                for action in sorted(by_action.keys()):
                    resources = by_action[action]
                    lines.append(f"## {action}")
                    for resource in sorted(resources):
                        lines.append(f"- `{resource}`")
                    lines.append("")
                
                return [TextContent(type="text", text="\n".join(lines))]
                
            except Exception as e:
                return [TextContent(type="text", text=f"Error getting permissions: {str(e)}")]

        elif name == "grant_permission":
            try:
                user_input = arguments["user_id"]
                action = arguments["action"]
                resource = arguments["resource"]
                # Resolve username to UUID if needed
                user_id = await client.resolve_user_id(user_input)
                result = await client.grant_permission(user_id, action, resource)
                msg = result.get("message", "Permission granted successfully")
                resolved_note = f" (resolved from '{user_input}')" if user_id != user_input else ""
                return [TextContent(type="text", text=f"Permission granted: {action} on {resource} to user {user_id}{resolved_note}\n\n{msg}")]
            except Exception as e:
                return [TextContent(type="text", text=f"Error granting permission: {str(e)}")]

        elif name == "revoke_permission":
            try:
                user_input = arguments["user_id"]
                action = arguments["action"]
                resource = arguments["resource"]
                # Resolve username to UUID if needed
                user_id = await client.resolve_user_id(user_input)
                result = await client.revoke_permission(user_id, action, resource)
                msg = result.get("message", "Permission revoked successfully")
                resolved_note = f" (resolved from '{user_input}')" if user_id != user_input else ""
                return [TextContent(type="text", text=f"Permission revoked: {action} on {resource} from user {user_id}{resolved_note}\n\n{msg}")]
            except Exception as e:
                return [TextContent(type="text", text=f"Error revoking permission: {str(e)}")]

        elif name == "check_permission":
            try:
                user_input = arguments["user_id"]
                action = arguments["action"]
                resource = arguments["resource"]
                # Resolve username to UUID if needed
                user_id = await client.resolve_user_id(user_input)
                has_permission = await client.check_permission(user_id, action, resource)
                status = "Yes" if has_permission else "No"
                return [TextContent(type="text", text=f"Permission check: {action} on {resource} for user {user_id}\n\nHas permission: **{status}**")]
            except Exception as e:
                return [TextContent(type="text", text=f"Error checking permission: {str(e)}")]

        elif name == "get_user_permissions":
            try:
                user_input = arguments["user_id"]
                user_id = await client.resolve_user_id(user_input)
                grants = await client.get_user_grants(user_id)
                
                if not grants:
                    return [TextContent(type="text", text=f"# Permissions for User {user_id}\n\nNo permission grants found.")]
                
                # Group by action
                by_action: dict[str, list[dict]] = {}
                for grant in grants:
                    action = grant.get("action", "unknown")
                    if action not in by_action:
                        by_action[action] = []
                    by_action[action].append(grant)
                
                lines = [f"# Permissions for User {user_id}", "", f"Total: {len(grants)} grants", ""]
                
                for action in sorted(by_action.keys()):
                    action_grants = by_action[action]
                    lines.append(f"## {action}")
                    for g in action_grants:
                        resource = g.get("resource", "unknown")
                        granted_by = g.get("grantedBy", "unknown")
                        granted_at = (g.get("grantedAt", "") or "")[:10]
                        lines.append(f"- `{resource}` (granted by {granted_by} on {granted_at})")
                    lines.append("")
                
                return [TextContent(type="text", text="\n".join(lines))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error getting user permissions: {str(e)}")]

        elif name == "list_all_permission_grants":
            try:
                grants = await client.get_all_grants()
                
                if not grants:
                    return [TextContent(type="text", text="# All Permission Grants\n\nNo grants found in the organization.")]
                
                # Group by user
                by_user: dict[str, list[dict]] = {}
                for grant in grants:
                    uid = grant.get("userId", "unknown")
                    if uid not in by_user:
                        by_user[uid] = []
                    by_user[uid].append(grant)
                
                lines = ["# All Permission Grants", "", f"Total: {len(grants)} grants across {len(by_user)} users", ""]
                
                for uid in sorted(by_user.keys()):
                    user_grants = by_user[uid]
                    lines.append(f"## User: {uid}")
                    for g in sorted(user_grants, key=lambda x: x.get("action", "")):
                        action = g.get("action", "unknown")
                        resource = g.get("resource", "unknown")
                        lines.append(f"- {action} on `{resource}`")
                    lines.append("")
                
                return [TextContent(type="text", text="\n".join(lines))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error listing grants: {str(e)}")]

        elif name == "list_available_permissions":
            try:
                available = await client.get_available_permissions()
                
                lines = ["# Available Permissions", ""]
                
                # Process each category
                skip_keys = {"resourceTypes"}
                for category, perms in available.items():
                    if category in skip_keys:
                        continue
                    if not isinstance(perms, list):
                        continue
                    lines.append(f"## {category.replace('_', ' ').title()}")
                    for p in perms:
                        action = p.get("action", "unknown")
                        desc = p.get("description", "")
                        lines.append(f"- **{action}**: {desc}")
                    lines.append("")
                
                # Resource types
                resource_types = available.get("resourceTypes", {})
                if resource_types:
                    lines.append("## Resource Types")
                    for rt_name, rt_info in resource_types.items():
                        pattern = rt_info.get("pattern", "")
                        desc = rt_info.get("description", "")
                        lines.append(f"- **{rt_name}**: `{pattern}` - {desc}")
                    lines.append("")
                
                return [TextContent(type="text", text="\n".join(lines))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error listing available permissions: {str(e)}")]

        elif name == "execute_query":
            query = arguments.get("query", "").strip()
            if not query:
                return [TextContent(type="text", text="Error: 'query' is required")]

            try:
                result = await client.execute_query(query)

                total = result.get("totalSourceTickets", 0)
                succeeded = result.get("succeeded", 0)
                failed = result.get("failed", 0)
                updates = result.get("updates", {})
                creates = result.get("creates", {})
                links = result.get("links", {})
                errors = result.get("errors", [])
                created_tickets = result.get("createdTickets", [])
                job_status = result.get("status")

                lines = [
                    "# Execution Result",
                    "",
                ]
                if job_status and job_status != "completed":
                    lines.append(f"**Job status:** {job_status}")
                    lines.append("")
                lines.extend(
                    [
                        f"**Source tickets processed:** {total}",
                        f"**Succeeded:** {succeeded}  |  **Failed:** {failed}",
                        "",
                    ]
                )
                if result.get("error"):
                    lines.append(f"**Error:** {result['error']}")
                    lines.append("")

                # Operation breakdown
                ops_lines = []
                if updates.get("succeeded", 0) or updates.get("failed", 0):
                    ops_lines.append(f"- Updates: {updates.get('succeeded', 0)} succeeded, {updates.get('failed', 0)} failed")
                if creates.get("succeeded", 0) or creates.get("failed", 0):
                    ops_lines.append(f"- Creates: {creates.get('succeeded', 0)} succeeded, {creates.get('failed', 0)} failed")
                if links.get("succeeded", 0) or links.get("failed", 0):
                    ops_lines.append(f"- Links: {links.get('succeeded', 0)} succeeded, {links.get('failed', 0)} failed")
                if ops_lines:
                    lines.append("**Operations:**")
                    lines.extend(ops_lines)
                    lines.append("")

                # Created tickets
                if created_tickets:
                    lines.append(f"**Created tickets:** {', '.join(created_tickets)}")
                    lines.append("")

                # Errors
                if errors:
                    lines.append("**Errors:**")
                    for err in errors[:20]:  # Cap at 20
                        seq = err.get("sequenceNumber", "")
                        op = err.get("operation", "")
                        msg = err.get("error", "")
                        prefix = f"{seq} ({op})" if seq else op
                        lines.append(f"- {prefix}: {msg}")

                return [TextContent(type="text", text="\n".join(lines))]
            except Exception as e:
                error_msg = str(e)
                # Try to extract the API error message from httpx response
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_data = e.response.json()
                        error_msg = error_data.get("message", error_data.get("error", str(e)))
                    except Exception:
                        pass
                return [TextContent(type="text", text=f"Error executing query: {error_msg}")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


def create_app():
    """Create the Starlette ASGI app hosting the MCP server over HTTP + SSE."""
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    from mcp.server.sse import SseServerTransport
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    session_manager = StreamableHTTPSessionManager(app=server, json_response=False)

    async def handle_streamable_http(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        return Response()

    async def health(_request):
        return Response("ok", media_type="text/plain")

    @asynccontextmanager
    async def lifespan(_app):
        async with session_manager.run():
            logger.info("Pomavo MCP HTTP server started")
            yield

    return Starlette(
        routes=[
            Route("/health", endpoint=health),
            Mount("/mcp", app=handle_streamable_http),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
        lifespan=lifespan,
    )


def main():
    """Run the MCP server over HTTP (streamable) + SSE."""
    import uvicorn

    host = os.environ.get("POMAVO_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("POMAVO_MCP_PORT", "8000"))
    logger.info("Starting Pomavo MCP HTTP server on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


# Module-level ASGI app so it can be served via `uvicorn pomavo_mcp.server:app`
# (used by the Aspire uv/uvicorn host and the Docker entrypoint).
app = create_app()


if __name__ == "__main__":
    main()
