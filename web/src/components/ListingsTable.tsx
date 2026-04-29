import { useState } from "react";
import { ChevronUp, ChevronDown, ExternalLink, Download } from "lucide-react";
import type { Listing } from "../lib/types";
import { SENIORITY_LABELS, SCOPE_SIGNAL_LABELS, toNZD } from "../lib/types";
import { normaliseSalary } from "../lib/filters";

interface Props {
  listings: Listing[];
  normaliseToNZD: boolean;
}

type SortKey = "title" | "company" | "location" | "salary_min" | "seniority" | "posted_date";

interface Sort {
  key: SortKey;
  dir: "asc" | "desc";
}

export function ListingsTable({ listings, normaliseToNZD }: Props) {
  const [sort, setSort] = useState<Sort>({ key: "seniority", dir: "desc" });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggleSort(key: SortKey) {
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }
    );
  }

  function toggleExpand(id: string) {
    setExpanded((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const sorted = [...listings].sort((a, b) => {
    let av: any, bv: any;
    if (sort.key === "salary_min") {
      const as = normaliseSalary(a, normaliseToNZD);
      const bs = normaliseSalary(b, normaliseToNZD);
      av = as.min ?? -1;
      bv = bs.min ?? -1;
    } else {
      av = a[sort.key] ?? "";
      bv = b[sort.key] ?? "";
    }
    if (av < bv) return sort.dir === "asc" ? -1 : 1;
    if (av > bv) return sort.dir === "asc" ? 1 : -1;
    return 0;
  });

  function exportCSV() {
    const header = [
      "title", "company", "location", "country", "seniority",
      "salary_min", "salary_max", "currency", "includes_super",
      "posted_date", "scope_signals", "url",
    ];
    const rows = sorted.map((l) => {
      const { min, max, displayCurrency } = normaliseSalary(l, normaliseToNZD);
      return [
        l.title, l.company, l.location, l.country, l.seniority,
        min ?? "", max ?? "", displayCurrency, l.salary_includes_super ?? "",
        l.posted_date ?? "", l.scope_signals.join("|"), l.url,
      ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",");
    });
    const blob = new Blob([[header.join(","), ...rows].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `gtm-ops-benchmark-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const SortIcon = ({ col }: { col: SortKey }) =>
    sort.key === col ? (
      sort.dir === "asc" ? <ChevronUp size={12} /> : <ChevronDown size={12} />
    ) : (
      <ChevronDown size={12} className="opacity-30" />
    );

  const Th = ({ col, children }: { col: SortKey; children: React.ReactNode }) => (
    <th
      className="text-left py-2 px-3 text-xs font-medium text-gray-500 uppercase tracking-wide
                 cursor-pointer hover:text-gray-900 select-none whitespace-nowrap"
      onClick={() => toggleSort(col)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        <SortIcon col={col} />
      </span>
    </th>
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-gray-900">
          Listings
          <span className="ml-2 text-sm font-normal text-gray-400">({listings.length})</span>
        </h2>
        <button
          onClick={exportCSV}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border
                     border-gray-200 text-gray-600 hover:border-gray-400 hover:text-gray-900 transition-colors"
        >
          <Download size={13} />
          Export CSV
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-sm border-collapse">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <Th col="title">Title</Th>
              <Th col="company">Company</Th>
              <Th col="location">Location</Th>
              <Th col="salary_min">Salary range</Th>
              <Th col="seniority">Level</Th>
              <Th col="posted_date">Posted</Th>
              <th className="py-2 px-3 w-8" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((l) => {
              const { min, max, displayCurrency } = normaliseSalary(l, normaliseToNZD);
              const isExpanded = expanded.has(l.id);
              const salaryStr = min != null
                ? `${displayCurrency === "NZD" ? "NZ$" : "A$"}${Math.round(min / 1000)}k${
                    max && max !== min ? `–${Math.round(max / 1000)}k` : ""
                  }${l.salary_includes_super ? " +super" : ""}`
                : "—";

              return [
                <tr
                  key={l.id}
                  className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
                  onClick={() => toggleExpand(l.id)}
                >
                  <td className="py-2.5 px-3 font-medium text-gray-900 max-w-xs">
                    <span className="line-clamp-1">{l.title}</span>
                  </td>
                  <td className="py-2.5 px-3 text-gray-600 whitespace-nowrap">{l.company}</td>
                  <td className="py-2.5 px-3 text-gray-500 text-xs whitespace-nowrap">
                    {l.city ?? l.location}
                    <span className="ml-1 text-gray-300">{l.country}</span>
                  </td>
                  <td className="py-2.5 px-3 font-mono text-xs whitespace-nowrap">
                    {min != null ? (
                      <span className="text-green-700">{salaryStr}</span>
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  <td className="py-2.5 px-3">
                    <SeniorityBadge seniority={l.seniority} />
                  </td>
                  <td className="py-2.5 px-3 text-gray-400 text-xs whitespace-nowrap">
                    {l.posted_date ?? "—"}
                  </td>
                  <td className="py-2.5 px-3 text-gray-300">
                    {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </td>
                </tr>,
                isExpanded && (
                  <tr key={`${l.id}-exp`} className="bg-blue-50 border-b border-gray-100">
                    <td colSpan={7} className="px-4 py-3">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                        <div className="md:col-span-2">
                          <p className="text-gray-500 font-medium mb-1">Description excerpt</p>
                          <p className="text-gray-700 leading-relaxed">{l.description_excerpt || "No description available."}</p>
                        </div>
                        <div>
                          <p className="text-gray-500 font-medium mb-1">Scope signals</p>
                          <div className="flex flex-wrap gap-1 mb-3">
                            {l.scope_signals.length > 0
                              ? l.scope_signals.map((sig) => (
                                  <span
                                    key={sig}
                                    className="px-2 py-0.5 bg-white border border-blue-200 text-blue-700 rounded-full text-xs"
                                  >
                                    {SCOPE_SIGNAL_LABELS[sig] ?? sig}
                                  </span>
                                ))
                              : <span className="text-gray-400">None detected</span>}
                          </div>
                          <div className="text-gray-400 text-xs space-y-0.5">
                            {l.company_size && <div>Company: <span className="capitalize">{l.company_size}</span></div>}
                            <div>Confidence: {Math.round(l.title_match_confidence * 100)}%</div>
                            <div>Source: {l.source}</div>
                          </div>
                          <a
                            href={l.url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="mt-2 inline-flex items-center gap-1 text-brand-600 hover:text-brand-700 font-medium"
                          >
                            View listing <ExternalLink size={11} />
                          </a>
                        </div>
                      </div>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>

        {listings.length === 0 && (
          <div className="text-center py-12 text-gray-400 text-sm">
            No listings match current filters.
          </div>
        )}
      </div>
    </div>
  );
}

const SENIORITY_COLOURS: Record<string, string> = {
  manager: "bg-gray-100 text-gray-600",
  senior_manager: "bg-purple-50 text-purple-700",
  head: "bg-blue-50 text-blue-700",
  director: "bg-indigo-50 text-indigo-700",
  vp: "bg-amber-50 text-amber-700",
};

function SeniorityBadge({ seniority }: { seniority: string }) {
  return (
    <span
      className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${
        SENIORITY_COLOURS[seniority] ?? "bg-gray-100 text-gray-600"
      }`}
    >
      {SENIORITY_LABELS[seniority as keyof typeof SENIORITY_LABELS] ?? seniority}
    </span>
  );
}
