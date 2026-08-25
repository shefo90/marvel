import { useEffect, useState } from 'react';

import { useAccount } from '../../hooks/useAccount.jsx';
import { useLocale } from '../../hooks/useLocale.jsx';
import styles from '../../assets/styles/account.module.scss';

const COPY = {
  en: {
    heading: 'Sign in',
    email: 'Email',
    password: 'Password',
    submit: 'Sign in',
    working: 'Signing in…',
    noAccount: 'New here?',
    register: 'Create an account',
    already: 'You are signed in.',
    toAccount: 'Go to your account',
  },
  ar: {
    heading: 'تسجيل الدخول',
    email: 'البريد الإلكتروني',
    password: 'كلمة المرور',
    submit: 'تسجيل الدخول',
    working: 'جارٍ تسجيل الدخول…',
    noAccount: 'جديد هنا؟',
    register: 'إنشاء حساب',
    already: 'أنت مسجّل الدخول بالفعل.',
    toAccount: 'الذهاب إلى حسابك',
  },
};

/**
 * Sign in.
 *
 * The form posts to `/account/session`, which sets the refresh cookie and
 * returns an access token this app keeps in memory only.
 *
 * A shopper who is already signed in is shown a way onward rather than an empty
 * form: arriving here with a live session usually means a bookmark or a back
 * button, and re-presenting the form invites them to type a password they do
 * not need to.
 */
export default function Page() {
  const { locale, href } = useLocale();
  const { shopper, ready, busy, error, signIn, clearError } = useAccount();
  const copy = COPY[locale] ?? COPY.en;

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  // Otherwise a failed attempt's message outlives the page it belongs to and
  // greets the shopper on their next visit.
  useEffect(() => clearError, [clearError]);

  const onSubmit = async (event) => {
    event.preventDefault();
    const ok = await signIn({ email, password });
    if (ok) window.location.assign(href('/account'));
  };

  if (ready && shopper) {
    return (
      <div className={styles.panel}>
        <h1>{copy.heading}</h1>
        <p>{copy.already}</p>
        <a className={styles.primary} href={href('/account')}>
          {copy.toAccount}
        </a>
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <h1>{copy.heading}</h1>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <form className={styles.form} onSubmit={onSubmit}>
        <label className={styles.field}>
          <span>{copy.email}</span>
          <input
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        <label className={styles.field}>
          <span>{copy.password}</span>
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        <button className={styles.primary} type="submit" disabled={busy}>
          {busy ? copy.working : copy.submit}
        </button>
      </form>

      <p className={styles.aside}>
        {copy.noAccount} <a href={href('/account/register')}>{copy.register}</a>
      </p>
    </div>
  );
}
