# Quiet unread: an Agents Hub plugin

The "new" mark on a session (the blue dot in the list and the "New" section in the "Now" tab) lights up only for a result addressed to you: a reply to your message, to your task, or the continuation of such a turn when background work has finished.

Service traffic no longer lights up: session replies to core messages, sessions' reports to each other, "pushed", the handoff before sleep, the watchdog. A card with a question to you is still visible by the "waiting for you" mark.

Two cases the core gets wrong are fixed here:

- your task to a session broke on an error, and the session then sent its result anyway: the core no longer ties that result to your task, the plugin still lights it up (within 3 hours of the break, a line of at least 20 characters);
- a reply that is only a pass-on line or a conveyor counter ("—", "— Done 3 of 5") stays quiet.

## Settings

"Settings" → "Quiet unread": tick the roles for which "new" lights up on any result, as without the plugin. By default only the hub is on: its results are always visible. Specialists, executors and other sessions are off.

The settings text is English by default and Russian when the hub language is Russian.

## Install

"Settings" → "Plugins" → paste the link to this repository → "Check and install". Needs a hub where the core marks results for the owner (`owner_reply` in the session snapshot) and plugins have `hub.addUnread`. On a hub without it the plugin changes nothing: "unread" is decided by the core, as before.

## Tests

```
node --test tests/unread.test.mjs
```

Icon — [3D Fluency](https://icons8.com/icons/3d-fluency) by Icons8.
