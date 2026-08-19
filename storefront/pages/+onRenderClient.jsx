import { hydrateRoot } from 'react-dom/client';

import Layout from '../layouts/LayoutDefault.jsx';
import '../assets/styles/main.scss';

let root;

/**
 * Hydration, and client-side navigation after it.
 *
 * Deliberately does NOT touch <html lang> or <html dir>. Section 6.7 bans
 * client-side assignment of them and makes locale switching a full navigation,
 * so the server document template owns both and they can never disagree with
 * the URL. The language links carry rel="external" to force that full load.
 *
 * The title still updates, because a client-side navigation within one locale
 * genuinely changes the page.
 */
export default function onRenderClient(pageContext) {
  const { Page, data } = pageContext;
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
