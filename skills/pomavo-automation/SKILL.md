---
name: pomavo-automation
description: Build Pomavo automation rules incrementally with the automation authoring tools (create_automation, add_node, set_node_config, connect_nodes, validate_automation, and the discovery tools). Load this before authoring or editing an automation — covers the node catalog by category, the type system + assignability, the stable-alias model, the 'alias.handle' edge syntax, dynamic (Extract Properties) outputs, and the trigger/cycle/validity rules. Node and condition queries use the pomavo-query-language skill.
---

# Pomavo Automation Authoring

How to build a Pomavo **automation rule** incrementally with the MCP automation
tools. An automation is a **directed graph** of typed nodes: a **trigger** fires it,
data flows along **edges** into **actions** and **conditions**. You build it one node
and one edge at a time — you never submit a whole graph at once.

The server is the source of truth for types and validity. Every edit returns the
**fully-resolved graph view**, and `connect_nodes` **hard-rejects** an edge whose
source type is not assignable to the target input, with a plain-English reason. Trust
those responses instead of guessing.

---

## The tools

Discovery (catalog — no automation needed):
- `search_node_types(query?, category?)` — find node types. Categories: `Triggers`,
  `Actions`, `Conditions`, `Data`, `Tools.Logical`, `Tools.Math`, `Tools.List`,
  `Schedulers`.
- `get_node_definition(node_type)` — a node type's inputs, outputs, config fields, docs.
- `get_type_definition(type_id)` — a type's kind + properties (for planning `data.extract`).

Building (operate on one automation):
- `create_automation(name, description?, project_id?, enabled?)` — new **empty** rule.
  Keep `enabled` false while building; enable it from the Automations UI once valid.
- `add_node(automation_id, alias, node_type, config?)` — add a node under an **alias you
  choose**.
- `set_node_config(automation_id, alias, config, replace?)` — merge (default) or replace
  a node's config. Keys are config **field ids** from `get_node_definition`.
- `remove_node(automation_id, alias)` — delete a node and every edge touching it.
- `connect_nodes(automation_id, from, to)` — wire `"srcAlias.outputHandle"` →
  `"tgtAlias.inputHandle"`. Type-checked and hard-rejected on mismatch.
- `disconnect_nodes(automation_id, from, to)` — remove one edge.

Inspection:
- `get_automation(automation_id)` — full alias-addressed resolved view + validity.
- `search_nodes(automation_id, query?)` — find nodes within a rule (recall aliases/handles).
- `validate_automation(automation_id)` — list every outstanding problem; call before enabling.

---

## Aliases and the `alias.handle` edge syntax

Nodes are addressed by a **stable alias** you assign in `add_node` — not by an internal
id. Pick short, meaningful, unique aliases (`trigger`, `is_bug`, `comment`, `assignee`).
The alias is persisted, so it stays valid across calls and after reloads.

Edges are always written as two `"alias.handle"` references:

```
connect_nodes(id, from="trigger.ticket", to="comment.ticket")
```

- `from` = a **source alias** + one of its **output** handle ids.
- `to` = a **target alias** + one of its **input** handle ids.

Get the exact handle ids from the resolved view (`get_automation`) or from
`get_node_definition`. Output/input handles are **live-resolved**, so a node with dynamic
ports (below) may expose handles that only appear after its inputs/config are set.

---

## The type system

Every port has a type. A connection is allowed only if the source type is **assignable**
to the target input type.

Primitives: `string`, `number`, `integer`, `boolean`, `date`, `void`, `any`.
Domain objects (complex): `ticket`, `user`, `iteration`, `project`, `state`, `comment`,
`field`, `workflow`, `template`, `link`, `link_type`.
Generic: `list<T>` (e.g. `list<ticket>`).

Assignability rules that matter:
- `integer` ↔ `number` are interchangeable.
- `any` connects to/from anything (its concrete type is only known at runtime).
- A complex object is assignable only to the **same** complex type (a `ticket` output
  cannot feed a `user` input).
- `list<T>` is assignable to `list<U>` when `T` is assignable to `U`.

Complex types have **named properties** (e.g. a `ticket` has `sequence_number`, `title`,
`status`, `assignee`, …). Use `get_type_definition("ticket")` to see them; those property
names are what an Extract Properties node exposes as outputs.

---

## Node catalog (by category)

Use `search_node_types` / `get_node_definition` for exact ports and config. This is the map.

**Triggers — `Triggers.Events`** (every rule needs exactly one entry point; most are triggers):
`trigger.ticket_created`, `trigger.ticket_transitioned`, `trigger.field_changed`,
`trigger.comment_added`, `trigger.comment_updated`, `trigger.comment_deleted`,
`trigger.link_created`, `trigger.link_deleted`, `trigger.attachment_created`,
`trigger.attachment_deleted`, `trigger.sprint_started`, `trigger.sprint_completed`,
`trigger.sprint_restarted`.

**Schedulers** (alternative entry points): `scheduler.recurring_cron` (cron),
`scheduler.run_after` (delay after another job).

**Actions — `Actions`**: `action.transition_ticket`, `action.add_comment`,
`action.change_field`, `action.move_to_iteration`, `action.close_sprint`,
`action.start_sprint`, `action.create_iteration`, `action.create_ticket`,
`action.clone_ticket`, `action.add_link`, `action.remove_link`, and locks:
`action.lock_field`, `action.lock_link`, `action.lock_attachment`,
`action.lock_status_transition`, `action.lock_comment_add`.

**Conditions — `Conditions`**: `dsl.condition` (evaluate a query DSL condition on a
ticket → boolean), `dsl.query` (run a query DSL → `list<ticket>`).

**Tools.Logical**: `tools.logical.and`, `tools.logical.or`, `tools.logical.not`,
`tools.logical.if_else` (routes on a boolean), `tools.logical.is_null`.

**Tools.Math**: `tools.math.add`, `tools.math.subtract`, `tools.math.multiply`,
`tools.math.divide`, `tools.math.increment`, `tools.math.decrement`.

**Tools.List**: `tools.list.for_each`, `tools.list.collect`, `tools.list.length`.

**Data — constants (`Data.Constants`)**: `data.constant.string`, `data.constant.number`,
`data.constant.boolean`, `data.constant.date`, `data.constant.time`,
`data.constant.datetime`, `data.constant.list`, `data.constant.tags`,
`data.constant.richtext`, `data.constant.interpolation` (text template with `${...}`).

**Data — pickers / lookups (`Data.Ticket` + `Data`)**: `data.template`,
`data.shared_field`, `data.user`, `data.workflow`, `data.workflow_state`,
`data.workflow_transition`, `data.template_fields`, `data.get_field`, `data.link_type`,
`data.ticket_links`, `data.ticket_comments`, `data.ticket_follows`,
`data.iteration_picker`, `data.project_picker`, `data.field_value`, `data.dynamic_list`.

**Data — transformers (`Data`)**: `data.compare` (two values → boolean),
`data.extract` (Extract Properties — outputs depend on the input's type), `debug.inspect`.

---

## Dynamic outputs (Extract Properties)

`data.extract` has **no fixed outputs** — it exposes one output per property of whatever
type is wired into its input. Wire the input first, then re-read `get_automation`: the new
property handles appear (e.g. feeding a `ticket` yields `.sequence_number`, `.title`,
`.status`, `.assignee`, …). Match them against `get_type_definition` for that type. Several
data/list nodes resolve their ports the same way, so always re-inspect after connecting.

---

## Validity rules

`validate_automation` (and the `errors` in every view) reports:
- **Missing trigger** — a rule needs exactly one entry point (a `trigger.*` or a
  `scheduler.*`).
- **Required input not connected** — a required input port with no incoming edge.
- **Type error on a port** — the resolver rejected a value's type.
- **Cycle** — the graph must be acyclic; edges flow one direction.
- **Unsupported node** — a node type the engine can't run.

`isValid` is true only when there are zero errors. Enable the rule (in the UI) only then.

---

## Workflow

1. `load_skill("pomavo-automation")` (this doc), then `search_node_types` /
   `get_node_definition` to learn the exact nodes you need.
2. `create_automation(name, project_id, enabled=false)` → note the returned id.
3. `add_node` each node with a clear alias, passing known config inline.
4. `connect_nodes` the edges as `"alias.handle"`. If one is rejected, read the reason —
   it names the produced vs. expected type — and fix the source/target or insert a
   converter/extract node.
5. After wiring nodes with dynamic ports, `get_automation` to see the freshly resolved
   handles.
6. `validate_automation`. Resolve every error.
7. Enable the rule from the Automations UI once `isValid` is true.

---

## Worked example

*"When a ticket is created, if it's a Bug, add a comment."*

```
create_automation(name="Comment on new bugs", project_id=2, enabled=false)   # -> id 41

add_node(41, alias="trigger",  node_type="trigger.ticket_created")
add_node(41, alias="is_bug",   node_type="dsl.condition",
         config={"query": "template = 'Bug'"})
add_node(41, alias="gate",     node_type="tools.logical.if_else")
add_node(41, alias="comment",  node_type="action.add_comment",
         config={"body": "New bug filed — please triage."})

connect_nodes(41, from="trigger.ticket",   to="is_bug.ticket")
connect_nodes(41, from="is_bug.result",    to="gate.condition")
connect_nodes(41, from="trigger.ticket",   to="comment.ticket")
connect_nodes(41, from="gate.true",        to="comment.run")   # control edge

validate_automation(41)   # expect isValid: true
```

(Handle ids like `ticket`, `result`, `condition`, `true`, `run`, `body` come from
`get_node_definition` / the resolved view — confirm them there rather than assuming.)

If `connect_nodes(41, from="is_bug.result", to="comment.ticket")` were attempted, it is
rejected: *"Type mismatch: 'is_bug.result' produces boolean, which is not assignable to
'comment.ticket' (expects ticket)."* That is the intended, self-correcting behavior.
