export type Seniority = "manager" | "senior_manager" | "head" | "director" | "vp";
export type Country = "NZ" | "AU" | "ANZ" | "US" | "UK" | "REMOTE";
export type Currency = "NZD" | "AUD" | "USD" | "GBP";
export type CompanySize = "startup" | "scaleup" | "enterprise";

export interface Listing {
  id: string;
  source: string;
  url: string;
  title: string;
  company: string;
  company_size: CompanySize | null;
  location: string;
  country: Country;
  city: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: Currency;
  salary_includes_super: boolean | null;
  ote_min: number | null;
  ote_max: number | null;
  seniority: Seniority;
  title_match_confidence: number;
  scope_signals: string[];
  description_excerpt: string;
  posted_date: string | null;
  scraped_date: string;
}

export interface Filters {
  country: "NZ" | "AU" | "both";
  seniority: Seniority[];
  hasSalary: boolean;
  normaliseToNZD: boolean;
  dateRangeDays: 30 | 60 | 90 | 999;
}

export const SENIORITY_LABELS: Record<Seniority, string> = {
  manager: "Manager",
  senior_manager: "Senior Manager",
  head: "Head of",
  director: "Director",
  vp: "VP",
};

export const SENIORITY_ORDER: Seniority[] = [
  "manager",
  "senior_manager",
  "head",
  "director",
  "vp",
];

export const SCOPE_SIGNAL_LABELS: Record<string, string> = {
  manages_team: "Manages team",
  reports_to_c_suite: "Reports to C-suite",
  owns_crm_stack: "Owns CRM stack",
  owns_forecasting: "Owns forecasting",
  cross_functional: "Cross-functional",
  ai_remit: "AI / automation remit",
  multi_gtm_functions: "Multi-GTM functions",
};

// Hardcoded FX rates — update periodically
export const AUD_TO_NZD = 1.09;
export const USD_TO_NZD = 1.65;
export const GBP_TO_NZD = 2.10;

export function toNZD(value: number, currency: Currency): number {
  if (currency === "AUD") return value * AUD_TO_NZD;
  if (currency === "USD") return value * USD_TO_NZD;
  if (currency === "GBP") return value * GBP_TO_NZD;
  return value;
}

export function formatSalary(value: number, currency: Currency): string {
  const k = Math.round(value / 1000);
  const sym = currency === "NZD" ? "NZ$" : currency === "AUD" ? "A$" : currency === "GBP" ? "£" : "US$";
  return `${sym}${k}k`;
}

// ── Analysis types ────────────────────────────────────────────────────────────

export interface RegionalStats {
  n: number;
  currency: string;
  p25_nzd: number;
  median_nzd: number;
  p75_nzd: number;
  mean_nzd: number;
  p25_local: number;
  median_local: number;
  p75_local: number;
  by_seniority: Record<string, { n: number; median_nzd: number; median_local: number }>;
}

export interface NZEstimate {
  insufficient_data: boolean;
  method?: string;
  nz_swe_anchor_nzd?: number;
  market_ratios?: Record<string, number>;
  avg_ratio?: number;
  estimated_p25_nzd?: number;
  estimated_median_nzd?: number;
  estimated_p75_nzd?: number;
  caveats?: string[];
}

export interface TopCompany {
  company: string;
  country: string;
  n_roles: number;
  median_nzd: number;
}

export interface Analysis {
  generated_at: string;
  total_listings: number;
  listings_with_salary: number;
  regional: Record<string, RegionalStats>;
  nz_estimate: NZEstimate;
  top_companies_by_salary: TopCompany[];
}
