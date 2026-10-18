"""Conservative, local language hints for clear current messages only.

Ambiguous text stays with the answer model. This is not a general language
detector, and never reads a profile, teacher notice, quote, or previous turn.
"""
import re


LANGUAGE_NAMES = {
    'en-IN': 'English', 'hi-IN': 'Hindi', 'bn-IN': 'Bengali', 'ta-IN': 'Tamil',
    'te-IN': 'Telugu', 'mr-IN': 'Marathi', 'gu-IN': 'Gujarati', 'kn-IN': 'Kannada',
    'ml-IN': 'Malayalam', 'pa-IN': 'Punjabi', 'od-IN': 'Odia',
}
SCRIPTS = {
    'bn-IN': (0x0980, 0x09FF), 'ta-IN': (0x0B80, 0x0BFF),
    'te-IN': (0x0C00, 0x0C7F), 'gu-IN': (0x0A80, 0x0AFF),
    'kn-IN': (0x0C80, 0x0CFF), 'ml-IN': (0x0D00, 0x0D7F),
    'pa-IN': (0x0A00, 0x0A7F), 'od-IN': (0x0B00, 0x0B7F),
}
ROMANIZED = {
    'hi-IN': set('kya kyun kyu kaise kab kal lana chahiye hai hain mujhe batao bataye samjhao isko mein karo'.split()),
    'mr-IN': set('udya kay aahe ahet mala sanga samjavun anayche'.split()),
    'ta-IN': set('enna naalai nalai venum vendum kondu varanum sollunga'.split()),
    'te-IN': set('repu emi emiti kavali teesukovali teesukuravali cheppandi'.split()),
    'bn-IN': set('agamikal ki ante hobe amake bolun bujhiye'.split()),
    'gu-IN': set('kaale kale shu lavanu chhe mane samjavo'.split()),
}
ENGLISH = set('i my we our you your what whats when where why which how can could would '
              'should is are do does did the this that these those please explain summarize '
              'tell me more about bring need next tomorrow today time in two short sentences '
              'hi hello hey ok okay thanks thank yes no continue help again'.split())
HINDI = set('क्या कब कहाँ कैसे कल है हैं मुझे हमें इसे में समझाओ समझाइए बताओ बताइए लाना चाहिए'.split())
MARATHI = set('काय कधी कुठे कसा कशी कसे उद्या आहे आहेत मला आम्ही तुम्ही सांगा समजावून आणायचे आणायचं'.split())


def language_hint(text: str, *, allow_requests: bool = True) -> str | None:
    if allow_requests:
        names = '|'.join(LANGUAGE_NAMES.values())
        # Only a current imperative, not a mention such as "the teacher speaks
        # Hindi". More complex/native-language requests are left to the model.
        match = re.search(r'(?:^|[.!?]\s*)(?:please\s+)?(?:reply|answer|respond|speak|write|explain|translate)'
                          r'[^.!?\n]{0,100}?\b(?:in|into)\s+(' + names + r')\b', text, re.I)
        if match and not re.search(r"\b(?:not|don.t|never|instead)\b", match[0], re.I):
            return next(code for code, name in LANGUAGE_NAMES.items() if name.casefold() == match[1].casefold())
        if re.search(r'\b(?:' + names + r')\b|अंग्रेज़ी|अंग्रेजी|हिंदी|हिन्दी|मराठी|தமிழ்|తెలుగు|বাংলা|ગુજરાતી', text, re.I):
            return None
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    for code, (start, end) in SCRIPTS.items():
        if sum(start <= ord(c) <= end for c in letters) > len(letters) / 2:
            return code
    if sum(0x0900 <= ord(c) <= 0x097F for c in letters) > len(letters) / 2:
        words = set(re.findall(r'[\u0900-\u097f]+', text))
        hindi, marathi = len(words & HINDI), len(words & MARATHI)
        return 'hi-IN' if hindi > marathi else 'mr-IN' if marathi > hindi else None
    words = set(re.findall(r'[a-z]+', text.casefold()))
    ranked = sorted(((len(words & markers), code) for code, markers in ROMANIZED.items()), reverse=True)
    if ranked[0][0] >= 2 and ranked[0][0] > ranked[1][0]:
        return ranked[0][1]
    if words and (len(words & ENGLISH) >= 2 or (len(words) == 1 and words <= ENGLISH)):
        return 'en-IN'
    return None
