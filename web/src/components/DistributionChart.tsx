/**
 * Salary distribution chart.
 * Shows min/p25/median/p75/max per seniority level as a grouped bar chart
 * (Recharts doesn't support box plots natively; this is the spec's stated fallback).
 */
import {
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ErrorBar,
} from "recharts";
import type { Listing } from "../lib/types";
import { SENIORITY_LABELS, SENIORITY_ORDER, toNZD } from "../lib/types";
import type { Seniority, Currency } from "../lib/types";

interface Props {
  listings: Listing[];
  normaliseToNZD: boolean;
}

interface SeniorityStats {
  seniority: Seniority;
  label: string;
  nz: DistStats | null;
  au: DistStats | null;
  nzCount: number;
  auCount: number;
}

interface DistStats {
  min: number;
  p25: number;
  median: number;
  p75: number;
  max: number;
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function computeStats(values: number[]): DistStats | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return {
    min: sorted[0],
    p25: percentile(sorted, 25),
    median: percentile(sorted, 50),
    p75: percentile(sorted, 75),
    max: sorted[sorted.length - 1],
  };
}

function getMidpoints(listings: Listing[], normalise: boolean, country: "NZ" | "AU"): Map<Seniority, number[]> {
  const map = new Map<Seniority, number[]>();
  for (const s of SENIORITY_ORDER) map.set(s, []);

  for (const l of listings) {
    if (l.salary_min == null || l.salary_max == null) continue;
    const matchCountry = country === "NZ"
      ? l.country === "NZ" || l.country === "ANZ"
      : l.country === "AU" || l.country === "ANZ";
    if (!matchCountry) continue;

    const currency: Currency = l.salary_currency;
    const mid = (l.salary_min + l.salary_max) / 2;
    const normalised = normalise ? toNZD(mid, currency) : mid;
    map.get(l.seniority)!.push(normalised);
  }
  return map;
}

export function DistributionChart({ listings, normaliseToNZD }: Props) {
  const nzMap = getMidpoints(listings, normaliseToNZD, "NZ");
  const auMap = getMidpoints(listings, normaliseToNZD, "AU");

  const chartData: Array<SeniorityStats & Record<string, number | null | string>> = SENIORITY_ORDER.map((s) => {
    const nzVals = nzMap.get(s)!;
    const auVals = auMap.get(s)!;
    const nz = computeStats(nzVals);
    const au = computeStats(auVals);
    return {
      seniority: s,
      label: SENIORITY_LABELS[s],
      nz,
      au,
      nzCount: nzVals.length,
      auCount: auVals.length,
      nzMedian: nz?.median ?? null,
      nzMin: nz?.min ?? null,
      nzMax: nz?.max ?? null,
      auMedian: au?.median ?? null,
      auMin: au?.min ?? null,
      auMax: au?.max ?? null,
    };
  }).filter((d) => d.nzCount > 0 || d.auCount > 0);

  const currencyLabel = normaliseToNZD ? "NZD" : "local currency";

  const formatK = (v: number) => `$${Math.round(v / 1000)}k`;

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-lg text-xs">
        <p className="font-semibold mb-2">{label}</p>
        {payload.map((p: any) => {
          const entry = chartData.find((d) => d.label === label);
          const isNZ = p.dataKey === "nzMedian";
          const stats = isNZ ? entry?.nz : entry?.au;
          const count = isNZ ? entry?.nzCount : entry?.auCount;
          if (!stats) return null;
          return (
            <div key={p.dataKey} className="mb-1">
              <span className="font-medium" style={{ color: p.fill }}>
                {isNZ ? "NZ" : "AU"} ({count} listings)
              </span>
              <div className="mt-0.5 text-gray-600">
                <span>Min: {formatK(stats.min)}</span>
                <span className="mx-1">·</span>
                <span>P25: {formatK(stats.p25)}</span>
                <span className="mx-1">·</span>
                <span className="font-semibold">Median: {formatK(stats.median)}</span>
                <span className="mx-1">·</span>
                <span>P75: {formatK(stats.p75)}</span>
                <span className="mx-1">·</span>
                <span>Max: {formatK(stats.max)}</span>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
        No salary data available for current filters.
      </div>
    );
  }

  const lowConfidenceGroups = chartData.filter(
    (d) => (d.nzCount > 0 && d.nzCount < 5) || (d.auCount > 0 && d.auCount < 5)
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold text-gray-900">
          Salary Distribution by Seniority
        </h2>
        <span className="text-xs text-gray-400">
          Midpoints of disclosed ranges · {currencyLabel}
        </span>
      </div>

      {lowConfidenceGroups.length > 0 && (
        <div className="mb-3 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded px-3 py-1.5">
          ⚠ Low confidence:{" "}
          {lowConfidenceGroups.map((g) => {
            const parts = [];
            if (g.nzCount > 0 && g.nzCount < 5) parts.push(`${g.label} NZ (n=${g.nzCount})`);
            if (g.auCount > 0 && g.auCount < 5) parts.push(`${g.label} AU (n=${g.auCount})`);
            return parts.join(", ");
          }).join("; ")}{" "}
          — fewer than 5 listings.
        </div>
      )}

      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="label" tick={{ fontSize: 12 }} />
          <YAxis
            tickFormatter={formatK}
            tick={{ fontSize: 11 }}
            domain={["auto", "auto"]}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            formatter={(value) => (
              <span className="text-xs">{value === "nzMedian" ? "NZ median" : "AU median"}</span>
            )}
          />
          <Bar dataKey="nzMedian" name="nzMedian" fill="#0ea5e9" radius={[3, 3, 0, 0]} maxBarSize={48} />
          <Bar dataKey="auMedian" name="auMedian" fill="#f59e0b" radius={[3, 3, 0, 0]} maxBarSize={48} />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Range table below chart for p25/p75 detail */}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-xs text-gray-600 border-collapse">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left py-1.5 pr-4 font-medium text-gray-500">Level</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">Country</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">n</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">Min</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">P25</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500 text-gray-900 font-semibold">Median</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">P75</th>
              <th className="text-right py-1.5 px-2 font-medium text-gray-500">Max</th>
            </tr>
          </thead>
          <tbody>
            {chartData.flatMap((d) => {
              const rows = [];
              if (d.nz && d.nzCount > 0) {
                rows.push(
                  <tr key={`${d.seniority}-nz`} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-1.5 pr-4 font-medium text-gray-700">{d.label}</td>
                    <td className="text-right px-2"><span className="text-blue-600 font-medium">NZ</span></td>
                    <td className="text-right px-2">{d.nzCount}{d.nzCount < 5 && " ⚠"}</td>
                    <td className="text-right px-2">{formatK(d.nz.min)}</td>
                    <td className="text-right px-2">{formatK(d.nz.p25)}</td>
                    <td className="text-right px-2 font-semibold text-gray-900">{formatK(d.nz.median)}</td>
                    <td className="text-right px-2">{formatK(d.nz.p75)}</td>
                    <td className="text-right px-2">{formatK(d.nz.max)}</td>
                  </tr>
                );
              }
              if (d.au && d.auCount > 0) {
                rows.push(
                  <tr key={`${d.seniority}-au`} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-1.5 pr-4 font-medium text-gray-700">{d.nzCount === 0 ? d.label : ""}</td>
                    <td className="text-right px-2"><span className="text-amber-600 font-medium">AU</span></td>
                    <td className="text-right px-2">{d.auCount}{d.auCount < 5 && " ⚠"}</td>
                    <td className="text-right px-2">{formatK(d.au.min)}</td>
                    <td className="text-right px-2">{formatK(d.au.p25)}</td>
                    <td className="text-right px-2 font-semibold text-gray-900">{formatK(d.au.median)}</td>
                    <td className="text-right px-2">{formatK(d.au.p75)}</td>
                    <td className="text-right px-2">{formatK(d.au.max)}</td>
                  </tr>
                );
              }
              return rows;
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
