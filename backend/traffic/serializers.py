from rest_framework import serializers
from .domain import DIRECTIONS

class JunctionCreateSerializer(serializers.Serializer):
    junction_id = serializers.CharField(max_length=32, trim_whitespace=True)

class SensorEventSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=120)
    junction_id = serializers.CharField(max_length=32)
    direction = serializers.ChoiceField(choices=DIRECTIONS)
    event_type = serializers.ChoiceField(choices=["VEHICLE_ARRIVED", "VEHICLE_CLEARED"])
    vehicle_id = serializers.CharField(max_length=80)
    vehicle_type = serializers.ChoiceField(choices=["FORKLIFT", "TRUCK", "EMPLOYEE_VEHICLE", "EMERGENCY"], required=False, allow_null=True)
    sequence_no = serializers.IntegerField(min_value=0)
    timestamp = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["event_type"] == "VEHICLE_ARRIVED" and not attrs.get("vehicle_type"):
            raise serializers.ValidationError({"vehicle_type": "Required for VEHICLE_ARRIVED."})
        return attrs

class JunctionCommandSerializer(serializers.Serializer):
    command = serializers.ChoiceField(choices=["MANUAL_GREEN_REQUEST", "RETURN_TO_AUTOMATIC"])
    direction = serializers.ChoiceField(choices=DIRECTIONS, required=False)
    def validate(self, attrs):
        if attrs["command"] == "MANUAL_GREEN_REQUEST" and not attrs.get("direction"):
            raise serializers.ValidationError({"direction": "Required for MANUAL_GREEN_REQUEST."})
        return attrs

class ControllerEventSerializer(serializers.Serializer):
    command_id = serializers.CharField(max_length=80)
    junction_id = serializers.CharField(max_length=32)
    status = serializers.ChoiceField(choices=["ACK", "NACK", "OFFLINE"])
    actual_state = serializers.ChoiceField(choices=["RED", "YELLOW", "GREEN", "UNKNOWN"], required=False)
    direction = serializers.ChoiceField(choices=DIRECTIONS, required=False)

class DeviceEventSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=120)
    junction_id = serializers.CharField(max_length=32)
    device_type = serializers.ChoiceField(choices=["SIGNAL_CONTROLLER", "SENSOR"])
    direction = serializers.ChoiceField(choices=DIRECTIONS, required=False)
    status = serializers.ChoiceField(choices=["ONLINE", "OFFLINE", "DEGRADED"])
    timestamp = serializers.DateTimeField()
