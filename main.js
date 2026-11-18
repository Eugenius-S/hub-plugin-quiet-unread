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

export default function register(hub) {
  if (typeof hub.addUnread !== "function") return;   // a hub without addUnread - as before
  const t = makeT(hub);
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
  hub.addUnread((s, snap) => unread(s, loud, snap));
}
