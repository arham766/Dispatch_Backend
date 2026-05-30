# Checkout Flow — fast Kane testmd reproduction
#
# Bundled into 3 mega-steps (was 10). Each Kane step costs ~30s of
# agent reasoning, so a flow with fewer steps runs ~3-4× faster while
# producing the same verdict.
#
# Total expected runtime on a healthy run: ~45-75s (was ~5-6min).

## Steps

1. Navigate to `$STAGING_BASE_URL/`, wait for the checkout form to load,
   then fill the form with: card number `4111 1111 1111 1111`,
   expiry `12/28`, CVV `123`, cardholder name `Test User`.

2. Click the **Pay** button and wait for the result.

3. **Assert** that the page now shows an order confirmation with an
   order number visible. **Store** the order number **as** `order_number`,
   and if the page shows any error message **store** it **as** `error_text`.
