/** Sentences the server writes with numbers in them. translate() tries the exact table first, then these. Each pattern keeps the numbers and swaps the words. */
export const HI_PATTERNS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/^(\d+) medicines, written to be taken at (\d+|unspecified) time\(s\) of day, (\d+) with a special direction\. A simple count of what is written, not the validated Medication Regimen Complexity Index\.$/,
    (m) => `${m[1]} दवाएँ, दिन के ${m[2] === 'unspecified' ? 'अनिर्दिष्ट' : m[2]} समय पर लेने के लिए लिखी गई, ${m[3]} में विशेष निर्देश। यह केवल जो लिखा है उसकी सरल गिनती है, मान्य Medication Regimen Complexity Index नहीं।`],
  [/^(\d+) from (\d+) medicine\(s\) on this short list; a total of 3 or more is the usual reason to ask a pharmacist for a review\. The list is a subset, so the real total could be higher\. This is a talking point, not a verdict\.$/,
    (m) => `इस छोटी सूची की ${m[2]} दवा(ओं) से ${m[1]}; कुल 3 या अधिक होना फ़ार्मासिस्ट से समीक्षा माँगने का आम कारण है। सूची पूरी नहीं है, इसलिए असली कुल अधिक हो सकता है। यह चर्चा का बिंदु है, निर्णय नहीं।`],
  [/^Of (\d+) possible pairs among the (\d+) medicines the reference data knows, the source lists (\d+): (\d+) with a severity, (\d+) without one; (\d+) are not listed\. A pair that is not listed has not been rated as safe\.$/,
    (m) => `संदर्भ डेटा जिन ${m[2]} दवाओं को जानता है उनके ${m[1]} संभावित जोड़ों में से स्रोत ${m[3]} सूचीबद्ध करता है: ${m[4]} में गंभीरता दी है, ${m[5]} में नहीं; ${m[6]} सूचीबद्ध नहीं हैं। जो जोड़ा सूचीबद्ध नहीं है उसे सुरक्षित नहीं आँका गया है।`],
  [/^Of (\d+) entries read from photos, voice notes or documents, (\d+) were saved exactly as read; the rest were corrected by the carer first\.$/,
    (m) => `फ़ोटो, आवाज़ के नोट या दस्तावेज़ से पढ़ी गई ${m[1]} प्रविष्टियों में से ${m[2]} जैसी पढ़ी गईं वैसी ही सहेजी गईं; बाकी पहले देखभालकर्ता ने सुधारीं।`],
];
