import { CircleForms } from '../components/CircleForms';
import { PageHead } from '../components/PageHead';
import { useApp } from '../state';

/** A signed-in account with no circle yet: nothing is pre-filled. You make your own, or join one you were invited to. */
export function Onboarding(): React.JSX.Element {
  const app = useApp();
  return (
    <div className="screen">
      <PageHead crumb={`Welcome, ${app.profile?.name ?? ''}`} title="Set up your first circle" lede="A circle is one person being looked after and the carers who share their record. It starts empty: everything in it will be what you and the other carers add." />
      <div style={{ marginTop: 18 }}><CircleForms /></div>
    </div>
  );
}
