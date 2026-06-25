import { useEffect, useState } from "react";
import type { ApplicationOutcome, HistoryEntry, HistoryStats } from "../lib/api";
import { getHistory, getHistoryStats } from "../lib/api";
import StatsCard from "../components/StatsCard";

const outcomeOptions: ApplicationOutcome[] = [
  "submitted",
  "viewed",
  "interview",
  "hired",
  "rejected",
  "no_response",
];

const outcomeColors: Record<ApplicationOutcome, string> = {
  submitted: "text-blue-400",
  viewed: "text-purple-400",
  interview: "text-amber-400",
  hired: "text-green-400",
  rejected: "text-red-400",
  no_response: "text-gray-500",
};

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "--";
  return new Date(dateStr).toLocaleDateString();
}

function formatOutcomeLabel(outcome: ApplicationOutcome): string {
  return outcome.replace("_", " ");
}

export default function History() {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [stats, setStats] = useState<HistoryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [historyData, statsData] = await Promise.all([
          getHistory(),
          getHistoryStats(),
        ]);
        setEntries(historyData);
        setStats(statsData);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load history");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  function handleOutcomeChange(id: number, outcome: ApplicationOutcome) {
    // V1: local-only update — no backend endpoint yet
    setEntries((prev) =>
      prev.map((entry) =>
        entry.id === id ? { ...entry, outcome } : entry,
      ),
    );
  }

  // Build outcomes breakdown text
  function outcomesSubtext(): string {
    if (!stats?.outcomes_breakdown) return "";
    const parts = Object.entries(stats.outcomes_breakdown)
      .filter(([, count]) => count > 0)
      .map(([key, count]) => `${key.replace("_", " ")}: ${count}`);
    return parts.join(", ");
  }

  if (loading) {
    return (
      <div className="py-16 text-center text-sm text-gray-500">
        Loading history...
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-semibold text-gray-100">Application History</h2>
        <div className="rounded border border-red-800 bg-red-950 p-4 text-sm text-red-300">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-100">Application History</h2>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatsCard
            label="Total Applications"
            value={stats.total_applications}
          />
          <StatsCard
            label="Connects Spent"
            value={stats.connects_spent}
          />
          <StatsCard
            label="Response Rate"
            value={`${Math.round(stats.response_rate * 100)}%`}
            subtext="Viewed, interview, or hired"
          />
          <StatsCard
            label="Outcomes"
            value={stats.total_applications}
            subtext={outcomesSubtext() || "No outcomes yet"}
          />
        </div>
      )}

      {/* Applications table */}
      {entries.length === 0 ? (
        <p className="py-12 text-center text-sm text-gray-500">
          No applications recorded yet. Applied proposals will appear here.
        </p>
      ) : (
        <div className="overflow-x-auto rounded border border-gray-700">
          <table className="w-full text-sm text-left">
            <thead className="bg-gray-800 text-xs text-gray-400">
              <tr>
                <th className="px-4 py-3 font-medium">Contract</th>
                <th className="px-4 py-3 font-medium">Date Applied</th>
                <th className="px-4 py-3 font-medium">Connects</th>
                <th className="px-4 py-3 font-medium">Bid Amount</th>
                <th className="px-4 py-3 font-medium">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {entries.map((entry) => (
                <tr key={entry.id} className="bg-gray-900 hover:bg-gray-800">
                  <td className="px-4 py-3 text-gray-200">
                    Contract #{entry.contract_id}
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {formatDate(entry.submitted_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {entry.connects_spent ?? "--"}
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    --
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className={`rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs capitalize ${outcomeColors[entry.outcome]}`}
                      value={entry.outcome}
                      onChange={(e) =>
                        handleOutcomeChange(
                          entry.id,
                          e.target.value as ApplicationOutcome,
                        )
                      }
                    >
                      {outcomeOptions.map((opt) => (
                        <option key={opt} value={opt}>
                          {formatOutcomeLabel(opt)}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
