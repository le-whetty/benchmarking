import { useState, useEffect } from "react";
import type { Listing } from "./types";

interface UseListingsResult {
  listings: Listing[];
  loading: boolean;
  error: string | null;
  scrapedDate: string | null;
  refresh: () => void;
}

export function useListings(): UseListingsResult {
  const [listings, setListings] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scrapedDate, setScrapedDate] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setLoading(true);
    setError(null);
    // Cache-bust with timestamp to pick up re-scrapes
    fetch(`/data/listings.json?t=${Date.now()}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: Listing[]) => {
        setListings(data);
        const latest = data.reduce<string | null>((acc, l) => {
          if (!acc || l.scraped_date > acc) return l.scraped_date;
          return acc;
        }, null);
        setScrapedDate(latest);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, [tick]);

  return { listings, loading, error, scrapedDate, refresh: () => setTick((t) => t + 1) };
}
