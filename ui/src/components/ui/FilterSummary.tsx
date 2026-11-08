import { X } from "lucide-react";

export interface FilterSegment {
  /** "Type", "Status", "Search" */
  label: string;
  /** what is selected, already formatted: "2" or the search text */
  value: string;
  /** opens the menu (or focuses the search box) that owns this segment */
  onOpen: () => void;
}

/** One pill that appears only while a filter is active: "Type: 2 · Status: 1 · Search: lot · Clear". */
export function FilterSummary({ segments, onClear }: { segments: FilterSegment[]; onClear: () => void }) {
  if (segments.length === 0) return null;
  return (
    <div data-filter-summary role="status" className="flex flex-wrap items-center gap-x-1 rounded-md border border-line bg-surface-2 px-2 py-1 text-[11.5px] text-tx2">
      {segments.map((s, i) => (
        <span key={s.label} className="inline-flex items-center gap-1">
          {i > 0 && <span aria-hidden className="text-tx3">·</span>}
          <button onClick={s.onOpen} className="rounded px-0.5 hover:text-tx focus-visible:outline-2" title={`Change the ${s.label.toLowerCase()} filter`}>
            {s.label}: <span className="font-medium text-tx">{s.value}</span>
          </button>
        </span>
      ))}
      <button onClick={onClear} className="ml-auto inline-flex items-center gap-0.5 rounded px-1 text-tx3 hover:text-tx focus-visible:outline-2">
        <X size={12} aria-hidden /> Clear
      </button>
    </div>
  );
}
