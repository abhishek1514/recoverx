import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../services/api';
import { CURRENCIES } from '../utils/countries';


function loadRazorpayScript() {

  return new Promise((resolve) => {
    if (window.Razorpay) {
      resolve(true);
      return;
    }
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

export default function PaymentCheckout() {
  const navigate = useNavigate();

  const [amount, setAmount] = useState('500');
  const [currency, setCurrency] = useState('INR');
  const [customerName, setCustomerName] = useState('Acme Global Technologies');
  const [customerEmail, setCustomerEmail] = useState('finance@acmeglobal.com');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handlePay = async (e) => {
    e.preventDefault();
    setError(null);

    const numAmount = parseFloat(amount);
    if (isNaN(numAmount) || numAmount <= 0) {
      setError('Please enter a valid payment amount greater than 0.');
      return;
    }

    try {
      setLoading(true);

      // 1. Create Razorpay Test Order via Backend (Calls real Razorpay Orders API)
      const orderData = await api.createRazorpayOrder({
        amount: numAmount,
        currency: currency,
        customer_name: customerName,
        customer_email: customerEmail,
      });

      const { order_id, key_id, amount_subunits } = orderData;

      // 2. Load Razorpay Checkout Script
      const scriptLoaded = await loadRazorpayScript();

      if (!scriptLoaded || !window.Razorpay) {
        setError('Unable to load Razorpay Checkout script from CDN. Please check your internet connection.');
        setLoading(false);
        return;
      }

      // 3. Configure Razorpay Standard Checkout
      const options = {
        key: key_id,
        amount: amount_subunits,
        currency: currency,
        name: 'RecoverX Test Checkout',
        description: 'AI Revenue Recovery & Settlement Friction Test',
        order_id: order_id,
        prefill: {
          name: customerName,
          email: customerEmail,
          contact: '9999999999',
        },
        theme: {
          color: '#3b82f6',
        },
        modal: {
          ondismiss: () => {
            setLoading(false);
          },
        },
        handler: async function (response) {
          try {
            // 4. Send signature to backend for verification
            await api.verifyRazorpayPayment({
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_order_id: response.razorpay_order_id || order_id,
              razorpay_signature: response.razorpay_signature,
            });

            // 5. Navigate to Live Payment Status Tracker
            navigate(`/payments/${order_id}/status`);
          } catch (verifyErr) {
            console.error('Verification error:', verifyErr);
            // Navigate to status page anyway to allow webhook to catch up
            navigate(`/payments/${order_id}/status`);
          }
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.on('payment.failed', function (resp) {
        setError(`Payment failed: ${resp.error.description || 'Transaction declined'}`);
        setLoading(false);
      });
      rzp.open();
    } catch (err) {
      setError(err.message || 'Failed to initiate Razorpay checkout.');
      setLoading(false);
    }
  };

  return (
    <div className="payment-checkout-page" style={{ maxWidth: '640px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
          <Link to="/" style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            ← Back to Dashboard
          </Link>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff' }}>
            Make a Test Payment
          </h1>
          <span
            style={{
              padding: '0.2rem 0.65rem',
              borderRadius: '9999px',
              fontSize: '0.75rem',
              fontWeight: 600,
              background: 'rgba(59, 130, 246, 0.15)',
              color: 'var(--accent-blue)',
              border: '1px solid rgba(59, 130, 246, 0.3)',
            }}
          >
            Razorpay Test Mode
          </span>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', marginTop: '0.25rem' }}>
          Complete a realistic test checkout. RecoverX automatically catches the payment webhook and analyzes settlement risk.
        </p>
      </div>

      {/* Test Mode Banner */}
      <div
        style={{
          background: 'rgba(59, 130, 246, 0.08)',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          borderRadius: 'var(--radius-md)',
          padding: '1rem 1.25rem',
          marginBottom: '1.75rem',
          display: 'flex',
          gap: '0.75rem',
          alignItems: 'flex-start',
        }}
      >
        <span style={{ fontSize: '1.25rem' }}>🛡️</span>
        <div style={{ fontSize: '0.85rem', color: '#cbd5e1', lineHeight: '1.45' }}>
          <strong style={{ color: '#fff' }}>Razorpay Test Mode — No Real Money:</strong> This opens the official
          Razorpay Standard Checkout. After payment, the webhook automatically normalizes the transaction and starts RecoverX recovery analysis.
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: '1rem',
            background: 'var(--danger-bg)',
            border: '1px solid var(--danger)',
            borderRadius: 'var(--radius-md)',
            color: '#fca5a5',
            marginBottom: '1.5rem',
            fontSize: '0.9rem',
          }}
        >
          <strong>Notice:</strong> {error}
        </div>
      )}

      {/* Checkout Form */}
      <div className="table-card" style={{ padding: '2rem' }}>
        <form onSubmit={handlePay}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: '1rem', marginBottom: '1.25rem' }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Payment Amount *</label>
              <input
                type="number"
                step="any"
                min="1"
                required
                className="form-input"
                placeholder="e.g. 500"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>

            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Currency *</label>
              <select
                className="form-select"
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
              >
                {CURRENCIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.code} ({c.symbol})
                  </option>
                ))}
              </select>
            </div>
          </div>


          <div className="form-group">
            <label className="form-label">Customer / Business Name</label>
            <input
              type="text"
              className="form-input"
              placeholder="e.g. Acme Global Corp"
              value={customerName}
              onChange={(e) => setCustomerName(e.target.value)}
            />
          </div>

          <div className="form-group" style={{ marginBottom: '1.75rem' }}>
            <label className="form-label">Customer Email</label>
            <input
              type="email"
              className="form-input"
              placeholder="e.g. billing@acmeglobal.com"
              value={customerEmail}
              onChange={(e) => setCustomerEmail(e.target.value)}
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary"
            style={{
              width: '100%',
              padding: '0.85rem',
              fontSize: '1rem',
              fontWeight: 600,
              justifyContent: 'center',
            }}
          >
            {loading ? 'Opening Razorpay Checkout...' : 'Pay with Razorpay →'}
          </button>
        </form>
      </div>

      {/* Note on Large-Value Distinction */}
      <div style={{ marginTop: '1.5rem', textAlign: 'center', fontSize: '0.825rem', color: 'var(--text-muted)' }}>
        Looking for mega-scale or multi-billion enterprise simulations? Use{' '}
        <Link to="/transactions/new" style={{ color: 'var(--accent-blue)', textDecoration: 'underline' }}>
          Analyze a Payment (Live Test Mode)
        </Link>
        .
      </div>
    </div>
  );
}
