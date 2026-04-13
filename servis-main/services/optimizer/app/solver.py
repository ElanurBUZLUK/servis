from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from typing import List, Dict, Optional
import numpy as np


class AdvancedCVRPTWSolver:
    """
    problem_data şeması:
    {
      "time_matrix": List[List[int]],
      "students": [
          {
              "id": 101,
              "loc_index": 5,
              "tw": (lo, hi),
              "demand": 1,
              "max_ride": 45*60,
              "service_time_sec": 60,
          }
      ],
      "vehicles": [
          {
              "id": 1,
              "capacity": 14,
              "start_index": 0,
              "end_index": SCHOOL_INDEX,
              "shift_window": (shift_lo, shift_hi)
          }
      ],
      "school_index": int,
      "school_arrival_deadline": Optional[int],
      "horizon": int,
      "drop_penalty": int,
      "max_wait_slack": int,
    }
    """

    def __init__(self):
        self.solver_configs = {
            "small": {
                "time_limit": 10,
                "first_solution": routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC,
                "metaheuristic": routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH,
            },
            "medium": {
                "time_limit": 30,
                "first_solution": routing_enums_pb2.FirstSolutionStrategy.SAVINGS,
                "metaheuristic": routing_enums_pb2.LocalSearchMetaheuristic.SIMULATED_ANNEALING,
            },
            "large": {
                "time_limit": 60,
                "first_solution": routing_enums_pb2.FirstSolutionStrategy.SAVINGS,
                "metaheuristic": routing_enums_pb2.LocalSearchMetaheuristic.TABU_SEARCH,
            },
        }

    def solve_cvrptw_optimized(self, problem_data: Dict, warm_start: Optional[List[List[int]]] = None) -> Dict:
        num_students = len(problem_data["students"])
        config = self._get_config_by_size(num_students)
        return self._solve_with_constraint_solver(problem_data, config, warm_start)

    def _get_config_by_size(self, n: int) -> Dict:
        if n < 50:
            return self.solver_configs["small"]
        if n < 150:
            return self.solver_configs["medium"]
        return self.solver_configs["large"]

    def _setup_routing_model(self, data: Dict):
        time_matrix = data["time_matrix"]
        n_nodes = len(time_matrix)
        starts = [v["start_index"] for v in data["vehicles"]]
        ends = [v.get("end_index", data.get("school_index", v["start_index"])) for v in data["vehicles"]]

        manager = pywrapcp.RoutingIndexManager(n_nodes, len(starts), starts, ends)
        routing = pywrapcp.RoutingModel(manager)

        service_times = np.zeros(n_nodes, dtype=int)
        for s in data["students"]:
            service_times[s["loc_index"]] = int(s.get("service_time_sec", 0))

        def time_cb(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel_sec = int(time_matrix[from_node][to_node])
            service_sec = int(service_times[from_node])
            return travel_sec + service_sec

        transit_idx = routing.RegisterTransitCallback(time_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
        return manager, routing, transit_idx

    def _add_time_dimension(self, routing, manager, transit_idx, data: Dict):
        horizon = int(data.get("horizon", 4 * 60 * 60))
        max_wait_slack = int(data.get("max_wait_slack", horizon))

        routing.AddDimension(
            transit_idx,
            max_wait_slack,
            horizon,
            False,
            "Time",
        )
        time_dim = routing.GetDimensionOrDie("Time")

        for s in data["students"]:
            node = s["loc_index"]
            lo, hi = s["tw"]
            idx = manager.NodeToIndex(node)
            time_dim.CumulVar(idx).SetRange(int(lo), int(hi))

        school_deadline = data.get("school_arrival_deadline")
        for v_idx, vehicle in enumerate(data["vehicles"]):
            start = routing.Start(v_idx)
            end = routing.End(v_idx)

            shift_lo, shift_hi = vehicle.get("shift_window", (0, horizon))
            shift_lo = max(0, int(shift_lo))
            shift_hi = min(horizon, int(shift_hi))

            time_dim.CumulVar(start).SetRange(shift_lo, shift_hi)
            end_hi = min(shift_hi, int(school_deadline)) if school_deadline is not None else shift_hi
            time_dim.CumulVar(end).SetRange(0, end_hi)

    def _add_capacity_dimension(self, routing, manager, data: Dict):
        n_nodes = len(data["time_matrix"])
        demands = np.zeros(n_nodes, dtype=int)
        for s in data["students"]:
            demands[s["loc_index"]] = int(s.get("demand", 1))

        demand_idx = routing.RegisterUnaryTransitCallback(lambda index: int(demands[manager.IndexToNode(index)]))
        capacities = [int(v["capacity"]) for v in data["vehicles"]]
        routing.AddDimensionWithVehicleCapacity(demand_idx, 0, capacities, True, "Capacity")

    def _add_disjunctions(self, routing, manager, data: Dict):
        base_penalty = int(data.get("drop_penalty", 10_000))
        for s in data["students"]:
            penalty = int(base_penalty * max(1, s.get("priority", 1)))
            routing.AddDisjunction([manager.NodeToIndex(s["loc_index"])], penalty)

    def _build_search_parameters(self, config: Dict):
        sp = pywrapcp.DefaultRoutingSearchParameters()
        sp.first_solution_strategy = config["first_solution"]
        sp.local_search_metaheuristic = config["metaheuristic"]
        sp.time_limit.FromSeconds(int(config["time_limit"]))
        return sp

    def _extract_solution(self, routing, manager, solution, data: Dict):
        time_dim = routing.GetDimensionOrDie("Time")
        capacity_dim = routing.GetDimensionOrDie("Capacity")

        routes = []
        for v in range(routing.vehicles()):
            idx = routing.Start(v)
            seq = []
            arrival_times = []
            cumulative_loads = []

            while True:
                seq.append(manager.IndexToNode(idx))
                arrival_times.append(solution.Value(time_dim.CumulVar(idx)))
                cumulative_loads.append(solution.Value(capacity_dim.CumulVar(idx)))
                if routing.IsEnd(idx):
                    break
                idx = solution.Value(routing.NextVar(idx))

            route_duration_sec = 0
            if arrival_times:
                route_duration_sec = max(0, int(arrival_times[-1] - arrival_times[0]))

            routes.append(
                {
                    "vehicle_index": v,
                    "sequence": seq,
                    "arrival_times": arrival_times,
                    "cumulative_loads": cumulative_loads,
                    "route_duration_sec": route_duration_sec,
                }
            )

        unassigned_students = []
        for s in data["students"]:
            idx = manager.NodeToIndex(s["loc_index"])
            if solution.Value(routing.NextVar(idx)) == idx:
                unassigned_students.append(s["id"])

        return routes, unassigned_students

    def _solve_with_constraint_solver(self, data: Dict, config: Dict, warm_start: Optional[List[List[int]]] = None) -> Dict:
        try:
            manager, routing, transit_idx = self._setup_routing_model(data)
            self._add_time_dimension(routing, manager, transit_idx, data)
            self._add_capacity_dimension(routing, manager, data)
            self._add_disjunctions(routing, manager, data)

            search_params = self._build_search_parameters(config)

            if warm_start:
                assignment = self._convert_warm_start(routing, manager, warm_start)
                solution = routing.SolveFromAssignmentWithParameters(assignment, search_params)
            else:
                solution = routing.SolveWithParameters(search_params)

            if solution:
                routes, unassigned_students = self._extract_solution(routing, manager, solution, data)
                return {
                    "routes": routes,
                    "objective_value": solution.ObjectiveValue(),
                    "solve_time_ms": solution.WallTime(),
                    "status": "SUCCESS" if not unassigned_students else "PARTIAL_SOLUTION",
                    "unassigned_students": unassigned_students,
                }

            return {
                "routes": [],
                "objective_value": None,
                "solve_time_ms": None,
                "status": "NO_SOLUTION",
                "unassigned_students": [s["id"] for s in data["students"]],
            }
        except Exception as e:
            return {
                "routes": [],
                "objective_value": None,
                "solve_time_ms": None,
                "status": f"ERROR: {str(e)}",
                "unassigned_students": [s["id"] for s in data.get("students", [])],
            }

    def _convert_warm_start(self, routing, manager, warm_routes: List[List[int]]):
        routes_as_indices = []
        for route in warm_routes:
            route_indices = []
            for node in route:
                route_indices.append(manager.NodeToIndex(node))
            routes_as_indices.append(route_indices)
        return routing.ReadAssignmentFromRoutes(routes_as_indices, True)
