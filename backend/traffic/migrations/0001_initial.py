# Initial schema for the assessment prototype.
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="JunctionRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("junction_id", models.CharField(max_length=32, unique=True)),
                ("state", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="ProcessedSensorEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.CharField(max_length=120, unique=True)),
                ("junction_id", models.CharField(db_index=True, max_length=32)),
                ("sequence_no", models.PositiveBigIntegerField(blank=True, null=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("accepted", models.BooleanField(default=False)),
                ("result", models.JSONField(default=dict)),
            ],
        ),
        migrations.CreateModel(
            name="ControllerCommand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("command_id", models.CharField(max_length=80, unique=True)),
                ("junction_id", models.CharField(db_index=True, max_length=32)),
                ("direction", models.CharField(max_length=10)),
                ("requested_state", models.CharField(max_length=10)),
                ("status", models.CharField(default="PENDING", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("junction_id", models.CharField(db_index=True, max_length=32)),
                ("event_type", models.CharField(db_index=True, max_length=80)),
                ("details", models.JSONField(default=dict)),
                ("timestamp", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={"ordering": ["-timestamp", "-id"]},
        ),
    ]
