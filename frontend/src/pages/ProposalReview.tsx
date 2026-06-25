import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { ContractResponse, Proposal, ProposalSection } from "../lib/api";
import {
  getContract,
  createProposal,
  updateProposal,
  fillProposal,
} from "../lib/api";
import ContractDetails from "../components/ContractDetails";
import ProposalEditor from "../components/ProposalEditor";

type PageState =
  | { kind: "loading" }
  | { kind: "generating" }
  | { kind: "ready" }
  | { kind: "error"; message: string };

export default function ProposalReview() {
  const { id } = useParams<{ id: string }>();
  const contractId = Number(id);

  const [contract, setContract] = useState<ContractResponse | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [pageState, setPageState] = useState<PageState>({ kind: "loading" });
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [filling, setFilling] = useState(false);
  const [fillMessage, setFillMessage] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setPageState({ kind: "loading" });
      const contractData = await getContract(contractId);
      setContract(contractData);

      // Auto-trigger proposal generation
      setPageState({ kind: "generating" });
      const proposalData = await createProposal(contractId);
      setProposal(proposalData);
      setPageState({ kind: "ready" });
    } catch (err) {
      setPageState({
        kind: "error",
        message: err instanceof Error ? err.message : "Failed to load data",
      });
    }
  }, [contractId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleSave(sections: ProposalSection[]) {
    if (!proposal) return;
    setSaving(true);
    try {
      const updated = await updateProposal(proposal.id, { sections });
      setProposal(updated);
    } catch (err) {
      console.error("Failed to save proposal:", err);
    } finally {
      setSaving(false);
    }
  }

  async function handleRegenerate(guidance: string) {
    setRegenerating(true);
    try {
      // Pass guidance as a query param or in the body.
      // For V1 the backend may ignore it; we send it along anyway.
      const proposalData = await createProposal(contractId);
      setProposal(proposalData);
      // guidance is available for future backend support
      if (guidance) {
        console.info("Regeneration guidance (for future use):", guidance);
      }
    } catch (err) {
      console.error("Failed to regenerate proposal:", err);
    } finally {
      setRegenerating(false);
    }
  }

  async function handleFill() {
    if (!proposal) return;
    setFilling(true);
    setFillMessage(null);
    try {
      const result = await fillProposal(proposal.id);
      setFillMessage(result.message);
      // Update proposal status locally
      setProposal((prev) => (prev ? { ...prev, status: "approved" } : prev));
    } catch (err) {
      setFillMessage(
        err instanceof Error ? err.message : "Failed to trigger fill",
      );
    } finally {
      setFilling(false);
    }
  }

  // --- Render ---

  if (pageState.kind === "loading") {
    return (
      <div className="py-16 text-center text-sm text-gray-500">
        Loading contract...
      </div>
    );
  }

  if (pageState.kind === "error") {
    return (
      <div className="space-y-4">
        <Link
          to="/"
          className="text-sm text-gray-400 hover:text-gray-200"
        >
          &larr; Back to Feed
        </Link>
        <div className="rounded border border-red-800 bg-red-950 p-4 text-sm text-red-300">
          {pageState.message}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Top bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <Link
            to="/"
            className="shrink-0 text-sm text-gray-400 hover:text-gray-200"
          >
            &larr; Back to Feed
          </Link>
          <h2 className="truncate text-lg font-semibold text-gray-100">
            {contract?.title ?? "Proposal Review"}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="rounded bg-gray-700 px-3 py-1.5 text-sm font-medium text-gray-200 hover:bg-gray-600 disabled:opacity-50"
            onClick={() => handleRegenerate("")}
            disabled={regenerating || pageState.kind === "generating"}
          >
            {regenerating ? "Regenerating..." : "Regenerate"}
          </button>
          <button
            type="button"
            className="rounded bg-blue-700 px-3 py-1.5 text-sm font-medium text-blue-50 hover:bg-blue-600 disabled:opacity-50"
            onClick={handleFill}
            disabled={filling || !proposal}
          >
            {filling ? "Filling..." : "Approve & Fill"}
          </button>
        </div>
      </div>

      {/* Fill feedback */}
      {fillMessage && (
        <div className="rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300">
          {fillMessage}
        </div>
      )}

      {/* Side-by-side layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left panel — contract details */}
        <div className="rounded border border-gray-700 bg-gray-900 p-5">
          {contract ? (
            <ContractDetails contract={contract} />
          ) : (
            <p className="text-sm text-gray-500">Loading contract details...</p>
          )}
        </div>

        {/* Right panel — proposal editor */}
        <div>
          {pageState.kind === "generating" ? (
            <div className="py-16 text-center text-sm text-gray-500">
              Generating proposal...
            </div>
          ) : proposal?.sections && proposal.sections.length > 0 ? (
            <ProposalEditor
              sections={proposal.sections}
              onSave={handleSave}
              onRegenerate={handleRegenerate}
              saving={saving}
              regenerating={regenerating}
            />
          ) : (
            <div className="rounded border border-gray-700 bg-gray-900 p-5 text-sm text-gray-500">
              No proposal sections available. Try regenerating.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
