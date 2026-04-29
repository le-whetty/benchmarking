import { RefreshCw } from "lucide-react";
import type { Listing } from "../lib/types";

interface Props {
  listings: Listing[];
  scrapedDate: string | null;
  onRefresh: () => void;
  loading: boolean;
}

export function Header({ listings, scrapedDate, onRefresh, loading }: Props) {
  const nz = listings.filter((l) => l.country === "NZ" || l.country === "ANZ").length;
  const au = listings.filter((l) => l.country === "AU" || l.country === "ANZ").length;
  const withSalary = listings.filter((l) => l.salary_min != null).length;

  return (
    <header className="bg-white border-b border-gray-200 px-6 py-4">
      <div className="max-w-7xl mx-auto flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">
            GTM Ops Salary Benchmark
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            ANZ Revenue Operations &amp; GTM leadership roles
          </p>
        </div>

        <div className="flex items-center gap-6">
          <div className="hidden sm:flex gap-5 text-sm">
            <Stat label="Total listings" value={listings.length} />
            <Stat label="NZ" value={nz} />
            <Stat label="AU" value={au} />
            <Stat label="With salary" value={withSalary} />
          </div>

          <div className="text-right">
            {scrapedDate && (
              <p className="text-xs text-gray-400 mb-1">
                Last scraped: {scrapedDate}
              </p>
            )}
            <button
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md
                         bg-brand-500 text-white hover:bg-brand-600 disabled:opacity-50
                         transition-colors"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-center">
      <div className="text-lg font-semibold text-gray-900">{value}</div>
      <div className="text-gray-400 text-xs">{label}</div>
    </div>
  );
}
