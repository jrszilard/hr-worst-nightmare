import { useState } from "react";
import type { ProposalSection } from "../lib/api";
import AnnotationMarker from "./AnnotationMarker";

const sectionBorders: Record<string, string> = {
  hook: "border-l-green-500",
  experience: "border-l-blue-500",
  approach: "border-l-orange-500",
  differentiator: "border-l-purple-500",
  cta: "border-l-teal-500",
};

const sectionOrder = ["hook", "experience", "approach", "differentiator", "cta"];

interface ProposalEditorProps {
  sections: ProposalSection[];
  onSave: (sections: ProposalSection[]) => void;
  onRegenerate: (guidance: string) => void;
  saving: boolean;
  regenerating: boolean;
}

export default function ProposalEditor({
  sections,
  onSave,
  onRegenerate,
  saving,
  regenerating,
}: ProposalEditorProps) {
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [editingType, setEditingType] = useState<string | null>(null);
  const [showGuidance, setShowGuidance] = useState(false);
  const [guidance, setGuidance] = useState("");

  const hasEdits = Object.keys(edited).length > 0;

  // Sort sections according to defined order, keeping any extras at the end
  const sorted = [...sections].sort((a, b) => {
    const ai = sectionOrder.indexOf(a.type);
    const bi = sectionOrder.indexOf(b.type);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });

  function handleContentChange(type: string, value: string) {
    const original = sections.find((s) => s.type === type);
    if (original && original.content === value) {
      // Revert: remove from edited map
      setEdited((prev) => {
        const next = { ...prev };
        delete next[type];
        return next;
      });
    } else {
      setEdited((prev) => ({ ...prev, [type]: value }));
    }
  }

  function handleSave() {
    const updated = sections.map((s) =>
      edited[s.type] !== undefined ? { ...s, content: edited[s.type] } : s,
    );
    onSave(updated);
    setEdited({});
    setEditingType(null);
  }

  function handleRegenerate() {
    onRegenerate(guidance);
    setGuidance("");
    setShowGuidance(false);
  }

  return (
    <div className="space-y-4">
      {sorted.map((section) => {
        const isEditing = editingType === section.type;
        const currentContent = edited[section.type] ?? section.content;
        const borderClass = sectionBorders[section.type] ?? "border-l-gray-500";

        return (
          <div
            key={section.type}
            className={`rounded border border-gray-700 bg-gray-800 border-l-4 ${borderClass}`}
          >
            <div className="px-4 py-3">
              {/* Header row */}
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wider text-gray-400">
                  {section.type}
                </span>
                <AnnotationMarker annotation={section.annotation} />
              </div>

              {/* Content */}
              {isEditing ? (
                <textarea
                  className="w-full rounded border border-gray-600 bg-gray-900 px-3 py-2 text-sm leading-relaxed text-gray-200 focus:border-gray-400 focus:outline-none"
                  rows={5}
                  value={currentContent}
                  onChange={(e) => handleContentChange(section.type, e.target.value)}
                  onBlur={() => setEditingType(null)}
                  autoFocus
                />
              ) : (
                <p
                  className="cursor-text whitespace-pre-wrap text-sm leading-relaxed text-gray-300 hover:text-gray-100"
                  onClick={() => setEditingType(section.type)}
                >
                  {currentContent || "(empty)"}
                </p>
              )}
            </div>
          </div>
        );
      })}

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-3 pt-2">
        {hasEdits && (
          <button
            type="button"
            className="rounded bg-green-700 px-4 py-2 text-sm font-medium text-green-50 hover:bg-green-600 disabled:opacity-50"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        )}

        <button
          type="button"
          className="rounded bg-gray-700 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-gray-600 disabled:opacity-50"
          onClick={() => setShowGuidance((v) => !v)}
          disabled={regenerating}
        >
          {regenerating ? "Regenerating..." : "Regenerate"}
        </button>
      </div>

      {/* Guidance input for regenerate */}
      {showGuidance && (
        <div className="flex items-center gap-2">
          <input
            type="text"
            className="flex-1 rounded border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:border-gray-400 focus:outline-none"
            placeholder='Optional guidance (e.g., "make it shorter", "emphasize Python more")'
            value={guidance}
            onChange={(e) => setGuidance(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleRegenerate();
            }}
          />
          <button
            type="button"
            className="rounded bg-blue-700 px-3 py-2 text-sm font-medium text-blue-50 hover:bg-blue-600"
            onClick={handleRegenerate}
          >
            Go
          </button>
        </div>
      )}
    </div>
  );
}
