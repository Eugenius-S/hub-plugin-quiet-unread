import { test } from "node:test";
import assert from "node:assert/strict";
import register, { unread, presence, lateResults, LATE, LATE_MAX, STR, ROLES, makeT } from "../main.js";

test("unread - only a result for the owner after they looked", () => {
  assert.equal(unread({ owner_reply: 10, seen: 5, unread: true }), true);
  assert.equal(unread({ owner_reply: 4, seen: 5, unread: true }), false);   // a later service result - quiet
  assert.equal(unread({ owner_reply: 0, seen: 0, unread: true }), false);
});

test("a ticked role - any result, as in the core", () => {
  const loud = (r) => r === "hub";
  assert.equal(unread({ role: "hub", owner_reply: 4, owner_out: 9, seen: 5 }, loud), true);
  assert.equal(unread({ role: "hub", owner_reply: 4, owner_out: 4, seen: 5 }, loud), false);
  assert.equal(unread({ role: "agent", owner_reply: 4, owner_out: 9, seen: 5 }, loud), false);
});

test("ticks in the settings: the hub is on, the rest are off", () => {
  const got = {};
  register({ addUnread: (fn) => (got.fn = fn), addOptions: (g) => (got.g = g), option: (k) => k === "hub" });
  assert.deepEqual(got.g.options.map((o) => [o.key, o.on]), [["hub", true], ["agent", false], ["executor", false], ["worker", false]]);
  assert.equal(got.fn({ role: "hub", owner_reply: 0, owner_out: 9, seen: 5 }), true);
  assert.equal(got.fn({ role: "executor", owner_reply: 0, owner_out: 9, seen: 5 }), false);
});

test("an old core without owner_reply - the core decides", () => {
  assert.equal(unread({ unread: true }), undefined);
});

test("a hub without addUnread - the plugin does nothing", () => {
  assert.doesNotThrow(() => register({}));
  const got = [];
  register({ addUnread: (fn) => got.push(fn) });
  assert.equal(got.length, 1);
});

const options = (hub) => {
  const got = {};
  register({ ...hub, addUnread: () => {}, addOptions: (g) => (got.g = g) });
  return got.g;
};

test("settings text is English by default", () => {
  const g = options({});
  assert.equal(g.title, "Quiet unread");
  assert.deepEqual(g.options.map((o) => o.label), ["Hub", "Specialists", "Executors", "Other sessions"]);
  assert.equal(g.options[0].hint, "Its results are always \"new\"");
  assert.equal(g.options[1].hint, undefined);
});

test("settings text is Russian when the hub language is Russian", () => {
  const g = options({ lang: "ru" });
  assert.equal(g.title, "Тихое «непрочитано»");
  assert.equal(g.hint, "Где «новое» горит на любой итог, а не только на ответ вам");
  assert.deepEqual(g.options.map((o) => o.label), ["Хаб", "Специалисты", "Исполнители", "Остальные сессии"]);
  assert.equal(g.options[0].hint, "Его итоги всегда «новое»");
});

test("any other language falls back to English", () => {
  for (const lang of ["uk", "de", "xx", "", null]) assert.equal(options({ lang }).title, "Quiet unread");
});

test("the language is read at use time, not at load", () => {
  const hub = {};
  const t = makeT(hub);
  assert.equal(t("title"), "Quiet unread");
  hub.lang = "ru";
  assert.equal(t("title"), "Тихое «непрочитано»");
});

test("Russian has every key English has, and every role has a label", () => {
  assert.deepEqual(Object.keys(STR.ru).sort(), Object.keys(STR.en).sort());
  for (const r of ROLES) assert.ok(STR.en[`role_${r.key}`] && STR.ru[`role_${r.key}`], r.key);
});

// replay of 18.11: the owner's task to a specialist broke on an error (state "stopped"), the specialist then sent the
// reports anyway - the core no longer ties them to the task (owner_reply stays 0), but they are the owner's results
const T = 1_800_000_000;
const report = { name: "analyst", role: "agent", owner_reply: 0, owner_out: 859998, seen: 859000, out_head_ts: T,
  out_head: "Matchbox: decided to build the farm and autoposting on it; 8 steps below" };
const snap = (...tasks) => ({ delegations: tasks });
const task = { id: "d859716", session: "analyst", for: "m859706", state: "stopped", since: T - 1800 };

test("a report after the owner's task broke on an error - new", () => {
  assert.equal(unread(report, undefined, snap(task)), true);
});

test("a stopped task does not light up what it should not", () => {
  assert.equal(unread(report, undefined, snap()), false);
  assert.equal(unread(report, undefined, undefined), false);
  assert.equal(unread(report, undefined, snap({ ...task, session: "designer" })), false);   // someone else's task
  assert.equal(unread(report, undefined, snap({ ...task, for: null })), false);           // not the owner's
  assert.equal(unread(report, undefined, snap({ ...task, state: "working" })), false);    // the core ties those itself
  assert.equal(unread(report, undefined, snap({ ...task, id: "d860000" })), false);       // set after the result
  assert.equal(unread(report, undefined, snap({ ...task, since: T - 2 * 86400 })), false); // stopped days ago
  assert.equal(unread({ ...report, seen: 860000 }, undefined, snap(task)), false);         // already looked
  assert.equal(unread({ ...report, out_head: "done" }, undefined, snap(task)), false);     // a service line
});

test("a pass-on line and a conveyor counter are not new even as a reply", () => {
  const s = { name: "gen-x", role: "worker", owner_reply: 859551, owner_out: 859551, seen: 859000 };
  assert.equal(unread({ ...s, out_head: "— Done 42 of 42, 0 in progress." }), false);
  assert.equal(unread({ ...s, out_head: "—" }), false);
  assert.equal(unread({ ...s, out_head: "-" }), false);
  assert.equal(unread({ ...s, out_head: "Done: the post is up" }), true);
  // the core's own head of the reply (reply_head) wins over the latest result
  assert.equal(unread({ ...s, owner_out: 859600, out_head: "a later service line", reply_head: "— Done 42 of 42" }), false);
});

test("the hook hands the snapshot over", () => {
  const got = {};
  register({ addUnread: (fn) => (got.fn = fn), option: () => false });
  assert.equal(got.fn(report, snap(task)), true);
});

// replay of 19.11 (Windows journal): the owner asked hub-launch on the page whether every access was there (m814742) and
// went on in Telegram; the answer (815215, 10:11:27) was marked read by the open page tab a second later (owner.seen
// 815217, 10:11:28), the same with every later reply while he wrote from Telegram (10:16-10:42) - none of them lit up.
// Read needs the owner at the page: an input in this tab after the result came, while that session is open.
const clockAt = (t0) => { const c = { t: t0 }; c.now = () => c.t; return c; };
const mem = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)) }; };
const launch = { name: "hub-launch", role: "worker", owner_reply: 815046, owner_out: 815046, last_out: 815046, seen: 815046,
  out_head: "Записал главный реф" };
const answer = { ...launch, owner_reply: 815215, owner_out: 815215, last_out: 815215, out_head: "Нашёл в Higgsfield все рефы" };

function page(cur = "hub-launch") {
  const c = clockAt(1_000_000), store = mem(), env = { visible: true, cur };
  const p = presence({ now: c.now, store, visible: () => env.visible, current: () => env.cur });
  const look = (s) => unread({ ...s, seen: p.seen(s) });
  return { c, store, env, p, look };
}

test("the open tab marking read with nobody at the page keeps the reply new (19.11 replay)", () => {
  const { c, look } = page();
  assert.equal(look(launch), false);                      // first look: what was read stays read
  c.t += 600_000; assert.equal(look({ ...answer, seen: 815046 }), true);   // the answer came
  c.t += 1_300; assert.equal(look({ ...answer, seen: 815215 }), true);     // owner.seen 815217: the tab, not the owner
  assert.equal(unread({ ...answer, seen: 815215 }), false);                // 0.6.0 put the dot out here
  c.t += 60_000; assert.equal(look({ ...answer, seen: 815215 }), true);    // still new a minute later
});

test("the owner at the page after the answer came - read as the core says", () => {
  const { c, p, look } = page();
  look(launch);
  c.t += 600_000; look({ ...answer, seen: 815046 });
  c.t += 500; p.input();                                     // a mouse move, a key, a wheel in this tab
  c.t += 800; assert.equal(look({ ...answer, seen: 815215 }), false);
});

test("a held reply goes out once the owner shows up at that session, and only there", () => {
  const { c, env, p, look } = page("hub-core");
  look(launch);
  c.t += 600_000; look({ ...answer, seen: 815046 });
  c.t += 60_000; look({ ...answer, seen: 815215 });          // marked read on another screen (or the phone page)
  c.t += 1_000; p.input();                                   // active, but in another session
  assert.equal(look({ ...answer, seen: 815215 }), true);
  env.cur = "hub-launch"; p.input();                         // opened it and moved
  assert.equal(look({ ...answer, seen: 815215 }), false);
});

test("input before the answer came does not count, a hidden tab gives no input", () => {
  const { c, env, p, look } = page();
  look(launch);
  p.input();
  c.t += 600_000; look({ ...answer, seen: 815046 });
  c.t += 1_000; assert.equal(look({ ...answer, seen: 815215 }), true);
  env.visible = false; p.input();
  assert.equal(look({ ...answer, seen: 815215 }), true);
});

test("a held reply survives a reload of the page", () => {
  const { c, store, env, look } = page();
  look(launch);
  c.t += 600_000; look({ ...answer, seen: 815046 });
  c.t += 1_000; look({ ...answer, seen: 815215 });
  const again = presence({ now: c.now, store, visible: () => true, current: () => env.cur });
  assert.equal(unread({ ...answer, seen: again.seen({ ...answer, seen: 815215 }) }), true);
});

test("a click just before the core marked it (opening it, read all) counts", () => {
  const { c, env, p, look } = page("hub-core");
  look(launch);
  c.t += 600_000; look({ ...answer, seen: 815046 });
  c.t += 60_000; p.input();                                  // the click in the list
  env.cur = "hub-launch";
  c.t += 2_000; assert.equal(look({ ...answer, seen: 815215 }), false);
});

test("the hook keeps a reply new when the core read it with nobody at the page", () => {
  const got = {}, c = clockAt(1_000_000);
  register({ addUnread: (fn) => (got.fn = fn), option: () => false },
    { now: c.now, store: mem(), visible: () => true, current: () => "hub-launch" });
  got.fn(launch);
  c.t += 600_000; got.fn({ ...answer, seen: 815046 });
  c.t += 1_300; assert.equal(got.fn({ ...answer, seen: 815215 }), true);
});

// the page of hub 1.9.x: api.js applyAll runs the hooks on the snapshot's own row objects, sidebar.js puts a row into
// "Answered you" by the row's "seen" (a copy of its answered() without the "mark all read" part)
const answered = (s) => !!s.unread && (s.owner_reply || 0) > (s.seen || 0);
function apply(fn, s) {
  s.core_unread ??= !!s.unread;
  s.unread = s.core_unread;
  const v = fn(s);
  if (typeof v === "boolean") s.unread = v;
  return s;
}

test("a held reply stays in the list's \"Answered you\", not only as a dot", () => {
  const got = {}, c = clockAt(1_000_000), env = { cur: "hub-launch" };
  const deps = { now: c.now, store: mem(), visible: () => true, current: () => env.cur };
  register({ addUnread: (fn) => (got.fn = fn), option: () => false }, deps);
  apply(got.fn, { ...launch, unread: false });
  c.t += 600_000; apply(got.fn, { ...answer, seen: 815046, unread: true });
  c.t += 1_300;
  const row = apply(got.fn, { ...answer, seen: 815215, unread: false });   // the core read it with nobody at the page
  assert.equal(row.unread, true);
  assert.equal(answered(row), true);
  apply(got.fn, row); apply(got.fn, row);                                    // hub.redraw: the same object again
  assert.equal(row.seen, 815046);
  assert.equal(row.core_seen, 815215);
  assert.equal(answered(row), true);
  c.t += 5_000;
  const next = apply(got.fn, { ...answer, seen: 815215, unread: false });    // the core sent the row again
  assert.equal(answered(next), true);
});

test("once the owner is at the page the row gets the core's \"seen\" back", () => {
  const got = {}, c = clockAt(1_000_000), env = { cur: "hub-launch" };

  const deps = { now: c.now, store: mem(), visible: () => true, current: () => env.cur };
  register({ addUnread: (fn) => (got.fn = fn), option: () => false }, deps);
  apply(got.fn, { ...launch, unread: false });
  c.t += 600_000; apply(got.fn, { ...answer, seen: 815046, unread: true });
  c.t += 1_300;
  const row = apply(got.fn, { ...answer, seen: 815215, unread: false });
  assert.equal(answered(row), true);
  const touch = presence(deps);   // the same store: what input() does to the hold
  touch.input();
  apply(got.fn, row);
  assert.equal(row.seen, 815215);
  assert.equal(row.unread, false);
  assert.equal(answered(row), false);
});

// late results: the plugin's channel posts (main.py) as plaques above the input of the chat of the owner's word
const memory = () => { const m = {}; return { getItem: (k) => m[k] ?? null, setItem: (k, v) => { m[k] = v; }, m }; };
const NOW = 1_800_000_000;
const post = (seq, session, at, head = `result ${seq}`, ts = NOW - 60) =>
  ({ id: `p${seq}`, ts, by: "plugin quiet-unread", text: JSON.stringify({ kind: "late", seq, session, at, head, words: "the table" }) });

test("late results: a plaque in the chat of his word, a word from Telegram - any chat but the session's own", () => {
  const l = lateResults({ now: () => NOW * 1000, store: memory() });
  l.add([post(1, "writer", null), post(2, "helper", "boss"), { id: "p3", ts: NOW, text: "not json" },
    { id: "p4", ts: NOW, text: JSON.stringify({ kind: "other", session: "x" }) }]);
  assert.deepEqual(l.shown("boss").map((p) => p.id), ["p2", "p1"]);   // newest first
  assert.deepEqual(l.shown("hub-core").map((p) => p.id), ["p1"]);
  assert.deepEqual(l.shown("writer").map((p) => p.id), []);           // its own chat has it already
  assert.deepEqual(l.shown("helper").map((p) => p.id), ["p1"]);
  assert.deepEqual(l.shown(null), []);
});

test("late results: at most three, old ones not shown, a repeat read adds nothing", () => {
  const l = lateResults({ now: () => NOW * 1000, store: memory() });
  const rows = [1, 2, 3, 4, 5].map((n) => post(n, `s${n}`, null));
  l.add(rows);
  l.add(rows);
  l.add([post(6, "s6", null, "old", NOW - 4 * 86400)]);
  assert.equal(LATE_MAX, 3);
  assert.deepEqual(l.shown("x").map((p) => p.id), ["p5", "p4", "p3"]);
});

test("late results: held until seen - a visit to the session or hiding the plaque, a reload keeps it", () => {
  const store = memory();
  let changes = 0;
  const l = lateResults({ now: () => NOW * 1000, store, changed: () => changes++ });
  l.add([post(1, "writer", null), post(2, "writer", null), post(3, "helper", "boss")]);
  assert.equal(l.pending("writer"), true);
  l.visit("writer");
  assert.deepEqual(l.shown("boss").map((p) => p.id), ["p3"]);
  assert.equal(l.pending("writer"), false);
  l.hide("p3");
  assert.deepEqual(l.shown("boss"), []);
  assert.equal(changes, 2);
  l.visit("writer");   // nothing new: no redraw
  assert.equal(changes, 2);
  // a reload: the same posts, seen ones stay hidden, a new one shows
  const again = lateResults({ now: () => NOW * 1000, store });
  again.add([post(1, "writer", null), post(2, "writer", null), post(3, "helper", "boss"), post(7, "writer", null)]);
  assert.deepEqual(again.shown("boss").map((p) => p.id), ["p7"]);
  assert.ok(JSON.parse(store.getItem(LATE)).seen.includes("p3"));
});

test("a result while its session waits for him: held like a late one, its plaque says the session waits for him", () => {
  const l = lateResults({ now: () => NOW * 1000, store: memory() });
  const wait = { id: "p8", ts: NOW - 60, text: JSON.stringify({ kind: "wait", seq: 8, session: "analyst", at: null,
    head: "The test scene is ready", words: "owner: look at the test scene" }) };
  l.add([wait, post(9, "writer", null)]);
  assert.deepEqual(l.shown("boss").map((p) => [p.id, p.kind]), [["p9", "late"], ["p8", "wait"]]);
  assert.deepEqual(l.shown("analyst").map((p) => p.id), ["p9"]);   // its own chat has it already
  assert.equal(l.pending("analyst"), true);                          // the row stays new until he is in its chat
  l.visit("analyst");
  assert.equal(l.pending("analyst"), false);
  assert.match(makeT({ lang: "ru" })("wait", { session: "analyst", head: "Сцена готова" }), /^👀 analyst ждёт тебя: Сцена готова$/);
  assert.match(makeT({ lang: "en" })("wait", { session: "analyst", head: "Scene" }), /^👀 analyst waits for you: Scene$/);
});

test("late results: the slot reads the channel when the snapshot names a newer post, the row stays new; the plaque is painted without waiting for a snapshot", async () => {
  const got = {}, asked = [];
  let redraws = 0;
  const hub = {
    addUnread: (fn) => (got.fn = fn), option: () => false, redraw: () => redraws++,
    addSlot: (slot, it) => (got.slot = [slot, it]),
    feed: async (since) => { asked.push(since); return [post(5, "writer", null)]; },
  };
  register(hub, { now: () => NOW * 1000, store: memory() });
  assert.equal(got.slot[0], "session.composer");
  const node = () => ({ dataset: {}, children: [], setAttribute() {}, addEventListener(t, f) { this.on = f; },
    append(...n) { this.children.push(...n); }, replaceChildren(...n) { this.children = n; } });
  const root = { ...node(), hidden: false, ownerDocument: { createElement: () => node() } };
  got.slot[1].render(root, { feeds: {} }, { session: { name: "hub-core" } });
  assert.deepEqual(asked, []);
  got.slot[1].render(root, { feeds: { "quiet-unread": 5 } }, { session: { name: "hub-core" } });
  got.slot[1].render(root, { feeds: { "quiet-unread": 5 } }, { session: { name: "hub-core" } });   // one read at a time
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(asked, [0]);
  assert.equal(redraws, 1);
  // hub.redraw redraws only the list: the plaque is already there, with no second render (a quiet hub sends no snapshot)
  assert.equal(root.hidden, false);
  assert.equal(root.children[0].children[0].textContent, "writer sent a result on your task: result 5");
  got.slot[1].render(root, { feeds: { "quiet-unread": 5 } }, { session: { name: "hub-core" } });
  assert.deepEqual(asked, [0]);   // nothing newer
  assert.equal(root.hidden, false);
  got.slot[1].render(root, { feeds: { "quiet-unread": 5 } }, { session: { name: "writer" } });
  assert.equal(root.hidden, true);   // its own chat
  assert.equal(got.fn({ name: "writer", role: "agent", owner_reply: 3, owner_out: 5, seen: 9 }), true);
  assert.equal(got.fn({ name: "other", role: "agent", owner_reply: 3, owner_out: 5, seen: 9 }), false);
  // × hides it at once, also without a snapshot
  got.slot[1].render(root, { feeds: { "quiet-unread": 5 } }, { session: { name: "hub-core" } });
  root.children[0].children[1].on();
  assert.equal(root.hidden, true);
});
