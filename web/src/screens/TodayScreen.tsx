import { Camera, Eye, FileText, Mic, Pill as PillIcon, Type, Users } from 'lucide-react';
import { motion } from 'motion/react';
import { Async } from '../components/Async';
import { Flags } from '../components/Flags';
import { Hero } from '../components/Hero';
import { DrugInfo } from '../components/DrugInfo';
import { MedActions } from '../components/MedActions';
import { PageHead } from '../components/PageHead';
import { Pill } from '../components/Pill';
import { ProfileCard } from '../components/ProfileCard';
import { Checklist } from '../components/Checklist';
import { Counts } from '../components/Counts';
import { Readings } from '../components/Readings';
import { Recalls } from '../components/Recalls';
import { Scale } from '../components/Scale';
import { ago, nameOf, plural, title } from '../lib/format';
import { useT } from '../lib/i18n';
import { useApp, useLoad } from '../state';

const SOURCE = { typed: 'typed in', photo: 'from a photo', voice: 'from a voice note', document: 'from a document' } as const;
const SRC_ICON = { typed: Type, photo: Camera, voice: Mic, document: FileText } as const;

export function TodayScreen(): React.JSX.Element {
  const app = useApp();
  const t = useT();
  const state = useLoad((a) => a.api.check());
  const div = useLoad((a) => a.api.divergence(a.now()), [app.warp]);
  const carers = div.data ? Object.keys(div.data.carers).length : 0;
  const unseen = div.data ? Object.values(div.data.carers).reduce((n, c) => n + c.unacknowledged.length, 0) : 0;
  return (
    <div className="screen">
      <PageHead crumb={`${title(app.session.person)} · ${t('shared medicines record')}`} title="Today" lede="What the record says, checked against public interaction data. It records and cross-checks; it never advises." />
      <Async state={state}>
        {(c) => (
          <div className="layout">
            <div className="col">
              <Checklist />
              <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: 'easeOut' }}>
                <Hero
                  check={c}
                  chips={[
                    { Icon: PillIcon, text: plural(c.regimen.length, 'medicine') },
                    { Icon: Users, text: plural(carers, 'carer') },
                    { Icon: Eye, text: unseen ? `${unseen} unseen` : 'all seen' },
                  ]}
                />
              </motion.div>
              <section className="card" aria-labelledby="reg-title">
                <div className="card-head">
                  <h2 id="reg-title">{t('On record for')} {title(app.session.person)}</h2>
                  <Pill tone="info">{plural(c.regimen.length, 'medicine')}</Pill>
                </div>
                {c.regimen.length === 0 ? (
                  <div className="empty">
                    <span className="ico">
                      <PillIcon size={26} strokeWidth={1.75} aria-hidden="true" />
                    </span>
                    <b>{t('Nothing on record yet')}</b>
                    <span>{t('Add a medicine from a photo, a voice note, a document or by typing.')}</span>
                    <button type="button" className="btn" onClick={() => app.go('add')}>
                      {t('Add a medicine')}
                    </button>
                  </div>
                ) : (
                  <div className="rows">
                    {c.regimen.map((r, i) => {
                      const Icon = SRC_ICON[r.source];
                      return (
                        <motion.div key={r.id} className="med" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.05 * i, duration: 0.3 }}>
                          <span className="ico">
                            <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
                          </span>
                          <div>
                            <div className="item__title">
                              {title(r.drug)} <span className="muted">{r.dose_text} {r.freq_text}</span>{r.product ? <span className="pill pill--mute" style={{ marginLeft: 6 }}>{t('as')} {title(r.product)}</span> : null}
                            </div>
                            <div className="item__sub">
                              added by {nameOf(r.by)} {SOURCE[r.source]}, {ago(r.since, app.now())}
                            </div>
                            {r.quote && <div className="item__sub">“{r.quote}”</div>}
                          </div>
                          <div className="row no-print">
                            <button type="button" className="btn btn--ghost btn--sm" onClick={() => app.go('graph')}>
                              {t('In graph')}
                            </button>
                            <DrugInfo drug={r.drug} />
                            <MedActions r={r} />
                          </div>
                        </motion.div>
                      );
                    })}
                  </div>
                )}
              </section>
            </div>
            <div className="col">
              <ProfileCard />
              <Recalls />
              <details className="more" data-testid="today-more">
                <summary className="more__summary">{t('More: how to read a flag, how the record adds up, readings, where the flags come from')}</summary>
                <div className="stack">
                  <Scale check={c} />
                  <Counts />
                  <Readings />
                  <section className="card" aria-labelledby="sources-title">
                    <h2 id="sources-title">{t('Where the flags come from')}</h2>
                    <ul className="steps">
                      <li><span><b>{t('Direct pairs:')}</b> {t('DDInter 2.0, a curated interaction database, with its severity.')}</span></li>
                      <li><span><b>{t('Enzyme paths:')}</b> {t('one medicine slows or speeds a liver enzyme that clears another (FDA table, a two-step graph path).')}</span></li>
                    </ul>
                  </section>
                </div>
              </details>
            </div>
            {(c.direct.length > 0 || c.enzyme_paths.length > 0 || c.unrated.length > 0 || (c.duplicates?.length ?? 0) > 0) && (
              <section className="card wide" aria-labelledby="flags-title">
                <h2 id="flags-title">{t('Flags, with their sources')}</h2>
                <Flags check={c} />
                <p className="muted small">{t(c.notice)}</p>
              </section>
            )}
          </div>
        )}
      </Async>
    </div>
  );
}
