import { useEffect, useState } from 'react';

import styles from '../../assets/styles/account.module.scss';
import { useAccount } from '../../hooks/useAccount.jsx';
import { useLocale } from '../../hooks/useLocale.jsx';

const COPY = {
  en: {
    heading: 'Create an account',
    email: 'Email',
    password: 'Password',
    passwordHelp: 'At least 8 characters.',
    phone: 'Phone (optional)',
    phoneHelp: 'If you have ordered as a guest, this reunites you with those orders.',
    firstName: 'First name (optional)',
    lastName: 'Last name (optional)',
    submit: 'Create account',
    working: 'Creating your account…',
    haveOne: 'Already have an account?',
    signIn: 'Sign in',
  },
  ar: {
    heading: 'إنشاء حساب',
    email: 'البريد الإلكتروني',
    password: 'كلمة المرور',
    passwordHelp: '٨ أحرف على الأقل.',
    phone: 'رقم الهاتف (اختياري)',
    phoneHelp: 'إذا سبق أن طلبت كضيف، فهذا يربطك بطلباتك السابقة.',
    firstName: 'الاسم الأول (اختياري)',
    lastName: 'اسم العائلة (اختياري)',
    submit: 'إنشاء الحساب',
    working: 'جارٍ إنشاء حسابك…',
    haveOne: 'لديك حساب بالفعل؟',
    signIn: 'تسجيل الدخول',
  },
};

/**
 * Create a shopper account.
 *
 * **Phone is optional and load-bearing when given.** A guest who checked out by
 * phone alone is matched on it, so supplying it here is what reunites somebody
 * with the orders they placed before they had an account. The help text says so
 * rather than leaving it as a field people skip.
 *
 * Registering signs the shopper straight in. The API keeps account creation and
 * session creation as separate calls -- one code path issues tokens -- but that
 * is an API shape, not a reason to make someone type the password they just
 * chose a second time.
 */
export default function Page() {
  const { locale, href } = useLocale();
  const { busy, error, register, clearError } = useAccount();
  const copy = COPY[locale] ?? COPY.en;

  const [form, setForm] = useState({
    email: '',
    password: '',
    phone: '',
    first_name: '',
    last_name: '',
  });

  useEffect(() => clearError, [clearError]);

  const set = (field) => (event) =>
    setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const onSubmit = async (event) => {
    event.preventDefault();
    // Empty optional fields are omitted rather than sent blank: the API's
    // guest-matching treats an empty phone as a value to match on.
    const payload = Object.fromEntries(
      Object.entries(form).filter(([, value]) => value !== ''),
    );
    const ok = await register(payload);
    if (ok) window.location.assign(href('/account'));
  };

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
            value={form.email}
            onChange={set('email')}
          />
        </label>

        <label className={styles.field}>
          <span>{copy.password}</span>
          <input
            type="password"
            name="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={form.password}
            onChange={set('password')}
          />
          <small>{copy.passwordHelp}</small>
        </label>

        <label className={styles.field}>
          <span>{copy.phone}</span>
          <input
            type="tel"
            name="phone"
            autoComplete="tel"
            value={form.phone}
            onChange={set('phone')}
          />
          <small>{copy.phoneHelp}</small>
        </label>

        <label className={styles.field}>
          <span>{copy.firstName}</span>
          <input
            type="text"
            name="first_name"
            autoComplete="given-name"
            value={form.first_name}
            onChange={set('first_name')}
          />
        </label>

        <label className={styles.field}>
          <span>{copy.lastName}</span>
          <input
            type="text"
            name="last_name"
            autoComplete="family-name"
            value={form.last_name}
            onChange={set('last_name')}
          />
        </label>

        <button className={styles.primary} type="submit" disabled={busy}>
          {busy ? copy.working : copy.submit}
        </button>
      </form>

      <p className={styles.aside}>
        {copy.haveOne} <a href={href('/account/login')}>{copy.signIn}</a>
      </p>
    </div>
  );
}
