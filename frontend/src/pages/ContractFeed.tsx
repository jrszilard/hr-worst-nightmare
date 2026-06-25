import { useCallback, useEffect, useState } from "react";
import ContractCard from "../components/ContractCard";
import FilterBar from "../components/FilterBar";
import ScanButton from "../components/ScanButton";
import type { ContractFilters, ContractResponse } from "../lib/api";
import { getContracts } from "../lib/api";

export default function ContractFeed() {
  const [contracts, setContracts] = useState<ContractResponse[]>([]);
  const [filters, setFilters] = useState<ContractFilters>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchContracts = useCallback(async (f: ContractFilters) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getContracts(f);
      setContracts(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load contracts");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load and whenever filters change
  useEffect(() => {
    fetchContracts(filters);
  }, [filters, fetchContracts]);

  function handleSkip(id: number) {
    // Optimistic local update — mark as skipped in the UI.
    // (No backend PATCH endpoint yet; the status will persist in local state only.)
    setContracts((prev) =>
      prev.map((c) => (c.id === id ? { ...c, status: "skipped" as const } : c)),
    );
  }

  function handleScanComplete() {
    fetchContracts(filters);
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-100">Contracts</h2>
        <ScanButton onComplete={handleScanComplete} />
      </div>

      {/* Filters */}
      <FilterBar filters={filters} onChange={setFilters} />

      {/* Content */}
      {loading ? (
        <p className="py-12 text-center text-sm text-gray-500">Loading contracts...</p>
      ) : error ? (
        <div className="rounded border border-red-800 bg-red-950 p-4 text-sm text-red-300">
          {error}
        </div>
      ) : contracts.length === 0 ? (
        <p className="py-12 text-center text-sm text-gray-500">
          No contracts found. Click Scan Contracts to get started.
        </p>
      ) : (
        <div className="space-y-3">
          {contracts.map((contract) => (
            <ContractCard
              key={contract.id}
              contract={contract}
              onSkip={handleSkip}
            />
          ))}
        </div>
      )}
    </div>
  );
}
