import { useState, useEffect } from "react";
import AvailabilityForm from "../components/AvailabilityForm";
import { getBudget, updateBudget, type BudgetConfig, getProfileYaml, putProfileYaml } from "../lib/api";

// Hard-coded from data/profile.yaml — displayed read-only in V1
const coreSkills = [
  "Power BI",
  "Tableau",
  "DAX",
  "SQL",
  "Data modeling",
  "Python",
  "LangChain",
  "Anthropic Claude API",
  "OpenAI API",
  "RAG pipelines",
  "AI agents",
  "Pandas",
  "ETL",
  "REST APIs",
  "Database design",
  "Process automation",
];

const adjacentSkills = [
  "React",
  "TypeScript",
  "Node.js",
  "FastAPI",
  "Docker",
  "AWS",
  "PostgreSQL",
  "Git",
];

// Hard-coded from data/searches.yaml — displayed read-only in V1
const savedSearches = [
  { name: "Power BI", query: "Power BI dashboard", category: "reporting" },
  { name: "Python Automation", query: "Python automation scripting", category: "data" },
  { name: "AI LLM", query: "AI LLM chatbot integration", category: "ai" },
  { name: "Tableau", query: "Tableau dashboard visualization", category: "reporting" },
];

export default function Settings() {
  const [budget, setBudget] = useState<BudgetConfig | null>(null);
  const [budgetSaveMsg, setBudgetSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [profileYaml, setProfileYaml] = useState<string>("");
  const [profileMsg, setProfileMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    getBudget().then((b) => setBudget(b.config)).catch(() => {});
  }, []);

  useEffect(() => {
    getProfileYaml().then(setProfileYaml).catch(() => setProfileYaml(""));
  }, []);

  async function saveProfile() {
    setProfileMsg(null);
    try {
      await putProfileYaml(profileYaml);
      setProfileMsg({ ok: true, text: "Profile saved." });
    } catch (e) {
      setProfileMsg({ ok: false, text: e instanceof Error ? e.message : "Save failed." });
    }
    setTimeout(() => setProfileMsg(null), 3000);
  }

  async function saveBudget() {
    if (!budget) return;
    setBudgetSaveMsg(null);
    try {
      await updateBudget(budget);
      setBudgetSaveMsg({ ok: true, text: "Budget saved." });
    } catch (e) {
      setBudgetSaveMsg({ ok: false, text: e instanceof Error ? e.message : "Save failed." });
    }
    setTimeout(() => setBudgetSaveMsg(null), 3000);
  }

  return (
    <div className="space-y-8">
      <h2 className="text-xl font-semibold text-gray-100">Settings</h2>

      {/* ── Availability ────────────────────────────────────────────── */}
      <section className="space-y-3">
        <h3 className="text-lg font-medium text-gray-200">Availability</h3>
        <div className="rounded border border-gray-700 bg-gray-800 p-4">
          <AvailabilityForm />
        </div>
      </section>

      {/* ── Apply Budget ────────────────────────────────────────────── */}
      <section className="space-y-3">
        <h3 className="text-lg font-medium text-gray-200">Apply Budget</h3>
        {budget && (
          <section className="rounded border border-gray-700 bg-gray-800 p-4">
            <h3 className="mb-3 text-sm font-semibold text-gray-100">Apply budget (per week)</h3>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <label className="text-gray-400">Connects / week
                <input type="number" value={budget.connects_per_period}
                  onChange={(e) => setBudget({ ...budget, connects_per_period: Number(e.target.value) })}
                  className="mt-1 w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-100" />
              </label>
              <label className="text-gray-400">Generations / week
                <input type="number" value={budget.generation_apps_per_period}
                  onChange={(e) => setBudget({ ...budget, generation_apps_per_period: Number(e.target.value) })}
                  className="mt-1 w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-100" />
              </label>
              <label className="text-gray-400">Generation $ / week (enforced)
                <input type="number" step="0.5" value={budget.generation_dollars_per_period}
                  onChange={(e) => setBudget({ ...budget, generation_dollars_per_period: Number(e.target.value) })}
                  className="mt-1 w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-100" />
              </label>
              <label className="text-gray-400">Default per-run cap
                <input type="number" value={budget.per_run_max_apps ?? ""}
                  onChange={(e) => setBudget({ ...budget, per_run_max_apps: e.target.value === "" ? null : Number(e.target.value) })}
                  className="mt-1 w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-100" />
              </label>
            </div>
            <button onClick={saveBudget} className="mt-3 rounded bg-green-700 px-3 py-1.5 text-sm text-green-50 hover:bg-green-600">Save budget</button>
            {budgetSaveMsg && (
              <span className={`ml-3 text-xs ${budgetSaveMsg.ok ? "text-green-400" : "text-red-400"}`}>
                {budgetSaveMsg.text}
              </span>
            )}
          </section>
        )}
      </section>

      {/* ── Profile (review generated profile.yaml) ── */}
      <section className="space-y-3">
        <h3 className="text-lg font-medium text-gray-200">Profile</h3>
        <div className="rounded border border-gray-700 bg-gray-800 p-4 space-y-3">
          <p className="text-xs text-gray-500">
            Generated by <code className="text-gray-400">./onboard.sh</code>. Review and edit, then save.
          </p>
          <textarea
            value={profileYaml}
            onChange={(e) => setProfileYaml(e.target.value)}
            rows={20}
            className="w-full rounded border border-gray-700 bg-gray-900 px-2 py-1 font-mono text-xs text-gray-100"
          />
          <button onClick={saveProfile} className="rounded bg-green-700 px-3 py-1.5 text-sm text-green-50 hover:bg-green-600">
            Save profile
          </button>
          {profileMsg && (
            <span className={`ml-3 text-xs ${profileMsg.ok ? "text-green-400" : "text-red-400"}`}>
              {profileMsg.text}
            </span>
          )}
        </div>
      </section>

      {/* ── Skills (read-only) ──────────────────────────────────────── */}
      <section className="space-y-3">
        <h3 className="text-lg font-medium text-gray-200">Skills</h3>
        <div className="rounded border border-gray-700 bg-gray-800 p-4 space-y-4">
          <div>
            <p className="text-xs font-medium text-gray-400 mb-2">Core Skills</p>
            <div className="flex flex-wrap gap-2">
              {coreSkills.map((skill) => (
                <span
                  key={skill}
                  className="inline-flex items-center gap-1.5 rounded bg-gray-700 px-2 py-1 text-xs text-gray-200"
                >
                  {skill}
                  <span className="rounded bg-blue-700 px-1 py-0.5 text-[10px] font-semibold text-blue-100">
                    1.0
                  </span>
                </span>
              ))}
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-gray-400 mb-2">Adjacent Skills</p>
            <div className="flex flex-wrap gap-2">
              {adjacentSkills.map((skill) => (
                <span
                  key={skill}
                  className="inline-flex items-center gap-1.5 rounded bg-gray-700 px-2 py-1 text-xs text-gray-200"
                >
                  {skill}
                  <span className="rounded bg-gray-600 px-1 py-0.5 text-[10px] font-semibold text-gray-300">
                    0.6
                  </span>
                </span>
              ))}
            </div>
          </div>

          <p className="text-xs text-gray-500">
            Edit skills in <code className="text-gray-400">data/profile.yaml</code>
          </p>
        </div>
      </section>

      {/* ── Search Configs (read-only) ──────────────────────────────── */}
      <section className="space-y-3">
        <h3 className="text-lg font-medium text-gray-200">Saved Searches</h3>
        <div className="rounded border border-gray-700 bg-gray-800 p-4 space-y-3">
          <div className="space-y-2">
            {savedSearches.map((search) => (
              <div
                key={search.name}
                className="flex items-center justify-between rounded border border-gray-700 bg-gray-900 px-3 py-2"
              >
                <div>
                  <p className="text-sm font-medium text-gray-200">{search.name}</p>
                  <p className="text-xs text-gray-500">{search.query}</p>
                </div>
                <span className="rounded bg-gray-700 px-2 py-0.5 text-[11px] text-gray-400">
                  {search.category}
                </span>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-500">
            Edit searches in <code className="text-gray-400">data/searches.yaml</code>
          </p>
        </div>
      </section>
    </div>
  );
}
