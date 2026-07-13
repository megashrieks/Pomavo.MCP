"""HTTP client for the Pomavo API."""

import asyncio
import os
import re
import ssl
import time
import uuid
from typing import Any

import httpx

from .models import (
    AvailableTransition,
    CreateTicketRequest,
    FieldUpdate,
    FieldValue,
    Iteration,
    Project,
    SearchResult,
    Template,
    Ticket,
    UpdateTicketRequest,
)


async def _raise_for_status_hook(response: httpx.Response) -> None:
    """httpx event hook: on 4xx/5xx, attach the API failure body to the raised error.

    The Pomavo API returns errors in the shape `{ failure: { Code, Message, Data } }`
    (or sometimes a flat `{ message }` / `{ error }`). Surface that message instead of
    the generic ``Client error '400 Bad Request' for url ...`` text so MCP callers can
    see what actually went wrong (locked field, validation error, etc.).
    """
    if response.status_code < 400:
        return

    detail: str | None = None
    try:
        await response.aread()
        body = response.json()
    except Exception:
        body = None

    if isinstance(body, dict):
        failure = body.get("failure") or body.get("Failure")
        if isinstance(failure, dict):
            code = failure.get("Code") or failure.get("code")
            msg = failure.get("Message") or failure.get("message")
            data = failure.get("Data") or failure.get("data")
            parts = []
            if code:
                parts.append(str(code))
            if msg:
                parts.append(str(msg))
            if data:
                parts.append(f"data={data}")
            if parts:
                detail = ": ".join(parts) if len(parts) > 1 else parts[0]
        if detail is None:
            for key in ("message", "Message", "error", "Error", "title", "detail"):
                val = body.get(key)
                if isinstance(val, str) and val:
                    detail = val
                    break
    elif isinstance(body, str) and body:
        detail = body

    method = response.request.method if response.request is not None else "?"
    url = str(response.request.url) if response.request is not None else "?"
    base = f"HTTP {response.status_code} from {method} {url}"
    message = f"{base} — {detail}" if detail else base

    raise httpx.HTTPStatusError(message, request=response.request, response=response)


def normalize_markdown(text: str) -> str:
    """Normalize markdown text to match TipTap editor serialization.
    
    TipTap with @tiptap/extension-markdown serializes content with specific formatting:
    - Headings are always followed by a blank line
    - Trailing newline at end of document
    
    This ensures that markdown created via MCP matches what TipTap would produce,
    preventing false "changes detected" when viewing in the UI.
    
    Args:
        text: The markdown text to normalize
        
    Returns:
        Normalized markdown text
    """
    if not text:
        return text
    
    # Trim leading/trailing whitespace
    result = text.strip()
    
    # Ensure blank line after ALL headings (TipTap always adds this)
    # Match heading line followed by a single newline (not already a blank line)
    result = re.sub(r'(^#{1,6}\s+.+)\n(?!\n)', r'\1\n\n', result, flags=re.MULTILINE)
    
    # Ensure trailing newline
    if result and not result.endswith('\n'):
        result = result + '\n'
    
    return result


def transform_mentions_to_tiptap(text: str) -> str:
    """Transform plain @mentions to TipTap markdown format.
    
    Converts @username mentions to the TipTap shortcode format:
    @username -> [@ id="username" label="username"]
    
    TipTap uses the format [shortcode attr="value"] where shortcode is "@" for mentions.
    
    This allows mentions to be properly parsed by TipTap when the content
    is loaded in the rich text editor.
    
    Note: This only transforms mentions that are NOT already in TipTap format
    (i.e., not already [@ ...]).
    
    Args:
        text: The markdown text with plain @mentions
        
    Returns:
        Text with mentions converted to TipTap format
    """
    if not text:
        return text
    
    # Match @username that is NOT preceded by [ (already in TipTap format)
    # Username can contain letters, numbers, underscores, hyphens
    # Must be at word boundary (start of line, after space, or after punctuation)
    pattern = r'(?<!\[)(?<![a-zA-Z0-9])@([a-zA-Z][a-zA-Z0-9_-]*)'
    
    def replace_mention(match: re.Match) -> str:
        username = match.group(1)
        return f'[@ id="{username}" label="{username}"]'
    
    return re.sub(pattern, replace_mention, text)


def transform_ticket_refs_to_tiptap(text: str) -> str:
    """Transform plain #TICKET-123 references to TipTap markdown format.
    
    Converts #PREFIX-123 ticket references to the TipTap shortcode format:
    #BUG-123 -> [# sequenceNumber="BUG-123"]
    
    TipTap uses the format [shortcode attr="value"] where shortcode is "#" for ticket refs.
    
    This allows ticket references to be properly parsed by TipTap when the content
    is loaded in the rich text editor.
    
    Note: This only transforms references that are NOT already in TipTap format.
    
    Args:
        text: The markdown text with plain ticket references
        
    Returns:
        Text with ticket references converted to TipTap format
    """
    if not text:
        return text
    
    # Match #PREFIX-123 that is NOT preceded by [ (already in TipTap format)
    # Prefix is uppercase letters, number is digits
    pattern = r'(?<!\[)(?<![a-zA-Z0-9])#([A-Z]+-\d+)'
    
    def replace_ticket_ref(match: re.Match) -> str:
        sequence_number = match.group(1)
        return f'[# sequenceNumber="{sequence_number}"]'
    
    return re.sub(pattern, replace_ticket_ref, text)


def markdown_to_tiptap_json(text: str) -> str:
    """Convert markdown text to TipTap JSON document format.
    
    Produces a JSON string with the structure:
    {"type":"doc","content":[...nodes...]}
    
    Supports: paragraphs, headings (h1-h6), bold, italic, code spans,
    bullet lists, ordered lists, code blocks, blockquotes, horizontal rules,
    @mention shortcodes, and #ticket-ref shortcodes.
    
    Args:
        text: Markdown text (with TipTap shortcodes already applied)
        
    Returns:
        JSON string in TipTap document format
    """
    import json
    
    if not text or not text.strip():
        return json.dumps({"type": "doc", "content": [{"type": "paragraph", "attrs": {"textAlign": None}}]})
    
    # Normalize literal \n escape sequences to actual newlines
    # (MCP tool arguments may pass escaped newlines as literal backslash-n)
    normalized = text.replace('\\n', '\n')
    
    lines = normalized.split('\n')
    content: list[dict] = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Code block (fenced)
        if line.strip().startswith('```'):
            lang = line.strip()[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            node: dict = {"type": "codeBlock", "attrs": {"language": lang or None}, "content": [{"type": "text", "text": '\n'.join(code_lines)}]}
            content.append(node)
            continue
        
        # Heading
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            inline_nodes = _parse_inline(heading_match.group(2))
            content.append({"type": "heading", "attrs": {"textAlign": None, "level": level}, "content": inline_nodes})
            i += 1
            continue
        
        # Horizontal rule
        if re.match(r'^(-{3,}|\*{3,}|_{3,})\s*$', line.strip()):
            content.append({"type": "horizontalRule"})
            i += 1
            continue
        
        # Bullet list
        if re.match(r'^[-*+]\s', line.strip()):
            items = []
            while i < len(lines) and re.match(r'^[-*+]\s', lines[i].strip()):
                item_text = re.sub(r'^[-*+]\s+', '', lines[i].strip())
                inline_nodes = _parse_inline(item_text)
                items.append({"type": "listItem", "content": [{"type": "paragraph", "attrs": {"textAlign": None}, "content": inline_nodes}]})
                i += 1
            content.append({"type": "bulletList", "content": items})
            continue
        
        # Ordered list
        if re.match(r'^\d+\.\s', line.strip()):
            items = []
            while i < len(lines) and re.match(r'^\d+\.\s', lines[i].strip()):
                item_text = re.sub(r'^\d+\.\s+', '', lines[i].strip())
                inline_nodes = _parse_inline(item_text)
                items.append({"type": "listItem", "content": [{"type": "paragraph", "attrs": {"textAlign": None}, "content": inline_nodes}]})
                i += 1
            content.append({"type": "orderedList", "attrs": {"start": 1, "type": None}, "content": items})
            continue
        
        # Blockquote
        if line.strip().startswith('>'):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                quote_lines.append(re.sub(r'^>\s?', '', lines[i].strip()))
                i += 1
            quote_text = ' '.join(quote_lines)
            inline_nodes = _parse_inline(quote_text)
            content.append({"type": "blockquote", "content": [{"type": "paragraph", "attrs": {"textAlign": None}, "content": inline_nodes}]})
            continue
        
        # Table (markdown pipe tables)
        if '|' in line and re.match(r'^\s*\|', line.strip()):
            table_lines = []
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                table_lines.append(lines[i])
                i += 1
            if len(table_lines) >= 2:
                table_node = _parse_table(table_lines)
                if table_node:
                    content.append(table_node)
                    continue
            # If table parsing failed, fall through to paragraph handling
            # Reset i to re-process these lines
            i -= len(table_lines)
        
        # Empty line -> skip (paragraph breaks are handled by grouping)
        if not line.strip():
            i += 1
            continue
        
        # Regular paragraph
        inline_nodes = _parse_inline(line)
        if inline_nodes:
            content.append({"type": "paragraph", "attrs": {"textAlign": None}, "content": inline_nodes})
        else:
            content.append({"type": "paragraph", "attrs": {"textAlign": None}})
        i += 1
    
    if not content:
        content = [{"type": "paragraph", "attrs": {"textAlign": None}}]
    
    return json.dumps({"type": "doc", "content": content})


def _parse_table(table_lines: list[str]) -> dict | None:
    """Parse markdown pipe table lines into a TipTap table node.
    
    Expected format:
        | Header 1 | Header 2 |
        |---|---|
        | Cell 1 | Cell 2 |
    
    Returns a TipTap table node, or None if parsing fails.
    """
    def split_cells(line: str) -> list[str]:
        """Split a table row into cell contents, stripping outer pipes."""
        stripped = line.strip()
        if stripped.startswith('|'):
            stripped = stripped[1:]
        if stripped.endswith('|'):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split('|')]
    
    if len(table_lines) < 2:
        return None
    
    # Check if second line is the separator (---|---| pattern)
    separator_idx = None
    for idx, tl in enumerate(table_lines):
        if re.match(r'^\s*\|?\s*[-:]+[-|\s:]*$', tl.strip()):
            separator_idx = idx
            break
    
    rows: list[dict] = []
    
    for row_idx, row_line in enumerate(table_lines):
        # Skip separator line
        if row_idx == separator_idx:
            continue
        
        cells = split_cells(row_line)
        is_header = separator_idx is not None and row_idx < separator_idx
        
        cell_type = "tableHeader" if is_header else "tableCell"
        cell_nodes = []
        for cell_text in cells:
            inline = _parse_inline(cell_text) if cell_text else []
            cell_node: dict = {"type": cell_type, "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None}}
            if inline:
                cell_node["content"] = [{"type": "paragraph", "attrs": {"textAlign": None}, "content": inline}]
            else:
                cell_node["content"] = [{"type": "paragraph", "attrs": {"textAlign": None}}]
            cell_nodes.append(cell_node)
        
        if cell_nodes:
            rows.append({"type": "tableRow", "content": cell_nodes})
    
    if not rows:
        return None
    
    return {"type": "table", "content": rows}


def _parse_inline(text: str) -> list[dict]:
    """Parse inline markdown formatting into TipTap text nodes with marks.
    
    Handles: bold (**), italic (*/_), code (`), @mentions, #ticket-refs.
    """
    nodes: list[dict] = []
    
    # Regex to match inline elements in order of priority
    # @mention shortcode: [@ id="..." label="..."]
    # #ticket-ref shortcode: [# sequenceNumber="..."]
    # Bold: **text**
    # Italic: *text* or _text_
    # Code: `text`
    pattern = re.compile(
        r'(\[@\s+id="([^"]+)"\s+label="([^"]+)"\])'  # @mention
        r'|(\[#\s+sequenceNumber="([^"]+)"\])'         # #ticket-ref
        r'|(\*\*(.+?)\*\*)'                            # bold
        r'|(\*(.+?)\*)'                                 # italic
        r'|(`([^`]+)`)'                                 # inline code
    )
    
    pos = 0
    for m in pattern.finditer(text):
        # Add plain text before this match
        if m.start() > pos:
            plain = text[pos:m.start()]
            if plain:
                nodes.append({"type": "text", "text": plain})
        
        if m.group(1):
            # @mention -> mention node
            nodes.append({
                "type": "mention",
                "attrs": {"id": m.group(2), "label": m.group(3), "mentionSuggestionChar": "@", "image": None},
            })
        elif m.group(4):
            # #ticket-ref -> ticketReference node
            nodes.append({
                "type": "ticketReference",
                "attrs": {"sequenceNumber": m.group(5)},
            })
        elif m.group(6):
            # Bold
            nodes.append({"type": "text", "text": m.group(7), "marks": [{"type": "bold"}]})
        elif m.group(8):
            # Italic
            nodes.append({"type": "text", "text": m.group(9), "marks": [{"type": "italic"}]})
        elif m.group(10):
            # Inline code
            nodes.append({"type": "text", "text": m.group(11), "marks": [{"type": "code"}]})
        
        pos = m.end()
    
    # Remaining plain text
    if pos < len(text):
        remaining = text[pos:]
        if remaining:
            nodes.append({"type": "text", "text": remaining})
    
    return nodes


def prepare_rich_text(text: str) -> str:
    """Prepare text for storage as rich text content in TipTap JSON format.
    
    Converts markdown text to TipTap JSON document format:
    1. Transform @mentions to TipTap mention nodes
    2. Transform #ticket references to TipTap ticket reference nodes
    3. Convert markdown to TipTap JSON structure
    
    Args:
        text: The raw text to prepare
        
    Returns:
        TipTap JSON string ready for storage
    """
    if not text:
        return text
    
    result = transform_mentions_to_tiptap(text)
    result = transform_ticket_refs_to_tiptap(result)
    return markdown_to_tiptap_json(result)


class PomavoClient:
    """Client for interacting with the Pomavo API."""

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        org_short_name: str | None = None,
        verify_ssl: bool = True,
        host_header: str | None = None,
    ):
        """Initialize the Pomavo API client.

        Args:
            api_url: Base URL of the Pomavo API (default: POMAVO_API_URL env var)
            api_key: API key for authentication (default: POMAVO_API_KEY env var)
            org_short_name: Organization short name (default: POMAVO_ORG_SHORT_NAME env var)
            verify_ssl: Whether to verify SSL certificates (default: True)
            host_header: Optional override for the HTTP Host header on outgoing
                requests. Useful when reaching the API through a hostname the
                reverse proxy (nginx) doesn't recognize (e.g. host.docker.internal)
                so the caller can still route to the correct virtual host.
        """
        self.api_url = (api_url or os.environ.get("POMAVO_API_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("POMAVO_API_KEY", "")
        self.org_short_name = org_short_name or os.environ.get("POMAVO_ORG_SHORT_NAME", "")
        self.verify_ssl = verify_ssl
        self.host_header = host_header or os.environ.get("POMAVO_HOST_HEADER", "")

        if not self.api_url:
            raise ValueError("API URL is required (set POMAVO_API_URL or send X-Pomavo-Api-Url)")
        if not self.api_key:
            raise ValueError("API key is required (send it via the X-API-Key header)")
        if not self.org_short_name:
            raise ValueError("Organization short name is required (send it via the X-Org-Short-Name header)")

    def _get_headers(self) -> dict[str, str]:
        """Get the headers for API requests."""
        headers = {
            "X-API-Key": self.api_key,
            "X-Org-Short-Name": self.org_short_name,
            "Content-Type": "application/json",
        }
        if self.host_header:
            headers["Host"] = self.host_header
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        """Get an HTTP client with the appropriate configuration."""
        return httpx.AsyncClient(
            base_url=self.api_url,
            headers=self._get_headers(),
            verify=self.verify_ssl,
            timeout=30.0,
            event_hooks={"response": [_raise_for_status_hook]},
        )

    # Templates

    async def list_templates(self) -> list[Template]:
        """List all ticket templates."""
        async with self._get_client() as client:
            response = await client.get("/api/templates")
            response.raise_for_status()
            return [Template.model_validate(t) for t in response.json()]

    async def get_template(self, template_id: int) -> Template:
        """Get a template by ID."""
        async with self._get_client() as client:
            response = await client.get(f"/api/templates/{template_id}")
            response.raise_for_status()
            return Template.model_validate(response.json())

    async def get_template_by_name(self, name: str) -> Template | None:
        """Get a template by name (case-insensitive)."""
        templates = await self.list_templates()
        name_lower = name.lower()
        for template in templates:
            if template.name.lower() == name_lower:
                return template
        return None

    # Projects

    async def list_projects(self) -> list[Project]:
        """List all projects."""
        async with self._get_client() as client:
            response = await client.get("/api/projects")
            response.raise_for_status()
            return [Project.model_validate(p) for p in response.json()]

    async def get_project(self, project_id: int) -> Project:
        """Get a project by ID."""
        async with self._get_client() as client:
            response = await client.get(f"/api/projects/{project_id}")
            response.raise_for_status()
            return Project.model_validate(response.json())

    async def get_project_by_slug(self, slug: str) -> Project | None:
        """Get a project by slug path (e.g., 'PARENT/child')."""
        projects = await self.list_projects()
        slug_lower = slug.lower()
        for project in projects:
            if project.project_slug.lower() == slug_lower:
                return project
        return None

    async def create_project(
        self,
        parent_project_id: int,
        slug: str,
        name: str,
        description: str | None = None,
        use_case: str | None = None,
    ) -> Project:
        """Create a sub-project under an existing parent project."""
        payload = {
            "parentProjectId": parent_project_id,
            "slug": slug,
            "name": name,
            "description": description,
            "useCase": use_case,
        }
        async with self._get_client() as client:
            response = await client.post("/api/projects", json=payload)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "success" in data:
                data = data["success"]
            return Project.model_validate(data)

    # Iterations

    async def list_iterations(self, project_id: int) -> list[Iteration]:
        """List all iterations for a project."""
        async with self._get_client() as client:
            response = await client.get(f"/api/projects/{project_id}/iterations")
            response.raise_for_status()
            return [Iteration.model_validate(i) for i in response.json()]

    async def get_active_iteration(self, project_id: int) -> Iteration | None:
        """Get the active iteration for a project."""
        iterations = await self.list_iterations(project_id)
        for iteration in iterations:
            if iteration.is_active:
                return iteration
        return None

    async def create_iteration(
        self, project_id: int, custom_name: str | None = None
    ) -> Iteration:
        """Create a new sprint iteration for a project."""
        async with self._get_client() as client:
            response = await client.post(
                f"/api/projects/{project_id}/iterations",
                json={"customName": custom_name},
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "success" in data:
                data = data["success"]
            return Iteration.model_validate(data)

    async def create_backlog(self, project_id: int) -> Iteration:
        """Create the backlog iteration for a project."""
        async with self._get_client() as client:
            response = await client.post(f"/api/projects/{project_id}/iterations/backlog")
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "success" in data:
                data = data["success"]
            return Iteration.model_validate(data)

    # Reports

    async def create_report(
        self,
        project_id: int,
        name: str,
        layout_code: str,
        variables: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a report owned by a project. Returns the created report as a dict."""
        payload = {
            "projectId": project_id,
            "name": name,
            "layoutCode": layout_code,
            "variables": variables or [],
        }
        async with self._get_client() as client:
            response = await client.post("/api/reports", json=payload)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "success" in data:
                data = data["success"]
            return data

    async def list_reports(self, project_id: int) -> list[dict[str, Any]]:
        """List all reports configured for a project."""
        async with self._get_client() as client:
            response = await client.get(f"/api/reports/projects/{project_id}")
            response.raise_for_status()
            return response.json()

    async def get_report(self, report_id: int) -> dict[str, Any]:
        """Get a single report by id. Returns the report as a dict."""
        async with self._get_client() as client:
            response = await client.get(f"/api/reports/{report_id}")
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "success" in data:
                data = data["success"]
            return data

    async def update_report(
        self,
        report_id: int,
        name: str,
        layout_code: str,
        project_id: int = 0,
        variables: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Update a report's name, layout code, variables, and (optionally) owning project.

        Pass project_id=0 to leave the owning project unchanged. Returns the updated report.
        """
        payload = {
            "projectId": project_id,
            "name": name,
            "layoutCode": layout_code,
            "variables": variables or [],
        }
        async with self._get_client() as client:
            response = await client.put(f"/api/reports/{report_id}", json=payload)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "success" in data:
                data = data["success"]
            return data

    # Automations

    async def list_automations(self, project_id: int | None = None) -> list[dict[str, Any]]:
        """List automation rules, optionally scoped to a project."""
        params: dict[str, Any] = {}
        if project_id is not None:
            params["projectId"] = project_id
        async with self._get_client() as client:
            response = await client.get("/api/AutomationRules", params=params)
            response.raise_for_status()
            return response.json()

    async def create_automation(
        self,
        name: str,
        description: str | None = None,
        project_id: int | None = None,
        enabled: bool = False,
    ) -> dict[str, Any]:
        """Create an empty automation rule (no nodes yet). Returns the created rule."""
        payload = {
            "name": name,
            "description": description,
            "projectId": project_id,
            "enabled": enabled,
            "graph": {"nodes": [], "edges": []},
        }
        async with self._get_client() as client:
            response = await client.post("/api/AutomationRules", json=payload)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "success" in data:
                data = data["success"]
            return data

    async def get_automation_graph(self, automation_id: int) -> dict[str, Any]:
        """Get the alias-addressed, resolved view of an automation's graph."""
        async with self._get_client() as client:
            response = await client.get(f"/api/AutomationRules/{automation_id}/graph")
            response.raise_for_status()
            return response.json()

    async def search_node_types(
        self, query: str | None = None, category: str | None = None
    ) -> list[dict[str, Any]]:
        """Search the automation node-type catalog (concise results)."""
        params: dict[str, Any] = {}
        if query:
            params["query"] = query
        if category:
            params["category"] = category
        async with self._get_client() as client:
            response = await client.get("/api/AutomationRules/definitions/nodes", params=params)
            response.raise_for_status()
            return response.json()

    async def get_node_definition(self, node_type: str) -> dict[str, Any]:
        """Get the full definition (ports, config, docs) of a single node type."""
        async with self._get_client() as client:
            response = await client.get(f"/api/AutomationRules/definitions/nodes/{node_type}")
            response.raise_for_status()
            return response.json()

    async def get_type_definition(self, type_id: str) -> dict[str, Any]:
        """Get the full definition (properties) of a single automation type."""
        async with self._get_client() as client:
            response = await client.get(f"/api/AutomationRules/definitions/types/{type_id}")
            response.raise_for_status()
            return response.json()

    async def add_automation_node(
        self,
        automation_id: int,
        alias: str,
        node_type: str,
        config: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Add a node to an automation. Returns the fresh resolved graph view."""
        payload = {"alias": alias, "type": node_type, "config": config or {}}
        async with self._get_client() as client:
            response = await client.post(
                f"/api/AutomationRules/{automation_id}/nodes", json=payload
            )
            response.raise_for_status()
            return response.json()

    async def update_automation_node_config(
        self,
        automation_id: int,
        alias: str,
        config: dict[str, str],
        replace: bool = False,
    ) -> dict[str, Any]:
        """Update a node's config (merge by default). Returns the fresh resolved graph view."""
        payload = {"config": config, "replace": replace}
        async with self._get_client() as client:
            response = await client.patch(
                f"/api/AutomationRules/{automation_id}/nodes/{alias}", json=payload
            )
            response.raise_for_status()
            return response.json()

    async def remove_automation_node(self, automation_id: int, alias: str) -> dict[str, Any]:
        """Remove a node (and its edges). Returns the fresh resolved graph view."""
        async with self._get_client() as client:
            response = await client.delete(
                f"/api/AutomationRules/{automation_id}/nodes/{alias}"
            )
            response.raise_for_status()
            return response.json()

    async def connect_automation(
        self, automation_id: int, from_ref: str, to_ref: str
    ) -> dict[str, Any]:
        """Connect two node handles ('alias.handle'). Hard-rejects type mismatches."""
        payload = {"from": from_ref, "to": to_ref}
        async with self._get_client() as client:
            response = await client.post(
                f"/api/AutomationRules/{automation_id}/edges", json=payload
            )
            response.raise_for_status()
            return response.json()

    async def disconnect_automation(
        self, automation_id: int, from_ref: str, to_ref: str
    ) -> dict[str, Any]:
        """Remove a connection between two node handles ('alias.handle')."""
        payload = {"from": from_ref, "to": to_ref}
        async with self._get_client() as client:
            response = await client.request(
                "DELETE", f"/api/AutomationRules/{automation_id}/edges", json=payload
            )
            response.raise_for_status()
            return response.json()

    # Tickets

    async def get_ticket(self, ticket_id: int) -> Ticket:
        """Get a ticket by ID."""
        async with self._get_client() as client:
            response = await client.get(f"/api/tickets/{ticket_id}")
            response.raise_for_status()
            return Ticket.model_validate(response.json())

    async def get_ticket_by_sequence(self, sequence_number: str) -> Ticket:
        """Get a ticket by sequence number (e.g., 'BUG-123')."""
        async with self._get_client() as client:
            response = await client.get(f"/api/tickets/by-sequence/{sequence_number}")
            response.raise_for_status()
            return Ticket.model_validate(response.json())

    async def create_ticket(
        self,
        template_id: int,
        fields: dict[str, str],
        client_ticket_id: str | None = None,
    ) -> Ticket:
        """Create a new ticket.

        Args:
            template_id: ID of the template to use
            fields: Dictionary mapping field IDs to values
            client_ticket_id: Optional client-provided ID for idempotency

        Returns:
            The created ticket
        """
        if client_ticket_id is None:
            client_ticket_id = str(uuid.uuid4())

        request = CreateTicketRequest(
            clientTicketId=client_ticket_id,
            templateId=template_id,
            fields=[
                FieldValue(templateFieldId=field_id, value=value)
                for field_id, value in fields.items()
            ],
        )

        async with self._get_client() as client:
            response = await client.post(
                "/api/tickets",
                json=request.model_dump(by_alias=True),
            )
            response.raise_for_status()
            data = response.json()
            # API returns {success: {id, ...ticket}} - extract from wrapper
            if isinstance(data, dict) and "success" in data:
                data = data["success"]
            return Ticket.model_validate(data)

    async def update_ticket(
        self,
        ticket_id: int,
        fields: dict[str, str] | None = None,
        new_state_id: str | None = None,
    ) -> dict[str, Any]:
        """Update a ticket.

        Args:
            ticket_id: ID of the ticket to update
            fields: Dictionary mapping field IDs to values (uses templateFieldId for new fields)
            new_state_id: New workflow state ID

        Returns:
            Success/failure response
        """
        field_updates = None
        if fields:
            field_updates = [
                FieldUpdate(templateFieldId=field_id, value=value)
                for field_id, value in fields.items()
            ]

        request = UpdateTicketRequest(
            newStateId=new_state_id,
            fields=field_updates,
        )

        async with self._get_client() as client:
            response = await client.put(
                f"/api/tickets/{ticket_id}",
                json=request.model_dump(by_alias=True, exclude_none=True),
            )
            response.raise_for_status()
            return response.json()

    async def get_available_transitions(self, ticket_id: int) -> list[AvailableTransition]:
        """Get available state transitions for a ticket."""
        async with self._get_client() as client:
            response = await client.get(f"/api/tickets/{ticket_id}/transitions")
            response.raise_for_status()
            return [AvailableTransition.model_validate(t) for t in response.json()]

    # Search

    async def search_tickets(
        self,
        query: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> SearchResult:
        """Search for tickets.

        Args:
            query: Search query string
            page: Page number (1-indexed)
            page_size: Number of results per page

        Returns:
            Search results
        """
        params = {"page": page, "pageSize": page_size}
        if query:
            params["q"] = query

        async with self._get_client() as client:
            response = await client.get("/api/search", params=params)
            response.raise_for_status()
            return SearchResult.model_validate(response.json())

    # Execute (mutation queries)

    async def execute_query(self, query: str, preview: bool = False) -> dict:
        """Execute a mutation query (SET, CREATE, LINK operations).

        Preview runs synchronously and returns estimated counts. A real
        execution is dispatched as an asynchronous background job: the API
        responds with ``202 Accepted { jobId }`` and the mutation (plus any
        fan-out batch sub-jobs) runs in the Worker. This method polls the job
        status endpoint until the job completes and returns a normalized result
        dict with the final counts so callers see the actual outcome instead of
        the empty dispatch acknowledgement.

        Args:
            query: The mutation DSL query string.
            preview: If True, returns what would happen without executing.

        Returns:
            Mutation execution result dict with counts and errors.
        """
        async with self._get_client() as client:
            response = await client.post("/api/execute", json={"query": query, "preview": preview})
            data = response.json()

            # Preview mode returns a full MutationResult synchronously.
            if preview:
                return data

            # Real execution is asynchronous — poll the job to completion.
            job_id = data.get("jobId") or data.get("jobID") or data.get("id")
            if not job_id:
                # Fallback: a synchronous result body (older API) — return as-is.
                return data

            return await self._poll_execution(client, job_id)

    async def _poll_execution(self, client: httpx.AsyncClient, job_id: str, timeout: float = 180.0) -> dict:
        """Poll an async DSL mutation job until it completes, then normalize the
        status response into the flat result shape the formatting layer expects."""
        deadline = time.monotonic() + timeout
        delay = 0.5
        status_body: dict = {}

        while True:
            resp = await client.get(f"/api/execute/{job_id}/status")
            status_body = resp.json()
            status = status_body.get("status")
            if status in ("completed", "failed"):
                break
            if time.monotonic() >= deadline:
                status_body["status"] = status or "timeout"
                break
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 3.0)

        sub_jobs = status_body.get("subJobs") or {}
        aggregated = sub_jobs.get("aggregated") or {}

        errors: list[dict] = []
        for item in sub_jobs.get("items") or []:
            if item.get("status") == "failed":
                errors.append(
                    {
                        "sequenceNumber": item.get("title", ""),
                        "operation": "mutation",
                        "error": item.get("error", ""),
                    }
                )

        result: dict = {
            "jobId": job_id,
            "status": status_body.get("status"),
            "totalSourceTickets": aggregated.get("totalTickets", 0),
            "succeeded": aggregated.get("succeeded", 0),
            "failed": aggregated.get("failed", 0),
            "durationMs": aggregated.get("durationMs", 0),
            "throughputPerSec": aggregated.get("throughputPerSec", 0),
            "errors": errors,
        }
        if status_body.get("error"):
            result["error"] = status_body["error"]
        return result

    # Helper methods

    async def get_project_path(self, project: Project) -> str:
        """Get the full path of a project (e.g., 'PARENT/child')."""
        if project.parent_project_id is None:
            return project.project_slug

        projects = await self.list_projects()
        parent = next((p for p in projects if p.id == project.parent_project_id), None)
        if parent:
            parent_path = await self.get_project_path(parent)
            return f"{parent_path}/{project.project_slug}"
        return project.project_slug

    # History

    async def get_ticket_history(self, ticket_id: int) -> list[dict[str, Any]]:
        """Get the history/audit trail for a ticket."""
        async with self._get_client() as client:
            response = await client.get(f"/api/tickets/{ticket_id}/history")
            response.raise_for_status()
            return response.json()

    # Attachments

    async def get_ticket_attachments(self, client_ticket_id: str) -> list[dict[str, Any]]:
        """Get attachments for a ticket by its client ticket ID (GUID)."""
        async with self._get_client() as client:
            response = await client.get(f"/api/attachments/by-client-ticket/{client_ticket_id}")
            response.raise_for_status()
            return response.json()

    async def get_attachment_download_url(
        self, attachment_id: str, expiry_seconds: int | None = None
    ) -> dict[str, Any]:
        """Get a presigned download URL for an attachment.
        
        Args:
            attachment_id: The attachment ID (GUID)
            expiry_seconds: Optional presigned URL lifetime in seconds. When omitted,
                the server default is used. Clamped server-side to supported bounds.
            
        Returns:
            Dict with 'success' containing 'downloadUrl' or 'failure' with error info
        """
        params: dict[str, Any] = {}
        if expiry_seconds is not None:
            params["expirySeconds"] = expiry_seconds
        async with self._get_client() as client:
            response = await client.get(
                f"/api/attachments/{attachment_id}/download-url", params=params
            )
            response.raise_for_status()
            return response.json()

    async def download_attachment(self, attachment_id: str) -> bytes:
        """Download an attachment's content.
        
        First gets a presigned URL, then downloads the file content.
        
        Args:
            attachment_id: The attachment ID (GUID)
            
        Returns:
            The file content as bytes
        """
        # Get presigned download URL
        url_response = await self.get_attachment_download_url(attachment_id)
        
        if "failure" in url_response:
            raise ValueError(f"Failed to get download URL: {url_response['failure']}")
        
        download_url = url_response["success"]["downloadUrl"]
        
        # Download the file (no auth needed for presigned URL)
        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=60.0) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            return response.content

    async def delete_attachment(self, attachment_id: str) -> dict[str, Any]:
        """Delete an attachment by its ID.
        
        Args:
            attachment_id: The attachment ID (GUID)
            
        Returns:
            Dict with success/failure info
        """
        async with self._get_client() as client:
            response = await client.delete(f"/api/attachments/{attachment_id}")
            response.raise_for_status()
            return response.json()

    # Comments

    async def list_comments(self, ticket_id: int) -> list[dict[str, Any]]:
        """List all comments on a ticket."""
        async with self._get_client() as client:
            response = await client.get(f"/api/tickets/{ticket_id}/comments")
            response.raise_for_status()
            return response.json()

    async def add_comment(
        self,
        ticket_id: int,
        content: str,
        reply_to_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a comment to a ticket.

        Args:
            ticket_id: ID of the ticket
            content: Comment content
            reply_to_id: Optional parent comment ID for replies

        Returns:
            The created comment
        """
        payload: dict[str, Any] = {"content": content}
        if reply_to_id is not None:
            payload["repliedToId"] = reply_to_id

        async with self._get_client() as client:
            response = await client.post(
                f"/api/tickets/{ticket_id}/comments",
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def edit_comment(
        self,
        ticket_id: int,
        comment_id: int,
        content: str,
    ) -> dict[str, Any]:
        """Edit an existing comment.

        Args:
            ticket_id: ID of the ticket
            comment_id: ID of the comment to edit
            content: New comment content

        Returns:
            Success/failure response
        """
        async with self._get_client() as client:
            response = await client.put(
                f"/api/tickets/{ticket_id}/comments/{comment_id}",
                json={"content": content},
            )
            response.raise_for_status()
            return response.json()

    async def delete_comment(
        self,
        ticket_id: int,
        comment_id: int,
    ) -> dict[str, Any]:
        """Delete a comment.

        Args:
            ticket_id: ID of the ticket
            comment_id: ID of the comment to delete

        Returns:
            Success/failure response
        """
        async with self._get_client() as client:
            response = await client.delete(
                f"/api/tickets/{ticket_id}/comments/{comment_id}",
            )
            response.raise_for_status()
            return response.json()

    # Ticket Links

    async def list_links(self, ticket_id: int) -> list[dict[str, Any]]:
        """List all links for a ticket."""
        async with self._get_client() as client:
            response = await client.get(f"/api/tickets/{ticket_id}/links")
            response.raise_for_status()
            return response.json()

    async def list_link_types(self, ticket_id: int) -> list[dict[str, Any]]:
        """List available link types for a ticket."""
        async with self._get_client() as client:
            response = await client.get(f"/api/tickets/{ticket_id}/available-link-types")
            response.raise_for_status()
            return response.json()

    async def create_link(
        self,
        source_ticket_id: int,
        target_ticket_id: int,
        template_link_id: int,
    ) -> dict[str, Any]:
        """Create a link between two tickets.

        Args:
            source_ticket_id: ID of the source ticket
            target_ticket_id: ID of the target ticket
            template_link_id: ID of the link type template

        Returns:
            The created link
        """
        async with self._get_client() as client:
            response = await client.post(
                f"/api/tickets/{source_ticket_id}/links",
                json={
                    "templateLinkId": template_link_id,
                    "targetTicketId": target_ticket_id,
                },
            )
            response.raise_for_status()
            return response.json()

    async def delete_link(self, link_id: int) -> None:
        """Delete a ticket link.

        Args:
            link_id: ID of the link to delete
        """
        async with self._get_client() as client:
            response = await client.delete(f"/api/ticket-links/{link_id}")
            response.raise_for_status()

    # Attachment Upload

    async def get_upload_url(
        self,
        client_ticket_id: str,
        filename: str,
        content_type: str,
        file_size_bytes: int,
        is_manual: bool = True,
        attachment_id: str | None = None,
        expiry_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Get a presigned upload URL for an attachment.
        
        Args:
            client_ticket_id: The client ticket ID (GUID) 
            filename: Name of the file to upload
            content_type: MIME type of the file
            file_size_bytes: Size of the file in bytes
            is_manual: Whether this is a manual attachment (default: True)
            attachment_id: Optional client-provided attachment ID (GUID)
            expiry_seconds: Optional presigned URL lifetime in seconds. When omitted,
                the server default is used. Clamped server-side to supported bounds.
            
        Returns:
            Dict with 'success' containing upload URL info or 'failure' with error
        """
        payload: dict[str, Any] = {
            "clientTicketId": client_ticket_id,
            "fileName": filename,
            "contentType": content_type,
            "fileSizeBytes": file_size_bytes,
            "isManual": is_manual,
        }
        
        if attachment_id:
            payload["attachmentId"] = attachment_id
        if expiry_seconds is not None:
            payload["expirySeconds"] = expiry_seconds
        
        async with self._get_client() as client:
            response = await client.post("/api/attachments/upload-url", json=payload)
            response.raise_for_status()
            return response.json()

    async def upload_attachment(
        self,
        client_ticket_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        is_manual: bool = True,
    ) -> dict[str, Any]:
        """Upload an attachment to a ticket.
        
        Gets a presigned URL and uploads the file content.
        
        Args:
            client_ticket_id: The client ticket ID (GUID)
            filename: Name of the file to upload
            content: The file content as bytes
            content_type: MIME type of the file
            is_manual: Whether this is a manual attachment (default: True)
            
        Returns:
            Dict with attachment info including 'attachmentId', 'fileName', etc.
        """
        # Get presigned upload URL
        url_response = await self.get_upload_url(
            client_ticket_id=client_ticket_id,
            filename=filename,
            content_type=content_type,
            file_size_bytes=len(content),
            is_manual=is_manual,
        )
        
        if "failure" in url_response:
            return url_response
        
        upload_info = url_response["success"]
        upload_url = upload_info["uploadUrl"]
        attachment_id = upload_info["attachmentId"]
        
        # Upload the file to the presigned URL (no auth needed)
        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=60.0) as client:
            response = await client.put(
                upload_url,
                content=content,
                headers={"Content-Type": content_type},
            )
            response.raise_for_status()
        
        return {
            "success": {
                "attachmentId": attachment_id,
                "fileName": filename,
                "contentType": content_type,
                "fileSizeBytes": len(content),
            }
        }

    # Members

    async def search_members(self, search: str = "") -> list[dict]:
        """Search for members in the organization.
        
        Args:
            search: Optional search term (matches username, name, email)
            
        Returns:
            List of member objects with 'id', 'username', 'name', 'email', 'image', 'role'
        """
        async with self._get_client() as client:
            params = {}
            if search:
                params["search"] = search
            response = await client.get("/api/members", params=params)
            response.raise_for_status()
            return response.json()

    async def resolve_user_id(self, username_or_id: str) -> str:
        """Resolve a username to a user ID (UUID).
        
        If the input looks like a UUID (contains hyphens and is 36 chars), returns it as-is.
        Otherwise, searches members by username and returns the matching user's ID.
        
        Args:
            username_or_id: A username (e.g., 'testbot') or user ID (UUID)
            
        Returns:
            The user's UUID
            
        Raises:
            ValueError: If the username is not found
        """
        # If it looks like a UUID, return as-is
        if len(username_or_id) == 36 and '-' in username_or_id:
            return username_or_id
        
        # Search for the member by username
        members = await self.search_members(username_or_id)
        for member in members:
            if member.get("username", "").lower() == username_or_id.lower():
                return member["id"]
        
        raise ValueError(f"User '{username_or_id}' not found. Use a valid username or user ID (UUID).")

    async def get_current_user_id(self) -> str | None:
        """Get the current authenticated user's ID by searching members.
        
        Returns:
            The current user's UUID, or None if not found
        """
        # Get permissions to find some identifying information
        # The API key auth should resolve to a member entry
        members = await self.search_members("")
        # We can't directly get our own ID from the permissions API
        # but we can check the /api/members endpoint which returns all members
        # The MCP user should be one of them
        return None  # Caller should use resolve_user_id with known username

    # Permissions

    async def get_my_permissions(self) -> list[dict[str, str]]:
        """Get the current user's effective permissions.
        
        Returns:
            List of permission objects with 'action' and 'resource' fields
        """
        async with self._get_client() as client:
            response = await client.get("/api/permissions/me")
            response.raise_for_status()
            return response.json()

    async def grant_permission(self, user_id: str, action: str, resource: str) -> dict:
        """Grant a permission to a user.
        
        Args:
            user_id: The user ID to grant permission to
            action: The permission action (e.g., 'VIEW_ISSUE', 'EDIT_TICKET')
            resource: The resource scope (e.g., 'urn:pomavo:project:2')
            
        Returns:
            Response dict with success message
        """
        async with self._get_client() as client:
            response = await client.post("/api/permissions/grant", json={
                "userId": user_id,
                "action": action,
                "resource": resource,
            })
            response.raise_for_status()
            return response.json()

    async def revoke_permission(self, user_id: str, action: str, resource: str) -> dict:
        """Revoke a permission from a user.
        
        Args:
            user_id: The user ID to revoke permission from
            action: The permission action
            resource: The resource scope
            
        Returns:
            Response dict with success message
        """
        async with self._get_client() as client:
            response = await client.post("/api/permissions/revoke", json={
                "userId": user_id,
                "action": action,
                "resource": resource,
            })
            response.raise_for_status()
            return response.json()

    async def check_permission(self, user_id: str, action: str, resource: str) -> bool:
        """Check if a user has a specific permission.
        
        Args:
            user_id: The user ID to check
            action: The permission action
            resource: The resource scope
            
        Returns:
            True if the user has the permission, False otherwise
        """
        async with self._get_client() as client:
            response = await client.get("/api/permissions/check", params={
                "userId": user_id,
                "action": action,
                "resource": resource,
            })
            response.raise_for_status()
            return response.json()

    async def get_user_grants(self, user_id: str) -> list[dict]:
        """Get all permission grants for a specific user.
        
        Args:
            user_id: The user ID to get grants for
            
        Returns:
            List of grant objects with id, userId, action, resource, grantedBy, grantedAt
        """
        async with self._get_client() as client:
            response = await client.get(f"/api/permissions/user/{user_id}")
            response.raise_for_status()
            return response.json()

    async def get_all_grants(self) -> list[dict]:
        """Get all permission grants in the organization.
        
        Returns:
            List of all grant objects
        """
        async with self._get_client() as client:
            response = await client.get("/api/permissions")
            response.raise_for_status()
            return response.json()

    async def get_available_permissions(self) -> dict:
        """Get all available permission actions grouped by category.
        
        Returns:
            Dict with permission categories and resource types
        """
        async with self._get_client() as client:
            response = await client.get("/api/permissions/available")
            response.raise_for_status()
            return response.json()
