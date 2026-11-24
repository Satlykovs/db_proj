from dataclasses import astuple, fields, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import ClassVar, Protocol


class DbModel(Protocol):
    """Контракт для моделей: любой dataclass с указанием имени таблицы."""

    __table__: ClassVar[str]


def format_value(v) -> str:
    """Превращает Python-объект в SQL-литерал для PostgreSQL."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, datetime):
        return f"'{v.isoformat(sep=' ', timespec='seconds')}'"
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    if isinstance(v, time):
        return f"'{v.isoformat(timespec='seconds')}'"

    escaped = str(v).replace("'", "''")
    return f"'{escaped}'"


class SqlWriter:
    """Записывает модели батчами в .sql файл."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.f = None

    def __enter__(self):
        self.f = open(self.filepath, "w", encoding="utf-8")
        self.f.write("-- " + "=" * 50 + "\n")
        self.f.write(
            "-- AutoService Pro: Generated automatically, don't touch! Serg, I am not joking\n"
        )
        self.f.write("-- " + "=" * 50 + "\n")
        self.f.write("BEGIN;\n\n")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.f.write("COMMIT;\n")
        else:
            self.f.write("ROLLBACK;\n")
        self.f.close()

    def write_comment(self, text: str):
        self.f.write(f"\n-- {text}\n")

    def insert(self, models: list[DbModel], batch_size: int = 1000):
        """Генерирует батчевый INSERT из списка датаклассов."""
        if not models:
            return

        sample = models[0]
        if not is_dataclass(sample):
            raise TypeError(f"Ожидался dataclass, получен {type(sample)}")

        table = sample.__table__
        columns = [f.name for f in fields(sample)]
        cols_joined = ", ".join(columns)

        for i in range(0, len(models), batch_size):
            batch = models[i : i + batch_size]
            self.f.write(f"INSERT INTO {table} ({cols_joined}) VALUES\n")

            formatted_rows = []
            for model in batch:
                values = [format_value(val) for val in astuple(model)]
                formatted_rows.append("(" + ", ".join(values) + ")")

            self.f.write(",\n".join(formatted_rows) + ";\n\n")
