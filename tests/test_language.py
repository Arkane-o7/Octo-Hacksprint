import pytest

from octo.language import language_hint


@pytest.mark.parametrize('text,expected', [
    ('Explain this in two short sentences.', 'en-IN'),
    ('What should I bring tomorrow?', 'en-IN'),
    ('My pickup time is 4 pm', 'en-IN'),
    ('why?', 'en-IN'),
    ('hi', 'en-IN'),
    ('ok', 'en-IN'),
    ('explain', 'en-IN'),
    ('tell me more', 'en-IN'),
    ('कल क्या लाना है?', 'hi-IN'),
    ('इसे दो छोटे वाक्यों में समझाओ।', 'hi-IN'),
    ('kal kya lana hai?', 'hi-IN'),
    ('isko do chhote vakyon mein samjhao', 'hi-IN'),
    ('நாளை என்ன கொண்டு வர வேண்டும்?', 'ta-IN'),
    ('రేపు ఏమి తీసుకురావాలి?', 'te-IN'),
    ('আগামীকাল কী আনতে হবে?', 'bn-IN'),
    ('उद्या काय आणायचे आहे?', 'mr-IN'),
    ('કાલે શું લાવવાનું છે?', 'gu-IN'),
    ('What should I bring? Reply in Telugu.', 'te-IN'),
    ('Explain this in Hindi.', 'hi-IN'),
    ('मराठी में बताओ', None),  # Explicit native-language request: model decides.
    ('अंग्रेजी में समझाओ', None),
    ('Do not reply in Hindi.', None),
    ('The teacher said "reply in Hindi"', None),
    ('42', None),
    ('👍', None),
    ('नमस्कार', None),  # Shared Hindi/Marathi greeting is ambiguous.
    ('repu emi teesukuravali?', 'te-IN'),
    ('naalai enna kondu varanum?', 'ta-IN'),
])
def test_hint_uses_only_clear_current_input(text, expected):
    assert language_hint(text) == expected
