---
name: pomavo-query-language
description: The Pomavo search/filter DSL used to find tickets. Load this when writing a query for the search_tickets tool, when building the [filter] part of an execute_query mutation, or when writing chart/variable queries inside a report. Covers comparison and logical operators, built-in and custom fields, @mentions, date literals, in/not in, and ORDER BY sorting.
---

# Pomavo Query Language (search / filter DSL)

A custom DSL that is translated to Elasticsearch queries. It is the read/filter
language shared across the product:

- **`search_tickets`** — the entire `query` argument is this DSL.
- **`execute_query`** — the leading `[filter]` before a mutation clause is this DSL.
- **`create_report`** — every chart `query="..."` and every `<Variable query="...">`
  is this DSL (with `... group by ... return ...` aggregation appended; see the
  `pomavo-report-layout` skill).

## Quick starts

- Find all bugs: `template = "Bug Report"`
- Find open bugs: `template = "Bug Report" and status != "Done"`
- My open tickets: `Assignee = @me and status_category != "terminal"`
- Tickets in a sprint: `Iteration = "sprint-4"`
- Tickets in a project: `Project = "POMAVO/app"`
- Unassigned to-do: `Assignee = "" and status = "To Do"`
- Recent (last 7 days): `created_at >= d'-7d'`
- Overdue: `"Due Date" < d'today' and status_category != "terminal"`
- All completed: `status_category = "terminal"`

## Comparison operators

- `=` equals (case-insensitive): `status = "Open"`
- `!=` not equals: `status != "Closed"`
- `<`, `<=`, `>`, `>=`: `Priority >= 3`
- `contains` partial text: `Title contains "urgent"`
- `not contains`: `Title not contains "spam"`
- `between` (inclusive range): `created_at between d'2025-01-01' and d'2025-02-01'`
- `in` / `not in` (set membership): `status in ("Open", "In Progress")`
  - An empty set is allowed: `priority in ()` matches nothing.
  - `field in ('')` and `field = ''` are equivalent (both match blank/empty values).

## Logical operators

- `and`: `status = "Open" and Priority = "High"`
- `or`: `status = "Open" or status = "In Progress"`
- `not`: `not (status = "Closed")`
- Parentheses for grouping: `(status = "Open" or status = "In Progress") and Priority = "High"`

## Built-in fields

- `status` — workflow state name (To Do, In Progress, Testing, Done, Abandoned, ...)
- `sequence_number` (alias `sequencenumber`) — ticket number, e.g. `"BUG-00001"`
- `ticket_type` (aliases `tickettype`, `template`) — template name (Bug Report, Epic, Task, User Story, SubTask)
- `created_at` (aliases `createdat`, `created`) — creation timestamp
- `updated_at` (aliases `updatedat`, `updated`) — last-update timestamp
- `author` (aliases `created_by`, `createdby`) — creator username
- `Project` — project path, e.g. `"POMAVO/app"`
- `Iteration` — sprint/iteration name, e.g. `"sprint-4"`
- `status_category` (alias `statuscategory`) — workflow category: `"initial"` (not started),
  `"default"` (in progress), `"terminal"` (completed/abandoned). Prefer this over checking
  individual status names for done/not-done filtering.

## Custom fields

Use the field label directly: `Priority = "High"`, `Assignee = "john"`, `Title contains "bug"`.
Quote names with spaces: `"Due Date" = d'2025-01-15'`.

## Strings & quotes

Single quotes (`'...'`) and double quotes (`"..."`) are interchangeable — both work
for string **values** *and* for field **names** with spaces. Prefer single quotes so
a query stays valid when it is embedded inside a double-quoted attribute (see below):

- Value: `status_category != 'terminal'`, empty value: `"End Date" != ''`
- Field name with spaces: `'End Date' >= d'-7d'`, `group by 'End Date'`, `'End Date' as x`

**Embedding a query in a report layout attribute:** report chart/variable queries are
authored inside a double-quoted attribute, e.g. `query="..."`. Do **not** escape inner
double quotes (`\"` is not valid in a layout attribute and will fail to parse). Instead,
write the whole query with single quotes:

```
query="status_category != 'terminal' and 'End Date' != '' group by 'End Date', Priority return 'End Date' as x, Priority as series, count() as y"
```

## User mentions

- `@me` — the current logged-in user.
- `@username` — a specific user: `Assignee = @john`.

## Date literals (prefixed with `d`)

- Absolute: `d'2025-01-15'` or `d'2025-01-15T10:30:00'`
- Relative: `d'now'`, `d'today'`, `d'-7d'` (7 days ago), `d'+3d'` (3 days from now)
- Units: `y` (years), `m` (months), `w` (weeks), `d` (days), `h` (hours)
- Combined: `d'-2y3m4d'` (2 years, 3 months, 4 days ago)

## Sorting

- `order by field [ASC|DESC]`: `order by created_at desc`
- Multiple fields: `order by Priority desc, created_at asc`
- Numeric sorting: `order by Priority numeric desc`
- Custom order: `order by status custom("Todo", "In Progress", "Done") asc`

## Examples

- `status = "Open" and Priority = "High" order by created_at desc`
- `Assignee = @me and created_at >= d'-7d'`
- `Title contains "login" and status != "Closed"`
- `template = "Bug Report" and status = "Open"`
- `(status = "Open" or status = "In Progress") and Priority >= 3`

## Related MCP tools

- **`search_tickets`** — read-only search; `query` is this DSL end to end.
- **`get_sprint_tickets`** — convenience wrapper that applies this DSL under the hood.
- **`execute_query`** — its `[filter]` prefix is this DSL (see the `pomavo-mutation-dsl` skill for the mutation clauses).
- **`create_report`** — chart and `<Variable>` queries are this DSL plus `group by`/`return` (see the `pomavo-report-layout` skill).
