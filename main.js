// "Unread" for a session - only a result strictly for the owner (the core's owner_reply: a turn made for their message or its
// continuation, a reply to their task); service messages of the core and sessions (REPLIED, HANDOFF, "push it", the
// watchdog, reports to each other, a "—" pass-on line) - no; a result right after the owner's task to the session broke
// on an error - yes. Roles ticked in the settings - any result, as in the core (owner_out). A core
// without owner_reply (old) decides itself.
export const ROLES = [
  { key: "hub", hint: true, on: true },
  { key: "agent", on: false },
  { key: "executor", on: false },
  { key: "worker", on: false },
];

// UI strings: English by default, Russian when the hub language is Russian (hub.lang).
export const STR = {
  en: {
    title: "Quiet unread",
    hint: "Where \"new\" lights up on any result, not only on a reply to you",
    role_hub: "Hub",
    role_hub_hint: "Its results are always \"new\"",
    role_agent: "Specialists",
    role_executor: "Executors",
    role_worker: "Other sessions",
  },
  ru: {
    title: "Тихое «непрочитано»",
    hint: "Где «новое» горит на любой итог, а не только на ответ вам",
    role_hub: "Хаб",
    role_hub_hint: "Его итоги всегда «новое»",
    role_agent: "Специалисты",
    role_executor: "Исполнители",
    role_worker: "Остальные сессии",
  },
};
// the language is read at the moment of use, not at module load
export const makeT = (hub) => (k, v) => {
  let s = (STR[hub.lang] ?? STR.en)[k] ?? STR.en[k] ?? k;
  for (const [name, val] of Object.entries(v ?? {})) s = s.replaceAll(`{${name}}`, String(val));
  return s;
};

// a pass-on line ("—") and a conveyor counter ("— Done 3 of 5") carry nothing to read
const PASS_ON = /^\s*[—–-](\s|$)/;
// a stopped task still lights up results that follow it within this window (the core no longer ties them to it)
export const STOPPED_WINDOW = 3 * 3600;
const seqOf = (id) => (/^d\d+$/.test(id || "") ? Number(id.slice(1)) : Infinity);

// the owner's task to this session broke on an error ("stopped"), and the session then sent its result anyway: the core
// does not tie such a turn to the task (owner_reply stays behind), but it is what the owner asked for
function afterStopped(s, snap) {
  if (typeof s.owner_out !== "number" || typeof s.out_head_ts !== "number") return false;
  if ((s.out_head || "").trim().length < 20) return false;   // "done", "ok": a service line
  return (snap?.delegations || []).some((d) => d.session === s.name && d.for && d.state === "stopped"
    && seqOf(d.id) < s.owner_out && typeof d.since === "number" && s.out_head_ts - d.since <= STOPPED_WINDOW);
}

export function unread(s, loud = () => false, snap) {
  if (typeof s.owner_reply !== "number" || typeof s.seen !== "number") return undefined;
  if (loud(s.role)) return typeof s.owner_out === "number" ? s.owner_out > s.seen : undefined;
  const replyHead = typeof s.reply_head === "string" ? s.reply_head : s.owner_out === s.owner_reply ? s.out_head : "";
  if (PASS_ON.test(replyHead || "")) return false;
  return s.owner_reply > s.seen || (s.owner_out > s.seen && afterStopped(s, snap));
}

// "Read" needs the owner at the page. The core's page marks a session read when its new result has stood for a second in
// a visible tab, whether or not anyone is at the screen: a chat left open on a second monitor reads every reply itself
// while the owner talks from Telegram or has walked away. Such a result stays "new" here until the owner shows up in
// this tab after it came: a key, a click, a wheel, a touch or a mouse move while that session is open (or a click just
// before the core marked it: opening it from the list). Held results are kept in the browser, a reload keeps them.
export const HELD = "quiet-unread.held";   // localStorage: {session: the core's "seen" the owner really confirmed}
export const CLICK_MS = 5000;
export function presence({ now = () => Date.now(), store, visible = () => true, current = () => null, changed = () => {} } = {}) {
  const live = {};   // session -> { seen, key, at }: the core's "seen" this page last got and when the latest result came
  let input = -Infinity;
  const load = () => { try { return JSON.parse(store?.getItem(HELD) || "{}") || {}; } catch { return {}; } };
  const save = (h) => { try { store?.setItem(HELD, JSON.stringify(h)); } catch { /* private mode: held for this page only */ } };
  const confirm = (name) => {
    const h = load();
    if (!name || !(name in h)) return;
    delete h[name];
    save(h);
    changed();
  };
  return {
    // the owner touched this tab: what the open session shows is read
    input() {
      if (!visible()) return;
      input = now();
      confirm(current());
    },
    // the open session changed by the owner's click: the one opened is in front of them
    opened() { if (now() - input < CLICK_MS) confirm(current()); },
    // the core's "seen" for the row, as far as the owner was really here
    seen(s) {
      const name = s.name, t = now(), key = [s.owner_out, s.owner_reply, s.last_out].join("|");
      const was = live[name];
      live[name] = { seen: s.seen, key, at: was && was.key === key ? was.at : t };
      const h = load();
      if (was && typeof s.seen === "number" && s.seen > was.seen && !(name in h)) {
        const here = visible() && input >= live[name].at && (current() === name || t - input < CLICK_MS);
        if (!here) { h[name] = was.seen; save(h); }
      }
      if (!(name in h)) return s.seen;
      if (typeof s.seen !== "number" || s.seen < h[name]) { delete h[name]; save(h); return s.seen; }   // the core went back (a new session)
      return h[name];
    },
  };
}

// the open session from the address: #/s/<name>; no address - the hub
function openSession(hub) {
  const m = /^#\/s\/([^?]+)/.exec(location.hash);
  if (m) { try { return decodeURIComponent(m[1]); } catch { return m[1]; } }
  if (location.hash && location.hash !== "#/") return null;
  return (hub.snapshot?.()?.sessions || []).find((r) => r.role === "hub")?.name ?? null;
}
function browser(hub) {
  if (typeof window === "undefined" || typeof document === "undefined") return {};
  let store = null;
  try { store = window.localStorage; } catch { /* no storage */ }
  return {
    store,
    visible: () => document.visibilityState === "visible",
    current: () => openSession(hub),
    changed: () => hub.redraw?.(),
  };
}
function listen(p) {
  if (typeof window === "undefined") return;
  const on = () => p.input();
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart"]) window.addEventListener(ev, on, { capture: true, passive: true });
  // a real move: the page redrawn under a still mouse is not the owner
  window.addEventListener("pointermove", (e) => { if (e.movementX || e.movementY) on(); }, { capture: true, passive: true });
  window.addEventListener("hashchange", () => p.opened());
}

export default function register(hub, deps) {
  if (typeof hub.addUnread !== "function") return;   // a hub without addUnread - as before
  const t = makeT(hub);
  const p = presence(deps ?? browser(hub));
  if (!deps) listen(p);
  const loud = (role) => {
    const r = ROLES.find((o) => o.key === role) || ROLES[ROLES.length - 1];
    return typeof hub.option === "function" ? hub.option(r.key) : r.on;
  };
  if (typeof hub.addOptions === "function")
    hub.addOptions({
      title: t("title"),
      hint: t("hint"),
      options: ROLES.map((r) => ({ key: r.key, label: t(`role_${r.key}`), ...(r.hint ? { hint: t(`role_${r.key}_hint`) } : {}), on: r.on })),
    });
  hub.addUnread((s, snap) => {
    if (typeof s.seen !== "number") return unread(s, loud, snap);
    // the page sorts and signs rows by the row's own "seen" (the list's "Answered you", the reply line): a held result
    // goes into the row, or it stays "new" only as a dot in a folded group. The core's value is kept beside it: the row
    // is the same object until the core sends it again
    if (typeof s.core_seen !== "number") s.core_seen = s.seen;
    s.seen = p.seen({ ...s, seen: s.core_seen });
    return unread(s, loud, snap);
  });
}
