import json
from geometry import Vec3

MAX_BUILDINGS = 15
CELL_SIZE_M = 2.0
GROUND_CELLS = (30, 30)

CITY_PRESETS = {
    "Lahore": {"lat": 31.5204, "lon": 74.3587, "tz": 5.0},
    "Karachi": {"lat": 24.8607, "lon": 67.0011, "tz": 5.0},
    "Islamabad": {"lat": 33.6844, "lon": 73.0479, "tz": 5.0},
    "London": {"lat": 51.5074, "lon": -0.1278, "tz": 0.0},
    "New York": {"lat": 40.7128, "lon": -74.0060, "tz": -5.0},
    "Sydney": {"lat": -33.8688, "lon": 151.2093, "tz": 10.0},
}


class Building:
    """Represents an axis-aligned box building on the ground plane."""
    def __init__(
        self,
        id: int,
        label: str,
        position: Vec3,
        size: Vec3,
        color: str
    ):
        self.id = int(id)
        self.label = str(label)[:12]
        self.position = Vec3(position.x, position.y, 0.0)
        self.size = Vec3(size.x, size.y, size.z)
        self.color = str(color)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "position": {"x": self.position.x, "y": self.position.y, "z": self.position.z},
            "size": {"x": self.size.x, "y": self.size.y, "z": self.size.z},
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Building":
        pos = Vec3(d["position"]["x"], d["position"]["y"], d["position"]["z"])
        sz = Vec3(d["size"]["x"], d["size"]["y"], d["size"]["z"])
        return cls(d["id"], d["label"], pos, sz, d["color"])


class Scenario:
    """Site model holding buildings, geographical location, and revision state."""
    def __init__(
        self,
        name: str = "Untitled",
        buildings: list[Building] | None = None,
        ground_size: tuple[int, int] = GROUND_CELLS,
        lat: float = 31.5204,
        lon: float = 74.3587,
        tz_offset: float = 5.0,
        cell_size_m: float = CELL_SIZE_M,
        next_id: int = 1,
        revision: int = 0
    ):
        self.name = str(name)
        self.buildings = list(buildings) if buildings is not None else []
        self.ground_size = (int(ground_size[0]), int(ground_size[1]))
        self.lat = float(lat)
        self.lon = float(lon)
        self.tz_offset = float(tz_offset)
        self.cell_size_m = float(cell_size_m)
        self.next_id = int(next_id)
        self.revision = int(revision)

    def touch(self) -> None:
        """Increments revision number to mark cached calculations stale."""
        self.revision += 1

    def can_place(self, candidate: Building, ignore_id: int | None = None) -> bool:
        """Validates that candidate footprint is inside ground bounds and does not overlap others."""
        gw = self.ground_size[0] * self.cell_size_m
        gd = self.ground_size[1] * self.cell_size_m
        cx, cy = candidate.position.x, candidate.position.y
        cw, cd = candidate.size.x, candidate.size.y

        # Check bounds
        if cx < -1e-6 or cy < -1e-6 or (cx + cw) > (gw + 1e-6) or (cy + cd) > (gd + 1e-6):
            return False

        # Check overlaps
        for b in self.buildings:
            if ignore_id is not None and b.id == ignore_id:
                continue
            bx, by = b.position.x, b.position.y
            bw, bd = b.size.x, b.size.y
            if not (cx + cw <= bx + 1e-6 or cx >= bx + bw - 1e-6 or cy + cd <= by + 1e-6 or cy >= by + bd - 1e-6):
                return False
        return True

    def add_building(self, building: Building) -> bool:
        """Adds a building if within capacity and footprint is valid."""
        if len(self.buildings) >= MAX_BUILDINGS:
            return False
        if not self.can_place(building):
            return False
        if building.id <= 0 or any(b.id == building.id for b in self.buildings):
            building.id = self.next_id
            self.next_id += 1
        else:
            self.next_id = max(self.next_id, building.id + 1)
        self.buildings.append(building)
        self.touch()
        return True

    def remove_building(self, building_id: int) -> bool:
        """Removes a building by ID."""
        orig_len = len(self.buildings)
        self.buildings = [b for b in self.buildings if b.id != building_id]
        if len(self.buildings) < orig_len:
            self.touch()
            return True
        return False

    def move_building(self, building_id: int, new_pos: Vec3) -> bool:
        """Moves a building to a new snapped position if unobstructed."""
        target = None
        for b in self.buildings:
            if b.id == building_id:
                target = b
                break
        if target is None:
            return False

        temp = Building(target.id, target.label, new_pos, target.size, target.color)
        if self.can_place(temp, ignore_id=building_id):
            target.position = Vec3(new_pos.x, new_pos.y, 0.0)
            self.touch()
            return True
        return False

    def find_free_spot(self, size: Vec3) -> Vec3 | None:
        """Searches for an open spot on the ground grid for the given footprint."""
        nx, ny = self.ground_size
        cs = self.cell_size_m
        for j in range(ny):
            for i in range(nx):
                pos = Vec3(i * cs, j * cs, 0.0)
                temp = Building(-1, "Test", pos, size, "#FFFFFF")
                if self.can_place(temp):
                    return pos
        return None

    def occupied_mask(self) -> list[list[bool]]:
        """Returns 2D grid [j][i] indicating cells covered by buildings."""
        nx, ny = self.ground_size
        cs = self.cell_size_m
        mask = [[False for _ in range(nx)] for _ in range(ny)]
        for j in range(ny):
            cy = (j + 0.5) * cs
            for i in range(nx):
                cx = (i + 0.5) * cs
                for b in self.buildings:
                    bx, by = b.position.x, b.position.y
                    bw, bd = b.size.x, b.size.y
                    if bx <= cx <= bx + bw and by <= cy <= by + bd:
                        mask[j][i] = True
                        break
        return mask

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "buildings": [b.to_dict() for b in self.buildings],
            "ground_size": list(self.ground_size),
            "lat": self.lat,
            "lon": self.lon,
            "tz_offset": self.tz_offset,
            "cell_size_m": self.cell_size_m,
            "next_id": self.next_id,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        buildings = [Building.from_dict(b) for b in d.get("buildings", [])]
        return cls(
            name=d.get("name", "Untitled"),
            buildings=buildings,
            ground_size=tuple(d.get("ground_size", [30, 30])),
            lat=float(d.get("lat", 31.5204)),
            lon=float(d.get("lon", 74.3587)),
            tz_offset=float(d.get("tz_offset", 5.0)),
            cell_size_m=float(d.get("cell_size_m", 2.0)),
            next_id=int(d.get("next_id", 1)),
            revision=int(d.get("revision", 0)),
        )

    def clone(self) -> "Scenario":
        """Creates a deep copy of the scenario via JSON serialization."""
        return Scenario.from_dict(self.to_dict())


def create_demo_scenario() -> Scenario:
    """Creates the default demo scenario 'Courtyard' with 3 buildings."""
    b1 = Building(1, "Tower", Vec3(8.0, 8.0, 0.0), Vec3(8.0, 10.0, 18.0), "#D98E73")
    b2 = Building(2, "Block", Vec3(30.0, 12.0, 0.0), Vec3(10.0, 8.0, 9.0), "#8FB8DE")
    b3 = Building(3, "Annex", Vec3(14.0, 34.0, 0.0), Vec3(12.0, 8.0, 6.0), "#E6C65C")
    scen = Scenario(
        name="Courtyard",
        buildings=[b1, b2, b3],
        ground_size=(30, 30),
        lat=31.5204,
        lon=74.3587,
        tz_offset=5.0,
        cell_size_m=2.0,
        next_id=4,
        revision=1
    )
    return scen


def run_checks() -> list[tuple[str, bool, str]]:
    """Self-test checks for scenario model and operations."""
    results = []
    scen = create_demo_scenario()

    # 1. Check bounds and overlap rejection
    oob_b = Building(99, "OOB", Vec3(56.0, 56.0, 0.0), Vec3(10.0, 10.0, 10.0), "#FFFFFF")
    can_oob = scen.can_place(oob_b)
    overlap_b = Building(98, "Overlap", Vec3(8.0, 8.0, 0.0), Vec3(4.0, 4.0, 4.0), "#FFFFFF")
    can_overlap = scen.can_place(overlap_b)
    ok_place = (not can_oob) and (not can_overlap)
    results.append(("Scenario: Bounds & overlap rejection", ok_place, f"OOB={can_oob}, Overlap={can_overlap}"))

    # 2. Max buildings cap
    test_scen = scen.clone()
    for i in range(len(test_scen.buildings), MAX_BUILDINGS):
        spot = test_scen.find_free_spot(Vec3(2.0, 2.0, 5.0))
        if spot:
            test_scen.add_building(Building(i + 10, f"B{i}", spot, Vec3(2.0, 2.0, 5.0), "#8FB8DE"))
    excess_spot = test_scen.find_free_spot(Vec3(2.0, 2.0, 5.0))
    added_excess = False
    if excess_spot:
        added_excess = test_scen.add_building(Building(999, "Excess", excess_spot, Vec3(2.0, 2.0, 5.0), "#8FB8DE"))
    ok_cap = (len(test_scen.buildings) == MAX_BUILDINGS) and (not added_excess)
    results.append(("Scenario: 15 buildings maximum cap", ok_cap, f"Count={len(test_scen.buildings)}, excess={added_excess}"))

    # 3. JSON round-trip
    d = scen.to_dict()
    restored = Scenario.from_dict(d)
    ok_roundtrip = (
        len(restored.buildings) == len(scen.buildings)
        and restored.lat == scen.lat
        and restored.lon == scen.lon
        and restored.revision == scen.revision
    )
    results.append(("Scenario: JSON serialization round-trip", ok_roundtrip, f"Buildings={len(restored.buildings)}"))

    return results
