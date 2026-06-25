import { useCallback, useEffect, useRef, useState } from "react";
import { getJobScanStatus, scanJobBoards } from "../lib/api";
import type { ScannerState } from "../lib/api";

interface JobsScanButtonProps {
  onComplete: () => void;
}

export default function JobsScanButton({ onComplete }: JobsScanButtonProps) {
  const [state, setState] = useState<ScannerState>("idle");
  const [found, setFound] = useState(0);
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
        const status = await getJobScanStatus();
        setState(status.state);
        setFound(status.contracts_found);
        if (status.state === "complete" || status.state === "error") {
          stopPolling();
          if (status.state === "complete") onComplete();
          setTimeout(() => setState("idle"), 2000);
        }
      } catch {
        stopPolling();
        setState("error");
        setTimeout(() => setState("idle"), 2000);
      }
    }, 2000);
  }, [onComplete, stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);

  async function handleClick() {
    if (state === "running") return;
    setState("running");
    setFound(0);
    try {
      await scanJobBoards();
      pollStatus();
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2000);
    }
  }

  const isRunning = state === "running";
  let label = "Scan job boards";
  if (isRunning) label = `Scanning… ${found} found`;
  else if (state === "complete") label = `Done! ${found} jobs`;
  else if (state === "error") label = "Scan failed";

  return (
    <button
      type="button"
      disabled={isRunning}
      onClick={handleClick}
      className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
        isRunning
          ? "cursor-not-allowed bg-gray-600 text-gray-300"
          : state === "error"
            ? "bg-red-700 text-red-100 hover:bg-red-600"
            : "bg-blue-600 text-white hover:bg-blue-500"
      }`}
    >
      {label}
    </button>
  );
}
