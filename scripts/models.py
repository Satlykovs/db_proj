from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar


@dataclass(frozen=True)
class AutoService:
    __table__: ClassVar[str] = "auto_services"
    name: str
    address: str
    city: str
    lifts_count: int
    specialization: str
    is_24_hours: bool
    open_time: str | None
    close_time: str | None


@dataclass(frozen=True)
class User:
    __table__: ClassVar[str] = "users"
    name: str
    phone: str
    email: str | None


@dataclass(frozen=True)
class Car:
    __table__: ClassVar[str] = "cars"
    user_id: int
    vin_number: str
    brand: str
    model: str
    manufacture_year: int
    mileage_km: int
    fuel_type: str


@dataclass(frozen=True)
class ServiceCategory:
    __table__: ClassVar[str] = "service_categories"
    name: str
    required_specialization: str


@dataclass(frozen=True)
class Service:
    __table__: ClassVar[str] = "services"
    category_id: int
    name: str
    base_price: Decimal
    standard_hours: Decimal
    warranty_months: int
    warranty_mileage_km: int


@dataclass
class Staff:
    __table__: ClassVar[str] = "staff"
    auto_service_id: int
    full_name: str
    specialization: str
    grade: int
    hourly_rate: Decimal
    review_count: int = 0
    review_sum: int = 0


@dataclass(frozen=True)
class Part:
    __table__: ClassVar[str] = "parts"
    sku: str
    name: str
    manufacturer: str
    base_price: Decimal


@dataclass(frozen=True)
class AutoServiceStorage:
    __table__: ClassVar[str] = "auto_service_storage"
    auto_service_id: int
    part_id: int
    stock_quantity: int
    min_stock: int
    selling_price: Decimal


@dataclass(frozen=True)
class Record:
    __table__: ClassVar[str] = "records"
    user_id: int
    auto_service_id: int
    car_id: int
    category_id: int
    scheduled_at: datetime
    status: str


@dataclass(frozen=True)
class WorkOrder:
    __table__: ClassVar[str] = "work_orders"
    record_id: int
    total_price: Decimal
    started_at: datetime
    ended_at: datetime | None
    status: str
    mileage_at_service: int


@dataclass(frozen=True)
class WorkOrderItem:
    __table__: ClassVar[str] = "work_order_items"
    work_order_id: int
    staff_id: int
    service_id: int
    price: Decimal
    hours: Decimal
    warranty_months: int
    warranty_mileage_km: int
    warranty_expires_at: datetime | None


@dataclass(frozen=True)
class WorkOrderPart:
    __table__: ClassVar[str] = "work_order_parts"
    work_order_id: int
    part_id: int
    quantity_used: int
    unit_price: Decimal


@dataclass(frozen=True)
class WarrantyClaim:
    __table__: ClassVar[str] = "warranty_claims"
    work_order_item_id: int
    claim_date: datetime
    reason: str
    status: str
    resolution: str | None
    resolved_at: datetime | None
    resolved_by: int | None


@dataclass(frozen=True)
class Review:
    __table__: ClassVar[str] = "reviews"
    work_order_id: int
    staff_id: int
    rating: int
    comment: str | None
    created_at: datetime
