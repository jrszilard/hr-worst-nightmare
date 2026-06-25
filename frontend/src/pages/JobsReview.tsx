import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { JobBucket, JobDetail, JobListItem, SkillWeight } from "../lib/api";
import { getJob, getPreferences, listJobs, setFinalist, setJobApplied, setJobFeedback } from "../lib/api";
import JobsScanButton from "../components/JobsScanButton";

const bucketOrder: JobBucket[] = ["finalist", "candidate", "applied", "skipped"];
const bucketLabels: Record<JobBucket, string> = {
  finalist: "Finalist",
  candidate: "Candidate",
  applied: "Applied",
  skipped: "Skipped",
};
const bucketPill: Record<JobBucket, string> = {
  finalist: "bg-indigo-700 text-indigo-50",
  candidate: "bg-blue-600 text-blue-50",
  applied: "bg-green-700 text-green-50",
  skipped: "bg-gray-500 text-gray-100",
};

type WorkMode = "remote" | "location";
type CompanyGroup = { company: string; items: JobListItem[]; maxPriority: number };

const workModeOrder: WorkMode[] = ["remote", "location"];
const workModeLabels: Record<WorkMode, string> = {
  remote: "Remote-friendly",
  location: "Location-based / hybrid",
};

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  return new Date(dateStr).toLocaleDateString();
}

// Stored descriptions carry raw HTML entities (&mdash;, &nbsp;, &amp;). Parsing
// as HTML and reading textContent decodes them and strips any stray tags via the
// browser parser — no dangerouslySetInnerHTML, so nothing scraped can execute.
function decodeHtmlEntities(raw: string): string {
  if (!raw) return "";
  return new DOMParser().parseFromString(raw, "text/html").body.textContent ?? "";
}

function displayCompany(job: { company?: string | null; platform: string }): string {
  return job.company || job.platform;
}

function groupKey(bucket: JobBucket, workMode: WorkMode, company: string): string {
  return `${bucket}:${workMode}:${company}`;
}

function jobWorkMode(job: { work_mode?: string }): WorkMode {
  return job.work_mode === "remote" ? "remote" : "location";
}

function groupByCompany(items: JobListItem[]): CompanyGroup[] {
  const map = new Map<string, JobListItem[]>();
  for (const item of items) {
    const company = displayCompany(item);
    map.set(company, [...(map.get(company) || []), item]);
  }
  return [...map.entries()]
    .map(([company, groupItems]) => ({
      company,
      items: groupItems,
      maxPriority: Math.max(...groupItems.map((j) => j.job_priority)),
    }))
    .sort((a, b) => b.maxPriority - a.maxPriority || a.company.localeCompare(b.company));
}

function ChannelBadge({ channel }: { channel?: string }) {
  const isAuto = channel === "auto";
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
        isAuto ? "bg-teal-700 text-teal-50" : "bg-gray-600 text-gray-200"
      }`}
      title={isAuto ? "Auto-submitted after the apply gate" : "Manual submit (you click submit)"}
    >
      {isAuto ? "auto" : "assisted"}
    </span>
  );
}

export default function JobsReview() {
  const [searchParams] = useSearchParams();
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDescription, setShowDescription] = useState(false);
  const [prefs, setPrefs] = useState<SkillWeight[]>([]);
  const [showPrefs, setShowPrefs] = useState(false);
  const [query, setQuery] = useState("");
  const [companyFilter, setCompanyFilter] = useState("all");
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});

  async function refreshList() {
    const data = await listJobs();
    setJobs(data);
    return data;
  }

  useEffect(() => {
    refreshList()
      .then((data) => {
        const selectedParam = Number(searchParams.get("selected"));
        const requested = Number.isFinite(selectedParam)
          ? data.find((j) => j.id === selectedParam)
          : null;
        const firstSelectable = data.find((j) => j.bucket !== "skipped");
        if (requested) setSelectedId(requested.id);
        else if (firstSelectable) setSelectedId(firstSelectable.id);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load jobs"),
      )
      .finally(() => setLoading(false));
  }, [searchParams]);

  async function refreshPrefs() {
    try {
      setPrefs(await getPreferences());
    } catch {
      /* preferences are non-critical; ignore */
    }
  }

  useEffect(() => { void refreshPrefs(); }, []);

  useEffect(() => {
    setShowDescription(true);
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    getJob(selectedId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load job");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  async function handleToggleApplied() {
    if (!detail) return;
    try {
      const updated = await setJobApplied(detail.id, !detail.applied);
      setDetail(updated);
      await refreshList();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update job");
    }
  }

  async function handleFeedback(next: "liked" | "disliked") {
    if (!detail) return;
    const value = detail.feedback === next ? null : next; // toggle off if same
    try {
      const updated = await setJobFeedback(detail.id, value);
      setDetail(updated);
      await refreshList();   // re-ranked
      await refreshPrefs();  // updated weights
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to set feedback");
    }
  }

  const selectedJob = jobs.find((j) => j.id === selectedId) || null;
  const normalizedQuery = query.trim().toLowerCase();
  const companies = useMemo(
    () => [...new Set(jobs.map(displayCompany))].sort((a, b) => a.localeCompare(b)),
    [jobs],
  );
  const filteredJobs = useMemo(() => jobs.filter((job) => {
    const company = displayCompany(job);
    if (companyFilter !== "all" && company !== companyFilter) return false;
    if (!normalizedQuery) return true;
    const haystack = [
      job.title,
      company,
      job.location,
      job.bucket,
      job.work_mode,
      job.description_excerpt,
      ...(job.skills_required || []),
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(normalizedQuery);
  }), [jobs, companyFilter, normalizedQuery]);

  const grouped = bucketOrder.map((bucket) => ({
    bucket,
    items: filteredJobs.filter((j) => j.bucket === bucket),
  }));

  const learnedPrefs = prefs.filter((p) => p.weight !== 0);

  function isGroupCollapsed(bucket: JobBucket, workMode: WorkMode, company: string, items: JobListItem[]): boolean {
    if (normalizedQuery) return false;
    if (items.some((item) => item.id === selectedId)) return false;
    const key = groupKey(bucket, workMode, company);
    return collapsedGroups[key] ?? (bucket === "candidate" || bucket === "skipped");
  }

  function setAllGroupsCollapsed(collapsed: boolean) {
    const next: Record<string, boolean> = {};
    for (const { bucket, items } of grouped) {
      for (const workMode of workModeOrder) {
        const laneItems = items.filter((job) => jobWorkMode(job) === workMode);
        for (const group of groupByCompany(laneItems)) {
          next[groupKey(bucket, workMode, group.company)] = collapsed;
        }
      }
    }
    setCollapsedGroups(next);
  }

  function renderJobButton(job: JobListItem) {
    const isSkipped = job.bucket === "skipped";
    const isSelected = job.id === selectedId;
    return (
      <button
        key={job.id}
        disabled={isSkipped}
        onClick={() => setSelectedId(job.id)}
        className={`w-full rounded border p-2 text-left transition-colors ${
          isSelected
            ? "border-gray-400 bg-gray-700"
            : "border-gray-700 bg-gray-800"
        } ${isSkipped ? "opacity-50" : "hover:border-gray-500"}`}
      >
        <div className="flex items-start justify-between gap-2">
          <span className="flex-1 truncate text-sm text-gray-100">
            {job.title ?? "Untitled job"}
          </span>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${bucketPill[job.bucket]}`}
          >
            {bucketLabels[job.bucket]}
          </span>
          <ChannelBadge channel={job.submission_channel} />
          {job.flag_count > 0 && (
            <span className="shrink-0 rounded-full bg-red-900/60 px-2 py-0.5 text-[11px] text-red-300">
              {job.flag_count} flag{job.flag_count > 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="mt-1 text-xs text-gray-400">
          <span className="text-gray-300">{displayCompany(job)}</span>
          <span className={jobWorkMode(job) === "remote" ? "text-emerald-300" : "text-gray-400"}>
            {' '}· {jobWorkMode(job) === "remote" ? "Remote" : "Location"}
          </span>
          {job.location && <> · {job.location}</>}
        </div>
        <div className="mt-1 text-xs text-gray-400">
          priority{" "}
          <span className="text-emerald-300">
            {job.job_priority.toFixed(2)}
          </span>
          {job.match_score != null && (
            <> · match {job.match_score.toFixed(2)}</>
          )}
          {isSkipped && job.skip_reason && <> · {job.skip_reason}</>}
          {job.bucket === "applied" && job.applied_at && (
            <> · {formatDate(job.applied_at)}</>
          )}
        </div>
        {job.skills_required && job.skills_required.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {job.skills_required.slice(0, 4).map((skill) => (
              <span key={skill} className="rounded bg-gray-700 px-1.5 py-0.5 text-[10px] text-gray-300">
                {skill}
              </span>
            ))}
            {job.skills_required.length > 4 && (
              <span className="text-[10px] text-gray-500">+{job.skills_required.length - 4}</span>
            )}
          </div>
        )}
        {job.description_excerpt && (
          <p className="mt-1 line-clamp-3 text-xs leading-snug text-gray-500">
            {decodeHtmlEntities(job.description_excerpt)}
          </p>
        )}
      </button>
    );
  }

  if (loading) return <p className="text-gray-400">Loading jobs…</p>;
  if (error) return <p className="text-red-400">{error}</p>;
  if (jobs.length === 0) {
    return (
      <div className="text-gray-400">
        <p className="text-lg text-gray-200">No screened jobs yet.</p>
        <p className="mt-2 text-sm">
          Run <code className="text-gray-300">python scripts/screen_and_store_jobs.py</code>{" "}
          to screen the jobs in <code className="text-gray-300">data/jobs_to_screen.yaml</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-medium text-gray-100">Jobs</h1>
          <p className="text-xs text-gray-500">
            {filteredJobs.length.toLocaleString()} shown of {jobs.length.toLocaleString()}
            {selectedJob && <> · selected {displayCompany(selectedJob)}</>}
          </p>
        </div>
        <JobsScanButton onComplete={() => { void refreshList(); }} />
      </div>
      {learnedPrefs.length > 0 && (
        <div className="rounded border border-gray-700 bg-gray-800 p-3">
          <button
            onClick={() => setShowPrefs((s) => !s)}
            className="text-xs font-semibold uppercase tracking-wide text-gray-400 hover:text-gray-200"
          >
            What I've learned ({learnedPrefs.length} skills) {showPrefs ? "▾" : "▸"}
          </button>
          {showPrefs && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {learnedPrefs.map((p) => (
                  <span
                    key={p.skill}
                    className={`rounded-full px-2 py-0.5 text-[11px] ${
                      p.weight > 0
                        ? "bg-green-900/50 text-green-200"
                        : "bg-red-900/50 text-red-200"
                    }`}
                  >
                    {p.skill} {p.weight > 0 ? "+" : ""}{p.weight.toFixed(2)}
                  </span>
                ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-start gap-6">
        {/* Left: independently scrolling grouped list */}
        <div className="sticky top-4 w-[27rem] shrink-0 space-y-3 self-start">
          <div className="rounded border border-gray-700 bg-gray-900 p-3">
            <div className="grid grid-cols-1 gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search title, company, skill, location…"
                className="rounded border border-gray-700 bg-gray-950 px-2 py-1.5 text-sm text-gray-200 placeholder:text-gray-600"
              />
              <select
                value={companyFilter}
                onChange={(e) => setCompanyFilter(e.target.value)}
                className="rounded border border-gray-700 bg-gray-950 px-2 py-1.5 text-sm text-gray-200"
              >
                <option value="all">All companies</option>
                {companies.map((company) => (
                  <option key={company} value={company}>{company}</option>
                ))}
              </select>
            </div>
            <div className="mt-2 flex gap-2 text-xs">
              <button
                onClick={() => setAllGroupsCollapsed(false)}
                className="rounded border border-gray-700 px-2 py-1 text-gray-300 hover:border-gray-500"
              >
                Expand groups
              </button>
              <button
                onClick={() => setAllGroupsCollapsed(true)}
                className="rounded border border-gray-700 px-2 py-1 text-gray-300 hover:border-gray-500"
              >
                Collapse groups
              </button>
            </div>
          </div>

          <div className="max-h-[calc(100vh-17rem)] space-y-4 overflow-y-auto pr-2">
            {grouped.map(({ bucket, items }) =>
              items.length === 0 ? null : (
                <div key={bucket}>
                  <h2 className="sticky top-0 z-10 mb-1 bg-gray-950 py-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    {bucketLabels[bucket]} ({items.length})
                  </h2>
                  <div className="space-y-3">
                    {workModeOrder.map((workMode) => {
                      const laneItems = items.filter((job) => jobWorkMode(job) === workMode);
                      if (laneItems.length === 0) return null;
                      return (
                        <div key={`${bucket}:${workMode}`} className="space-y-2">
                          <div className="flex items-center justify-between rounded bg-gray-900 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
                            <span>{workMode === "remote" ? "🌐" : "📍"} {workModeLabels[workMode]}</span>
                            <span>{laneItems.length}</span>
                          </div>
                          {groupByCompany(laneItems).map((group) => {
                            const collapsed = isGroupCollapsed(bucket, workMode, group.company, group.items);
                            const key = groupKey(bucket, workMode, group.company);
                            return (
                              <div key={key} className="rounded border border-gray-800 bg-gray-900/40">
                                <button
                                  onClick={() => setCollapsedGroups((prev) => ({
                                    ...prev,
                                    [key]: !collapsed,
                                  }))}
                                  className="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-xs text-gray-300 hover:bg-gray-800"
                                >
                                  <span className="truncate font-medium">{collapsed ? "▸" : "▾"} {group.company}</span>
                                  <span className="shrink-0 text-gray-500">
                                    {group.items.length} · best {group.maxPriority.toFixed(2)}
                                  </span>
                                </button>
                                {!collapsed && (
                                  <div className="space-y-1 border-t border-gray-800 p-1.5">
                                    {group.items.map(renderJobButton)}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ),
            )}
          </div>
        </div>

        {/* Right: sticky, independently scrolling detail */}
        <div className="sticky top-4 max-h-[calc(100vh-8rem)] min-w-0 flex-1 overflow-y-auto pr-2">
          {!detail ? (
            <p className="text-gray-400">Select a job to view its application.</p>
          ) : (
            <div className="space-y-5">
              <div className="rounded border border-gray-800 bg-gray-900/40 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-lg font-medium text-gray-100">
                      {detail.title ?? "Untitled job"}
                    </h2>
                    <p className="mt-1 text-xs text-gray-400">
                      <span className="text-gray-300">{displayCompany(detail)}</span>
                      <span className={jobWorkMode(detail) === "remote" ? "text-emerald-300" : "text-gray-400"}>
                        {' '}· {jobWorkMode(detail) === "remote" ? "Remote" : "Location"}
                      </span>
                      {detail.location && <> · {detail.location}</>}
                      <> · priority {detail.job_priority.toFixed(2)}</>
                      {detail.match_score != null && <> · match {detail.match_score.toFixed(2)}</>}
                      {detail.description_fit != null && (
                        <> · fit {detail.description_fit.toFixed(2)}</>
                      )}
                    </p>
                    {detail.skills_required && detail.skills_required.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {detail.skills_required.map((skill) => (
                          <span key={skill} className="rounded-full bg-gray-800 px-2 py-0.5 text-[11px] text-gray-300">
                            {skill}
                          </span>
                        ))}
                      </div>
                    )}
                    {detail.url && (
                      <p className="mt-2 text-xs">
                        <span className="text-gray-500">{detail.platform}</span>{" "}
                        <a
                          href={detail.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-400 hover:text-blue-300 hover:underline"
                        >
                          · View original posting ↗
                        </a>
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="flex items-center gap-1 text-xs text-gray-300">
                      <input
                        type="checkbox"
                        checked={detail.is_finalist}
                        onChange={async (e) => {
                          const next = e.target.checked;
                          setDetail((d) => (d ? { ...d, is_finalist: next } : d));
                          try {
                            await setFinalist(detail.id, next);
                            await refreshList();
                          } catch (err) {
                            setDetail((d) => (d ? { ...d, is_finalist: !next } : d));
                            setError(err instanceof Error ? err.message : "Failed to update finalist");
                          }
                        }}
                      />
                      Finalist
                    </label>
                    <button
                      onClick={handleToggleApplied}
                      disabled={!detail.cover_letter && !detail.applied}
                      title={!detail.cover_letter && !detail.applied
                        ? "Generate an application first (promote to finalist, then Apply)"
                        : undefined}
                      className={`shrink-0 rounded px-3 py-1.5 text-sm font-medium ${
                        detail.applied
                          ? "border border-green-700 text-green-300"
                          : !detail.cover_letter
                            ? "cursor-not-allowed bg-gray-700 text-gray-500"
                            : "bg-green-700 text-green-50 hover:bg-green-600"
                      }`}
                    >
                      {detail.applied ? "Applied ✓ (undo)" : "Mark applied"}
                    </button>
                    <button
                      onClick={() => handleFeedback("liked")}
                      title="More like this"
                      className={`rounded px-2 py-1 text-sm ${
                        detail.feedback === "liked"
                          ? "bg-green-700 text-green-50"
                          : "border border-gray-700 text-gray-300 hover:border-gray-500"
                      }`}
                    >
                      👍
                    </button>
                    <button
                      onClick={() => handleFeedback("disliked")}
                      title="Less like this"
                      className={`rounded px-2 py-1 text-sm ${
                        detail.feedback === "disliked"
                          ? "bg-red-800 text-red-50"
                          : "border border-gray-700 text-gray-300 hover:border-gray-500"
                      }`}
                    >
                      👎
                    </button>
                  </div>
                </div>
              </div>

              {detail.review_flags && detail.review_flags.length > 0 && (
                <div className="rounded border border-amber-900/60 bg-amber-950/30 p-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-400">
                    Review flags ({detail.review_flags.length})
                  </h3>
                  <ul className="mt-2 space-y-1 text-xs text-amber-200">
                    {detail.review_flags.map((flag, i) => (
                      <li key={i}>{JSON.stringify(flag)}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Job description
                </h3>
                {detail.description ? (
                  <>
                    <button
                      onClick={() => setShowDescription((s) => !s)}
                      className="text-xs text-blue-400 hover:text-blue-300 hover:underline"
                    >
                      {showDescription
                        ? "Hide full description"
                        : `Show full description (${detail.description.length.toLocaleString()} chars)`}
                    </button>
                    {showDescription && (
                      <div className="mt-2 max-h-96 overflow-y-auto whitespace-pre-wrap rounded border border-gray-700 bg-gray-900 p-3 text-sm leading-relaxed text-gray-300">
                        {decodeHtmlEntities(detail.description)}
                      </div>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-gray-500">No description stored.</p>
                )}
              </div>

              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Cover letter
                </h3>
                <div className="whitespace-pre-wrap rounded border border-gray-700 bg-gray-900 p-3 text-sm leading-relaxed text-gray-200">
                  {detail.cover_letter ?? "Not generated yet — runs at apply-time for finalists."}
                </div>
              </div>

              {detail.screening_answers && detail.screening_answers.length > 0 && (
                <div>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Screening answers
                  </h3>
                  <div className="space-y-3">
                    {detail.screening_answers.map((qa, i) => (
                      <div
                        key={i}
                        className="rounded border border-gray-700 bg-gray-900 p-3"
                      >
                        <p className="text-sm font-medium text-gray-300">{qa.question}</p>
                        <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-gray-200">
                          {qa.answer}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
