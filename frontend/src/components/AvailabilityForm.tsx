import { useEffect, useState } from "react";
import type { AvailabilityConfig } from "../lib/api";
import { getAvailability, updateAvailability } from "../lib/api";

export default function AvailabilityForm() {
  const [form, setForm] = useState<AvailabilityConfig>({
    hours_per_week: 40,
    max_concurrent_contracts: 3,
    current_committed_hours: 0,
    preferred_duration: "any",
    preferred_contract_type: "both",
    min_hourly_rate: 75,
    min_fixed_budget: 500,
    hourly_value: 100,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await getAvailability();
        setForm(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load availability");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  function handleChange(key: keyof AvailabilityConfig, value: string | number) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSuccess(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const updated = await updateAvailability(form);
      setForm(updated);
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save availability");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-500">Loading availability...</p>;
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded border border-green-800 bg-green-950 px-3 py-2 text-sm text-green-300">
          Availability saved successfully.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Hours per week */}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Hours per week</span>
          <input
            type="number"
            min="0"
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
            value={form.hours_per_week}
            onChange={(e) => handleChange("hours_per_week", Number(e.target.value))}
          />
        </label>

        {/* Max concurrent contracts */}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Max concurrent contracts</span>
          <input
            type="number"
            min="1"
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
            value={form.max_concurrent_contracts}
            onChange={(e) => handleChange("max_concurrent_contracts", Number(e.target.value))}
          />
        </label>

        {/* Current committed hours */}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Current committed hours</span>
          <input
            type="number"
            min="0"
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
            value={form.current_committed_hours}
            onChange={(e) => handleChange("current_committed_hours", Number(e.target.value))}
          />
        </label>

        {/* Min hourly rate */}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Min hourly rate ($)</span>
          <input
            type="number"
            min="0"
            step="5"
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
            value={form.min_hourly_rate}
            onChange={(e) => handleChange("min_hourly_rate", Number(e.target.value))}
          />
        </label>

        {/* Min fixed budget */}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Min fixed budget ($)</span>
          <input
            type="number"
            min="0"
            step="100"
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
            value={form.min_fixed_budget}
            onChange={(e) => handleChange("min_fixed_budget", Number(e.target.value))}
          />
        </label>

        {/* Hourly value */}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Hourly value ($)</span>
          <input
            type="number"
            min="0"
            step="5"
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
            value={form.hourly_value}
            onChange={(e) => handleChange("hourly_value", Number(e.target.value))}
          />
        </label>

        {/* Preferred duration */}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Preferred duration</span>
          <select
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
            value={form.preferred_duration}
            onChange={(e) => handleChange("preferred_duration", e.target.value)}
          >
            <option value="short">Short</option>
            <option value="medium">Medium</option>
            <option value="long">Long</option>
            <option value="any">Any</option>
          </select>
        </label>

        {/* Preferred contract type */}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Preferred contract type</span>
          <select
            className="rounded border border-gray-600 bg-gray-900 px-2 py-1.5 text-sm text-gray-200"
            value={form.preferred_contract_type}
            onChange={(e) => handleChange("preferred_contract_type", e.target.value)}
          >
            <option value="hourly">Hourly</option>
            <option value="fixed">Fixed</option>
            <option value="both">Both</option>
          </select>
        </label>
      </div>

      <button
        type="button"
        className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-blue-50 hover:bg-blue-600 disabled:opacity-50"
        onClick={handleSave}
        disabled={saving}
      >
        {saving ? "Saving..." : "Save"}
      </button>
    </div>
  );
}
