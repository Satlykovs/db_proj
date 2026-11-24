import itertools
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from catalogs import (
    CAR_CATALOG,
    CATEGORY_PART_PREFIXES,
    NEGATIVE_REVIEWS,
    PART_MANUFACTURERS,
    PART_TEMPLATES,
    POSITIVE_REVIEWS,
    SERVICE_CATEGORIES,
    SERVICES_CATALOG,
    WARRANTY_LOGIC,
)
from mimesis import Generic
from mimesis.enums import Gender
from mimesis.locales import Locale
from models import (
    AutoService,
    AutoServiceStorage,
    Car,
    Part,
    Record,
    Review,
    Service,
    ServiceCategory,
    Staff,
    User,
    WarrantyClaim,
    WorkOrder,
    WorkOrderItem,
    WorkOrderPart,
)
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from sql_writer import SqlWriter


@dataclass(frozen=True)
class BranchConfig:
    city: str
    district: str
    specialization: str
    lifts: int
    is_24h: bool = False
    premium_share: float = 0.20


@dataclass(frozen=True)
class SeedConfig:
    seed: int = 67
    brand_name: str = "AutoService Pro"
    now: datetime = datetime.now(timezone.utc).replace(hour=15, minute=0, second=0, microsecond=0)

    users_count: int = 140
    max_cars_per_user: int = 2
    min_car_year: int = 2005
    max_car_year: int = 2026

    staff_per_spec_in_branch: int = 2
    max_staff_orders_per_day: int = 8

    orders_count: int = 1800
    recent_orders_share: float = 0.55
    recent_window_days: int = 20
    stale_car_share: float = 0.15
    warranty_claims_count: int = 120

    branches: tuple[BranchConfig, ...] = (
        BranchConfig("Москва", "Север", "german", lifts=6, is_24h=True, premium_share=0.75),
        BranchConfig("Москва", "Юг", "japanese", lifts=5, premium_share=0.20),
        BranchConfig("Москва", "Центр", "electric", lifts=5, premium_share=0.75),
        BranchConfig("Санкт-Петербург", "Приморский", "universal", lifts=6, is_24h=True),
        BranchConfig("Казань", "Вахитовский", "universal", lifts=4, premium_share=0.15),
        BranchConfig("Екатеринбург", "Чкаловский", "universal", lifts=4, premium_share=0.15),
    )


@dataclass
class _CarMeta:
    id: int
    user_id: int
    service_spec: str
    age_days: int
    annual_km: int
    current_mileage: int
    is_stale: bool


@dataclass
class _ServiceMeta:
    id: int
    category_id: int
    category_name: str
    required_spec: str
    base_price: Decimal
    standard_hours: Decimal
    warranty_months: int
    warranty_mileage_km: int


@dataclass
class _StaffMeta:
    id: int
    model: Staff


class SeedGenerator:
    VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    SPECIALIZATIONS = ("motorist", "electrician", "bodyworker", "diagnostician")
    EXPENSIVE_CATEGORIES = frozenset(
        {"Ремонт двигателя", "Кузовной ремонт", "Ремонт электрооборудования"}
    )
    ANNUAL_KM_PROFILES = (10_000, 15_000, 22_000, 45_000)
    GRADE_RATING_WEIGHTS: dict[int, tuple[int, ...]] = {
        3: (12, 15, 23, 30, 20),
        4: (5, 8, 15, 32, 40),
        5: (3, 3, 6, 18, 70),
        6: (1, 1, 3, 10, 85),
    }

    def __init__(self, writer: SqlWriter, config: SeedConfig | None = None):
        self.cfg = config or SeedConfig()
        self.writer = writer
        self.g = Generic(locale=Locale.RU, seed=self.cfg.seed)
        self.rng = random.Random(self.cfg.seed)

        self._seq = {
            name: itertools.count(1)
            for name in (
                "service",
                "user",
                "car",
                "category",
                "srv_item",
                "staff",
                "part",
                "record",
                "wo",
                "wo_item",
            )
        }

        self._branch_by_id: dict[int, BranchConfig] = {}
        self._branches_by_spec: dict[str, list[int]] = {}
        self._all_branch_ids: list[int] = []
        self._cars: list[_CarMeta] = []
        self._categories: list[tuple[int, str, str]] = []
        self._services_by_cat: dict[int, list[_ServiceMeta]] = {}
        self._staff_by_branch_spec: dict[tuple[int, str], list[_StaffMeta]] = {}
        self._parts_storage: dict[int, list[tuple[int, Decimal, str]]] = {}

        self._used_vins: set[str] = set()
        self._used_phones: set[str] = set()
        self._branch_hour_lifts: dict[tuple[int, date, int], int] = {}
        self._staff_day_count: dict[tuple[int, date], int] = {}

    def run(self):
        console = Console()
        self.writer.write_comment("=== AUTO-GENERATED SEED DATA ===")

        steps = [
            ("[1/6] Генерация филиалов автосервиса", self._gen_auto_services),
            (
                f"[2/6] Генерация клиентов ({self.cfg.users_count}) и авто",
                self._gen_users_and_cars,
            ),
            ("[3/6] Заполнение категорий и прайса услуг", self._gen_catalog_entities),
            ("[4/6] Формирование штата мастеров", self._prepare_staff),
            ("[5/6] Наполнение каталога запчастей и складов", self._gen_parts_and_storage),
        ]

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            main_task = progress.add_task("Инициализация...", total=6)
            for desc, fn in steps:
                progress.update(main_task, description=desc)
                fn()
                progress.advance(main_task)

            progress.update(main_task, description="[6/6] Эмуляция (заказы, отзывы, гарантии)")
            wf_stats = self._gen_workflow(progress)
            progress.advance(main_task)
            progress.update(main_task, description="[bold green]Генерация завершена!")

        table = Table(title=f"Сводка генерации (seed={self.cfg.seed})")
        table.add_column("Сущность", style="cyan")
        table.add_column("Строк", justify="right", style="green")
        table.add_row("Филиалы (auto_services)", str(len(self._all_branch_ids)))
        table.add_row("Клиенты (users)", str(self.cfg.users_count))
        table.add_row("Автомобили (cars)", str(len(self._cars)))
        table.add_row(
            "Мастера (staff)", str(sum(len(v) for v in self._staff_by_branch_spec.values()))
        )
        for label, count in wf_stats.items():
            table.add_row(label, str(count))
        console.print(table)

    def _gen_auto_services(self):
        self.writer.write_comment("1. Автосервисы")
        models: list[AutoService] = []
        for branch in self.cfg.branches:
            b_id = next(self._seq["service"])
            self._branch_by_id[b_id] = branch
            self._all_branch_ids.append(b_id)
            self._branches_by_spec.setdefault(branch.specialization, []).append(b_id)
            models.append(
                AutoService(
                    name=f"{self.cfg.brand_name} {branch.city} ({branch.district})",
                    address=(
                        f"г. {branch.city}, {self.g.address.street_name()}, "
                        f"д. {self.rng.randint(1, 140)}"
                    ),
                    city=branch.city,
                    lifts_count=branch.lifts,
                    specialization=branch.specialization,
                    is_24_hours=branch.is_24h,
                    open_time=None if branch.is_24h else "08:00:00",
                    close_time=None if branch.is_24h else "21:00:00",
                )
            )
        self.writer.insert(models)

    def _gen_users_and_cars(self):
        self.writer.write_comment("2. Клиенты и автомобили")
        users: list[User] = []
        cars: list[Car] = []
        for _ in range(self.cfg.users_count):
            u_id = next(self._seq["user"])
            users.append(
                User(
                    name=self._full_name(),
                    phone=self._unique_phone(),
                    email=f"user{u_id}_{self.g.person.email()}",
                )
            )
            for _ in range(self.rng.randint(1, self.cfg.max_cars_per_user)):
                c_id = next(self._seq["car"])
                spec = self.rng.choice(CAR_CATALOG)
                year = self.rng.randint(self.cfg.min_car_year, self.cfg.max_car_year)
                age_years = max(0, self.cfg.now.year - year)
                age_days = max(60, age_years * 365 + self.rng.randint(30, 300))
                annual_km = self.rng.choice(self.ANNUAL_KM_PROFILES)
                mileage = max(1_500, int((age_days / 365.0) * annual_km))
                is_stale = age_years >= 2 and self.rng.random() < self.cfg.stale_car_share

                self._cars.append(
                    _CarMeta(c_id, u_id, spec.service_spec, age_days, annual_km, mileage, is_stale)
                )
                cars.append(
                    Car(
                        user_id=u_id,
                        vin_number=self._unique_vin(),
                        brand=spec.brand,
                        model=self.rng.choice(spec.models),
                        manufacture_year=year,
                        mileage_km=mileage,
                        fuel_type=self.rng.choice(spec.fuel_types),
                    )
                )
        self.writer.insert(users)
        self.writer.insert(cars)

    def _gen_catalog_entities(self):
        self.writer.write_comment("3. Категории и прайс-лист услуг")
        cat_models: list[ServiceCategory] = []
        cat_name_to_id: dict[str, int] = {}
        cat_name_to_spec: dict[str, str] = {}

        for name, req_spec in SERVICE_CATEGORIES:
            c_id = next(self._seq["category"])
            cat_name_to_id[name] = c_id
            cat_name_to_spec[name] = req_spec
            self._categories.append((c_id, name, req_spec))
            cat_models.append(ServiceCategory(name=name, required_specialization=req_spec))

        srv_models: list[Service] = []
        for s in SERVICES_CATALOG:
            s_id = next(self._seq["srv_item"])
            c_id = cat_name_to_id[s.category]
            meta = _ServiceMeta(
                id=s_id,
                category_id=c_id,
                category_name=s.category,
                required_spec=cat_name_to_spec[s.category],
                base_price=s.base_price,
                standard_hours=s.standard_hours,
                warranty_months=s.warranty_months,
                warranty_mileage_km=s.warranty_mileage_km,
            )
            self._services_by_cat.setdefault(c_id, []).append(meta)
            srv_models.append(
                Service(
                    category_id=c_id,
                    name=s.name,
                    base_price=s.base_price,
                    standard_hours=s.standard_hours,
                    warranty_months=s.warranty_months,
                    warranty_mileage_km=s.warranty_mileage_km,
                )
            )
        self.writer.insert(cat_models)
        self.writer.insert(srv_models)

    def _prepare_staff(self):
        for b_id in self._all_branch_ids:
            for spec in self.SPECIALIZATIONS:
                grades = [6, 3] if self.cfg.staff_per_spec_in_branch == 2 else None
                for idx in range(self.cfg.staff_per_spec_in_branch):
                    st_id = next(self._seq["staff"])
                    grade = grades[idx] if grades else self.rng.randint(3, 6)
                    staff_obj = Staff(
                        auto_service_id=b_id,
                        full_name=self._full_name(),
                        specialization=spec,
                        grade=grade,
                        hourly_rate=Decimal(1200 + grade * 350),
                    )
                    self._staff_by_branch_spec.setdefault((b_id, spec), []).append(
                        _StaffMeta(id=st_id, model=staff_obj)
                    )

    def _gen_parts_and_storage(self):
        self.writer.write_comment("4. Справочник запчастей и остатки на складах")
        parts: list[Part] = []
        storage: list[AutoServiceStorage] = []
        part_entries: list[tuple[int, Decimal, str]] = []

        for tpl in PART_TEMPLATES:
            for mfg in PART_MANUFACTURERS:
                p_id = next(self._seq["part"])
                sku = f"{tpl.code}-{mfg[:3].upper()}-{p_id:03d}"
                price = Decimal(self.rng.randint(tpl.min_price, tpl.max_price))
                part_entries.append((p_id, price, tpl.code))
                parts.append(
                    Part(sku=sku, name=f"{tpl.name} ({mfg})", manufacturer=mfg, base_price=price)
                )

        for b_id in self._all_branch_ids:
            for p_id, base_price, code in part_entries:
                min_stock = self.rng.randint(3, 10)
                stock_qty = (
                    self.rng.randint(0, min_stock - 1)
                    if self.rng.random() < 0.15
                    else self.rng.randint(min_stock, min_stock + 25)
                )
                sell_price = (base_price * Decimal("1.25")).quantize(Decimal("0.01"))
                self._parts_storage.setdefault(b_id, []).append((p_id, sell_price, code))
                storage.append(
                    AutoServiceStorage(
                        auto_service_id=b_id,
                        part_id=p_id,
                        stock_quantity=stock_qty,
                        min_stock=min_stock,
                        selling_price=sell_price,
                    )
                )
        self.writer.insert(parts)
        self.writer.insert(storage)

    def _gen_workflow(self, progress: Progress | None = None) -> dict[str, int]:
        wf_task = (
            progress.add_task("  └─ Обработка визитов...", total=self.cfg.orders_count)
            if progress
            else None
        )
        records: list[Record] = []
        work_orders: list[WorkOrder] = []
        wo_items: list[WorkOrderItem] = []
        wo_parts: list[WorkOrderPart] = []
        reviews: list[Review] = []
        warranty_claims: list[WarrantyClaim] = []
        eligible_for_warranty: list[tuple[int, str, str, datetime, datetime, int]] = []

        for _ in range(self.cfg.orders_count):
            if progress and wf_task is not None:
                progress.advance(wf_task)

            car = self.rng.choice(self._cars)
            branch_id = self._pick_branch(car.service_spec)
            branch = self._branch_by_id[branch_id]
            cat_id, cat_name, req_spec = self._pick_category(branch)

            max_past_days = max(30, car.age_days - 5)
            recent_cap = min(self.cfg.recent_window_days, max_past_days)
            history_cap = min(max_past_days, 365)

            if car.is_stale:
                low = min(375, max_past_days)
                high = max(low, min(max_past_days, 730))
                days_ago = self.rng.randint(low, high)
            elif (
                self.rng.random() < self.cfg.recent_orders_share
                or history_cap <= self.cfg.recent_window_days
            ):
                days_ago = self.rng.randint(1, max(1, recent_cap))
            else:
                days_ago = self.rng.randint(self.cfg.recent_window_days + 1, history_cap)

            if not car.is_stale and self.rng.random() < 0.10:
                next(self._seq["record"])
                future_dt = self._pick_slot(
                    branch_id,
                    (self.cfg.now + timedelta(days=self.rng.randint(1, 14))).date(),
                    branch.is_24h,
                )
                status = self.rng.choice(["planned", "cancelled"])
                records.append(Record(car.user_id, branch_id, car.id, cat_id, future_dt, status))
                continue

            visit_date = (self.cfg.now - timedelta(days=days_ago)).date()
            scheduled_at = self._pick_slot(branch_id, visit_date, branch.is_24h)
            chosen_staff = self._pick_staff(branch_id, req_spec, scheduled_at.date())
            if chosen_staff is None:
                visit_date = visit_date - timedelta(days=self.rng.randint(1, 3))
                scheduled_at = self._pick_slot(branch_id, visit_date, branch.is_24h)
                chosen_staff = self._pick_staff(branch_id, req_spec, scheduled_at.date())
                if chosen_staff is None:
                    continue

            rec_id = next(self._seq["record"])
            wo_id = next(self._seq["wo"])
            staff_id, staff_obj = chosen_staff.id, chosen_staff.model

            self._branch_hour_lifts[(branch_id, scheduled_at.date(), scheduled_at.hour)] = (
                self._branch_hour_lifts.get((branch_id, scheduled_at.date(), scheduled_at.hour), 0)
                + 1
            )
            self._staff_day_count[(staff_id, scheduled_at.date())] = (
                self._staff_day_count.get((staff_id, scheduled_at.date()), 0) + 1
            )

            started_at = scheduled_at + timedelta(minutes=self.rng.randint(5, 25))
            available_srvs = self._services_by_cat[cat_id]
            items_k = (
                self.rng.randint(2, 3)
                if self.rng.random() < branch.premium_share
                else self.rng.randint(1, 2)
            )
            chosen_srvs = self.rng.sample(available_srvs, k=min(len(available_srvs), items_k))

            total_price = Decimal("0.00")
            total_hours = Decimal("0.00")
            pending_items: list[tuple[int, _ServiceMeta, Decimal, Decimal]] = []

            for srv in chosen_srvs:
                item_id = next(self._seq["wo_item"])
                efficiency_factor = Decimal(str(self.rng.uniform(0.80, 1.25)))
                fact_hours = (srv.standard_hours * efficiency_factor).quantize(Decimal("0.01"))
                item_price = (srv.base_price + staff_obj.hourly_rate * srv.standard_hours).quantize(
                    Decimal("0.01")
                )
                total_price += item_price
                total_hours += fact_hours
                pending_items.append((item_id, srv, item_price, fact_hours))

            prefixes = CATEGORY_PART_PREFIXES.get(cat_name, ())
            if prefixes:
                matching_parts = [
                    (pid, price)
                    for pid, price, code in self._parts_storage[branch_id]
                    if code.startswith(prefixes)
                ]
                parts_k = (
                    self.rng.randint(2, 3)
                    if self.rng.random() < branch.premium_share
                    else self.rng.randint(1, 2)
                )
                for part_id, unit_price in self.rng.sample(
                    matching_parts, k=min(len(matching_parts), parts_k)
                ):
                    qty = self.rng.randint(1, 2)
                    total_price += unit_price * qty
                    wo_parts.append(
                        WorkOrderPart(
                            work_order_id=wo_id,
                            part_id=part_id,
                            quantity_used=qty,
                            unit_price=unit_price,
                        )
                    )

            est_ended_at = started_at + timedelta(hours=max(1, int(total_hours)))
            can_finish = est_ended_at <= self.cfg.now
            is_finished = can_finish and (days_ago > 2 or self.rng.random() < 0.70)

            if is_finished:
                ended_at: datetime | None = est_ended_at
                wo_status = "ready" if days_ago <= 3 and self.rng.random() < 0.25 else "issued"
                rec_status = "done"
            else:
                ended_at = None
                wo_status = self.rng.choice(["accepted", "in_progress", "waiting_parts"])
                rec_status = "confirmed"

            for item_id, srv, item_price, fact_hours in pending_items:
                w_expires = (
                    ended_at + timedelta(days=30 * srv.warranty_months)
                    if ended_at is not None and srv.warranty_months > 0
                    else None
                )
                wo_items.append(
                    WorkOrderItem(
                        work_order_id=wo_id,
                        staff_id=staff_id,
                        service_id=srv.id,
                        price=item_price,
                        hours=fact_hours,
                        warranty_months=srv.warranty_months,
                        warranty_mileage_km=srv.warranty_mileage_km,
                        warranty_expires_at=w_expires,
                    )
                )
                if (
                    ended_at is not None
                    and w_expires is not None
                    and min(w_expires, self.cfg.now - timedelta(days=3))
                    > ended_at + timedelta(days=3)
                ):
                    eligible_for_warranty.append(
                        (item_id, cat_name, req_spec, ended_at, w_expires, branch_id)
                    )

            records.append(Record(car.user_id, branch_id, car.id, cat_id, scheduled_at, rec_status))

            km_delta = int((days_ago / 365.0) * car.annual_km)
            mileage_at_srv = max(100, car.current_mileage - km_delta)

            work_orders.append(
                WorkOrder(
                    record_id=rec_id,
                    total_price=total_price,
                    started_at=started_at,
                    ended_at=ended_at,
                    status=wo_status,
                    mileage_at_service=mileage_at_srv,
                )
            )

            if ended_at is not None and self.rng.random() < 0.65:
                weights = self.GRADE_RATING_WEIGHTS[staff_obj.grade]
                rating = self.rng.choices([1, 2, 3, 4, 5], weights=weights)[0]
                comment = (
                    self.rng.choice(POSITIVE_REVIEWS)
                    if rating >= 4
                    else self.rng.choice(NEGATIVE_REVIEWS)
                )
                staff_obj.review_count += 1
                staff_obj.review_sum += rating
                review_dt = min(
                    ended_at + timedelta(hours=self.rng.randint(2, 48)),
                    self.cfg.now,
                )
                reviews.append(
                    Review(
                        work_order_id=wo_id,
                        staff_id=staff_id,
                        rating=rating,
                        comment=comment,
                        created_at=review_dt,
                    )
                )

        for item_id, cat_name, req_spec, ended_at, w_expires, branch_id in self.rng.sample(
            eligible_for_warranty,
            k=min(len(eligible_for_warranty), self.cfg.warranty_claims_count),
        ):
            reasons = WARRANTY_LOGIC.get(
                cat_name, [("Дефект после ремонта", "Устранено по гарантии")]
            )
            reason_txt, resolution_txt = self.rng.choice(reasons)
            max_claim_dt = min(w_expires, self.cfg.now - timedelta(days=3))
            span_days = max(1, (max_claim_dt - ended_at).days - 3)
            claim_dt = ended_at + timedelta(days=self.rng.randint(3, min(45, 3 + span_days)))
            is_closed = self.rng.random() < 0.75
            resolved_dt = min(claim_dt + timedelta(days=2), self.cfg.now)

            specialist_id = max(
                self._staff_by_branch_spec[(branch_id, req_spec)],
                key=lambda m: m.model.grade,
            ).id
            warranty_claims.append(
                WarrantyClaim(
                    work_order_item_id=item_id,
                    claim_date=claim_dt,
                    reason=reason_txt,
                    status="closed" if is_closed else "in_progress",
                    resolution=resolution_txt if is_closed else None,
                    resolved_at=resolved_dt if is_closed else None,
                    resolved_by=specialist_id if is_closed else None,
                )
            )

        self.writer.write_comment("5. Мастера сервисных центров")
        all_staff = [
            meta.model for staff_list in self._staff_by_branch_spec.values() for meta in staff_list
        ]
        self.writer.insert(all_staff)

        self.writer.write_comment("6. Записи, заказ-наряды, работы, запчасти, отзывы и гарантии")
        self.writer.insert(records)
        self.writer.insert(work_orders)
        self.writer.insert(wo_items)
        self.writer.insert(wo_parts)
        self.writer.insert(reviews)
        self.writer.insert(warranty_claims)

        return {
            "Записи (records)": len(records),
            "Заказы-наряды (work_orders)": len(work_orders),
            "Позиции работ (work_order_items)": len(wo_items),
            "Запчасти в заказах (work_order_parts)": len(wo_parts),
            "Отзывы (reviews)": len(reviews),
            "Гарантия (warranty_claims)": len(warranty_claims),
        }

    def _pick_branch(self, car_spec: str) -> int:
        specialized = self._branches_by_spec.get(car_spec, [])
        universal = self._branches_by_spec.get("universal", [])
        pool = specialized + universal
        if not pool:
            return self.rng.choice(self._all_branch_ids)
        weights = [3 if b_id in specialized else 1 for b_id in pool]
        return self.rng.choices(pool, weights=weights, k=1)[0]

    def _pick_category(self, branch: BranchConfig) -> tuple[int, str, str]:
        want_expensive = self.rng.random() < branch.premium_share
        pool = [
            cat
            for cat in self._categories
            if (cat[1] in self.EXPENSIVE_CATEGORIES) == want_expensive
        ]
        return self.rng.choice(pool or self._categories)

    def _pick_slot(self, branch_id: int, visit_date: date, is_24h: bool) -> datetime:
        branch = self._branch_by_id[branch_id]
        hours_pool = list(range(24)) if is_24h else list(range(8, 20))
        weights = [3 if h in (9, 10, 11, 17, 18, 19) else 1 for h in hours_pool]
        for _ in range(10):
            hour = self.rng.choices(hours_pool, weights=weights, k=1)[0]
            if self._branch_hour_lifts.get((branch_id, visit_date, hour), 0) < branch.lifts:
                return datetime(
                    visit_date.year,
                    visit_date.month,
                    visit_date.day,
                    hour,
                    self.rng.choice([0, 15, 30, 45]),
                    tzinfo=timezone.utc,
                )
        hour = self.rng.choice(hours_pool)
        return datetime(
            visit_date.year,
            visit_date.month,
            visit_date.day,
            hour,
            self.rng.choice([0, 15, 30, 45]),
            tzinfo=timezone.utc,
        )

    def _pick_staff(self, branch_id: int, req_spec: str, visit_date: date) -> _StaffMeta | None:
        candidates = [
            m
            for m in self._staff_by_branch_spec[(branch_id, req_spec)]
            if self._staff_day_count.get((m.id, visit_date), 0) < self.cfg.max_staff_orders_per_day
        ]
        if not candidates:
            return None
        weights = [(m.model.grade - 2) ** 2 for m in candidates]
        return self.rng.choices(candidates, weights=weights, k=1)[0]

    def _unique_vin(self) -> str:
        while True:
            vin = "".join(self.rng.choices(self.VIN_CHARS, k=17))
            if vin not in self._used_vins:
                self._used_vins.add(vin)
                return vin

    def _unique_phone(self) -> str:
        while True:
            phone = self.g.person.phone_number(mask="+7 (9##) ###-##-##")
            if phone not in self._used_phones:
                self._used_phones.add(phone)
                return phone

    def _full_name(self) -> str:
        gender = self.rng.choice([Gender.MALE, Gender.FEMALE])
        return self.g.person.full_name(gender=gender)


def main():
    output_path = Path(__file__).resolve().parent.parent / "db" / "init" / "02_seed.sql"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = SeedConfig()
    with SqlWriter(str(output_path)) as writer:
        SeedGenerator(writer, config).run()

    print(f"Готово! Файл {output_path} успешно сгенерирован.")


if __name__ == "__main__":
    main()
