import { renderToString } from 'react-dom/server';
import { dangerouslySkipEscape, escapeInject } from 'vike/server';

import Layout from '../layouts/LayoutDefault.jsx';
import { consentAndGtmSnippet, readConsentCookie } from '../services/dataLayer.js';
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

  // Consent defaults and the container, in the FIRST response and before
  // anything else. Consent set after GTM has loaded is set after tags have
  // already decided what to do. A returning visitor's remembered choice rides
  // in on the cookie, so their defaults already match it -- no denied first hit.
  const consent = readConsentCookie(pageContext.headers?.cookie);
  const measurement = consentAndGtmSnippet(process.env.GTM_CONTAINER_ID, consent);

  return escapeInject`<!DOCTYPE html>
<html lang="${code}" dir="${dir}">
  <head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <!-- One dual-script family for both locales. Section 6.7 asks for exactly
         this: an Arabic page set in a Latin-first stack falls back to whatever
         the OS happens to have, so the same shop looks like a different brand
         after the language switch. IBM Plex Sans Arabic covers both scripts, so
         headings, prices and product names keep one voice either side of it.

         Still short of 6.7's full contract: this is Google's CDN rather than
         self-hosted files subset by unicode-range, so it costs a third-party
         connection and ships more of the family than either page needs. -->
    <link rel="preconnect" href="https://fonts.googleapis.com"/>
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap"/>
    ${dangerouslySkipEscape(measurement)}
    ${dangerouslySkipEscape(head)}
  </head>
  <body>
    <div id="root">${dangerouslySkipEscape(html)}</div>
  </body>
</html>`;
}
