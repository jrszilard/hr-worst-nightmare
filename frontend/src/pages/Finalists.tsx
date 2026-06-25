import { useEffect, useState } from "react";
import type { BudgetStatus, FinalistItem, JobDetail, JobScreeningAnswer, PlanResult, RunResult } from "../lib/api";
import {
  fillPreparedJobApplication,
  getBudget,
  getJob,
  listFinalists,
  planApply,
  runApply,
  updateJobApplication,
} from "../lib/api";

function Bar({ used, cap }: { used: number; cap: number }) {
  const pct = cap > 0 ? Math.min(100, (used / cap) * 100) : 0;
  const warn = pct >= 80;
  return (
    <div className="mt-1 h-2 rounded bg-gray-900">
      <div className={`h-full rounded ${warn ? "bg-amber-600" : "bg-green-700"}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function decodeHtmlEntities(raw: string): string {
  if (!raw) return "";
  return new DOMParser().parseFromString(raw, "text/html").body.textContent ?? "";
}

function isSupportedAssistedApply(job: JobDetail): boolean {
  if (!job.url) return false;
  try {
    const host = new URL(job.url).hostname;
    if (host === "example.com" || host === "www.example.com") return false;
    return ["greenhouse.io", "lever.co", "ashbyhq.com"].some((domain) => host.endsWith(domain));
  } catch {
    return false;
  }
}

function PreparedApplicationCard({
  job,
  awaitingDetail,
  onUpdated,
}: {
  job: JobDetail;
  awaitingDetail?: string;
  onUpdated: (job: JobDetail) => void;
}) {
  const [coverLetter, setCoverLetter] = useState(job.cover_letter ?? "");
  const [answers, setAnswers] = useState<JobScreeningAnswer[]>(job.screening_answers ?? []);
  const [saving, setSaving] = useState(false);
  const [filling, setFilling] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setCoverLetter(job.cover_letter ?? "");
    setAnswers(job.screening_answers ?? []);
    setStatus(null);
  }, [job.id, job.cover_letter, job.screening_answers]);

  async function saveEdits(): Promise<JobDetail> {
    setSaving(true);
    setStatus(null);
    try {
      const updated = await updateJobApplication(job.id, {
        cover_letter: coverLetter,
        screening_answers: answers,
      });
      onUpdated(updated);
      setStatus("Saved edits.");
      return updated;
    } finally {
      setSaving(false);
    }
  }

  const canAssistedApply = isSupportedAssistedApply(job);

  async function handleAssistedApply() {
    if (!canAssistedApply) {
      setStatus("This prepared application uses a sample or unsupported URL, so assisted fill is unavailable.");
      return;
    }
    setFilling(true);
    setStatus(null);
    try {
      const updated = await saveEdits();
      const result = await fillPreparedJobApplication(updated.id);
      setStatus(result.detail || "Filled; awaiting human submit.");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Assisted apply failed");
    } finally {
      setFilling(false);
    }
  }

  return (
    <div className="rounded border border-gray-700 bg-gray-900 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="font-medium text-gray-100">{job.title ?? "Untitled job"}</h4>
          <p className="mt-1 text-xs text-gray-500">
            {job.company || job.platform}
            {job.location && <> · {job.location}</>}
            {job.work_mode === "remote" && <span className="text-emerald-300"> · Remote</span>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <button
            onClick={() => { void saveEdits(); }}
            disabled={saving || filling}
            className="rounded border border-gray-600 px-2 py-1 text-gray-300 hover:border-gray-400 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save edits"}
          </button>
          <button
            onClick={() => { void handleAssistedApply(); }}
            disabled={saving || filling || !coverLetter.trim() || !canAssistedApply}
            className="rounded bg-green-700 px-2 py-1 text-green-50 hover:bg-green-600 disabled:opacity-50"
            title={canAssistedApply
              ? "Saves edits, opens/fills the application, then leaves final submit to you"
              : "Assisted fill only supports real Greenhouse/Lever/Ashby postings; this looks like a sample or unsupported URL"}
          >
            {filling ? "Opening…" : "Apply (assisted fill)"}
          </button>
          <a href={`/jobs?selected=${job.id}`} className="rounded border border-gray-600 px-2 py-1 text-gray-300 hover:border-gray-400">
            View in Jobs
          </a>
          {job.url && (
            <a href={job.url} target="_blank" rel="noopener noreferrer" className="rounded bg-blue-700 px-2 py-1 text-blue-50 hover:bg-blue-600">
              Original posting ↗
            </a>
          )}
        </div>
      </div>

      {awaitingDetail && (
        <p className="mt-3 rounded border border-amber-800 bg-amber-950/30 p-2 text-xs text-amber-200">
          Awaiting your submit: {awaitingDetail}
        </p>
      )}
      {!canAssistedApply && (
        <p className="mt-3 rounded border border-gray-700 bg-gray-950 p-2 text-xs text-gray-400">
          Assisted fill unavailable for this sample/unsupported URL. Use real Greenhouse, Lever, or Ashby postings.
        </p>
      )}
      {status && (
        <p className="mt-3 rounded border border-blue-900 bg-blue-950/30 p-2 text-xs text-blue-200">
          {status}
        </p>
      )}

      <div className="mt-4">
        <h5 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">Cover letter</h5>
        <textarea
          value={coverLetter}
          onChange={(e) => setCoverLetter(e.target.value)}
          className="min-h-72 w-full rounded border border-gray-700 bg-gray-950 p-3 text-sm leading-relaxed text-gray-200"
          placeholder="Cover letter"
        />
      </div>

      {answers.length > 0 && (
        <div className="mt-4">
          <h5 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">Screening answers</h5>
          <div className="space-y-2">
            {answers.map((qa, i) => (
              <div key={i} className="rounded border border-gray-700 bg-gray-950 p-3">
                <p className="text-sm font-medium text-gray-300">{qa.question}</p>
                <textarea
                  value={qa.answer}
                  onChange={(e) => setAnswers((prev) => prev.map((item, idx) => (
                    idx === i ? { ...item, answer: e.target.value } : item
                  )))}
                  className="mt-2 min-h-24 w-full rounded border border-gray-700 bg-gray-900 p-2 text-sm leading-relaxed text-gray-200"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {job.description_excerpt && (
        <details className="mt-4">
          <summary className="cursor-pointer text-xs text-blue-400 hover:text-blue-300">Show posting excerpt</summary>
          <p className="mt-2 text-sm leading-relaxed text-gray-400">{decodeHtmlEntities(job.description_excerpt)}</p>
        </details>
      )}
    </div>
  );
}

export default function Finalists() {
  const [budget, setBudget] = useState<BudgetStatus | null>(null);
  const [items, setItems] = useState<FinalistItem[]>([]);
  const [perRun, setPerRun] = useState<number | "">("");
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [preparedJobs, setPreparedJobs] = useState<JobDetail[]>([]);
  const [preparedLoading, setPreparedLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [plannedCap, setPlannedCap] = useState<number | null>(null);

  async function loadPreparedJobIds(ids: number[]) {
    const uniqueIds = [...new Set(ids)];
    if (uniqueIds.length === 0) {
      setPreparedJobs([]);
      return;
    }
    setPreparedLoading(true);
    try {
      const jobs = await Promise.all(uniqueIds.map((id) => getJob(id)));
      setPreparedJobs(jobs.filter((job) => job.cover_letter || job.screening_answers?.length));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load prepared applications");
    } finally {
      setPreparedLoading(false);
    }
  }

  async function loadExistingPreparedApplications(finalists: FinalistItem[]) {
    await loadPreparedJobIds(finalists.filter((item) => item.kind === "job").map((item) => item.id));
  }

  async function refresh() {
    const [b, f] = await Promise.all([getBudget(), listFinalists()]);
    setBudget(b);
    setItems(f);
    await loadExistingPreparedApplications(f);
  }

  useEffect(() => {
    refresh().catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, []);

  async function loadPreparedApplications(run: RunResult) {
    await loadPreparedJobIds([
      ...run.awaiting_submit.map((item) => item.id),
      ...run.processed.filter((item) => item.kind === "job").map((item) => item.id),
    ]);
  }

  async function handlePlan() {
    setError(null);
    setResult(null);
    const cap = perRun === "" ? null : Number(perRun);
    setPlannedCap(cap);
    try {
      setPlan(await planApply(cap));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Plan failed");
    }
  }

  async function handleConfirm() {
    if (applying) return;
    setApplying(true);
    setError(null);
    setPreparedJobs([]);
    try {
      const r = await runApply(plannedCap);
      setResult(r);
      setPlan(null);
      await loadPreparedApplications(r);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Apply failed");
    } finally {
      setApplying(false);
    }
  }

  if (error) return <p className="text-red-400">{error}</p>;
  if (!budget) return <p className="text-gray-400">Loading…</p>;

  const awaitingById = new Map((result?.awaiting_submit || []).map((item) => [item.id, item.detail]));

  function updatePreparedJob(updated: JobDetail) {
    setPreparedJobs((prev) => prev.map((job) => (job.id === updated.id ? updated : job)));
  }

  return (
    <div className="max-w-5xl space-y-6">
      <h2 className="text-xl font-semibold text-gray-100">Finalists</h2>

      {/* Budget meter */}
      <div className="flex gap-8 rounded border border-gray-700 bg-gray-800 p-4">
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wide text-gray-500">Connects this week</div>
          <div className="text-sm text-gray-200">
            {budget.used.connects} / {budget.config.connects_per_period}
            <span className="text-gray-500"> ({budget.remaining.connects} left)</span>
          </div>
          <Bar used={budget.used.connects} cap={budget.config.connects_per_period} />
        </div>
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wide text-gray-500">Generation this week</div>
          <div className="text-sm text-gray-200">
            {budget.used.generation_apps} / {budget.config.generation_apps_per_period} apps
            <span className="text-gray-500"> · ~${budget.used.generation_dollars.toFixed(2)}</span>
          </div>
          <Bar used={budget.used.generation_apps} cap={budget.config.generation_apps_per_period} />
        </div>
      </div>

      {/* Run cap + lineup */}
      <div className="flex items-center gap-2 text-sm text-gray-400">
        <span className="text-xs uppercase tracking-wide text-gray-500">This run cap</span>
        max <input type="number" min={1} value={perRun} placeholder="—"
          onChange={(e) => setPerRun(e.target.value === "" ? "" : Number(e.target.value))}
          className="w-16 rounded border border-gray-700 bg-gray-900 px-1 text-gray-200" /> apps
        <span className="text-gray-600">· tighter of run-cap vs weekly budget wins</span>
      </div>

      <div className="rounded border border-gray-700 bg-gray-800">
        {items.length === 0 ? (
          <p className="p-4 text-sm text-gray-500">No finalists yet. Promote jobs/contracts from their pages.</p>
        ) : (
          items.map((it) => (
            <div key={it.id} className="flex items-center gap-3 border-b border-gray-700 px-4 py-2 last:border-0">
              <span className="rounded bg-indigo-900 px-2 py-0.5 text-[11px] text-indigo-200">{it.kind}</span>
              <span className="flex-1 truncate text-sm text-gray-100">{it.title ?? "Untitled"}</span>
              <span className="text-xs text-gray-500">{it.connects_cost} connects</span>
              <span className="text-xs text-emerald-300">{it.job_priority.toFixed(2)}</span>
            </div>
          ))
        )}
      </div>

      {items.length > 0 && (
        <button onClick={handlePlan} className="rounded bg-green-700 px-4 py-2 text-sm font-medium text-green-50 hover:bg-green-600">
          Apply finalists
        </button>
      )}

      {/* Confirmation */}
      {plan && (
        <div className="rounded border border-amber-700 bg-amber-950/30 p-4 text-sm">
          <h3 className="font-semibold text-amber-200">Confirm budgeted apply</h3>
          {plan.will_process.length > 0 ? (
            <>
              <p className="mt-1 text-green-300">{plan.will_process.length} finalists · generate + assisted-fill forms</p>
              <p className="text-green-300">{plan.totals.connects} connects reserved · ~${plan.totals.generation_dollars.toFixed(2)} generation</p>
            </>
          ) : (
            <p className="mt-1 text-amber-300">
              No unprepared finalists are left to generate. Prepared applications are shown below.
            </p>
          )}
          {plan.deferred.length > 0 && (
            <p className="mt-1 text-red-300">{plan.deferred.length} deferred (budget/run cap)</p>
          )}
          <p className="mt-2 text-xs text-gray-400">
            Browser-channel finalists are filled in an assisted browser flow and then listed below
            as awaiting your review/submit. The app never clicks the final submit button.
          </p>
          <div className="mt-3 flex gap-2">
            {plan.will_process.length > 0 && (
              <button disabled={applying} onClick={handleConfirm} className="rounded bg-amber-700 px-3 py-1.5 text-amber-50 hover:bg-amber-600 disabled:opacity-50">{applying ? "Running…" : "Confirm & run"}</button>
            )}
            <button onClick={() => setPlan(null)} className="rounded border border-gray-600 px-3 py-1.5 text-gray-300">Cancel</button>
          </div>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="rounded border border-gray-700 bg-gray-800 p-4 text-sm">
          <p className="text-green-300">
            {result.processed.length > 0
              ? `Prepared ${result.processed.length} application(s).`
              : "No new applications prepared; all current finalist applications were already generated."}
          </p>
          {result.awaiting_submit.length > 0 && (
            <p className="text-amber-300">{result.awaiting_submit.length} awaiting your manual review + submit.</p>
          )}
          {result.deferred.length > 0 && <p className="text-amber-300">Deferred {result.deferred.length}.</p>}
          <p className="mt-1 text-xs text-gray-400">
            Connects remaining: {result.remaining.connects} · generation remaining: {result.remaining.generation_apps} apps
          </p>
        </div>
      )}

      {preparedLoading && <p className="text-sm text-gray-400">Loading prepared applications…</p>}

      {preparedJobs.length > 0 && (
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-100">Prepared applications</h3>
            <p className="text-xs text-gray-500">
              Review these before clicking submit on the original posting. Generated text is saved; final submit is manual.
            </p>
          </div>
          {preparedJobs.map((job) => (
            <PreparedApplicationCard
              key={job.id}
              job={job}
              awaitingDetail={awaitingById.get(job.id) || "Prepared already; review and submit manually."}
              onUpdated={updatePreparedJob}
            />
          ))}
        </div>
      )}
    </div>
  );
}
