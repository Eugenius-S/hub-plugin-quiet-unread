// "Unread" for a session - only a result strictly for the owner (the core's owner_reply: a turn made for their message or its
// continuation, a reply to their task); service messages of the core and sessions (REPLIED, HANDOFF, "push it", the
// watchdog, reports to each other) - no. Roles ticked in the settings - any result, as in the core (owner_out). A core
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
    role_hub_hint: "Его итоги — всегда «новое»",
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

export function unread(s, loud = () => false) {
  if (typeof s.owner_reply !== "number" || typeof s.seen !== "number") return undefined;
  if (loud(s.role)) return typeof s.owner_out === "number" ? s.owner_out > s.seen : undefined;
  return s.owner_reply > s.seen;
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
  hub.addUnread((s) => unread(s, loud));
}
