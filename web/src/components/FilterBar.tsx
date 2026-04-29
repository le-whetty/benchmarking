import type { Filters, Seniority } from "../lib/types";
import { SENIORITY_LABELS, SENIORITY_ORDER } from "../lib/types";

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
  totalVisible: number;
}

export function FilterBar({ filters, onChange, totalVisible }: Props) {
  function set<K extends keyof Filters>(key: K, value: Filters[K]) {
    onChange({ ...filters, [key]: value });
  }

  function toggleSeniority(s: Seniority) {
    const cur = filters.seniority;
    const next = cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s];
    set("seniority", next);
  }

  return (
    <div className="bg-white border-b border-gray-200 px-6 py-3">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center gap-x-6 gap-y-2">

        {/* Country */}
        <FilterGroup label="Country">
          {(["NZ", "AU", "both"] as const).map((c) => (
            <Pill
              key={c}
              active={filters.country === c}
              onClick={() => set("country", c)}
            >
              {c === "both" ? "NZ + AU" : c}
            </Pill>
          ))}
        </FilterGroup>

        {/* Seniority */}
        <FilterGroup label="Seniority">
          {SENIORITY_ORDER.map((s) => (
            <Pill
              key={s}
              active={filters.seniority.includes(s)}
              onClick={() => toggleSeniority(s)}
            >
              {SENIORITY_LABELS[s]}
            </Pill>
          ))}
        </FilterGroup>

        {/* Date range */}
        <FilterGroup label="Posted within">
          {([30, 60, 90, 999] as const).map((d) => (
            <Pill
              key={d}
              active={filters.dateRangeDays === d}
              onClick={() => set("dateRangeDays", d)}
            >
              {d === 999 ? "All time" : `${d}d`}
            </Pill>
          ))}
        </FilterGroup>

        {/* Toggles */}
        <FilterGroup label="Options">
          <Toggle
            label="Salary disclosed"
            checked={filters.hasSalary}
            onChange={(v) => set("hasSalary", v)}
          />
          <Toggle
            label="Normalise to NZD"
            checked={filters.normaliseToNZD}
            onChange={(v) => set("normaliseToNZD", v)}
          />
        </FilterGroup>

        <span className="ml-auto text-sm text-gray-400">{totalVisible} listings</span>
      </div>
    </div>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-xs font-medium text-gray-400 uppercase tracking-wide mr-1 shrink-0">
        {label}
      </span>
      {children}
    </div>
  );
}

function Pill({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
        active
          ? "bg-brand-500 border-brand-500 text-white"
          : "bg-white border-gray-200 text-gray-600 hover:border-brand-500 hover:text-brand-600"
      }`}
    >
      {children}
    </button>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-600 select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-gray-300 text-brand-500 focus:ring-brand-500"
      />
      {label}
    </label>
  );
}
