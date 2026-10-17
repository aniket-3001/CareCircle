import { HI_PATTERNS } from './hi_patterns';
import { useSyncExternalStore } from 'react';
import { HI_MORE } from './hi_more';

/** English and Hindi. The English text is the key, so a string with no Hindi entry simply stays English. The choice is a per-browser convenience
 *  (it is not account data); the helper, voice input and read-aloud follow it too. */
export type Lang = 'en' | 'hi';

const KEY = 'cc-lang';
const read = (): Lang => {
  try {
    const v = window.localStorage.getItem(KEY);
    if (v === 'hi' || v === 'en') return v;
  } catch { /* storage can be blocked */ }
  return typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('hi') ? 'hi' : 'en';
};
let current: Lang = read();
const subs = new Set<() => void>();
export const getLang = (): Lang => current;
export function setLang(l: Lang): void {
  current = l;
  try { window.localStorage.setItem(KEY, l); } catch { /* ignore */ }
  document.documentElement.lang = l;
  subs.forEach((f) => f());
}
if (typeof document !== 'undefined') document.documentElement.lang = current;

const HI: Record<string, string> = {
  // header, tabs, dock
  'Care Circle': 'केयर सर्कल', 'Sign in': 'साइन इन', 'Sign up': 'साइन अप', 'Create account': 'खाता बनाएँ', 'Sign out': 'साइन आउट',
  'About and safety': 'परिचय और सुरक्षा', 'Close': 'बंद करें', 'Circle': 'सर्कल', 'Today': 'आज', 'Add': 'जोड़ें', 'Graph': 'ग्राफ़', 'History': 'इतिहास',
  'Main': 'मुख्य', 'Ask the helper': 'सहायक से पूछें', 'Add a medicine': 'दवा जोड़ें', 'Language': 'भाषा', 'Switch to dark theme': 'डार्क थीम चालू करें', 'Switch to light theme': 'लाइट थीम चालू करें', 'Dark theme': 'डार्क थीम', 'Light theme': 'लाइट थीम',
  // about
  'What this is': 'यह क्या है', 'What it will not do': 'यह क्या नहीं करेगा', 'Your data': 'आपका डेटा', 'Where the data comes from': 'डेटा कहाँ से आता है', 'AI use': 'AI का उपयोग',
  "A shared record of a person's medicines for the people who look after them. It records what carers add, cross-checks it against public data, and shows who has not seen a change.":
    'किसी व्यक्ति की दवाओं का साझा रिकॉर्ड, उनकी देखभाल करने वालों के लिए। यह वही दर्ज करता है जो देखभालकर्ता जोड़ते हैं, उसे सार्वजनिक डेटा से मिलाता है, और दिखाता है कि किसने कौन-सा बदलाव नहीं देखा।',
  'It never tells anyone what to take, stop, skip or change. Flags are for discussion with a prescriber or pharmacist. No flag does not mean safe. The helper answers only from the record and refuses to advise.':
    'यह कभी नहीं बताता कि क्या लें, रोकें, छोड़ें या बदलें। चिह्न डॉक्टर या फ़ार्मासिस्ट से चर्चा के लिए हैं। कोई चिह्न न होने का मतलब सुरक्षित नहीं है। सहायक सिर्फ़ रिकॉर्ड से उत्तर देता है और सलाह देने से मना करता है।',
  // welcome
  'Shared memory for people who care': 'देखभाल करने वालों की साझा याददाश्त',
  "One shared, verified memory of a loved one's medicines.": 'अपने प्रियजन की दवाओं की एक साझा, जाँची हुई याददाश्त।',
  'Each carer adds what they know, the record is checked against public interaction data, and everyone is told what they have not yet seen.':
    'हर देखभालकर्ता वही जोड़ता है जो वह जानता है, रिकॉर्ड को सार्वजनिक इंटरैक्शन डेटा से जाँचा जाता है, और सबको बताया जाता है कि उन्होंने क्या अभी नहीं देखा।',
  'It records and cross-checks. It never says what to take or stop.': 'यह दर्ज करता और मिलान करता है। यह कभी नहीं कहता कि क्या लें या रोकें।',
  'Get started': 'शुरू करें', 'with your email': 'अपने ईमेल से', 'Create an account': 'खाता बनाएँ', 'free, takes a minute': 'मुफ़्त, एक मिनट में',
  'Back': 'वापस', 'Email': 'ईमेल', 'Password': 'पासवर्ड', 'Your name': 'आपका नाम', 'Forgot your password?': 'पासवर्ड भूल गए?',
  'New here? Create an account': 'नए हैं? खाता बनाएँ', 'Already have one? Sign in': 'खाता है? साइन इन करें', 'Check your email': 'अपना ईमेल देखें',
  'Confirm': 'पुष्टि करें', 'Send a new code': 'नया कोड भेजें', 'Reset your password': 'पासवर्ड रीसेट करें', 'Send the code': 'कोड भेजें',
  'Choose a new password': 'नया पासवर्ड चुनें', 'Change password': 'पासवर्ड बदलें', 'The code we emailed you': 'ईमेल से भेजा गया कोड',
  'Try a demo account': 'डेमो खाता आज़माएँ', 'Just look around': 'बस घूमकर देखें', 'Start a demo circle': 'डेमो सर्कल शुरू करें',
  'What you can do in two minutes': 'दो मिनट में आप क्या कर सकते हैं',
  'Two carers who already share a circle for Asha. Sign in as one, then as the other in another window, to see how a change reaches the second carer. The password is public.':
    'दो देखभालकर्ता जो आशा के लिए पहले से एक सर्कल साझा करते हैं। एक के रूप में साइन इन करें, फिर दूसरी विंडो में दूसरे के रूप में, यह देखने के लिए कि बदलाव दूसरे तक कैसे पहुँचता है। पासवर्ड सार्वजनिक है।',
  'A throw-away circle with fake data and two carers you can switch between. No account, nothing kept.': 'नकली डेटा और दो देखभालकर्ताओं वाला अस्थायी सर्कल। कोई खाता नहीं, कुछ सहेजा नहीं जाता।',
  'An account keeps your circles, records and conversations on the server, so they follow you to any phone or laptop.':
    'खाता आपके सर्कल, रिकॉर्ड और बातचीत सर्वर पर रखता है, इसलिए वे किसी भी फ़ोन या लैपटॉप पर आपके साथ रहते हैं।',
  // today
  'Today · shared medicines record': 'आज · साझा दवा रिकॉर्ड',
  'What the record says, checked against public interaction data. It records and cross-checks; it never advises.':
    'रिकॉर्ड क्या कहता है, सार्वजनिक इंटरैक्शन डेटा से जाँचा हुआ। यह दर्ज करता और मिलान करता है; सलाह कभी नहीं देता।',
  'Nothing on record yet': 'अभी रिकॉर्ड में कुछ नहीं', 'Add a medicine from a photo, a voice note, a document or by typing.': 'फ़ोटो, आवाज़, दस्तावेज़ या टाइप करके दवा जोड़ें।',
  'In graph': 'ग्राफ़ में', 'Where the flags come from': 'चिह्न कहाँ से आते हैं', 'Flags, with their sources': 'चिह्न, उनके स्रोतों के साथ',
  'Major interaction flagged': 'गंभीर इंटरैक्शन चिह्नित', 'Interactions flagged': 'इंटरैक्शन चिह्नित', 'Minor flags only': 'सिर्फ़ हल्के चिह्न',
  'Not enough to judge': 'आकलन के लिए पर्याप्त नहीं', 'No known conflict': 'कोई ज्ञात टकराव नहीं', 'Nothing to check yet': 'अभी जाँचने को कुछ नहीं',
  'Most serious': 'सबसे गंभीर', 'FLAG': 'चिह्न', 'FLAGS': 'चिह्न', 'all seen': 'सबने देखा',
  'Flags are for discussion with a prescriber or pharmacist. No flag does not mean safe. DDInter 2.0 · FDA CYP table.':
    'चिह्न डॉक्टर या फ़ार्मासिस्ट से चर्चा के लिए हैं। कोई चिह्न न होना सुरक्षित होना नहीं है। DDInter 2.0 · FDA CYP तालिका।',
  // other screens
  'The circle': 'सर्कल', 'Who has seen what': 'किसने क्या देखा', 'Doses given': 'दी गई खुराकें', 'The record over time': 'समय के साथ रिकॉर्ड',
  'What did we know, and when?': 'हमें क्या पता था, और कब?', 'Look back in time': 'पीछे मुड़कर देखें', 'Everything that happened': 'जो कुछ हुआ',
  'Medicines': 'दवाएँ', 'Account': 'खाता', 'Session': 'सत्र', 'Sign out of this account': 'इस खाते से साइन आउट',
  // assistant
  'Assistant': 'सहायक', 'Ask about the record…': 'रिकॉर्ड के बारे में पूछें…', 'Your question': 'आपका सवाल', 'Send': 'भेजें', 'Ask by voice': 'आवाज़ से पूछें',
  'Stop recording': 'रिकॉर्डिंग रोकें', 'Reading aloud': 'पढ़कर सुनाना चालू', 'Read aloud': 'पढ़कर सुनाएँ', 'Suggestions': 'सुझाव',
  'Who has not seen the latest change?': 'ताज़ा बदलाव किसने नहीं देखा?', 'What is on record?': 'रिकॉर्ड में क्या है?', 'What does the record flag?': 'रिकॉर्ड में क्या चिह्नित है?',
  'What changed recently?': 'हाल में क्या बदला?', 'from the record': 'रिकॉर्ड से', 'AI-assisted, checked': 'AI की मदद से, जाँचा हुआ',
  'I could not hear anything in that.': 'मुझे उसमें कुछ सुनाई नहीं दिया।', 'Could not transcribe that.': 'इसे लिखित रूप में नहीं बदल सका।',
  'Reading answers aloud': 'जवाब पढ़कर सुनाए जा रहे हैं', 'Read answers aloud': 'जवाब पढ़कर सुनाएँ', 'left today': 'आज बाकी', 'Clear': 'साफ़ करें', 'Ask the helper ': '',
  'On record for': 'रिकॉर्ड में है', 'shared medicines record': 'साझा दवा रिकॉर्ड',
  'Conversation deleted': 'बातचीत हटा दी गई',
};

export const tr = (s: string): string => translate(s);
/** A sentence the server wrote with numbers in it: the matching pattern keeps the numbers and swaps the words. */
function fromPattern(s: string): string {
  for (const [re, f] of HI_PATTERNS) {
    const m = s.match(re);
    if (m) return f(m);
  }
  return s;
}

export function translate(s: string, l: Lang = current): string {
  return l === 'hi' ? HI[s] ?? HI_MORE[s] ?? fromPattern(s) : s;
}

/** `const t = useT()`: re-renders when the language changes. */
export function useT(): (s: string) => string {
  const l = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, getLang);
  return (s: string) => translate(s, l);
}
export function useLang(): Lang {
  return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, getLang);
}
