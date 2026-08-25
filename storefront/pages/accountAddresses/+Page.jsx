import { useCallback, useEffect, useState } from 'react';

import styles from '../../assets/styles/account.module.scss';
import { useAccount } from '../../hooks/useAccount.jsx';
import { useLocale } from '../../hooks/useLocale.jsx';
import {
  archiveAddress,
  createAddress,
  listAddresses,
  updateAddress,
} from '../../services/account.service.js';

const COPY = {
  en: {
    heading: 'Your addresses',
    back: 'Back to your account',
    none: 'You have not saved an address yet.',
    add: 'Add an address',
    save: 'Save address',
    saving: 'Saving…',
    cancel: 'Cancel',
    remove: 'Remove',
    makeDefault: 'Use as default',
    isDefault: 'Default',
    signIn: 'Sign in to manage your addresses.',
    toSignIn: 'Sign in',
    loading: 'Loading your addresses…',
    label: 'Label (optional)',
    recipient: 'Recipient name',
    phone: 'Phone',
    governorate: 'Governorate',
    city: 'City',
    district: 'District (optional)',
    street: 'Street address',
    building: 'Building (optional)',
    floor: 'Floor (optional)',
    apartment: 'Apartment (optional)',
    landmark: 'Landmark (optional)',
  },
  ar: {
    heading: 'عناوينك',
    back: 'العودة إلى حسابك',
    none: 'لم تحفظ أي عنوان بعد.',
    add: 'إضافة عنوان',
    save: 'حفظ العنوان',
    saving: 'جارٍ الحفظ…',
    cancel: 'إلغاء',
    remove: 'إزالة',
    makeDefault: 'اجعله الافتراضي',
    isDefault: 'الافتراضي',
    signIn: 'سجّل الدخول لإدارة عناوينك.',
    toSignIn: 'تسجيل الدخول',
    loading: 'جارٍ تحميل عناوينك…',
    label: 'الاسم المختصر (اختياري)',
    recipient: 'اسم المستلم',
    phone: 'رقم الهاتف',
    governorate: 'المحافظة',
    city: 'المدينة',
    district: 'الحي (اختياري)',
    street: 'العنوان',
    building: 'رقم العقار (اختياري)',
    floor: 'الطابق (اختياري)',
    apartment: 'الشقة (اختياري)',
    landmark: 'علامة مميزة (اختياري)',
  },
};

const REQUIRED = ['recipient_name', 'phone', 'governorate', 'city', 'street_address'];

const BLANK = {
  label: '',
  recipient_name: '',
  phone: '',
  governorate: '',
  city: '',
  district: '',
  street_address: '',
  building: '',
  floor: '',
  apartment: '',
  landmark: '',
};

/**
 * The address book.
 *
 * **Removing archives rather than deletes.** `addresses.archived_at` exists so
 * the row survives, and nothing else in this schema destroys a customer record.
 * The button still says "Remove", because that is what the shopper is doing —
 * the distinction is ours to honour, not theirs to read about.
 *
 * The default is managed by the API: the first address saved becomes the
 * default whatever was ticked, and archiving the default promotes another. A
 * shopper with addresses and no default would meet a checkout that preselects
 * nothing, which reads as the book having lost them.
 */
export default function Page() {
  const { locale, href } = useLocale();
  const { shopper, ready } = useAccount();
  const copy = COPY[locale] ?? COPY.en;

  const [addresses, setAddresses] = useState(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const reload = useCallback(
    () =>
      listAddresses(locale)
        .then(setAddresses)
        .catch(() => setAddresses([])),
    [locale],
  );

  useEffect(() => {
    if (!shopper) return;
    reload();
  }, [shopper, reload]);

  const set = (field) => (event) =>
    setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const onSubmit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Blank optionals are dropped rather than stored as empty strings, so a
      // saved address never renders a line with nothing on it.
      const payload = Object.fromEntries(
        Object.entries(form).filter(([, value]) => value !== ''),
      );
      await createAddress(locale, payload);
      setForm(BLANK);
      setAdding(false);
      await reload();
    } catch (failure) {
      setError(failure?.response?.data?.detail ?? copy.save);
    } finally {
      setBusy(false);
    }
  };

  const makeDefault = async (address) => {
    await updateAddress(locale, address.id, { is_default_shipping: true });
    await reload();
  };

  const remove = async (address) => {
    await archiveAddress(locale, address.id);
    await reload();
  };

  if (!ready) return <div className={styles.panel} />;

  if (!shopper) {
    return (
      <div className={styles.panel}>
        <h1>{copy.heading}</h1>
        <p>{copy.signIn}</p>
        <a className={styles.primary} href={href('/account/login')}>
          {copy.toSignIn}
        </a>
      </div>
    );
  }

  return (
    <div className={styles.wide}>
      <header className={styles.header}>
        <h1>{copy.heading}</h1>
        <nav className={styles.actions}>
          <a href={href('/account')}>{copy.back}</a>
        </nav>
      </header>

      {addresses === null ? <p>{copy.loading}</p> : null}

      {addresses !== null && addresses.length === 0 && !adding ? <p>{copy.none}</p> : null}

      {addresses !== null && addresses.length > 0 ? (
        <ul className={styles.list} aria-label={copy.heading}>
          {addresses.map((address) => (
            <li key={address.id} className={styles.addressRow}>
              <div>
                <strong>{address.recipient_name}</strong>
                {address.is_default_shipping ? (
                  <span className={styles.badge}>{copy.isDefault}</span>
                ) : null}
                <div className={styles.aside}>
                  {address.street_address}, {address.city}, {address.governorate}
                </div>
                <div className={styles.aside}>{address.phone}</div>
              </div>
              <div className={styles.actions}>
                {address.is_default_shipping ? null : (
                  <button
                    type="button"
                    className={styles.link}
                    onClick={() => makeDefault(address)}
                  >
                    {copy.makeDefault}
                  </button>
                )}
                <button type="button" className={styles.link} onClick={() => remove(address)}>
                  {copy.remove}
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {adding ? (
        <form className={styles.form} onSubmit={onSubmit}>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}

          {Object.keys(BLANK).map((field) => (
            <label key={field} className={styles.field}>
              <span>{copy[fieldCopyKey(field)] ?? field}</span>
              <input
                type={field === 'phone' ? 'tel' : 'text'}
                name={field}
                required={REQUIRED.includes(field)}
                value={form[field]}
                onChange={set(field)}
              />
            </label>
          ))}

          <div className={styles.actions}>
            <button className={styles.primary} type="submit" disabled={busy}>
              {busy ? copy.saving : copy.save}
            </button>
            <button type="button" className={styles.link} onClick={() => setAdding(false)}>
              {copy.cancel}
            </button>
          </div>
        </form>
      ) : (
        <button className={styles.primary} type="button" onClick={() => setAdding(true)}>
          {copy.add}
        </button>
      )}
    </div>
  );
}

/** `street_address` -> `street`, so the copy tables stay readable. */
function fieldCopyKey(field) {
  const named = {
    recipient_name: 'recipient',
    street_address: 'street',
  };
  return named[field] ?? field;
}
