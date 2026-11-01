"""Core types and color math shared by the UI and the backends.

Matter speaks in its own units: hue and saturation are 0-254, brightness
("level") is 0-254, and color temperature is in mireds (micro reciprocal
degrees) rather than kelvin. Everything here converts between those and the
friendlier units the UI works in.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

# Matter cluster ids we care about.
CLUSTER_ON_OFF = 0x0006
CLUSTER_LEVEL = 0x0008
CLUSTER_COLOR = 0x0300
CLUSTER_BASIC_INFO = 0x0028

# Attribute ids within those clusters.
ATTR_ON_OFF = 0x0000
ATTR_CURRENT_LEVEL = 0x0000
ATTR_CURRENT_HUE = 0x0000
ATTR_CURRENT_SATURATION = 0x0001
ATTR_COLOR_TEMP_MIREDS = 0x0007
ATTR_COLOR_MODE = 0x0008
ATTR_COLOR_CAPABILITIES = 0x400A
ATTR_CT_PHYS_MIN = 0x400B
ATTR_CT_PHYS_MAX = 0x400C
ATTR_VENDOR_NAME = 0x0001
ATTR_PRODUCT_NAME = 0x0003
ATTR_NODE_LABEL = 0x0005

# Matter's own scale limits. Level 0 is reserved as "off" by the spec, so the
# lowest level we will ever command is 1.
LEVEL_MIN = 1
LEVEL_MAX = 254
HUE_MAX = 254
SAT_MAX = 254


class ColorMode(Enum):
    """Which of the bulb's two color models is currently driving the output."""

    HS = "hs"
    CT = "ct"


@dataclass
class Bulb:
    """Everything we know about one physical bulb.

    `node_id` / `endpoint_id` address it on the Matter fabric. The rest is the
    last state we observed or commanded, kept in Matter's native units so that
    sending it back needs no conversion.
    """

    node_id: int
    endpoint_id: int
    name: str
    online: bool = True
    on: bool = False
    level: int = LEVEL_MAX
    hue: int = 0
    saturation: int = 0
    mireds: int = 370
    mode: ColorMode = ColorMode.CT
    ct_min: int = 153          # ~6500 K
    ct_max: int = 454          # ~2200 K
    supports_color: bool = True   # hue/saturation capable
    supports_ct: bool = True      # colour-temperature capable
    vendor: str = ""
    product: str = ""

    @property
    def key(self) -> str:
        """Stable identifier used for config storage and UI lookup."""
        return f"{self.node_id}:{self.endpoint_id}"

    def with_changes(self, **changes) -> "Bulb":
        return replace(self, **changes)


@dataclass
class Fabric:
    """Snapshot of the backend's view of the world."""

    bulbs: list[Bulb] = field(default_factory=list)
    connected: bool = False
    detail: str = ""


# --- unit conversions -------------------------------------------------------


def kelvin_to_mireds(kelvin: float) -> int:
    return int(round(1_000_000.0 / max(kelvin, 1.0)))


def mireds_to_kelvin(mireds: float) -> int:
    return int(round(1_000_000.0 / max(mireds, 1.0)))


def matter_hs_to_float(hue: int, saturation: int) -> tuple[float, float]:
    """Matter hue/sat (0-254) to fractions in 0..1."""
    return hue / HUE_MAX, saturation / SAT_MAX


def float_to_matter_hs(hue: float, saturation: float) -> tuple[int, int]:
    """Fractions in 0..1 to Matter hue/sat, clamped to the legal range."""
    h = int(round(clamp(hue, 0.0, 1.0) * HUE_MAX))
    s = int(round(clamp(saturation, 0.0, 1.0) * SAT_MAX))
    return h, s


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


#: sRGB renderings of blackbody radiators, normalised so the brightest
#: channel is 255 (Mitchell Charity's blackbody table). Normalising is what
#: makes the cool end read blue instead of white: an un-normalised 6500 K is
#: almost exactly the sRGB white point, so a physical fit gives a ramp that
#: fades to white and tells the eye nothing.
_BLACKBODY: list[tuple[int, tuple[int, int, int]]] = [
    (1500, (255, 109, 0)),
    (1800, (255, 147, 41)),
    (2200, (255, 166, 69)),
    (2700, (255, 197, 143)),
    (3000, (255, 214, 170)),
    (3500, (255, 228, 206)),
    (4000, (255, 241, 224)),
    (4500, (255, 250, 244)),
    (5000, (255, 255, 251)),
    (5500, (245, 243, 255)),
    (6000, (235, 238, 255)),
    (6500, (227, 233, 255)),
    (7500, (214, 225, 255)),
    (9000, (204, 219, 255)),
]


def kelvin_to_rgb(kelvin: float) -> tuple[int, int, int]:
    """Approximate the sRGB appearance of a white at `kelvin`.

    Used to tint the temperature slider and the white presets, so the control
    previews what it will do. Linear interpolation between table anchors is
    well under a just-noticeable difference at these step sizes.
    """
    kelvin = clamp(kelvin, _BLACKBODY[0][0], _BLACKBODY[-1][0])
    previous_k, previous_rgb = _BLACKBODY[0]
    for current_k, current_rgb in _BLACKBODY:
        if kelvin <= current_k:
            span = current_k - previous_k
            t = 0.0 if span == 0 else (kelvin - previous_k) / span
            return tuple(  # type: ignore[return-value]
                int(round(a + (b - a) * t))
                for a, b in zip(previous_rgb, current_rgb)
            )
        previous_k, previous_rgb = current_k, current_rgb
    return _BLACKBODY[-1][1]
