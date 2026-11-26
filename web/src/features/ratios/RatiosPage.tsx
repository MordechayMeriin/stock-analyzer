import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, Minus, Table2 } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  api,
  type CheckResult,
  type Ratios,
  type RatioSeries,
  type RatioValue,
} from "@/api/client";
import { useMode } from "@/app/mode";
import { QueryView } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  currencySymbol,
  formatDelta,
  formatRatio,
  type RatioUnit,
} from "@/lib/format";
import { cn } from "@/lib/utils";

const TEMPLATE_HE: Record<string, string> = {
  industrial: "חברה תעשייתית",
  bank: "בנק",
  insurer: "חברת ביטוח",
};
const STATUS_HE: Record<RatioValue["status"], string> = {
  improved: "השתפר",
  deteriorated: "הורע",
  changed: "השתנה",
  stable: "יציב",
  na: "אין השוואה",
};

type CheckLabels = Record<string, string>;

/** Financial ratios: one year-over-year line chart per ratio, grouped (web-client spec: Ratios view). */
export function RatiosPage() {
  const { ticker = "" } = useParams();
  const { mode } = useMode();
  const [asOf, setAsOf] = useState("");
  const [asTable, setAsTable] = useState(false);
  const ratios = useQuery({
    queryKey: ["ratios", ticker, mode, asOf],
    queryFn: ({ signal }) =>
      api.ratios(ticker, mode, asOf || undefined, signal),
  });
  return (
    <section className="space-y-6" aria-labelledby="ratios-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 id="ratios-title" className="text-xl font-semibold">
            יחסים פיננסיים
          </h1>
          {ratios.data && (
            <p
              className="text-muted-foreground text-sm"
              data-testid="ratios-meta"
            >
              {TEMPLATE_HE[ratios.data.template] ?? ratios.data.template} · מטבע
              הדיווח: <bdi className="font-medium">{ratios.data.currency}</bdi>{" "}
              · נקודה חלולה{" "}
              <AlertTriangle
                className="inline size-3.5 text-[var(--status-warning)]"
                aria-hidden
              />{" "}
              = ביטחון נמוך
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            aria-pressed={asTable}
            onClick={() => setAsTable((t) => !t)}
            data-testid="table-toggle"
          >
            <Table2 aria-hidden /> {asTable ? "תצוגת גרפים" : "תצוגת טבלה"}
          </Button>
          <label className="flex items-center gap-2 text-sm">
            זמין עד תאריך
            <Input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="w-40"
              dir="ltr"
              data-testid="as-of"
            />
          </label>
        </div>
      </div>
      <QueryView
        query={ratios}
        isEmpty={(d) => d.years.length === 0}
        loadingLabel="מחשב יחסים…"
      >
        {(d) => {
          const checkLabels = labelsOf(d);
          return (
            <div className="space-y-8">
              {d.groups.map((g) => (
                <section
                  key={g.group}
                  aria-labelledby={`group-${g.group}`}
                  data-testid={`group-${g.group}`}
                >
                  <h2
                    id={`group-${g.group}`}
                    className="mb-3 text-lg font-semibold"
                  >
                    {g.label}
                  </h2>
                  {asTable ? (
                    <RatioTable
                      ratios={g.ratios}
                      years={d.years}
                      currency={d.currency}
                    />
                  ) : (
                    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                      {g.ratios.map((r) => (
                        <RatioCard
                          key={r.code}
                          ratio={r}
                          years={d.years}
                          currency={d.currency}
                          checkLabels={checkLabels}
                        />
                      ))}
                    </div>
                  )}
                </section>
              ))}
            </div>
          );
        }}
      </QueryView>
    </section>
  );
}

function labelsOf(d: Ratios): CheckLabels {
  const out: CheckLabels = {};
  for (const results of Object.values(d.checks))
    for (const c of results as CheckResult[]) out[c.id] = c.label_he;
  return out;
}

type Point = { fy: number; y: number | null; v: RatioValue };

/** Plot coordinates only; every number shown as text comes from the exact strings. */
function points(ratio: RatioSeries, years: number[]): Point[] {
  return [...years]
    .sort((a, b) => a - b)
    .map((fy) => {
      const v = ratio.values[String(fy)];
      const y =
        v?.value == null
          ? null
          : Number(v.value) * (ratio.unit === "percent" ? 100 : 1);
      return { fy, y, v };
    });
}

function RatioCard({
  ratio,
  years,
  currency,
  checkLabels,
}: {
  ratio: RatioSeries;
  years: number[];
  currency: string | null;
  checkLabels: CheckLabels;
}) {
  const latestYear = years[0];
  const latest = ratio.values[String(latestYear)];
  const unit = ratio.unit as RatioUnit;
  const plotted = points(ratio, years);
  const scale = niceScale(plotted.map((p) => p.y));
  // `hover` is an invisible series at the bottom of the axis: Recharts hides the tooltip when the hovered
  // year has no value, and a missing year must still show why it is missing (web-client spec: Gaps).
  const data = plotted.map((p) => ({ ...p, hover: scale?.domain[0] ?? 0 }));
  return (
    <Card className="gap-3 py-4" data-testid={`ratio-${ratio.code}`}>
      <CardHeader className="gap-1 px-4">
        <CardTitle className="text-sm font-medium">{ratio.name_he}</CardTitle>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span
            className="text-2xl font-semibold tabular-nums"
            data-testid="latest-value"
          >
            <bdi dir="ltr">{formatRatio(latest?.value, unit, currency)}</bdi>
          </span>
          <span className="text-muted-foreground text-xs">
            <bdi>FY{latestYear}</bdi>
          </span>
          {latest && <ChangeBadge value={latest} unit={unit} />}
          {latest?.value != null && latest.confidence === "low" && (
            <Badge
              variant="outline"
              className="gap-1 text-[11px]"
              data-testid="low-confidence-badge"
            >
              <AlertTriangle
                className="size-3 text-[var(--status-warning)]"
                aria-hidden
              />{" "}
              ביטחון נמוך
            </Badge>
          )}
        </div>
        {latest?.value == null && latest?.missing_message_he && (
          <p className="text-muted-foreground text-xs">
            {latest.missing_message_he}
          </p>
        )}
      </CardHeader>
      <CardContent className="px-2">
        {/* Years run left to right (oldest → newest) even in the RTL layout. */}
        {!scale ? (
          <p
            className="text-muted-foreground flex h-36 items-center justify-center rounded-md border border-dashed text-xs"
            data-testid="no-data"
          >
            אין נתונים לחישוב היחס בשנים המוצגות
          </p>
        ) : (
          <div dir="ltr" className="h-36" data-testid="ratio-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data}
                margin={{ top: 8, right: 12, bottom: 0, left: 4 }}
              >
                <CartesianGrid
                  vertical={false}
                  stroke="var(--chart-grid)"
                  strokeWidth={1}
                />
                <XAxis
                  dataKey="fy"
                  type="category"
                  padding={{ left: 14, right: 14 }}
                  tickLine={false}
                  axisLine={{ stroke: "var(--chart-grid)" }}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                />
                <YAxis
                  width={48}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  tickFormatter={(n: number) => axisTick(n, unit)}
                  domain={scale.domain}
                  ticks={scale.ticks}
                  interval={0}
                />
                <Tooltip
                  cursor={{ stroke: "var(--muted-foreground)", strokeWidth: 1 }}
                  // By the hovered year, not the payload: Recharts drops null values from the payload, and a
                  // missing year must still explain why it is missing (web-client spec: Gaps).
                  content={({ active, label }) => {
                    const point = data.find(
                      (p) => String(p.fy) === String(label),
                    );
                    return active && point ? (
                      <PointTooltip
                        point={point}
                        unit={unit}
                        currency={currency}
                        checkLabels={checkLabels}
                      />
                    ) : null;
                  }}
                />
                <Line
                  dataKey="hover"
                  stroke="none"
                  dot={false}
                  activeDot={false}
                  isAnimationActive={false}
                  legendType="none"
                />
                <Line
                  dataKey="y"
                  type="linear"
                  connectNulls={false}
                  stroke="var(--chart-series)"
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  isAnimationActive={false}
                  dot={(props) => (
                    <PointDot
                      key={`d-${props.index}`}
                      {...(props as DotProps)}
                    />
                  )}
                  activeDot={(props) => (
                    <PointDot
                      key={`a-${props.index}`}
                      {...(props as DotProps)}
                      active
                    />
                  )}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

type DotProps = {
  cx?: number;
  cy?: number;
  payload?: Point;
  index?: number;
  active?: boolean;
};

/** Filled dot with a surface ring; low confidence = hollow with a warning-colored ring. No dot for a gap. */
function PointDot({ cx, cy, payload, active }: DotProps) {
  if (cx == null || cy == null || !payload || payload.y == null) return null;
  const low = payload.v.confidence === "low";
  return (
    <circle
      cx={cx}
      cy={cy}
      r={active ? 5.5 : 4.5}
      fill={low ? "var(--chart-surface)" : "var(--chart-series)"}
      stroke={low ? "var(--status-warning)" : "var(--chart-surface)"}
      strokeWidth={2}
      data-fy={payload.fy}
      data-low={low ? "true" : "false"}
      data-testid={active ? undefined : "point"}
    />
  );
}

/** Round y-axis ticks (steps of 1, 2, 2.5 or 5 × 10^k, about four ticks) spanning the plotted values. */
function niceScale(
  values: (number | null)[],
): { domain: [number, number]; ticks: number[] } | undefined {
  const vs = values.filter(
    (v): v is number => v !== null && Number.isFinite(v),
  );
  if (!vs.length) return undefined;
  let min = Math.min(...vs);
  let max = Math.max(...vs);
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const rough = (max - min) / 3;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  const step =
    (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) *
    mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step)
    ticks.push(Number(t.toFixed(10)));
  return { domain: [ticks[0], ticks[ticks.length - 1]], ticks };
}

function axisTick(n: number, unit: RatioUnit): string {
  if (unit === "percent") return `${Number(n.toFixed(2))}%`;
  if (unit === "amount")
    return Intl.NumberFormat("en", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(n);
  return String(Number(n.toFixed(2)));
}

function PointTooltip({
  point,
  unit,
  currency,
  checkLabels,
}: {
  point: Point;
  unit: RatioUnit;
  currency: string | null;
  checkLabels: CheckLabels;
}) {
  const { v, fy } = point;
  return (
    <div
      dir="rtl"
      className="bg-popover text-popover-foreground max-w-64 rounded-md border p-2.5 text-xs shadow-md"
      data-testid="ratio-tooltip"
    >
      <div className="mb-1 font-semibold">
        <bdi>FY{fy}</bdi>
      </div>
      {v?.value == null ? (
        <p data-testid="missing-reason">
          {v?.missing_message_he ?? "אין נתון"}
        </p>
      ) : (
        <>
          <p className="text-sm font-medium tabular-nums">
            <bdi dir="ltr">{formatRatio(v.value, unit, currency)}</bdi>
          </p>
          {v.delta != null && (
            <p className="text-muted-foreground">
              שינוי מהשנה הקודמת:{" "}
              <bdi dir="ltr">{formatDelta(v.delta, unit)}</bdi> (
              {STATUS_HE[v.status]})
            </p>
          )}
          {v.avg_used && (
            <p className="text-muted-foreground">
              מחושב על ממוצע יתרות פתיחה וסגירה
            </p>
          )}
          {v.confidence === "low" && (
            <div
              className="mt-1.5 border-t pt-1.5"
              data-testid="low-confidence-details"
            >
              <p className="flex items-center gap-1 font-medium">
                <AlertTriangle
                  className="size-3.5 text-[var(--status-warning)]"
                  aria-hidden
                />{" "}
                ביטחון נמוך
              </p>
              {v.failed_checks.length > 0 && (
                <ul className="mt-0.5 list-inside list-disc">
                  {v.failed_checks.map((c) => {
                    const [id, year] = c.split(":");
                    return (
                      <li key={c}>
                        בדיקה <bdi>{id}</bdi> נכשלה{year ? ` (FY${year})` : ""}:{" "}
                        {checkLabels[id] ?? ""}
                      </li>
                    );
                  })}
                </ul>
              )}
              {v.derived_inputs.length > 0 && (
                <p className="mt-0.5">
                  נתונים מחושבים:{" "}
                  <bdi dir="ltr">{v.derived_inputs.join(", ")}</bdi>
                </p>
              )}
            </div>
          )}
          {v.notes.includes("non_annual_source") && (
            <p className="text-muted-foreground mt-1">
              מקור: דוח שאינו דוח שנתי
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** Status of the change from the year before: icon by direction of the move, color by status, and a word. */
function ChangeBadge({ value, unit }: { value: RatioValue; unit: RatioUnit }) {
  if (value.delta == null) return null;
  const Icon = value.delta.startsWith("-")
    ? ArrowDown
    : /^0(\.0*)?$/.test(value.delta)
      ? Minus
      : ArrowUp;
  const color =
    value.status === "improved"
      ? "text-[var(--status-good)]"
      : value.status === "deteriorated"
        ? "text-[var(--status-critical)]"
        : "text-muted-foreground";
  return (
    <span
      className="inline-flex items-center gap-1 text-xs"
      data-testid="change"
      data-status={value.status}
    >
      <Icon className={cn("size-3.5", color)} aria-hidden />
      <bdi dir="ltr" className="tabular-nums">
        {formatDelta(value.delta, unit)}
      </bdi>
      <span className="text-muted-foreground">· {STATUS_HE[value.status]}</span>
    </span>
  );
}

/** The accessible table view: every ratio and year, with missing reasons and low-confidence marks. */
function RatioTable({
  ratios,
  years,
  currency,
}: {
  ratios: RatioSeries[];
  years: number[];
  currency: string | null;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[36rem] border-collapse text-sm">
        <thead>
          <tr className="border-b">
            <th scope="col" className="px-3 py-2 text-start font-medium">
              יחס
            </th>
            {years.map((y) => (
              <th
                key={y}
                scope="col"
                className="px-3 py-2 text-end font-medium"
              >
                <bdi>FY{y}</bdi>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ratios.map((r) => (
            <tr
              key={r.code}
              className="border-b last:border-0"
              data-code={r.code}
            >
              <th scope="row" className="px-3 py-1.5 text-start font-normal">
                {r.name_he}
              </th>
              {years.map((y) => {
                const v = r.values[String(y)];
                return (
                  <td
                    key={y}
                    className="px-3 py-1.5 text-end tabular-nums"
                    title={v?.missing_message_he ?? undefined}
                  >
                    <bdi dir="ltr">
                      {formatRatio(v?.value, r.unit as RatioUnit, currency)}
                    </bdi>
                    {v?.value != null && v.confidence === "low" && (
                      <AlertTriangle
                        className="ms-1 inline size-3.5 text-[var(--status-warning)]"
                        aria-label="ביטחון נמוך"
                      />
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-muted-foreground px-3 py-2 text-xs">
        ערכים במטבע <bdi>{currencySymbol(currency)}</bdi> לפי היחידה;{" "}
        <AlertTriangle
          className="inline size-3 text-[var(--status-warning)]"
          aria-hidden
        />{" "}
        = ביטחון נמוך
      </p>
    </div>
  );
}
