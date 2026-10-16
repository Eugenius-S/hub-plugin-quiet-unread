// «Непрочитано» у сессии — только итог строго владельцу (owner_reply ядра: ход по его сообщению или его продолжение,
// ответ на его задачу); служебное ядра и сессий (REPLIED, HANDOFF, «запушь», сторож, отчёты друг другу) — нет.
// Роли с галочкой в настройках — любой итог, как у ядра (owner_out). Ядро без owner_reply (старое) — решает само.
export const ROLES = [
  { key: "hub", label: "Хаб", hint: "Его итоги — всегда «новое»", on: true },
  { key: "agent", label: "Специалисты", on: false },
  { key: "executor", label: "Исполнители", on: false },
  { key: "worker", label: "Остальные сессии", on: false },
];

export function unread(s, loud = () => false) {
  if (typeof s.owner_reply !== "number" || typeof s.seen !== "number") return undefined;
  if (loud(s.role)) return typeof s.owner_out === "number" ? s.owner_out > s.seen : undefined;
  return s.owner_reply > s.seen;
}

export default function register(hub) {
  if (typeof hub.addUnread !== "function") return;   // хаб без addUnread — как было
  const loud = (role) => {
    const r = ROLES.find((o) => o.key === role) || ROLES[ROLES.length - 1];
    return typeof hub.option === "function" ? hub.option(r.key) : r.on;
  };
  if (typeof hub.addOptions === "function")
    hub.addOptions({ title: "Тихое «непрочитано»", hint: "Где «новое» горит на любой итог, а не только на ответ вам", options: ROLES });
  hub.addUnread((s) => unread(s, loud));
}
