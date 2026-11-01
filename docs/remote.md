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

## Pin assignment

ADC1 is GPIO0–6 on the C6, and GPIO0–7 are LP/RTC-capable so they can wake the
chip from deep sleep. GPIO4, 5, 8, 9 and 15 are strapping pins and GPIO12/13
are USB — all avoided.

| Pin | Use | Notes |
|---|---|---|
| GPIO0–3 | Keypad rows | Read with internal pull-ups; LP-capable, so any row going low can wake the chip |
| GPIO5–7 | Keypad columns | Open-drain, driven low one at a time |
| GPIO10 | I²C SDA | OLED |
| GPIO11 | I²C SCL | OLED |

The matrix needs 7 pins and only 8 LP pins exist, so one strapping pin
(GPIO5) is unavoidable. It is safe in practice: at reset the columns are
high-Z and the row pull-ups are not yet enabled, so a key held during
power-on cannot assert a level on it.

The GME12864-13 is a 4-pin I²C SSD1306-class 128×64 panel: `GND VCC SCL SDA`,
address usually `0x3C`.

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
  days, and all the sleep work is wasted. Desolder it or use a bare module.
* **Wiring the cell to 3V3 directly.** A full LiPo is 4.2 V; the C6's maximum
  is 3.6 V. Use a low-quiescent LDO (ME6211-class, ~1 µA) — not one with a
  50 µA quiescent, which would cost more than the radio.
* Charging needs a TP4056-class module with protection.

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

1. Second C6 (or an H2 — no WiFi radio, so lower idle draw for a Thread-only
   device), bare module or power LED removed.
2. Clone `esp-matter`; start from its `light_switch` example. 4 MB flash is the
   bare minimum, so use a custom partition table with OTA disabled.
3. ~~Bring up OLED + keypad on USB power; get the UI right before touching
   Matter or power management.~~ **Done** — `firmware/remote`.
4. Commission onto the fabric, write ACLs and bindings via matter-server's
   `write_attribute`.
5. Add the ICD/sleep behaviour last — it makes everything harder to debug, so
   it should go in once the rest is known-good.
6. Battery, LDO, charger.
