# Quiet unread: an Agents Hub plugin

The "new" mark on a session (the blue dot in the list and the "New" section in the "Now" tab) lights up only for a result addressed to you: a reply to your message, to your task, or the continuation of such a turn when background work has finished.

Service traffic no longer lights up: session replies to core messages, sessions' reports to each other, "pushed", the handoff before sleep, the watchdog. A card with a question to you is still visible by the "waiting for you" mark.

The cases the core gets wrong are fixed here:

- your task to a session broke on an error, and the session then sent its result anyway: the core no longer ties that result to your task, the plugin still lights it up (within 3 hours of the break, a line of at least 20 characters) and sends it to you as a notice in Telegram, once;
- a session you talk to on the page answers later in that talk (a specialist or an executor it called brought the work back): the Telegram bot keeps such a chain on the page as your own talk, the plugin sends that later result to Telegram as a notice, once (your direct reply on the page stays there);
- the page marked a result read only because the session stood open in a visible tab for a second, with nobody at the screen (a chat left on a second monitor while you talk from Telegram or are away): the plugin keeps such a result "new" until you show up in that tab after it came, by a key, a click, a wheel, a touch or a mouse move while that session is open, or by opening it from the list. A held result keeps its place in the list too: it stays in "Answered you" with its reply line, not only as a dot on a folded group. Held results are kept in the browser, a reload keeps them. A result you read on another device stays "new" here until you touch that session here;
- a session answers on your task later, in its own chat (an executor or a specialist brought the work back), while you talk in another chat: the core shows it nowhere as your reply. The plugin puts a plaque above the input field of the chat where you gave that task, "<session> sent a result on your task: <first line>" (a task given from Telegram or the terminal: above any chat but that session's own). A click opens the session; the plaque goes once you have seen the result: the click, × or being at the page in that session's chat. Its row in the list stays "new" until then. Up to 3 plaques, newest on top, for 3 days; seen ones are kept in the browser, a reload keeps them. Results the core already showed as your reply, a session's results to the one that called it and replies in the chat of your own word get no plaque;
- a reply that is only a pass-on line or a conveyor counter ("—", "— Done 3 of 5") stays quiet.

## The process

Sending to Telegram is done by the plugin's process (`main.py`, started by the hub). It reads the tail of the journal and checks each candidate result in a short child process against the core's state at that event, so the core's state is not kept in memory. A result the core already sends itself (your reply, the reply of your task) is skipped. The notice has the id `r<seq>`: a repeat edits the same message. A late result in the thread of your word (the plaque above) goes to the plugin's own channel (`hub feed quiet-unread`), not to Telegram, post id `p<seq>`, once; the page reads the channel when the snapshot names a newer post. The first start begins at the journal's end. `python3 main.py --dry [hours]` prints what the current journal would have sent and sends nothing.

## Settings

"Settings" → "Quiet unread": tick the roles for which "new" lights up on any result, as without the plugin. By default only the hub is on: its results are always visible. Specialists, executors and other sessions are off.

The settings text is English by default and Russian when the hub language is Russian.

## Install

"Settings" → "Plugins" → paste the link to this repository → "Check and install". Needs a hub where the core marks results for the owner (`owner_reply` in the session snapshot) and plugins have `hub.addUnread`. On a hub without it the plugin changes nothing: "unread" is decided by the core, as before.

## Tests

```
node --test tests/unread.test.mjs
cd tests && python3 -m unittest test_backend
```

The backend tests replay events through the core's own reducer: the core is `HUB_CORE`, else the newest layer in `~/.hub-core/layers`.

Icon — [3D Fluency](https://icons8.com/icons/3d-fluency) by Icons8.
