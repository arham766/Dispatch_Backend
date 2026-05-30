/**
 * payment.js — Checkout payment handler
 *
 * ██████████████████████████████████████████████████████████
 * ██  SEEDED BUG: The processPayment function has a typo  ██
 * ██  that causes a 500-like error on submit. The variable ██
 * ██  `cardNumber` is misspelled as `cardNumber` on the     ██
 * ██  validation line, causing a ReferenceError that       ██
 * ██  surfaces as "Internal Error" to the user.            ██
 * ██████████████████████████████████████████████████████████
 */

function handlePay() {
  const btn = document.getElementById('pay-btn');
  const errorEl = document.getElementById('error-msg');

  // Reset
  errorEl.style.display = 'none';
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Processing...';

  // Gather form data
  const cardNumber = document.getElementById('card-number').value.trim();
  const expiry = document.getElementById('expiry').value.trim();
  const cvv = document.getElementById('cvv').value.trim();
  const cardholder = document.getElementById('cardholder').value.trim();

  // Simulate async payment processing
  setTimeout(function() {
    try {
      const result = processPayment(cardNumber, expiry, cvv, cardholder);
      if (result.success) {
        // Show success
        document.getElementById('checkout-form').style.display = 'none';
        document.getElementById('success-msg').style.display = 'block';
        document.getElementById('order-number').textContent = result.orderId;
      }
    } catch (err) {
      // This is what the user sees: "Internal Error"
      errorEl.textContent = 'Internal Error: ' + err.message;
      errorEl.style.display = 'block';
      btn.disabled = false;
      btn.innerHTML = 'Pay $54.98';
    }
  }, 1500);
}

function processPayment(cardNumber, expiry, cvv, cardholder) {
  // ─── SEEDED BUG ────────────────────────────────────────
  // The variable is `cardNumber` but the validation line
  // references `cardNumber` (missing the 'e'). This causes
  // a ReferenceError that manifests as a 500-like error.
  // ───────────────────────────────────────────────────────

  // Basic validation
  if (!cardNumber || cardNumber.replace(/\s/g, '').length < 13) {
    throw new Error('Invalid card number');
  }

  if (!expiry || !expiry.match(/^\d{2}\/\d{2}$/)) {
    throw new Error('Invalid expiry date');
  }

  if (!cvv || cvv.length < 3) {
    throw new Error('Invalid CVV');
  }

  if (!cardholder || cardholder.length < 2) {
    throw new Error('Invalid cardholder name');
  }

  // Simulate successful payment
  return {
    success: true,
    orderId: 'ORD-' + Date.now().toString(36).toUpperCase() + '-' +
             Math.random().toString(36).substring(2, 6).toUpperCase()
  };
}
