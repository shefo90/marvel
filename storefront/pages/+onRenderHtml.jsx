import { renderToString } from 'react-dom/server';
import { dangerouslySkipEscape, escapeInject } from 'vike/server';

import Layout from '../layouts/LayoutDefault.jsx';
import { buildHead } from '../utils/head.js';
import { localeOf } from '../utils/locales.js';

/**
 * Server render.
 *
 * ``lang`` and ``dir`` are set on <html>, not on a wrapper div, because that is
 * where a screen reader and the browser's own bidi algorithm look. Arabic in a
 * left-to-right document is not merely ugly: punctuation lands on the wrong end
 * of the sentence.
 */
export default function onRenderHtml(pageContext) {
  const { Page, data } = pageContext;
  const locale = data?.locale ?? pageContext.routeParams?.locale ?? 'en';
  const { code, dir } = localeOf(locale);

  const html = Page
    ? renderToString(
        <Layout pageContext={pageContext}>
          <Page />
        </Layout>,
      )
    : '';

  const head = buildHead({ ...(data?.head ?? {}), locale });

  return escapeInject`<!DOCTYPE html>
<html lang="${code}" dir="${dir}">
  <head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    ${dangerouslySkipEscape(head)}
  </head>
  <body>
    <div id="root">${dangerouslySkipEscape(html)}</div>
  </body>
</html>`;
}
