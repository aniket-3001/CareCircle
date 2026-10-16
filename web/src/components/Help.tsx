import { tr } from '../lib/i18n';

const QA: [string, string][] = [
  ['How do I add a medicine?', 'Open Add. Take a photo of the label, record a voice note, upload a PDF or Word file, or type it. You see exactly what was read and the line it came from, then confirm. Nothing is saved until you confirm.'],
  ['How do I bring in another carer?', 'In Account, open your circle and press Invite a carer. Send them the code. It works once and expires. They sign up, press Join with a code, and see the same record.'],
  ['What does "unseen" mean?', 'A carer has not yet pressed "I have seen this" on a change someone else made. It shows who is behind, so a changed dose does not stay unknown to the person giving it.'],
  ['What does a flag mean?', 'Two medicines on the record are listed together in a public interaction source, or one slows the liver enzyme that clears the other. It is a reason to ask the prescriber or pharmacist. No flag does not mean safe.'],
  ['I made a mistake in an entry. How do I fix it?', 'Add the corrected entry: it replaces the old one and the old one stays in History. To remove an entry for good, use History, Remove for good. A receipt is kept that something was removed.'],
  ['How do reminders work?', 'In Account, turn on browser notifications or link the Telegram bot. A reminder is sent once for a change a carer has not yet seen, and not again.'],
  ['Can I use it for two people?', 'Yes: make one circle for each person. The circle picker at the top of the page switches between them.'],
  ['Does it tell me what to take?', 'No. It records what people wrote and cross-checks it. For what to take, stop or change, ask the prescriber or pharmacist. In an emergency call your local emergency number.'],
];

/** Plain answers to the questions a new carer asks first. */
export function Help(): React.JSX.Element {
  return (
    <div className="stack" data-testid="help">
      {QA.map(([q, a]) => (
        <details key={q} className="faq">
          <summary>{tr(q)}</summary>
          <p>{tr(a)}</p>
        </details>
      ))}
    </div>
  );
}
