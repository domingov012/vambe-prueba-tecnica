import csv
import io
from typing import Iterator

EXPECTED_HEADERS = [
    "Nombre",
    "Correo Electronico",
    "Numero de Telefono",
    "Fecha de la Reunion",
    "Vendedor asignado",
    "closed",
    "Transcripcion",
]


class CSVValidationError(Exception):
    def __init__(self, missing: list[str], extra: list[str]):
        self.missing = missing
        self.extra = extra
        parts = []
        if missing:
            parts.append(f"missing columns: {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected columns: {', '.join(extra)}")
        super().__init__("; ".join(parts))


def parse_csv(raw_bytes: bytes) -> Iterator[dict[str, str]]:
    text = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    _validate_headers(reader.fieldnames or [])
    yield from reader


def _validate_headers(headers: list[str]) -> None:
    expected = set(EXPECTED_HEADERS)
    actual = set(headers)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise CSVValidationError(missing=missing, extra=extra)
