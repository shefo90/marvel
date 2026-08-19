import Footer from '../components/common/Footer/Footer.jsx';
import Header from '../components/common/Header/Header.jsx';
import { CartProvider } from '../hooks/useCart.jsx';
import { LocaleProvider } from '../hooks/useLocale.jsx';
import { PageContextProvider } from '../hooks/usePageContext.jsx';

/**
 * The chrome every page sits inside.
 *
 * Deliberately thin. The header and footer are the only shared furniture, and
 * the language switch lives in the header because it is a navigation act — it
 * changes the URL, and the URL is the only thing that decides language.
 */
export default function Layout({ children, pageContext }) {
  const locale = pageContext?.data?.locale ?? pageContext?.routeParams?.locale ?? 'en';
  const urlPathname = pageContext?.urlPathname ?? '/';

  return (
    <PageContextProvider pageContext={pageContext}>
      <LocaleProvider locale={locale} pathname={urlPathname}>
        <CartProvider>
          <a className="skip-link" href="#main">
            Skip to content
          </a>
          <Header />
          <main id="main" className="page">
            {children}
          </main>
          <Footer />
        </CartProvider>
      </LocaleProvider>
    </PageContextProvider>
  );
}
