from datetime import datetime

from app.models import Client, MeetingTranscript


def row_to_client_fields(row: dict[str, str]) -> dict[str, str]:
    return {
        "name": row["Nombre"].strip(),
        "email": row["Correo Electronico"].strip().lower(),
        "phone_number": row["Numero de Telefono"].strip(),
    }


def row_to_meeting(row: dict[str, str], client: Client) -> MeetingTranscript:
    return MeetingTranscript(
        client=client,
        meeting_date=datetime.strptime(row["Fecha de la Reunion"].strip(), "%Y-%m-%d").date(),
        salesperson=row["Vendedor asignado"].strip(),
        closed=bool(int(row["closed"].strip())),
        transcript=row["Transcripcion"].strip(),
    )
