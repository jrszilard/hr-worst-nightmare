import { useState, useRef, useEffect } from "react";

interface AnnotationMarkerProps {
  annotation: string | null;
}

export default function AnnotationMarker({ annotation }: AnnotationMarkerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  if (!annotation) return null;

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        className="rounded bg-gray-700 px-1.5 py-0.5 text-[11px] font-medium text-gray-300 hover:bg-gray-600 hover:text-gray-100"
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        Why?
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-1.5 w-64 rounded border border-gray-600 bg-gray-800 p-2.5 text-xs text-gray-300 shadow-lg">
          {annotation}
        </div>
      )}
    </div>
  );
}
