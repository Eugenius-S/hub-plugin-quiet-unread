#!/usr/bin/env python3
"""quiet-unread — the process of the plugin: a result that comes after the owner's task broke off goes to Telegram too.

The page lights such a result up (main.js, afterStopped): the owner's task of a session went `stopped` (a spend limit, a
crash, a stop), and the session answered later anyway. The core counts that answer to nobody (no `owner_reply`), so the
Telegram bot does not send it: the owner sees it only on the page. This process sends it as a notice (owner.notify), once.

How: it reads the tail of journal.jsonl (raw lines; only `turn.result` lines are parsed). A result that can matter (no
error, at least MIN_TEXT characters, not a pass-on "—" or a conveyor counter, not the hub) is checked in a child process
against the core's state at exactly that event (journal.state_at; when the state file is already further on, the journal
is folded up to it): the session counted it to the owner (owner_out) but not as his reply (owner_reply), no task of his
took it as its reply (replied_seq: the bot sends that one itself), and either a task of his on that session is `stopped`
since at most WINDOW before it, or the turn is a later one of a chain he began with his own words to this session on the
page (page_talk: the bot keeps such a chain on the page as his own talk, though only his direct reply is read there). The child keeps the core's state (hundreds of MB) out of this long-lived process.

Out: owner.notify {id: r<seq>, title, text, session, push: false} through the spool. The same id is never sent twice: the
sent ids live in <state>/quiet-unread/state.json, written after the spool. The first start begins at the journal's end
(history is not replayed). `python3 main.py --dry [hours]` prints what the current journal would have sent, sends nothing.
"""
import json, os, re, subprocess, sys, time

KEY = os.environ.get("HUB_EXTENSION") or "quiet-unread"   # hub.json extensions key: <account>:quiet-unread from the market
NAME = KEY.split(":")[-1]
STATE = os.environ.get("HUB_STATE_DIR") or os.path.expanduser("~/.hub-core")
HOME = os.path.join(STATE, NAME)
JOURNAL = os.path.join(STATE, "journal.jsonl")
WINDOW = 3 * 3600     # the result came at most this long after the task broke off (main.js STOPPED_WINDOW)
MIN_TEXT = 20         # a shorter result is a status line, not something to read
POLL = 2.0            # seconds between reads of the journal
SETTLE = 3.0          # a result is checked once the core's verdict on it (the next line) is written, or after this
KEEP = 200            # sent ids kept against repeats
CHECK_TIMEOUT = 120   # the child gives up: the result is logged, not sent
SEQ = re.compile(rb'^\{"seq":([0-9]+),')
PASS_ON = re.compile(r"^\s*[—–-](\s|$)")   # "—" and "— Done 3 of 5": nothing to read (main.js PASS_ON)
COUNTER = re.compile(r"^\s*(готово|done)\s+\d+\s+(из|of)\s+\d+\b[^\n]*$", re.I)   # a bare conveyor counter line


def log(*parts):
    print(time.strftime("%H:%M:%S"), NAME, *parts, flush=True)


def maybe(ev):
    """The shown text of a result worth a check, or None: cheap tests on the event alone."""
    from core import reducer
    data = ev.get("data") or {}
    if ev.get("type") != "turn.result" or not ev.get("entity") or data.get("is_error") or reducer.failure(data):
        return None
    text = reducer.shown_text(data.get("text")).strip()
    if len(text) < MIN_TEXT or PASS_ON.match(text) or COUNTER.match(text):
        return None
    return text


def _seq(did):
    return int(did[1:]) if isinstance(did, str) and re.fullmatch(r"d\d+", did) else None


def important(st, ev):
    """The notice for result ev given the core's state right after it, or None (see the module doc)."""
    text = maybe(ev)
    if text is None:
        return None
    name, seq = ev["entity"], ev["seq"]
    sess = (st.get("sessions") or {}).get(name) or {}
    if sess.get("kind") == "hub" or sess.get("owner_out") != seq or sess.get("owner_reply") == seq:
        return None   # not counted to the owner, or counted as his reply: the bot sends that one itself
    if (sess.get("merged") or {}).get("seq") == seq:
        return None
    tasks = list((st.get("delegations") or {}).values())
    if any(d.get("replied_seq") == seq and d.get("for") for d in tasks):
        return None   # the reply of his task: the bot sends it
    if page_talk(st, name, sess):
        return notice(name, seq, text, ((st.get("messages") or {}).get(sess["turn_root"]) or {}).get("text"))
    broke = [d for d in tasks if d.get("session") == name and d.get("for") and d.get("state") == "stopped"
             and (_seq(d.get("id")) or seq) < seq and isinstance(d.get("since"), (int, float))
             and 0 <= ev["ts"] - d["since"] <= WINDOW]
    if not broke:
        return None
    d = max(broke, key=lambda d: d["since"])
    return notice(name, seq, text, d.get("words"))


def page_talk(st, name, sess):
    """A later turn of a chain the owner began with his own words to this session on the page (not Telegram): the turn
    was woken by something else (a specialist's reply, an executor's result). The bot keeps the whole chain on the page
    (own_talk), though he has left it long ago; only his direct reply (owner_reply) stays there."""
    root = sess.get("turn_root")
    start = (st.get("messages") or {}).get(root or "") or {}
    return bool(root and sess.get("turn_marker") != root and start.get("from_owner") and start.get("channel") != "telegram"
                and start.get("session", start.get("to")) == name)


def notice(name, seq, text, words):
    words = " ".join(str(words or "").split())
    title = name + (" · " + words[:40] + ("…" if len(words) > 40 else "") if words else "")
    return {"id": f"r{seq}", "title": title, "text": text, "session": name, "push": False}


def state_at(seq):
    """The core's state right after event seq: the state file plus the journal up to seq; the state file is already
    further on (it is written every 50 events) or does not join — the whole journal folded up to seq. None: not found."""
    from core import journal, reducer
    st = journal.state_at(STATE, seq)
    if isinstance(st, dict):
        return st
    events = []
    with open(JOURNAL, "rb") as f:
        for line in f:
            head = SEQ.match(line)
            if head and int(head[1]) <= seq and line.endswith(b"\n"):
                events.append(json.loads(line))   # after a rotation the journal starts with older seqs: all lines are read
    st = reducer.fold(reducer.empty(), events)
    return st if st.get("seq") == seq else None


def check(seq):
    """The child: the notice for event seq of the journal (dict) or None."""
    ev = None
    with open(JOURNAL, "rb") as f:
        for line in f:
            if line.startswith(b'{"seq":%d,' % seq) and b'"turn.result"' in line[:300]:
                ev = json.loads(line)
    if not ev:
        return None
    st = state_at(seq)
    return important(st, ev) if st else None


def ask_child(seq):
    """Run the check in a child process: the core's state stays out of this one. (notice or None, error or None)"""
    try:
        out = subprocess.run([sys.executable, os.path.abspath(__file__), "--check", str(seq)], capture_output=True,
                             timeout=CHECK_TIMEOUT, env=os.environ.copy())
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if out.returncode:
        return None, (out.stderr.decode("utf-8", "replace").strip().splitlines() or ["code %d" % out.returncode])[-1]
    return json.loads(out.stdout.decode("utf-8") or "null"), None


def send(notice):
    from core import spool
    spool.put(os.path.join(STATE, "spool"), "owner.notify", None, notice, src="ext:" + KEY)


def load():
    try:
        with open(os.path.join(HOME, "state.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(mine):
    os.makedirs(HOME, exist_ok=True)
    path = os.path.join(HOME, "state.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(mine, f)
    os.replace(path + ".tmp", path)


class Tail:
    """Reads journal.jsonl from where it stopped; after a rotation continues in the new file (journal.go_on)."""

    def __init__(self, mine):
        self.mine = mine   # {seq, ino, offset, sent: [ids]}
        self.pending = []  # [(event, seen at)] results waiting for the core's verdict

    def lines(self):
        """New journal lines: (seq, event, offset of the line) - the event parsed only for a result or a rejection, else None;
        the offset is None for the end of the archive after a rotation."""
        from core import journal
        now = journal.identity(JOURNAL)
        if not now:
            return []
        ino, offset, got = self.mine.get("ino"), self.mine.get("offset") or 0, []
        if ino and ino != now:   # rotated: finish the archive, then the new file from its "rotate" snapshot
            went = journal.go_on(JOURNAL, ino, offset, now)
            got, offset = ([(e["seq"], e, None) for e in went[0]], went[1]) if went else ([], 0)
        try:
            with open(JOURNAL, "rb") as f:
                if f.seek(0, 2) < offset:
                    offset = 0
                f.seek(offset)
                for line in f:
                    if not line.endswith(b"\n"):
                        break   # hubd is writing it
                    at, offset = offset, offset + len(line)
                    head = SEQ.match(line)
                    if head:
                        wanted = b'"turn.result"' in line[:300] or b'"core.rejected"' in line[:300]
                        got.append((int(head[1]), json.loads(line) if wanted else None, at))
        except OSError:
            return []
        self.mine.update(ino=now, offset=offset)
        return got

    def step(self, now=None):
        """One read: new results queue up, settled ones (the core's verdict line is written, or SETTLE passed) are
        checked and sent. The notices sent."""
        now = time.time() if now is None else now
        before, last = dict(self.mine), self.mine.get("seq") or 0
        for seq, e, at in self.lines():
            if seq <= last:
                continue   # read already (a carried part after a rotation, a reread from the start)
            if e and e["type"] == "core.rejected":
                of = (e.get("data") or {}).get("of")
                self.pending = [p for p in self.pending if p[0]["seq"] != of]
            elif e and maybe(e) is not None:
                self.pending.append((e, now, at))
            self.mine["seq"] = last = seq
        sent = []
        while self.pending and (self.pending[0][0]["seq"] < last or now - self.pending[0][1] >= SETTLE):
            ev = self.pending.pop(0)[0]
            nid = f"r{ev['seq']}"
            if nid in self.mine.setdefault("sent", []):
                continue
            notice, err = ask_child(ev["seq"])
            if err:
                log("check", ev["seq"], "failed:", err)
            elif notice:
                send(notice)   # first the spool, then the record: a crash between them repeats, the id edits the same message
                self.mine["sent"] = (self.mine["sent"] + [nid])[-KEEP:]
                sent.append(notice)
                log("sent", nid, ev.get("entity"))
        if self.mine != before:
            ev, _, at = self.pending[0] if self.pending else (None, None, None)
            # a result still waiting: a restart reads again from its line
            save({**self.mine, "seq": ev["seq"] - 1, "offset": at} if at is not None else self.mine)
        return sent


def start():
    """The first start: from the journal's end, history is not replayed."""
    mine = load()
    if not mine.get("ino"):
        from core import journal
        try:
            size = os.path.getsize(JOURNAL)
        except OSError:
            size = 0
        mine.update(ino=journal.identity(JOURNAL), offset=size, seq=0, sent=mine.get("sent") or [])
    return Tail(mine)


def dry(hours):
    """What the current journal would have sent in the last hours (nothing is sent)."""
    since, n = time.time() - hours * 3600, 0
    with open(JOURNAL, "rb") as f:
        for line in f:
            if b'"turn.result"' not in line[:300]:
                continue
            ev = json.loads(line)
            if ev.get("type") != "turn.result" or ev["ts"] < since or maybe(ev) is None:
                continue
            n += 1
            notice, err = ask_child(ev["seq"])
            if err or notice:
                print(ev["seq"], time.strftime("%d.%m %H:%M", time.localtime(ev["ts"])), ev["entity"],
                      err or json.dumps({k: notice[k] for k in ("id", "title")}, ensure_ascii=False), flush=True)
    print("checked", n, flush=True)


def main(argv):
    if argv[:1] == ["--check"]:
        print(json.dumps(check(int(argv[1])), ensure_ascii=False))
        return
    if argv[:1] == ["--dry"]:
        return dry(float(argv[1]) if argv[1:] else 24)
    tail = start()
    log("watching", JOURNAL)
    while True:
        try:
            tail.step()
        except Exception as e:   # noqa: BLE001 — one bad read must not stop the process: the next read retries
            log("error:", repr(e)[:300])
        time.sleep(POLL)


if __name__ == "__main__":
    main(sys.argv[1:])
