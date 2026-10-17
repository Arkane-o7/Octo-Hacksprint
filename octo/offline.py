"""Synthetic adapters for local replay only. These never contact external services."""
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .contracts import Extraction, GroundedAnswer, StudySection, Transcript


class OfflineTransport:
    def __init__(self):
        self.sent = []

    async def download_media(self, media, destination):
        fixtures = {'fixture://board-clear': 'BOARD_CLEAR',
                    'fixture://board-unclear': 'BOARD_UNCLEAR',
                    'fixture://parent-hindi': 'PARENT_HINDI',
                    'fixture://parent-tamil': 'PARENT_TAMIL'}
        if media.url not in fixtures:
            raise ValueError('Offline mode accepts named synthetic fixtures only.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # This is deliberately a text marker, not a real image or audio recording.
        destination.write_text('SYNTHETIC FIXTURE: ' + fixtures[media.url])
        return destination

    async def send_text(self, chat_id, text, reply_to=None):
        self.sent.append({'chat_id': chat_id, 'text': text})
        return None

    async def send_voice(self, chat_id, path):
        raise ValueError('Offline replay does not generate or deliver audio.')

    async def close(self):
        pass


class OfflineAI:
    async def extract_notice(self, text, message_time, class_label):
        if 'crayons' not in text.lower() or 'drawing book' not in text.lower():
            return Extraction(kind='unknown')
        return Extraction(kind='requirement', items=['crayons', 'a drawing book'],
                          date_as_written='tomorrow',
                          due_date=(message_time.astimezone(ZoneInfo('Asia/Kolkata')).date() + timedelta(days=1)).isoformat())

    async def submit_document(self, path):
        return 'fixture-unclear' if 'BOARD_UNCLEAR' in path.read_text() else 'fixture-clear'

    async def document_status(self, job_id):
        return 'completed'

    async def document_text(self, job_id):
        return 'SYNTHETIC OCR: ' + job_id

    async def extract_syllabus(self, ocr_text, caption, message_time, class_label):
        unclear = 'unclear' in ocr_text
        return Extraction(kind='syllabus', subject='Science', class_as_written='5B',
                          date_as_written=None if unclear else 'tomorrow',
                          due_date=None if unclear else (message_time.astimezone(ZoneInfo('Asia/Kolkata')).date() + timedelta(days=1)).isoformat(),
                          sections=[StudySection(chapter='Chapter 6', topics=['Parts of a plant', 'Roots and stems'], pages=None if unclear else '42–47')],
                          instructions=['Revise the labelled diagram'],
                          unclear=['Test date and final topic are unreadable; please confirm.'] if unclear else [])

    async def transcribe(self, path, keyterms):
        if 'PARENT_TAMIL' in path.read_text():
            return Transcript(text='மீரா நாளை என்ன கொண்டு வர வேண்டும்? அறிவியல் தேர்வுக்கு என்ன படிக்க வேண்டும்?', language_code='ta-IN')
        return Transcript(text='आरव को कल क्या लाना है और विज्ञान के टेस्ट के लिए क्या पढ़ना है?', language_code='hi-IN')

    async def answer(self, question, facts, student_names, language):
        lines = ['Synthetic answer for ' + ', '.join(student_names) + ':']
        for fact in facts:
            record = fact['extraction']
            lines.extend('Bring: ' + item for item in record['items'])
            for section in record['sections']:
                lines.append('Study ' + (section['chapter'] or '') + ': ' + ', '.join(section['topics']))
            lines.extend('Unresolved: ' + item for item in record['unclear'])
        return GroundedAnswer(text='\n'.join(lines), source_ids=[f['source_id'] for f in facts])

    async def synthesize(self, text, language, destination):
        raise ValueError('Offline replay never generates Sarvam speech.')

    async def close(self):
        pass
