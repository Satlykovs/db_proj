# AutoService Pro $\text{--}$ База данных сети автосервисов

Проект по дисциплине "Базы данных".  
**Участники:** Басков Серхио Перез, Сатлыков Санджар.

---

## 1. Запуск БД и pgAdmin

```bash
docker compose up -d
```

* pgAdmin: http://localhost:5050 (сервер `AutoService Pro` подключится сам)
* Пересоздать БД с нуля (после правок в `db/init/`):

```bash
docker compose down -v && docker compose up -d
```

## 2. Python venv & scripts

Нужен **Python >= 3.10** (только если нужно перегенерить `db/init/02_seed.sql`).

1. Поставить `poetry` и плагин для `shell`:

```bash
pip install poetry poetry-plugin-shell
```

2. Подтянуть зависимости проекта:

```bash
poetry install
```

3. Активировать окружение и запустить генератор:

```bash
poetry shell
python scripts/generate_seed.py
```