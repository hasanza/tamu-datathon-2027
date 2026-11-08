import { useCallback, useEffect, useRef, useState } from "react";

type Axis = "x" | "y";

/** How far the target's centre is from the scroller's visible centre along `axis` (px), and the sizes used to judge "near". */
function offsetOf(scroller: HTMLElement, target: HTMLElement, axis: Axis) {
  const s = scroller.getBoundingClientRect();
  const t = target.getBoundingClientRect();
  return axis === "x"
    ? { delta: t.left + t.width / 2 - (s.left + s.width / 2), view: s.width, size: t.width }
    : { delta: t.top + t.height / 2 - (s.top + s.height / 2), view: s.height, size: t.height };
}

/**
 * Follow the active element of a growing view: centre it in its scroller, smoothly, only when it has left the central 60%,
 * and hand control back to the reader the moment they scroll, drag or click. They resume with `resume()` or by scrolling
 * back to within one element size of the active one.
 *
 * `enabled`: a run is live or a replay is playing (otherwise nothing ever scrolls by itself).
 * `activeKey`: changes when the active element changes (a stage lands, the active stage moves).
 * `resetKey`: changes at the start of a live run or a replay: following starts again.
 */
export function useFollow({
  scroller,
  target,
  axis,
  enabled,
  activeKey,
  resetKey,
  reduced,
}: {
  scroller: () => HTMLElement | null;
  target: () => HTMLElement | null;
  axis: Axis;
  enabled: boolean;
  activeKey: unknown;
  resetKey: unknown;
  reduced: boolean;
}) {
  const [following, setFollowing] = useState(true);
  const force = useRef(false);
  const left = useRef(false); // the reader has gone more than one element away since pausing
  const fns = useRef({ scroller, target });
  fns.current = { scroller, target };

  useEffect(() => {
    left.current = false;
    setFollowing(true);
  }, [resetKey]);

  // move when the active element changes (or on resume), but only when it is outside the central 60%
  useEffect(() => {
    if (!enabled || !following) return;
    const sc = fns.current.scroller();
    const el = fns.current.target();
    if (!sc || !el) return;
    const { delta, view } = offsetOf(sc, el, axis);
    const must = force.current;
    force.current = false;
    if (!must && Math.abs(delta) <= view * 0.3) return;
    sc.scrollBy(axis === "x" ? { left: delta, behavior: reduced ? "auto" : "smooth" } : { top: delta, behavior: reduced ? "auto" : "smooth" });
  }, [enabled, following, activeKey, axis, reduced]);

  const pause = useCallback(() => {
    left.current = false;
    setFollowing(false);
  }, []);
  const resume = useCallback(() => {
    left.current = false;
    force.current = true;
    setFollowing(true);
  }, []);

  // reader takes over on wheel / touch / drag / scrollbar; scrolling back next to the active element resumes
  useEffect(() => {
    const sc = fns.current.scroller();
    if (!enabled || !sc) return;
    const stop = () => pause();
    const near = () => {
      if (following) return;
      const el = fns.current.target();
      if (!el) return;
      const { delta, size } = offsetOf(sc, el, axis);
      if (Math.abs(delta) > size) left.current = true;
      else if (left.current) resume();
    };
    sc.addEventListener("wheel", stop, { passive: true });
    sc.addEventListener("pointerdown", stop, { passive: true });
    sc.addEventListener("touchstart", stop, { passive: true });
    sc.addEventListener("scroll", near, { passive: true });
    return () => {
      sc.removeEventListener("wheel", stop);
      sc.removeEventListener("pointerdown", stop);
      sc.removeEventListener("touchstart", stop);
      sc.removeEventListener("scroll", near);
    };
  }, [enabled, following, axis, pause, resume, activeKey]);

  return { following, paused: enabled && !following, pause, resume };
}
