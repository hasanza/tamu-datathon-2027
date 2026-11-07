"""Task 1.1: load the organizers' CSV tables into typed, indexed, immutable records.

Today is Monday 2027-03-08 = working-day index 0. The calendar covers idx -10..19, Mon-Fri only.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
KIT_DIR = REPO_ROOT / "hack_the_highway"
DATA_DIR = KIT_DIR / "data"
TODAY = date(2027, 3, 8)
FIRST_IDX, LAST_IDX = -10, 19
TIER_RANK = {"Platinum": 0, "Gold": 1, "Standard": 2}
LOANER_TIERS = ("Platinum", "Gold")


@dataclass(frozen=True, slots=True)
class Plant:
    plant_id: str
    name: str
    city: str
    slots_per_day: int


@dataclass(frozen=True, slots=True)
class Part:
    part_id: str
    name: str
    category: str


@dataclass(frozen=True, slots=True)
class Supplier:
    supplier_id: str
    name: str
    city: str


@dataclass(frozen=True, slots=True)
class Shipment:
    shipment_id: str
    supplier_id: str
    part_id: str
    plant_id: str
    eta_date: date
    covers_days: int


@dataclass(frozen=True, slots=True)
class ProductionOrder:
    id: str
    plant_id: str
    build_date: date
    model: str
    units: int


@dataclass(frozen=True, slots=True)
class CustomerOrder:
    id: str
    production_order_id: str
    dealer_id: str
    customer_id: str
    model: str
    promised_date: date


@dataclass(frozen=True, slots=True)
class Customer:
    customer_id: str
    name: str
    tier: str


@dataclass(frozen=True, slots=True)
class Dealer:
    dealer_id: str
    name: str
    city: str
    region: str
    transit_days: int


@dataclass(frozen=True, slots=True)
class Lot:
    lot_id: str
    part_id: str
    supplier_id: str
    plant_id: str
    first_build_date: date
    last_build_date: date


@dataclass(frozen=True, slots=True)
class Vehicle:
    vin: str
    production_order_id: str
    model: str
    plant_id: str
    build_date: date
    dealer_id: str
    status: str
    customer_id: str | None


@dataclass(frozen=True, slots=True)
class Alias:
    alias: str
    entity_type: str
    entity_id: str


class Calendar:
    """Working-day index <-> date. Weekends and anything outside 2027-02-22..2027-04-02 are not working days."""

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._by_idx = {int(r["day_index"]): date.fromisoformat(r["date"]) for r in rows}
        self._by_date = {d: i for i, d in self._by_idx.items()}

    def idx(self, d: date) -> int:
        try:
            return self._by_date[d]
        except KeyError:
            raise ValueError(f"{d} is not a working day in the calendar") from None

    def date_of(self, idx: int) -> date:
        return self._by_idx[idx]

    def is_working_day(self, d: date) -> bool:
        return d in self._by_date

    def next_working_day(self, d: date) -> date | None:
        """First working day strictly after `d`, or None if the calendar ends first."""
        later = [x for x in self._by_date if x > d]
        return min(later) if later else None

    def working_days(self, start: date, end: date) -> list[date]:
        return sorted(x for x in self._by_date if start <= x <= end)


@dataclass
class World:
    calendar: Calendar
    plants: dict[str, Plant]
    plant_models: dict[str, frozenset[str]]
    builders: dict[str, frozenset[str]]  # model -> plants that build it
    models: dict[str, str]  # model -> segment
    parts: dict[str, Part]
    bom: dict[str, frozenset[str]]  # model -> parts
    suppliers: dict[str, Supplier]
    shipments: dict[str, Shipment]
    production_orders: dict[str, ProductionOrder]
    customer_orders: dict[str, CustomerOrder]
    customers: dict[str, Customer]
    dealers: dict[str, Dealer]
    loaner_pool: dict[str, int]
    lots: dict[str, Lot]
    vehicles: dict[str, Vehicle]
    aliases: list[Alias]
    cos_by_po: dict[str, list[CustomerOrder]] = field(default_factory=dict)
    vehicles_by_po: dict[str, list[Vehicle]] = field(default_factory=dict)

    def is_future(self, po: ProductionOrder) -> bool:
        return po.build_date >= TODAY


def _read(data_dir: Path, name: str) -> list[dict[str, str]]:
    with open(data_dir / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _d(text: str) -> date:
    return date.fromisoformat(text)


@lru_cache(maxsize=2)
def _load(data_dir: str) -> World:
    p = Path(data_dir)
    rd = lambda n: _read(p, n)  # noqa: E731
    plants = {
        r["plant_id"]: Plant(r["plant_id"], r["name"], r["city"], int(r["slots_per_day"])) for r in rd("plants.csv")
    }
    pm: dict[str, set[str]] = defaultdict(set)
    builders: dict[str, set[str]] = defaultdict(set)
    for r in rd("plant_models.csv"):
        pm[r["plant_id"]].add(r["model"])
        builders[r["model"]].add(r["plant_id"])
    bom: dict[str, set[str]] = defaultdict(set)
    for r in rd("bom.csv"):
        bom[r["model"]].add(r["part_id"])
    pos = {
        r["production_order_id"]: ProductionOrder(
            r["production_order_id"], r["plant_id"], _d(r["build_date"]), r["model"], int(r["units"])
        )
        for r in rd("production_orders.csv")
    }
    cos = {
        r["customer_order_id"]: CustomerOrder(
            r["customer_order_id"],
            r["production_order_id"],
            r["dealer_id"],
            r["customer_id"],
            r["model"],
            _d(r["promised_date"]),
        )
        for r in rd("customer_orders.csv")
    }
    vehicles = {
        r["vin"]: Vehicle(
            r["vin"],
            r["production_order_id"],
            r["model"],
            r["plant_id"],
            _d(r["build_date"]),
            r["dealer_id"],
            r["status"],
            r["customer_id"] or None,
        )
        for r in rd("finished_vehicles.csv")
    }
    world = World(
        calendar=Calendar(rd("calendar.csv")),
        plants=plants,
        plant_models={k: frozenset(v) for k, v in pm.items()},
        builders={k: frozenset(v) for k, v in builders.items()},
        models={r["model"]: r["segment"] for r in rd("models.csv")},
        parts={r["part_id"]: Part(r["part_id"], r["name"], r["category"]) for r in rd("parts.csv")},
        bom={k: frozenset(v) for k, v in bom.items()},
        suppliers={r["supplier_id"]: Supplier(r["supplier_id"], r["name"], r["city"]) for r in rd("suppliers.csv")},
        shipments={
            r["shipment_id"]: Shipment(
                r["shipment_id"],
                r["supplier_id"],
                r["part_id"],
                r["plant_id"],
                _d(r["eta_date"]),
                int(r["covers_days"]),
            )
            for r in rd("inbound_shipments.csv")
        },
        production_orders=pos,
        customer_orders=cos,
        customers={r["customer_id"]: Customer(r["customer_id"], r["name"], r["tier"]) for r in rd("customers.csv")},
        dealers={
            r["dealer_id"]: Dealer(r["dealer_id"], r["name"], r["city"], r["region"], int(r["transit_days"]))
            for r in rd("dealers.csv")
        },
        loaner_pool={r["dealer_id"]: int(r["loaners_available"]) for r in rd("loaners.csv")},
        lots={
            r["lot_id"]: Lot(
                r["lot_id"],
                r["part_id"],
                r["supplier_id"],
                r["plant_id"],
                _d(r["first_build_date"]),
                _d(r["last_build_date"]),
            )
            for r in rd("part_lots.csv")
        },
        vehicles=vehicles,
        aliases=[Alias(r["alias"], r["entity_type"], r["entity_id"]) for r in rd("aliases.csv")],
    )
    by_po: dict[str, list[CustomerOrder]] = defaultdict(list)
    for co in cos.values():
        by_po[co.production_order_id].append(co)
    veh_po: dict[str, list[Vehicle]] = defaultdict(list)
    for v in vehicles.values():
        veh_po[v.production_order_id].append(v)
    world.cos_by_po = {k: sorted(v, key=lambda c: c.id) for k, v in by_po.items()}
    world.vehicles_by_po = {k: sorted(v, key=lambda x: x.vin) for k, v in veh_po.items()}
    return world


def load_world(data_dir: Path | str = DATA_DIR) -> World:
    """Load (and cache) the world. The returned object is shared: treat it as read-only."""
    return _load(str(Path(data_dir).resolve()))
