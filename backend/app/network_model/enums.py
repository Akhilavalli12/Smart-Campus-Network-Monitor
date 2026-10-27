"""Vocabulary of the campus network model."""
from enum import StrEnum


class DeviceType(StrEnum):
    INTERNET = "internet"
    EDGE_ROUTER = "edge_router"
    CORE_SWITCH = "core_switch"
    SWITCH = "switch"
    ACCESS_POINT = "access_point"
    SERVER = "server"
    PC = "pc"


class CampusBlock(StrEnum):
    BACKBONE = "backbone"
    CSE = "cse"
    LIBRARY = "library"
    ADMIN = "admin"


class MonitoringMode(StrEnum):
    REAL = "real"
    SIMULATED = "simulated"


class DeviceStatus(StrEnum):
    UNKNOWN = "unknown"  # registered, not measured yet
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNREACHABLE = "unreachable"  # cannot be reached because an upstream device failed


class LinkKind(StrEnum):
    WAN = "wan"
    BACKBONE = "backbone"
    UPLINK = "uplink"
    ACCESS = "access"


class FaultType(StrEnum):
    NONE = "none"
    OFFLINE = "offline"
    HIGH_LATENCY = "high_latency"
    PACKET_LOSS = "packet_loss"
    CONGESTION = "congestion"
