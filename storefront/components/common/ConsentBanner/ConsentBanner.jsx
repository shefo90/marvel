import { useEffect, useState } from 'react';

import { useLocale } from '../../../hooks/useLocale.jsx';
import { readConsentCookie, recordConsent } from '../../../services/dataLayer.js';
import styles from './ConsentBanner.module.scss';

const COPY = {
  en: {
    label: 'Cookie consent',
    message:
      'We use cookies to measure how the shop is used. Accept to help us make it better.',
    privacy: 'Privacy',
    accept: 'Accept',
    reject: 'Reject',
  },
  ar: {
    label: 'الموافقة على ملفات تعريف الارتباط',
    message:
      'نستخدم ملفات تعريف الارتباط لقياس طريقة استخدام المتجر. وافق لمساعدتنا في تحسينه.',
    privacy: 'الخصوصية',
    accept: 'أوافق',
    reject: 'أرفض',
  },
};

/**
 * The consent bar.
 *
 * Consent Mode already ships denied in the first HTML response, so the shop
 * works and sends privacy-safe pings before anyone clicks anything — this bar
 * only decides whether those pings become full, cookie-backed measurement.
 *
 * It renders nothing until it has checked the cookie on the client. The check
 * needs ``document`` and would flash on a server that cannot know the choice,
 * so the server renders an empty banner and the decision happens after mount —
 * which also keeps hydration honest.
 */
export default function ConsentBanner() {
  const { locale, href } = useLocale();
  const [answered, setAnswered] = useState(true);

  useEffect(() => {
    setAnswered(readConsentCookie(document.cookie) !== null);
  }, []);

  if (answered) return null;

  const copy = COPY[locale] ?? COPY.en;

  function choose(choice) {
    recordConsent(choice);
    setAnswered(true);
  }

  return (
    <div className={styles.banner} role="region" aria-label={copy.label}>
      <p className={styles.message}>
        {copy.message}{' '}
        <a className={styles.link} href={href('/privacy')}>
          {copy.privacy}
        </a>
      </p>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.reject}
          onClick={() => choose('denied')}
        >
          {copy.reject}
        </button>
        <button
          type="button"
          className={styles.accept}
          onClick={() => choose('granted')}
        >
          {copy.accept}
        </button>
      </div>
    </div>
  );
}
