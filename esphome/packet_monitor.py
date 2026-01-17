#!/usr/bin/env python3
"""
Navien Packet Monitor
Reads ESPHome packet dumps from stdin, parses known packet structures,
and only reports changes in unknown/undefined bytes.
"""

import sys
import re
import argparse
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

@dataclass
class PacketField:
    name: str
    offset: int
    known: bool = True  # False for unknown fields

# Packet structure definitions based on navien_proto.h
# Header fields:
#   src: 0x50=from Navien (PACKET_SRC_STATUS), 0x0F=from control device (PACKET_SRC_CONTROL)
#   dst: 0x50=water data (PACKET_DST_WATER), 0x0F=gas data (PACKET_DST_GAS)
#   direction: 0x90=status packet (PACKET_DIR_STATUS), 0x10=control packet (PACKET_DIR_CONTROL)
HEADER_FIELDS = [
    PacketField("packet_marker", 0, True),
    PacketField("sys_type", 1, True),       # System type identifier (0x05)
    PacketField("src", 2, True),            # Packet source address
    PacketField("dst", 3, True),            # Packet destination/type
    PacketField("direction", 4, True),      # 0x90=status, 0x10=control
    PacketField("len", 5, True),
]

# WATER_DATA packet (src=0x50, dst=0x50, total 41 bytes)
# Field names and offsets from navien_proto.h WATER_DATA struct
WATER_FIELDS = [
    PacketField("unknown_06", 6, False),
    PacketField("unknown_07", 7, False),
    PacketField("heating_mode", 8, True),      # DEVICE_HEATING_MODE enum (0x00=Idle, 0x08=Recirc, 0x10=SpaceHeat, 0x20=DHW)
    PacketField("system_power", 9, True),      # Bitmask: 0x05=on/off, 0x20=hot button absent
    PacketField("operating_state", 10, True),  # OPERATING_STATE enum (0x14=Standby, 0x15=Demand, etc.)
    PacketField("set_temp", 11, True),
    PacketField("outlet_temp", 12, True),
    PacketField("inlet_temp", 13, True),
    PacketField("unknown_14", 14, False),
    PacketField("unknown_15", 15, False),
    PacketField("unknown_16", 16, False),
    PacketField("operating_capacity", 17, True),
    PacketField("water_flow", 18, True),
    PacketField("unknown_19", 19, False),
    PacketField("unknown_20", 20, False),
    PacketField("unknown_21", 21, False),
    PacketField("unknown_22", 22, False),
    PacketField("unknown_23", 23, False),
    PacketField("system_status", 24, True),    # Bitmask: 0x02=recirc mode (1=sched, 0=hotbutton), 0x08=units (1=C, 0=F)
    PacketField("unknown_25", 25, False),
    PacketField("unknown_26", 26, False),
    PacketField("boiler_active", 27, True),    # Boolean: 0x00=inactive, 0x01=active
    PacketField("unknown_28", 28, False),      # Counter, pinned to 255 on NCB-H
    PacketField("unknown_29", 29, False),      # Counter, pinned to 255 on NCB-H
    PacketField("unknown_30", 30, False),      # Counter, pinned to 255 on NCB-H
    PacketField("unknown_31", 31, False),      # Counter, pinned to 255 on NCB-H
    PacketField("unknown_32", 32, False),
    PacketField("recirculation_enabled", 33, True),  # Bitmask: 0x01=hotbutton active, 0x02=scheduled allowed
    PacketField("unknown_34", 34, False),
    PacketField("unknown_35", 35, False),
    PacketField("unknown_36", 36, False),
    PacketField("unknown_37", 37, False),
    PacketField("unknown_38", 38, False),
    PacketField("unknown_39", 39, False),
    PacketField("checksum", 40, True),
]

# GAS_DATA packet (src=0x50, dst=0x0F, total 49 bytes)
# Field names and offsets from navien_proto.h GAS_DATA struct
GAS_FIELDS = [
    PacketField("unknown_00", 6, False),           # 0x45 on NCB-H
    PacketField("unknown_01", 7, False),           # 0x00
    PacketField("device_type", 8, True),           # DEVICE_TYPE enum
    PacketField("unknown_03", 9, False),           # 0x01 on NCB-H
    PacketField("controller_version_lo", 10, True),
    PacketField("controller_version_hi", 11, True),
    PacketField("panel_version_lo", 12, True),
    PacketField("panel_version_hi", 13, True),
    PacketField("set_temp", 14, True),
    PacketField("outlet_temp", 15, True),
    PacketField("inlet_temp", 16, True),
    PacketField("sh_outlet_temp", 17, True),       # Space heating outlet temp (combi models)
    PacketField("sh_return_temp", 18, True),       # Space heating return temp (combi models)
    PacketField("unknown_18", 19, False),          # 0x9E on NCB-H
    PacketField("heat_capacity", 20, True),        # Current heat output level
    PacketField("unknown_20", 21, False),          # 0x21 on NCB-H, 0x05 elsewhere
    PacketField("current_gas_lo", 22, True),
    PacketField("current_gas_hi", 23, True),
    PacketField("cumulative_gas_lo", 24, True),
    PacketField("cumulative_gas_hi", 25, True),
    PacketField("unknown_26", 26, False),          # 0x00
    PacketField("unknown_27", 27, False),          # 0x00
    PacketField("days_since_install_lo", 28, True),
    PacketField("days_since_install_hi", 29, True),
    PacketField("cumulative_domestic_usage_cnt_lo", 30, True),
    PacketField("cumulative_domestic_usage_cnt_hi", 31, True),
    PacketField("unknown_32", 32, False),
    PacketField("unknown_33", 33, False),
    PacketField("unknown_34", 34, False),
    PacketField("unknown_35", 35, False),          # 0x00
    PacketField("total_operating_time_lo", 36, True),
    PacketField("total_operating_time_hi", 37, True),
    PacketField("cumulative_dwh_usage_hours_lo", 38, True),
    PacketField("cumulative_dwh_usage_hours_hi", 39, True),
    PacketField("cumulative_sh_usage_hours_lo", 40, True),
    PacketField("cumulative_sh_usage_hours_hi", 41, True),
    PacketField("unknown_42", 42, False),
    PacketField("unknown_43", 43, False),
    PacketField("unknown_44", 44, False),
    PacketField("unknown_45", 45, False),
    PacketField("unknown_46", 46, False),
    PacketField("unknown_47", 47, False),
    PacketField("checksum", 48, True),
]

# Control packet (src=0x0F, dst=0x50, 10 bytes for NAVILINK_PRESENT)
CONTROL_SMALL_FIELDS = [
    PacketField("unknown_06", 6, False),
    PacketField("unknown_07", 7, False),
    PacketField("unknown_08", 8, False),
    PacketField("checksum", 9, True),
]

# Known control commands from navien_proto.h
# Format: (name, byte_array)
KNOWN_COMMANDS = [
    ("TURN_OFF_CMD", bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x0c, 0x4f, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0A])),
    ("TURN_ON_CMD", bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x0c, 0x4f, 0x00, 0x0a, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xCE])),
    ("HOT_BUTTON_PRESS_CMD", bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x0c, 0x4f, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x6A])),
    ("ACKNOWLEDGEMENT", bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x0c, 0x4f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x2A])),
    ("RECIRC_ON_CMD", bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x0c, 0x4f, 0x00,   0x00,   0x00, 0x00, 0x08, 0xD9, 0x00, 0x00, 0x00, 0x00, 0x00, 0xD0])),
    ("SCHEDULED_RECIRC_ON_CMD", bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x0c, 0x4f, 0x00,   0x00,   0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xEE])),
    ("SCHEDULED_RECIRC_OFF_CMD", bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x0c, 0x4f, 0x00,   0x00,   0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC0])),
    ("NAVILINK_PRESENT", bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x03, 0x4a, 0x00, 0x01, 0x55])),
]

# SET_TEMP_CMD has varying temp (byte 9) and checksum (byte 18), so we check fixed bytes
SET_TEMP_CMD_PREFIX = bytes([0xF7, 0x05, 0x0F, 0x50, 0x10, 0x0c, 0x4f, 0x00, 0x00])
SET_TEMP_CMD_MIDDLE = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

class PacketMonitor:
    def __init__(self, verbose: bool = False, show_gas: bool = True, show_water: bool = True):
        self.packet_history: Dict[Tuple[int, int, int], bytes] = {}
        self.verbose = verbose
        self.show_gas = show_gas
        self.show_water = show_water

    def parse_line(self, line: str) -> Optional[tuple]:
        """Parse a line for packet dump header or hex data."""
        len_match = re.search(r'navien.link.packet.*Packet dump, len=(\d+)\t(.*)', line)
        if not len_match:
            return None
        length = int(len_match.group(1))
        data_part = len_match.group(2)
        hex_bytes = re.findall(r'\b([0-9a-f]{2})\b', data_part)
        if hex_bytes:
            bytes_list = [int(b, 16) for b in hex_bytes]
            return bytes_list

        return None

    def get_packet_fields(self, packet: bytes) -> Tuple[List[PacketField], bool]:
        """
        Determine which field definitions apply to this packet.
        Returns (fields, is_known_type).
        """
        if len(packet) < 6:
            return [], False

        src = packet[2]
        dst = packet[3]
        plen = len(packet)

        fields = HEADER_FIELDS.copy()
        is_known = True

        # Water status packet (from Navien, water data)
        if src == 0x50 and dst == 0x50:
            fields.extend(WATER_FIELDS)
        # Gas status packet (from Navien, gas data)
        elif src == 0x50 and dst == 0x0F:
            fields.extend(GAS_FIELDS)
        # Small control packet (NAVILINK_PRESENT)
        elif src == 0x0F and dst == 0x50 and plen == 10:
            fields.extend(CONTROL_SMALL_FIELDS)
        else:
            # Unknown packet type - mark all as unknown
            is_known = False
            fields.extend([PacketField(f"unknown_{i}", i, False)
                          for i in range(6, plen)])

        return fields, is_known

    def is_known_control_command(self, packet: bytes) -> Optional[str]:
        """
        Check if a control packet matches a known command.
        Returns the command name if known, None otherwise.
        """
        # Check exact matches
        for name, cmd_bytes in KNOWN_COMMANDS:
            if packet == cmd_bytes:
                return name

        # Check SET_TEMP_CMD pattern (19 bytes with varying temp and checksum)
        if len(packet) == 19:
            if (packet[:9] == SET_TEMP_CMD_PREFIX and
                packet[10:18] == SET_TEMP_CMD_MIDDLE):
                temp = packet[9]
                return f"SET_TEMP_CMD(temp={temp}°C/{int(temp*9/10.+32.5)}°F)"

        return None

    def get_packet_name(self, packet: bytes) -> str:
        """Get a human-readable name for the packet type."""
        if len(packet) < 6:
            return "INVALID"

        src = packet[2]
        dst = packet[3]
        plen = len(packet)

        if src == 0x50 and dst == 0x50:
            if plen >= 12:
                set_temp = packet[11]
                return f"WATER_STATUS(set_temp={set_temp}°C/{int(set_temp*9/10.+32.5)}°F)"
            return "WATER_STATUS"
        elif src == 0x50 and dst == 0x0F:
            return "GAS_STATUS"
        elif src == 0x0F and dst == 0x50:
            # Check if it's a known command
            cmd_name = self.is_known_control_command(packet)
            if cmd_name:
                return cmd_name
            else:
                return "UNKNOWN_CONTROL_CMD"
        else:
            return f"UNKNOWN(src=0x{src:02X},dst=0x{dst:02X})"

    def process_packet(self, packet_bytes: bytes) -> None:
        """Process a complete packet and report changes in unknown fields."""
        if len(packet_bytes) < 4:
            print(f"⚠️  Packet too short: {len(packet_bytes)} bytes")
            return

        src = packet_bytes[2]
        dst = packet_bytes[3]
        plen = len(packet_bytes)
        packet_name = self.get_packet_name(packet_bytes)

        # Filter out packet types based on flags
        is_water = src == 0x50 and dst == 0x50
        is_gas = src == 0x50 and dst == 0x0F
        if is_water and not self.show_water:
            return
        if is_gas and not self.show_gas:
            return

        # Verbose mode: log every packet
        if self.verbose:
            print(f"📦 {packet_name}: {' '.join(f'{b:02X}' for b in packet_bytes)}")

        # Special handling for control commands (src=0x0F means from control device)
        if src == 0x0F:
            cmd_name = self.is_known_control_command(packet_bytes)
            if cmd_name is None:
                # Unknown control command - always dump it
                print(f"\n⚠️  UNKNOWN CONTROL COMMAND: {packet_name}")
                print(f"   Full: {' '.join(f'{b:02X}' for b in packet_bytes)}")
                print(f"   Length: {plen} bytes")
            else:
                # Report NAVILINK_PRESENT (alive packet) for monitoring
                if cmd_name == "NAVILINK_PRESENT":
                    packet_key = ("ALIVE", 0, 0)
                    if packet_key not in self.packet_history:
                        print(f"\n💓 ALIVE PACKET: {cmd_name}")
                        print(f"   Full: {' '.join(f'{b:02X}' for b in packet_bytes)}")
                        self.packet_history[packet_key] = packet_bytes
                    elif self.packet_history[packet_key] != packet_bytes:
                        print(f"\n💓 ALIVE PACKET CHANGED: {cmd_name}")
                        print(f"   Old: {' '.join(f'{b:02X}' for b in self.packet_history[packet_key])}")
                        print(f"   New: {' '.join(f'{b:02X}' for b in packet_bytes)}")
                        self.packet_history[packet_key] = packet_bytes
                else:
                    print (f"\n✅ Known CONTROL COMMAND: {cmd_name}")
            return

        # Status packets - use src, dst, length as key
        packet_key = (src, dst, plen)

        # Check if this is a new packet type
        if packet_key not in self.packet_history:
            fields, is_known = self.get_packet_fields(packet_bytes)

            print(f"\n🆕 NEW PACKET: {packet_name} (src=0x{src:02X}, dst=0x{dst:02X}, len={plen})")

            # For unknown packet types, show full data
            print(f"   Full: {' '.join(f'{b:02X}' for b in packet_bytes)}")

            self.packet_history[packet_key] = packet_bytes
            return

        # Compare with previous packet
        prev_packet = self.packet_history[packet_key]
        if packet_bytes == prev_packet:
            return  # No changes

        # Report set_temp changes for water packets
        if src == 0x50 and dst == 0x50 and plen >= 12:
            old_temp = prev_packet[11]
            new_temp = packet_bytes[11]
            if old_temp != new_temp:
                print(f"\n🌡️  SET_TEMP CHANGED: {old_temp}°C/{int(old_temp*9/10.+32.5)}°F -> {new_temp}°C/{int(new_temp*9/10.+32.5)}°F")

        # Find changes in all fields (not just unknown)
        fields, is_known = self.get_packet_fields(packet_bytes)
        unknown_changes = []

        for field in fields:
            if field.offset >= len(packet_bytes):
                continue
            if not field.known:
                old_val = prev_packet[field.offset]
                new_val = packet_bytes[field.offset]
                if old_val != new_val:
                    unknown_changes.append((field, old_val, new_val))

        if unknown_changes:
            print(f"\n📝 UNKNOWN FIELD CHANGES in {packet_name}:")
            for field, old_val, new_val in unknown_changes:
                print(f"   [{field.name:20s}] 0x{old_val:02X} -> 0x{new_val:02X} "
                      f"(dec: {old_val:3d} -> {new_val:3d}, "
                      f"bin: {old_val:08b} -> {new_val:08b})")

                # Special reporting for known bitfield fields
                if field.name in ["system_power", "system_status", "recirculation_enabled"]:
                    changed_bits = old_val ^ new_val
                    if changed_bits:
                        print(f"      🔍 Bit-level changes:")
                        for bit in range(8):
                            if changed_bits & (1 << bit):
                                old_bit = (old_val >> bit) & 1
                                new_bit = (new_val >> bit) & 1
                                print(f"         Bit {bit} (0x{1<<bit:02X}): {old_bit} → {new_bit}")

        # Update history
        self.packet_history[packet_key] = packet_bytes

    def run(self):
        """Main loop - read from stdin and process packets."""
        current_packet: List[int] = []
        expected_length: Optional[int] = None

        print("🔍 Navien Packet Monitor (Unknown Fields Only)")
        print("=" * 70)

        for line in sys.stdin:
            parsed = self.parse_line(line)
            if not parsed:
                continue

            self.process_packet(bytes(parsed))

        if current_packet:
            self.process_packet(bytes(current_packet))

        print("\n" + "=" * 70)
        print(f"🏁 Tracked {len(self.packet_history)} unique packet types.")

def parse_args():
    parser = argparse.ArgumentParser(
        description='Monitor Navien packet dumps and report changes in unknown fields.'
    )
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Log all packets, not just changes')
    parser.add_argument('--gas', action='store_true', dest='show_gas', default=True,
                        help='Show gas packets (default)')
    parser.add_argument('--no-gas', action='store_false', dest='show_gas',
                        help='Hide gas packets')
    parser.add_argument('--water', action='store_true', dest='show_water', default=True,
                        help='Show water packets (default)')
    parser.add_argument('--no-water', action='store_false', dest='show_water',
                        help='Hide water packets')
    return parser.parse_args()


if __name__ == '__main__':
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    monitor = PacketMonitor(
        verbose=args.verbose,
        show_gas=args.show_gas,
        show_water=args.show_water
    )
    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(0)
