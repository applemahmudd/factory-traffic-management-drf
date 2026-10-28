# Factory Traffic Management System — Django REST Framework

Backend Developer Intern assessment implementation for CSI Smart Tech. This version uses **Django REST Framework**, SQLite, a separated traffic-domain module, and a plain HTML/CSS/JavaScript dashboard. REST APIs simulate sensors and physical-controller acknowledgements; an MQTT adapter can later call the same application services.

## Requirements
- Python 3.10+
- pip

## Run on Windows
```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations traffic
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/api/health` to check the backend and `http://127.0.0.1:8000/api/junctions/A/status` to initialize Junction A. Open `frontend/index.html` in your browser. The dashboard calls `http://127.0.0.1:8000` by default; use its API field if needed. SQLite data is stored in `backend/traffic.sqlite3`.

Interactive API: `http://127.0.0.1:8000/api/junctions/A/status` (DRF browsable API available for endpoints). There is no built-in Swagger UI dependency in this assessment version.

## API overview
- `GET /api/health`
- `GET /api/junctions`, `POST /api/junctions`, `GET /api/junctions/{id}`
- `GET /api/junctions/{id}/status`
- `POST /api/sensor-events`
- `POST /api/junctions/{id}/commands` (`MANUAL_GREEN_REQUEST`, `RETURN_TO_AUTOMATIC`)
- `POST /api/junctions/{id}/tick` advances timers without blocking sleeps
- `POST /api/controller-events` simulates ACK/NACK/OFFLINE
- `POST /api/device-events` reports device status
- `GET /api/junctions/{id}/history`
- `GET /api/junctions/{id}/commands`

## Architecture
- `backend/traffic/domain.py`: pure Python domain model, scoring, phase selection, safe transition functions. It has no Django or HTTP dependencies.
- `backend/traffic/models.py`: persisted junction JSON state, processed event IDs, controller commands, and audit history.
- `backend/traffic/services.py`: application services, transaction boundaries, queue handling, domain orchestration, and controller command creation.
- `backend/traffic/views.py`: DRF API endpoints and HTTP response mapping.
- `frontend/index.html`: dashboard. It displays API state and sends commands; it does not choose traffic phases.

State-changing operations use `transaction.atomic()` and attempt row locking with `select_for_update()`. SQLite does not provide PostgreSQL-style row-level locking; this is a single-process assessment design. For multiple workers, use PostgreSQL with row locks or serialized per-junction processing. Event IDs are unique in the database to enforce idempotency.

## Traffic-control algorithm
The scheduler scores each phase using queue size, maximum vehicle priority, capped waiting time, and starvation protection for vehicles waiting at least 45 seconds. Priority order: `EMERGENCY > TRUCK > FORKLIFT > EMPLOYEE_VEHICLE`. Emergency arrivals request preemption but never set a conflicting phase directly to GREEN.

Normal GREEN duration is approximately 30 seconds. A phase switch follows `GREEN -> YELLOW (5 seconds) -> ALL_RED (1-second simulation assumption) -> target GREEN`. `POST /api/junctions/{id}/tick` advances the transition. It does not sleep in a request handler. The dashboard polls every five seconds; a durable background worker would be needed for automatic ticking without manual API calls.

## Event semantics
- `event_id` is the idempotency key. A repeated ID does not apply queue changes twice.
- `sequence_no` must increase per direction. Stale sequence numbers are rejected and audited.
- Sensor timestamp is retained in audit; server receive time is used for queue waiting time.
- Queue membership is based on vehicle ID. A clearance without a matching arrival is rejected and never makes queue counts negative.
- The provided schema does not include sensor/device ID, so sequence numbers are tracked per direction. A production API should include device identity.

## Controller simulation and recovery
Desired signal state and controller-confirmed actual state are separate. A command receives a unique `command_id` and remains pending until a matching response. ACK updates actual state only to the state reported by the controller; a mismatch keeps the system degraded and adds an alert. NACK/OFFLINE moves the junction into DEGRADED. Duplicate ACKs do not re-apply the command.

On first initialization, actual states are UNKNOWN and mode is DEGRADED. The status endpoint creates pending commands to reconcile desired signals; the evaluator can simulate ACKs using the dashboard. The implementation persists queue, event, command, junction and audit data across restarts. It does not yet have a durable command timeout/retry worker; this is documented as incomplete.

## Assumptions / Questions / Requirement Issues
1. **Conflict model:** only NORTH+SOUTH and EAST+WEST phases are represented. Real turning movements require a site-specific conflict matrix.
2. **ALL_RED duration:** the PDF permits ALL_RED but does not specify duration. One second is a demo assumption, not a real-world safety recommendation.
3. **Emergency completion:** an emergency is cleared when its vehicle receives `VEHICLE_CLEARED`. Multiple emergencies from different directions require an explicit operational arbitration policy; this demo tracks active emergency directions and prioritizes an emergency phase request.
4. **Manual vs emergency:** emergency mode overrides manual control. Manual requests are rejected while emergency mode is active or controller state is degraded. Manual override has no lease/expiry.
5. **Sequence semantics:** sequence numbers are checked per direction because the input schema has no sensor ID.
6. **Controller acknowledgement:** sending a command is not proof it executed. Actual state changes only after ACK. Autonomous timeout/retry processing remains incomplete.
7. **Restart recovery:** persistent queue/history remains, while physical state starts UNKNOWN/DEGRADED until controller state is reconciled. Do not assume requested signals survived a restart.
8. **Concurrency:** `transaction.atomic()` and `select_for_update()` communicate intended locking; SQLite has limited locking semantics. Production multi-worker deployment should use PostgreSQL locks or a per-junction actor/queue.
9. **Authentication:** omitted for time-boxed assessment; manual control must be authorized before deployment.
10. **Physical fail-safe:** software alone cannot guarantee hardware safety during communication failure. Hardware interlocks and an approved fail-safe plan are necessary.

## Demonstration scenarios
1. Start server and open the dashboard. First, simulate controller ACKs for pending initial signal commands, using the requested states shown in the command list.
2. Submit arrivals from different directions and observe queue counts and history.
3. Submit the exact same event payload twice with the same event ID; queue count must not increase twice.
4. Submit a vehicle arrival then a clearance for the same vehicle ID and direction.
5. Add an emergency vehicle from EAST while NORTH/SOUTH is active. Advance transitions using the dashboard's scheduler button and ACK each pending controller command.
6. Request manual GREEN for WEST, then return to automatic. Commands must use safe transitions.
7. Simulate controller NACK/OFFLINE and inspect DEGRADED mode and alerts.
8. Restart server and verify persisted queues/history. Actual states remain persisted as last confirmed state, but the documented limitation is that a production controller reconciliation should run at startup before normal operation.

## Tests
```bat
cd backend
python manage.py test traffic
```
Tests cover duplicate-event idempotency, invalid directions, unknown junctions, and the health endpoint.

## Major architectural decisions
- DRF was selected because it is familiar to the candidate and provides serializer validation and clear API structure.
- Traffic domain rules are separated from API handlers and persistence.
- SQLite makes the assessment easy to run; PostgreSQL is recommended for concurrent production workloads.
- REST is used to simulate IoT and controller communication; MQTT can be introduced as an adapter without moving traffic rules into MQTT callbacks.
- Polling is chosen for the dashboard because real-time streaming is optional.

## AI / Tool Usage
ChatGPT was used to help interpret the assessment, plan the architecture, draft implementation scaffolding and tests, and prepare documentation. The candidate is responsible for reviewing, testing, understanding, and being able to explain or modify the submitted code.

## Known limitations / next steps
- Add a durable periodic scheduler (e.g. Celery) for automatic timer advancement.
- Add command acknowledgement timeout, bounded retry, and stale command supersession.
- Strengthen emergency arbitration and event sequence tracking per sensor.
- Add authentication/authorization for manual commands.
- Use PostgreSQL row-level locks for multi-worker deployment.
- Add broader state-machine and browser tests. Before real-world use, have qualified traffic-control engineers validate timings and hardware fail-safe behavior.
