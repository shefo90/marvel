// The order number, not the internal id. It is the immutable commerce identity
// and doubles as the GA4/Ads transaction_id -- an id in the URL would leak a
// sequence and mean nothing to the shopper.
export default '/@locale/order/@orderNumber';
