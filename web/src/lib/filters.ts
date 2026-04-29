import { subDays } from "date-fns";
import type { Listing, Filters } from "./types";
import { toNZD } from "./types";

export function applyFilters(listings: Listing[], filters: Filters): Listing[] {
  const cutoff = filters.dateRangeDays === 999
    ? null
    : subDays(new Date(), filters.dateRangeDays);

  return listings.filter((l) => {
    if (filters.country !== "both") {
      if (filters.country === "NZ" && l.country !== "NZ" && l.country !== "ANZ") return false;
      if (filters.country === "AU" && l.country !== "AU" && l.country !== "ANZ") return false;
    }

    if (filters.seniority.length > 0 && !filters.seniority.includes(l.seniority)) return false;

    if (filters.hasSalary && (l.salary_min == null || l.salary_max == null)) return false;

    if (cutoff && l.posted_date) {
      const posted = new Date(l.posted_date);
      if (posted < cutoff) return false;
    }

    return true;
  });
}

export function normaliseSalary(
  listing: Listing,
  normalise: boolean
): { min: number | null; max: number | null; displayCurrency: string } {
  if (listing.salary_min == null) return { min: null, max: null, displayCurrency: listing.salary_currency };

  if (!normalise) {
    return {
      min: listing.salary_min,
      max: listing.salary_max,
      displayCurrency: listing.salary_currency,
    };
  }

  return {
    min: toNZD(listing.salary_min, listing.salary_currency),
    max: listing.salary_max != null ? toNZD(listing.salary_max, listing.salary_currency) : null,
    displayCurrency: "NZD",
  };
}
