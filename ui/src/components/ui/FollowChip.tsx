/** Shown while auto-follow is paused by the reader: say so, and offer the way back. */
export function FollowChip({ onResume }: { onResume: () => void }) {
  return (
    <span data-follow-chip role="status" className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-0.5 text-[11px] text-tx2">
      Following live - paused
      <button onClick={onResume} className="rounded font-medium text-tx underline-offset-2 hover:underline focus-visible:outline-2">
        Resume
      </button>
    </span>
  );
}
