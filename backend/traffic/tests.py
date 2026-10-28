from django.test import TestCase
from rest_framework.test import APIClient
from .models import JunctionRecord, AuditEvent
from .services import fresh_junction, state_to_json

class TrafficAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        JunctionRecord.objects.create(junction_id="A", state=state_to_json(fresh_junction("A")))

    def event(self, event_id="evt-1", seq=1, vehicle_id="VH-1", event_type="VEHICLE_ARRIVED", vehicle_type="TRUCK"):
        return {"event_id": event_id, "junction_id": "A", "direction": "NORTH", "event_type": event_type,
                "vehicle_id": vehicle_id, "vehicle_type": vehicle_type, "sequence_no": seq,
                "timestamp": "2026-10-27T10:00:00Z"}

    def test_duplicate_event_is_idempotent(self):
        first = self.client.post("/api/sensor-events", self.event(), format="json")
        second = self.client.post("/api/sensor-events", self.event(), format="json")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        status_response = self.client.get("/api/junctions/A/status")
        self.assertEqual(status_response.data["queues"]["NORTH"], 1)

    def test_invalid_direction_rejected(self):
        payload = self.event(); payload["direction"] = "UP"
        self.assertEqual(self.client.post("/api/sensor-events", payload, format="json").status_code, 400)

    def test_unknown_junction_rejected(self):
        payload = self.event(); payload["junction_id"] = "Z"
        self.assertEqual(self.client.post("/api/sensor-events", payload, format="json").status_code, 404)

    def test_health(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
