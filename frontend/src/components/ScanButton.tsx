import { useCallback, useEffect, useRef, useState } from "react";
import { enrichBatch, getScannerStatus, scanContracts } from "../lib/api";
import type { ScannerState } from "../lib/api";

interface ScanButtonProps {
  onComplete: () => void;
}

export default function ScanButton({ onComplete }: ScanButtonProps) {
  const [state, setState] = useState<ScannerState>("idle");
  const [progress, setProgress] = useState(0);
  const [found, setFound] = useState(0);
  const [currentSearch, setCurrentSearch] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollStatus = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const status = await getScannerStatus();
        setState(status.state);
        setProgress(status.progress);
        setFound(status.contracts_found);
        setCurrentSearch(status.current_search);

        if (status.state === "complete" || status.state === "error") {
          stopPolling();
          if (status.state === "complete") {
            // Enrich contracts missing skills before refreshing the list
            setCurrentSearch("enriching contracts...");
            try {
              await enrichBatch();
            } catch {
              // Enrichment failure is non-fatal — contracts are still saved
            }
            onComplete();
          }
          // Reset to idle after a short delay so the button becomes available
          setTimeout(() => setState("idle"), 2000);
        }
      } catch {
        stopPolling();
        setState("error");
        setTimeout(() => setState("idle"), 2000);
      }
    }, 2000);
  }, [onComplete, stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  async function handleClick() {
    if (state === "running") return;
    setState("running");
    setProgress(0);
    setFound(0);
    try {
      await scanContracts();
      pollStatus();
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2000);
    }
  }

  const isRunning = state === "running";
  const isError = state === "error";

  let label = "Scan Contracts";
  if (isRunning) {
    const pct = Math.round(progress * 100);
    label = currentSearch
      ? `Scanning: ${currentSearch} (${pct}%)`
      : found > 0
        ? `Scanning... ${found} found (${pct}%)`
        : `Scanning... (${pct}%)`;
  } else if (state === "complete") {
    label = `Done! ${found} contracts found`;
  } else if (isError) {
    label = "Scan failed";
  }

  return (
    <button
      type="button"
      disabled={isRunning}
      onClick={handleClick}
      className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
        isRunning
          ? "cursor-not-allowed bg-gray-600 text-gray-300"
          : isError
            ? "bg-red-700 text-red-100 hover:bg-red-600"
            : "bg-blue-600 text-white hover:bg-blue-500"
      }`}
    >
      {label}
    </button>
  );
}
