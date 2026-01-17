# Navien Packet Analysis Guide

## Overview

This guide describes how to use Claude to interactively analyze Navien water heater protocol packets. The workflow allows you to perform actions on your water heater while Claude monitors the packet stream and correlates changes to your actions.

## The Packet Monitor Script

Location: `packet_monitor.py`

**What it does:**
- Reads ESPHome packet logs from stdin
- Parses known packet structures (WATER_STATUS, GAS_STATUS, control commands)
- Reports ONLY changes in unknown/undefined bytes
- Dumps unknown control commands in full
- Silently ignores known control commands and checksum changes

**Known Packet Types:**
1. **WATER_STATUS** (41 bytes, dir=0x50, type=0x50)
   - Contains: temperatures, flow rate, system power, recirculation status
   - Many unknown fields we're trying to reverse engineer

2. **GAS_STATUS** (49 bytes, dir=0x50, type=0x0F)
   - Contains: gas usage, temperatures, version info
   - Also has unknown fields

3. **Control Commands** (dir=0x0F, type=0x50)
   - Known: TURN_ON, TURN_OFF, HOT_BUTTON_PRESS/RELEASE, RECIRC_ON, SET_TEMP, NAVILINK_PRESENT
   - Unknown commands are dumped in full

**Usage:**
```bash
# Run interactively
esphome logs navien-esphome-atom-s3-lite-esp32.yml --device 172.16.10.190 | python3 packet_monitor.py

# Or from saved logs
cat logfile.txt | python3 packet_monitor.py
```

## Interactive Analysis Workflow with Claude

### Setup Phase

1. **Start a new conversation with Claude** (to have clean context)
2. **Provide this context document**
3. **Tell Claude to start the packet monitor in background**

Claude will run:
```bash
esphome logs navien-esphome-atom-s3-lite-esp32.yml --device 172.16.10.190 | python3 packet_monitor.py
```
as a background task.

### Analysis Phase

**Your role:**
- Perform actions on the water heater (turn on tap, adjust temperature, press buttons, etc.)
- Tell Claude what you just did in natural language
- Example: "I just turned on the hot water tap in the kitchen sink"
- Example: "I pressed the hot button on the panel"
- Example: "I adjusted the temperature setpoint from 120°F to 115°F"

**Claude's role:**
- Monitor the background packet monitor output
- Check what fields changed when you performed the action
- Correlate the changes to your action
- Form hypotheses about what unknown fields represent
- Track patterns across multiple actions

**Example interaction:**
```
You: "I just turned on the hot water tap"

Claude: Let me check what the monitor saw...
[Claude checks background task output]

Claude: "I see these changes in WATER_STATUS:
- unknown_10: 0x14 → 0x46 (dec: 20 → 70)
- water_flow: 0x00 → 0x18 (3.2 GPM)
- unknown_19 in GAS_STATUS: Started counting down from 0x5E

Hypothesis: unknown_10 might track water demand or valve state"
```

### Commands for Claude

- "Check the packet monitor" - Claude will read recent output
- "What's changed since last time?" - Claude compares to previous state
- "Stop monitoring" - Claude kills the background task
- "Start fresh" - Claude restarts the monitor (clears history)

## Current State of Knowledge

### Unit Type Differences (from PR #23 testing)

⚠️ **Important:** Protocol interpretation varies by unit type. The system_type byte (byte 1 after the F7 marker) identifies the unit:

| system_type | Unit Model | Notes |
|-------------|------------|-------|
| 0x05 | NPE-240A2, 240A | Standard tankless |
| 0x06 | NCB-240-130H | Combi boiler |

**Key differences observed:**
- **Units flag location:** NPE uses system_status bit 3, NCB uses system_status bit 1
- **Recirculation status:** NPE reflects recirc mode changes in system_status; NCB does not
- **system_power bit 5:** On NCB, corresponds to internal pump running state, not just mode

**Recommendation from PR #23:** Use GAS packet byte 21 (unknown_20) bit 0 for units detection, as it's consistent across all tested units.

---

### WATER_STATUS Packet (41 bytes)

**Structure from navien_proto.h (WATER_DATA):**
```
Bytes 0-5:   Header (marker, unknown_0x05, direction, packet_type, unknown_0x90, len)
Byte 6:      unknown_06
Byte 7:      unknown_07
Byte 8:      heating_mode (DEVICE_HEATING_MODE enum)
Byte 9:      system_power (bitmask - see below)
Byte 10:     operating_state (OPERATING_STATE enum)
Byte 11:     set_temp (target temperature in °C)
Byte 12:     outlet_temp (outlet water temperature in °C)
Byte 13:     inlet_temp (inlet water temperature in °C)
Bytes 14-16: unknown_14, unknown_15, unknown_16
Byte 17:     operating_capacity (% utilization)
Byte 18:     water_flow (raw value, use flow2lpm/flow2gpm to convert)
Bytes 19-23: unknown_19, unknown_20, unknown_21, unknown_22, unknown_23
Byte 24:     system_status (bitmask - units/recirc mode flags)
Bytes 25-26: unknown_25, unknown_26
Byte 27:     boiler_active (boolean)
Bytes 28-31: unknown_28-31 (counters, pinned to 255 on NCB-H)
Byte 32:     unknown_32
Byte 33:     recirculation_enabled (MODE-DEPENDENT bitmask)
Bytes 34-39: unknown_34-39
Byte 40:     checksum
```

**Decoded fields:**

**Byte 8 (heating_mode) - DEVICE_HEATING_MODE enum**
| Value | Enum Name | Description |
|-------|-----------|-------------|
| 0x00 | HEATING_MODE_IDLE | Unit is idle |
| 0x08 | HEATING_MODE_DOMESTIC_HOT_WATER_RECIRCULATING | Scheduled recirculation active |
| 0x10 | HEATING_MODE_SPACE_HEATING | Space heating active (combi units) |
| 0x20 | HEATING_MODE_DOMESTIC_HOT_WATER_DEMAND | Hot water demand (tap open) |

**IMPORTANT:** Value 0x08 only appears during scheduled recirculation mode. In HotButton mode, when recirculation is triggered it shows as 0x20 with recirculation_enabled bit 0 also set.

**Byte 9 (system_power) - Power Status Bitmask**
| Bit | Mask | Description |
|-----|------|-------------|
| 0 | 0x01 | POWER_STATUS_ON_OFF - Unit power on when set |
| 2 | 0x04 | Unknown (was incorrectly included in original 0x05 power mask) |
| 4 | 0x10 | Unknown (set on NCB-H models) |
| 5 | 0x20 | Scheduled recirculation active (1=scheduled recirc enabled, 0=not) |

**Note:** The original code incorrectly used 0x05 (bits 0+2) as the power mask. PR #23 testing confirmed bit 0 (0x01) alone indicates power status. The purpose of bit 2 (0x04) remains unknown.

Observed values (vary by unit):
- NPE-240A2: 0x05 (power on), 0x25 (power on + scheduled recirc)
- NCB-240-130H: 0x17 (power on), 0x37 (power on + scheduled recirc active)
- 240A: 0x05 (power on)

**Behavior note:** On some units, bit 5 (0x20) corresponds to the internal recirculation pump actually running, not just the mode being enabled. This was observed on NCB-240-130H where system_power cycled 0x37↔0x17 as the pump turned on/off.

**Byte 10 (operating_state) - OPERATING_STATE enum**
| Value | Enum Name | Description |
|-------|-----------|-------------|
| 0x14 | STANDBY | Unit on standby |
| 0x15 | DEMAND | Water demand detected |
| 0x20 | STARTUP | Unit starting up |
| 0x28 | PRE_PURGE_1 | Pre-purge phase 1 |
| 0x29 | PRE_PURGE_2 | Pre-purge phase 2 |
| 0x2A | PRE_IGNITION | Pre-ignition phase |
| 0x2B | IGNITION | Ignition in progress |
| 0x2C | FLAME_ON | Flame established |
| 0x2D | RAMP_UP | Ramping up heat output |
| 0x33 | ACTIVE_COMBUSTION | Active combustion |
| 0x34 | WATER_ADJUSTMENT_VALVE_OPERATION | Water valve adjusting |
| 0x3C | FLAME_OFF | Flame turned off |
| 0x46 | POST_PURGE_1 | Post-purge phase 1 |
| 0x47 | POST_PURGE_2 | Post-purge phase 2 |
| 0x49 | DHW_WAIT | DHW Wait / Set Point Match |

**Byte 24 (system_status) - System Configuration Flags**

⚠️ **WARNING: Interpretation varies by unit type!** See cross-unit testing results below.

**NPE-240A2 (system_type 0x05):**
| Bit | Mask | Description |
|-----|------|-------------|
| 0 | 0x01 | Internal scheduled recirculation enabled |
| 1 | 0x02 | External scheduled recirculation enabled |
| 2 | 0x04 | External pump on |
| 3 | 0x08 | Units: 1=metric (°C, L/min, m), 0=imperial (°F, GPM, ft) |

**NCB-240-130H (system_type 0x06):**
| Bit | Mask | Description |
|-----|------|-------------|
| 1 | 0x02 | Units: 1=Celsius, 0=Fahrenheit (**opposite meaning from NPE!**) |

Recirculation setting changes had no material effect on this unit's system_status byte.

**240A:**
| Bit | Mask | Description |
|-----|------|-------------|
| 3 | 0x08 | Units: 1=Celsius, 0=Fahrenheit (same as NPE-240A2) |

**Cross-Unit Test Results (from PR #23):**

| Unit | Change | system_status |
|------|--------|---------------|
| NPE-240A2 | No Recirc | 0x00 |
| NPE-240A2 | Ext Recirc (scheduled modes) | 0x02 |
| NPE-240A2 | Ext Recirc + pump | 0x06 |
| NPE-240A2 | Int Recirc | 0x01 |
| NPE-240A2 | Ext Recirc HotButton | 0x00 |
| NPE-240A2 | Celsius | 0x0A |
| NPE-240A2 | Fahrenheit | 0x02 |
| NCB-240-130H | Fahrenheit | 0x00 |
| NCB-240-130H | Celsius | 0x02 |
| 240A | Fahrenheit | 0x00 |
| 240A | Celsius | 0x08 |

**Byte 27 (boiler_active) - Boolean**
- 0x00: Boiler/burner not active
- 0x01: Boiler/burner active (water flowing, heat being produced)

**Byte 33 (recirculation_enabled)**

| Bit | Mask | Meaning |
|-----|------|---------|
| 0 | 0x01 (RECIRC_STATUS_FLAG_HOTBUTTON_ON) | Hot button recirc active |
| 1 | 0x02 (RECIRC_STATUS_FLAG_SCHEDULED_ON) | Scheduled recirc active (meaning the unit can recirculate when it wants, not that it's necessarily actively doing it; that's indicated by HEATING_MODE_DOMESTIC_HOT_WATER_RECIRCULATING in heating_mode (byte 8)). This bit can be set and cleared when Hot button mode is being used but nothing happens as a result. |

In Scheduled mode:
- 0x00: Schedule has disabled recirculation (outside active window)
- 0x02: Schedule allows recirculation (inside active window)

In HotButton mode:
- 0x00: No recirculation active
- 0x01: Hot button was pressed, recirculation running

**Unknown fields still to investigate:**
- Bytes 6-7: unknown_06, unknown_07
- Bytes 14-16: unknown_14, unknown_15, unknown_16
- Bytes 19-23: unknown_19-23 (0x00 on NPE, various values on NCB-H)
- Bytes 25-26: unknown_25, unknown_26
- Bytes 28-31: unknown_28-31 (counters, pinned to 255 on NCB-H models)
- Byte 32: unknown_32
- Bytes 34-39: unknown_34-39

---

### GAS_STATUS Packet (49 bytes)

**Structure from navien_proto.h (GAS_DATA):**
```
Bytes 0-5:   Header
Byte 6:      unknown_00 (0x45 on NCB-H)
Byte 7:      unknown_01 (0x00)
Byte 8:      device_type (DEVICE_TYPE enum)
Byte 9:      unknown_03 (0x01 on NCB-H)
Bytes 10-11: controller_version (lo/hi)
Bytes 12-13: panel_version (lo/hi)
Byte 14:     set_temp (target temperature in °C)
Byte 15:     outlet_temp
Byte 16:     inlet_temp
Byte 17:     sh_outlet_temp (space heating outlet - combi models)
Byte 18:     sh_return_temp (space heating return - combi models)
Byte 19:     unknown_18 (0x9E on NCB-H)
Byte 20:     heat_capacity (varies during operation)
Byte 21:     unknown_20 (0x21 on NCB-H, 0x05 elsewhere)
Bytes 22-23: current_gas (lo/hi)
Bytes 24-25: cumulative_gas (lo/hi)
Bytes 26-27: unknown_26, unknown_27 (0x00)
Bytes 28-29: days_since_install (lo/hi)
Bytes 30-31: cumulative_domestic_usage_cnt (lo/hi, in 10-usage increments)
Bytes 32-35: unknown_32-35
Bytes 36-37: total_operating_time (lo/hi)
Bytes 38-39: cumulative_dwh_usage_hours (lo/hi)
Bytes 40-41: cumulative_sh_usage_hours (lo/hi)
Bytes 42-47: unknown_42-47
Byte 48:     checksum
```

**Decoded fields:**

**Byte 8 (device_type) - DEVICE_TYPE enum**
| Value | Enum Name | Description |
|-------|-----------|-------------|
| 0 | NO_DEVICE | No device |
| 1 | NPE | NPE tankless |
| 2 | NCB | NCB combi boiler |
| 3 | NHB | NHB boiler |
| 4 | CAS_NPE | CAS NPE |
| 5 | CAS_NHB | CAS NHB |
| 6 | NFB | NFB boiler |
| 7 | CAS_NFB | CAS NFB |
| 8 | NFC | NFC |
| 9 | NPN | NPN |
| 10 | CAS_NPN | CAS NPN |
| 11 | NPE2 | NPE2 |
| 12 | CAS_NPE2 | CAS NPE2 |
| 13 | NCB_H | NCB-H |
| 14 | NVW | NVW |
| 15 | CAS_NVW | CAS NVW |

**Bytes 10-13 (versions)**
- controller_version: Firmware version (lo * 256 + hi format)
- panel_version: Panel firmware version

**Bytes 17-18 (space heating temps - combi models only)**
- sh_outlet_temp: Space heating supply temperature
- sh_return_temp: Space heating return temperature

**Byte 20 (heat_capacity)**
- Varies based on boiler cycling while operating
- Indicates current heat output level

**Byte 21 (unknown_20) - Units & HotButton Flags** ✅ NEW from PR #23
| Bit | Mask | Description |
|-----|------|-------------|
| 0 | 0x01 | Units: 0=imperial (°F), 1=metric (°C) - **CONSISTENT across all units!** |
| 2 | 0x04 | HotButton mode enabled (observed on NPE-240A2) |

**RECOMMENDATION:** Use this byte's bit 0 for units detection since it's consistent across all tested unit types, unlike the water packet's system_status byte which varies by model.

Cross-unit test results:
| Unit | Fahrenheit | Celsius |
|------|------------|---------|
| NPE-240A2 | 0x01 | 0x00 |
| NCB-240-130H | 0x21 | 0x20 |
| 240A | 0x01 | 0x00 |

Note: Bit 0 consistently indicates: 0=metric, 1=imperial (inverted from what you might expect)

**Bytes 28-29 (days_since_install)**
- Total days since unit installation

**Bytes 30-31 (cumulative_domestic_usage_cnt)**
- Domestic hot water usage counter (in 10-usage increments)

**Bytes 36-37 (total_operating_time)**
- Total operating time counter

**Bytes 38-39 (cumulative_dwh_usage_hours)**
- Cumulative domestic hot water usage in hours

**Bytes 40-41 (cumulative_sh_usage_hours)**
- Cumulative space heating usage in hours (combi models)

**Byte 47 (unknown_46) - Recirculation Mirror** ✅ NEW from PR #23
| Bit | Mask | Description |
|-----|------|-------------|
| 0 | 0x01 | Mirrors water system_power bit 5 (scheduled recirculation on/off) |

Observed on NPE-240A2: When scheduled recirculation modes are active, this bit is set (0x01). In HotButton mode or No Recirc, it's clear (0x00).

**Note:** This behavior was not observed on NCB-240-130H during testing - recirculation setting changes had no material effect on this byte.

**Unknown fields still to investigate:**
- Bytes 6-7, 9: unknown_00, unknown_01, unknown_03
- Byte 19: unknown_18
- Bytes 26-27: unknown_26, unknown_27
- Bytes 32-35: unknown_32-35
- Bytes 42-46: unknown_42-46

---

### Heating Cycle Signature (for reference)

**Start of heating cycle:**
1. WATER_STATUS heating_mode (byte 8): 0x00 → 0x20 (HEATING_MODE_DOMESTIC_HOT_WATER_DEMAND)
2. WATER_STATUS operating_state (byte 10): 0x14 (STANDBY) → 0x15 (DEMAND) → 0x20 (STARTUP) → ...
3. WATER_STATUS boiler_active (byte 27): 0x00 → 0x01 (boiler firing)
4. GAS_STATUS heat_capacity (byte 20): increases as burner modulates

**During steady heating:**
- WATER_STATUS operating_state: cycles through ACTIVE_COMBUSTION (0x33), WATER_ADJUSTMENT_VALVE_OPERATION (0x34)
- GAS_STATUS heat_capacity: modulates based on demand intensity

**Shutdown sequence:**
1. WATER_STATUS heating_mode (byte 8): 0x20 → 0x00 (HEATING_MODE_IDLE)
2. WATER_STATUS boiler_active (byte 27): 0x01 → 0x00
3. WATER_STATUS operating_state: FLAME_OFF (0x3C) → POST_PURGE phases → STANDBY (0x14)

**Recirculation cycle (Scheduled mode):**
1. WATER_STATUS heating_mode (byte 8): 0x00 → 0x08 (HEATING_MODE_DOMESTIC_HOT_WATER_RECIRCULATING)
2. WATER_STATUS recirculation_enabled (byte 33) bit 1: 0x02 (schedule allows recirc)

**Recirculation cycle (HotButton mode):**
1. WATER_STATUS heating_mode (byte 8): 0x00 → 0x20 (HEATING_MODE_DOMESTIC_HOT_WATER_DEMAND)
2. WATER_STATUS recirculation_enabled (byte 33) bit 0: 0x01 (hot button recirc active)

### Control Commands

All control commands follow pattern: `F7 05 0F 50 10 [len] [data...] [checksum]`

**Previously known commands (suppressed by monitor):**
- TURN_ON, TURN_OFF
- HOT_BUTTON_PRESS, HOT_BUTTON_RELEASE
- RECIRC_ON
- SET_TEMP
- NAVILINK_PRESENT

**Newly decoded commands:**

#### Weekly Schedule Control (Command Type 0x4F)

**Structure:**
```
F7 05 0F 50 10 0C 4F 00 00 00 00 [state] 00 00 00 00 00 00 [checksum]
```

**Schedule ON:**
```
F7 05 0F 50 10 0C 4F 00 00 00 00 10 00 00 00 00 00 00 C0
```
- Byte 11 (data position 6): **0x10** (bit 4 set)
- Sent 2-3 times for reliability

**Schedule OFF:**
```
F7 05 0F 50 10 0C 4F 00 00 00 00 08 00 00 00 00 00 00 EE
```
- Byte 11 (data position 6): **0x08** (bit 3 set)
- Sent 2-3 times for reliability

**Schedule enters active recirculation window** (in Scheduled mode)
```
F7 05 0F 50 10 0C 4F 00 00 00 00 08 00 00 00 00 00 00 EE
```
- Byte 11: **0x08** (bit 3 set)
- `recirculation_enabled` (byte 33) changes to 0x02 (bit 1 set = allowed)
- `water_status` (byte 8) bit 3 (0x08) activates during scheduled recirc cycles

**Schedule exits active recirculation window** (in Scheduled mode)
```
F7 05 0F 50 10 0C 4F 00 00 00 00 10 00 00 00 00 00 00 C0
```
- Byte 11: **0x10** (bit 4 set)
- `recirculation_enabled` (byte 33) changes to 0x00 (bit 1 clear = disabled)

**Behavior:**
- These commands are sent automatically by the Navien app when schedule windows start/end
- Turning schedule ON/OFF also sends these same commands
- Schedule start triggers brief recirculation test cycle
- During scheduled recirc: `water_status` bit 3 (0x08) sets, transient fields activate

**NOTE:** The recirculation mode (Scheduled vs Hot Button) is indicated by **byte 25 (system_status) bit 1**: 1=Scheduled mode, 0=Hot Button mode.

**Command breakdown:**
- Header: `F7 05 0F 50 10` (standard control command)
- Length: `0C` (12 bytes of data)
- Command type: `4F` (schedule control)
- Padding: `00 00 00 00`
- State byte: `10` (ON) or `08` (OFF)
- More padding: `00 00 00 00 00 00`
- Checksum: Calculated based on command content

## Tips for Effective Analysis

1. **Do one thing at a time** - Change only one variable per test
2. **Wait for steady state** - Let packets stabilize before next action
3. **Document everything** - Claude will help track what you tested
4. **Look for patterns** - Repeated tests help confirm hypotheses
5. **Check both packet types** - Some fields appear in multiple packets
6. **Note edge cases** - First turn-on, shutdown, errors are interesting

## ESPHome Configuration

**Device:** M5Stack Atom S3 Lite (ESP32-S3)
**Config file:** `navien-esphome-atom-s3-lite-esp32.yml`

**Packet Logging Control:**
- Switch in Home Assistant: "Packet logging"
- Turn ON: Sets navien.link log level to INFO (packets visible)
- Turn OFF: Sets navien.link log level to WARN (packets hidden)

**To see logs:**
```bash
esphome logs navien-esphome-atom-s3-lite-esp32.yml --device 172.16.10.190
```

## Troubleshooting

**No packets appearing:**
- Check that "Packet logging" switch is ON in Home Assistant
- Verify ESPHome device is connected and communicating
- Check UART connection to Navien unit

**Too much noise:**
- The packet_monitor.py script already filters to unknown fields only
- If still too noisy, we can modify the script to suppress specific fields

**Background task issues:**
- Claude can check task status with `/tasks` command
- Can restart the monitor if needed
- Can view accumulated output at any time

## TODO - Outstanding Investigation Items

### High Priority
1. ✅ **~~Identify recirculation mode indicator~~** - **SOLVED**: Byte 24 (system_status) bit 1 (0x02) on NPE units:
   - **Bit 1 = 1**: Scheduled mode
   - **Bit 1 = 0**: Hot Button mode
   - ⚠️ Note: This interpretation is unit-specific (see PR #23 findings)

2. ✅ **~~Fix POWER_ON_OFF_MASK~~** - **SOLVED in PR #23**: Should be 0x01, not 0x05

3. ✅ **~~Decode GAS unknown_20 (byte 21)~~** - **SOLVED in PR #23**:
   - Bit 0: Units flag (0=imperial, 1=metric) - consistent across all unit types
   - Bit 2: HotButton enabled (on NPE-240A2)

4. **Differentiate byte 8 bit 5 vs byte 27 bit 0**: Both appear to track hot water tap/appliance demand and are aligned in observed testing (both set when tap open, both clear during recirc). There must be a subtle difference in meaning we haven't discerned yet. Possibilities:
   - One is demand request, other is flow confirmation?
   - One is electrical/control signal, other is physical sensor?
   - Different behavior in edge cases?

5. **Test byte 8 bit 5 and byte 27 bit 0 in Hot Button mode**: Verify behavior when hot button recirculation is active vs scheduled recirculation.

### Medium Priority
6. **Document unit-specific protocol differences**: PR #23 revealed significant differences between NPE and NCB units. Need systematic testing across more unit types.

7. **Implement units detection using GAS byte 21**: Per PR #23 recommendation, switch from system_status to GAS unknown_20 bit 0 for reliable cross-unit units detection.

### Low Priority
8. **Map remaining unknown fields**: Many fields (unknown_14, 15, 20-24, 25, 26, 32, 34-39) have shown no changes during testing. May require specific conditions or features to activate.

## Files Reference

- `packet_monitor.py` - The monitoring script
- `components/navien/navien_proto.h` - C++ packet structure definitions
- `navien-base.yml` - Base ESPHome config with packet logging switch
- `navien-esphome-atom-s3-lite-esp32.yml` - Device-specific config
- `CLAUDE.md` - ESPHome API reference for code development
- This file - Guide for packet analysis sessions

## External References

- **PR #23**: https://github.com/htumanyan/navien/pull/23
  - Cross-unit testing by @jhoos (NPE-240A2), @mikeygnyc (NCB-240-130H), @htumanyan (240A)
  - Discovered unit-specific protocol differences
  - Corrected POWER_ON_OFF_MASK (0x01, not 0x05)
  - Identified GAS byte 21 bit 0 as consistent units flag
  - Packet logs: [jhoos gist](https://gist.github.com/jhoos/6109bd235ddbec77d0a55cb7e19bddc7), [mikeygnyc gist](https://gist.github.com/mikeygnyc/c8f8874a690cc058b10f5c7b6b3a2d74)
