import { hydrateRoot } from 'react-dom/client';

import Layout from '../layouts/LayoutDefault.jsx';
import { localeOf } from '../utils/locales.js';
import '../assets/styles/main.scss';

let root;

/**
 * Hydration, and client-side navigation after it.
 *
 * The <html> attributes are updated on every navigation because switching
 * language is a route change, not a reload — without this, moving from the
 * English page to the Arabic one would leave the document declaring itself
 * left-to-right English.
 */
export default function onRenderClient(pageContext) {
  const { Page, data } = pageContext;
  const locale = data?.locale ?? pageContext.routeParams?.locale ?? 'en';
  const { code, dir } = localeOf(locale);
  document.documentElement.lang = code;
  document.documentElement.dir = dir;
  if (data?.head?.title) document.title = data.head.title;

  const page = (
    <Layout pageContext={pageContext}>
      <Page />
    </Layout>
  );

  const container = document.getElementById('root');
  if (!root) {
    root = hydrateRoot(container, page);
  } else {
    root.render(page);
  }
}
