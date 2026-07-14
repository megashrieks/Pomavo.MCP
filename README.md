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
| `pomavo-report-layout` | Report layout language: layout tags, chart components, `x/y/series/color` contract, `<Variable>` | `create_report`, `update_report`, `list_reports`, `get_report` |
| `pomavo-screen-layout` | Ticket template screen layout language: `Field`/`Label`/`Plugin`/`Row`/`Column`/`Section`/`Collapsible`/`Color`/`Font`/`Trigger`/`Text` | template screen `layout_code` |
| `pomavo-template` | Authoring ticket templates: mandatory fields (Title/Description/Author/Assignee), field types, screens, workflow, sequence config | `create_template`, `update_template` |
| `pomavo-workflow` | Authoring workflows: state categories (initial/default/terminal), the required `Created` state, transitions, granular editing | `create_workflow`, `add_workflow_state`, `add_workflow_transition` |
| `pomavo-screen` | Template screen types (create/issues/section/preview-*/card) and the create/update/delete screen tools | `create_screen`, `update_screen` |
| `pomavo-template-link` | Authoring relationship (link) types: name + outward/inward names | `create_template_link` |
| `pomavo-shared-fields` | Authoring shared org-level fields and attaching them to templates | `create_shared_field`, `add_shared_field_to_template` |
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
| `create_template` | Create a template (fields + screens + workflow) | `create_template name="Bug" ...` (load `pomavo-template`) |
| `update_template` | Edit name/description/icon/color | `update_template template_id=3 name="Bug"` |
| `update_template_workflow` | Point a template at another workflow | `update_template_workflow template_id=3 workflow_id=7` |
| `delete_template` | Soft-delete a template | `delete_template template_id=3` |

### Screens

| Tool | Description | Example |
|------|-------------|---------|
| `create_screen` | Add a screen to a template | `create_screen template_id=3 name="section" description="Details"` |
| `update_screen` | Edit one screen (by id or name) | `update_screen template_id=3 name="create" layout_code="..."` |
| `delete_screen` | Remove a screen | `delete_screen template_id=3 name="section"` |

### Workflows

| Tool | Description | Example |
|------|-------------|---------|
| `list_workflows` | List workflows | `list_workflows` |
| `get_workflow` | Get states + transitions | `get_workflow workflow_id=7` |
| `create_workflow` | Create a workflow | `create_workflow name="Flow" ...` (load `pomavo-workflow`) |
| `update_workflow` | Replace states/transitions in bulk | `update_workflow workflow_id=7 ...` |
| `delete_workflow` | Delete a workflow | `delete_workflow workflow_id=7` |
| `add_workflow_state` | Add one state | `add_workflow_state workflow_id=7 name="In Review" category="default" color="#3b82f6"` |
| `remove_workflow_state` | Remove one state (+ its transitions) | `remove_workflow_state workflow_id=7 name="In Review"` |
| `add_workflow_transition` | Add one transition | `add_workflow_transition workflow_id=7 name="Start" from_state_id="s1" to_state_id="s2"` |
| `remove_workflow_transition` | Remove one transition | `remove_workflow_transition workflow_id=7 name="Start"` |

### Template Links

| Tool | Description | Example |
|------|-------------|---------|
| `list_template_links` | List relationship types | `list_template_links` |
| `create_template_link` | Create a relationship type | `create_template_link name="Blocks" outward_name="blocks" inward_name="is blocked by"` |
| `update_template_link` | Edit a relationship type | `update_template_link link_id=4 name="Blocks" outward_name="blocks" inward_name="is blocked by"` |
| `delete_template_link` | Delete a relationship type | `delete_template_link link_id=4` |

### Shared Fields

| Tool | Description | Example |
|------|-------------|---------|
| `list_shared_fields` | List org-level shared fields | `list_shared_fields` |
| `create_shared_field` | Create a shared field | `create_shared_field label="Severity" field_type="dropdown"` |
| `update_shared_field` | Edit a shared field | `update_shared_field field_id="guid" label="Severity" field_type="dropdown"` |
| `delete_shared_field` | Delete a shared field (`force` to detach first) | `delete_shared_field field_id="guid" force=true` |
| `add_shared_field_to_template` | Attach to a template | `add_shared_field_to_template template_id=3 shared_field_id="guid"` |
| `remove_shared_field_from_template` | Detach from a template | `remove_shared_field_from_template template_id=3 shared_field_id="guid"` |

### Automations

| Tool | Description | Example |
|------|-------------|---------|
| `create_automation` | Create an empty rule | `create_automation name="Auto-assign"` |
| `add_node` / `set_node_config` / `remove_node` | Edit nodes (load `pomavo-automation`) | `add_node automation_id=1 alias="t1" node_type="trigger.ticket_created"` |
| `connect_nodes` / `disconnect_nodes` | Wire/unwire edges | `connect_nodes automation_id=1 from="t1.out" to="a1.in"` |
| `delete_automation` | Delete an entire rule | `delete_automation automation_id=1` |

### Reports

| Tool | Description | Example |
|------|-------------|---------|
| `list_reports` | List a project's reports | `list_reports project_id=2` |
| `get_report` | Get a report's layout + variables | `get_report report_id=5` |
| `create_report` | Create a project report | `create_report project_id=2 name="Sprint Health" layout_code="..."` |
| `update_report` | Edit an existing report | `update_report report_id=5 layout_code="..."` |

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
