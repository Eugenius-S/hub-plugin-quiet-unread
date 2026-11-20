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

A result to the owner while its session waits for him pings him (waiting): a `hub wait` of that session, still on at the
result, waits for him ("владелец: …", "owner: …", "отмашка"), or the watchdog marked the session as waiting for him
(watch.needs_owner, taken by the core) on a turn of his own task while such a wait is on: the mark alone is the
watchdog's guess, and a turn on another session's task is never his (owner's word 20.11). The bot sends such a result
like any other, with nothing that says he is needed: one notice "👀 Waits for you: <first line>", once per wait and once per turn. The bot sent the result already (his reply,
his task's reply): the notice carries what the session waits for; it did not: the notice is the result itself, instead
of r<seq>. On the page the result stays "new" until he is in its chat (a "wait" post, main.js).

A ping he leaves unanswered comes again (nag): every EVERY of a work day (10:00-19:00, Russian work calendar of hub-sync,
<state>/workcal-<year>.json; without it Saturday and Sunday are off), at most REPEATS times, a new notice
w<seq>.<n> "<session>: <what it waits for>" (the same id would only edit the old message). An evening or a day off keeps
the repeat to 10:00 of the next work day. It stops on his answer to that session, read from the journal lines: his message
to it (the page, Telegram, a reply to its post there), his word passed to it (`--for`, a task), his reaction to its post,
his answer to its card; and when the wait is over, checked in a child against the core's state: its `hub wait` removed
(`hub wait done`), the watchdog's mark dropped (a new turn), the session gone. A new ping of the session takes the place of
its open repeats.

Out: owner.notify {id: r<seq> | w<seq> | w<seq>.<n>, title, text, session, push: false} through the spool. The same id is never sent
twice: the sent ids live in <state>/quiet-unread/state.json, written after the spool. The first start begins at the journal's end
(history is not replayed). `python3 main.py --dry [hours]` prints what the current journal would have sent, sends nothing.
"""
import datetime, json, os, re, subprocess, sys, time

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
HEAD = 300            # characters of a late result's first line and of the owner's word on its plaque
CHECK_TIMEOUT = 120   # the child gives up: the result is logged, not sent
SEQ = re.compile(rb'^\{"seq":([0-9]+),')
PASS_ON = re.compile(r"^\s*[—–-](\s|$)")   # "—" and "— Done 3 of 5": nothing to read (main.js PASS_ON)
COUNTER = re.compile(r"^\s*(готово|done)\s+\d+\s+(из|of)\s+\d+\b[^\n]*$", re.I)   # a bare conveyor counter line
# a `hub wait` for the owner: "владелец: …", "owner: …" at the start, "отмашка" anywhere (hub-sync proactive.py WAIT_OWNER),
# but not "… потом владельцу": that one waits for another session first
OWNER_WAIT = re.compile(r"^\s*(владел|owner\b)|отмашк", re.I)
LOOK = {"en": "👀 Waits for you: ", "ru": "👀 Ждёт тебя: "}
TITLE = 150           # characters of the first line in the title of a ping
AGAIN = 15 * 60       # a watchdog's mark does not ping a session pinged this recently (a new hub wait still does)
EVERY = 2 * 3600      # an unanswered ping comes again this often, in work hours
REPEATS = 4           # times it comes again, at most
WORK = (10, 19)       # the work hours of a work day, local time
RETRY = 600           # a repeat whose check failed is tried again this much later
FORGET = 7 * 86400    # an open repeat is dropped this long after its ping
ZONE = None           # the clock of work hours: the machine's local time (tests set UTC)
ANSWERS = (b'"message.received"', b'"message.reacted"', b'"permission.answered"', b'"delegation.created"')
WANTED = (b'"turn.result"', b'"core.rejected"', b'"watch.needs_owner"') + ANSWERS   # the journal lines parsed
CHECKED = (b'"turn.result"', b'"watch.needs_owner"')                      # the lines checked in a child


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


def late(st, ev):
    """A late result in the thread of the owner's word, for the page: a later turn of a chain his own word began (not his
    direct reply: turn_marker is not the word), that the core counted to him (owner_out) but showed nowhere as his reply -
    neither as the session's owner_reply nor as the reply line of a task of his (replied_seq). The page shows it as a plaque
    in the chat where he said that word (at), so that a result does not hide in a chat he is not in; a word from Telegram or
    the terminal has no chat on the page: at is None, any open chat but the session's own. A result in the chat the word was
    said in is already in front of him: none. {kind, seq, session, at, head, words} or None."""
    text = maybe(ev)
    if text is None:
        return None
    name, seq = ev["entity"], ev["seq"]
    sess = (st.get("sessions") or {}).get(name) or {}
    if sess.get("kind") == "hub" or sess.get("owner_out") != seq or sess.get("owner_reply") == seq:
        return None
    if (sess.get("merged") or {}).get("seq") == seq:
        return None
    if any(d.get("replied_seq") == seq and d.get("for") for d in (st.get("delegations") or {}).values()):
        return None
    root = sess.get("turn_root")
    word = (st.get("messages") or {}).get(root or "") or {}
    if not root or sess.get("turn_marker") == root or not word.get("from_owner"):
        return None
    at = word.get("session", word.get("to")) if word.get("channel") == "web" else None
    if at == name:
        return None
    words = " ".join(str(word.get("text") or "").split())
    return {"kind": "late", "seq": seq, "session": name, "at": at, "head": text.splitlines()[0].strip()[:HEAD],
            "words": words[:HEAD]}


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


def owner_waits(st, name):
    """The `hub wait`s of session name that wait for the owner and are still on: {kin: what it waits for}."""
    from core import schedule
    got = {}
    for jid, job in (st.get("schedule") or {}).items():
        if not isinstance(job, dict) or job.get("session") != name or job.get("state") in schedule.ENDED:
            continue
        what = schedule.waiting_for({**job, "id": jid})
        if what and OWNER_WAIT.search(what):
            got[schedule.kin(jid)] = " ".join(what.split())
    return got


def look(st):
    """ "👀 Waits for you: " in the owner's language."""
    try:
        from core import i18n
        lang = i18n.state_lang(st)
    except Exception:   # noqa: BLE001 — an older core without languages: English
        lang = None
    return LOOK.get(lang) or LOOK["en"]


def _ping(st, name, seq, head, text):
    head = head[:TITLE] + ("…" if len(head) > TITLE else "")
    return {"id": f"w{seq}", "title": look(st) + head, "text": text, "session": name, "push": False}


def waiting(st, ev):
    """Result ev to the owner while its session waits for him (see the module doc): {notice, waits: [kins], turn, post}
    or None. The parent sends it once per wait (waits); its notice replaces r<seq>."""
    text = maybe(ev)
    if text is None:
        return None
    name, seq = ev["entity"], ev["seq"]
    sess = (st.get("sessions") or {}).get(name) or {}
    if sess.get("kind") == "hub" or sess.get("owner_out") != seq or (sess.get("merged") or {}).get("seq") == seq:
        return None
    waits = owner_waits(st, name)
    if not waits:
        return None
    what = "; ".join(dict.fromkeys(waits.values()))
    sent = sess.get("owner_reply") == seq or any(d.get("replied_seq") == seq and d.get("for")
                                                  for d in (st.get("delegations") or {}).values())
    head = text.splitlines()[0].strip()
    return {"notice": _ping(st, name, seq, head, what if sent else text), "waits": sorted(waits),
            "turn": f"{name}:{sess.get('turn_seq')}", "what": what,
            "post": {"kind": "wait", "seq": seq, "session": name, "at": None, "head": head[:HEAD], "words": what[:HEAD]}}


def owners_turn(st, sess):
    """Whether the session's turn is on the owner's own word: his message, his word passed on (--for), or his task -
    `for` with no `for_session` (as the core's digest of his tasks); not the chain's root, which an old word of his to
    the hub gives to every task of every session after it. A turn without a marker goes on with the session's task."""
    msg = (st.get("messages") or {}).get(sess.get("turn_marker") or "")
    if msg and (msg.get("from_owner") or msg.get("re")):
        return True
    did = (msg.get("task") or msg.get("for_delegation") or msg.get("delegation") or msg.get("about") if msg
           else sess.get("delegation") or sess.get("last_task"))
    d = (st.get("delegations") or {}).get(did or "") or {}
    return bool(d.get("for") and not d.get("for_session"))


def marked(st, ev):
    """The watchdog's "waits for you" mark ev, as the core took it: {notice, waits: [], turn} or None. The parent sends
    it once per turn and not within AGAIN of the session's last ping. The page shows the mark itself (attention)."""
    name, data = ev.get("entity"), ev.get("data") or {}
    sess = (st.get("sessions") or {}).get(name) or {}
    if not sess or sess.get("kind") == "hub" or (sess.get("attention") or {}).get("since") != ev["ts"]:
        return None   # rejected, or not this mark
    if not owners_turn(st, sess) or not owner_waits(st, name):
        return None   # a guess: the turn is not on his task, or nothing of the session says it waits for him
    ask, text = " ".join(str(data.get("ask") or "").split()), str(data.get("text") or "").strip()
    head = ask or (text.splitlines() or [""])[0].strip()
    if not head:
        return None
    return {"notice": _ping(st, name, ev["seq"], head, text or ask), "waits": [], "turn": f"{name}:{sess.get('turn_seq')}",
            "what": head, "mark": ev["ts"]}


def still(st, nag):
    """Whether the wait of an open repeat is still on in state st: its session is there, its `hub wait`s are not removed
    (a wait whose checks are done still waits), or - a watchdog's mark - the very mark is still on the session."""
    from core import schedule
    sess = (st.get("sessions") or {}).get(nag["session"]) or {}
    if not sess or sess.get("state") == "removed":
        return False
    if not nag.get("kins"):
        return (sess.get("attention") or {}).get("since") == nag.get("mark")
    jobs = [job for jid, job in (st.get("schedule") or {}).items()
            if isinstance(job, dict) and schedule.kin(jid) in nag["kins"]]
    return bool(jobs) and not any(job.get("state") == "removed" for job in jobs)


def answered(e):
    """The session the owner answered with journal event e, or None: his message to it (his own, or his word passed on
    with `for`), a task for him given to it, his reaction to its post, his answer to its card."""
    data, kind = e.get("data") or {}, e.get("type")
    if kind == "message.received" and (data.get("owner") or data.get("for")):
        return data.get("to")
    if kind == "delegation.created" and data.get("for"):
        return data.get("session")
    if kind == "message.reacted" and data.get("owner"):
        return data.get("session")
    if kind == "permission.answered" and data.get("owner"):
        return e.get("entity")
    return None


def _local(ts):
    return datetime.datetime.fromtimestamp(ts, ZONE) if ZONE else datetime.datetime.fromtimestamp(ts).astimezone()


def off(day):
    """Whether date day is a day off: the Russian work calendar hub-sync keeps (workday), else Saturday and Sunday."""
    try:
        with open(os.path.join(STATE, f"workcal-{day.year}.json"), encoding="utf-8") as f:
            days = json.load(f)["off"]
        return day.strftime("%m-%d") in days
    except (OSError, ValueError, KeyError, TypeError):
        return day.weekday() >= 5


def next_work(ts):
    """The first moment at or after ts in work hours of a work day."""
    t = _local(ts)
    for _ in range(60):
        start, end = t.replace(hour=WORK[0], minute=0, second=0, microsecond=0), t.replace(hour=WORK[1], minute=0,
                                                                                            second=0, microsecond=0)
        if not off(t.date()) and t < end:
            return max(t, start).timestamp()
        t = (start + datetime.timedelta(days=1)).replace(hour=0)
    return ts


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


def checked_still(seq, nag):
    """The child: whether the wait of repeat nag is still on right after event seq (None: no state)."""
    st = state_at(seq)
    return None if not st else still(st, nag)


def check(seq):
    """The child: {notice, late, wait} for result seq of the journal, {wait} for a watchdog's mark, or None."""
    ev = None
    with open(JOURNAL, "rb") as f:
        for line in f:
            if line.startswith(b'{"seq":%d,' % seq) and any(w in line[:300] for w in CHECKED):
                ev = json.loads(line)
    if not ev:
        return None
    st = state_at(seq)
    if not st:
        return None
    if ev["type"] == "watch.needs_owner":
        return {"wait": marked(st, ev)}
    return {"notice": important(st, ev), "late": late(st, ev), "wait": waiting(st, ev)}


def ask_child(seq, nag=None):
    """Run the check in a child process: the core's state stays out of this one. ({notice, late} or None, error or None);
    with nag: whether its wait is still on."""
    args = ["--still", str(seq), json.dumps(nag)] if nag else ["--check", str(seq)]
    try:
        out = subprocess.run([sys.executable, os.path.abspath(__file__), *args], capture_output=True,
                             timeout=CHECK_TIMEOUT, env=os.environ.copy())
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if out.returncode:
        return None, (out.stderr.decode("utf-8", "replace").strip().splitlines() or ["code %d" % out.returncode])[-1]
    return json.loads(out.stdout.decode("utf-8") or "null"), None


def send(notice):
    from core import spool
    spool.put(os.path.join(STATE, "spool"), "owner.notify", None, notice, src="ext:" + KEY)


def post(late):
    """A late result into the plugin's own channel: the page reads it (hub.feed); the channel goes nowhere else."""
    from core import spool
    spool.put(os.path.join(STATE, "spool"), "ext.post", None,
              {"plugin": NAME, "text": json.dumps(late, ensure_ascii=False)}, src="ext:" + KEY)


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

    def __init__(self, mine, dry=False):
        self.mine = mine   # {seq, ino, offset, sent: [ids], posted: [ids], waited: [wait kins], pinged: [turns]}
        for key in ("sent", "posted", "waited", "pinged"):
            mine.setdefault(key, [])   # a state saved by an older version lacks the newer list
        mine.setdefault("pinged_at", {})   # {session: ts of its last ping}
        mine.setdefault("nag", {})   # {wid: {seq, session, kins, mark, title, what, n, due, at}} open repeats
        self.pending = []  # [(event, seen at)] results waiting for the core's verdict
        self.dry = [] if dry else None   # a dry run: [(ts, kind, data)] of what would go out; nothing is sent or saved

    def _send(self, notice, now):
        if self.dry is None:
            send(notice)
        else:
            self.dry.append((now, "notice", notice))

    def _post(self, late, now):
        if self.dry is None:
            post(late)
        else:
            self.dry.append((now, "post", late))

    def lines(self):
        """New journal lines: (seq, event, offset of the line) - the event parsed only for a result, a rejection or a
        watchdog's mark, else None; the offset is None for the end of the archive after a rotation."""
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
                        wanted = any(w in line[:300] for w in WANTED)
                        got.append((int(head[1]), json.loads(line) if wanted else None, at))
        except OSError:
            return []
        self.mine.update(ino=now, offset=offset)
        return got

    def step(self, now=None):
        """One read: new results queue up, settled ones (the core's verdict line is written, or SETTLE passed) are
        checked and sent; due repeats are checked and sent. The notices sent."""
        now = time.time() if now is None else now
        return self.feed(self.lines(), now)

    def feed(self, items, now):
        before, last, heard = dict(self.mine), self.mine.get("seq") or 0, []
        for seq, e, at in items:
            if seq <= last:
                continue   # read already (a carried part after a rotation, a reread from the start)
            who = e and answered(e)
            if who:
                heard.append((seq, who))
            elif e and e["type"] == "core.rejected":
                of = (e.get("data") or {}).get("of")
                self.pending = [p for p in self.pending if p[0]["seq"] != of]
            elif e and (e["type"] == "watch.needs_owner" or maybe(e) is not None):
                self.pending.append((e, now, at))
            self.mine["seq"] = last = seq
        sent = []
        while self.pending and (self.pending[0][0]["seq"] < last or now - self.pending[0][1] >= SETTLE):
            ev = self.pending.pop(0)[0]
            nid, pid, wid = f"r{ev['seq']}", f"p{ev['seq']}", f"w{ev['seq']}"
            if {nid, wid} & set(self.mine["sent"]) and {pid, wid} & set(self.mine["posted"]):
                continue
            got, err = ask_child(ev["seq"])
            if err:
                log("check", ev["seq"], "failed:", err)
                continue
            notice, lt, wt = (got or {}).get("notice"), (got or {}).get("late"), (got or {}).get("wait")
            name, at_ts = ev.get("entity"), ev.get("ts") or now
            if wt and (any(k not in self.mine["waited"] for k in wt["waits"]) if wt["waits"]
                       else wt["turn"] not in self.mine["pinged"]
                       and at_ts - self.mine["pinged_at"].get(name, 0) >= AGAIN):
                self.mine["pinged_at"] = {**self.mine["pinged_at"], name: at_ts}
                if wid not in self.mine["sent"]:
                    self._send(wt["notice"], now)   # the result's own text when the bot did not send it: instead of r<seq>
                    self.mine["sent"] = (self.mine["sent"] + [wid])[-KEEP:]
                    sent.append(wt["notice"])
                    log("pinged", wid, ev.get("entity"))
                    nags = {k: v for k, v in self.mine["nag"].items() if v["session"] != name}   # it takes their place
                    nags[wid] = {"seq": ev["seq"], "session": name, "kins": wt["waits"], "mark": wt.get("mark"),
                                 "title": wt["notice"]["title"], "what": wt.get("what") or "", "n": 0,
                                 "due": next_work(now + EVERY), "at": now}
                    self.mine["nag"] = nags
                self.mine["waited"] = (self.mine["waited"] + [k for k in wt["waits"] if k not in self.mine["waited"]])[-KEEP:]
                self.mine["pinged"] = (self.mine["pinged"] + [wt["turn"]])[-KEEP:]
                notice, lt, pid = None, wt.get("post"), wid
            elif wt and not wt["waits"]:   # a mark not pinged (pinged lately): an open repeat of a mark follows the new one
                self.mine["nag"] = {k: {**v, "mark": wt["mark"]} if v["session"] == name and not v["kins"] else v
                                    for k, v in self.mine["nag"].items()}
            if notice and nid not in self.mine["sent"]:
                self._send(notice, now)   # first the spool, then the record: a crash between them repeats, the id edits the same message
                self.mine["sent"] = (self.mine["sent"] + [nid])[-KEEP:]
                sent.append(notice)
                log("sent", nid, ev.get("entity"))
            if lt and pid not in self.mine["posted"]:
                self._post(lt, now)
                self.mine["posted"] = (self.mine["posted"] + [pid])[-KEEP:]
                log("posted", pid, ev.get("entity"), "->", lt["at"] or "*")
        sent += self.nag(heard, now)
        if self.dry is not None:
            return sent
        if self.mine != before:
            ev, _, at = self.pending[0] if self.pending else (None, None, None)
            # a result still waiting: a restart reads again from its line
            save({**self.mine, "seq": ev["seq"] - 1, "offset": at} if at is not None else self.mine)
        return sent


    def nag(self, heard, now):
        """Close the repeats he answered (heard: [(seq, session)]) or that are old, check and send the due ones."""
        nags = {k: v for k, v in self.mine["nag"].items()
                if now - v["at"] < FORGET and not any(s == v["session"] and seq > v["seq"] for seq, s in heard)}
        sent = []
        for wid, v in sorted(nags.items(), key=lambda kv: kv[1]["due"]):
            if v["due"] > now or self.pending:
                continue   # not yet; or a result read is not checked yet: it may take the place of this one
            on, err = ask_child(self.mine["seq"], v)
            if err or on is None:
                log("repeat", wid, "check failed:", err or "no state")
                nags[wid] = {**v, "due": now + RETRY}
                continue
            if not on:
                log("repeat", wid, "over")
                del nags[wid]
                continue
            n = v["n"] + 1
            notice = {"id": f"{wid}.{n}", "title": v["title"], "text": f"{v['session']}: {v['what']}",
                      "session": v["session"], "push": False}
            self._send(notice, now)
            sent.append(notice)
            log("repeated", notice["id"], v["session"])
            if n >= REPEATS:
                del nags[wid]
            else:
                nags[wid] = {**v, "n": n, "due": next_work(now + EVERY)}
        if nags != self.mine["nag"]:
            self.mine["nag"] = nags
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
        mine.update(ino=journal.identity(JOURNAL), offset=size, seq=0, sent=mine.get("sent") or [],
                    posted=mine.get("posted") or [])
    return Tail(mine)


def dry(hours, now=None):
    """What the tail would have sent over the last hours of the current journal, repeats too, replayed on the events'
    own clock and then on to now (nothing is sent or saved). Prints each notice and post, then the repeats by session."""
    from core import journal
    now = time.time() if now is None else now
    since, offset, seq = now - hours * 3600, 0, 0
    with open(JOURNAL, "rb") as f:
        for line in f:
            head = SEQ.match(line)
            if head and b'"ts":' in line[:80] and json.loads(line)["ts"] >= since:
                break
            offset, seq = offset + len(line), int(head[1]) if head else seq
    tail = Tail({"ino": journal.identity(JOURNAL), "offset": offset, "seq": seq}, dry=True)
    items, clock = tail.lines(), since
    for item in items:
        clock = max(clock, (item[1] or {}).get("ts") or clock)
        tail.feed([item], clock)
    while clock < now:
        clock = min(now, clock + 600)
        tail.feed([], clock)
    by = {}
    for ts, kind, data in tail.dry:
        what = data["id"] if kind == "notice" else "post " + data["kind"]
        print(time.strftime("%d.%m %H:%M", time.localtime(ts)), data["session"], what,
              (data.get("title") or data.get("head") or "")[:100], flush=True)
        if kind == "notice" and "." in data["id"]:
            by[data["session"]] = by.get(data["session"], 0) + 1
    print("lines", len(items), "repeats", sum(by.values()), json.dumps(by, ensure_ascii=False))
    for wid, v in tail.mine["nag"].items():
        print("open", wid, v["session"], "sent", v["n"], "next", time.strftime("%d.%m %H:%M", time.localtime(v["due"])),
              v["what"][:100])


def main(argv):
    if argv[:1] == ["--check"]:
        print(json.dumps(check(int(argv[1])), ensure_ascii=False))
        return
    if argv[:1] == ["--still"]:
        print(json.dumps(checked_still(int(argv[1]), json.loads(argv[2]))))
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
