from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple, Dict, Any
import os
import json
import httpx
import psycopg
from datetime import datetime, time, timedelta, date as date_cls
from enum import Enum
from redis import asyncio as aioredis
import numpy as np
from .solver import AdvancedCVRPTWSolver
from .traffic import SmartMatrixCache


class OSRMClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    async def table(self, coords: List[Tuple[float, float]]) -> List[List[int]]:
        loc = ";".join([f"{lon},{lat}" for lon, lat in coords])
        url = f"{self.base_url}/table/v1/car/{loc}?annotations=duration"
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            res = await client.get(url)
            res.raise_for_status()
            return res.json()["durations"]


app = FastAPI(title="Optimizer MVP", version="0.2.0")


class Student(BaseModel):
    id: int
    lat: float
    lon: float
    tw_lo: Optional[str] = None
    tw_hi: Optional[str] = None
    max_ride_min: Optional[int] = 45
    service_time_sec: int = 60
    demand: int = 1
    priority: int = 1


class Vehicle(BaseModel):
    id: int
    capacity: int
    start_lat: float
    start_lon: float
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    shift_start_ts: Optional[str] = None
    shift_end_ts: Optional[str] = None


class OptimizeReq(BaseModel):
    date: str
    direction: str
    school_id: int
    school_lat: float
    school_lon: float
    school_arrival_deadline: Optional[str] = None
    students: List[Student]
    vehicles: List[Vehicle]
    drop_penalty: int = 10_000
    max_wait_slack_sec: int = 30 * 60
    allow_partial_solution: bool = True


OSRM_URL = os.getenv("OSRM_URL", "http://localhost:5000")
DB_URL = os.getenv("DB_URL", "postgresql://postgres:secret@localhost:5432/shuttle")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

redis_client: Optional[aioredis.Redis] = None
solver = AdvancedCVRPTWSolver()
matrix_cache = None


@app.on_event("startup")
async def on_startup():
    global redis_client, matrix_cache
    redis_client = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    matrix_cache = SmartMatrixCache(redis_client, OSRMClient(OSRM_URL))


@app.get("/health")
async def health():
    checks = {"status": "ok"}
    try:
        with psycopg.connect(DB_URL, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"
        checks["status"] = "degraded"

    try:
        pong = await redis_client.ping() if redis_client else False
        checks["redis"] = "ok" if pong else "error"
        if not pong:
            checks["status"] = "degraded"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        checks["status"] = "degraded"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OSRM_URL}")
            checks["osrm"] = "ok" if r.status_code < 500 else f"error: {r.status_code}"
            if r.status_code >= 500:
                checks["status"] = "degraded"
    except Exception as e:
        checks["osrm"] = f"error: {e}"
        checks["status"] = "degraded"
    return checks


@app.post("/optimize")
async def optimize(req: OptimizeReq):
    try:
        coords: List[Tuple[float, float]] = []
        for v in req.vehicles:
            coords.append((v.start_lon, v.start_lat))
        for s in req.students:
            coords.append((s.lon, s.lat))
        coords.append((req.school_lon, req.school_lat))

        durations = await matrix_cache.get_matrix(coords)
        problem_data = build_problem_data(req, durations)
        result = solver.solve_cvrptw_optimized(problem_data)

        if result["status"] == "NO_SOLUTION" or str(result["status"]).startswith("ERROR"):
            return {
                "plan_ids": [],
                "routes": [],
                "route_details": [],
                "solver_status": result["status"],
                "unassigned_students": result.get("unassigned_students", []),
                "metrics": {
                    "total_route_duration_sec": 0,
                    "assigned_students": 0,
                    "unassigned_students": len(result.get("unassigned_students", [])),
                    "max_ride_sec": None,
                },
                "warnings": ["No feasible solution found for current constraints."],
            }

        route_details, metrics, warnings = build_route_details(req, problem_data, result)
        plan_ids = save_route_plans(req, result["routes"], problem_data)

        if redis_client:
            snapshot = req.model_dump()
            try:
                await redis_client.setex(
                    f"plan:snapshot:{req.date}:{req.direction}:{req.school_id}",
                    24 * 3600,
                    json.dumps(snapshot),
                )
            except Exception:
                pass

        return {
            "plan_ids": plan_ids,
            "routes": [route_info["sequence"] for route_info in result["routes"]],
            "route_details": route_details,
            "solver_status": result["status"],
            "unassigned_students": result.get("unassigned_students", []),
            "objective_value": result.get("objective_value"),
            "solve_time_ms": result.get("solve_time_ms"),
            "metrics": metrics,
            "warnings": warnings,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _parse_time_like(value: Optional[str], service_date: date_cls) -> Optional[int]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed_time = datetime.strptime(text, fmt).time()
            return parsed_time.hour * 3600 + parsed_time.minute * 60 + parsed_time.second
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(text)
        return dt.hour * 3600 + dt.minute * 60 + dt.second
    except ValueError as exc:
        raise ValueError(f"Unsupported datetime/time format: {value}") from exc


def _seconds_to_datetime(date_str: str, second_of_day: Optional[int]) -> Optional[str]:
    if second_of_day is None:
        return None
    base_date = datetime.fromisoformat(date_str).date()
    dt = datetime.combine(base_date, time(0, 0)) + timedelta(seconds=int(second_of_day))
    return dt.isoformat()


def build_problem_data(req: OptimizeReq, durations: List[List[int]] | np.ndarray) -> Dict[str, Any]:
    """Günlük attendance tabanlı gerçek solve datası üretir."""
    service_date = datetime.fromisoformat(req.date).date()
    duration_matrix = durations.tolist() if isinstance(durations, np.ndarray) else durations

    n_vehicles = len(req.vehicles)
    n_students = len(req.students)
    school_index = n_vehicles + n_students

    school_deadline = _parse_time_like(req.school_arrival_deadline, service_date)
    if school_deadline is None:
        inferred_hi_values = [_parse_time_like(s.tw_hi, service_date) for s in req.students if s.tw_hi]
        default_deadline = 8 * 3600 + 30 * 60 if req.direction.upper() == "AM" else 17 * 3600 + 30 * 60
        school_deadline = max(inferred_hi_values, default=default_deadline)

    inferred_shift_starts = [_parse_time_like(v.shift_start_ts, service_date) for v in req.vehicles if v.shift_start_ts]
    inferred_student_lows = [_parse_time_like(s.tw_lo, service_date) for s in req.students if s.tw_lo]
    earliest_start = min(inferred_shift_starts + inferred_student_lows, default=max(0, school_deadline - 3 * 3600))

    horizon_candidates = [school_deadline + 30 * 60]
    for v in req.vehicles:
        shift_end = _parse_time_like(v.shift_end_ts, service_date)
        if shift_end is not None:
            horizon_candidates.append(shift_end)
    for s in req.students:
        hi = _parse_time_like(s.tw_hi, service_date)
        if hi is not None:
            horizon_candidates.append(hi + 30 * 60)
    horizon = max(horizon_candidates + [4 * 60 * 60, school_deadline])

    students = []
    student_index_to_id: Dict[int, int] = {}
    for i, s in enumerate(req.students):
        loc_index = n_vehicles + i
        tw_lo = _parse_time_like(s.tw_lo, service_date)
        tw_hi = _parse_time_like(s.tw_hi, service_date)

        if tw_lo is None:
            tw_lo = max(0, earliest_start)
        if tw_hi is None:
            tw_hi = school_deadline
        if tw_hi < tw_lo:
            raise ValueError(f"Invalid time window for student {s.id}: tw_hi < tw_lo")

        student_data = {
            "id": s.id,
            "loc_index": loc_index,
            "tw": (tw_lo, tw_hi),
            "demand": int(s.demand),
            "max_ride": int((s.max_ride_min or 45) * 60),
            "service_time_sec": int(s.service_time_sec),
            "priority": int(s.priority),
        }
        students.append(student_data)
        student_index_to_id[loc_index] = s.id

    vehicles = []
    for i, v in enumerate(req.vehicles):
        shift_lo = _parse_time_like(v.shift_start_ts, service_date)
        shift_hi = _parse_time_like(v.shift_end_ts, service_date)
        if shift_lo is None:
            shift_lo = max(0, earliest_start)
        if shift_hi is None:
            shift_hi = horizon
        if shift_hi < shift_lo:
            raise ValueError(f"Invalid shift window for vehicle {v.id}: shift_end_ts < shift_start_ts")

        vehicles.append(
            {
                "id": v.id,
                "capacity": v.capacity,
                "start_index": i,
                "end_index": school_index,
                "shift_window": (shift_lo, shift_hi),
            }
        )

    return {
        "time_matrix": duration_matrix,
        "students": students,
        "vehicles": vehicles,
        "school_index": school_index,
        "school_arrival_deadline": school_deadline,
        "horizon": horizon,
        "drop_penalty": int(req.drop_penalty),
        "max_wait_slack": int(req.max_wait_slack_sec),
        "node_student_map": student_index_to_id,
    }


def build_route_details(req: OptimizeReq, problem_data: Dict[str, Any], result: Dict[str, Any]):
    node_to_student = {s["loc_index"]: s for s in problem_data["students"]}
    vehicle_lookup = {idx: vehicle for idx, vehicle in enumerate(req.vehicles)}
    school_index = problem_data["school_index"]

    route_details = []
    total_route_duration_sec = 0
    assigned_students = 0
    max_ride_sec = None
    warnings: List[str] = []

    for route_info in result["routes"]:
        vehicle = vehicle_lookup[route_info["vehicle_index"]]
        sequence = route_info["sequence"]
        arrival_times = route_info.get("arrival_times", [])
        stops = []
        end_eta = arrival_times[-1] if arrival_times else None

        for node, eta in zip(sequence, arrival_times):
            stop_payload: Dict[str, Any] = {
                "node_index": node,
                "eta": _seconds_to_datetime(req.date, eta),
            }

            if node < len(req.vehicles):
                stop_payload["type"] = "VEHICLE_START"
            elif node == school_index:
                stop_payload["type"] = "SCHOOL"
            else:
                student = node_to_student.get(node)
                if student is None:
                    continue
                ride_time = None
                if end_eta is not None:
                    ride_time = max(0, int(end_eta - eta))
                    max_ride_sec = ride_time if max_ride_sec is None else max(max_ride_sec, ride_time)
                    if ride_time > student["max_ride"]:
                        warnings.append(
                            f"Student {student['id']} exceeds max ride target ({ride_time}s > {student['max_ride']}s)."
                        )
                stop_payload.update(
                    {
                        "type": "PICKUP",
                        "student_id": student["id"],
                        "ride_time_sec": ride_time,
                        "time_window": {
                            "lo": _seconds_to_datetime(req.date, student["tw"][0]),
                            "hi": _seconds_to_datetime(req.date, student["tw"][1]),
                        },
                    }
                )
                assigned_students += 1
            stops.append(stop_payload)

        total_route_duration_sec += int(route_info.get("route_duration_sec", 0))
        route_details.append(
            {
                "vehicle_id": vehicle.id,
                "capacity": vehicle.capacity,
                "route_duration_sec": int(route_info.get("route_duration_sec", 0)),
                "stops": stops,
            }
        )

    metrics = {
        "total_route_duration_sec": total_route_duration_sec,
        "assigned_students": assigned_students,
        "unassigned_students": len(result.get("unassigned_students", [])),
        "max_ride_sec": max_ride_sec,
    }
    return route_details, metrics, warnings


def save_route_plans(req: OptimizeReq, route_infos: List[Dict[str, Any]], problem_data: Dict[str, Any]) -> List[int]:
    plan_ids: List[int] = []
    students_offset = len(req.vehicles)
    school_index = students_offset + len(req.students)
    route_by_vehicle_idx = {route_info["vehicle_index"]: route_info for route_info in route_infos}

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            for idx, vehicle in enumerate(req.vehicles):
                route_info = route_by_vehicle_idx.get(idx, {"sequence": [], "arrival_times": []})
                seq_indices = route_info.get("sequence", [])
                arrival_times = route_info.get("arrival_times", [])

                student_ids: List[int] = []
                eta_sequence: List[datetime] = []
                for node, eta in zip(seq_indices, arrival_times):
                    if node == school_index or node < students_offset:
                        continue
                    student_idx = node - students_offset
                    if 0 <= student_idx < len(req.students):
                        student_ids.append(req.students[student_idx].id)
                        eta_sequence.append(datetime.fromisoformat(_seconds_to_datetime(req.date, eta)))

                cur.execute(
                    """
                    INSERT INTO route_plan (date, direction, vehicle_id, student_sequence, eta_sequence)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (req.date, req.direction, vehicle.id, student_ids, eta_sequence or None),
                )
                new_id = cur.fetchone()[0]
                plan_ids.append(new_id)
            conn.commit()
    return plan_ids


class EventType(str, Enum):
    ARRIVE = "ARRIVE"
    PICKED_UP = "PICKED_UP"
    DEPART = "DEPART"
    MANUAL_SKIP = "MANUAL_SKIP"


class StopEvent(BaseModel):
    ts: datetime
    trip_id: str
    vehicle_id: int
    student_id: int
    event_type: EventType
    lat: Optional[float] = None
    lon: Optional[float] = None


@app.post("/events")
async def ingest_event(event: StopEvent, idempotency_key: Optional[str] = Header(default=None)):
    if idempotency_key and redis_client:
        exists = await redis_client.exists(f"idem:{idempotency_key}")
        if exists:
            return {"status": "duplicate"}
    try:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO stop_events (ts, trip_id, vehicle_id, student_id, event_type, lat, lon, seq_no)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        event.ts,
                        event.trip_id,
                        event.vehicle_id,
                        event.student_id,
                        event.event_type.value,
                        event.lat,
                        event.lon,
                        int(datetime.utcnow().timestamp()),
                    ),
                )
                _id = cur.fetchone()[0]
                conn.commit()
        if idempotency_key and redis_client:
            await redis_client.setex(f"idem:{idempotency_key}", 24 * 3600, "1")
        return {"status": "accepted", "id": _id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/plan/{plan_id}")
async def get_plan(plan_id: int):
    try:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, date, direction, vehicle_id, student_sequence, eta_sequence, version, is_active FROM route_plan WHERE id=%s",
                    (plan_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="plan not found")
                return {
                    "id": row[0],
                    "date": row[1].isoformat() if row[1] else None,
                    "direction": row[2],
                    "vehicle_id": row[3],
                    "student_sequence": row[4],
                    "eta_sequence": [dt.isoformat() for dt in row[5]] if row[5] else None,
                    "version": row[6],
                    "is_active": row[7],
                }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/plan/{plan_id}/status")
async def get_plan_status(plan_id: int):
    try:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT vehicle_id, student_sequence FROM route_plan WHERE id=%s", (plan_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="plan not found")
                vehicle_id, student_sequence = row
                cur.execute(
                    "SELECT student_id, event_type, ts FROM stop_events WHERE trip_id=%s AND vehicle_id=%s ORDER BY ts ASC",
                    (str(plan_id), vehicle_id),
                )
                events = cur.fetchall() or []
        status_map = {sid: "pending" for sid in (student_sequence or [])}
        for sid, et, _ in events:
            if et == "ARRIVE":
                status_map[sid] = "arrived"
            elif et == "PICKED_UP":
                status_map[sid] = "picked_up"
            elif et in ("MANUAL_SKIP",):
                status_map[sid] = "skipped"
        stops = [{"student_id": sid, "status": status_map.get(sid, "pending")} for sid in (student_sequence or [])]
        return {"vehicle_id": vehicle_id, "stops": stops}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class NoShowReq(BaseModel):
    student_id: int
    date: str
    direction: str
    school_id: int


@app.post("/parent/no-show")
async def parent_no_show(req: NoShowReq):
    try:
        planned_pickup = time(8, 0)
        now = datetime.now().time()
        cutoff_time = (datetime.combine(datetime.today(), planned_pickup) - timedelta(minutes=60)).time()
        if now >= cutoff_time:
            return {"status": "late", "reopt": False}

        if not redis_client:
            raise HTTPException(status_code=500, detail="snapshot cache unavailable")
        snap_key = f"plan:snapshot:{req.date}:{req.direction}:{req.school_id}"
        snap_raw = await redis_client.get(snap_key)
        if not snap_raw:
            raise HTTPException(status_code=404, detail="snapshot not found")
        snap = json.loads(snap_raw)

        students = [s for s in snap["students"] if s["id"] != req.student_id]
        snap["students"] = students

        coords: List[Tuple[float, float]] = []
        for v in snap["vehicles"]:
            coords.append((v["start_lon"], v["start_lat"]))
        for s in students:
            coords.append((s["lon"], s["lat"]))
        coords.append((snap["school_lon"], snap["school_lat"]))
        durations = await matrix_cache.get_matrix(coords)
        reopt_req = OptimizeReq(**snap)
        problem_data = build_problem_data(reopt_req, durations)
        result = solver.solve_cvrptw_optimized(problem_data)
        if result["status"] == "NO_SOLUTION" or str(result["status"]).startswith("ERROR"):
            return {
                "status": "no_solution",
                "reopt": False,
                "solver_status": result["status"],
                "unassigned_students": result.get("unassigned_students", []),
            }
        plan_ids = save_route_plans(reopt_req, result["routes"], problem_data)

        await redis_client.setex(snap_key, 24 * 3600, json.dumps(snap))
        return {
            "status": "ok",
            "reopt": True,
            "new_plan_ids": plan_ids,
            "solver_status": result["status"],
            "unassigned_students": result.get("unassigned_students", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
