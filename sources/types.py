from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawNotice:
    source_key: str
    external_id: str
    source_url: str
    state: str
    agency: str
    title: str
    description: str
    deadline_at: datetime | None
    deadline_text: str
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
