import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ProductForecast } from "../api/brainTypes";
import { CHART } from "../theme";

export interface ChartPoint {
  date: string;
  sales: number | null;
  forecast: number | null;
  band: [number, number] | null;
}

/** One point per day: the closed-day history, then the forecast days with their 80% band. */
export function chartData(
  history: ProductForecast["history"],
  forecast: ProductForecast["forecast"],
): ChartPoint[] {
  return [
    ...history.map((h) => ({ date: h.business_date, sales: h.y_units, forecast: null, band: null })),
    ...forecast.map((f) => ({
      date: f.target_date,
      sales: null,
      forecast: f.yhat,
      band: [f.low, f.high] as [number, number],
    })),
  ];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-11-18" → "18 Nov" (no time zone conversion: these are business dates). */
export const shortDate = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;

const round1 = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

function tooltipValue(value: unknown): string {
  if (Array.isArray(value)) return `${round1(Number(value[0]))} – ${round1(Number(value[1]))}`;
  return round1(Number(value));
}

interface Props {
  data: ChartPoint[];
  today: string;
  /** A fixed size (tests, where nothing can be measured); otherwise the chart fills its card. */
  size?: { width: number; height: number };
}

/** History, forecast and the 80% range on one axis (research R-18). */
export function ForecastChart({ data, today, size }: Props) {
  const chart = (
    <ComposedChart
      data={data}
      width={size?.width}
      height={size?.height}
      margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
      accessibilityLayer
    >
      <CartesianGrid stroke={CHART.grid} vertical={false} />
      <XAxis
        dataKey="date"
        tickFormatter={shortDate}
        tick={{ fill: CHART.axis, fontSize: 12 }}
        stroke={CHART.grid}
        minTickGap={24}
      />
      <YAxis
        allowDecimals={false}
        tick={{ fill: CHART.axis, fontSize: 12 }}
        stroke={CHART.grid}
        width={56}
        label={{ value: "Units per day", angle: -90, position: "insideLeft", fill: CHART.axis, fontSize: 12 }}
      />
      <Tooltip
        labelFormatter={(label) => shortDate(String(label))}
        formatter={(value) => tooltipValue(value)}
      />
      <Legend verticalAlign="top" height={32} />
      <Area
        dataKey="band"
        name="80% range"
        stroke="none"
        fill={CHART.forecast}
        fillOpacity={CHART.bandOpacity}
        isAnimationActive={false}
        legendType="square"
      />
      <Line
        dataKey="sales"
        name="Sales (last 28 days)"
        stroke={CHART.history}
        strokeWidth={2}
        dot={false}
        activeDot={{ r: 4 }}
        isAnimationActive={false}
        connectNulls={false}
      />
      <Line
        dataKey="forecast"
        name="Forecast"
        stroke={CHART.forecast}
        strokeWidth={2}
        strokeDasharray="6 4"
        dot={false}
        activeDot={{ r: 4 }}
        isAnimationActive={false}
        connectNulls={false}
      />
      <ReferenceLine
        x={today}
        stroke={CHART.today}
        strokeDasharray="2 2"
        label={{ value: "Today", position: "insideTopRight", fill: CHART.axis, fontSize: 12 }}
      />
    </ComposedChart>
  );
  return (
    <div data-testid="forecast-chart" className="forecast-chart">
      {size ? chart : <ResponsiveContainer width="100%" height={340}>{chart}</ResponsiveContainer>}
    </div>
  );
}
