"""Deterministic app copy. Source content is never translated by this module."""
from __future__ import annotations

import re

# English strings are stable keys as well as the fallback for other languages.
COPY = {}


def register(en, hi, ta):
    COPY[en] = {'en': en, 'hi': hi, 'ta': ta}


def language(text='', fallback='en-IN', stt=None):
    """Current script wins; ASCII prose is English. Unheard audio uses roster.

    Romanized Indian languages cannot reliably be detected without a model;
    recognized greeting/shortcut aliases below are the deliberate exception.
    """
    if re.search(r'[\u0b80-\u0bff]', text):
        return 'ta-IN'
    if re.search(r'[\u0900-\u097f]', text):
        # Devanagari is shared with Marathi; retain an explicit STT/roster signal.
        if (stt or fallback).split('-')[0] == 'mr':
            return stt or fallback
        return 'hi-IN'
    if stt and stt.split('-')[0] != 'en':
        return stt
    if text.strip().casefold().strip('!.? ') in {'namaste', 'namaskar'}:
        return 'hi-IN'
    if text.strip().casefold().strip('!.? ') == 'vanakkam':
        return 'ta-IN'
    if re.search(r'[A-Za-z]', text):
        return 'en-IN'
    return stt or fallback or 'en-IN'


def message(en, lang='en-IN', **values):
    template = COPY.get(en, {}).get(lang.split('-')[0], en)
    return template.format(**values) if values else template


register('Hi! I’m Octo. I can help with saved school notices.', 'नमस्ते! मैं Octo हूँ। मैं सहेजी गई स्कूल सूचनाओं में मदद कर सकता हूँ।', 'வணக்கம்! நான் Octo. சேமித்த பள்ளி அறிவிப்புகளைப் பற்றி உதவ முடியும்.')
register('Linked children: {names}', 'जुड़े बच्चे: {names}', 'இணைக்கப்பட்ட குழந்தைகள்: {names}')
register('Class-wide notices: {classes}', 'पूरी कक्षा की सूचनाएँ: {classes}', 'முழு வகுப்பு அறிவிப்புகள்: {classes}')
register('Try: Tomorrow · Next test · Find notes', 'पूछें: कल · अगली परीक्षा · नोट्स खोजें', 'கேளுங்கள்: நாளை · அடுத்த தேர்வு · குறிப்புகளைத் தேடு')
register('What is scheduled or needed tomorrow? Include any uncertainty in the saved notices.', 'कल के लिए क्या निर्धारित है या क्या चाहिए? सहेजी गई सूचनाओं में कोई अनिश्चितता हो तो बताएँ।', 'நாளை என்ன திட்டமிடப்பட்டுள்ளது அல்லது என்ன தேவை? சேமித்த அறிவிப்புகளில் உள்ள உறுதியற்ற தகவல்களையும் கூறுங்கள்.')
register('When is the next test explicitly mentioned in the saved notices? If no test is confirmed, say so.', 'सहेजी गई सूचनाओं में स्पष्ट रूप से बताई गई अगली परीक्षा कब है? कोई परीक्षा पक्की नहीं है तो बताएँ।', 'சேமித்த அறிவிப்புகளில் வெளிப்படையாகக் குறிப்பிடப்பட்ட அடுத்த தேர்வு எப்போது? தேர்வு உறுதிப்படுத்தப்படவில்லை என்றால் கூறுங்கள்.')
register('Find the saved class notes and share an available document link. If no document is available, say so.', 'सहेजे गए कक्षा नोट्स खोजें और उपलब्ध दस्तावेज़ का लिंक दें। दस्तावेज़ उपलब्ध नहीं है तो बताएँ।', 'சேமித்த வகுப்புக் குறிப்புகளைக் கண்டறிந்து கிடைக்கும் ஆவண இணைப்பைப் பகிருங்கள். ஆவணம் இல்லை என்றால் கூறுங்கள்.')
register('Which subject? {subjects}. Please include the subject in your question.', 'कौन-सा विषय? {subjects}। कृपया सवाल में विषय लिखें।', 'எந்தப் பாடம்? {subjects}. கேள்வியில் பாடத்தையும் குறிப்பிடுங்கள்.')
register('Which student do you mean: {names}? Please include the name in your question.', 'किस बच्चे के बारे में पूछ रहे हैं: {names}? कृपया सवाल में नाम लिखें।', 'எந்தக் குழந்தையைப் பற்றிக் கேட்கிறீர்கள்: {names}? கேள்வியில் பெயரையும் குறிப்பிடுங்கள்.')
register('I do not have saved school information for your class yet. Ask the teacher to post a notice in the demo group.', 'आपकी कक्षा की स्कूल जानकारी अभी सहेजी नहीं गई है। शिक्षक से डेमो समूह में सूचना भेजने को कहें।', 'உங்கள் வகுப்பிற்கான பள்ளித் தகவல் இன்னும் சேமிக்கப்படவில்லை. டெமோ குழுவில் அறிவிப்பை அனுப்ப ஆசிரியரிடம் கேளுங்கள்.')
register('I can only answer individual questions about students linked to your account. You can ask about class-wide notices here.', 'मैं केवल आपके खाते से जुड़े बच्चों के व्यक्तिगत सवालों का जवाब दे सकता हूँ। यहाँ पूरी कक्षा की सूचनाएँ पूछ सकते हैं।', 'உங்கள் கணக்குடன் இணைக்கப்பட்ட குழந்தைகளைப் பற்றிய தனிப்பட்ட கேள்விகளுக்கு மட்டுமே பதிலளிக்க முடியும். முழு வகுப்பு அறிவிப்புகளைப் பற்றி இங்கே கேட்கலாம்.')
register('I could not verify an answer against the saved notices. Please ask again or ask the teacher to clarify.', 'सहेजी गई सूचनाओं से जवाब की पुष्टि नहीं हो सकी। कृपया फिर पूछें या शिक्षक से स्पष्ट करने को कहें।', 'சேமித்த அறிவிப்புகளுடன் பதிலைச் சரிபார்க்க முடியவில்லை. மீண்டும் கேளுங்கள் அல்லது ஆசிரியரிடம் விளக்கம் கேளுங்கள்.')
register('Please ask the teacher to post the syllabus photo in the demo class group. You can ask me about saved school information here.', 'शिक्षक से पाठ्यक्रम की फ़ोटो डेमो कक्षा समूह में भेजने को कहें। यहाँ सहेजी गई स्कूल जानकारी पूछ सकते हैं।', 'பாடத்திட்டப் படத்தை டெமோ வகுப்புக் குழுவில் அனுப்ப ஆசிரியரிடம் கேளுங்கள். சேமித்த பள்ளித் தகவல்களை இங்கே கேட்கலாம்.')
register('Please send text, a short voice note, a board photo or a PDF.', 'कृपया लिखकर, छोटे वॉइस नोट, बोर्ड की फ़ोटो या PDF से संदेश भेजें।', 'எழுத்து, சிறிய குரல் செய்தி, பலகைப் படம் அல்லது PDF அனுப்புங்கள்.')
register('📄 Reading your PDF…', '📄 आपका PDF पढ़ रहा हूँ…', '📄 உங்கள் PDF-ஐப் படிக்கிறேன்…')
register('📷 Reading your photo…', '📷 आपकी फ़ोटो पढ़ रहा हूँ…', '📷 உங்கள் படத்தைப் படிக்கிறேன்…')
register('The syllabus photo is still processing. I will send the result when it is ready.', 'पाठ्यक्रम की फ़ोटो अभी पढ़ी जा रही है। तैयार होने पर परिणाम भेजूँगा।', 'பாடத்திட்டப் படம் இன்னும் செயலாக்கப்படுகிறது. தயாரானதும் முடிவை அனுப்புவேன்.')
register('The written answer is ready, but audio is unavailable right now.', 'लिखित जवाब तैयार है, लेकिन ऑडियो अभी उपलब्ध नहीं है।', 'எழுத்துப் பதில் தயார், ஆனால் இப்போது ஒலி கிடைக்கவில்லை.')
register('Audio is skipped in offline mode; no Sarvam speech was generated.', 'ऑफ़लाइन मोड में ऑडियो नहीं बनता; Sarvam से आवाज़ नहीं बनाई गई।', 'ஆஃப்லைன் முறையில் ஒலி தவிர்க்கப்படுகிறது; Sarvam குரல் உருவாக்கப்படவில்லை.')
register('Please send cart commands in a direct message to me.', 'कार्ट के आदेश मुझे निजी संदेश में भेजें।', 'கூடை கட்டளைகளை எனக்குத் தனிச் செய்தியில் அனுப்புங்கள்.')
register('*I couldn’t hear that clearly*\n\nPlease record a short voice note again, or type your message.', '*आवाज़ साफ़ सुनाई नहीं दी*\n\nकृपया छोटा वॉइस नोट फिर भेजें या संदेश लिखें।', '*தெளிவாகக் கேட்கவில்லை*\n\nசிறிய குரல் செய்தியை மீண்டும் பதிவு செய்யுங்கள் அல்லது எழுதுங்கள்.')
register('*Couldn’t finish that*', '*यह पूरा नहीं हो सका*', '*முடிக்க முடியவில்லை*')
register('The service could not finish that request. Please try again shortly.', 'सेवा यह अनुरोध पूरा नहीं कर सकी। कृपया थोड़ी देर बाद फिर कोशिश करें।', 'சேவையால் கோரிக்கையை முடிக்க முடியவில்லை. சிறிது நேரம் கழித்து மீண்டும் முயலுங்கள்.')
register('Please send a voice note shorter than 30 seconds.', 'कृपया 30 सेकंड से छोटा वॉइस नोट भेजें।', '30 வினாடிகளுக்குக் குறைவான குரல் செய்தியை அனுப்புங்கள்.')
register('Please send a PDF document, or a JPEG/PNG board photo.', 'कृपया PDF दस्तावेज़ या बोर्ड की JPEG/PNG फ़ोटो भेजें।', 'PDF ஆவணம் அல்லது பலகையின் JPEG/PNG படத்தை அனுப்புங்கள்.')
register('Saved media is unavailable. Please resend it.', 'सहेजा गया मीडिया उपलब्ध नहीं है। कृपया फिर भेजें।', 'சேமித்த ஊடகம் கிடைக்கவில்லை. மீண்டும் அனுப்புங்கள்.')
register('This message has no downloadable media. Please resend it.', 'इस संदेश का मीडिया डाउनलोड नहीं हो सकता। कृपया फिर भेजें।', 'இந்தச் செய்தியில் பதிவிறக்கக்கூடிய ஊடகம் இல்லை. மீண்டும் அனுப்புங்கள்.')
register('*Notice not saved*\n\nI can save supplies, study topics and class-day notices.\n\nSpecific lesson, test or practice changes are not supported yet.', '*सूचना सहेजी नहीं गई*\n\nमैं सामग्री, पढ़ाई के विषय और पूरी कक्षा के दिन की सूचनाएँ सहेज सकता हूँ।\n\nअलग पाठ, परीक्षा या अभ्यास के बदलाव अभी समर्थित नहीं हैं।', '*அறிவிப்பு சேமிக்கப்படவில்லை*\n\nபொருட்கள், படிப்புத் தலைப்புகள் மற்றும் முழு வகுப்பு நாள் அறிவிப்புகளைச் சேமிக்க முடியும்.\n\nதனிப் பாடம், தேர்வு அல்லது பயிற்சி மாற்றங்கள் இன்னும் ஆதரிக்கப்படவில்லை.')

for en, hi, ta in [
    ('No classes', 'कक्षाएँ नहीं होंगी', 'வகுப்புகள் இல்லை'),
    ('Classes as usual', 'कक्षाएँ सामान्य रूप से होंगी', 'வழக்கம்போல் வகுப்புகள்'),
    ('Activity cancelled', 'गतिविधि रद्द', 'செயல்பாடு ரத்து'),
    ('Marked complete', 'पूरा हुआ चिह्नित', 'முடிந்ததாகக் குறிக்கப்பட்டது'),
    ('What to bring', 'क्या लाना है', 'என்ன கொண்டுவர வேண்டும்'),
    ('Study checklist', 'पढ़ाई की सूची', 'படிப்புப் பட்டியல்'),
    ('Class notes', 'कक्षा के नोट्स', 'வகுப்புக் குறிப்புகள்'),
    ('School update', 'स्कूल की सूचना', 'பள்ளி அறிவிப்பு'),
    ('Class', 'कक्षा', 'வகுப்பு'), ('Chapter', 'अध्याय', 'அத்தியாயம்'),
    ('Pages', 'पृष्ठ', 'பக்கங்கள்'), ('Remember', 'याद रखें', 'நினைவில் கொள்ளுங்கள்'),
    ('Please confirm', 'कृपया पुष्टि करें', 'உறுதிப்படுத்துங்கள்'),
    ('Date to confirm', 'तारीख़ की पुष्टि चाहिए', 'தேதியை உறுதிப்படுத்த வேண்டும்'),
    ('Please confirm the full date, including the year.', 'कृपया वर्ष सहित पूरी तारीख़ की पुष्टि करें।', 'ஆண்டு உட்பட முழுத் தேதியை உறுதிப்படுத்துங்கள்.'),
    ('Reminder scheduled.', 'रिमाइंडर निर्धारित है।', 'நினைவூட்டல் திட்டமிடப்பட்டுள்ளது.'),
    ('Saved', 'सहेजा गया', 'சேமிக்கப்பட்டது'),
    ('SIMULATED — no purchase made.', 'सिमुलेशन — कोई खरीदारी नहीं हुई।', 'மாதிரி செயல்பாடு — எதுவும் வாங்கப்படவில்லை.'),
    ('Fixed demo prices; no merchant connection.', 'डेमो की तय कीमतें; किसी विक्रेता से संपर्क नहीं।', 'நிலையான டெமோ விலைகள்; வணிகர் இணைப்பு இல்லை.'),
    ('*Reply with one action* · expires in 10 minutes', '*एक आदेश भेजें* · 10 मिनट में समाप्त', '*ஒரு செயலைப் பதிலளிக்கவும்* · 10 நிமிடங்களில் காலாவதியாகும்'),
]:
    register(en, hi, ta)


def cart_chrome(text, lang):
    # Exact whole-line substitutions only: codes, commands, amounts and item
    # names are untouched. Untranslated safety warnings remain explicit English.
    return '\n'.join(message(line, lang) for line in text.split('\n'))

register('Please confirm this forwarded notice in a fresh class message with the relevant date. I have not changed the class records.', 'कृपया इस फ़ॉरवर्ड की गई सूचना की सही तारीख़ के साथ नए कक्षा संदेश में पुष्टि करें। मैंने कक्षा के रिकॉर्ड नहीं बदले हैं।', 'இந்தப் பகிரப்பட்ட அறிவிப்பை உரிய தேதியுடன் புதிய வகுப்புச் செய்தியில் உறுதிப்படுத்துங்கள். வகுப்புப் பதிவுகளை நான் மாற்றவில்லை.')
register('This demo saves class-wide notices only. Please send a class-wide requirement without individual student details.', 'यह डेमो केवल पूरी कक्षा की सूचनाएँ सहेजता है। व्यक्तिगत छात्र विवरण के बिना पूरी कक्षा की आवश्यकता भेजें।', 'இந்த டெமோ முழு வகுப்பு அறிவிப்புகளை மட்டுமே சேமிக்கிறது. தனிப்பட்ட மாணவர் விவரமின்றி முழு வகுப்புத் தேவையை அனுப்புங்கள்.')
register('I could not identify school requirements, syllabus topics or lesson notes in this attachment. Please send the actual school notice or a clearer photo of the notes; nothing was saved.', 'इस संलग्नक में स्कूल की आवश्यकताएँ, पाठ्यक्रम या पाठ के नोट्स पहचान नहीं सका। असली स्कूल सूचना या नोट्स की साफ़ फ़ोटो भेजें; कुछ भी सहेजा नहीं गया।', 'இந்த இணைப்பில் பள்ளித் தேவைகள், பாடத்திட்டம் அல்லது பாடக் குறிப்புகளை அடையாளம் காண முடியவில்லை. உண்மையான பள்ளி அறிவிப்பு அல்லது தெளிவான குறிப்புப் படத்தை அனுப்புங்கள்; எதுவும் சேமிக்கப்படவில்லை.')
register('The class written in this notice differs from this group. Please confirm the correct class before I save it.', 'इस सूचना में लिखी कक्षा इस समूह से अलग है। सहेजने से पहले सही कक्षा की पुष्टि करें।', 'இந்த அறிவிப்பில் உள்ள வகுப்பு இந்தக் குழுவிலிருந்து வேறுபடுகிறது. சேமிக்கும் முன் சரியான வகுப்பை உறுதிப்படுத்துங்கள்.')
register('I have not changed the class-day record. Please confirm whether the whole class has no classes or classes as usual, and give the date. Send any supplies or syllabus in a separate notice.', 'मैंने कक्षा के दिन का रिकॉर्ड नहीं बदला है। तारीख़ सहित पुष्टि करें कि पूरी कक्षा की छुट्टी है या कक्षाएँ सामान्य रूप से होंगी। सामग्री या पाठ्यक्रम अलग सूचना में भेजें।', 'வகுப்பு நாள் பதிவை நான் மாற்றவில்லை. முழு வகுப்பிற்கும் வகுப்புகள் இல்லையா அல்லது வழக்கம்போல் உள்ளதா என்பதைத் தேதியுடன் உறுதிப்படுத்துங்கள். பொருட்கள் அல்லது பாடத்திட்டத்தைத் தனி அறிவிப்பாக அனுப்புங்கள்.')
register('Which date does this class-day notice apply to? Please resend the full notice with the date; I have not changed the class-day record.', 'यह कक्षा-दिन सूचना किस तारीख़ के लिए है? तारीख़ सहित पूरी सूचना फिर भेजें; मैंने कक्षा के दिन का रिकॉर्ड नहीं बदला है।', 'இந்த வகுப்பு நாள் அறிவிப்பு எந்தத் தேதிக்கானது? தேதியுடன் முழு அறிவிப்பையும் மீண்டும் அனுப்புங்கள்; வகுப்பு நாள் பதிவை நான் மாற்றவில்லை.')
register('The document service is taking too long. The photo is retained; please retry later.', 'दस्तावेज़ सेवा में अधिक समय लग रहा है। फ़ोटो रखी गई है; कृपया बाद में फिर कोशिश करें।', 'ஆவணச் சேவை அதிக நேரம் எடுக்கிறது. படம் பாதுகாக்கப்பட்டுள்ளது; பின்னர் மீண்டும் முயலுங்கள்.')
register('The document service could not process this photo. Please try again or send a clearer photo.', 'दस्तावेज़ सेवा यह फ़ोटो पढ़ नहीं सकी। फिर कोशिश करें या साफ़ फ़ोटो भेजें।', 'ஆவணச் சேவையால் இந்தப் படத்தைச் செயலாக்க முடியவில்லை. மீண்டும் முயலுங்கள் அல்லது தெளிவான படத்தை அனுப்புங்கள்.')
register('The document service returned an unexpected status. Please retry later.', 'दस्तावेज़ सेवा से अप्रत्याशित स्थिति मिली। कृपया बाद में फिर कोशिश करें।', 'ஆவணச் சேவை எதிர்பாராத நிலையைத் தந்தது. பின்னர் மீண்டும் முயலுங்கள்.')
register('This photo contains an individual student name. This demo saves class-wide syllabus notices only; please send a class-wide notice without individual details.', 'इस फ़ोटो में एक छात्र का नाम है। यह डेमो केवल पूरी कक्षा का पाठ्यक्रम सहेजता है; व्यक्तिगत विवरण के बिना पूरी कक्षा की सूचना भेजें।', 'இந்தப் படத்தில் ஒரு மாணவரின் பெயர் உள்ளது. இந்த டெமோ முழு வகுப்புப் பாடத்திட்ட அறிவிப்புகளை மட்டுமே சேமிக்கிறது; தனிப்பட்ட விவரங்கள் இல்லாத வகுப்பு அறிவிப்பை அனுப்புங்கள்.')


def requested_language(text):
    """Read supported language names only after a language-only intent."""
    for code, pattern in [('hi-IN', r'\bhindi\b|हिंदी|हिन्दी'),
                          ('ta-IN', r'\btamil\b|தமிழ்'),
                          ('en-IN', r'\benglish\b|अंग्रेज़ी|ஆங்கிலம்')]:
        if re.search(pattern, text, re.I):
            return code
    return None

register('🎙️ Processing your voice message…', '🎙️ आपका वॉइस संदेश समझ रहा हूँ…', '🎙️ உங்கள் குரல் செய்தியைப் புரிந்துகொள்கிறேன்…')
register('Which notice or student do you mean? Please ask the full question.', 'किस सूचना या बच्चे के बारे में पूछ रहे हैं? कृपया पूरा सवाल पूछें।', 'எந்த அறிவிப்பு அல்லது குழந்தையைப் பற்றிக் கேட்கிறீர்கள்? முழுக் கேள்வியையும் கேளுங்கள்.')
register('Please ask the full question for a student linked to your account.', 'कृपया अपने खाते से जुड़े बच्चे के लिए पूरा सवाल पूछें।', 'உங்கள் கணக்குடன் இணைக்கப்பட்ட குழந்தைக்கான முழுக் கேள்வியையும் கேளுங்கள்.')
register('The previous selection is no longer available. Please ask the full question.', 'पिछला चयन अब उपलब्ध नहीं है। कृपया पूरा सवाल पूछें।', 'முந்தைய தேர்வு இப்போது கிடைக்கவில்லை. முழுக் கேள்வியையும் கேளுங்கள்.')
register('Which of the previous notices do you mean? Please name its topic and date.', 'पिछली किस सूचना के बारे में पूछ रहे हैं? कृपया उसका विषय और तारीख़ बताएँ।', 'முந்தைய அறிவிப்புகளில் எதைக் குறிப்பிடுகிறீர்கள்? அதன் தலைப்பையும் தேதியையும் கூறுங்கள்.')
register('The date is saved on the original notice.', 'तारीख़ मूल सूचना में सहेज दी गई है।', 'மூல அறிவிப்பில் தேதி சேமிக்கப்பட்டது.')
register('Please send the full corrected notice with a valid date and year.', 'कृपया सही तारीख़ और वर्ष के साथ पूरी संशोधित सूचना भेजें।', 'சரியான தேதி மற்றும் ஆண்டுடன் முழுத் திருத்தப்பட்ட அறிவிப்பை அனுப்புங்கள்.')
register('Please send the full corrected notice with its date; I cannot identify one pending notice.', 'कृपया तारीख़ सहित पूरी संशोधित सूचना भेजें; मैं एक लंबित सूचना की पहचान नहीं कर पा रहा हूँ।', 'தேதியுடன் முழுத் திருத்தப்பட்ட அறிவிப்பை அனுப்புங்கள்; ஒரே ஒரு நிலுவை அறிவிப்பை என்னால் அடையாளம் காண முடியவில்லை.')
register('That notice has changed. Please send the full corrected notice.', 'वह सूचना बदल गई है। कृपया पूरी संशोधित सूचना भेजें।', 'அந்த அறிவிப்பு மாறியுள்ளது. முழுத் திருத்தப்பட்ட அறிவிப்பை அனுப்புங்கள்.')
register('Which date (including year) applies? Reply with just the date. If several notices are pending, send a full corrected notice.', 'कौन-सी तारीख़ और वर्ष लागू हैं? केवल तारीख़ भेजें। कई सूचनाएँ लंबित हों तो पूरी संशोधित सूचना भेजें।', 'எந்த தேதி மற்றும் ஆண்டு பொருந்தும்? தேதியை மட்டும் அனுப்புங்கள். பல அறிவிப்புகள் நிலுவையில் இருந்தால் முழுத் திருத்தப்பட்ட அறிவிப்பை அனுப்புங்கள்.')
register('Which date does this class-day notice apply to? Reply with the date; I have not changed the class-day record.', 'यह कक्षा-दिन सूचना किस तारीख़ के लिए है? तारीख़ भेजें; मैंने कक्षा के दिन का रिकॉर्ड नहीं बदला है।', 'இந்த வகுப்பு நாள் அறிவிப்பு எந்தத் தேதிக்கானது? தேதியை அனுப்புங்கள்; வகுப்பு நாள் பதிவை நான் மாற்றவில்லை.')
register('The school record is saved, but Google Calendar synchronization is unconfirmed after three attempts. Automatic retries have stopped; check the demo calendar and OAuth setup.', 'स्कूल रिकॉर्ड सहेजा गया है, लेकिन तीन कोशिशों के बाद भी Google Calendar सिंक की पुष्टि नहीं हुई है। अपने-आप फिर कोशिश करना बंद हो गया है; डेमो कैलेंडर और OAuth सेटअप जाँचें।', 'பள்ளிப் பதிவு சேமிக்கப்பட்டது, ஆனால் மூன்று முயற்சிகளுக்குப் பிறகும் Google Calendar ஒத்திசைவு உறுதியாகவில்லை. தானியங்கி மறுமுயற்சிகள் நிறுத்தப்பட்டன; டெமோ நாட்காட்டி மற்றும் OAuth அமைப்பைச் சரிபாருங்கள்.')
register('The written answer is ready, but audio delivery was not confirmed. Please check the chat before retrying.', 'लिखित जवाब तैयार है, लेकिन ऑडियो पहुँचने की पुष्टि नहीं हुई। फिर कोशिश करने से पहले चैट जाँचें।', 'எழுத்து வடிவிலான பதில் தயார், ஆனால் ஒலி அனுப்பப்பட்டது உறுதியாகவில்லை. மீண்டும் முயலும் முன் அரட்டையைச் சரிபாருங்கள்.')
