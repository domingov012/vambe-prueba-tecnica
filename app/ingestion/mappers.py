from dataclasses import dataclass
from datetime import date, datetime

ClientKey = tuple[str, str, str]


@dataclass(frozen=True)
class ParsedRow:
    """One CSV row, normalized. Produced in the request path (so a malformed row
    fails the upload with a 422) and then carried through the enrichment job."""

    name: str
    email: str
    phone_number: str
    meeting_date: date
    salesperson: str
    closed: bool
    transcript: str

    @property
    def client_key(self) -> ClientKey:
        return (self.name, self.email, self.phone_number)


def parse_row(row: dict[str, str]) -> ParsedRow:
    """Map one raw CSV row to a `ParsedRow`. Raises `ValueError` on a bad date or
    `closed` value (the caller turns that into a 422)."""
    return ParsedRow(
        name=row["Nombre"].strip(),
        email=row["Correo Electronico"].strip().lower(),
        phone_number=row["Numero de Telefono"].strip(),
        meeting_date=datetime.strptime(row["Fecha de la Reunion"].strip(), "%Y-%m-%d").date(),
        salesperson=row["Vendedor asignado"].strip(),
        closed=bool(int(row["closed"].strip())),
        transcript=row["Transcripcion"].strip(),
    )
