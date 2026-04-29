import { useState } from "react";
import { useListings } from "./lib/useListings";
import { applyFilters } from "./lib/filters";
import { Header } from "./components/Header";
import { FilterBar } from "./components/FilterBar";
import { DistributionChart } from "./components/DistributionChart";
import { ListingsTable } from "./components/ListingsTable";
import type { Filters } from "./lib/types";

const DEFAULT_FILTERS: Filters = {
  country: "both",
  seniority: [],
  hasSalary: false,
  normaliseToNZD: false,
  dateRangeDays: 999,
};

export default function App() {
  const { listings, loading, error, scrapedDate, refresh } = useListings();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);

  const visible = applyFilters(listings, filters);

  return (
    <div className="min-h-screen bg-gray-50">
      <Header
        listings={listings}
        scrapedDate={scrapedDate}
        onRefresh={refresh}
        loading={loading}
      />

      <FilterBar
        filters={filters}
        onChange={setFilters}
        totalVisible={visible.length}
      />

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-8">
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Failed to load listings: {error}. Make sure{" "}
            <code className="font-mono text-xs">public/data/listings.json</code> exists.
          </div>
        )}

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
      </main>
    </div>
  );
}
