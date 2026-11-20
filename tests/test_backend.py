"""The process of the plugin (main.py) on a replay of journal events through the core's own reducer: a temp state folder,
never the live hub. The core is HUB_CORE, else the newest layer of ~/.hub-core; its spool is the temp folder's."""
import glob, json, os, shutil, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def core_dir():
    if os.environ.get("HUB_CORE"):
        return os.environ["HUB_CORE"]
    layers = sorted(glob.glob(os.path.expanduser("~/.hub-core/layers/*/core/reducer.py")), key=os.path.getmtime)
    return os.path.dirname(os.path.dirname(layers[-1])) if layers else ROOT


CORE = core_dir()
TMP = tempfile.mkdtemp(prefix="quiet-unread-")
os.environ["HUB_STATE_DIR"] = os.path.join(TMP, "state")   # never the live hub
os.environ.pop("HUB_EXTENSION", None)
os.environ["PYTHONPATH"] = CORE + os.pathsep + os.environ.get("PYTHONPATH", "")   # the child checks with the same core
sys.path.insert(0, CORE)
sys.path.insert(0, ROOT)
import main  # noqa: E402

STATE = os.environ["HUB_STATE_DIR"]
REPORT = "Отчёт по соцсетям готов: охваты выросли на 12%, подробности в файле."


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class Journal(unittest.TestCase):
    """A temp hub: a journal written as hubd writes it, the plugin's tail on it."""

    def setUp(self):
        shutil.rmtree(STATE, ignore_errors=True)
        os.makedirs(STATE)
        self.seq, self.ts = 0, 1_800_000_000.0
        self.tail = main.start()   # the first start: from the end of an empty journal

    def ev(self, type, entity=None, data=None, src="core", after=1.0):
        self.seq += 1
        self.ts += after
        e = {"seq": self.seq, "ts": self.ts, "src": src, "type": type, "entity": entity, "data": data or {}}
        with open(main.JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")   # as hubd writes it
        return e

    def result(self, text, after=60.0, error=False):
        self.ev("turn.started", "analyst", {"marker": f"m{self.seq}"}, src="hook", after=1.0)
        return self.ev("turn.result", "analyst", {"text": text, "subtype": "success", "is_error": error}, src="host",
                       after=after)

    def broken_task(self):
        """The owner gives analyst a task from Telegram; its turn ends on the spend limit: the task is `stopped`."""
        self.ev("session.requested", "analyst", {"cwd": TMP, "kind": "work", "role": "agent", "channel": "cli", "owner": True})
        self.ev("session.started", "analyst", {"session_id": "x"}, src="hook")
        m = self.ev("message.received", None, {"to": "analyst", "text": "report please", "channel": "telegram", "owner": True})
        d = self.ev("delegation.created", None, {"session": "analyst", "for": f"m{m['seq']}", "channel": "cli",
                                                  "owner": True, "words": "report please"})
        self.ev("turn.started", "analyst", {"marker": f"m{d['seq']}"}, src="hook")
        self.ev("turn.result", "analyst", {"text": "You've hit your org's monthly spend limit", "subtype": "success",
                                           "is_error": True}, src="host")
        self.ev("message.received", None, {"to": "analyst", "text": "finish it", "about": f"d{d['seq']}",
                                           "channel": "session", "owner": False, "sender": "hub"})
        return d

    def spooled(self, type="owner.notify"):
        found = []
        for path in sorted(glob.glob(os.path.join(STATE, "spool", "*.json"))):
            with open(path, encoding="utf-8") as f:
                item = json.load(f)
            if type is None or item["type"] == type:
                found.append(item)
        return found

    def posted(self):
        """The late results posted to the plugin's channel: their data, parsed."""
        got = self.spooled("ext.post")
        for g in got:
            self.assertEqual(("ext:quiet-unread", "quiet-unread"), (g["src"], g["data"]["plugin"]))
        return [json.loads(g["data"]["text"]) for g in got]

    def run_tail(self, later=10.0):
        self.tail.step(now=self.ts)
        return self.tail.step(now=self.ts + later)   # SETTLE passed: the last result is checked too



class Replay(Journal):
    def test_a_report_after_the_task_broke_goes_to_telegram_once(self):
        d = self.broken_task()
        r = self.result(REPORT)
        self.run_tail()
        got = self.spooled()
        self.assertEqual(1, len(got), got)
        self.assertEqual("owner.notify", got[0]["type"])
        self.assertEqual("ext:quiet-unread", got[0]["src"])
        self.assertEqual({"id": f"r{r['seq']}", "title": "analyst · report please", "text": REPORT, "session": "analyst",
                          "push": False}, got[0]["data"])
        self.assertEqual("stopped", main.state_at(r["seq"])["delegations"][f"d{d['seq']}"]["state"])
        # the same journal again, a reread from its start, a restart: no second notice
        self.run_tail()
        self.tail.mine.update(offset=0, seq=0)
        self.run_tail()
        main.start().step(now=self.ts + 20)
        self.assertEqual(1, len(self.spooled()))
        # his word came from Telegram: on the page a plaque in any chat but analyst's, once
        self.assertEqual([(r["seq"], "analyst", None)], [(p["seq"], p["session"], p["at"]) for p in self.posted()])

    def test_a_pass_on_line_and_a_counter_are_not_sent(self):
        self.broken_task()
        for text in ("—", "— Готово 3 из 5, в работе 2.", "Готово 3 из 5, в работе 2.", "Done 3 of 5, 2 in progress",
                     "ok, на месте"):
            self.result(text)
        self.run_tail()
        self.assertEqual([], self.spooled())

    def test_a_reply_the_core_counts_to_the_owner_is_not_sent_again(self):
        self.broken_task()
        m = self.ev("message.received", None, {"to": "analyst", "text": "how is the report?", "channel": "telegram",
                                               "owner": True})
        self.ev("turn.started", "analyst", {"marker": f"m{m['seq']}"}, src="hook")
        r = self.ev("turn.result", "analyst", {"text": REPORT, "subtype": "success", "is_error": False}, src="host", after=60)
        self.assertEqual(r["seq"], main.state_at(r["seq"])["sessions"]["analyst"]["owner_reply"])   # the bot sends it itself
        self.run_tail()
        self.assertEqual([], self.spooled())

    def test_a_result_without_a_broken_task_is_not_sent(self):
        self.ev("session.requested", "analyst", {"cwd": TMP, "kind": "work", "role": "agent", "channel": "cli", "owner": True})
        self.ev("session.started", "analyst", {"session_id": "x"}, src="hook")
        self.result(REPORT)
        self.run_tail()
        self.assertEqual([], self.spooled())

    def test_a_result_long_after_the_break_is_not_sent(self):
        self.broken_task()
        self.result(REPORT, after=main.WINDOW + 60)
        self.run_tail()
        self.assertEqual([], self.spooled())

    def test_a_result_the_core_rejected_is_not_sent(self):
        self.broken_task()
        r = self.result(REPORT)
        self.ev("core.rejected", "analyst", {"of": r["seq"], "type": "turn.result", "reason": "test"})
        self.run_tail()
        self.assertEqual([], self.spooled())

    def test_the_first_start_does_not_replay_history(self):
        self.broken_task()
        self.result(REPORT)
        shutil.rmtree(os.path.join(STATE, "quiet-unread"), ignore_errors=True)
        fresh = main.start()
        fresh.step(now=self.ts)
        fresh.step(now=self.ts + 20)
        self.assertEqual([], self.spooled())

    def test_a_result_waiting_for_its_verdict_survives_a_restart(self):
        self.broken_task()
        r = self.result(REPORT)
        with mock.patch.object(main, "ask_child", side_effect=AssertionError("checked too early")):
            self.tail.step(now=self.ts)   # read, not yet settled: saved so that a restart reads it again
        again = main.start()
        again.step(now=self.ts)
        again.step(now=self.ts + 20)
        self.assertEqual([f"r{r['seq']}"], [s["data"]["id"] for s in self.spooled()])

    def page_talk(self, channel="web"):
        """The owner writes analyst on the page; analyst answers him there (his reply: the bot keeps it on the page) and
        passes the work to helper; helper's result wakes analyst again (a follow-up of the chain he started on the page)."""
        for name in ("analyst", "helper"):
            self.ev("session.requested", name, {"cwd": TMP, "kind": "work", "role": "agent", "channel": "cli", "owner": True})
            self.ev("session.started", name, {"session_id": name}, src="hook")
        m = self.ev("message.received", None, {"to": "analyst", "text": "put the plan into Figma", "channel": channel,
                                               "owner": True})
        self.ev("turn.started", "analyst", {"marker": f"m{m['seq']}"}, src="hook")
        d = self.ev("delegation.created", None, {"session": "helper", "for_session": "analyst", "context": "draw the plan",
                                                 "channel": "session", "owner": False, "sender": "analyst"})
        first = self.ev("turn.result", "analyst", {"text": "Взял, передал рисовать, пришлю ссылку.", "subtype": "success",
                                                   "is_error": False}, src="host", after=5)
        self.ev("turn.started", "helper", {"marker": f"m{d['seq']}"}, src="hook")
        done = self.ev("turn.result", "helper", {"text": "Plan is drawn, frame 12:34 in the file.", "subtype": "success",
                                                 "is_error": False}, src="host", after=30)
        self.ev("turn.started", "analyst", {"marker": f"m{done['seq']}x1"}, src="hook")   # the core hands helper's reply back
        return m, first

    def test_a_follow_up_of_a_page_talk_goes_to_telegram(self):
        m, first = self.page_talk()
        st = main.state_at(first["seq"])
        self.assertEqual(first["seq"], st["sessions"]["analyst"]["owner_reply"])   # his reply: the bot's own rule
        r = self.ev("turn.result", "analyst", {"text": REPORT, "subtype": "success", "is_error": False}, src="host",
                    after=20)
        sess = main.state_at(r["seq"])["sessions"]["analyst"]
        self.assertEqual((r["seq"], f"m{m['seq']}"), (sess.get("owner_out"), sess.get("turn_root")))
        self.assertNotEqual(r["seq"], sess.get("owner_reply"))   # the clean bot drops it: own page talk, not his reply
        self.run_tail()
        got = [s["data"] for s in self.spooled()]
        self.assertEqual([{"id": f"r{r['seq']}", "title": "analyst · put the plan into Figma", "text": REPORT,
                           "session": "analyst", "push": False}], got)   # helper's own result and the first reply: not sent

    def test_a_follow_up_of_a_telegram_talk_is_left_to_the_bot(self):
        self.page_talk(channel="telegram")
        r = self.ev("turn.result", "analyst", {"text": REPORT, "subtype": "success", "is_error": False}, src="host", after=20)
        self.run_tail()
        self.assertEqual([], self.spooled())
        # on the page it is a plaque in any chat but analyst's own: his word has no chat on the page
        self.assertEqual([{"kind": "late", "seq": r["seq"], "session": "analyst", "at": None, "head": REPORT,
                           "words": "put the plan into Figma"}], self.posted())
        main.start().step(now=self.ts + 30)   # a restart: posted once
        self.tail.mine.update(offset=0, seq=0)
        self.run_tail()
        self.assertEqual(1, len(self.posted()))

    def test_a_state_saved_before_plaques_still_posts(self):
        """state.json of 0.8.0 has no "posted": a late result is posted, not a KeyError on every read."""
        self.page_talk(channel="telegram")
        self.run_tail()
        main.save({k: v for k, v in self.tail.mine.items() if k != "posted"})
        self.assertNotIn("posted", main.load())   # as on a hub updated from 0.8.0
        self.tail = main.start()
        r = self.ev("turn.result", "analyst", {"text": REPORT, "subtype": "success", "is_error": False}, src="host", after=20)
        self.run_tail()
        self.assertEqual([r["seq"]], [p["seq"] for p in self.posted()])

    def test_a_follow_up_in_the_chat_of_his_word_gets_no_plaque(self):
        self.page_talk()
        self.ev("turn.result", "analyst", {"text": REPORT, "subtype": "success", "is_error": False}, src="host", after=20)
        self.run_tail()
        self.assertEqual([], self.posted())   # he said it in analyst's chat: the result is right there

    def test_a_later_result_of_his_task_goes_to_the_chat_of_his_word(self):
        """The owner writes boss on the page; boss gives helper his task; helper's first result is his task's reply (the
        core puts it into boss's chat as a reply line); helper's next result, woken by boss, shows nowhere but helper's
        own chat: a plaque in boss's chat."""
        for name in ("boss", "helper"):
            self.ev("session.requested", name, {"cwd": TMP, "kind": "work", "role": "agent", "channel": "cli", "owner": True})
            self.ev("session.started", name, {"session_id": name}, src="hook")
        m = self.ev("message.received", None, {"to": "boss", "text": "a table of 100 comments", "channel": "web",
                                               "owner": True})
        self.ev("turn.started", "boss", {"marker": f"m{m['seq']}"}, src="hook")
        d = self.ev("delegation.created", None, {"session": "helper", "for": f"m{m['seq']}", "context": "the table",
                                                 "channel": "session", "owner": False, "sender": "boss"})
        self.ev("turn.result", "boss", {"text": "Отдал таблицу, пришлю, как будет готова.", "subtype": "success",
                                        "is_error": False}, src="host", after=5)
        self.ev("turn.started", "helper", {"marker": f"m{d['seq']}"}, src="hook")
        first = self.ev("turn.result", "helper", {"text": "Таблица на 130 комментариев готова, файл рядом.",
                                                  "subtype": "success", "is_error": False}, src="host", after=30)
        st = main.state_at(first["seq"])
        self.assertEqual(first["seq"], st["delegations"][f"d{d['seq']}"].get("replied_seq"))   # the core's reply line
        w = self.ev("message.received", None, {"to": "helper", "text": "fix line 36", "about": f"d{d['seq']}",
                                               "channel": "session", "owner": False, "sender": "boss"})
        self.ev("turn.started", "helper", {"marker": f"m{w['seq']}"}, src="hook")
        r = self.ev("turn.result", "helper", {"text": "Поправил строку 36, таблица готова.\nФайл: table.xlsx",
                                              "subtype": "success", "is_error": False}, src="host", after=30)
        self.run_tail()
        self.assertEqual([{"kind": "late", "seq": r["seq"], "session": "helper", "at": "boss",
                           "head": "Поправил строку 36, таблица готова.", "words": "a table of 100 comments"}], self.posted())

    def test_the_first_reply_to_his_page_word_stays_on_the_page(self):
        self.page_talk()
        self.run_tail()
        self.assertEqual([], self.spooled())   # he is on the page: his reply and helper's result are not sent


WAIT = "владелец: посмотреть тестовую сцену перед генерацией"
SHOWN = "Тестовая сцена готова, посмотри ролик, прежде чем запускать генерацию.\nФайл: test-v1.mp4"


class OwnerWait(Journal):
    """A result while the session waits for the owner (`hub wait "владелец: …"`): it pings him once, with sound."""

    def owner_task(self):
        """The owner gives analyst a task from Telegram; its turn is running (as hub-launch at 11:44 on 20.11)."""
        self.ev("session.requested", "analyst", {"cwd": TMP, "kind": "work", "role": "agent", "channel": "cli", "owner": True})
        self.ev("session.started", "analyst", {"session_id": "x"}, src="hook")
        m = self.ev("message.received", None, {"to": "analyst", "text": "make a test scene", "channel": "telegram",
                                               "owner": True})
        d = self.ev("delegation.created", None, {"session": "analyst", "for": f"m{m['seq']}", "channel": "cli",
                                                  "owner": True, "words": "make a test scene"})
        self.ev("turn.started", "analyst", {"marker": f"m{d['seq']}"}, src="hook")
        return d

    def wait(self, what=WAIT, label="ab12"):
        """`hub wait` in the turn: two checks of one wait, as bin/hub writes them."""
        for n in (1, 2):
            self.ev("schedule.set", f"analyst-wait-{label}-{n}",
                    {"session": "analyst", "at": self.ts + 600 * n, "prompt": f"[waiting for reply] {what}. Check now.",
                     "wait": what, "channel": "session", "owner": False, "sender": "analyst"}, src="session")
        return f"analyst-wait-{label}"

    def answer(self, text=SHOWN, after=30.0):
        return self.ev("turn.result", "analyst", {"text": text, "subtype": "success", "is_error": False}, src="host",
                       after=after)

    def notices(self):
        return [s["data"] for s in self.spooled()]

    def test_the_reply_of_his_task_while_it_waits_for_him_pings_him(self):
        """The case of 20.11 11:44: the core sends the reply itself (his task), the plugin adds one short ping."""
        d = self.owner_task()
        self.wait()
        r = self.answer()
        st = main.state_at(r["seq"])
        self.assertEqual(r["seq"], st["delegations"][f"d{d['seq']}"].get("replied_seq"))   # the bot sends the reply itself
        self.run_tail()
        self.assertEqual([{"id": f"w{r['seq']}", "title": "👀 Waits for you: Тестовая сцена готова, посмотри ролик, "
                           "прежде чем запускать генерацию.", "text": WAIT, "session": "analyst", "push": False}],
                         self.notices())
        self.assertEqual([{"kind": "wait", "seq": r["seq"], "session": "analyst", "at": None,
                           "head": "Тестовая сцена готова, посмотри ролик, прежде чем запускать генерацию.",
                           "words": WAIT}], self.posted())
        # a reread, a restart: no second ping
        self.tail.mine.update(offset=0, seq=0)
        self.run_tail()
        main.start().step(now=self.ts + 20)
        self.assertEqual(1, len(self.spooled()))
        self.assertEqual(1, len(self.posted()))

    def test_the_owners_language_names_the_ping(self):
        self.owner_task()
        self.wait()
        r = self.answer()
        with mock.patch("core.i18n.state_lang", return_value="ru"):
            got = main.check(r["seq"])
        self.assertTrue(got["wait"]["notice"]["title"].startswith("👀 Ждёт тебя: Тестовая сцена"), got)

    def test_a_reply_without_a_wait_is_not_pinged(self):
        self.owner_task()
        self.answer()
        self.run_tail()
        self.assertEqual([], self.spooled())
        self.assertEqual([], self.posted())

    def test_a_wait_of_someone_else_is_not_pinged(self):
        self.owner_task()
        self.wait("analyst-helper: ответ по таблице, потом владельцу")
        self.answer()
        self.run_tail()
        self.assertEqual([], self.spooled())

    def test_a_second_result_under_the_same_wait_does_not_ping_again(self):
        self.owner_task()
        self.wait()
        r = self.answer()
        self.ev("message.received", None, {"to": "analyst", "text": "check the log", "channel": "session", "owner": False,
                                           "sender": "hub"})
        self.ev("turn.started", "analyst", {"marker": f"m{self.seq}"}, src="hook")
        self.answer("Лог проверил, сцена та же, жду твоего взгляда на ролик.")
        self.run_tail()
        self.assertEqual([f"w{r['seq']}"], [n["id"] for n in self.notices()])

    def test_a_new_wait_pings_again(self):
        self.owner_task()
        self.wait()
        self.answer()
        self.ev("turn.started", "analyst", {"marker": f"m{self.seq}"}, src="hook")
        self.wait("владелец: выбрать один из трёх вариантов", label="cd34")
        r = self.answer("Сделал три варианта сцены, выбери один.")
        self.run_tail()
        self.assertEqual(2, len(self.notices()))
        self.assertEqual(f"w{r['seq']}", self.notices()[-1]["id"])

    def test_a_wait_done_before_the_result_is_not_pinged(self):
        self.owner_task()
        job = self.wait()
        for n in (1, 2):
            self.ev("schedule.remove_requested", f"{job}-{n}", {"channel": "session", "owner": False, "sender": "analyst"},
                    src="session")
        self.assertEqual({"removed"}, {main.state_at(self.seq)["schedule"][f"{job}-{n}"]["state"] for n in (1, 2)})
        self.answer()
        self.run_tail()
        self.assertEqual([], self.spooled())

    def test_a_result_the_bot_does_not_send_comes_whole_once(self):
        """The owner's task broke; the late result (0.8.0 sends it as r<seq>) waits for him: one notice, the whole text."""
        self.broken_task()
        self.ev("turn.started", "analyst", {"marker": f"m{self.seq}"}, src="hook")
        self.wait()
        r = self.answer(REPORT)
        self.run_tail()
        self.assertEqual([{"id": f"w{r['seq']}", "title": "👀 Waits for you: " + REPORT, "text": REPORT,
                           "session": "analyst", "push": False}], self.notices())

    def watch(self, ask="Посмотри ролик и скажи, запускать ли генерацию"):
        return self.ev("watch.needs_owner", "analyst", {"p": 1.0, "ask": ask, "text": SHOWN, "seen_at": self.ts,
                                                        "channel": "cli", "owner": True}, src="watch", after=5)

    def test_the_watchdogs_mark_pings_once_per_result(self):
        self.owner_task()
        self.answer()
        w = self.watch()
        self.assertIn("attention", main.state_at(w["seq"])["sessions"]["analyst"])   # the core took the mark
        self.watch("Ещё раз: запускать?")   # the same result: no second ping
        self.run_tail()
        self.assertEqual([{"id": f"w{w['seq']}", "title": "👀 Waits for you: Посмотри ролик и скажи, запускать ли "
                           "генерацию", "text": SHOWN, "session": "analyst", "push": False}], self.notices())

    def test_the_watchdogs_mark_after_a_wait_ping_is_not_sent(self):
        self.owner_task()
        self.wait()
        r = self.answer()
        self.watch()
        self.run_tail()
        self.assertEqual([f"w{r['seq']}"], [n["id"] for n in self.notices()])

    def test_the_watchdogs_marks_of_a_busy_talk_ping_once_in_a_while(self):
        """review-briefly on 20.11 12:11-12:18: a mark on every turn of a live talk, one ping per AGAIN."""
        self.owner_task()
        self.answer()
        first = self.watch()
        for after in (60.0, 60.0, main.AGAIN):
            self.ev("turn.started", "analyst", {}, src="hook", after=after)
            self.answer()
            last = self.watch()
        self.run_tail()
        self.assertEqual([f"w{first['seq']}", f"w{last['seq']}"], [n["id"] for n in self.notices()])

    def test_a_rejected_mark_is_not_sent(self):
        self.owner_task()
        self.answer()
        w = self.watch()
        self.ev("core.rejected", "analyst", {"of": w["seq"], "type": "watch.needs_owner", "reason": "test"})
        self.run_tail()
        self.assertEqual([], self.spooled())


if __name__ == "__main__":
    unittest.main()
