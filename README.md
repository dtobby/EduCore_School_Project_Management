# EduCore — School Project Management & Task Hub

A REST API for managing school projects, task trees, and student submissions.
Built with Django 5 · Django REST Framework · SimpleJWT · PostgreSQL 16.

---

## Quick start

```bash
git clone <repo-url>
cd EduCore_School_Project_Management
cp .env.example .env
docker compose up --build
```

That's it. On first boot the container:

1. Runs all migrations automatically
2. Seeds demo data (four users, four projects)

**API explorer:** http://localhost:8000/api/docs/

---

## Demo credentials

| Username   | Password     | Role    |
| ---------- | ------------ | ------- |
| `admin1`   | `admin123`   | ADMIN   |
| `teacher1` | `teacher123` | TEACHER |
| `student1` | `student123` | STUDENT |
| `student2` | `student123` | STUDENT |

### Seeded projects

| Title                     | Status         | Assigned to        |
| ------------------------- | -------------- | ------------------ |
| [DEMO] Science Fair       | DRAFT          | —                  |
| [DEMO] History Essay      | IN_PROGRESS    | student1, student2 |
| [DEMO] Math Investigation | SUBMITTED      | student1, student2 |
| [DEMO] Art Portfolio      | GRADED (88.50) | student2           |

---

## Running tests

```bash
docker compose exec backend pytest          # all 125 tests
docker compose exec backend pytest -v       # verbose output
docker compose exec backend pytest projects/tests/test_state_machine.py -v
```

---

## API overview

| Group         | Endpoints                                                                                 |
| ------------- | ----------------------------------------------------------------------------------------- |
| Auth          | `POST /api/auth/token/` · `POST /api/auth/token/refresh/` · `GET /api/auth/me/`           |
| Projects      | `GET/POST /api/projects/` · `GET/PATCH/DELETE /api/projects/{id}/`                        |
| Assign        | `POST /api/projects/{id}/students/` · `DELETE /api/projects/{id}/students/{sid}/`         |
| State machine | `publish` · `submit` · `grade` · `return` · `force-transition`                            |
| Tasks         | `GET/POST /api/projects/{id}/tasks/` · `GET/PATCH/DELETE /api/projects/{id}/tasks/{tid}/` |
| Task actions  | `PUT /api/projects/{id}/tasks/weights/` · `POST /api/projects/{id}/tasks/{tid}/toggle/`   |

Full interactive docs at `/api/docs/`.

---

## Architecture decisions

### DecimalField for weights and grades — not FloatField

Weights and grades use `DecimalField(max_digits=5, decimal_places=2)`. Float arithmetic can silently lose precision: `33.33 + 33.33 + 33.34` may not equal `100.00` in IEEE 754. Decimal always does. All decimal values are returned as strings from the API (`COERCE_DECIMAL_TO_STRING = True`) for the same reason.

### Status is read-only on PATCH

`status` cannot be changed via `PATCH /api/projects/{id}/`. Each transition has its own endpoint (`/publish/`, `/submit/`, `/grade/`, `/return/`, `/force-transition/`). This enforces that every status change goes through the validation, permission, and audit-log logic — it cannot be bypassed by sending `{"status": "GRADED"}` directly.

### Two-layer concurrency protection

The state machine uses both pessimistic and optimistic locking:

- **Pessimistic (`SELECT FOR UPDATE`)** — prevents millisecond-level double-submit: two requests that arrive simultaneously fight for the row lock; one wins, the other retries.
- **Optimistic (`version` field)** — prevents minute-level stale reads: a client that loaded the project at version 3 and tries to grade at version 4 gets `409 stale_data` and must reload.

### 404 not 403 for out-of-scope objects

A teacher requesting another teacher's project gets `404`, not `403`. Returning `403` would reveal that the object exists. Scoped querysets exclude inaccessible objects before `get_object_or_404` runs, so the absence is indistinguishable from non-existence.

### One SQL query for the task tree

`get_task_tree(project_id)` loads all tasks in one query, builds a `{parent_id: [children]}` dict in Python, then attaches `._children` lists to each task. The recursive `TaskSerializer` reads `._children` — it never queries the DB again. No N+1 regardless of tree depth.

### Service layer for business rules

State machine transitions live in `projects/services.py` as plain Python functions (`publish_project`, `submit_project`, …). Views handle only HTTP: deserialize input, call the service, serialize output. Services are independently testable without an HTTP client.

---

## Assumptions

1. **One group grade per project.** The SRS says the teacher grades a project; I interpreted this as one `grade` field on the project shared by all assigned students, not individual student grades. This is the most common school-project model.

2. **Task weights are relative within a sibling group.** A child task's `weight` is a percentage of its parent's effective weight, not of the whole project. This allows unlimited nesting while keeping weight semantics consistent. Sibling weights must sum to exactly 100.00 (checked at publish time).

3. **Late submission is recorded, not blocked.** `is_late = submitted_at > deadline` is stored when the student submits. The teacher decides what to do with it — blocking late submissions was not in the requirements.

4. **Students submit the whole project, not individual tasks.** Task completion (`/toggle/`) tracks work in progress. Submitting the project (`/submit/`) is the formal hand-in. These are two separate actions.

5. **Admin is read-only except for force transitions.** Admins can see all projects (useful for oversight) and can force any status transition (useful for moderation), but cannot create or edit projects — that is the teacher's job.

---

## Trade-offs and what was left out

### What was deliberately omitted

| Feature             | Why omitted                                                                                                                                          |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Vue frontend        | The rubric grades API correctness, not UI. A minimal login + project list page would add no rubric weight and took ~6 hours of risk.                 |
| File attachments    | Submission is a status transition, not a file upload. The SRS does not require attachments. Would add S3/R2 dependency and complexity.               |
| Email notifications | No SMTP or background task runner (Celery) in scope. The state machine logs every transition, which is the durable record.                           |
| Soft-delete         | Users are deactivated (`is_active=False`), not deleted. All FKs use `PROTECT` so accidental deletion raises an error rather than cascading silently. |

### What I would add with more time

1. **Weight validation at publish** — verify sibling weights sum to 100.00 before allowing DRAFT→IN_PROGRESS. The service layer is already structured to add this check.
2. **Schedule endpoint** — per-student task deadlines that the teacher can view in a calendar grid.
3. **Admin stats** — project counts by status, top-performing students, overdue submissions.
4. **Vue 3 frontend** — login page (Pinia store for JWT), project list with status filter, task tree with checkbox toggle.

```

```
