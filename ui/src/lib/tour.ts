import { driver, type Driver, type DriveStep, type PopoverDOM, type Side } from "driver.js";
import "driver.js/dist/driver.css";
import { freshTour, getTour, setTour } from "./tourStore";

/* ---------- signals: components say what happened, the tour waits for it ---------- */

export type TourSignal = "run-started" | "event-received" | "event-done" | "replay-start" | "node-expanded";
export interface TourDetail {
  type: TourSignal;
  id?: string;
  status?: string;
}
export const emitTour = (type: TourSignal, extra: Omit<TourDetail, "type"> = {}) =>
  window.dispatchEvent(new CustomEvent<TourDetail>("ct-tour", { detail: { type, ...extra } }));

/** Events that already happened (a fast run can finish before the tour asks). */
const seen = { received: new Set<string>(), done: new Set<string>() };
if (typeof window !== "undefined") {
  window.addEventListener("ct-tour", (e) => {
    const d = (e as CustomEvent<TourDetail>).detail;
    if (d.type === "event-received" && d.id) seen.received.add(d.id);
    if (d.type === "event-done" && d.id) seen.done.add(d.id);
    if (d.type === "run-started") {
      // a new run of the same id starts again
      if (d.id) {
        seen.received.delete(d.id);
        seen.done.delete(d.id);
      }
    }
  });
}

function waitSignal(type: TourSignal, ok: (d: TourDetail) => boolean, signal: AbortSignal): Promise<TourDetail | null> {
  return new Promise((resolve) => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<TourDetail>).detail;
      if (d.type === type && ok(d)) {
        cleanup();
        resolve(d);
      }
    };
    const cleanup = () => {
      window.removeEventListener("ct-tour", on);
      signal.removeEventListener("abort", abort);
    };
    const abort = () => {
      cleanup();
      resolve(null);
    };
    window.addEventListener("ct-tour", on);
    signal.addEventListener("abort", abort);
  });
}

/** The first element that matches, now or within `ms` (a DOM observer, no polling). */
function waitElement(selector: string, ms: number, signal: AbortSignal): Promise<Element | null> {
  const now = document.querySelector(selector);
  if (now) return Promise.resolve(now);
  return new Promise((resolve) => {
    const done = (el: Element | null) => {
      mo.disconnect();
      window.clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      resolve(el);
    };
    const mo = new MutationObserver(() => {
      const el = document.querySelector(selector);
      if (el) done(el);
    });
    const onAbort = () => done(null);
    const timer = window.setTimeout(() => done(document.querySelector(selector)), ms);
    mo.observe(document.body, { childList: true, subtree: true });
    signal.addEventListener("abort", onAbort);
  });
}

/* ---------- the engine ---------- */

interface StepDef {
  /** CSS selector of what to highlight; none = a centred popover */
  element?: string;
  title: string;
  body: string;
  side?: Side;
  /** runs before the element is looked up (open a tab...) */
  before?: () => void | Promise<void>;
  /** Next stays disabled with "Waiting for the agents..." until this resolves */
  waitFor?: (signal: AbortSignal) => Promise<unknown>;
  /** skip the step when false */
  onlyIf?: () => boolean;
  /** move on by itself as soon as `waitFor` has resolved (a pure "waiting" popover) */
  autoAdvance?: boolean;
  /** while this step is showing, move on by itself when this resolves (unless the reader already moved) */
  advanceWhen?: (signal: AbortSignal) => Promise<unknown>;
}

let drv: Driver | null = null;
let abort: AbortController | null = null;
let internal = false;
let token = 0;
let active: "orientation" | "run" | "hint" | null = null;
let hintId: string | null = null;

const reduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
export const tourActive = () => active;
export const hintFor = () => hintId;

export function stopTour() {
  token += 1;
  abort?.abort();
  abort = null;
  if (drv) {
    internal = true;
    try {
      drv.destroy();
    } catch {
      /* already gone */
    }
    internal = false;
    drv = null;
  }
  active = null;
  hintId = null;
  document.body.classList.remove("ct-tour-nonblocking");
}

function makeDriver(modal: boolean, onEnd: () => void): Driver {
  document.body.classList.toggle("ct-tour-nonblocking", !modal);
  return driver({
    animate: !reduced(),
    smoothScroll: !reduced(),
    overlayOpacity: modal ? 0.35 : 0,
    overlayClickBehavior: "none", // clicks outside the highlight are ignored
    allowClose: true, // Esc
    stagePadding: 6,
    stageRadius: 8,
    popoverClass: "ct-tour-popover",
    showProgress: false,
    // Esc and the close button end the tour; our own highlight() calls replace each other silently
    onDestroyStarted: (_el, _step, o) => {
      if (internal || o.reason === "replaced" || o.reason === "api") return;
      onEnd();
    },
  });
}

/**
 * Driver.js blocks the page while it is active (`.driver-active * { pointer-events: none }`). The quiet hints must not:
 * drop that body class after highlighting (the popover and the outline stay).
 */
function releasePage() {
  document.body.classList.remove("driver-active");
}

function skipButton(pop: PopoverDOM, onSkip: () => void) {
  if (pop.footerButtons.querySelector("[data-tour-skip]")) return;
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = "Skip";
  b.setAttribute("data-tour-skip", "");
  b.className = "ct-tour-skip";
  b.onclick = onSkip;
  pop.footerButtons.prepend(b);
}

/** Phases 1 and 3: a modal sequence. Back/Next/Skip and a counter on every popover. */
async function runSequence(kind: "orientation" | "run", defs: StepDef[], opts: { onFinish: () => void; onSkip: () => void }) {
  stopTour();
  active = kind;
  abort = new AbortController();
  const signal = abort.signal;
  const my = (token += 1);
  const stale = () => my !== token || signal.aborted;
  const skip = () => {
    stopTour();
    opts.onSkip();
  };
  drv = makeDriver(true, skip);
  let i = 0;
  const applicable = () => defs.filter((d) => !d.onlyIf || d.onlyIf());

  const show = async (dir: 1 | -1): Promise<void> => {
    while (i >= 0 && i < defs.length && defs[i]?.onlyIf && !defs[i]?.onlyIf?.()) i += dir;
    if (i < 0) i = 0;
    if (i >= defs.length) {
      stopTour();
      opts.onFinish();
      return;
    }
    const d = defs[i] as StepDef;
    await d.before?.();
    if (stale()) return;
    const list = applicable();
    const n = list.indexOf(d) + 1;
    const last = n === list.length;
    const render = (waiting: boolean, el: Element | null) => {
      const step: DriveStep = {
        element: el ?? undefined,
        popover: {
          title: d.title,
          description: d.body,
          side: d.side ?? "bottom",
          align: "center",
          showButtons: ["previous", "next"],
          disableButtons: [...(waiting ? (["next"] as const) : []), ...(n === 1 ? (["previous"] as const) : [])],
          showProgress: true,
          progressText: `${n}/${list.length}`,
          nextBtnText: last ? "Done" : "Next",
          prevBtnText: "Back",
          doneBtnText: "Done",
          onNextClick: () => {
            if (waiting) return;
            i += 1;
            void show(1);
          },
          onPrevClick: () => {
            i -= 1;
            void show(-1);
          },
          onDoneClick: () => {
            i += 1;
            void show(1);
          },
          onPopoverRender: (pop) => {
            skipButton(pop, skip);
            if (waiting) {
              const w = document.createElement("p");
              w.className = "ct-tour-waiting";
              w.textContent = "Waiting for the agents...";
              pop.description.append(w);
            }
          },
        },
      };
      drv?.highlight(step);
    };
    if (d.waitFor) {
      // what to highlight may not exist until the signal arrives (the flow strip needs its first stage): wait first, then look
      render(true, d.element ? document.querySelector(d.element) : null);
      await d.waitFor(signal);
      if (stale()) return;
    }
    let el: Element | null = null;
    if (d.element) {
      el = await waitElement(d.element, d.waitFor ? 10000 : 4000, signal);
      if (stale()) return;
      if (!el) {
        i += dir; // not on screen (a tab that is not there): move on
        return show(dir);
      }
    }
    render(false, el);
    const here = i;
    const mine = (shownToken += 1);
    const still = () => !stale() && mine === shownToken && i === here;
    if (d.autoAdvance) {
      window.setTimeout(() => {
        if (still()) {
          i += 1;
          void show(1);
        }
      }, 400);
    } else if (d.advanceWhen) {
      void d.advanceWhen(signal).then(() => {
        if (still()) {
          i += 1;
          void show(1);
        }
      });
    }
  };
  let shownToken = 0;
  await show(1);
}

/* ---------- phase 1: orientation ---------- */

export function startOrientation() {
  const onFinish = () => setTour({ orientation: "done" });
  const onSkip = () => setTour({ orientation: "done", run: "done", enabled: false });
  const steps: StepDef[] = [
    {
      title: "Welcome to the Control Tower",
      body: "Fifteen real-world messages come in as free text. Four agents read them, plan what the handbook prescribes, check it on a copy, then act. About a minute: skip any time.",
    },
    { element: "[data-feed]", title: "Event feed", body: "Events arrive here as the feed runs, newest on top, judge events included. Filter and search.", side: "right" },
    { element: '[data-tour="custom"]', title: "Try your own event", body: "Paste any message. It runs on a private sandbox server through the same agents and MCP client.", side: "right" },
    { element: '[data-tour="run-feed"]', title: "Run the feed", body: "All 15 against the scored server, Sequential or Parallel. The menu also holds the last run's numbers and the model used.", side: "bottom" },
    { element: "[data-inbox]", title: "Escalation inbox", body: "When the agents cannot act safely they hand over to a person. Each card says what a human must supply, and you can re-run it with details.", side: "left" },
    { element: '[data-tour="activity"]', title: "Activity", body: "A live stream of agent steps and tool calls while a run is on.", side: "left" },
    { title: "Start something", body: "Press Run feed, or try your own event, to continue. The tutorial picks up from there." },
  ];
  void runSequence("orientation", steps, { onFinish, onSkip });
}

/* ---------- phase 2: one quiet hint, non-blocking ---------- */

export function showRunHint(eventId: string, onDismiss: () => void, target: "event" | "feed" = "event") {
  stopTour();
  active = "hint";
  hintId = eventId;
  abort = new AbortController();
  const signal = abort.signal;
  const my = (token += 1);
  const sel = target === "feed" ? '[data-tour="run-feed"]' : '[data-tour="run-event"]';
  void waitElement(sel, 3000, signal).then((el) => {
    if (!el || my !== token) {
      if (my === token) stopTour();
      return;
    }
    drv = makeDriver(false, () => {
      stopTour();
      onDismiss();
    });
    drv.highlight({
      element: el,
      popover: {
        title: target === "feed" ? "Start the feed" : "Watch it work",
        description:
          target === "feed"
            ? "Press Run feed (or try your own event) and events arrive one by one. The tutorial follows the first one."
            : "Press this to watch the four agents handle it live (about a minute, through the MCP client). The tutorial continues when you do.",
        side: "bottom",
        align: "end",
        showButtons: ["close"],
        closeBtnLabel: "Dismiss",
        popoverClass: "ct-tour-popover ct-tour-hint",
      },
    });
    releasePage();
  });
}

/* ---------- phase 3: following a real run ---------- */

const openTab = (name: string) => window.dispatchEvent(new CustomEvent("ct-open-tab", { detail: name }));

export function startRunPhase(initialId: string | null) {
  let id = initialId; // a judge event gets its C-nn only when the stream announces it
  const finish = () => setTour({ run: "done", enabled: false });
  const onSkip = () => setTour({ orientation: "done", run: "done", enabled: false });
  const waitDone = async (signal: AbortSignal) => {
    if (id && seen.done.has(id)) return;
    await waitSignal("event-done", (d) => !id || d.id === id, signal);
  };
  const escalated = () => !!id && !!document.querySelector(`[data-inbox-card]`)?.textContent?.includes(id);
  const steps: StepDef[] = [
    {
      element: "#event-detail",
      title: "The coordinator is reading the message",
      body: "It classifies the text, resolves plants, parts and dates against the company graph, and decides whether it is safe to act.",
      side: "left",
      autoAdvance: true,
      waitFor: async (signal) => {
        if (id && seen.received.has(id)) return;
        const d = await waitSignal("event-received", (x) => (id ? x.id === id : !!x.id), signal);
        if (d?.id && !id) {
          id = d.id; // a judge event, or the first event of the feed: show it live
          window.location.hash = `/${id}`;
        }
      },
    },
    {
      element: "[data-flow]",
      title: "Orchestration",
      body: "The coordinator on top, the specialists below. Stages appear as hand-offs happen; click a stage to read its thoughts.",
      side: "left",
      before: () => {
        openTab("Orchestration");
      },
      waitFor: async (signal) => void (await waitElement("[data-flow-node]", 60000, signal)),
      advanceWhen: waitDone, // the event finishes: on to the summary (the reader can press Next earlier)
    },
    {
      element: "[data-headline]",
      title: "What happened, and why",
      body: "The summary comes from the same counts as the actions, so the numbers match what the agents really did. The chips below show the guardrails that passed.",
      side: "left",
      before: () => {
        openTab("Summary");
      },
      waitFor: waitDone,
    },
    {
      element: "#tabpanel",
      title: "Graph",
      body: "The path from the message to what it touches: Shipment, Part, Model, ProductionOrder, CustomerOrder, then Dealer or Customer (Plant and Lot variants too). Pin a path to keep it.",
      side: "left",
      before: () => {
        openTab("Graph");
      },
    },
    {
      element: '[data-tour="actions"]',
      title: "Actions",
      body: "Every tool call, with its transport (MCP). A real incident uses at least three write kinds; reads are free.",
      side: "top",
      before: () => {
        openTab("Actions");
      },
    },
    {
      element: '[data-tour="guardrails"]',
      title: "Audit",
      body: "The pre-flight on a sandbox copy, the second model's verdict and the world diff: what changed, checked against the handbook.",
      side: "left",
      before: () => {
        openTab("Audit");
      },
    },
    {
      element: "[data-inbox-card]",
      title: "Handed to a person",
      body: "This event was escalated: the card says what a human must confirm, and you can re-run it with details.",
      side: "left",
      onlyIf: escalated,
    },
    { title: "Tutorial complete", body: "Turn it on again from the header whenever you like." },
  ];
  void runSequence("run", steps, { onFinish: finish, onSkip });
}

/** The run did not complete: one popover on the top-bar alert, then the tour ends without marking the run done. */
export function showRunFailure() {
  stopTour();
  active = "hint";
  abort = new AbortController();
  const my = (token += 1);
  void waitElement('[role="alert"]', 3000, abort.signal).then((el) => {
    if (!el || my !== token) return;
    drv = makeDriver(false, () => stopTour());
    drv.highlight({
      element: el,
      popover: {
        title: "The run did not complete",
        description: "The top bar says why. The tutorial stops here; turn it on again to follow another run.",
        side: "bottom",
        align: "end",
        showButtons: ["close"],
        closeBtnLabel: "Dismiss",
        popoverClass: "ct-tour-popover ct-tour-hint",
      },
    });
    releasePage();
  });
}

/* ---------- the header toggle ---------- */

export function setTutorial(on: boolean) {
  if (on) {
    setTour(freshTour());
    startOrientation();
  } else {
    stopTour();
    setTour({ enabled: false });
  }
}
export const tourEnabled = () => getTour().enabled;
