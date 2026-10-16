import { test } from "node:test";
import assert from "node:assert/strict";
import register, { unread } from "../main.js";

test("непрочитано — только итог владельцу после того, как он смотрел", () => {
  assert.equal(unread({ owner_reply: 10, seen: 5, unread: true }), true);
  assert.equal(unread({ owner_reply: 4, seen: 5, unread: true }), false);   // служебный итог позже — тихо
  assert.equal(unread({ owner_reply: 0, seen: 0, unread: true }), false);
});

test("роль с галочкой — любой итог, как у ядра", () => {
  const loud = (r) => r === "hub";
  assert.equal(unread({ role: "hub", owner_reply: 4, owner_out: 9, seen: 5 }, loud), true);
  assert.equal(unread({ role: "hub", owner_reply: 4, owner_out: 4, seen: 5 }, loud), false);
  assert.equal(unread({ role: "agent", owner_reply: 4, owner_out: 9, seen: 5 }, loud), false);
});

test("галочки в настройках: хаб включён, остальные выключены", () => {
  const got = {};
  register({ addUnread: (fn) => (got.fn = fn), addOptions: (g) => (got.g = g), option: (k) => k === "hub" });
  assert.deepEqual(got.g.options.map((o) => [o.key, o.on]), [["hub", true], ["agent", false], ["executor", false], ["worker", false]]);
  assert.equal(got.fn({ role: "hub", owner_reply: 0, owner_out: 9, seen: 5 }), true);
  assert.equal(got.fn({ role: "executor", owner_reply: 0, owner_out: 9, seen: 5 }), false);
});

test("старое ядро без owner_reply — решает ядро", () => {
  assert.equal(unread({ unread: true }), undefined);
});

test("хаб без addUnread — плагин ничего не делает", () => {
  assert.doesNotThrow(() => register({}));
  const got = [];
  register({ addUnread: (fn) => got.push(fn) });
  assert.equal(got.length, 1);
});
