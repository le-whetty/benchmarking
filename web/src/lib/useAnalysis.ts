import { useState, useEffect } from "react";
import type { Analysis } from "./types";

interface UseAnalysisResult {
  analysis: Analysis | null;
  loading: boolean;
  error: string | null;
}

export function useAnalysis(): UseAnalysisResult {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/data/analysis.json?t=${Date.now()}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: Analysis) => {
        setAnalysis(data);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  return { analysis, loading, error };
}
