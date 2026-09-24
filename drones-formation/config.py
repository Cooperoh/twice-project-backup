# UAV_CFGS: List[Dict[str, Any]]
# 后续改为json或yaml配置文件加载，目前先写死在代码里

from constants import (
    DEFAULT_FORMATION_SPACING,
    DEFAULT_FORMATION_TYPE,
    DEFAULT_GROUP,
    DEFAULT_IS_LEADER,
    DEFAULT_READ_SIZE,
    DEFAULT_SERIAL_TIMEOUT,
    DEFAULT_UDP_TIMEOUT,
)

IP = "10.144.1.100"
myip = IP

FC_BIND_HOST = "127.0.0.1"
FC_TARGET_IP = "127.0.0.1"

UAV_BASE_CFGS = [
    {"id": 1,  "tag": "DRONE1",  "ip": myip, "cmd_port": 57001, "gui_host": IP},
    {"id": 2,  "tag": "DRONE2",  "ip": myip, "cmd_port": 57002, "gui_host": IP},
    {"id": 3,  "tag": "DRONE3",  "ip": myip, "cmd_port": 57003, "gui_host": IP},
    {"id": 4,  "tag": "DRONE4",  "ip": myip, "cmd_port": 57004, "gui_host": IP},
    {"id": 5,  "tag": "DRONE5",  "ip": myip, "cmd_port": 57005, "gui_host": IP},
    {"id": 6,  "tag": "DRONE6",  "ip": myip, "cmd_port": 57006, "gui_host": IP},
    {"id": 7,  "tag": "DRONE7",  "ip": myip, "cmd_port": 57007, "gui_host": IP},
    {"id": 8,  "tag": "DRONE8",  "ip": myip, "cmd_port": 57008, "gui_host": IP},
    {"id": 9,  "tag": "DRONE9",  "ip": myip, "cmd_port": 57009, "gui_host": IP},
    {"id": 10, "tag": "DRONE10", "ip": myip, "cmd_port": 57010, "gui_host": IP},
    {"id": 11, "tag": "DRONE11", "ip": myip, "cmd_port": 57011, "gui_host": IP},
    {"id": 12, "tag": "DRONE12", "ip": myip, "cmd_port": 57012, "gui_host": IP},
    {"id": 13, "tag": "DRONE13", "ip": myip, "cmd_port": 57013, "gui_host": IP},
    {"id": 14, "tag": "DRONE14", "ip": myip, "cmd_port": 57014, "gui_host": IP},
    {"id": 15, "tag": "DRONE15", "ip": myip, "cmd_port": 57015, "gui_host": IP},
    {"id": 16, "tag": "DRONE16", "ip": myip, "cmd_port": 57016, "gui_host": IP},
    {"id": 17, "tag": "DRONE17", "ip": myip, "cmd_port": 57017, "gui_host": IP},
    {"id": 18, "tag": "DRONE18", "ip": myip, "cmd_port": 57018, "gui_host": IP},
    {"id": 19, "tag": "DRONE19", "ip": myip, "cmd_port": 57019, "gui_host": IP},
    {"id": 20, "tag": "DRONE20", "ip": myip, "cmd_port": 57020, "gui_host": IP},
    {"id": 21, "tag": "DRONE21", "ip": myip, "cmd_port": 57021, "gui_host": IP},
    {"id": 22, "tag": "DRONE22", "ip": myip, "cmd_port": 57022, "gui_host": IP},
    {"id": 23, "tag": "DRONE23", "ip": myip, "cmd_port": 57023, "gui_host": IP},
    {"id": 24, "tag": "DRONE24", "ip": myip, "cmd_port": 57024, "gui_host": IP},
]

UAV_SERIAL_CFGS = [
    {"id": 1,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 2,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 3,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 4,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 5,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 6,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 7,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 8,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 9,  "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 10, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 11, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 12, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 13, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 14, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 15, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 16, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 17, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 18, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 19, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 20, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 21, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 22, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 23, "serial_port": "COM1", "serial_baudrate": 115200},
    {"id": 24, "serial_port": "COM1", "serial_baudrate": 115200},
]

UAV_UDP_CFGS = [
    {"id": 1,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6012, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6013},
    {"id": 2,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6022, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6023},
    {"id": 3,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6032, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6033},
    {"id": 4,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6042, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6043},
    {"id": 5,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6052, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6053},
    {"id": 6,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6062, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6063},
    {"id": 7,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6072, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6073},
    {"id": 8,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6082, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6083},
    {"id": 9,  "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6092, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6093},
    {"id": 10, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6102, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6103},
    {"id": 11, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6112, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6113},
    {"id": 12, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6122, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6123},
    {"id": 13, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6132, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6133},
    {"id": 14, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6142, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6143},
    {"id": 15, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6152, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6153},
    {"id": 16, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6162, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6163},
    {"id": 17, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6172, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6173},
    {"id": 18, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6182, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6183},
    {"id": 19, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6192, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6193},
    {"id": 20, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6202, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6203},
    {"id": 21, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6212, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6213},
    {"id": 22, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6222, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6223},
    {"id": 23, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6232, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6233},
    {"id": 24, "udp_bind_host": FC_BIND_HOST, "udp_bind_port": 6242, "udp_target_host": FC_TARGET_IP, "udp_target_port": 6243},
]


def _merge_uav_configs(base_configs, serial_configs, udp_configs):
    if not (len(base_configs) == len(serial_configs) == len(udp_configs)):
        raise ValueError("UAV config sections must have the same length")

    merged = []
    for base, serial, udp in zip(base_configs, serial_configs, udp_configs):
        if base["id"] != serial["id"] or base["id"] != udp["id"]:
            raise ValueError(f"UAV config id mismatch: {base['id']}, {serial['id']}, {udp['id']}")

        defaults = {
            "fc_id": base["id"],
            "group": DEFAULT_GROUP,
            "is_leader": DEFAULT_IS_LEADER,
            "formation_types": DEFAULT_FORMATION_TYPE,
            "formation_spacing": DEFAULT_FORMATION_SPACING,
            "serial_timeout": DEFAULT_SERIAL_TIMEOUT,
            "udp_timeout": DEFAULT_UDP_TIMEOUT,
            "read_size": DEFAULT_READ_SIZE,
        }
        merged.append({**defaults, **base, **serial, **udp})
    return merged


UAV_CFGS = _merge_uav_configs(UAV_BASE_CFGS, UAV_SERIAL_CFGS, UAV_UDP_CFGS)


def drone_broadcast(exclude_id):
    """Return an ID-to-address directory; each message selects its own members."""
    return {cfg["id"]: (cfg["ip"], cfg["cmd_port"]) for cfg in UAV_CFGS if cfg["id"] != exclude_id}
