# Handheld remote — design

A desk-mounted Seeed XIAO ESP32C6 with a 12-key pad that controls the
KAJPLATS bulbs **directly over Thread**, with no hub, no laptop and no border
router in the command path.

Mains powered from a 5 V adapter, not a battery. That decision removes most
of the hard parts: no sleep modes, no wake-source constraints, and the device
joins the mesh as a full **Thread Router** rather than a sleepy end device —
faster to respond, more reliable, and it extends the mesh instead of
depending on it.

## Why it works without a hub

Matter devices can hold a **Binding** table: a list of peers a client cluster
sends to. Commission the remote onto the existing fabric, grant it `Operate`
privilege in each bulb's Access Control List, write a binding pointing at each
bulb, and from then on it talks to them peer-to-peer over the Thread mesh.

The mesh itself survives without a border router — both bulbs are
mains-powered Thread **Routers** and keep the network alive on their own. That
was confirmed accidentally: with `otbr-agent` stopped, the mesh stayed up and
a newly booted node joined it as a child.

The bulbs' current ACL grants admin only to the controller:

```
0/31/0 → [{privilege: 5 (Administer), authMode: 2 (CASE), subjects: [112233]}]
```

so the remote needs a second entry at privilege 3 (`Operate`) for its own node
id. A border router *is* still needed for the one-time commissioning and ACL
write — which is why the existing C6 stays an RCP and the remote is a second
board.

## Controls

There is no display, which rules out modal controls: an earlier draft used
`#` to flip between a brightness mode and a white mode, which is fine with a
screen telling you which is live and unusable without one, because every
press becomes a guess.

So brightness — by far the most-used control — is unconditional, and white
temperature sits behind a momentary shift that announces itself on the LED
and times out on its own after 3 s:

| Key | Action |
|---|---|
| `1`-`9` | Brightness, 11% to 100% — always, no mode |
| `#` then `1`-`9` | White temperature, 2202 K to 6535 K (LED lit while armed) |
| `*` | Toggle power — 1 blink on, 2 blinks off |
| `0` | Cycle target BULB 1 → BULB 2 → BOTH — blinked back 1/2/3 |

| Key | Brightness | White (after `#`) |
|---|---|---|
| 1 | 11% | 2202 K |
| 5 | 55% | 3289 K |
| 9 | 100% | 6535 K |

Key 1 is deliberately dim rather than off — `*` is for off.

The shift is momentary rather than sticky precisely so forgetting about it
cannot strand the remote in a state you cannot see. The target is the only
state with no other observable signal, which is why `0` blinks it back.

## What the axes do

These are **white-spectrum (WS)** bulbs: `ColorCapabilities = 24`, hue/sat bit
clear, device type `0x010C Color Temperature Light`. They have no hue.

| Axis | Cluster | Range |
|---|---|---|
| BRIGHT | LevelControl `moveToLevelWithOnOff` | 1–254 |
| WHITE | ColorControl `moveToColorTemperature` | 454→153 mireds (2202–6535 K) |
| `*` | OnOff `toggle` | — |

The WHITE axis becomes a hue axis unchanged if a colour-capable (CWS) bulb is
ever added; only the mapping differs.

## Pin assignment — Seeed XIAO ESP32C6

The XIAO breaks out eleven GPIOs and reserves three more on the board:

| GPIO | Reserved for |
|---|---|
| 3 | **RF switch enable, active low** |
| 14 | Antenna select (low = onboard ceramic, high = external U.FL) |
| 15 | User LED |

GPIO3 matters more than it looks. It has no pull on the board, so firmware
that never touches it leaves the RF switch unpowered and the antenna
effectively disconnected — the radio then works across a desk and nowhere
else, which presents as a flaky mesh rather than as a pin mistake.
`board_init()` drives GPIO3 and GPIO14 low before anything uses the radio.

Header mapping, for cross-checking against the silkscreen:

```
D0=0  D1=1  D2=2  D3=21  D4=22(SDA)  D5=23(SCL)
D6=16 D7=17 D8=19 D9=20  D10=18
```

| Pin | Header | Use |
|---|---|---|
| GPIO0 | D0 | Keypad row — keys `1 2 3` |
| GPIO1 | D1 | Keypad row — keys `4 5 6` |
| GPIO2 | D2 | Keypad row — keys `* 0 #` |
| GPIO21 | D3 | Keypad row — keys `7 8 9` |
| GPIO22 | D4 | I²C SDA |
| GPIO23 | D5 | I²C SCL |
| GPIO16 | D6 | Keypad column — `1 4 7 *` |
| GPIO17 | D7 | Keypad column — `2 5 8 0` |
| GPIO19 | D8 | Keypad column — `3 6 9 #` |

### Why the rows are wired out of order

Historical, and no longer a constraint — but the wiring is built and working,
so it stays. Deep-sleep wake needed LP/RTC-capable pins (GPIO0-7 on the C6),
and the XIAO exposes only GPIO0-2 of those, so three of four rows could wake
the chip and one could not. The `* 0 #` row therefore took a wake-capable pin
and `7 8 9` took the one that could not.

Mains power made that moot. **Wire the pad's third and fourth rows swapped**
to match `KEYPAD_ROW_PINS`, or renumber the table in `board.h` if you would
rather wire them in printed order.

### Checking your wiring

Keypad ribbons differ between manufacturers, so every press logs where it
landed in the matrix before the layout table turns it into a character:

```
keypad: press at row 0 (GPIO0), col 0 (GPIO16) -> '1'
```

Press the key marked `1`: it should report row 0, col 0. If not, reorder
`KEYPAD_ROW_PINS` / `KEYPAD_COL_PINS` in `board.h` rather than rewiring. If a
press reports nothing at all, rows and columns are swapped — any 4 of the 7
ribbon pins are the rows.

## Power

A 5 V adapter into the XIAO's `5V` pad (or simply USB-C). The onboard
regulator handles the rest — no external step-down, no LDO, no charger.

**Never feed 5 V to the `3V3` pad.** That bypasses the regulator and goes
straight to the C6, whose absolute maximum is 3.6 V.

### Why not a battery

A 430 mAh LiPo was the original plan and would have given roughly 62 days.
It was dropped once the keypad became desk-mounted, because mains power is
free of the three constraints that shaped the earlier design: sleep states,
wake-capable pin placement, and LED frugality.

A USB power bank is specifically a bad idea here even though the capacity
looks adequate. Banks boost their 3.7 V cell to 5 V and you then drop it back
to 3.3 V, so a 400 mAh bank yields ~36-48 days against the LiPo's 62 — but
the real problem is that nearly all of them **auto-shut-off under low load**,
typically below 50-100 mA. A device idling in microamps gets switched off
within seconds of boot, every time.

## Interaction

Discrete keys avoid the stale-position problem knobs would have had: a knob
that no longer matches the bulb (because the desktop app changed it) jumps on
first touch, which is why the pot design needed a deadband and soft takeover.
A key press is unambiguous — it means "go to this step" — so the remote can
act immediately and simply redraw to match.

Commands are still rate-limited as the desktop app does, newest value wins
with ~100 ms per channel. Keypresses are far slower than that in practice,
but a held key or a bounce storm must not become a flood once this is driving
real bulbs.

Debounce is two consecutive agreeing scans at 20 ms, so 40 ms of settling,
and key events are edge-triggered: holding a key yields one event, not a
stream.

## Screen (128×64)

The active axis is drawn inverted, so it is always clear which control the
number keys will act on.

```
BOTH                      [ON]     y=0    target, power
--------------------------------   y=8
[BRIGHT]                   77%     y=12   inverted = active axis
+----------------------------+     y=21   nine-step bar
 WHITE                    3289K    y=33
+--------------+-------------+     y=42
#WHITE *PWR 0TGT                   y=54   context hint
```

Every row is checked against the 64 px height: at y=58 a 7 px footer would
run to y=64 and have its bottom row silently clipped, since `display_pixel`
discards out-of-range writes rather than complaining.

## Build order

1. ~~Second board.~~ **Done** — a Seeed XIAO ESP32C6: built-in battery
   charging, ~15 µA deep sleep, and small enough to hold.
2. Clone `esp-matter`; start from its `light_switch` example. 4 MB flash is the
   bare minimum, so use a custom partition table with OTA disabled.
3. ~~Bring up OLED + keypad on USB power; get the UI right before touching
   Matter or power management.~~ **Done** — `firmware/remote`.
4. Commission onto the fabric, write ACLs and bindings via matter-server's
   `write_attribute`.
5. ~~ICD/sleep behaviour.~~ **Dropped** — mains powered, so the device stays
   awake and joins as a Thread Router.
6. ~~Battery, LDO, charger.~~ **Dropped** — 5 V adapter into the `5V` pad.
