from django.db import transaction, IntegrityError
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import JunctionRecord, ProcessedSensorEvent, ControllerCommand, AuditEvent
from .serializers import JunctionCreateSerializer, SensorEventSerializer, JunctionCommandSerializer, ControllerEventSerializer, DeviceEventSerializer
from .services import ensure_junction, get_record, json_to_state, state_to_json, status_payload, audit, save_state, process_sensor, issue_command, tick_junction, now_ts
from .domain import DIRECTIONS

@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "Factory Traffic Management System", "framework": "Django REST Framework"})

class JunctionListCreateView(APIView):
    def get(self, request):
        ensure_junction("A")
        return Response([{"junction_id": r.junction_id, "created_at": r.created_at} for r in JunctionRecord.objects.all().order_by("junction_id")])
    def post(self, request):
        serializer = JunctionCreateSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        jid = serializer.validated_data["junction_id"]
        record, created = JunctionRecord.objects.get_or_create(junction_id=jid, defaults={"state": state_to_json(__import__("traffic.services", fromlist=["fresh_junction"]).fresh_junction(jid))})
        if created: audit(jid, "JUNCTION_CREATED", {})
        return Response({"junction_id": jid, "created": created}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

class JunctionDetailView(APIView):
    def get(self, request, junction_id):
        record = get_record(junction_id)
        if not record: return Response({"detail": "Unknown junction_id"}, status=404)
        return Response({"junction_id": record.junction_id, "status": status_payload(json_to_state(record.state))})

class JunctionStatusView(APIView):
    def get(self, request, junction_id):
        ensure_junction("A")
        with transaction.atomic():
            record = get_record(junction_id, lock=True)
            if not record: return Response({"detail": "Unknown junction_id"}, status=404)
            j = json_to_state(record.state)
            # Ensure initial desired states are sent to the controller simulator as pending commands.
            save_state(record, j, "STATUS_RECONCILIATION")
            return Response(status_payload(j))

class SensorEventView(APIView):
    def post(self, request):
        serializer = SensorEventSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        try: result = process_sensor(serializer.validated_data)
        except LookupError as exc: return Response({"detail": str(exc)}, status=404)
        return Response(result, status=200 if result.get("duplicate") else (202 if result.get("accepted") else 409))

class JunctionCommandsView(APIView):
    def get(self, request, junction_id):
        if not JunctionRecord.objects.filter(junction_id=junction_id).exists(): return Response({"detail": "Unknown junction_id"}, status=404)
        commands = ControllerCommand.objects.filter(junction_id=junction_id).order_by("-created_at")[:100]
        return Response([{"command_id": c.command_id, "junction_id": c.junction_id, "direction": c.direction, "requested_state": c.requested_state, "status": c.status, "created_at": c.created_at.timestamp()} for c in commands])
    def post(self, request, junction_id):
        serializer = JunctionCommandSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        try: result = issue_command(junction_id, serializer.validated_data)
        except LookupError as exc: return Response({"detail": str(exc)}, status=404)
        except ValueError as exc: return Response({"detail": str(exc)}, status=409)
        return Response(result)

class JunctionTickView(APIView):
    def post(self, request, junction_id):
        try: result = tick_junction(junction_id)
        except LookupError as exc: return Response({"detail": str(exc)}, status=404)
        return Response(result)

class JunctionHistoryView(APIView):
    def get(self, request, junction_id):
        if not JunctionRecord.objects.filter(junction_id=junction_id).exists(): return Response({"detail": "Unknown junction_id"}, status=404)
        try: limit = max(1, min(int(request.query_params.get("limit", 50)), 200))
        except ValueError: limit = 50
        events = AuditEvent.objects.filter(junction_id=junction_id)[:limit]
        return Response([{"junction_id": e.junction_id, "event_type": e.event_type, "details": e.details, "timestamp": e.timestamp.timestamp()} for e in events])

class ControllerEventView(APIView):
    def post(self, request):
        serializer = ControllerEventSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            record = get_record(data["junction_id"], lock=True)
            if not record: return Response({"detail": "Unknown junction_id"}, status=404)
            command = ControllerCommand.objects.filter(command_id=data["command_id"], junction_id=data["junction_id"]).first()
            if not command: return Response({"detail": "Unknown command_id"}, status=404)
            if command.status != "PENDING": return Response({"duplicate": True, "detail": "Command already processed"}, status=200)
            j = json_to_state(record.state)
            if data["status"] == "ACK":
                actual = data.get("actual_state")
                if not actual: return Response({"detail": "actual_state is required for ACK"}, status=400)
                command.status = "ACK"; command.acknowledged_at = timezone.now(); command.save(update_fields=["status", "acknowledged_at"])
                j.actual_signals[command.direction] = actual
                j.controller_status = "ONLINE"
                if actual != command.requested_state:
                    j.mode = "DEGRADED"
                    mismatch = f"Desired/actual mismatch for {command.direction}: desired {command.requested_state}, actual {actual}"
                    if mismatch not in j.alerts: j.alerts.append(mismatch)
                    audit(command.junction_id, "DESIRED_ACTUAL_MISMATCH", {"command_id": command.command_id, "direction": command.direction, "desired": command.requested_state, "actual": actual})
                j.pending_commands.pop(command.command_id, None)
                audit(command.junction_id, "SIGNAL_STATE_CONFIRMED", {"command_id": command.command_id, "direction": command.direction, "actual_state": actual})
                if all(v != "UNKNOWN" for v in j.actual_signals.values()) and not ControllerCommand.objects.filter(junction_id=j.junction_id, status="PENDING").exclude(command_id=command.command_id).exists():
                    if j.mode == "DEGRADED" and not any("mismatch" in a.lower() for a in j.alerts): j.mode = "AUTOMATIC"
                    j.alerts = [a for a in j.alerts if "Controller state unknown" not in a]
            else:
                command.status = data["status"]; command.acknowledged_at = timezone.now(); command.save(update_fields=["status", "acknowledged_at"])
                j.controller_status = "OFFLINE" if data["status"] == "OFFLINE" else "DEGRADED"
                j.mode = "DEGRADED"
                alert = f"Controller command {command.command_id} returned {data['status']}"
                if alert not in j.alerts: j.alerts.append(alert)
                j.pending_commands.pop(command.command_id, None)
                audit(command.junction_id, "CONTROLLER_FAILURE", {"command_id": command.command_id, "status": data["status"]})
            record.state = state_to_json(j); record.save(update_fields=["state", "updated_at"])
        return Response({"processed": True, "status": data["status"], "junction_status": status_payload(j)})

class DeviceEventView(APIView):
    def post(self, request):
        serializer = DeviceEventSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            record = get_record(data["junction_id"], lock=True)
            if not record: return Response({"detail": "Unknown junction_id"}, status=404)
            duplicate = ProcessedSensorEvent.objects.filter(event_id=data["event_id"]).exists()
            if duplicate: return Response({"duplicate": True}, status=200)
            j = json_to_state(record.state)
            if data["device_type"] == "SIGNAL_CONTROLLER":
                j.controller_status = data["status"]
            if data["status"] != "ONLINE":
                j.mode = "DEGRADED"
                alert = f"{data['device_type']} {data.get('direction', 'ALL')} is {data['status']}"
                if alert not in j.alerts: j.alerts.append(alert)
            else:
                j.alerts = [a for a in j.alerts if not (data["device_type"] in a and data["status"] in a)]
            record.state = state_to_json(j); record.save(update_fields=["state", "updated_at"])
            ProcessedSensorEvent.objects.create(event_id=data["event_id"], junction_id=j.junction_id, accepted=True, result={"device_event": True})
            audit(j.junction_id, "DEVICE_STATUS_CHANGED", {"device_type": data["device_type"], "direction": data.get("direction"), "status": data["status"], "sensor_timestamp": data["timestamp"].isoformat()})
        return Response({"accepted": True, "status": data["status"]}, status=202)
