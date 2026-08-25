import { useLocale } from '../../hooks/useLocale.jsx';
import { usePageContext } from '../../hooks/usePageContext.jsx';

const COPY = {
  en: {
    notFound: 'That page does not exist',
    notFoundBody:
      'The address may have changed, or the product may no longer be sold in this language.',
    error: 'Something went wrong',
    errorBody: 'Please try again in a moment.',
    home: 'Go to the shop',
  },
  ar: {
    notFound: 'هذه الصفحة غير موجودة',
    notFoundBody: 'ربما تغيّر العنوان، أو لم يعد المنتج معروضًا بهذه اللغة.',
    error: 'حدث خطأ ما',
    errorBody: 'يرجى المحاولة مرة أخرى بعد قليل.',
    home: 'الذهاب إلى المتجر',
  },
};

/**
 * 404 and 500.
 *
 * Both render a real page at the right status code. A 404 served as HTTP 200 —
 * a soft 404 — is what section 8A forbids, because it tells a crawler an
 * address is valid when it is not, and the status is set by Vike from
 * ``abortStatusCode``.
 */
export default function ErrorPage() {
  const pageContext = usePageContext();
  const { locale, href } = useLocale();
  const copy = COPY[locale] ?? COPY.en;
  const is404 = pageContext.is404 || pageContext.abortStatusCode === 404;

  return (
    <>
      <h1>{is404 ? copy.notFound : copy.error}</h1>
      <p>{is404 ? copy.notFoundBody : copy.errorBody}</p>
      <p>
        <a href={href('/')}>{copy.home}</a>
      </p>
    </>
  );
}
