// «Непрочитано» у сессии — только итог строго владельцу (owner_reply ядра: ход по его сообщению или его продолжение,
// ответ на его задачу); служебное ядра и сессий (REPLIED, HANDOFF, «запушь», сторож, отчёты друг другу) — нет.
// Ядро без owner_reply (старое) — решает само.
export function unread(s) {
  if (typeof s.owner_reply !== "number" || typeof s.seen !== "number") return undefined;
  return s.owner_reply > s.seen;
}

export default function register(hub) {
  if (typeof hub.addUnread !== "function") return;   // хаб без addUnread — как было
  hub.addUnread((s) => unread(s));
}
