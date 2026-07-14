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
  `<ScatterChart>`, `<RadarChart>`, `<HeatmapChart>`, `<StatChart>`, `<Table>`. Most charts use
  the same `x`/`y`/`series`/`color` column contract (below); `<HeatmapChart>` uses `x`/`y`/`value`
  instead, and `<StatChart>` reads a single scalar (see below).
- **Component attributes:** `query="..."` (required), `width={1-12}`, `height={rows}`,
  `heightAutoExpand`, `title="..."`.
  - Cartesian charts (BarChart/LineChart/AreaChart/ScatterChart) also accept
    `xlabel="..."` and `ylabel="..."` for axis titles.
  - Date axes: when an axis value is a date it arrives as an epoch-millisecond number
    and shows as a large integer by default. Annotate the axis with `xformat` / `yformat`
    to render readable dates. Values: `date`, `datetime`, `time`, `month`, `year`. Example:
    `<LineChart query="'End Date' != '' group by 'End Date' return 'End Date' as x, count() as y" xformat="date" />`.
  - `<BarChart>` also accepts `variant="horizontal"` to render horizontal bars
    (default is vertical).
- **`<Text>...</Text>`** renders literal text between the tags. Add `renderer="markdown"`
  to render its content as rich markdown (headings, lists, tables, code, links), e.g.
  `<Text renderer="markdown"># Overview\nSee the charts below.</Text>`. Newlines and
  `${...}` inside `<Text>` are preserved verbatim (not interpolated).
- **`<GeoMap>`** renders data on a styled OSM map (see the GeoMap section below). Unlike the
  other components it is a CONTAINER holding a `<Region>` plus one or more geographic data
  layers, not a single self-closing chart.
- **NOTE:** `<Field>` and `<Label>` tags are NOT valid in reports and render a runtime error.

## Layout composition (don't just stack top-down)

A report does NOT have to be a single top-down column of `<Text>` then `<chart>` then
`<Text>`. That reads monotonously. Compose with `<Row>` / `<Column>` to place explanatory
text beside a chart:

```
<Row>
  <BarChart title="Throughput" query="group by iteration return iteration as x, count() as y" width={8} />
  <Column width={4}>
    <Text renderer="markdown">## Throughput\nCompleted tickets per iteration. Use this to spot dips in delivery.</Text>
  </Column>
</Row>
```

- **Column top-align trick:** a bare `<Text>` next to a tall chart in a `<Row>` centers
  vertically. Wrap the text in a `<Column>` to top-align it so it lines up with the top of
  the chart. Use `<Column>` whenever you want a cell's content anchored to the top.
- **Columnar layout — wrap EACH column in a `<Column>`:** when a `<Row>` splits into
  side-by-side columns, wrap every one of its cells in its own `<Column width={n}>` (not just
  one side). Row children are vertically centered by default, so mixing a bare leaf with a
  `<Column>` — or leaving cells unwrapped — misaligns their tops. Giving each side its own
  `<Column>` anchors all columns to the top so they line up correctly:

  ```
  <Row>
    <Column width={6}>
      <Text renderer="markdown">### Left\nNotes for the left side.</Text>
      <BarChart title="Left chart" query="..." />
    </Column>
    <Column width={6}>
      <Text renderer="markdown">### Right\nNotes for the right side.</Text>
      <LineChart title="Right chart" query="..." />
    </Column>
  </Row>
  ```
- **Prefer a compact columnar layout when each section has its own explanation/text.** When
  every chart comes with explicit descriptive text, put the text and its chart side by side in
  a `<Row>` (text in a `<Column>`, chart in the other) rather than stacking text-above-chart
  down the whole page. This is more compact and readable — do this unless told otherwise.
  **Alternate the description side** row to row: description on the LEFT for one section, on the
  RIGHT for the next, and so on. The alternation keeps the page from looking repetitive:

  ```
  <Row>
    <Column width={4}>
      <Text renderer="markdown">### Throughput\nCompleted tickets per iteration.</Text>
    </Column>
    <BarChart title="Throughput" query="..." width={8} />
  </Row>
  <Row>
    <LineChart title="Cycle time" query="..." width={8} />
    <Column width={4}>
      <Text renderer="markdown">### Cycle time\nDays from start to done.</Text>
    </Column>
  </Row>
  ```
- Vary the visual rhythm: alternate full-width charts, side-by-side rows, and text/chart
  splits so the page doesn't look like one long stack.

## Tables

- **Don't constrain the width of a `<Table>` (or its parent) when it has many columns.** A wide
  table needs room to lay out its columns; a small `width={n}` (or a narrow `<Column>`/`<Row>`
  parent) clips the columns. Give wide tables the full width (`width={12}`, and don't nest them
  in a narrow container) so nothing is cut off.
- **Prefer tables with few columns.** A table with a handful of columns is far easier to read
  than a very wide one. Return only the columns that matter (project a focused set in the
  query), and split unrelated data into separate small tables rather than one sprawling table.

## Use headers and markdown (avoid monotony)

Give each section a heading and use appropriate text sizes — a wall of same-size charts and
plain text looks flat. Prefer `<Text renderer="markdown">` and lean on markdown as much as
possible:

- `# Report Title`, `## Section`, `### Subsection` for a clear hierarchy.
- Bold, lists, tables, and short intro paragraphs to explain what each chart shows.
- A markdown header above a `<Row>` of related charts groups them visually.

```
<Text renderer="markdown"># Sprint Health</Text>
<Text renderer="markdown">## Delivery</Text>
<Row>
  <LineChart title="Burndown" query="..." width={6} />
  <BarChart title="Scope changes" query="..." width={6} />
</Row>
<Text renderer="markdown">## Quality</Text>
<Row>
  <RadialChart title="Open bugs by priority" query="..." width={6} />
  <Column width={6}>
    <Text renderer="markdown">### Notes\nBugs above **P2** must be triaged before release.</Text>
  </Column>
</Row>
```

## Styling text: colors & font size

`<Text>` inherits its color and size from the theme. To override, wrap it in the shared
`<Color>` / `<Font>` container tags (zero-DOM wrappers that tint/size their children via CSS
inheritance):

- **`<Color>` — font color.** Prefer THEME variables via `class="..."` so colors stay
  consistent with light/dark mode: `foreground`, `muted-foreground`, `primary`, `secondary`,
  `destructive`, `accent-foreground`, etc. For a one-off, use a raw color with
  `value="#rrggbb"` (or `rgb()/hsl()`). Provide exactly one source.
- **`<Font size="...">` — text size.** `size` is one of `xs`, `sm`, `base`, `lg`, `xl`,
  `2xl`, `3xl`, `4xl`, `5xl`.
- Both cascade to nested children, so you can nest them and wrap `<Text>` (or a whole
  `<Column>`/`<Row>` of text).

```
<Color class="muted-foreground">
  <Text renderer="markdown">Small print / caption under a chart.</Text>
</Color>

<Font size="2xl">
  <Color class="primary">
    <Text renderer="markdown">**Headline KPI**</Text>
  </Color>
</Font>

<Color value="#16a34a"><Text>On track</Text></Color>
```

Note: these style raw `<Text>`. Chart element colors are controlled separately by the query's
`color` column (see Queries), and markdown headings (`#`, `##`) already imply sizes — reach for
`<Font>`/`<Color>` when you need finer control or a non-heading emphasis.

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
- **Multi-series** (LineChart / AreaChart / BarChart / ScatterChart / RadarChart): add a
  `series` column to plot one line/area/point-group/ring per distinct series value, or stacked
  bar segments, e.g. `... group by day, assignee return day as x, assignee as series, count() as y`.
- **Scatter** (ScatterChart): plots one point per `x`/`y` pair; both axes are auto-detected,
  so `x` and `y` may be numeric or categorical, e.g.
  `... group by assignee return avg(effort) as x, count() as y, priority as series`.
- **Radar** (RadarChart): plots the `y` measure as radial distance around a ring of `x`
  categories (spider/web); an optional `series` column overlays multiple rings, e.g.
  `... group by priority return priority as x, count() as y`.
- **Heatmap** (HeatmapChart): shades an `x` (columns) × `y` (rows) grid by a `value` column —
  it takes `x`/`y`/`value` (NOT `y` as the measure) and has NO `series` column, e.g.
  `... group by assignee, status return assignee as x, status as y, count() as value`. By
  default cells are shaded by a value-scaled gradient; pass a component `threshold` attribute
  to color cells in discrete bands: a comma-separated list of `minValue:color` pairs where a
  cell takes the color of the highest threshold at or below its value. Colors may be hex/named
  or theme tokens (`chart-1`, `primary`, `destructive`); not comma-bearing `rgb()/hsl()`, e.g.
  `<HeatmapChart query="..." threshold="0:chart-2,5:chart-4,10:destructive" width={8} />`.
  Alternatively pass a `gradient` attribute — a comma-separated list of colors/theme tokens for
  a continuous scale (one color = alpha ramp, two or more = interpolated across the value range),
  e.g. `<HeatmapChart query="..." gradient="chart-1,chart-3,destructive" width={8} />`.
- **Stat** (StatChart): a single-value KPI card. The query should return ONE row; the displayed
  value comes from a `value`, `y`, `count`, or `total` column (in that order) or else the first
  column, e.g. `status_category != 'terminal' return count() as value`. Numeric values are
  locale-formatted; a `yformat` date keyword renders epoch-millisecond values as dates. An optional
  `label` attribute adds a caption under the value, e.g.
  `<StatChart title="Open tickets" label="in progress" query="..." width={3} />`.
- **Custom colors:** any chart may return an optional `color` column (any CSS color: hex,
  `rgb()`/`rgba()`/`hsl()`, or a named color) to override the palette per
  category/point/series. To color each status bucket by its own workflow-state color, group by
  the system `status_color` field and return it as `color`, e.g.
  `... group by status, status_color return status as x, count() as y, status_color as color`.
  (`status_color` is a built-in system field — do NOT write it as a `$"..."` custom field.)
- Example: `project='${project}' and status_category != 'terminal' group by status return status as x, count() as y`
- Filters support field comparisons, `and`/`or`/`not`, date literals like `d'-7d'`, and `@mentions`.
- **Quoting inside `query="..."`:** the query lives inside a double-quoted attribute, so
  never escape inner double quotes (`\"` is invalid and won't parse). Use single quotes
  `'...'` for both string values and field names with spaces — single quotes work
  everywhere in the DSL. Example:
  `query="status_category != 'terminal' and 'End Date' != '' group by 'End Date', Priority return 'End Date' as x, Priority as series, count() as y"`

## GeoMap (geographic charts)

`<GeoMap>` plots ticket data on a styled OpenStreetMap-derived basemap (MapLibre GL). Unlike
the other charts it is a **container**: it holds one `<Region>` (the map extent) plus one or
more geographic **data layers**. All children are self-closing leaves — the composition is
expressed through tags + attributes, not nesting.

> **Coverage:** basemap and administrative join layers exist ONLY for **India** and the
> **United States**. Points/markers outside those two countries render on a blank basemap.
> Choropleth (polygon fill) is supported for `state`/`district`/`zip` (US) and
> `state`/`district`/`pin` (India). India PIN and any raw coordinates are point-only.

```
<GeoMap title="Tickets by state" width={12} height={8}>
  <Region by="country" country="india" />
  <Choropleth level="state" key="region" query="group by state return state as region, count() as value" gradient="chart-1,chart-3,destructive" />
</GeoMap>
```

### Container: `<GeoMap>`
Attributes: `title="..."`, `width={1-12}`, `height={rows}` (each row ≈ 60px; defaults to a
tall map). It fills its grid cell like any other chart.

### Extent: `<Region>` (required, frame only — draws nothing)
Controls what area the map frames to. Attributes:
- `by="lca"` — fit tightly to the plotted data (lowest common area; renders nothing extra).
  This is the default-style choice for coordinate layers.
- `by="country|state|district|zip|pin"` + `country="india|us"` — frame to that country's extent.
- `bbox="minLng,minLat,maxLng,maxLat"` — explicit extent (overrides auto-fit).

If no `<Region>` is given, the map auto-fits to the data (coordinate layers) or to the union of
the countries inferred from the choropleth join keys.

### Data layers (self-closing, each takes a `query`)
| Tag | Required query columns | Renders |
|-----|------------------------|---------|
| `<Points>` | `lat`, `lng` (+ optional `value`, `label`, `color`) | fixed-radius circles |
| `<Bubbles>` | `lat`, `lng`, `value` | circles scaled by `value` |
| `<Heat>` | `lat`, `lng` (+ optional `value` weight) | heatmap density |
| `<Categories>` | `lat`, `lng`, `series` (+ optional `color`) | circles colored per distinct `series` |
| `<Choropleth>` | `region` (join key) + `value` | admin polygon fill (color-scaled by `value`) |

Layer attributes:
- **Coordinate layers** (`Points`/`Bubbles`/`Heat`/`Categories`): `lat="..."` / `lng="..."`
  name the coordinate columns (default `lat` / `lng`); `radius={px}` sets the base marker size;
  `cluster` groups nearby points.
- **`<Choropleth>`**: `level="country|state|district|zip|pin"` picks the admin polygon set;
  `key="..."` names the query column holding the join key (default `region`); `country="..."`
  scopes framing. Color is scaled across the `value` range — use `gradient="..."` (comma-separated
  colors/theme tokens, interpolated) or `threshold="min:color,..."` (discrete bands), exactly like
  `<HeatmapChart>`.

Level aliases: `district` = `county`, `pin` = `pincode`. Use `state`/`district` for both
countries; `zip` for the US, `pin` for India.

### Column convention (geographic)
GeoMap queries follow a geo-specific column contract (NOT `x`/`y`):
- `region` — the admin join key for `<Choropleth>` (or a custom column named via `key`). Values
  must match the polygon keys: country ⇒ ISO-2 / name; state ⇒ ISO-3166-2 (`US-CA`, `IN-KA`) or
  name; district ⇒ id / GADM id / county FIPS; zip ⇒ ZCTA code; pin ⇒ PIN code.
- `value` — the measure (consistent with `<HeatmapChart>`), used for choropleth shading and
  bubble/heat magnitude.
- `lat` / `lng` — coordinates for point-based layers.
- `label` — optional tooltip text; `series` — the category for `<Categories>`; `color` —
  optional per-row CSS color override.

```
<GeoMap title="Field incidents" width={12} height={8}>
  <Region by="lca" />
  <Heat query="Latitude != '' group by Latitude, Longitude return Latitude as lat, Longitude as lng, count() as value" />
  <Points query="Priority='critical' and Latitude != '' return Latitude as lat, Longitude as lng, Title as label" radius={6} />
</GeoMap>
```

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
- **Quoting `${...}` interpolation (IMPORTANT):** a single-value variable (`text` / `select` /
  `query`) is substituted **raw and UNQUOTED** — `${assignee}` with value `john` becomes just
  `john`. So when you compare it against a string field you MUST wrap it in single quotes
  yourself: write `assignee='${assignee}'`, NOT `assignee=${assignee}` (the unquoted form is
  invalid DSL and the query fails to parse). This applies to every string comparison, e.g.
  `project='${project}'`, `priority='${priority}'`, `status='${status}'`.
- A `multiselect` is the exception: it interpolates as a comma-separated list of ALREADY-quoted
  DSL string literals, so it drops straight into an `in (...)` clause WITHOUT extra quotes —
  with `statuses=["todo","inprogress"]`, `"status in (${statuses})"` becomes
  `"status in ('todo', 'inprogress')"`. Do not add your own quotes around a multiselect.
- Changing a variable's value re-runs every chart query that interpolates it, refreshing the
  whole report.

## Full example (layout_code)

```
<Variable name="project" type="text" default="root/app" />
<Variable name="priority" type="select" options={["critical","high","medium","low"]} default="high" />
<Row>
  <BarChart title="By status" query="project='${project}' and priority='${priority}' group by status return status as x, count() as y" width={6} />
  <RadialChart title="Open by priority" query="project='${project}' and status_category != 'terminal' group by priority return priority as x, count() as y" width={6} />
</Row>
```

## Related MCP tools

- **`create_report`** — creates a NEW report; `layout_code` is this screen language.
- **`update_report`** — EDITS an existing report in place (change layout_code, name, variables,
  or move projects). Use this for changes instead of creating a new report each time; only the
  fields you pass are modified.
- **`list_reports`** — to find a report's numeric `report_id` for `update_report`.
- **`list_projects`** — to find the numeric `project_id` that owns the report.
- Related skill: **`pomavo-query-language`** — chart and `<Variable>` queries use it.
