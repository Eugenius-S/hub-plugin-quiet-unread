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
    late: "{session} sent a result on your task: {head}",
    wait: "👀 {session} waits for you: {head}",
    late_open: "Open the chat of {session}",
    late_close: "Hide",
  },
  ru: {
    title: "Тихое «непрочитано»",
    hint: "Где «новое» горит на любой итог, а не только на ответ вам",
    role_hub: "Хаб",
    role_hub_hint: "Его итоги всегда «новое»",
    role_agent: "Специалисты",
    role_executor: "Исполнители",
    role_worker: "Остальные сессии",
    late: "{session} прислала итог по твоей задаче: {head}",
    wait: "👀 {session} ждёт тебя: {head}",
    late_open: "Открыть чат {session}",
    late_close: "Скрыть",
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

// A late result in the thread of the owner's word: a session answered on his task later, in its own chat, while he talks in
// another one (the process main.py decides it from the core's state and posts it to the plugin's channel; the core showed
// it nowhere as his reply). A plaque above the input field of the chat where he said that word (at; a word from Telegram:
// any chat but the session's own) names it until he has seen it: a click on it opens that session, or he is at the page
// with that session open. Seen ones are kept in the browser, a reload keeps them; newest first, at most LATE_MAX.
// A result while its session waits for the owner (main.py waiting, kind "wait") is held the same way, in any chat but its own.
export const LATE = "quiet-unread.late";   // localStorage: {seen: [post ids]}
export const LATE_MAX = 3;
export const LATE_DAYS = 3;                // older posts are not shown
export function lateResults({ now = () => Date.now(), store, changed = () => {} } = {}) {
  let posts = [];   // [{id, ts, kind, session, at, head, words}] from the channel, oldest first
  const load = () => { try { return JSON.parse(store?.getItem(LATE) || "{}")?.seen || []; } catch { return []; } };
  const save = (seen) => { try { store?.setItem(LATE, JSON.stringify({ seen: seen.slice(-200) })); } catch { /* private mode */ } };
  return {
    // channel posts (hub.feed): only well-formed "late" and "wait" ones are kept
    add(rows) {
      const have = new Set(posts.map((p) => p.id));
      for (const r of rows || []) {
        if (have.has(r.id)) continue;
        let d;
        try { d = JSON.parse(r.text); } catch { continue; }
        if ((d?.kind !== "late" && d?.kind !== "wait") || typeof d.session !== "string" || !d.session) continue;
        posts.push({ id: r.id, ts: r.ts, kind: d.kind, session: d.session, at: d.at || null, head: String(d.head || ""), words: String(d.words || "") });
      }
      posts = posts.slice(-100);
    },
    // the plaques for the chat `here`: not seen, not the session's own results, newest first
    shown(here) {
      if (!here) return [];
      const seen = new Set(load()), old = now() / 1000 - LATE_DAYS * 86400;
      return posts.filter((p) => !seen.has(p.id) && p.ts >= old && p.session !== here && (p.at === null || p.at === here))
        .reverse().slice(0, LATE_MAX);
    },
    // a session with a late result not seen yet: its row stays "new"
    pending(name) {
      const seen = new Set(load()), old = now() / 1000 - LATE_DAYS * 86400;
      return posts.some((p) => p.session === name && p.ts >= old && !seen.has(p.id));
    },
    // the owner saw it: all of that session's late results (a click on a plaque, he is in its chat)
    visit(name) {
      const seen = load(), more = posts.filter((p) => p.session === name && !seen.includes(p.id)).map((p) => p.id);
      if (!more.length) return;
      save([...seen, ...more]);
      changed();
    },
    hide(id) {
      const seen = load();
      if (seen.includes(id)) return;
      save([...seen, id]);
      changed();
    },
  };
}

// the plaques into a slot root: a row per result, a click opens the session that sent it
export function drawLate(root, rows, t, { open, hide }) {
  root.hidden = !rows.length;
  if (!rows.length) { root.replaceChildren(); return; }
  const doc = root.ownerDocument;
  const el = (tag, cls, text) => { const n = doc.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  root.replaceChildren(...rows.map((r) => {
    const row = el("div", "qu-late");
    const go = el("button", "qu-late-go", t(r.kind === "wait" ? "wait" : "late", { session: r.session, head: r.head }));
    go.type = "button";
    go.title = r.words ? `${t("late_open", { session: r.session })}\n${r.words}` : t("late_open", { session: r.session });
    go.addEventListener("click", () => open(r));
    const x = el("button", "qu-late-x", "×");
    x.type = "button";
    x.title = t("late_close");
    x.setAttribute("aria-label", t("late_close"));
    x.addEventListener("click", () => hide(r));
    row.dataset.post = r.id;
    row.append(go, x);
    return row;
  }));
}
const LATE_CSS = `.qu-late{display:flex;align-items:center;gap:6px;margin:0 0 6px;padding:6px 8px 6px 10px;border-radius:10px;
background:color-mix(in srgb,var(--accent,#3b82f6) 12%,transparent);border:1px solid color-mix(in srgb,var(--accent,#3b82f6) 35%,transparent);font-size:13px}
.qu-late-go{flex:1;min-width:0;text-align:left;background:none;border:0;padding:0;color:inherit;font:inherit;cursor:pointer;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qu-late-go:hover{text-decoration:underline}
.qu-late-x{background:none;border:0;padding:0 4px;color:inherit;opacity:.6;font-size:16px;line-height:1;cursor:pointer}
.qu-late-x:hover{opacity:1}`;

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
function listen(p, late, hub) {
  if (typeof window === "undefined") return;
  const on = () => { p.input(); if (document.visibilityState === "visible") late.visit(openSession(hub)); };
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart"]) window.addEventListener(ev, on, { capture: true, passive: true });
  // a real move: the page redrawn under a still mouse is not the owner
  window.addEventListener("pointermove", (e) => { if (e.movementX || e.movementY) on(); }, { capture: true, passive: true });
  window.addEventListener("hashchange", () => p.opened());
  if (!document.getElementById("qu-late-css")) {
    const st = document.createElement("style");
    st.id = "qu-late-css";
    st.textContent = LATE_CSS;
    document.head.append(st);
  }
}

export default function register(hub, deps) {
  if (typeof hub.addUnread !== "function") return;   // a hub without addUnread - as before
  const t = makeT(hub);
  const env = deps ?? browser(hub);
  const p = presence(env);
  // hub.redraw redraws only the session list: the slot above the input field waits for the next snapshot, and on a quiet
  // hub there is none — the plaques are repainted here (a read of the channel, a seen one)
  let slot = null;   // {root, here} of the last render
  const late = lateResults({ ...env, changed: () => { env.changed?.(); paint(); } });
  const acts = {
    open: (r) => { late.visit(r.session); location.hash = `#/s/${encodeURIComponent(r.session)}`; },
    hide: (r) => late.hide(r.id),
  };
  const paint = () => { if (slot) drawLate(slot.root, late.shown(slot.here), t, acts); };
  if (!deps) listen(p, late, hub);
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
    return late.pending(s.name) || unread(s, loud, snap);
  });
  if (typeof hub.addSlot !== "function" || typeof hub.feed !== "function") return;
  // the channel is read when the snapshot names a newer post (snap.feeds), one read at a time
  const channel = "quiet-unread";
  let have = 0, reading = false;
  const pull = (snap) => {
    const top = snap?.feeds?.[channel];
    if (reading || typeof top !== "number" || top <= have) return;
    reading = true;
    hub.feed(have).then((rows) => {
      late.add(rows);
      for (const r of rows || []) have = Math.max(have, Number(String(r.id).slice(1)) || 0);
      have = Math.max(have, top);
      hub.redraw?.();
      paint();
    }).catch(() => { /* the next snapshot retries */ }).finally(() => { reading = false; });
  };
  hub.addSlot("session.composer", {
    id: "late",
    order: -10,
    render(root, snap, ctx) {
      slot = { root, here: ctx?.session?.name };
      paint();
      pull(snap);
    },
  });
}
