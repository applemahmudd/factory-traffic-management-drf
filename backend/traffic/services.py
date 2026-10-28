import uuid
from datetime import datetime, timezone
from django.db import transaction, IntegrityError
from django.utils import timezone as django_timezone
from .models import JunctionRecord, ProcessedSensorEvent, ControllerCommand, AuditEvent
from .domain import Junction, Vehicle, DIRECTIONS, PHASES, phase_for_direction, choose_phase, request_phase, advance_transition


def now_ts():
    return django_timezone.now().timestamp()


def fresh_junction(junction_id):
    j = Junction(junction_id=junction_id, green_started_at=now_ts())
    j.actual_signals = {d: "UNKNOWN" for d in DIRECTIONS}
    j.controller_status = "UNKNOWN"
    j.mode = "DEGRADED"  # Physical state is unknown until controller ACK/reconciliation.
    j.alerts = ["Controller state unknown; confirm physical states before normal operation."]
    return j


def state_to_json(j):
    return {
        "junction_id": j.junction_id, "mode": j.mode, "phase": j.phase,
        "transition": j.transition, "transition_target": j.transition_target,
        "transition_started_at": j.transition_started_at, "green_started_at": j.green_started_at,
        "queues": {d: [vars(v) for v in j.queues[d]] for d in DIRECTIONS},
        "desired_signals": j.desired_signals, "actual_signals": j.actual_signals,
        "controller_status": j.controller_status, "pending_commands": j.pending_commands,
        "emergency_directions": j.emergency_directions, "manual_target": j.manual_target,
        "last_event_sequence": j.last_event_sequence, "alerts": j.alerts,
    }


def json_to_state(data):
    j = Junction(junction_id=data["junction_id"])
    for field in ["mode", "phase", "transition", "transition_target", "transition_started_at", "green_started_at", "desired_signals", "actual_signals", "controller_status", "pending_commands", "emergency_directions", "manual_target", "last_event_sequence", "alerts"]:
        if field in data: setattr(j, field, data[field])
    j.queues = {d: [Vehicle(**v) for v in data.get("queues", {}).get(d, [])] for d in DIRECTIONS}
    return j


def get_record(junction_id, lock=False):
    qs = JunctionRecord.objects
    if lock: qs = qs.select_for_update()
    try: return qs.get(junction_id=junction_id)
    except JunctionRecord.DoesNotExist: return None


def ensure_junction(junction_id="A"):
    record, created = JunctionRecord.objects.get_or_create(junction_id=junction_id, defaults={"state": state_to_json(fresh_junction(junction_id))})
    return record


def audit(junction_id, event_type, details=None):
    AuditEvent.objects.create(junction_id=junction_id, event_type=event_type, details=details or {})


def make_commands(record, j, reason):
    """Persist desired-state commands. Physical actual state changes only on ACK."""
    for direction, requested in j.desired_signals.items():
        # Send only directions whose desired state differs from confirmed state.
        if j.actual_signals.get(direction) == requested:
            continue
        # Avoid multiple outstanding commands for the same direction/state.
        exists = ControllerCommand.objects.filter(junction_id=j.junction_id, direction=direction, requested_state=requested, status="PENDING").exists()
        if exists: continue
        cid = "cmd-" + uuid.uuid4().hex[:12]
        ControllerCommand.objects.create(command_id=cid, junction_id=j.junction_id, direction=direction, requested_state=requested)
        j.pending_commands[cid] = {"command_id": cid, "junction_id": j.junction_id, "direction": direction, "requested_state": requested, "status": "PENDING", "reason": reason}
        audit(j.junction_id, "SIGNAL_STATE_REQUESTED", {"command_id": cid, "direction": direction, "requested_state": requested, "reason": reason})


def save_state(record, j, reason="STATE_UPDATED"):
    make_commands(record, j, reason)
    record.state = state_to_json(j)
    record.save(update_fields=["state", "updated_at"])


def status_payload(j):
    payload = j.status()
    payload["pending_commands"] = list(j.pending_commands.values())
    return payload


def process_sensor(data):
    with transaction.atomic():
        # Create junction A by default, but reject truly unknown junction IDs.
        record = get_record(data["junction_id"], lock=True)
        if record is None: raise LookupError("Unknown junction_id")
        existing = ProcessedSensorEvent.objects.filter(event_id=data["event_id"]).first()
        if existing:
            audit(data["junction_id"], "DUPLICATE_SENSOR_EVENT", {"event_id": data["event_id"]})
            return {"duplicate": True, "accepted": existing.accepted, "result": existing.result}
        j = json_to_state(record.state)
        direction, vehicle_id = data["direction"], data["vehicle_id"]
        last = j.last_event_sequence.get(direction, -1)
        if data["sequence_no"] <= last:
            result = {"accepted": False, "reason": "Out-of-order sequence number"}
            ProcessedSensorEvent.objects.create(event_id=data["event_id"], junction_id=j.junction_id, sequence_no=data["sequence_no"], accepted=False, result=result)
            audit(j.junction_id, "REJECTED_SENSOR_EVENT", {"event_id": data["event_id"], **result})
            return result
        j.last_event_sequence[direction] = data["sequence_no"]
        event_type = data["event_type"]
        if event_type == "VEHICLE_ARRIVED":
            if any(v.vehicle_id == vehicle_id for q in j.queues.values() for v in q):
                result = {"accepted": False, "reason": "Vehicle already queued"}
            else:
                j.queues[direction].append(Vehicle(vehicle_id, data["vehicle_type"], now_ts(), data["sequence_no"]))
                result = {"accepted": True, "duplicate": False}
                audit(j.junction_id, "VEHICLE_DETECTED", {"event_id": data["event_id"], "direction": direction, "vehicle_id": vehicle_id, "vehicle_type": data["vehicle_type"], "sensor_timestamp": data["timestamp"].isoformat()})
                if data["vehicle_type"] == "EMERGENCY":
                    if direction not in j.emergency_directions: j.emergency_directions.append(direction)
                    j.mode = "EMERGENCY"
                    audit(j.junction_id, "EMERGENCY_DETECTED", {"direction": direction, "vehicle_id": vehicle_id})
                    target = phase_for_direction(direction)
                    if target != j.phase: request_phase(j, target, now_ts(), "EMERGENCY")
        else:
            found = False
            for d in DIRECTIONS:
                before = len(j.queues[d])
                j.queues[d] = [v for v in j.queues[d] if v.vehicle_id != vehicle_id]
                found = found or len(j.queues[d]) != before
            if found:
                result = {"accepted": True, "duplicate": False}
                audit(j.junction_id, "VEHICLE_CLEARED", {"event_id": data["event_id"], "direction": direction, "vehicle_id": vehicle_id})
                j.emergency_directions = [d for d in j.emergency_directions if any(v.vehicle_type == "EMERGENCY" for v in j.queues[d])]
                if j.mode == "EMERGENCY" and not j.emergency_directions: j.mode = "AUTOMATIC"
            else:
                result = {"accepted": False, "reason": "Vehicle not found in any queue"}
                audit(j.junction_id, "REJECTED_VEHICLE_CLEARANCE", {"vehicle_id": vehicle_id, "direction": direction})
        if j.mode == "AUTOMATIC" and j.transition == "STABLE":
            target = choose_phase(j, now_ts())
            if target != j.phase: request_phase(j, target, now_ts(), "SCHEDULER")
        save_state(record, j, event_type)
        ProcessedSensorEvent.objects.create(event_id=data["event_id"], junction_id=j.junction_id, sequence_no=data["sequence_no"], accepted=result["accepted"], result=result)
        return result


def issue_command(junction_id, data):
    with transaction.atomic():
        record = get_record(junction_id, lock=True)
        if record is None: raise LookupError("Unknown junction_id")
        j = json_to_state(record.state)
        if data["command"] == "RETURN_TO_AUTOMATIC":
            if j.mode == "DEGRADED": raise ValueError("Cannot enable automatic mode while controller state is unknown/degraded")
            j.mode = "AUTOMATIC"; j.manual_target = None
            audit(junction_id, "RETURNED_TO_AUTOMATIC", {})
            target = choose_phase(j, now_ts())
            if target != j.phase: request_phase(j, target, now_ts(), "AUTOMATIC")
        else:
            if j.mode == "EMERGENCY": raise ValueError("Emergency mode overrides manual control")
            if j.mode == "DEGRADED": raise ValueError("Controller is degraded; manual command rejected")
            j.mode = "MANUAL"; target = phase_for_direction(data["direction"]); j.manual_target = target
            request_phase(j, target, now_ts(), "MANUAL")
            audit(junction_id, "MANUAL_OVERRIDE_REQUESTED", {"direction": data["direction"], "target_phase": target})
        save_state(record, j, data["command"])
        return status_payload(j)


def tick_junction(junction_id):
    with transaction.atomic():
        record = get_record(junction_id, lock=True)
        if record is None: raise LookupError("Unknown junction_id")
        j = json_to_state(record.state); now = now_ts()
        result = advance_transition(j, now)
        if result: audit(junction_id, "SIGNAL_TRANSITION", {"result": result, "phase": j.phase, "transition": j.transition})
        elif j.mode == "AUTOMATIC" and j.transition == "STABLE" and now - j.green_started_at >= 30:
            target = choose_phase(j, now)
            if target != j.phase: result = request_phase(j, target, now, "SCHEDULE_TIMER")
        save_state(record, j, "TICK")
        return {"result": result or "NO_TRANSITION_DUE", **status_payload(j)}
