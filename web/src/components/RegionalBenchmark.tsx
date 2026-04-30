import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
  ErrorBar,
} from "recharts";
import type { Analysis, RegionalStats } from "../lib/types";

interface Props {
  analysis: Analysis;
}

const COUNTRY_LABELS: Record<string, string> = {
  US: "United States",
  UK: "United Kingdom",
  AU: "Australia",
  NZ: "New Zealand",
  ANZ: "ANZ",
};

const COUNTRY_COLORS: Record<string, string> = {
  US: "#6366f1",
  UK: "#ec4899",
  AU: "#f59e0b",
  NZ: "#10b981",
  ANZ: "#64748b",
};

const SENIORITY_ORDER = ["manager", "senior_manager", "head", "director", "vp"];
const SENIORITY_LABELS: Record<string, string> = {
  manager: "Manager",
  senior_manager: "Sr. Manager",
  head: "Head of",
  director: "Director",
  vp: "VP",
};

function fmt(n: number) {
  return `NZ$${Math.round(n / 1000)}k`;
}

function formatLocal(n: number, currency: string) {
  const sym = currency === "USD" ? "US$" : currency === "GBP" ? "£" : currency === "AUD" ? "A$" : "NZ$";
  return `${sym}${Math.round(n / 1000)}k`;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; payload: Record<string, unknown> }>;
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload as {
    country: string; median_nzd: number; p25_nzd: number; p75_nzd: number;
    median_local: number; currency: string; n: number;
  };
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-lg text-sm">
      <p className="font-semibold text-gray-900">{COUNTRY_LABELS[d.country] ?? d.country}</p>
      <p className="text-gray-500 text-xs mb-2">{d.n} listings</p>
      <p className="text-gray-700">Median: <span className="font-medium">{fmt(d.median_nzd)}</span>
        {" "}<span className="text-gray-400">({formatLocal(d.median_local, d.currency)} local)</span></p>
      <p className="text-gray-500 text-xs mt-1">Range: {fmt(d.p25_nzd)} – {fmt(d.p75_nzd)}</p>
    </div>
  );
}

export function RegionalBenchmark({ analysis }: Props) {
  const { regional, nz_estimate, top_companies_by_salary } = analysis;

  // Build chart data — ordered US → UK → AU → NZ
  const MARKET_ORDER = ["US", "UK", "AU", "NZ"];
  const chartData = MARKET_ORDER
    .filter((c) => regional[c]?.n > 0)
    .map((country) => {
      const r: RegionalStats = regional[country];
      return {
        country,
        label: country,
        median_nzd: r.median_nzd,
        p25_nzd: r.p25_nzd,
        p75_nzd: r.p75_nzd,
        median_local: r.median_local,
        currency: r.currency,
        n: r.n,
        // ErrorBar expects [lo, hi] deltas from the value
        range: [r.median_nzd - r.p25_nzd, r.p75_nzd - r.median_nzd],
      };
    });

  // NZ estimate data point (distinct colour)
  const hasEstimate = !nz_estimate.insufficient_data && nz_estimate.estimated_median_nzd;

  // Seniority breakdown table
  const marketOrder = MARKET_ORDER.filter((c) => regional[c]?.n > 0);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Global market comparison</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          RevOps / GTM Ops median salary, normalised to NZD. Bars show p25–p75 range.
        </p>
      </div>

      {/* ── Main bar chart ─────────────────────────────────────────────── */}
      {chartData.length === 0 ? (
        <p className="text-sm text-gray-400 py-12 text-center">
          No regional salary data yet — run <code className="font-mono text-xs">make scrape SOURCE=hiring_cafe</code> to populate.
        </p>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} barCategoryGap="30%">
              <XAxis
                dataKey="label"
                tick={{ fontSize: 13, fontWeight: 600 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={(v) => `$${v / 1000}k`}
                tick={{ fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={55}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: "#f3f4f6" }} />
              {hasEstimate && (
                <ReferenceLine
                  y={nz_estimate.estimated_median_nzd}
                  stroke="#10b981"
                  strokeDasharray="4 3"
                  label={{
                    value: "NZ est.",
                    position: "insideTopRight",
                    fontSize: 11,
                    fill: "#10b981",
                  }}
                />
              )}
              <Bar dataKey="median_nzd" radius={[4, 4, 0, 0]} maxBarSize={72}>
                {chartData.map((d) => (
                  <Cell key={d.country} fill={COUNTRY_COLORS[d.country] ?? "#94a3b8"} />
                ))}
                <ErrorBar dataKey="range" width={6} strokeWidth={2} stroke="#374151" opacity={0.4} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── NZ Estimate callout ────────────────────────────────────────── */}
      {hasEstimate && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="font-semibold text-emerald-900 text-sm">
                NZ benchmark estimate (ratio method)
              </h3>
              <p className="text-xs text-emerald-700 mt-0.5">
                Based on RevOps / SWE salary ratio across{" "}
                {Object.keys(nz_estimate.market_ratios ?? {}).join(", ")}, applied to NZ SWE anchor
                (NZ${(nz_estimate.nz_swe_anchor_nzd ?? 0).toLocaleString()}).
                Edit <code className="font-mono">data/benchmarks.json</code> to use Tracksuit's actual bands.
              </p>
            </div>
            <div className="text-right shrink-0">
              <p className="text-2xl font-bold text-emerald-800">
                {fmt(nz_estimate.estimated_median_nzd ?? 0)}
              </p>
              <p className="text-xs text-emerald-600">
                {fmt(nz_estimate.estimated_p25_nzd ?? 0)} – {fmt(nz_estimate.estimated_p75_nzd ?? 0)}
              </p>
            </div>
          </div>

          {/* Ratios */}
          <div className="mt-3 flex gap-4 flex-wrap">
            {Object.entries(nz_estimate.market_ratios ?? {}).map(([market, ratio]) => (
              <div key={market} className="text-xs text-emerald-800">
                <span className="font-medium">{market}</span> ratio:{" "}
                <span className="font-semibold">{ratio.toFixed(2)}×</span>
              </div>
            ))}
            <div className="text-xs text-emerald-800">
              avg: <span className="font-semibold">{(nz_estimate.avg_ratio ?? 0).toFixed(2)}×</span>
            </div>
          </div>

          {/* Caveats */}
          {nz_estimate.caveats && (
            <ul className="mt-3 space-y-0.5">
              {nz_estimate.caveats.map((c, i) => (
                <li key={i} className="text-xs text-emerald-600">· {c}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* ── Seniority breakdown ────────────────────────────────────────── */}
      {marketOrder.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-3">By seniority (median NZD)</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 pr-4 font-medium text-gray-500 text-xs">Level</th>
                  {marketOrder.map((c) => (
                    <th key={c} className="text-right py-2 px-3 font-medium text-xs" style={{ color: COUNTRY_COLORS[c] }}>
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {SENIORITY_ORDER.map((sen) => {
                  const hasSomeData = marketOrder.some(
                    (c) => (regional[c]?.by_seniority?.[sen]?.n ?? 0) > 0
                  );
                  if (!hasSomeData) return null;
                  return (
                    <tr key={sen} className="border-b border-gray-50 hover:bg-gray-50">
                      <td className="py-2 pr-4 text-gray-700 font-medium">
                        {SENIORITY_LABELS[sen]}
                      </td>
                      {marketOrder.map((c) => {
                        const d = regional[c]?.by_seniority?.[sen];
                        return (
                          <td key={c} className="py-2 px-3 text-right text-gray-600">
                            {d?.n > 0 ? (
                              <span title={`n=${d.n}`}>{fmt(d.median_nzd)}</span>
                            ) : (
                              <span className="text-gray-300">—</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Top companies ─────────────────────────────────────────────── */}
      {top_companies_by_salary.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Top-paying companies hiring RevOps</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 pr-4 font-medium text-gray-500 text-xs">Company</th>
                  <th className="text-left py-2 pr-4 font-medium text-gray-500 text-xs">Market</th>
                  <th className="text-right py-2 pr-4 font-medium text-gray-500 text-xs">Roles</th>
                  <th className="text-right py-2 font-medium text-gray-500 text-xs">Median (NZD)</th>
                </tr>
              </thead>
              <tbody>
                {top_companies_by_salary.slice(0, 15).map((co, i) => (
                  <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-2 pr-4 font-medium text-gray-800">{co.company}</td>
                    <td className="py-2 pr-4">
                      <span
                        className="inline-block px-2 py-0.5 rounded text-xs font-semibold"
                        style={{
                          background: `${COUNTRY_COLORS[co.country]}20`,
                          color: COUNTRY_COLORS[co.country] ?? "#64748b",
                        }}
                      >
                        {co.country}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-right text-gray-500">{co.n_roles}</td>
                    <td className="py-2 text-right font-medium text-gray-700">
                      {fmt(co.median_nzd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p className="text-xs text-gray-400">
        {analysis.listings_with_salary} of {analysis.total_listings} listings have salary data.
        Generated {new Date(analysis.generated_at).toLocaleDateString("en-NZ", { dateStyle: "medium" })}.
      </p>
    </div>
  );
}
