import { test } from "node:test";
import assert from "node:assert/strict";
import register, { unread } from "../main.js";

test("непрочитано — только итог владельцу после того, как он смотрел", () => {
  assert.equal(unread({ owner_reply: 10, seen: 5, unread: true }), true);
  assert.equal(unread({ owner_reply: 4, seen: 5, unread: true }), false);   // служебный итог позже — тихо
  assert.equal(unread({ owner_reply: 0, seen: 0, unread: true }), false);
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
