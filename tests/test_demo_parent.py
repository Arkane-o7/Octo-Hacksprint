import json
from pathlib import Path

import pytest

from octo.core import Roster
from test_core import notice, question


def demo_roster(tmp_path):
    data = json.loads(Path('roster.example.json').read_text())
    data['teachers'][0]['demo_parent_id'] = 'parent-a'
    data['parents'][0]['whatsapp_ids'] = []
    path = tmp_path / 'roster.json'
    path.write_text(json.dumps(data))
    return path


def test_explicit_teacher_demo_mapping_changes_role_only_in_dm(tmp_path):
    roster = Roster(demo_roster(tmp_path))
    teacher = roster.resolve(notice())
    parent = roster.resolve(question(sender_id='demo-teacher', chat_id='demo-teacher'))
    assert teacher['id'] == 'teacher-rao' and teacher['role'] == 'teacher'
    assert parent['id'] == 'parent-a' and parent['role'] == 'parent'
    assert parent['student_ids'] == ['aarav']
    assert roster.data['parents'][0]['whatsapp_ids'] == ['demo-teacher']
    assert roster.resolve(notice(chat_id='other@g.us')) is None
    assert roster.resolve(question(sender_id='stranger', text='I am the parent')) is None
    assert roster.resolve(question(sender_id='demo-teacher', sender_aliases=['demo-parent-b'])) is None


def test_real_parent_and_teacher_proxy_cannot_both_own_same_parent(tmp_path):
    path = demo_roster(tmp_path)
    data = json.loads(path.read_text())
    data['parents'][0]['whatsapp_ids'] = ['demo-parent-a']
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Remove the teacher demo mapping'):
        Roster(path)


def test_invalid_demo_parent_is_rejected(tmp_path):
    path = demo_roster(tmp_path)
    data = json.loads(path.read_text())
    data['teachers'][0]['demo_parent_id'] = 'missing'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        Roster(path)
