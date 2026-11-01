# Handheld remote — design

A battery-powered ESP32-C6 with an OLED and a 12-key pad that controls the
KAJPLATS bulbs **directly over Thread**, with no hub, no laptop and no border
router in the path.

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

A 12-key pad is 4x3 — `1-9`, `*`, `0`, `#`. There is no A-D row; that is a
16-key 4x4 part. Nine keys therefore have to serve two continuous controls,
so `#` switches which axis they act on and the screen shows which is live.

| Key | Action |
|---|---|
| `1`-`9` | Nine steps on the active axis |
| `#` | Switch axis: BRIGHT ↔ WHITE |
| `*` | Toggle power |
| `0` | Cycle target: BULB 1 → BULB 2 → BOTH |

| Key | BRIGHT | WHITE |
|---|---|---|
| 1 | level 29 (11%) | 2202 K |
| 5 | level 141 (55%) | 3289 K |
| 9 | level 254 (100%) | 6535 K |

Key 1 is deliberately dim rather than off — turning the bulbs off is what `*`
is for.

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

Deep-sleep wake needs LP/RTC-capable pins — GPIO0–7 on the C6 — and the XIAO
exposes only GPIO0, GPIO1 and GPIO2 of those. Three of the four keypad rows
can wake the chip; the fourth cannot.

So the `* 0 #` row goes to a wake-capable pin and `7 8 9` takes the one that
cannot. A remote whose power key will not wake it is a poor remote; losing
wake on 7/8/9 is a much smaller cost. **Wire the pad's third and fourth rows
swapped**, and confirm with the diagnostic below.

For full coverage on all twelve keys, feed the four row lines into one spare
LP pin through signal diodes (cathodes to the rows) and wake on that. Four
diodes, only worth it if missing 7/8/9 turns out to annoy.

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

Switching from knobs to a keypad removed the worst problem in the original
design. **A potentiometer is a permanent resistive load**: two 10 kΩ pots
across 3V3 draw 660 µA forever, which is 15.8 mAh/day and only 27 days on a
430 mAh cell — more than everything else in the design combined. Working
around it needed the pots' top rail driven from a GPIO and energised only
while sampling.

A matrix keypad has no such load. Idle, the columns are released and the rows
sit on their pull-ups with no path between them, so no current flows until a
key is physically pressed, and then only ~73 µA through one 45 kΩ pull-up for
as long as it is held.

Budget, assuming 20 uses/day at 10 s:

| Component | mAh/day |
|---|---|
| Awake: CPU + OLED + radio bursts, ~55 mA × 200 s | 3.1 |
| Matter ICD idle (light sleep, 100–300 µA) | 2.4–7.2 |
| Keypad | ~0 |
| **Total** | **5.5–10.3 → 6–12 weeks** |

### Things that destroy this

* **A stock dev board's power LED** draws ~2 mA on its own: 48 mAh/day, nine
  days, and all the sleep work is wasted. The XIAO is much better behaved
  here — Seeed quote ~15 µA in deep sleep for the whole board — which is a
  large part of why it suits this job.
* **Wiring the cell to 3V3 directly.** A full LiPo is 4.2 V; the C6's maximum
  is 3.6 V. The XIAO solves this on the board: it has battery pads with
  charging and regulation built in, so the cell connects there, not to 3V3.
* Battery voltage is readable on A0 (GPIO0) through a 1:2 divider — but GPIO0
  is a keypad row here, so battery monitoring would need rethinking.

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
5. Add the ICD/sleep behaviour last — it makes everything harder to debug, so
   it should go in once the rest is known-good.
6. Battery, LDO, charger.
