# LG Soundbar Plus

A Home Assistant custom integration for LG soundbars that speak the local
control protocol on TCP port 9741.

It exists because the core `lg_soundbar` integration reports the wrong state
and the wrong input list on several models. Everything here was measured
against a real LG SN-series unit rather than taken from the generic tables in
the `temescal` library.

## What it fixes

| | Core `lg_soundbar` | This integration |
|---|---|---|
| Power state | Stuck on, forever | Derived from the active input, updated by push |
| Input list | Taken from the speaker's own list, which is wrong | Verified table, so the current input is always in the list |
| Turn off | Sends a field this hardware ignores | Arms a one-minute sleep timer — see the caveat below |
| Speaker trim | — | Woofer, rear, centre, top |
| Settings | — | DRC, Neural:X, night mode, auto volume, auto power, TV remote, rear speakers |
| Sleep timer | — | Exposed as a number |

## Findings behind the design

These are measurements from an SN-series unit. They are written down because
they contradict what the library and the core integration assume, and because
other owners are hitting the same wall in
[home-assistant/core#152742](https://github.com/home-assistant/core/issues/152742).

**There is no power status field.** `SPK_LIST_VIEW_INFO` never carries
`b_powerstatus` on this hardware. The core integration's state therefore never
updates and defaults to on permanently. Power is inferred here from
`i_curr_func` instead: the speaker parks on the network input in standby and
moves to a real input when it wakes.

**There is no working power command, and no working standby trigger either.**
`b_powerkey` — what the core integration sends for turn on and turn off —
produces no response and no state change. That held with an active input
signal and without one, with `b_auto_power` on and off, and with sixty seconds
of passive listening afterwards so a wake-on-poll could not mask it.
`b_powerstatus`, `b_power`, `i_power` and `b_standby` are all unsupported as
writes.

A one-minute sleep timer is the closest thing found, and it is not enough. The
timer is accepted, counts down, and clears itself — and the speaker stays
awake on the same input. Measured end to end: the timer was armed at 11:07:44
and had cleared itself by 11:09:43, and eighty minutes later a fresh
connection asked `get_func()` and got `i_curr_func: 4` back in under a second,
with the TV off the whole time. `turn_off` therefore arms a timer rather than
turning anything off, which is the honest description of what it does.

**Standby is not announced.** Over the same eighty minutes the speaker pushed
nothing at all, on a socket that had never reconnected (`bytes_sent` still
carried the original requests). Power state is therefore read from the
selected input: the speaker parks on the network input in standby and moves to
a physical one when it wakes.

**PLAY_INFO is announced but never retracted.** The speaker pushes a track as
soon as something starts streaming to the network input, and then says nothing
when it stops. It does answer a direct query honestly — an idle speaker
returns `{}` — so the end of playback is only ever discoverable by asking. A
cached title left unchecked was observed still being reported twelve hours
later, holding the entity awake the whole time.

So this is the one thing the integration asks about: while a track is cached on
the network input, `PLAY_INFO` is re-requested once a minute until the speaker
says it is empty. That window is also the only time the speaker is either
certainly awake or has just gone quiet, which is what keeps a push-only design
honest without waking anything up. In every other state nothing is sent.

An empty reply has to *replace* the cache rather than merge into it — merging
an empty payload is a no-op, which is precisely how the stale track survived.

**The speaker's own input list is wrong.** It advertises
`ai_func_list = [0, 1, 15, 6, 19]`, but sweeping every index shows the ones it
truly accepts are `[0, 1, 4, 6, 19, 20]`. Index 15 is silently rewritten to 4,
7 to 6, 18 to 19, and 2 to 1; everything else falls back to 0. So the speaker
can be sitting on an input that is absent from the list it just handed you,
which is what breaks the source dropdown. This integration ignores the
advertised list.

**Trim levels are unsigned on the wire.** The device reports its range in dB
(`i_woofer_min: -15`, `i_woofer_max: 6`) but carries a zero-based step count
(`i_woofer_level: 21`). Writing 0, 3 and 15 reads back verbatim, and writing
-3 reads back as 3. So `dB = raw + min`, and the conversion is done here.

**Barely poll.** Requests are avoided because they light the front panel; the sole exception is the playback check above.
This integration fetches once at startup and then relies entirely on the
device's push messages, which arrive within a second of a real change.

## Install

Add this repository to HACS as a custom repository (category: Integration),
install it, restart Home Assistant, then add **LG Soundbar Plus** from
Settings → Devices & Services and enter the speaker's address.

You can run this alongside Google Cast on the same speaker. Cast handles
casting, album art and media metadata, which the 9741 protocol does not carry;
this integration handles input, sound mode, trim and settings.

## Known gaps

- **Turning off does not work.** `turn_off` arms a one-minute sleep timer,
  which the speaker then ignores; nothing found so far puts this hardware into
  standby. The service is kept because the LG mobile app does manage it, so a
  real command exists and this is where it will go once found. Capturing what
  the app sends on port 9741 would settle it — the protocol uses a fixed
  AES-256-CBC key, so a capture is fully decryptable. Until then, treat
  `turn_off` as "start a sleep timer", not as power off.
- **AV sync** is reported but the device does not report a valid range for it,
  so no entity is created rather than guessing one.
- **Side and dialogue levels** are reported but `temescal` has no setter for
  them, so they are read-only and not exposed.
- Only tested on an SN-series unit. Other models are likely to need their own
  entries in the source table — the media player exposes the raw index as a
  `source_index` attribute to make that easy to work out.

## Credit

Builds on [temescal](https://github.com/google/python-temescal) by Matthew
Garrett for the wire protocol.

## Licence

MIT. See [LICENSE](LICENSE).
