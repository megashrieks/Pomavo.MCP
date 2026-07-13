---
name: pomavo-report-layout
description: The Pomavo screen language (layout code) for building project reports with the create_report tool. Load this before writing a report's layout_code — covers the layout container/component tags, the shared chart x/y/series/color column contract, chart query aggregations, and the inline <Variable> parameter system. Chart queries use the pomavo-query-language skill.
---

# Pomavo Report Layout (screen language)

Reports are project-scoped, top-level dashboards of charts and tables built with the
Pomavo screen language (layout code) and backed by search-DSL queries. Created with the
**`create_report`** tool. The owning project scopes permissions — anyone with
`VIEW_REPORT` on that project can see it; creating requires `CREATE_REPORT`.

Use `list_projects` to find the numeric `project_id`.

## Layout code

JSX-like tags describing a 12-column grid.

- **Containers:** `<Row>`, `<Column>`, `<Section title="...">`. Row children share the
  12 columns via `width={n}`.
- **Report components** (LEAF tags, self-closing), each takes a required `query` attribute:
  `<RadialChart>`, `<BarChart>`, `<LineChart>`, `<AreaChart>`, `<PieChart>`,
  `<ScatterChart>`, `<Table>`. All charts use the same `x`/`y`/`series`/`color` column
  contract (below).
- **Component attributes:** `query="..."` (required), `width={1-12}`, `height={rows}`,
  `heightAutoExpand`, `title="..."`.
  - Cartesian charts (BarChart/LineChart/AreaChart/ScatterChart) also accept
    `xlabel="..."` and `ylabel="..."` for axis titles.
  - `<BarChart>` also accepts `variant="horizontal"` to render horizontal bars
    (default is vertical).
- **`<Text>...</Text>`** renders literal text between the tags. Add `renderer="markdown"`
  to render its content as rich markdown (headings, lists, tables, code, links), e.g.
  `<Text renderer="markdown"># Overview\nSee the charts below.</Text>`. Newlines and
  `${...}` inside `<Text>` are preserved verbatim (not interpolated).
- **NOTE:** `<Field>` and `<Label>` tags are NOT valid in reports and render a runtime error.

## Queries (chart data)

Each chart's `query` runs against tickets using the search DSL (see the
**`pomavo-query-language`** skill) with `GROUP BY` + `RETURN` aggregations appended to
produce chart data.

- **Aggregations:** `count()`, `sum(field)`, `avg(field)`, `min(field)`, `max(field)`,
  `count_distinct(field)`.
- **Standardized columns (ALL charts):** alias the independent dimension as `x` and the
  measure as `y`, e.g. `... group by priority return priority as x, count() as y`.
  Charts auto-detect whether `x` is categorical (labels) or continuous (numeric) and pick
  a band or numeric axis accordingly.
- **Multi-series** (LineChart / AreaChart / BarChart / ScatterChart): add a `series` column
  to plot one line/area/point-group per distinct series value, or stacked bar segments,
  e.g. `... group by day, assignee return day as x, assignee as series, count() as y`.
- **Scatter** (ScatterChart): plots one point per `x`/`y` pair; both axes are auto-detected,
  so `x` and `y` may be numeric or categorical, e.g.
  `... group by assignee return avg(effort) as x, count() as y, priority as series`.
- **Custom colors:** any chart may return an optional `color` column (any CSS color: hex,
  `rgb()`/`rgba()`/`hsl()`, or a named color) to override the palette per
  category/point/series, e.g.
  `... group by status, $"Status Color" return status as x, count() as y, $"Status Color" as color`.
- Example: `project=${project} and status_category != 'terminal' group by status return status as x, count() as y`
- Filters support field comparisons, `and`/`or`/`not`, date literals like `d'-7d'`, and `@mentions`.

## Variables

Report-level parameters interpolated into queries via `${name}`. Declare them INLINE in the
layout code using the self-closing `<Variable>` tag (single source of truth — the report
reads variables from the code):

```
<Variable name="project" type="text" default="root/app" />
<Variable name="priority" type="select" options={["low","medium","high"]} default="high" />
<Variable name="assignee" type="query" query="group by assignee return assignee as label" />
<Variable name="statuses" type="multiselect" options={["todo","inprogress","done"]} default={["todo","inprogress"]} />
```

- **Attributes:** `name` (required), `type="text"|"select"|"query"|"multiselect"`,
  `default="..."` (string for text/select; an array like `default={["todo","inprogress"]}`
  for multiselect), `options={["a","b"]}` (static select/multiselect options),
  `query="..."` (for `type=query` / dynamic select/multiselect options; the distinct
  first-column values populate the dropdown), `defaultQuery="..."` (multiselect only — a
  query whose returned values become the initial selection), `label="..."`, `width={1-12}`
  (grid units — how much horizontal space the inline control takes).
- `type="text"` renders an input; `select`/`query` render a single-choice dropdown;
  `multiselect` renders a multi-choice dropdown. A `<Variable>` renders INLINE as a control
  at its position in the layout (exactly like a field), so place it wherever you want it to appear.
- A multiselect interpolates as a comma-separated list of quoted DSL string literals, so it
  drops straight into an `in (...)` clause: with `statuses=["todo","inprogress"]`,
  `"status in (${statuses})"` becomes `"status in ('todo', 'inprogress')"`.
- Changing a variable's value re-runs every chart query that interpolates it, refreshing the
  whole report.

## Full example (layout_code)

```
<Variable name="project" type="text" default="root/app" />
<Variable name="priority" type="select" options={["critical","high","medium","low"]} default="high" />
<Row>
  <BarChart title="By status" query="project=${project} and priority=${priority} group by status return status as x, count() as y" width={6} />
  <RadialChart title="Open by priority" query="project=${project} and status_category != 'terminal' group by priority return priority as x, count() as y" width={6} />
</Row>
```

## Related MCP tools

- **`create_report`** — creates a report; `layout_code` is this screen language.
- **`list_projects`** — to find the numeric `project_id` that owns the report.
- Related skill: **`pomavo-query-language`** — chart and `<Variable>` queries use it.
