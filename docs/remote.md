# Handheld remote — design

A battery-powered ESP32-C6 with an OLED and two knobs that controls the
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
| GPIO1 | Pot A wiper | ADC1_CH1 |
| GPIO2 | Pot B wiper | ADC1_CH2 |
| GPIO3 | Pot top rail | **digital output**, high only while sampling |
| GPIO7 | Button | LP GPIO → deep-sleep wake source |
| GPIO10 | I²C SDA | OLED |
| GPIO11 | I²C SCL | OLED |

The GME12864-13 is a 4-pin I²C SSD1306-class 128×64 panel: `GND VCC SCL SDA`,
address usually `0x3C`.

## Power

The decisive detail is that **a potentiometer is a permanent resistive load**.
Wired across 3V3, two 10 kΩ pots draw 660 µA forever — 15.8 mAh/day, which on
a 430 mAh cell is 27 days and swamps every other number in the design.

Powering their top rail from GPIO3 and raising it only to sample costs about
2 seconds of conduction per day:

| Configuration | Draw | Life on 430 mAh |
|---|---|---|
| Two 10 kΩ pots on 3V3, always on | 15.8 mAh/day | 27 d |
| Two 100 kΩ pots on 3V3, always on | 1.6 mAh/day | 271 d (but poor ADC source impedance) |
| Two 10 kΩ pots, GPIO-switched | ~0 | — |

Full budget with GPIO-switched 10 kΩ pots, assuming 20 uses/day at 10 s:

| Component | mAh/day |
|---|---|
| Awake: CPU + OLED + radio bursts, ~55 mA × 200 s | 3.1 |
| Matter ICD idle (light sleep, 100–300 µA) | 2.4–7.2 |
| Pots | ~0 |
| **Total** | **5.5–10.3 → 6–12 weeks** |

### Things that destroy this

* **A stock dev board's power LED** draws ~2 mA on its own: 48 mAh/day, nine
  days, and all the sleep work is wasted. Desolder it or use a bare module.
* **Wiring the cell to 3V3 directly.** A full LiPo is 4.2 V; the C6's maximum
  is 3.6 V. Use a low-quiescent LDO (ME6211-class, ~1 µA) — not one with a
  50 µA quiescent, which would cost more than the radio.
* Charging needs a TP4056-class module with protection.

## Interaction

Absolute knobs have a stale-position problem: if the lights were changed from
the desktop app, the pot no longer reflects reality and the first touch would
jump. So:

* On wake, read both pots but **send nothing**. Draw the bulb's actual state
  and a marker for where each knob is sitting.
* Transmit only once a pot moves beyond a small deadband, then track it
  absolutely. The knob "takes over" on first deliberate movement.
* Rate-limit exactly as the desktop app does: newest value wins, one command
  in flight per channel, ~100 ms spacing. A knob sweep otherwise emits
  hundreds of commands that a Thread mesh will not absorb.

## Screen (128×64)

```
┌──────────────────────────────┐
│ BOTH BULBS            ●  87% │   target, on/off, battery
│                              │
│ Bright  ████████████░░░  78% │   filled = bulb, caret = knob
│                    ▲         │
│ White   █████░░░░░░░░  2700K │
│              ▲               │
│                              │
│ [btn] toggle    hold: select │
└──────────────────────────────┘
```

## Build order

1. Second C6 (or an H2 — no WiFi radio, so lower idle draw for a Thread-only
   device), bare module or LED removed.
2. Clone `esp-matter`; start from its `light_switch` example. 4 MB flash is the
   bare minimum, so use a custom partition table with OTA disabled.
3. Bring up OLED + pots + button on USB power first; get the UI right before
   touching Matter or power management.
4. Commission onto the fabric, write ACLs and bindings via matter-server's
   `write_attribute`.
5. Add the ICD/sleep behaviour last — it makes everything harder to debug, so
   it should go in once the rest is known-good.
6. Battery, LDO, charger.
