from datetime import date, datetime, time
from decimal import Decimal


class RawSQL:
    """Обёртка для SQL-кода."""

    def __init__(self, val: str):
        self.val = val


def format_value(v) -> str:
    """Превращает Python-объект в SQL-литерал для PostgreSQL."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, RawSQL):
        return v.val
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
    """Класс для записи данных батчами в .sql файл."""

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

    def insert_batch(
        self, table: str, columns: list[str], rows: list[tuple], batch_size: int = 1000
    ):
        """INSERT-запрос. Батчинг."""
        if not rows:
            return

        cols_joined = ", ".join(columns)

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]

            self.f.write(f"INSERT INTO {table} ({cols_joined}) VALUES\n")

            formatted_rows = []
            for row in batch:
                formatted_vals = [format_value(val) for val in row]
                formatted_rows.append("(" + ", ".join(formatted_vals) + ")")

            self.f.write(",\n".join(formatted_rows) + ";\n\n")
