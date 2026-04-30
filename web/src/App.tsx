import { useState } from "react";
import { useListings } from "./lib/useListings";
import { useAnalysis } from "./lib/useAnalysis";
import { applyFilters } from "./lib/filters";
import { Header } from "./components/Header";
import { FilterBar } from "./components/FilterBar";
import { DistributionChart } from "./components/DistributionChart";
import { ListingsTable } from "./components/ListingsTable";
import { RegionalBenchmark } from "./components/RegionalBenchmark";
import type { Filters } from "./lib/types";

const DEFAULT_FILTERS: Filters = {
  country: "both",
  seniority: [],
  hasSalary: false,
  normaliseToNZD: false,
  dateRangeDays: 999,
};

type Tab = "local" | "global";

export default function App() {
  const { listings, loading, error, scrapedDate, refresh } = useListings();
  const { analysis, loading: analysisLoading } = useAnalysis();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [tab, setTab] = useState<Tab>("local");

  const visible = applyFilters(listings, filters);

  return (
    <div className="min-h-screen bg-gray-50">
      <Header
        listings={listings}
        scrapedDate={scrapedDate}
        onRefresh={refresh}
        loading={loading}
      />

      {/* Tab bar */}
      <div className="border-b border-gray-200 bg-white">
        <div className="max-w-7xl mx-auto px-6">
          <nav className="flex gap-1 -mb-px">
            {(["local", "global"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                  tab === t
                    ? "border-indigo-500 text-indigo-600"
                    : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                }`}
              >
                {t === "local" ? "ANZ listings" : "Global benchmark"}
              </button>
            ))}
          </nav>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-8">
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Failed to load listings: {error}. Make sure{" "}
            <code className="font-mono text-xs">public/data/listings.json</code> exists.
          </div>
        )}

        {tab === "local" && (
          <>
            <FilterBar
              filters={filters}
              onChange={setFilters}
              totalVisible={visible.length}
            />
            {loading ? (
              <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
                Loading listings…
              </div>
            ) : (
              <>
                <section className="bg-white rounded-xl border border-gray-200 p-6">
                  <DistributionChart
                    listings={visible}
                    normaliseToNZD={filters.normaliseToNZD}
                  />
                </section>
                <section className="bg-white rounded-xl border border-gray-200 p-6">
                  <ListingsTable
                    listings={visible}
                    normaliseToNZD={filters.normaliseToNZD}
                  />
                </section>
              </>
            )}
          </>
        )}

        {tab === "global" && (
          <section className="bg-white rounded-xl border border-gray-200 p-6">
            {analysisLoading ? (
              <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
                Loading analysis…
              </div>
            ) : analysis ? (
              <RegionalBenchmark analysis={analysis} />
            ) : (
              <div className="py-16 text-center space-y-2">
                <p className="text-gray-500 text-sm">No analysis data yet.</p>
                <p className="text-gray-400 text-xs">
                  Run{" "}
                  <code className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">
                    make scrape SOURCE=hiring_cafe
                  </code>{" "}
                  then{" "}
                  <code className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">
                    make analyse
                  </code>
                  , then copy <code className="font-mono text-xs">data/analysis.json</code> to{" "}
                  <code className="font-mono text-xs">web/public/data/analysis.json</code>.
                </p>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
