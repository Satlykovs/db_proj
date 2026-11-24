import itertools
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

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


@dataclass(frozen=True)
class SeedConfig:
    seed: int = 67
    brand_name: str = "AutoService Pro"
    now: datetime = datetime.now(timezone.utc).replace(hour=15, minute=0, second=0, microsecond=0)

    users_count: int = 120
    max_cars_per_user: int = 2
    min_car_year: int = 2000
    max_car_year: int = 2026

    staff_per_spec_in_branch: int = 2
    orders_count: int = 350
    warranty_claims_count: int = 110

    branches: tuple[BranchConfig, ...] = (
        BranchConfig("Москва", "Север", "german", lifts=6, is_24h=True),
        BranchConfig("Москва", "Юг", "japanese", lifts=5),
        BranchConfig("Москва", "Центр", "electric", lifts=4),
        BranchConfig("Санкт-Петербург", "Приморский", "universal", lifts=6, is_24h=True),
        BranchConfig("Казань", "Вахитовский", "universal", lifts=4),
        BranchConfig("Екатеринбург", "Чкаловский", "universal", lifts=4),
    )


@dataclass
class _CarMeta:
    id: int
    user_id: int
    service_spec: str
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

        self._branches_by_spec: dict[str, list[int]] = {}
        self._all_branch_ids: list[int] = []
        self._cars: list[_CarMeta] = []
        self._categories: list[tuple[int, str, str]] = []
        self._services_by_cat: dict[int, list[_ServiceMeta]] = {}
        self._staff_by_branch_spec: dict[tuple[int, str], list[_StaffMeta]] = {}
        self._parts_storage: dict[int, list[tuple[int, Decimal, str]]] = {}
        self._used_vins: set[str] = set()

    def run(self):
        console = Console()
        self.writer.write_comment("=== AUTO-GENERATED SEED DATA ===")

        steps = [
            ("[1/6] Генерация филиалов автосервиса", self._gen_auto_services),
            (f"[2/6] Генерация клиентов ({self.cfg.users_count}) и авто", self._gen_users_and_cars),
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
            self._gen_workflow(progress)
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
        table.add_row("Визиты (records)", str(self.cfg.orders_count))
        console.print(table)

    def _gen_auto_services(self):
        self.writer.write_comment("1. Автосервисы")
        models: list[AutoService] = []
        for branch in self.cfg.branches:
            b_id = next(self._seq["service"])
            self._all_branch_ids.append(b_id)
            self._branches_by_spec.setdefault(branch.specialization, []).append(b_id)
            models.append(
                AutoService(
                    name=f"{self.cfg.brand_name} {branch.city} ({branch.district})",
                    address=f"г. {branch.city}, {self.g.address.street_name()}, д. "
                    f"{self.rng.randint(1, 140)}",
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
        for idx in range(self.cfg.users_count):
            u_id = next(self._seq["user"])
            users.append(
                User(
                    name=self._full_name(),
                    phone=self.g.person.phone_number(mask="+7 (9##) ###-##-##"),
                    email=f"user{u_id}_{self.g.person.email()}",
                )
            )
            for c_idx in range(self.rng.randint(1, self.cfg.max_cars_per_user)):
                c_id = next(self._seq["car"])
                spec = self.rng.choice(CAR_CATALOG)
                year = self.rng.randint(self.cfg.min_car_year, self.cfg.max_car_year)
                age = max(0, self.cfg.now.year - year)
                mileage = (
                    self.rng.randint(1_000, 12_000)
                    if age == 0
                    else self.rng.randint(age * 11_000, age * 21_000)
                )
                is_stale = idx % 6 == 0 and c_idx == 0
                self._cars.append(_CarMeta(c_id, u_id, spec.service_spec, mileage, is_stale))
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
                for _ in range(self.cfg.staff_per_spec_in_branch):
                    st_id = next(self._seq["staff"])
                    grade = self.rng.randint(3, 6)
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
        part_entries: list[tuple[int, Decimal]] = []

        for tpl in PART_TEMPLATES:
            for mfg in PART_MANUFACTURERS:
                p_id = next(self._seq["part"])
                sku = f"{tpl.code}-{mfg[:3].upper()}-{p_id:03d}"
                price = Decimal(self.rng.randint(tpl.min_price, tpl.max_price))
                part_entries.append((p_id, price))
                parts.append(
                    Part(sku=sku, name=f"{tpl.name} ({mfg})", manufacturer=mfg, base_price=price)
                )

        for b_id in self._all_branch_ids:
            for p_id, base_price in part_entries:
                min_stock = self.rng.randint(3, 10)
                stock_qty = (
                    self.rng.randint(0, min_stock - 1)
                    if self.rng.random() < 0.15
                    else self.rng.randint(min_stock, min_stock + 25)
                )
                sell_price = (base_price * Decimal("1.25")).quantize(Decimal("0.01"))
                self._parts_storage.setdefault(b_id, []).append((p_id, sell_price, tpl.code))
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

    def _gen_workflow(self, progress: Progress | None = None):
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

        star_staff_ids = {
            staff_list[0].id for staff_list in list(self._staff_by_branch_spec.values())[:2]
        }

        eligible_for_warranty: list[tuple[int, str, datetime, int]] = []

        for i in range(self.cfg.orders_count):
            if progress and wf_task is not None:
                progress.advance(wf_task)

            rec_id = next(self._seq["record"])
            car = self.rng.choice(self._cars)
            cat_id, cat_name, req_spec = self.rng.choice(self._categories)

            matching_branches = self._branches_by_spec.get(
                car.service_spec, []
            ) + self._branches_by_spec.get("universal", [])
            branch_id = self.rng.choice(matching_branches or self._all_branch_ids)

            if car.is_stale:
                days_ago = self.rng.randint(380, 700)
            elif i < 95:
                days_ago = self.rng.randint(1, 28)
            else:
                days_ago = self.rng.randint(1, 360)

            scheduled_at = self.cfg.now - timedelta(days=days_ago, hours=self.rng.randint(0, 10))

            if i % 10 == 0 and not car.is_stale:
                status = self.rng.choice(["planned", "cancelled"])
                future_dt = self.cfg.now + timedelta(days=self.rng.randint(1, 14))
                records.append(Record(car.user_id, branch_id, car.id, cat_id, future_dt, status))
                continue

            records.append(Record(car.user_id, branch_id, car.id, cat_id, scheduled_at, "done"))

            wo_id = next(self._seq["wo"])
            started_at = scheduled_at + timedelta(minutes=self.rng.randint(5, 30))

            candidates = self._staff_by_branch_spec[(branch_id, req_spec)]
            if i < 95:
                stars = [c for c in candidates if c.id in star_staff_ids]
                chosen_staff = self.rng.choice(stars) if stars else self.rng.choice(candidates)
            else:
                chosen_staff = self.rng.choice(candidates)

            staff_id, staff_obj = chosen_staff.id, chosen_staff.model

            available_srvs = self._services_by_cat.get(cat_id, [])
            chosen_srvs = self.rng.sample(
                available_srvs, k=min(len(available_srvs), self.rng.randint(1, 3))
            )

            total_price = Decimal("0.00")
            total_hours = Decimal("0.00")
            created_item_ids: list[int] = []

            for srv in chosen_srvs:
                item_id = next(self._seq["wo_item"])
                created_item_ids.append(item_id)
                fact_hours = (
                    srv.standard_hours * Decimal(str(self.rng.uniform(0.9, 1.2)))
                ).quantize(Decimal("0.01"))
                item_price = (srv.base_price + staff_obj.hourly_rate * srv.standard_hours).quantize(
                    Decimal("0.01")
                )
                total_price += item_price
                total_hours += fact_hours

                ended_est = started_at + timedelta(hours=float(fact_hours))
                w_expires = (
                    ended_est + timedelta(days=30 * srv.warranty_months)
                    if srv.warranty_months > 0
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
            prefixes = CATEGORY_PART_PREFIXES.get(cat_name, ())
            if prefixes:
                matching_parts = [
                    (pid, price)
                    for pid, price, code in self._parts_storage[branch_id]
                    if code.startswith(prefixes)
                ]
                for part_id, unit_price in self.rng.sample(
                    matching_parts, k=min(len(matching_parts), self.rng.randint(1, 3))
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

            is_finished = days_ago > 1 or self.rng.random() < 0.85
            ended_at = (
                started_at + timedelta(hours=max(1, int(total_hours))) if is_finished else None
            )
            wo_status = (
                "issued" if is_finished else self.rng.choice(["in_progress", "waiting_parts"])
            )

            km_delta = int((days_ago / 365.0) * 15_000)
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

            if is_finished and ended_at is not None:
                for it_id in created_item_ids:
                    eligible_for_warranty.append((it_id, cat_name, ended_at, branch_id))

                if self.rng.random() < 0.65:
                    rating = (
                        5
                        if staff_id in star_staff_ids
                        else self.rng.choices([1, 2, 3, 4, 5], weights=[15, 5, 10, 25, 45])[0]
                    )
                    comment = (
                        self.rng.choice(POSITIVE_REVIEWS)
                        if rating >= 4
                        else self.rng.choice(NEGATIVE_REVIEWS)
                    )
                    staff_obj.review_count += 1
                    staff_obj.review_sum += rating

                    reviews.append(
                        Review(
                            work_order_id=wo_id,
                            staff_id=staff_id,
                            rating=rating,
                            comment=comment,
                            created_at=ended_at + timedelta(hours=self.rng.randint(2, 48)),
                        )
                    )

        for item_id, cat_name, ended_at, branch_id in self.rng.sample(
            eligible_for_warranty,
            k=min(len(eligible_for_warranty), self.cfg.warranty_claims_count),
        ):
            reasons = WARRANTY_LOGIC.get(
                cat_name, [("Дефект после ремонта", "Устранено по гарантии")]
            )
            reason_txt, resolution_txt = self.rng.choice(reasons)
            claim_dt = ended_at + timedelta(days=self.rng.randint(3, 45))
            is_closed = self.rng.random() < 0.75

            any_staff_in_branch = self._staff_by_branch_spec[(branch_id, "motorist")][0].id
            warranty_claims.append(
                WarrantyClaim(
                    work_order_item_id=item_id,
                    claim_date=claim_dt,
                    reason=reason_txt,
                    status="closed" if is_closed else "in_progress",
                    resolution=resolution_txt if is_closed else None,
                    resolved_at=(claim_dt + timedelta(days=2)) if is_closed else None,
                    resolved_by=any_staff_in_branch if is_closed else None,
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

    def _unique_vin(self) -> str:
        while True:
            vin = "".join(self.rng.choices(self.VIN_CHARS, k=17))
            if vin not in self._used_vins:
                self._used_vins.add(vin)
                return vin

    def _full_name(self) -> str:
        gender = self.rng.choice([Gender.MALE, Gender.FEMALE])
        return self.g.person.full_name(gender=gender)


def main():
    from pathlib import Path

    output_path = Path(__file__).resolve().parent.parent / "db" / "init" / "02_seed.sql"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = SeedConfig()
    with SqlWriter(str(output_path)) as writer:
        SeedGenerator(writer, config).run()

    print(f"Готово! Файл {output_path} успешно сгенерирован.")


if __name__ == "__main__":
    main()
