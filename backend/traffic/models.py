from django.db import models

class JunctionRecord(models.Model):
    junction_id = models.CharField(max_length=32, unique=True)
    state = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class ProcessedSensorEvent(models.Model):
    event_id = models.CharField(max_length=120, unique=True)
    junction_id = models.CharField(max_length=32, db_index=True)
    sequence_no = models.PositiveBigIntegerField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    accepted = models.BooleanField(default=False)
    result = models.JSONField(default=dict)

class ControllerCommand(models.Model):
    command_id = models.CharField(max_length=80, unique=True)
    junction_id = models.CharField(max_length=32, db_index=True)
    direction = models.CharField(max_length=10)
    requested_state = models.CharField(max_length=10)
    status = models.CharField(max_length=20, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

class AuditEvent(models.Model):
    junction_id = models.CharField(max_length=32, db_index=True)
    event_type = models.CharField(max_length=80, db_index=True)
    details = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    class Meta:
        ordering = ["-timestamp", "-id"]
