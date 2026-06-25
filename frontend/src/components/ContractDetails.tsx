import type { ContractResponse } from "../lib/api";
import ROIBadge from "./ROIBadge";

interface ContractDetailsProps {
  contract: ContractResponse;
}

function formatBudget(min: number | null, max: number | null): string {
  if (min == null && max == null) return "TBD";
  if (min != null && max != null) {
    return `$${min.toLocaleString()} - $${max.toLocaleString()}`;
  }
  if (min != null) return `$${min.toLocaleString()}+`;
  return `Up to $${max!.toLocaleString()}`;
}

// Simple list of common core skills for the indicator heuristic.
// In a real app this would come from the user's profile.
const CORE_SKILLS = new Set([
  "react", "typescript", "javascript", "node.js", "next.js",
  "python", "django", "fastapi", "postgresql", "tailwind css",
  "html", "css", "graphql", "rest api", "aws",
]);

function isCore(skill: string): boolean {
  return CORE_SKILLS.has(skill.toLowerCase());
}

export default function ContractDetails({ contract }: ContractDetailsProps) {
  return (
    <div className="space-y-5">
      {/* ROI & Match */}
      <div className="flex items-center gap-3">
        <ROIBadge indicator={contract.indicator} score={contract.roi_score} />
        {contract.match_score != null && (
          <span className="text-sm text-gray-400">
            {Math.round(contract.match_score * 100)}% match
          </span>
        )}
      </div>

      {/* Competition */}
      {contract.proposals_count != null && (
        <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300">
          <span className="font-medium text-gray-100">{contract.proposals_count}</span>{" "}
          proposals submitted
        </div>
      )}

      {/* Description */}
      {contract.description && (
        <div>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Description
          </h4>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-300">
            {contract.description}
          </p>
        </div>
      )}

      {/* Budget & Duration */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">Budget</div>
          <div className="mt-0.5 text-sm font-medium text-gray-100">
            {formatBudget(contract.budget_min, contract.budget_max)}
          </div>
          {contract.contract_type && (
            <div className="mt-0.5 text-xs capitalize text-gray-400">
              {contract.contract_type}
            </div>
          )}
        </div>
        <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-gray-500">Duration</div>
          <div className="mt-0.5 text-sm font-medium text-gray-100">
            {contract.duration ?? "Not specified"}
          </div>
        </div>
      </div>

      {/* Client Info */}
      {(contract.client_hire_rate != null || contract.client_total_spent != null) && (
        <div>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Client
          </h4>
          <div className="grid grid-cols-2 gap-3">
            {contract.client_hire_rate != null && (
              <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-gray-500">
                  Hire Rate
                </div>
                <div className="mt-0.5 text-sm font-medium text-gray-100">
                  {Math.round(contract.client_hire_rate * 100)}%
                </div>
              </div>
            )}
            {contract.client_total_spent != null && (
              <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-gray-500">
                  Total Spent
                </div>
                <div className="mt-0.5 text-sm font-medium text-gray-100">
                  ${contract.client_total_spent.toLocaleString()}
                </div>
              </div>
            )}
          </div>
          {contract.client_location && (
            <div className="mt-2 text-xs text-gray-400">
              Location: {contract.client_location}
            </div>
          )}
        </div>
      )}

      {/* Skills */}
      {contract.skills_required && contract.skills_required.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Required Skills
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {contract.skills_required.map((skill) => (
              <span
                key={skill}
                className={`rounded px-2 py-0.5 text-xs font-medium ${
                  isCore(skill)
                    ? "bg-green-900/50 text-green-300 border border-green-700"
                    : "bg-blue-900/50 text-blue-300 border border-blue-700"
                }`}
              >
                {skill}
              </span>
            ))}
          </div>
          <div className="mt-1.5 flex items-center gap-3 text-[11px] text-gray-500">
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full bg-green-600" /> Core
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-600" /> Adjacent
            </span>
          </div>
        </div>
      )}

      {/* Connects Cost */}
      {contract.connects_cost != null && (
        <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300">
          <span className="text-[11px] uppercase tracking-wide text-gray-500">Connects Cost: </span>
          <span className="font-medium text-gray-100">{contract.connects_cost}</span>
        </div>
      )}
    </div>
  );
}
