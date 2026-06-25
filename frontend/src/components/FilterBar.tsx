import type { ContractFilters, ContractStatus, ContractType } from "../lib/api";

interface FilterBarProps {
  filters: ContractFilters;
  onChange: (filters: ContractFilters) => void;
}

export default function FilterBar({ filters, onChange }: FilterBarProps) {
  function set<K extends keyof ContractFilters>(key: K, value: ContractFilters[K]) {
    onChange({ ...filters, [key]: value || undefined });
  }

  return (
    <div className="flex flex-wrap items-end gap-3 rounded border border-gray-700 bg-gray-800 p-3 text-sm">
      {/* Status */}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-400">Status</span>
        <select
          className="rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200"
          value={filters.status ?? ""}
          onChange={(e) =>
            set("status", (e.target.value || undefined) as ContractStatus | undefined)
          }
        >
          <option value="">All</option>
          <option value="new">New</option>
          <option value="reviewed">Reviewed</option>
          <option value="drafting">Drafting</option>
          <option value="applied">Applied</option>
          <option value="skipped">Skipped</option>
        </select>
      </label>

      {/* Contract type */}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-400">Type</span>
        <select
          className="rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200"
          value={filters.contract_type ?? ""}
          onChange={(e) =>
            set(
              "contract_type",
              (e.target.value || undefined) as ContractType | undefined,
            )
          }
        >
          <option value="">All</option>
          <option value="hourly">Hourly</option>
          <option value="fixed">Fixed</option>
        </select>
      </label>

      {/* Min ROI */}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-400">Min ROI</span>
        <input
          type="number"
          step="0.1"
          min="0"
          placeholder="0"
          className="w-20 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200"
          value={filters.min_roi ?? ""}
          onChange={(e) =>
            set("min_roi", e.target.value ? Number(e.target.value) : undefined)
          }
        />
      </label>

      {/* Budget min */}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-400">Budget min</span>
        <input
          type="number"
          step="100"
          min="0"
          placeholder="$0"
          className="w-24 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200"
          value={filters.budget_min ?? ""}
          onChange={(e) =>
            set("budget_min", e.target.value ? Number(e.target.value) : undefined)
          }
        />
      </label>

      {/* Budget max */}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-400">Budget max</span>
        <input
          type="number"
          step="100"
          min="0"
          placeholder="$99999"
          className="w-24 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200"
          value={filters.budget_max ?? ""}
          onChange={(e) =>
            set("budget_max", e.target.value ? Number(e.target.value) : undefined)
          }
        />
      </label>

      {/* Skill keyword */}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-gray-400">Skill</span>
        <input
          type="text"
          placeholder="e.g. React"
          className="w-28 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-gray-200"
          value={filters.skill ?? ""}
          onChange={(e) => set("skill", e.target.value || undefined)}
        />
      </label>
    </div>
  );
}
