from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class Settings(BaseModel):
    mode: Literal["offline", "live"] = "offline"
    general_brain: bool = False
    data_dir: Path = Path("data")
    roster_path: Path = Path("roster.example.json")
    sarvam_api_key: str = Field(default="", repr=False)
    sarvam_base_url: str = "https://api.sarvam.ai"
    chat_model: str = "sarvam-105b"
    stt_model: str = "saaras:v4"
    tts_model: str = "bulbul:v3"
    document_language: str = "en-IN"
    waha_base_url: str = "http://127.0.0.1:3000"
    waha_api_key: str = Field(default="", repr=False)
    webhook_secret: str = Field(default="", repr=False)
    waha_session: str = "default"
    poll_seconds: float = 5
    reminder_time: str = Field(default='18:00', pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    drive_credentials_path: Path | None = None
    drive_root_folder_id: str = ''
    calendar_credentials_path: Path | None = None
    calendar_id: str = ''

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            mode=os.getenv("OCTO_MODE", "offline"),
            general_brain=os.getenv('OCTO_GENERAL_BRAIN', 'false').lower() == 'true',
            data_dir=Path(os.getenv("OCTO_DATA_DIR", "data")),
            roster_path=Path(os.getenv("OCTO_ROSTER", "roster.example.json")),
            sarvam_api_key=os.getenv("SARVAM_API_KEY", ""),
            sarvam_base_url=os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai"),
            chat_model=os.getenv("SARVAM_CHAT_MODEL", "sarvam-105b"),
            stt_model=os.getenv("SARVAM_STT_MODEL", "saaras:v4"),
            tts_model=os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
            document_language=os.getenv("SARVAM_DOCUMENT_LANGUAGE", "en-IN"),
            waha_base_url=os.getenv("WAHA_BASE_URL", "http://127.0.0.1:3000"),
            waha_api_key=os.getenv("WAHA_API_KEY", ""),
            webhook_secret=os.getenv("WAHA_WEBHOOK_SECRET", ""),
            waha_session=os.getenv("WAHA_SESSION", "default"),
            reminder_time=os.getenv('OCTO_REMINDER_TIME', '18:00'),
            drive_credentials_path=Path(os.environ['GOOGLE_DRIVE_CREDENTIALS']) if os.getenv('GOOGLE_DRIVE_CREDENTIALS') else None,
            drive_root_folder_id=os.getenv('GOOGLE_DRIVE_FOLDER_ID', ''),
            calendar_credentials_path=Path(os.environ['GOOGLE_CALENDAR_CREDENTIALS']) if os.getenv('GOOGLE_CALENDAR_CREDENTIALS') else (Path(os.environ['GOOGLE_DRIVE_CREDENTIALS']) if os.getenv('GOOGLE_DRIVE_CREDENTIALS') else None),
            calendar_id=os.getenv('GOOGLE_CALENDAR_ID', ''),
        )

    def check_live(self) -> None:
        if self.mode == "live":
            missing = [name for name, value in (
                ("SARVAM_API_KEY", self.sarvam_api_key),
                ("WAHA_API_KEY", self.waha_api_key),
                ("WAHA_WEBHOOK_SECRET", self.webhook_secret),
            ) if not value.strip()]
            if missing:
                raise ValueError("Live mode requires local configuration: " + ", ".join(missing))

