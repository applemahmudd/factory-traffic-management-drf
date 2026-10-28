# Before you submit

- [ ] Install dependencies and run migrations.
- [ ] Run `python manage.py test traffic` and review each test.
- [ ] Start the server and inspect `/api/junctions/A/status`.
- [ ] ACK initial pending commands using the exact requested state; do not blindly ACK RED for every command.
- [ ] Test duplicate event IDs and verify queue count does not change twice.
- [ ] Test arrival + clearance with the same vehicle ID.
- [ ] Test emergency preemption and each transition stage.
- [ ] Test manual override and return to automatic.
- [ ] Test NACK/OFFLINE and confirm DEGRADED mode is visible.
- [ ] Read `traffic/domain.py`, `traffic/services.py`, and `traffic/views.py` so you can explain the code.
- [ ] Update README if you change any behavior. Mention AI assistance honestly.

Important: this is an assessment prototype, not safety-certified traffic-control software. Do not connect it to real signal hardware.
