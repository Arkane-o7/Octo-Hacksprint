"""Small shared interfaces. Lead-owned; adapters must not import storage or app."""
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Media(BaseModel):
    url: str | None = None
    mime_type: str = "application/octet-stream"
    filename: str = "attachment"
    local_path: str | None = None


class IncomingMessage(BaseModel):
    session: str
    message_id: str
    chat_id: str
    sender_id: str
    sender_aliases: list[str] = Field(default_factory=list)
    timestamp: datetime
    kind: Literal["text", "image", "voice", "document"] = "text"
    text: str = ""
    media: Media | None = None
    is_group: bool = False
    forwarded: bool = False
    quoted_message_id: str | None = None
    quoted_chat_id: str | None = None
    is_quoted: bool = False

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Message timestamp must include a timezone")
        return value

    @property
    def source_key(self) -> str:
        import json
        return json.dumps([self.session, self.chat_id, self.message_id], separators=(",", ":"))


class StudySection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: str | None = None
    topics: list[str] = Field(default_factory=list)
    pages: str | None = None


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=60, description='Short descriptive category chosen from the source; not a fixed list of supported school topics.')
    summary: str | None = Field(default=None, description='Plain-language school fact retaining the source meaning and negation. No invented facts or advice.')
    status: Literal['active', 'cancelled', 'completed'] = 'active'
    student_id: str | None = Field(default=None, description='An explicitly named student ID from the supplied roster, or null for a class-wide fact.')
    replaces_source_ids: list[str] = Field(default_factory=list, description='Exact existing scoped fact source_ids being explicitly corrected, postponed or cancelled. Empty for new independent information. Ask when the target is ambiguous.')
    date_changed: bool = Field(default=False, description='For a replacement only: true only when THIS update explicitly changes its date; false when preserving the existing date, even if another fact in the message says tomorrow.')
    school_day_status: Literal["no_classes", "classes_scheduled"] | None = Field(
        default=None, description='Only for kind school_day: explicit whole-class no-classes/holiday or classes-as-usual notice. Never use for cancellation of a single subject, test or activity.')
    subject: str | None = None
    class_as_written: str | None = Field(default=None, description='Class explicitly written in source text; null if only known from group context.')
    date_as_written: str | None = Field(default=None, description='Exact source wording of the relevant date, or null when absent.')
    due_date: str | None = None  # ISO YYYY-MM-DD, validated again by domain code.
    items: list[str] = Field(default_factory=list, description='Physical supplies explicitly required to bring. Study topics, chapters, page ranges and revision instructions never belong here. Use [] for a pure syllabus.')
    sections: list[StudySection] = Field(default_factory=list, description='Study checklist grouped by chapter, with only source-provided topics and page ranges.')
    instructions: list[str] = Field(default_factory=list)
    unclear: list[str] = Field(default_factory=list)


class Transcript(BaseModel):
    text: str
    language_code: str | None = None


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    basis: Literal['school', 'conversation', 'clarification'] = Field(default='school',
        description='School information requires current fact source_ids. Conversation recalls only what this user said; clarification asks for missing information and asserts no school facts.')
    context_ids: list[str] = Field(default_factory=list, max_length=12,
        description='Exact supplied conversation reference IDs supporting recall of user-provided details. Never substitutes for teacher sources about school facts.')
    language_code: str = Field(pattern=r'^[a-z]{2,3}-[A-Z]{2}$',
        description='Language of this answer and spoken_text, chosen from the CURRENT question. An explicit reply-language request wins; the saved preference is only a fallback for unclear input.')
    text: str
    source_ids: list[str] = Field(default_factory=list)
    spoken_text: str | None = None
    proposed_items: list[str] = Field(default_factory=list,
                                      description='Catalogue item names only when the parent explicitly asks to prepare a simulated cart. This never approves or buys anything.')
    cart_request_quote: str | None = Field(default=None,
        description='Exact words from the CURRENT parent question requesting shopping/cart preparation, otherwise null. A question about what to bring is not a shopping request.')


class NoticeDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    records: list[Extraction] = Field(default_factory=list, max_length=8,
                                      description='Independent school facts from this message. Split mixed subjects or dates. Empty for conversation, questions or unresolved changes.')
    reply: str = Field(default='', max_length=3000,
                       description='A conversational answer or targeted clarification. Never claim a write, reminder, purchase or upload succeeded; the app confirms completed operations.')
    source_ids: list[str] = Field(default_factory=list, description='Exact supplied saved source IDs supporting any factual answer in reply.')


# Adapter contracts (async unless marked otherwise):
# WahaClient(base_url, api_key, session, *, client: httpx.AsyncClient | None = None)
#   normalize(payload: dict) -> IncomingMessage | None [module function, synchronous]
#   verify_signature(body: bytes, signature: str, secret: str) -> bool [module function]
#   download_media(media: Media, destination: Path) -> Path
#   send_text(chat_id: str, text: str, reply_to: str | None = None) -> str | None
#   send_voice(chat_id: str, path: Path) -> str | None
#   close()
# SarvamClient(api_key, *, base_url, chat_model, stt_model, tts_model,
#              client: httpx.AsyncClient | None = None)
#   extract_notice(text: str, message_time: datetime, class_label: str) -> Extraction
#   submit_document(path: Path) -> str  # digitise job ID; no blocking polling
#   document_status(job_id: str) -> str
#   document_text(job_id: str) -> str
#   extract_syllabus(ocr_text: str, caption: str, message_time: datetime,
#                    class_label: str) -> Extraction
#   answer(question: str, facts: list[dict], student_names: list[str],
#          language: str) -> GroundedAnswer
#   transcribe(path: Path, keyterms: list[str]) -> Transcript
#   synthesize(text: str, language: str, destination: Path) -> Path
#   close()

