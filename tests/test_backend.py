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


class Replay(unittest.TestCase):
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

    def spooled(self):
        found = []
        for path in sorted(glob.glob(os.path.join(STATE, "spool", "*.json"))):
            with open(path, encoding="utf-8") as f:
                found.append(json.load(f))
        return found

    def run_tail(self, later=10.0):
        self.tail.step(now=self.ts)
        return self.tail.step(now=self.ts + later)   # SETTLE passed: the last result is checked too

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


if __name__ == "__main__":
    unittest.main()
