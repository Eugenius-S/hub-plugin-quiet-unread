import { test } from "node:test";
import assert from "node:assert/strict";
import register, { unread, STR, ROLES, makeT } from "../main.js";

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
