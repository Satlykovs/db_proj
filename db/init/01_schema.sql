DROP TABLE IF EXISTS
    reviews, warranty_claims, records, work_order_parts, work_order_items,
    work_orders, auto_service_storage, parts, staff, services,
    service_categories, cars, users, auto_services
CASCADE;

CREATE TABLE auto_services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    address TEXT NOT NULL,
    city VARCHAR(200) NOT NULL,
    count_lift INTEGER NOT NULL CHECK (count_lift >= 0),
    specialization VARCHAR(20) NOT NULL DEFAULT 'universal'
        CHECK (specialization IN ('universal', 'russian', 'german', 'japanese', 'electric'))
);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    phone VARCHAR(20) NOT NULL UNIQUE,
    email TEXT UNIQUE
);

CREATE TABLE cars (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    vin_number VARCHAR(17) NOT NULL UNIQUE CHECK (length(vin_number) = 17),
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    manufacture_year SMALLINT,
    mileage_km INTEGER NOT NULL CHECK (mileage_km >= 0),
    fuel_type VARCHAR(30) NOT NULL
);

CREATE TABLE service_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE services (
    id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES service_categories(id) ON DELETE RESTRICT,
    name VARCHAR(150) NOT NULL,
    description TEXT NOT NULL,
    base_price NUMERIC(10, 2) NOT NULL CHECK (base_price >= 0),
    standard_hours NUMERIC(4, 2) DEFAULT 0 NOT NULL CHECK (standard_hours >= 0),
    warranty_months SMALLINT DEFAULT 0 NOT NULL CHECK (warranty_months >= 0),
    warranty_mileage_km INTEGER DEFAULT 0 NOT NULL CHECK (warranty_mileage_km >= 0)
);

CREATE TABLE staff (
    id SERIAL PRIMARY KEY,
    auto_service_id INTEGER NOT NULL REFERENCES auto_services(id) ON DELETE RESTRICT,
    full_name TEXT NOT NULL,
    specialization VARCHAR(20) NOT NULL
        CHECK (specialization IN ('universal', 'motorist', 'electrician', 'bodyworker', 'diagnostician')),
    rank SMALLINT NOT NULL CHECK (rank BETWEEN 3 AND 6),
    hourly_rate NUMERIC(10, 2) NOT NULL CHECK (hourly_rate >= 0),
    rating NUMERIC(3, 2) CHECK (rating BETWEEN 0 AND 5)
);

CREATE TABLE work_orders (
    id BIGSERIAL PRIMARY KEY,
    auto_service_id INTEGER NOT NULL REFERENCES auto_services(id) ON DELETE RESTRICT,
    car_id INTEGER NOT NULL REFERENCES cars(id) ON DELETE RESTRICT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    price_orders NUMERIC(10, 2) NOT NULL CHECK (price_orders >= 0),
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL
        CHECK (status IN ('accepted', 'in_progress', 'waiting_parts', 'ready', 'issued')),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE work_order_items (
    id BIGSERIAL PRIMARY KEY,
    work_orders_id BIGINT NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE RESTRICT,
    services_id INTEGER NOT NULL REFERENCES services(id) ON DELETE RESTRICT,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    hours NUMERIC(4, 2) NOT NULL DEFAULT 0 CHECK (hours >= 0),
    warranty_months SMALLINT NOT NULL DEFAULT 0 CHECK (warranty_months >= 0),
    warranty_mileage_km INTEGER NOT NULL DEFAULT 0 CHECK (warranty_mileage_km >= 0),
    warranty_expires_at TIMESTAMPTZ,
    mileage_at_service INTEGER NOT NULL CHECK (mileage_at_service >= 0)
);

CREATE TABLE parts (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    manufacturer VARCHAR(100) NOT NULL,
    base_price NUMERIC(10, 2) NOT NULL CHECK (base_price >= 0)
);

CREATE TABLE auto_service_storage (
    auto_service_id INTEGER NOT NULL REFERENCES auto_services(id) ON DELETE CASCADE,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE RESTRICT,
    stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
    min_stock INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
    selling_price NUMERIC(10, 2) CHECK (selling_price >= 0),
    PRIMARY KEY (auto_service_id, part_id)
);

CREATE TABLE work_order_parts (
    id BIGSERIAL PRIMARY KEY,
    work_orders_id BIGINT NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE RESTRICT,
    quantity_used  INTEGER NOT NULL CHECK (quantity_used  > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    UNIQUE (work_orders_id, part_id)
);

CREATE TABLE records (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    auto_service_id INTEGER NOT NULL REFERENCES auto_services(id) ON DELETE RESTRICT,
    car_id INTEGER NOT NULL REFERENCES cars(id) ON DELETE RESTRICT,
    category_id INTEGER REFERENCES service_categories(id) ON DELETE RESTRICT,
    scheduled_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'confirmed', 'cancelled', 'done'))
);

CREATE TABLE warranty_claims (
    id BIGSERIAL PRIMARY KEY,
    work_order_item_id BIGINT NOT NULL REFERENCES work_order_items(id) ON DELETE RESTRICT,
    claim_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'approved', 'rejected', 'in_progress', 'closed')),
    resolution TEXT,
    resolved_at TIMESTAMPTZ,
    resolved_by INTEGER REFERENCES staff(id) ON DELETE SET NULL
);

CREATE TABLE reviews (
    id BIGSERIAL PRIMARY KEY,
    work_order_id BIGINT NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE RESTRICT,
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (work_order_id, staff_id)
);


CREATE INDEX idx_cars_user             ON cars (user_id);
CREATE INDEX idx_wo_car                ON work_orders (car_id);
CREATE INDEX idx_wo_service            ON work_orders (auto_service_id);
CREATE INDEX idx_wo_user               ON work_orders (user_id);
CREATE INDEX idx_woi_order             ON work_order_items (work_orders_id);
CREATE INDEX idx_woi_staff             ON work_order_items (staff_id);
CREATE INDEX idx_woi_service           ON work_order_items (services_id);
CREATE INDEX idx_wop_part              ON work_order_parts (part_id);
CREATE INDEX idx_records_service_time  ON records (auto_service_id, scheduled_at);
CREATE INDEX idx_records_car           ON records (car_id);
CREATE INDEX idx_records_user          ON records (user_id);
CREATE INDEX idx_claims_item           ON warranty_claims (work_order_item_id);
CREATE INDEX idx_reviews_staff         ON reviews (staff_id);