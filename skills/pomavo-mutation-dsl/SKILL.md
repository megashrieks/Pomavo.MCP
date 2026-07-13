---
name: pomavo-mutation-dsl
description: The Pomavo mutation DSL executed by the execute_query tool for bulk changes. Load this before writing an execute_query query to UPDATE (SET), CREATE tickets, LINK/UNLINK tickets, or add COMMENTs in bulk. Prerequisite: the pomavo-query-language skill (the leading filter uses that syntax).
---

# Pomavo Mutation DSL (execute_query)

Executed by the **`execute_query`** tool. Performs bulk operations: UPDATE tickets,
CREATE new tickets, LINK tickets together, UNLINK (remove) links, and add COMMENTs.

**IMPORTANT: This modifies data!** All operations go through the service layer and
respect permissions.

The leading `[filter]` reuses the **`pomavo-query-language`** skill (same operators,
fields, `@me`, date literals, `"Field With Spaces"`). Load that skill for filter syntax.

## Syntax

```
[filter] mutation_clause+ [LIMIT n]
```

Mutation clauses are composable — chain SET, CREATE, and LINK in any combination.
They execute in order, once per matched source ticket.

---

## 1. UPDATE (SET)

Update matched tickets' fields:

```
filter SET field = value [, field = value]*
```

Operators:
- `=`  set value
- `+=` append (multiselect/label fields)
- `-=` remove (multiselect/label fields)

Examples:
```
status = "Open" and Project = "POMAVO/app/testing" SET status = "In Progress"
Assignee = @me SET Priority = "High", Labels += "urgent"
status = "Stale" SET Assignee = null LIMIT 10
```

**Updatable fields:** status, and any custom field (Priority, Assignee, Title, Labels, etc.)
**NOT updatable:** sequence_number, created_at, updated_at, template, author, id

---

## 2. CREATE

Create a new ticket per matched source (or standalone without filter):

```
filter CREATE "TemplateName" (
  SET field = value [, field = value]*
  [LINK "link_type"]
  [LINK "link_type" TO (sub_filter)]
)
```

Field references from the source ticket use `$`:
- `$Title` — source ticket's Title field value
- `$Assignee` — source ticket's Assignee value
- `$sequence_number` — source ticket's sequence number
- `$"Due Date"` — quoted field ref for names with spaces
- `"Prefix: ${Title}"` — string interpolation

Standalone create (no filter, no `$` refs):
```
CREATE "Task" (SET Title = "New task", Priority = "Medium", Project = "2")
```

Filtered create with link:
```
template = "Bug Report" and Priority = "Critical"
  CREATE "SubTask" (
    SET Title = "Investigate: ${Title}", Assignee = $Assignee, Project = $Project
    LINK "is parent of"
  )
  LIMIT 20
```

Multiple creates:
```
template = "Epic" and status = "Approved"
  CREATE "Task" (SET Title = "Design: ${Title}" LINK "is parent of")
  CREATE "Task" (SET Title = "Implement: ${Title}" LINK "is parent of")
  CREATE "Task" (SET Title = "Test: ${Title}" LINK "is parent of")
```

---

## 3. LINK

Link matched tickets to targets found by a sub-filter:

```
filter LINK "link_type" TO (target_filter)
```

Example:
```
status = "Blocked" LINK "is blocked by" TO (Labels contains "infrastructure")
```

Inside CREATE blocks:
- `LINK "type"` (no TO) — links source ticket to new ticket
- `LINK "type" TO (filter)` — links new ticket to targets from filter

---

## 4. UNLINK

Remove links from matched tickets:

```
filter UNLINK "link_type"                    # remove all links of that type
filter UNLINK "link_type" FROM (sub_filter)  # remove links of that type to specific targets
filter UNLINK ALL                             # remove ALL links
```

Examples:
```
status = "Done" UNLINK "is blocked by" FROM (status = "Done")
status = "Closed" UNLINK "relates to"
status = "Archived" UNLINK ALL LIMIT 50
```

---

## 5. COMMENT

Add a plain-text comment to matched tickets:

```
filter COMMENT "comment text"
```

Examples:
```
status = "Done" COMMENT "This ticket has been archived"
template = "Bug" SET status = "Closed" COMMENT "Auto-closed by bulk operation"
```

---

## 6. Combining all

All clauses are composable:
```
template = "Bug Report" and Priority = "Critical" and status = "Open"
  SET status = "In Progress", Labels += "triaged"
  CREATE "SubTask" (
    SET Title = "Investigate: ${Title}", Assignee = $Assignee, Project = $Project
    LINK "is parent of"
  )
  LINK "relates to" TO (template = "Epic" and Project = $Project)
  LIMIT 50
```

---

## Filter syntax

Same as `search_tickets` — see the `pomavo-query-language` skill:
- `=`, `!=`, `<`, `<=`, `>`, `>=`, `contains`, `not contains`, `between`, `in`, `not in`
- `and`, `or`, `not`, parentheses for grouping
- `@me` for current user, `d'-7d'` for relative dates
- Field names with spaces: `"Due Date"`

## Response & safety

- **Response:** returns counts of succeeded/failed operations and error details per ticket.
- **Safety:** use `LIMIT` to cap how many tickets are affected. `SET` without a filter is rejected.

## Related MCP tools

- **`execute_query`** — the only tool that runs this DSL.
- **`link_tickets` / `unlink_tickets` / `add_comment` / `update_ticket` / `create_ticket`** —
  single-ticket equivalents; prefer those for one-off changes and this DSL for bulk operations.
- Prerequisite skill: **`pomavo-query-language`** (the `[filter]` prefix).
