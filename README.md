# Pomavo MCP Server

MCP (Model Context Protocol) server for interacting with the Pomavo ticket management system. This enables AI assistants like GitHub Copilot to manage tickets through natural language.

## Installation

```bash
cd Pomavo.MCP
uv sync
```

## Configuration

Set the following environment variables:

```bash
POMAVO_API_URL=https://localhost:7124
POMAVO_API_KEY=ck_your_api_key_here
POMAVO_ORG_SHORT_NAME=your_org_short_name
POMAVO_VERIFY_SSL=false  # Set to false for local development
```

Or create a `.env` file with these values.

## Usage

### Running the server

```bash
uv run pomavo-mcp
```

### VS Code Integration

Add to your VS Code MCP settings (`mcp.json`):

```json
{
  "servers": {
    "pomavo": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "C:/path/to/Pomavo.MCP", "run", "pomavo-mcp"],
      "env": {
        "POMAVO_API_URL": "https://localhost:7124",
        "POMAVO_API_KEY": "ck_your_api_key",
        "POMAVO_ORG_SHORT_NAME": "POMAVO",
        "POMAVO_VERIFY_SSL": "false"
      }
    }
  }
}
```

## Available Tools

### Skills (on-demand reference)

The DSL-heavy tools keep short descriptions and defer their full reference to a
**skill** — a `SKILL.md` file under [`skills/`](./skills). Load the relevant skill
before writing a query or report layout.

| Tool | Description | Example |
|------|-------------|---------|
| `load_skill` | Return a skill's full markdown reference | `load_skill name="pomavo-query-language"` |

| Skill | Covers | Referenced by |
|-------|--------|---------------|
| `pomavo-query-language` | Read/filter search DSL (operators, fields, `@me`, date literals, `in`/`not in`, `order by`) | `search_tickets`, `get_sprint_tickets`, `execute_query` filter, report queries |
| `pomavo-mutation-dsl` | Bulk mutations: `SET` / `CREATE` / `LINK` / `UNLINK` / `COMMENT` | `execute_query` |
| `pomavo-report-layout` | Report layout language: layout tags, chart components, `x/y/series/color` contract, `<Variable>` | `create_report`, `update_report` |
| `pomavo-screen-layout` | Ticket template screen layout language: `Field`/`Label`/`Plugin`/`Row`/`Column`/`Section`/`Collapsible`/`Color`/`Font`/`Trigger`/`Text` | template screen `layout_code` |
| `pomavo-automation` | Incremental automation authoring: node catalog by category, type system + assignability, stable aliases, `alias.handle` edges, dynamic (Extract Properties) outputs, trigger/cycle/validity rules | `create_automation`, `add_node`, `set_node_config`, `connect_nodes`, `validate_automation` |

Skills are plain `SKILL.md` files (YAML frontmatter + markdown body), so this folder
doubles as an importable skill source for Agent Studio.

### Ticket Management

| Tool | Description | Example |
|------|-------------|---------|
| `create_ticket` | Create a new ticket | `create_ticket template="Bug Report" title="Login fails" priority="high"` |
| `get_ticket` | Get ticket by ID or sequence | `get_ticket sequence_number="BUG-123"` |
| `update_ticket` | Update ticket fields | `update_ticket ticket="BUG-123" effort=3 priority="high"` |
| `search_tickets` | Search with DSL query | `search_tickets query='template = "Bug Report" and status != "Done"'` |

### State Transitions

| Tool | Description | Example |
|------|-------------|---------|
| `get_transitions` | List available transitions | `get_transitions ticket="BUG-123"` |
| `transition_ticket` | Change ticket state by name | `transition_ticket ticket="BUG-123" state="Done"` |

### Comments

| Tool | Description | Example |
|------|-------------|---------|
| `list_comments` | List all comments on a ticket | `list_comments ticket="BUG-123"` |
| `add_comment` | Add a comment | `add_comment ticket="BUG-123" content="Fixed in PR #42"` |
| `edit_comment` | Edit an existing comment | `edit_comment ticket="BUG-123" comment_id=15 content="Updated"` |
| `delete_comment` | Delete a comment | `delete_comment ticket="BUG-123" comment_id=15` |

### Ticket Linking

| Tool | Description | Example |
|------|-------------|---------|
| `list_links` | List all links for a ticket | `list_links ticket="BUG-123"` |
| `list_link_types` | List available link types | `list_link_types ticket="BUG-123"` |
| `link_tickets` | Create a link between tickets | `link_tickets source_ticket="EPIC-1" target_ticket="BUG-123" link_type_id=1` |
| `unlink_tickets` | Remove a link | `unlink_tickets link_id=42` |

### Projects & Iterations

| Tool | Description | Example |
|------|-------------|---------|
| `list_projects` | List all projects | `list_projects` |
| `get_project` | Get project details | `get_project slug="POMAVO/app"` |
| `list_iterations` | List sprints for a project | `list_iterations project_slug="app"` |
| `get_active_iteration` | Get active sprint | `get_active_iteration project_slug="app"` |

### Templates

| Tool | Description | Example |
|------|-------------|---------|
| `list_templates` | List all ticket templates | `list_templates` |
| `get_template` | Get template with fields | `get_template name="Bug Report"` |

## Search Query DSL

The `search_tickets` tool supports a powerful query language:

### Common Searches
```
# Find all bugs
template = "Bug Report"

# Find open bugs
template = "Bug Report" and status != "Done"

# Find high priority items
Priority = "high" or Priority = "critical"

# Find by title
Title contains "login"

# Find recent tickets
created_at >= d'-7d'
```

### Operators
- `=`, `!=` - Equality
- `<`, `<=`, `>`, `>=` - Comparison
- `contains`, `not contains` - Text search
- `and`, `or`, `not` - Logical operators

### Date Literals
- Absolute: `d'2025-01-15'`
- Relative: `d'today'`, `d'-7d'` (7 days ago), `d'+3d'` (3 days from now)

### Sorting
```
status = "Open" order by created_at desc
Priority = "high" order by updated_at desc
```

## Link Types

Common link types (use `list_link_types` to see all):

| ID | Name | Outward | Inward |
|----|------|---------|--------|
| 1 | Hierarchy | "is parent of" | "is child of" |
| 2 | Blocks | "blocks" | "is blocked by" |
| 3 | Duplicates | "duplicates" | "is duplicated by" |
