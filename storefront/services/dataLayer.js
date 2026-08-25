/**
 * The dataLayer, and nothing else.
 *
 * Every measurement event in the storefront goes through ``pushEvent``. Nothing
 * calls ``window.dataLayer.push`` directly, and nothing calls gtag, fbq or
 * ttq at all — tags are GTM's job, and a pixel fired from application code is
 * a tag nobody can see, version or turn off.
 */

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
 * Consent Mode v2 defaults, and the GTM loader.
 *
 * Returned as a string because it must be in the first HTML response, before
 * GTM: consent defaults set after the container has loaded are set after tags
 * have already decided what to do, which is exactly the failure Consent Mode
 * exists to prevent.
 *
 * Everything defaults to ``denied``. A shopper who has not answered has not
 * consented, and ``ad_user_data``/``ad_personalization`` are the two v2 added —
 * omitting them means Ads treats the whole signal as missing.
 */
export function consentAndGtmSnippet(containerId) {
  const consent = `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',analytics_storage:'denied',functionality_storage:'granted',security_storage:'granted',wait_for_update:500});
gtag('set','ads_data_redaction',true);`;

  if (!containerId) {
    // No container configured. The defaults are still set, so a container added
    // later by any means starts from denied rather than from nothing.
    return `<script>${consent}</script>`;
  }

  const loader = `(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);})(window,document,'script','dataLayer','${containerId}');`;

  return `<script>${consent}
${loader}</script>`;
}
