import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ContractResponse } from "../lib/api";
import { setFinalist } from "../lib/api";
import ROIBadge from "./ROIBadge";

const statusColors: Record<string, string> = {
  new: "bg-blue-600 text-blue-50",
  reviewed: "bg-purple-600 text-purple-50",
  drafting: "bg-amber-600 text-amber-50",
  applied: "bg-green-700 text-green-50",
  skipped: "bg-gray-500 text-gray-100",
};

const skipReasonLabels: Record<string, string> = {
  low_match: "Low match",
  high_competition: "High competition",
  low_budget: "Below rate floor",
  low_client_quality: "Low client quality",
};

function formatBudget(min: number | null, max: number | null): string {
  if (min == null && max == null) return "Budget TBD";
  if (min != null && max != null) {
    return `$${min.toLocaleString()} - $${max.toLocaleString()}`;
  }
  if (min != null) return `$${min.toLocaleString()}+`;
  return `Up to $${max!.toLocaleString()}`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  if (diffHours < 1) return "< 1h ago";
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  return d.toLocaleDateString();
}

interface ContractCardProps {
  contract: ContractResponse;
  onSkip: (id: number) => void;
}

export default function ContractCard({ contract, onSkip }: ContractCardProps) {
  const navigate = useNavigate();
  const isSkipped = contract.status === "skipped";
  const [finalist, setFinalist_] = useState(contract.is_finalist);

  return (
    <div
      className={`rounded border border-gray-700 bg-gray-800 p-4 transition-colors ${
        isSkipped ? "opacity-50" : "hover:border-gray-500 cursor-pointer"
      }`}
      onClick={() => {
        if (!isSkipped) navigate(`/proposal/${contract.id}`);
      }}
    >
      {/* Top row: title + status pill */}
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-medium text-gray-100 leading-snug flex-1 min-w-0 truncate">
          {contract.title ?? "Untitled Contract"}
        </h3>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${statusColors[contract.status] ?? "bg-gray-600 text-gray-200"}`}
        >
          {contract.status}
        </span>
        {contract.skip_reason && (
          <span className="shrink-0 rounded-full bg-red-900/50 px-2 py-0.5 text-[11px] text-red-300">
            {skipReasonLabels[contract.skip_reason] ?? contract.skip_reason}
          </span>
        )}
      </div>

      {/* Metrics row */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-400">
        <span>{formatBudget(contract.budget_min, contract.budget_max)}</span>
        {contract.match_score != null && (
          <span>Match: {Math.round(contract.match_score * 100)}%</span>
        )}
        <ROIBadge indicator={contract.indicator} score={contract.roi_score} />
        {contract.proposals_count != null && (
          <span>{contract.proposals_count} proposals</span>
        )}
        {contract.posted_at && <span>{formatDate(contract.posted_at)}</span>}
        {contract.contract_type && (
          <span className="capitalize">{contract.contract_type}</span>
        )}
        {contract.source && (
          <span className="rounded bg-gray-700/50 px-1 py-0.5 text-[10px] text-gray-500">
            {contract.source === "best_matches" ? "Best Match" : "Search"}
          </span>
        )}
        <label className="flex items-center gap-1 text-xs" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={finalist}
            onChange={async (e) => {
              const next = e.target.checked;
              setFinalist_(next);
              try {
                await setFinalist(contract.id, next);
              } catch {
                setFinalist_(!next);
              }
            }}
          />
          Finalist
        </label>
      </div>

      {/* Skills */}
      {contract.skills_required && contract.skills_required.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {contract.skills_required.slice(0, 6).map((skill) => (
            <span
              key={skill}
              className="rounded bg-gray-700 px-1.5 py-0.5 text-[11px] text-gray-300"
            >
              {skill}
            </span>
          ))}
          {contract.skills_required.length > 6 && (
            <span className="text-[11px] text-gray-500">
              +{contract.skills_required.length - 6}
            </span>
          )}
        </div>
      )}

      {/* Action row */}
      <div className="mt-3 flex items-center gap-3">
        {contract.url && (
          <a
            href={contract.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-400 hover:text-blue-300"
            onClick={(e) => e.stopPropagation()}
          >
            View on Upwork
          </a>
        )}
        {!isSkipped && (
          <button
            type="button"
            className="ml-auto text-xs text-gray-500 hover:text-gray-300"
            onClick={(e) => {
              e.stopPropagation();
              onSkip(contract.id);
            }}
          >
            Skip
          </button>
        )}
      </div>
    </div>
  );
}
