"""The helper assistant in Hindi. Same rules and the same limits as the English one: it reads back what is on record, never advises, and sends advice
questions and emergencies to a fixed line. It understands Devanagari and Hinglish (Hindi in Latin letters) and answers in Devanagari. The guarded
model path is switched off for Hindi, because the advice and number checks that make a model answer safe are written for English text: a question
the rules do not cover gets the help text instead of a model guess."""
from __future__ import annotations

import re
import unicodedata

from .assistant import ADD, _title, _who

_re = lambda p, f=re.I: re.compile(unicodedata.normalize('NFC', p), f)
EMERGENCY_LINE = "अगर यह आपातकाल है, तो अभी अपने स्थानीय आपातकालीन नंबर पर फ़ोन करें (भारत और यूरोप में 112, अमेरिका और कनाडा में 911, ब्रिटेन में 999)। मैं सिर्फ़ वही पढ़कर बताता हूँ जो रिकॉर्ड में है।"
REFUSAL = ("मैं किसी दवा को लेने, रोकने, छोड़ने या बदलने के बारे में सलाह नहीं दे सकता, और यह भी नहीं बता सकता कि कुछ सुरक्षित है या नहीं। "
           "इसके लिए उस डॉक्टर या फ़ार्मासिस्ट से पूछें जो व्यक्ति को जानता है। मैं रिकॉर्ड में दर्ज बातें, जाँच की सूचियाँ और वे बदलाव दिखाता हूँ जो किसी ने अभी नहीं देखे।")
HELP = ("मैं बता सकता हूँ कि रिकॉर्ड में क्या है, किस बदलाव को किसने नहीं देखा, जाँच में क्या चिह्नित हुआ और क्यों, हाल में क्या बदला, और कौन-सी खुराक दी गई दर्ज है। "
        "आप \"add warfarin 5 mg once daily\" कह सकते हैं, मैं एक प्रविष्टि तैयार कर दूँगा जिसे आप पुष्टि करेंगे। यह रिकॉर्ड है, चिकित्सकीय सलाह नहीं।")
NO_ANSWER = "मैं इसका उत्तर रिकॉर्ड से नहीं दे सकता। "

EMERGENCY = _re(r"आपात|इमरजेंसी|एम्बुलेंस|एंबुलेंस|ओवरडोज़?|सीने में दर्द|सांस नहीं|साँस नहीं|बेहोश|दौरा|ज़हर|जहर|आत्महत्या|emergency|overdose|ambulance", re.I)
ADVICE = _re(
    r"चाहिए|ले सकत|दे सकत|खा सकत|सकती हूँ|सकता हूँ|छोड़ दूँ|छोड़ दें|छोड़ दूं|बंद कर|रोक दूँ|रोक दें|बढ़ा|घटा|कम कर|खुराक कितनी|कितनी खुराक|कितनी (गोली|दवा).*(लें|लूँ|लूं|दें|दूँ|दूं)"
    r"|कितना (लें|लूँ|लूं|दें|दूँ|दूं)|सुरक्षित|ठीक रहेगा|ठीक है क्या|नुकसान|साइड इफ़?ेक्ट|दुष्प्रभाव|लक्षण|विकल्प|की जगह|क्या करूँ|क्या करूं|कौन सी बेहतर"
    r"|चक्कर|उल्टी|मिचली|दर्द|खून|बुखार|खुजली|सूजन|कमज़ोरी|कमजोरी|कांप|काँप|पीस|तोड़|चबा|खाली पेट|सकते|सकती|सकता|भूल (गय|ग)|छूट (गय|ग)|अब क्या|क्या होगा|दिक्कत|परेशानी|खतरा|ख़तरा|जोखिम|शराब|दारू|जारी रख|रोकना|बंद करना|छोड़|दोगुना|दो गोली|खा लें|खा लूँ|खा लूं"
    r"|\b(should|safe|dosage|side effect)\b|\bkitn[ai]\b.*\b(lu|du|le|de|len|den)\b|\bkhana chahiye\b|\bchahiye\b|\bsakt[aei]\b|\bsurakshit\b"
    r"|\b(bhul|bhool|chhut|chut)\b|\bab kya\b|\bkya hoga\b|\bkhatra\b|\bdikkat\b|\bsharab\b|\b(band|chhod|chod|jaari|jari)\b|\bdo goli\b|\bdugna\b", re.I)
UNSEEN = _re(r"नहीं देखा|नहीं देखी|नहीं देखे|नहीं पता|किसने नहीं|किसे नहीं|अनदेखा|पीछे|अपडेट|पुष्टि नहीं|जानकारी नहीं|किसे पता|नहीं जानता|नहीं जानती|\bnahi (dekha|pata)\b|\bkisne nahi\b", re.I)
FLAGS = _re(r"इंटरैक्शन|इंटरेक्शन|इंटरएक्शन|चेतावनी|फ्लैग|चिह्नित|टकराव|एक साथ|साथ में|गंभीर|मध्यम|एंजाइम|एन्ज़ाइम|क्यों.*(लाल|फ्लैग|चेतावनी)|interaction|flag|warning", re.I)
DOSES = _re(r"दी गई|दी गयी|दी है|दिया गया|किसने दी|किसने दिया|खुराक.*दर्ज|\bgiven\b|\bdi gayi\b|\bkisne di\b", re.I)
RECENT = _re(r"क्या बदला|बदलाव|हाल (में|ही)|क्या हुआ|ताज़ा|ताजा|इतिहास|नया क्या|\brecent\b|\bkya badla\b", re.I)
REGIMEN = _re(r"कौन ?(सी|से)? ?-?दवा|दवाइयाँ|दवाइयां|दवाईयां|दवाएं|दवाएँ|क्या (ले|खा) रही|क्या (ले|खा) रहे|रिकॉर्ड में क्या|सूची|लिस्ट|\bkaun si dawa\b|\bdawai\b|\bregimen\b", re.I)
HELPQ = _re(r"मदद|क्या कर सकते|क्या पूछ|हेल्प|\bhelp\b|\bmadad\b", re.I)

# Devanagari and Hinglish spellings of medicine names -> the generic name the record uses
NAMES = {
    "metformin": ("मेटफॉर्मिन", "मेटफार्मिन", "ग्लाइकोमेट", "glycomet"),
    "amlodipine": ("एम्लोडिपिन", "अम्लोडिपिन", "एमलोडिपिन", "amlokind", "stamlo"),
    "atorvastatin": ("एटोरवास्टेटिन", "एटोरवास्टैटिन", "एटोरवेस्टेटिन", "storvas"),
    "lisinopril": ("लिसिनोप्रिल",),
    "levothyroxine": ("लेवोथायरॉक्सिन", "लिवोथायरॉक्सिन", "थायरोक्सिन", "थायरॉक्सिन", "थायरॉइड की दवा", "eltroxin", "thyronorm"),
    "omeprazole": ("ओमेप्राज़ोल", "ओमेप्राजोल", "ओमेप्राज़ॉल", "omez"),
    "warfarin": ("वारफेरिन", "वारफरिन", "वार्फरिन", "वारफ़रिन", "खून पतला करने की दवा"),
    "acetaminophen": ("पेरासिटामोल", "पैरासिटामोल", "पैरासीटामोल", "क्रोसिन", "डोलो", "paracetamol", "crocin", "dolo"),
    "ibuprofen": ("इबुप्रोफेन", "आइबुप्रोफेन", "ब्रूफेन", "brufen"),
    "clarithromycin": ("क्लैरिथ्रोमाइसिन", "क्लेरिथ्रोमाइसिन", "क्लेरीथ्रोमाइसिन"),
    "cetirizine": ("सेटिरिज़िन", "सेटिरिजिन", "सिट्रिज़िन", "सेट्रिज़िन"),
    "vitamin d": ("विटामिन डी", "विटामिन-डी", "vitamin d3"),
    "acetylsalicylic acid": ("एस्पिरिन", "ईकोस्प्रिन", "ecosprin"),
}
LEVEL = {"major": "गंभीर", "moderate": "मध्यम", "minor": "हल्का", "unknown": "बिना स्तर वाला"}
ADD_HI = _re(r"^\s*(कृपया\s+)?(जोड़ें|जोड़ो|जोड़\s*दो|जोड़\s*दीजिए|दर्ज\s*करें|दर्ज\s*करो|add\s)\s*", re.I)


HINGLISH = re.compile(r"\b(kya|kyun|hai|hain|dawa|dawai|dawaiyan|chahiye|nahi|nahin|kisne|kitna|kitni|mujhe|mummy|papa|dadi|nani|batao|bataiye|khana|lena|dena|chhod|band)\b", re.I)


def _ago(h: float) -> str:
    if h < 0.05:
        return "अभी-अभी"
    if h < 1:
        return f"{round(h * 60)} मिनट पहले"
    if h < 48:
        return f"{h:.1f} घंटे पहले".replace(".0 ", " ")
    return f"{round(h / 24)} दिन पहले"


def _drug(facts, text: str) -> str | None:
    low = unicodedata.normalize('NFC', text).lower()
    on_record = {r["drug"] for r in facts.regimen}
    for drug in on_record:
        if drug in low:
            return drug
    for generic, spellings in NAMES.items():
        if generic in on_record and any(unicodedata.normalize('NFC', s).lower() in low for s in spellings):
            return generic
    return None


def _regimen(f) -> str:
    if not f.regimen:
        return f"{_title(f.person)} के लिए अभी रिकॉर्ड में कुछ नहीं है। आप फ़ोटो, आवाज़, दस्तावेज़ या टाइप करके दवा जोड़ सकते हैं।"
    items = "; ".join(f"{_title(r['drug'])} {r['dose_text']} {r['freq_text']}".strip() for r in f.regimen)
    return f"{_title(f.person)} के लिए अभी रिकॉर्ड में ({len(f.regimen)}): {items}।"


def _unseen(f) -> str:
    lines = []
    for carer, v in f.div["carers"].items():
        if v["unacknowledged"]:
            lines.append(f"{_who(carer)} ने अभी नहीं देखा: " + "; ".join(f"{_title(x['drug'])} ({_ago(x['age_hours'])})" for x in v["unacknowledged"]) + "।")
    if not lines:
        return "सर्कल में सभी ने रिकॉर्ड का हर बदलाव देख लिया है।"
    return " ".join(lines) + " सर्कल टैब खोलकर \"मैंने देख लिया\" दबाएँ।"


def _flags(f, q: str) -> str:
    if not f.regimen:
        return "अभी रिकॉर्ड में कुछ नहीं है, इसलिए जाँचने को कुछ नहीं।"
    c = f.check
    drug = _drug(f, q)
    pairs = [x for x in c["direct"] if x["level"].lower() != "unknown"]
    if drug:
        pairs = [x for x in pairs if drug in x["drugs"]]
    pairs.sort(key=lambda x: {"major": 0, "moderate": 1, "minor": 2}.get(x["level"].lower(), 3))
    bits = [f"{_title(x['drugs'][0])} और {_title(x['drugs'][1])}: {LEVEL.get(x['level'].lower(), x['level'])} ({x['source'].split(';')[0]})" for x in pairs[:4]]
    paths = [x for x in c["enzyme_paths"] if not drug or drug in (x.get("x"), x.get("y"))]
    if paths:
        bits.append(f"{len(paths)} एंज़ाइम-मार्ग भी सूचीबद्ध हैं (FDA तालिका)")
    if not bits:
        return "स्रोत ने इन दवाओं के बीच कोई स्तर-वाला मेल सूचीबद्ध नहीं किया। इसका मतलब यह नहीं कि सब सुरक्षित है; फ़ार्मासिस्ट से पूछें।"
    return "जाँच में चिह्नित: " + "; ".join(bits) + "। ये चर्चा के लिए हैं, डॉक्टर या फ़ार्मासिस्ट से बात करें। ग्राफ़ टैब में रेखा पर क्लिक करके स्रोत देखें।"


def _recent(f) -> str:
    if not f.regimen:
        return "अभी कुछ दर्ज नहीं हुआ है।"
    latest = sorted(f.regimen, key=lambda r: -r["since"])[:4]
    return "हाल के बदलाव: " + "; ".join(
        f"{_title(r['drug'])} {r['dose_text']} {r['freq_text']}".strip() + f", {_who(r['by'])} ने {_ago(max(0.0, (f.now - r['since']) / 3_600_000))} दर्ज किया" for r in latest) + "।"


def _doses(f) -> str:
    if not f.gives:
        return "अभी कोई खुराक दी हुई दर्ज नहीं है। सर्कल टैब में दर्ज करें; हर समय-स्लॉट सिर्फ़ एक बार दर्ज हो सकता है।"
    return "दी गई दर्ज: " + "; ".join(f"{_title(g['drug'])} {g['slot']} ({_who(g['by'])} ने)" for g in f.gives[:6]) + "।"


def _one(f, drug: str) -> str:
    r = next(x for x in f.regimen if x["drug"] == drug)
    flags = [x for x in f.check["direct"] if drug in x["drugs"] and x["level"].lower() != "unknown"]
    seen = [_who(k) for k, v in f.div["carers"].items() if any(u["drug"] == drug for u in v["unacknowledged"])]
    out = f"{_title(drug)} {r['dose_text']} {r['freq_text']}, {_who(r['by'])} ने {_ago(max(0.0, (f.now - r['since']) / 3_600_000))} दर्ज किया।".replace("  ", " ")
    if flags:
        out += f" यह {len(flags)} चिह्न में आती है: " + "; ".join(f"{_title([d for d in x['drugs'] if d != drug][0])} के साथ ({LEVEL.get(x['level'].lower(), x['level'])})" for x in flags[:4]) + "।"
    else:
        out += " संदर्भ डेटा रिकॉर्ड की दूसरी दवाओं के साथ इसमें कुछ चिह्नित नहीं करता।"
    if seen:
        out += f" {', '.join(seen)} ने अभी नहीं देखा।"
    return out


def ask(q: str, facts, checker) -> dict:
    """Same shape as assistant.ask. Called only when the question contains Devanagari or the caller asked for Hindi."""
    from . import intake
    q = unicodedata.normalize("NFC", q)
    if EMERGENCY.search(q):
        return {"answer": EMERGENCY_LINE, "source": "refusal", "links": []}
    m = ADD_HI.match(q) or ADD.match(q)
    if m and len(q) > m.end():
        text = q[m.end():]
        props = intake.propose(text, checker)
        if props:
            return {"answer": "आपने जो कहा उससे मैंने एक प्रविष्टि तैयार की है। दवा, खुराक और कितनी बार, देखकर पुष्टि करें। आपके पुष्टि करने तक कुछ सहेजा नहीं जाएगा।",
                    "source": "proposal", "proposals": props[:3], "text": text, "links": []}
        return {"answer": "मुझे इसमें दवा का नाम नहीं मिला। \"add warfarin 5 mg once daily\" की तरह टाइप करें, या जोड़ें टैब में फ़ोटो या आवाज़ का उपयोग करें।",
                "source": "rules", "links": [{"tab": "add", "label": "जोड़ें खोलें"}]}
    if ADVICE.search(q):
        return {"answer": REFUSAL, "source": "refusal", "links": []}
    drug = _drug(facts, q)
    if drug and not (UNSEEN.search(q) or DOSES.search(q)):
        return {"answer": _one(facts, drug), "source": "rules", "links": [{"tab": "graph", "label": "ग्राफ़ में देखें"}]}
    if UNSEEN.search(q):
        return {"answer": _unseen(facts), "source": "rules", "links": [{"tab": "circle", "label": "सर्कल खोलें"}]}
    if FLAGS.search(q):
        return {"answer": _flags(facts, q), "source": "rules", "links": [{"tab": "today", "label": "आज खोलें"}, {"tab": "graph", "label": "ग्राफ़ खोलें"}]}
    if DOSES.search(q):
        return {"answer": _doses(facts), "source": "rules", "links": [{"tab": "circle", "label": "सर्कल खोलें"}]}
    if RECENT.search(q):
        return {"answer": _recent(facts), "source": "rules", "links": [{"tab": "history", "label": "इतिहास खोलें"}]}
    if HELPQ.search(q):
        return {"answer": HELP, "source": "rules", "links": []}
    if REGIMEN.search(q):
        return {"answer": _regimen(facts), "source": "rules", "links": [{"tab": "today", "label": "आज खोलें"}]}
    return {"answer": NO_ANSWER + HELP, "source": "rules", "links": []}
