"""Compact text-menu chrome. School answers keep their own detected language."""
COPY = {
    'en': {
        'main': '*Octo · School help*\n\n1 · Today\n2 · Tomorrow\n3 · Notes\n4 · Settings\n\nReply with a number, or ask a question in your own words.',
        'footer': '1 · Read aloud\n2 · Show sources & links\n3 · Ask another question\n0 · Main menu',
        'settings': '*Settings*\n\n1 · Language\n2 · Audio replies\n0 · Main menu',
        'languages': '*Menu language*\n\n1 · English\n2 · हिंदी\n3 · தமிழ்\n0 · Main menu',
        'audio': '*Audio replies*\n\n1 · Text only for typed questions\n2 · Text + audio for typed questions\n\nVoice questions still get text + audio in private chat.\n0 · Main menu',
        'saved': '✓ Preference saved.',
        'ask': 'Send your next question in your own words.\n0 · Main menu',
        'choose': '*Which child?*',
        'hint': 'Reply with a number. 0 · Main menu',
        'expired': 'That choice is no longer available. Please choose from this menu.',
        'fresh': 'Please send a new typed choice from the current menu.',
        'group': 'Send me “menu” in a private chat for choices and preferences. You can still ask class-wide questions here.',
        'stale': 'That answer is no longer current. Please ask again for the latest saved notices.',
        'sources': 'Saved sources for this answer:',
        'offline': 'Audio is skipped in offline mode; no Sarvam speech was generated.',
        'audio_failed': 'The written answer is ready, but audio is unavailable right now.',
        'audio_ready': '🔊 Reading the answer aloud.',
        'teacher': 'Post a class-wide notice, a short voice note, a board photo or a PDF here. Include the date when it matters. Parent menus are available in private chat.',
    },
    'hi': {
        'main': '*Octo · स्कूल की जानकारी*\n\n1 · आज\n2 · कल\n3 · नोट्स\n4 · सेटिंग्स\n\nनंबर भेजें या अपने शब्दों में सवाल पूछें।',
        'footer': '1 · सुनाएँ\n2 · स्रोत और लिंक दिखाएँ\n3 · अगला सवाल\n0 · मुख्य मेन्यू',
        'settings': '*सेटिंग्स*\n\n1 · भाषा\n2 · ऑडियो जवाब\n0 · मुख्य मेन्यू',
        'languages': '*मेन्यू की भाषा*\n\n1 · English\n2 · हिंदी\n3 · தமிழ்\n0 · मुख्य मेन्यू',
        'audio': '*ऑडियो जवाब*\n\n1 · लिखे सवालों का केवल लिखित जवाब\n2 · लिखे सवालों का लिखित और ऑडियो जवाब\n\nनिजी चैट में वॉइस सवालों के लिखित और ऑडियो जवाब मिलेंगे।\n0 · मुख्य मेन्यू',
        'saved': '✓ पसंद सेव हो गई।',
        'ask': 'अपना अगला सवाल लिखें।\n0 · मुख्य मेन्यू',
        'choose': '*किस बच्चे के लिए?*',
        'hint': 'नंबर भेजें। 0 · मुख्य मेन्यू',
        'expired': 'यह विकल्प अब उपलब्ध नहीं है। इस मेन्यू से चुनें।',
        'fresh': 'कृपया मौजूदा मेन्यू का नंबर नए संदेश में लिखें।',
        'group': 'विकल्प और सेटिंग्स के लिए निजी चैट में “menu” भेजें। यहाँ पूरी कक्षा के बारे में सवाल पूछ सकते हैं।',
        'stale': 'यह जवाब अब पुराना है। ताज़ा जानकारी के लिए दोबारा सवाल पूछें।',
        'sources': 'इस जवाब के सेव किए हुए स्रोत:',
        'offline': 'ऑफ़लाइन मोड में ऑडियो नहीं बनाया जाता।',
        'audio_failed': 'लिखित जवाब तैयार है, लेकिन अभी ऑडियो उपलब्ध नहीं है।',
        'audio_ready': '🔊 जवाब सुनाया जा रहा है।',
        'teacher': 'यहाँ पूरी कक्षा का नोटिस, छोटा वॉइस संदेश, बोर्ड की फोटो या PDF भेजें। ज़रूरी तारीख भी लिखें। अभिभावक मेन्यू निजी चैट में उपलब्ध हैं।',
    },
    'ta': {
        'main': '*Octo · பள்ளி உதவி*\n\n1 · இன்று\n2 · நாளை\n3 · குறிப்புகள்\n4 · அமைப்புகள்\n\nஎண்ணை அனுப்பவும் அல்லது உங்கள் சொற்களில் கேள்வி கேட்கவும்.',
        'footer': '1 · வாசித்துக் காட்டு\n2 · ஆதாரங்கள் மற்றும் இணைப்புகள்\n3 · அடுத்த கேள்வி\n0 · முதன்மை பட்டியல்',
        'settings': '*அமைப்புகள்*\n\n1 · மொழி\n2 · ஒலி பதில்கள்\n0 · முதன்மை பட்டியல்',
        'languages': '*பட்டியல் மொழி*\n\n1 · English\n2 · हिंदी\n3 · தமிழ்\n0 · முதன்மை பட்டியல்',
        'audio': '*ஒலி பதில்கள்*\n\n1 · எழுதிய கேள்விகளுக்கு எழுத்து பதில் மட்டும்\n2 · எழுதிய கேள்விகளுக்கு எழுத்து + ஒலி பதில்\n\nதனிப்பட்ட அரட்டையில் குரல் கேள்விகளுக்கு எழுத்து + ஒலி பதில் கிடைக்கும்.\n0 · முதன்மை பட்டியல்',
        'saved': '✓ விருப்பம் சேமிக்கப்பட்டது.',
        'ask': 'அடுத்த கேள்வியை உங்கள் சொற்களில் அனுப்பவும்.\n0 · முதன்மை பட்டியல்',
        'choose': '*எந்தக் குழந்தைக்கு?*',
        'hint': 'எண்ணை அனுப்பவும். 0 · முதன்மை பட்டியல்',
        'expired': 'இந்தத் தேர்வு இனி கிடைக்காது. இந்தப் பட்டியலில் இருந்து தேர்ந்தெடுக்கவும்.',
        'fresh': 'தற்போதைய பட்டியலின் எண்ணைப் புதிய செய்தியாகத் தட்டச்சு செய்யவும்.',
        'group': 'விருப்பங்களுக்கு தனிப்பட்ட அரட்டையில் “menu” அனுப்பவும். இங்கே வகுப்பு பற்றிய கேள்விகளைக் கேட்கலாம்.',
        'stale': 'அந்தப் பதில் இப்போது பழையது. சமீபத்திய தகவலுக்கு மீண்டும் கேட்கவும்.',
        'sources': 'இந்தப் பதிலுக்கான சேமிக்கப்பட்ட ஆதாரங்கள்:',
        'offline': 'ஆஃப்லைன் முறையில் ஒலி உருவாக்கப்படாது.',
        'audio_failed': 'எழுத்து பதில் தயாராக உள்ளது. இப்போது ஒலி கிடைக்கவில்லை.',
        'audio_ready': '🔊 பதில் வாசிக்கப்படுகிறது.',
        'teacher': 'வகுப்பு அறிவிப்பு, சிறிய குரல் செய்தி, பலகைப் படம் அல்லது PDF அனுப்பவும். தேவையான தேதியைக் குறிப்பிடவும். பெற்றோர் பட்டியல் தனிப்பட்ட அரட்டையில் கிடைக்கும்.',
    },
}


def copy(key, language):
    return COPY.get(language.split('-')[0], COPY['en'])[key]


def menu_language(text, parent):
    if any('\u0b80' <= c <= '\u0bff' for c in text):
        return 'ta-IN'
    if any('\u0900' <= c <= '\u097f' for c in text):
        return 'hi-IN'
    if any(c.isascii() and c.isalpha() for c in text):
        return 'en-IN'
    return parent.get('language', 'en-IN')
