"""Constants for the LG Soundbar Plus integration.

The values here are not copied from the temescal library's generic tables.
They were measured against a real LG SN-series soundbar by sweeping every
index and recording what the device actually accepted, because the generic
tables disagree with what this hardware reports.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "lg_soundbar_plus"
DEFAULT_PORT: Final = 9741

# Message types the device speaks. Only these produced responses in testing;
# OPTION_INFO_DEV, C4A_SETTING_INFO and BUILD_INFO_DEV were silently ignored.
MSG_SPK_LIST: Final = "SPK_LIST_VIEW_INFO"
MSG_FUNC: Final = "FUNC_VIEW_INFO"
MSG_SETTING: Final = "SETTING_VIEW_INFO"
MSG_EQ: Final = "EQ_VIEW_INFO"
MSG_PLAY: Final = "PLAY_INFO"
MSG_PRODUCT: Final = "PRODUCT_INFO"

# Input sources, verified by sweeping set_func(0..20) and reading back
# i_curr_func. Indices not listed here were rejected and fell back to 0.
#
# The device's own ai_func_list is unreliable: it advertises [0, 1, 15, 6, 19]
# but 15 resolves to 4, and 20 is settable while being absent from the list.
# Several indices are aliases that the device silently rewrites:
#   7 -> 6, 15 -> 4, 18 -> 19, 2 -> 1
SOURCES: Final[dict[int, str]] = {
    0: "Wi-Fi",
    1: "Bluetooth",
    4: "Optical",
    6: "HDMI",
    19: "USB",
    20: "eARC",
}
SOURCE_IDS: Final[dict[str, int]] = {name: idx for idx, name in SOURCES.items()}

# Aliases the firmware rewrites on its way in. Used to normalise a reported
# i_curr_func that is not a canonical index.
SOURCE_ALIASES: Final[dict[int, int]] = {2: 1, 7: 6, 15: 4, 18: 19}

# i_curr_func value that means "idle on the network input", which is what this
# hardware reports while in standby. There is no b_powerstatus field.
SOURCE_IDLE: Final = 0

# Equaliser presets. Unlike the source table, the library's equaliser names do
# line up with what this hardware reports, so they are reproduced verbatim.
EQUALISERS: Final[list[str]] = [
    "Standard",
    "Bass",
    "Flat",
    "Boost",
    "Treble and Bass",
    "User",
    "Music",
    "Cinema",
    "Night",
    "News",
    "Voice",
    "ia_sound",
    "Adaptive Sound Control",
    "Movie",
    "Bass Blast",
    "Dolby Atmos",
    "DTS Virtual X",
    "Bass Boost Plus",
    "DTS X",
    "AI Sound Pro",
    "Clear Voice",
    "Sports",
    "Game",
]

# Speaker trim levels. The wire protocol carries a zero-based raw value while
# the device reports the usable range in dB, so the two need converting:
#     dB  = raw + min
#     raw = dB - min
# Verified by writing 0/3/15 and reading back verbatim; negative values are
# rejected (-3 came back as 3), confirming the wire value is unsigned.
LEVEL_KEYS: Final[dict[str, tuple[str, str, str]]] = {
    # entity key -> (level field, min field, max field)
    "woofer": ("i_woofer_level", "i_woofer_min", "i_woofer_max"),
    "rear": ("i_rear_level", "i_rear_min", "i_rear_max"),
    "center": ("i_center_level", "i_center_min", "i_center_max"),
    "top": ("i_top_level", "i_top_min", "i_top_max"),
    "side": ("i_side_level", "i_side_min", "i_side_max"),
    "dialog": ("i_dialog_level", "i_dialog_min", "i_dialog_max"),
}

# Boolean settings carried in SETTING_VIEW_INFO. The device answers a set with
# an "ok" that echoes the changed field, so an empty echo means the field is
# not supported and the entity should not be created.
SWITCH_KEYS: Final[dict[str, str]] = {
    "drc": "b_drc",
    "neuralx": "b_neuralx",
    "night_mode": "b_night_time",
    "auto_volume": "b_auto_vol",
    "auto_power": "b_auto_power",
    "tv_remote": "b_tv_remote",
    "rear_speaker": "b_rear",
}

# Sleep timer, in minutes. -1 disables it. Writing a positive value starts a
# countdown that the device announces when it expires; writing 0 stores the
# value but never fires, so 0 is not a usable "sleep now".
SLEEP_OFF: Final = -1
SLEEP_MIN: Final = 1
SLEEP_MAX: Final = 180

# turn_off has no direct command on this hardware. b_powerkey (what the core
# integration sends) is ignored outright: it produces no response and no state
# change, matching reports from other LG soundbar owners.
#
# A one-minute sleep timer is the nearest thing, and it is not sufficient: the
# device accepts it, counts it down, clears it, and stays awake on the same
# input. It is used anyway because it is the only standby-adjacent command that
# the hardware acknowledges at all.
TURN_OFF_SLEEP_MINUTES: Final = 1

SIGNAL_UPDATE: Final = f"{DOMAIN}_update"
