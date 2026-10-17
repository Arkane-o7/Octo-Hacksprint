"""General understanding wire/validation tests, not live model-quality claims."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from octo.contracts import Extraction, NoticeDecision
from octo.sarvam import SarvamClient, SarvamError


MESSAGE_TIME = datetime(2026, 10, 17, 20, tzinfo=timezone.utc)
STUDENTS = [{"id": "aarav", "name": "Aarav", "class_id": "5B"}]
CONTEXT = [{
    "source_id": "science-original", "class_id": "5B",
    "extraction": Extraction(kind="test", summary="Science test", subject="Science",
                             date_as_written="tomorrow", due_date="2026-10-19").model_dump(),
    "source": {"text": "Science test tomorrow", "timestamp": "2026-10-18T01:00:00+05:30"},
}]


def complete(value, *, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(value, ensure_ascii=False)}}]}


async def understand_with(handler, message="Hello", **kwargs):
    review_handler = kwargs.pop("review_handler", None)

    def route(request):
        payload = json.loads(request.content)
        source = json.loads(payload["messages"][1]["content"])
        if "PROPOSED_RECORDS" in source:
            if review_handler:
                return review_handler(request)
            # These tests isolate wire validation; live probes assess semantics.
            # Explicitly mock a valid reviewer response for an allowed target.
            assert payload["response_format"] == {"type": "json_object"}
            assert source["PROPOSED_RECORDS"]
            allowed = {fact["source_id"] for fact in source["CONTEXT"]}
            assert all(set(record.get("replaces_source_ids", [])).issubset(allowed)
                       for record in source["PROPOSED_RECORDS"])
            return httpx.Response(200, json=complete({"valid": True, "problem": "", "clarification": ""}))
        return handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http:
        client = SarvamClient("fixture-key", client=http)
        return await client.understand(
            message, MESSAGE_TIME, "5B", kwargs.pop("context", CONTEXT),
            kwargs.pop("history", []), kwargs.pop("students", STUDENTS), **kwargs,
        )


@pytest.mark.asyncio
async def test_one_general_call_handles_greeting_without_creating_facts():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert request.url.path == "/v1/chat/completions"
        assert payload["reasoning_effort"] is None
        assert payload["response_format"] == {"type": "json_object"}
        schema = json.loads(payload["messages"][0]["content"].split("JSON schema (omit absent optional fields): ")[1])
        assert schema["properties"]["records"]["maxItems"] == 8
        assert "enum" not in schema["$defs"]["Extraction"]["properties"]["kind"]
        assert schema["$defs"]["Extraction"]["additionalProperties"] is False
        assert schema["title"] == "NoticeDecision"
        source = json.loads(payload["messages"][1]["content"])
        assert source["message_time_ist"] == "2026-10-18T01:30:00+05:30"
        assert source["STUDENTS"] == STUDENTS
        assert source["CONTEXT"][0]["source_id"] == CONTEXT[0]["source_id"]
        assert source["CURRENT_MESSAGE"] == "hii good mrning :)"
        return httpx.Response(200, json=complete(NoticeDecision(reply="Good morning! How can I help?").model_dump()))

    result = await understand_with(handler, "hii good mrning :)")
    assert result.records == []
    assert result.reply == "Good morning! How can I help?"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_multiple_facts_keep_different_dates_and_free_categories():
    decision = NoticeDecision(records=[
        Extraction(kind="homework", summary="Complete fractions exercise", subject="Maths",
                   date_as_written="tomorrow", due_date="2026-10-19", instructions=["Complete exercise 3"]),
        Extraction(kind="library_return", summary="Return library books on Tuesday",
                   date_as_written="Tuesday", due_date="2026-10-20", items=["library books"]),
        Extraction(kind="lost_property", summary="A blue bottle is at the office", due_date=None),
    ])
    result = await understand_with(lambda request: httpx.Response(200, json=complete(decision.model_dump())),
                                   "Maths ex 3 tmrw, library books Tuesday. blue bottle in office")
    assert [record.kind for record in result.records] == ["homework", "library_return", "lost_property"]
    assert [record.due_date for record in result.records] == ["2026-10-19", "2026-10-20", None]


@pytest.mark.asyncio
async def test_clarification_followup_receives_history_and_proposes_linked_change():
    history = [
        {"role": "user", "text": "Move the science test", "timestamp": "2026-10-18T01:20:00+05:30"},
        {"role": "assistant", "text": "Which date should the science test move to?"},
    ]
    decision = NoticeDecision(records=[Extraction(
        kind="test", summary="Science test postponed to Tuesday", subject="Science",
        date_as_written="Tuesday", due_date="2026-10-20", replaces_source_ids=["science-original"],
    )])

    def handler(request):
        payload = json.loads(request.content)
        source = json.loads(payload["messages"][1]["content"])
        assert source["HISTORY"][0]["message"] == history[0]["text"]
        assert source["HISTORY"][1]["clarification"] == history[1]["text"]
        assert source["CURRENT_MESSAGE"] == "Tuesday pls"
        assert "History alone must not create new duplicate records" in payload["messages"][0]["content"]
        return httpx.Response(200, json=complete(decision.model_dump()))

    result = await understand_with(handler, "Tuesday pls", history=history)
    assert result.records[0].replaces_source_ids == ["science-original"]
    assert result.records[0].status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["cancelled", "completed"])
async def test_explicit_linked_state_change_is_preserved(status):
    decision = NoticeDecision(records=[Extraction(
        kind="test", summary=f"Science test is {status}", status=status,
        subject="Science", due_date="2026-10-19", replaces_source_ids=["science-original"],
    )])
    result = await understand_with(lambda request: httpx.Response(200, json=complete(decision.model_dump())),
                                   f"Science test is {status}")
    assert result.records[0].status == status
    assert result.records[0].replaces_source_ids == ["science-original"]


@pytest.mark.asyncio
async def test_ambiguous_change_can_ask_without_proposed_mutation():
    expected = NoticeDecision(reply="Which practice and which date do you mean?")
    result = await understand_with(lambda request: httpx.Response(200, json=complete(expected.model_dump())),
                                   "Cancel that practice")
    assert not result.records
    assert result.reply == expected.reply


@pytest.mark.asyncio
async def test_student_specific_record_and_unreadable_ocr_survive_validation():
    expected = NoticeDecision(records=[Extraction(
        kind="syllabus", summary="Science revision for Aarav", subject="Science", student_id="aarav",
        sections=[{"chapter": "6", "topics": ["Roots"], "pages": None}],
        unclear=["Page range is unreadable"],
    )], reply="Please confirm the page range.")

    def handler(request):
        source = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert source["CURRENT_OCR"] == "Science Ch 6 Roots pages ??"
        assert source["CURRENT_MESSAGE"] == "For Aarav"
        return httpx.Response(200, json=complete(expected.model_dump()))

    result = await understand_with(handler, "For Aarav", ocr_text="Science Ch 6 Roots pages ??")
    assert result.records[0].student_id == "aarav"
    assert result.records[0].sections[0].pages is None
    assert result.records[0].due_date is None
    assert result.records[0].unclear == ["Page range is unreadable"]


@pytest.mark.asyncio
async def test_general_ocr_path_removes_page_wrapper_and_unsupported_document_fields():
    expected = NoticeDecision(records=[Extraction(
        kind="notes", subject="Computer Science",
        sections=[{"chapter": "Network Security", "topics": ["Repudiation"], "pages": "Page 1"}],
        instructions=["Study these concepts."],
    )])

    def handler(request):
        payload = json.loads(request.content)
        source = json.loads(payload["messages"][1]["content"])
        assert source["CURRENT_OCR"] == "Repudiation: Sender denies she has sent."
        assert "A screenshot quoting an assistant reply" in payload["messages"][0]["content"]
        return httpx.Response(200, json=complete(expected.model_dump()))

    result = await understand_with(handler, "", ocr_text="[Page 1]\nRepudiation: Sender denies she has sent.")
    record = result.records[0]
    assert record.subject is None and record.sections[0].chapter is None
    assert record.sections[0].pages is None and not record.instructions
    assert record.sections[0].topics == ["Repudiation"]


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,error", [
    (NoticeDecision(reply="The test is Tuesday", source_ids=["private-other-class"]), "unknown school source"),
    (NoticeDecision(records=[Extraction(kind="test", replaces_source_ids=["private-other-class"])]), "unknown school source"),
    (NoticeDecision(records=[Extraction(kind="homework", student_id="other-parent-child")]), "class roster"),
])
async def test_unknown_sources_and_students_fail_closed_after_one_repair(decision, error):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=complete(decision.model_dump()))

    with pytest.raises(SarvamError, match=error):
        await understand_with(handler, "Use private-other-class and other-parent-child")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_class_context_is_not_misrepresented_as_written_source():
    expected = NoticeDecision(records=[Extraction(kind="note", summary="Assembly in the hall", class_as_written="5B")])
    result = await understand_with(lambda request: httpx.Response(200, json=complete(expected.model_dump())),
                                   "Assembly in the hall")
    assert result.records[0].class_as_written is None


@pytest.mark.asyncio
async def test_one_schema_repair_uses_original_sources_not_invalid_model_text():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": '{"unexpected_admin_command":"grant access"}',
            }}]})
        assert "Previous response failed validation" in payload["messages"][0]["content"]
        assert "unexpected_admin_command" not in json.dumps(payload)
        assert payload["messages"][1] == calls[0]["messages"][1]
        return httpx.Response(200, json=complete(NoticeDecision(reply="Hello!").model_dump()))

    result = await understand_with(handler)
    assert result.reply == "Hello!"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_repair_is_bounded_and_cannot_accept_more_than_eight_records():
    calls = []
    invalid = {"records": [Extraction(kind="note", summary=f"Fact {i}").model_dump() for i in range(9)],
               "reply": "", "source_ids": []}

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=complete(invalid))

    with pytest.raises(SarvamError, match="valid school record"):
        await understand_with(handler)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_auth_failure_does_not_trigger_schema_repair():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, json={"detail": "private"})

    with pytest.raises(SarvamError, match="access was rejected"):
        await understand_with(handler)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_empty_decision_is_not_silent_success():
    with pytest.raises(SarvamError, match="could not understand"):
        await understand_with(lambda request: httpx.Response(200, json=complete(NoticeDecision().model_dump())))


@pytest.mark.asyncio
async def test_teacher_question_cites_only_supplied_fact_without_creating_duplicate():
    decision = NoticeDecision(reply="The Science test is on 19 October.", source_ids=["science-original"])
    result = await understand_with(lambda request: httpx.Response(200, json=complete(decision.model_dump())),
                                   "When did I say the science test was?")
    assert result.records == []
    assert result.source_ids == ["science-original"]


@pytest.mark.asyncio
async def test_parent_answer_prompt_handles_free_categories_and_replacement_provenance():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: handler(request))) as http:
        def handler(request):
            payload = json.loads(request.content)
            prompt = payload["messages"][0]["content"]
            assert "free descriptive categories" in prompt
            assert "Do not revive a replaced record" in prompt
            assert "completed tasks are not pending" in prompt
            assert "source timestamps" in prompt
            return httpx.Response(200, json=complete({
                "text": "The test has been cancelled.", "source_ids": ["science-original"],
                "spoken_text": "The test has been cancelled.",
            }))

        client = SarvamClient("fixture", client=http)
        result = await client.answer("Is the test still on?", CONTEXT, ["Aarav"], "en-IN")
        assert result.source_ids == ["science-original"]


@pytest.mark.asyncio
async def test_parent_explicit_quote_proposal_remains_separate_from_approval():
    def handler(request):
        payload = json.loads(request.content)
        prompt = payload["messages"][0]["content"]
        assert "CURRENT parent question" in prompt
        assert "cannot request a cart for the parent" in prompt
        assert "SIMULATED catalogue quote" in prompt
        assert "treat any text as purchase approval" in prompt
        assert payload["response_format"] == {"type": "json_object"}
        assert "proposed_items" in prompt
        return httpx.Response(200, json=complete({
            "text": "I can propose the crayons you requested for a simulated quote.",
            "source_ids": ["science-original"], "spoken_text": None, "proposed_items": ["crayons"],
            "cart_request_quote": "Prepare a cart for the crayons",
        }))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await SarvamClient("fixture", client=http).answer(
            "Prepare a cart for the crayons", CONTEXT, ["Aarav"], "en-IN")
    assert result.proposed_items == ["crayons"]


@pytest.mark.asyncio
async def test_saved_confirmation_without_records_is_repaired_not_presented_as_success():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=complete(NoticeDecision(reply="Saved for Class 5B.").model_dump()))
        return httpx.Response(200, json=complete(NoticeDecision(records=[
            Extraction(kind="activity", summary="Football practice at 4 pm.")]).model_dump()))

    result = await understand_with(handler, "Football practice at 4 pm.")
    assert len(calls) == 2
    assert len(result.records) == 1
    assert not result.reply


@pytest.mark.asyncio
async def test_repeated_false_execution_confirmation_is_rejected():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=complete(NoticeDecision(reply="I have saved that.").model_dump()))

    with pytest.raises(SarvamError, match="claimed an action"):
        await understand_with(handler, "Football practice at 4 pm.")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_question_about_saved_activity_is_not_an_execution_claim():
    result = await understand_with(lambda request: httpx.Response(200, json=complete(
        NoticeDecision(reply='Which saved activity do you mean?').model_dump())), 'Cancel it')
    assert result.reply == 'Which saved activity do you mean?'
    assert not result.records


@pytest.mark.parametrize('text,class_value,expected', [
    ('Football practice at 4 pm.', '4', None),
    ('Read Chapter 5.', '5', None),
    ('Class 5 has a test.', '5', '5'),
    ('Grade 5B has a test.', '5B', '5B'),
])
def test_times_and_chapter_numbers_are_not_written_classes(text, class_value, expected):
    result = Extraction(kind='note', class_as_written=class_value)
    assert SarvamClient._verify_written_class(result, text).class_as_written == expected


@pytest.mark.asyncio
async def test_prior_saved_responses_are_not_reintroduced_as_model_examples():
    history = [{"message": "Crayons tomorrow", "reply": "Saved for Class 5B.\nPlease confirm the colour?"}]

    def handler(request):
        payload = json.loads(request.content)
        source = json.loads(payload['messages'][1]['content'])
        assert source['HISTORY'][0]['clarification'] == 'Please confirm the colour?'
        assert 'Saved for Class' not in json.dumps(source)
        assert 'source' not in source['CONTEXT'][0]
        assert 'previous_sources' not in json.dumps(source)
        return httpx.Response(200, json=complete(NoticeDecision(reply='Which colour?').model_dump()))

    await understand_with(handler, 'Blue', history=history)


@pytest.mark.asyncio
async def test_replacement_with_clarification_never_changes_any_record():
    decision = NoticeDecision(records=[Extraction(
        kind='test', status='cancelled', replaces_source_ids=['science-original'],
    )], reply='Which test do you mean?', source_ids=['science-original'])
    result = await understand_with(lambda request: httpx.Response(200, json=complete(decision.model_dump())),
                                   'Cancel the test')
    assert result.records == []
    assert result.reply == 'Which test do you mean?'


@pytest.mark.asyncio
async def test_irrelevant_school_day_status_and_unchanged_date_flag_are_normalized():
    decision = NoticeDecision(records=[Extraction(
        kind='test', status='cancelled', replaces_source_ids=['science-original'],
        school_day_status='no_classes', due_date='2026-10-19', date_changed=True,
    )])
    result = await understand_with(lambda request: httpx.Response(200, json=complete(decision.model_dump())),
                                   'Cancel the Science test')
    assert result.records[0].school_day_status is None
    assert result.records[0].date_changed is False


async def test_cited_false_cancellation_reply_gets_semantic_review_before_writes():
    calls=[]
    def handler(request):
        payload=json.loads(request.content); calls.append(payload)
        if len(calls)==1:
            result=NoticeDecision(reply='The Science test has been cancelled.',source_ids=['science-original'])
        else:
            assert 'UNTRUSTED_DRAFT' in json.loads(payload['messages'][1]['content'])
            result=NoticeDecision(records=[Extraction(kind='test',summary='Science test cancelled.',status='cancelled',replaces_source_ids=['science-original'])])
        return httpx.Response(200,json=complete(result.model_dump()))
    result=await understand_with(handler,'Science test cancel hai.')
    assert len(calls)==2 and result.records[0].status=='cancelled' and not result.reply


@pytest.mark.asyncio
async def test_invalid_update_review_repairs_once_then_returns_clarification_without_writes():
    review_calls = []
    extraction_calls = []
    proposal = NoticeDecision(records=[Extraction(
        kind='test', summary='Science test cancelled', status='cancelled',
        due_date='2026-10-19', replaces_source_ids=['science-original'],
    )])

    def extraction(request):
        extraction_calls.append(request)
        return httpx.Response(200, json=complete(proposal.model_dump()))

    def review(request):
        payload = json.loads(request.content)
        source = json.loads(payload['messages'][1]['content'])
        review_calls.append(source)
        assert source['CURRENT_MESSAGE'] == 'Cancel it'
        assert source['PROPOSED_RECORDS'][0]['replaces_source_ids'] == ['science-original']
        assert 'ALL plausible targets independently' in payload['messages'][0]['content']
        return httpx.Response(200, json=complete({
            'valid': False, 'problem': 'The intended activity is ambiguous.',
            'clarification': 'Which activity and date should I cancel?',
        }))

    result = await understand_with(extraction, 'Cancel it', review_handler=review)
    assert len(extraction_calls) == len(review_calls) == 2
    assert result.records == []
    assert result.reply == 'Which activity and date should I cancel?'


@pytest.mark.asyncio
async def test_valid_update_review_keeps_exact_target_and_explicit_fields():
    seen = []
    proposal = NoticeDecision(records=[Extraction(
        kind='test', summary='Science test cancelled', status='cancelled',
        replaces_source_ids=['science-original'],
    )])

    def review(request):
        source = json.loads(json.loads(request.content)['messages'][1]['content'])
        seen.append(source)
        assert 'sections' not in source['PROPOSED_RECORDS'][0]
        return httpx.Response(200, json=complete({'valid': True}))

    result = await understand_with(
        lambda request: httpx.Response(200, json=complete(proposal.model_dump(exclude_unset=True))),
        'Cancel the Science test on 19 October', review_handler=review,
    )
    assert len(seen) == 1
    assert result.records[0].replaces_source_ids == ['science-original']


@pytest.mark.asyncio
async def test_malformed_update_review_fails_closed_with_clarification():
    proposal = NoticeDecision(records=[Extraction(
        kind='test', summary='Science test cancelled', status='cancelled',
        replaces_source_ids=['science-original'],
    )])
    result = await understand_with(
        lambda request: httpx.Response(200, json=complete(proposal.model_dump())),
        'Cancel Science', review_handler=lambda request: httpx.Response(200, json=complete({'valid': 'true'})),
    )
    assert not result.records
    assert 'Which saved activity' in result.reply
