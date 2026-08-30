/**
 * The dataLayer, the consent signal, and the GTM loader.
 *
 * Every measurement event in the storefront goes through ``pushEvent``. Nothing
 * calls ``window.dataLayer.push`` directly, and nothing calls gtag, fbq or
 * ttq at all — tags are GTM's job, and a pixel fired from application code is
 * a tag nobody can see, version or turn off.
 *
 * Consent is the one exception: ``gtag('consent', ...)`` is not a tag, it is the
 * gate every tag reads, so it has to be set from here rather than inside the
 * container.
 */

/** The first-party cookie that remembers the shopper's consent choice. */
export const CONSENT_COOKIE = 'consent';

/**
 * Clear the previous ecommerce object before pushing a new one.
 *
 * GA4 merges successive dataLayer pushes, so without this the items from a
 * ``view_item`` are still present when ``add_to_cart`` fires and the second
 * event reports the first one's basket. It is the single most common ecommerce
 * tagging defect and it is invisible in the UI.
 */
export function pushEvent(payload) {
  if (typeof window === 'undefined') return;
  window.dataLayer = window.dataLayer || [];

  const { event, locale, ...ecommerce } = payload;
  window.dataLayer.push({ ecommerce: null });
  window.dataLayer.push({ event, locale, ecommerce });
}

/**
 * The consent choice stored in a Cookie header, or ``null`` if there isn't one.
 *
 * Read on the server so the ``default`` state in the first HTML response already
 * reflects a returning visitor's decision — otherwise their first hit of every
 * session is denied until the banner re-fires an update.
 */
export function readConsentCookie(cookieHeader) {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(';')) {
    const [name, ...rest] = part.trim().split('=');
    if (name === CONSENT_COOKIE) {
      const value = rest.join('=');
      return value === 'granted' || value === 'denied' ? value : null;
    }
  }
  return null;
}

/** The four ad/analytics consent keys set to one state. */
function consentGroup(state) {
  return {
    ad_storage: state,
    ad_user_data: state,
    ad_personalization: state,
    analytics_storage: state,
  };
}

/**
 * Persist the shopper's choice and tell any loaded tag about it.
 *
 * The cookie is what stops the banner reappearing and what the server reads next
 * visit; the ``update`` is what changes the current page, where GTM has already
 * loaded and read the ``default``.
 */
export function recordConsent(choice) {
  if (typeof document === 'undefined') return;
  const value = choice === 'granted' ? 'granted' : 'denied';

  const year = 60 * 60 * 24 * 365;
  document.cookie = `${CONSENT_COOKIE}=${value}; path=/; max-age=${year}; samesite=lax`;

  if (typeof window.gtag === 'function') {
    window.gtag('consent', 'update', consentGroup(value));
  }
}

/**
 * Consent Mode v2 defaults, and the GTM loader.
 *
 * Returned as a string because it must be in the first HTML response, before
 * GTM: consent defaults set after the container has loaded are set after tags
 * have already decided what to do, which is exactly the failure Consent Mode
 * exists to prevent.
 *
 * With no stored choice everything defaults to ``denied``. A shopper who has not
 * answered has not consented, and ``ad_user_data``/``ad_personalization`` are
 * the two v2 added — omitting them means Ads treats the whole signal as missing.
 * ``consent`` is the shopper's remembered decision (see ``readConsentCookie``);
 * ``'granted'`` opens the defaults so a returning visitor is measured from the
 * first hit.
 */
export function consentAndGtmSnippet(containerId, consent) {
  const granted = consent === 'granted';
  const state = granted ? 'granted' : 'denied';

  // No point waiting for an update that will not come, and redaction only means
  // anything while ad_storage is denied.
  const tail = granted ? '' : ',wait_for_update:500';
  const redaction = granted ? '' : `\ngtag('set','ads_data_redaction',true);`;

  const consentJs = `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
gtag('consent','default',{ad_storage:'${state}',ad_user_data:'${state}',ad_personalization:'${state}',analytics_storage:'${state}',functionality_storage:'granted',security_storage:'granted'${tail}});${redaction}`;

  if (!containerId) {
    // No container configured. The defaults are still set, so a container added
    // later by any means starts from the right state rather than from nothing.
    return `<script>${consentJs}</script>`;
  }

  const loader = `(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);})(window,document,'script','dataLayer','${containerId}');`;

  return `<script>${consentJs}
${loader}</script>`;
}
