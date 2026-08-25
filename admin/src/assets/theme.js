/**
 * Ant Design tokens, given the storefront's palette.
 *
 * The two apps share no code and no stylesheet — the admin is a client-side SPA
 * on Ant Design, the storefront is server-rendered with its own SCSS — so they
 * agree on identity by being handed the same values, not by importing each
 * other. That is deliberate: merging them would put admin code in the same
 * bundle as the storefront's tracking pixels, which is what the admin's CSP
 * exists to prevent.
 *
 * When a colour changes, it changes in two places: here and
 * `storefront/assets/styles/_variables.scss`. Two files is the cost of keeping
 * the bundles apart, and it is cheaper than the alternative.
 */
const INK = '#16130f';
const INK_SOFT = '#6b625a';
const LINE = '#e7e1da';
const GROUND = '#faf8f5';
const ACCENT = '#a63d5a';
const NIGHT = '#1f1b17';

export const adminTheme = {
  token: {
    colorPrimary: ACCENT,
    colorLink: '#7d2c43',
    colorText: INK,
    colorTextSecondary: INK_SOFT,
    colorBorder: LINE,
    colorBorderSecondary: '#f0ebe4',
    colorBgLayout: GROUND,
    colorBgContainer: '#ffffff',
    colorError: '#b3261e',
    colorSuccess: '#3f7d51',
    colorWarning: '#b7791f',

    // The same family the storefront serves, so an operator editing Arabic
    // content sees it in the face the shopper will.
    fontFamily:
      "'IBM Plex Sans Arabic', system-ui, -apple-system, 'Segoe UI', Tahoma, sans-serif",
    fontSize: 14,

    borderRadius: 8,
    borderRadiusLG: 10,
    wireframe: false,
  },
  components: {
    Layout: {
      // A warm near-black, matching the storefront's hero panel. Ant's default
      // sider is a cool blue-grey that belongs to a different product.
      siderBg: NIGHT,
      triggerBg: '#332b25',
      headerBg: '#ffffff',
      headerHeight: 60,
      bodyBg: GROUND,
    },
    Menu: {
      darkItemBg: NIGHT,
      darkSubMenuItemBg: NIGHT,
      darkItemSelectedBg: ACCENT,
      darkItemColor: 'rgba(246, 241, 234, 0.72)',
      darkItemHoverColor: '#f6f1ea',
      darkItemSelectedColor: '#ffffff',
      itemBorderRadius: 8,
    },
    Button: { fontWeight: 500, primaryShadow: 'none', defaultShadow: 'none' },
    Table: {
      headerBg: GROUND,
      headerColor: INK_SOFT,
      headerSplitColor: 'transparent',
      rowHoverBg: '#fbf9f6',
    },
    Card: { colorBorderSecondary: LINE },
    Tabs: { itemSelectedColor: INK, inkBarColor: INK },
    Input: { activeShadow: 'none' },
    Segmented: { itemSelectedBg: INK, itemSelectedColor: '#ffffff' },
  },
};
