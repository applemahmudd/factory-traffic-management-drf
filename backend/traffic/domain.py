"""Pure traffic-domain rules. No HTTP, database, or MQTT dependencies."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

DIRECTIONS = ("NORTH", "SOUTH", "EAST", "WEST")
PHASES = {"NORTH_SOUTH": ("NORTH", "SOUTH"), "EAST_WEST": ("EAST", "WEST")}
VEHICLE_PRIORITY = {"EMPLOYEE_VEHICLE": 1, "FORKLIFT": 2, "TRUCK": 3, "EMERGENCY": 4}

class Signal(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"

class Mode(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    DEGRADED = "DEGRADED"

@dataclass
class Vehicle:
    vehicle_id: str
    vehicle_type: str
    arrived_at: float
    sequence_no: int

@dataclass
class Junction:
    junction_id: str
    mode: str = Mode.AUTOMATIC.value
    phase: str = "NORTH_SOUTH"
    transition: str = "STABLE"  # STABLE, YELLOW, ALL_RED
    transition_target: Optional[str] = None
    transition_started_at: Optional[float] = None
    green_started_at: float = 0.0
    queues: dict = field(default_factory=lambda: {d: [] for d in DIRECTIONS})
    desired_signals: dict = field(default_factory=lambda: {d: (Signal.GREEN.value if d in PHASES["NORTH_SOUTH"] else Signal.RED.value) for d in DIRECTIONS})
    actual_signals: dict = field(default_factory=lambda: {d: "UNKNOWN" for d in DIRECTIONS})
    controller_status: str = "UNKNOWN"
    pending_commands: dict = field(default_factory=dict)
    emergency_directions: list = field(default_factory=list)
    manual_target: Optional[str] = None
    last_event_sequence: dict = field(default_factory=dict)
    alerts: list = field(default_factory=list)

    def queue_counts(self):
        return {d: len(self.queues[d]) for d in DIRECTIONS}

    def status(self):
        return {
            "junction_id": self.junction_id, "mode": self.mode, "phase": self.phase,
            "transition": self.transition, "controller_status": self.controller_status,
            "desired_signals": dict(self.desired_signals), "actual_signals": dict(self.actual_signals),
            "queues": self.queue_counts(), "emergency_directions": list(self.emergency_directions),
            "alerts": list(self.alerts), "pending_commands": list(self.pending_commands.values()),
        }

def now_ts():
    return datetime.now(timezone.utc).timestamp()

def phase_for_direction(direction: str) -> str:
    if direction not in DIRECTIONS:
        raise ValueError("Invalid direction")
    return "NORTH_SOUTH" if direction in PHASES["NORTH_SOUTH"] else "EAST_WEST"

def choose_phase(j: Junction, now: float) -> str:
    """Deterministic score: queue size + max vehicle priority + capped wait bonus.
    A phase waiting >=45s gets a strong starvation-protection bonus."""
    scores = {}
    for phase, dirs in PHASES.items():
        vehicles = [v for d in dirs for v in j.queues[d]]
        queue_score = len(vehicles) * 2
        priority_score = max((VEHICLE_PRIORITY[v.vehicle_type] * 3 for v in vehicles), default=0)
        wait = max((now - v.arrived_at for v in vehicles), default=0)
        starvation_bonus = 100 if wait >= 45 else min(wait / 10, 4)
        emergency_bonus = 1000 if any(v.vehicle_type == "EMERGENCY" for v in vehicles) else 0
        scores[phase] = queue_score + priority_score + starvation_bonus + emergency_bonus
    if scores["NORTH_SOUTH"] == scores["EAST_WEST"]:
        # Tie-break toward the phase not currently being served.
        return "EAST_WEST" if j.phase == "NORTH_SOUTH" else "NORTH_SOUTH"
    return max(scores, key=scores.get)

def request_phase(j: Junction, target: str, now: float, reason: str = "SCHEDULER"):
    if target not in PHASES:
        raise ValueError("Invalid phase")
    if j.transition != "STABLE":
        j.transition_target = target
        return "TRANSITION_ALREADY_IN_PROGRESS"
    if target == j.phase:
        return "ALREADY_ACTIVE"
    # Always use safe sequence; no direct conflicting GREEN.
    j.transition = "YELLOW"
    j.transition_target = target
    j.transition_started_at = now
    j.desired_signals = {d: (Signal.YELLOW.value if d in PHASES[j.phase] else Signal.RED.value) for d in DIRECTIONS}
    return "TRANSITION_STARTED"

def advance_transition(j: Junction, now: float):
    """Timer-driven transition; called by scheduler/tick, never sleeps in a request."""
    if j.transition == "YELLOW" and j.transition_started_at is not None and now - j.transition_started_at >= 5:
        j.transition = "ALL_RED"
        j.transition_started_at = now
        j.desired_signals = {d: Signal.RED.value for d in DIRECTIONS}
        return "ALL_RED_STARTED"
    if j.transition == "ALL_RED" and j.transition_started_at is not None and now - j.transition_started_at >= 1:
        target = j.transition_target or j.phase
        j.phase = target
        j.transition = "STABLE"
        j.transition_target = None
        j.transition_started_at = None
        j.green_started_at = now
        j.desired_signals = {d: (Signal.GREEN.value if d in PHASES[target] else Signal.RED.value) for d in DIRECTIONS}
        if j.mode == Mode.EMERGENCY.value and not j.emergency_directions:
            j.mode = Mode.AUTOMATIC.value
        return "TARGET_PHASE_ACTIVE"
    return None
