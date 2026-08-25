import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency } from '../utils/format';
import { COUNTRIES, CURRENCIES, COUNTRY_MAP, getDefaultCurrencyForCountry } from '../utils/countries';

export default function NewTransaction() {
  const navigate = useNavigate();

  const [amount, setAmount] = useState('580000');
  const [countryCode, setCountryCode] = useState('IN');
  const [currency, setCurrency] = useState('INR');
  const [hasManualCurrencyChange, setHasManualCurrencyChange] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState('received');
  const [customerComplete, setCustomerComplete] = useState(false);
  const [customerName, setCustomerName] = useState('');
  const [customerEmail, setCustomerEmail] = useState('');
  const [documentAvailable, setDocumentAvailable] = useState(true);
  const [invoiceAmount, setInvoiceAmount] = useState('580000');
  const [invoiceCurrency, setInvoiceCurrency] = useState('INR');
  const [invoiceReference, setInvoiceReference] = useState('INV-DEMO-580K');

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleCountryChange = (newCode) => {
    setCountryCode(newCode);
    const defCurr = getDefaultCurrencyForCountry(newCode);
    setCurrency(defCurr);
    setInvoiceCurrency(defCurr);
    setHasManualCurrencyChange(false);
  };

  const handleCurrencyChange = (newCurrency) => {
    setCurrency(newCurrency);
    setInvoiceCurrency(newCurrency);
    setHasManualCurrencyChange(true);
  };

  const applyPreset = (preset) => {
    setAmount(preset.amount);
    setCountryCode(preset.countryCode);
    setCurrency(preset.currency);
    setHasManualCurrencyChange(false);
    setPaymentStatus(preset.paymentStatus);
    setCustomerComplete(preset.customerComplete);
    setCustomerName(preset.customerName || '');
    setCustomerEmail(preset.customerEmail || '');
    setDocumentAvailable(preset.documentAvailable);
    setInvoiceAmount(preset.invoiceAmount || preset.amount);
    setInvoiceCurrency(preset.invoiceCurrency || preset.currency);
    setInvoiceReference(preset.invoiceReference || `INV-${preset.currency}-${Date.now().toString().slice(-4)}`);
  };

  const selectedCountry = COUNTRY_MAP[countryCode] || { code: countryCode, name: countryCode, defaultCurrency: 'USD', flag: '🌐' };
  const isCurrencyMismatch = selectedCountry.defaultCurrency !== currency;

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      setError(null);

      const payload = {
        amount: Number(amount),
        currency: currency.toUpperCase(),
        country_code: countryCode.toUpperCase(),
        payment_status: paymentStatus,
        customer_information_complete: customerComplete,
        customer_name: customerComplete ? customerName || 'Enterprise Partner LLC' : customerName || '',
        customer_email: customerComplete ? customerEmail || 'finance@enterprisepartner.com' : customerEmail || '',
        document_available: documentAvailable,
        invoice_amount: invoiceAmount ? Number(invoiceAmount) : null,
        invoice_currency: invoiceCurrency ? invoiceCurrency.toUpperCase() : currency.toUpperCase(),
        invoice_reference: invoiceReference || `INV-${currency}-${Date.now().toString().slice(-4)}`,
      };

      const result = await api.createTestTransaction(payload);
      // Directly navigate to newly analyzed case details
      navigate(`/cases/${result.case_id}`);
    } catch (err) {
      setError(err.message || 'Failed to analyze payment.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="new-transaction-page" style={{ maxWidth: '840px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Page Header */}
      <div style={{ marginBottom: '1.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
          <Link to="/dashboard" style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            ← Dashboard
          </Link>
          <span style={{ color: 'var(--border-light)' }}>/</span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Analyze a Payment</span>
        </div>
        <h1 style={{ fontSize: '1.65rem', fontWeight: 700, color: '#fff', marginBottom: '0.35rem' }}>
          Analyze a Payment
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
          Check whether a high-value or international payment needs recovery action before settlement review.
        </p>
      </div>

      {/* Quick Example Scenarios */}
      <div className="table-card" style={{ padding: '1.25rem', marginBottom: '1.75rem', background: 'rgba(22, 31, 48, 0.6)' }}>
        <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '0.75rem' }}>
          Quick Example Scenarios (Click to Pre-fill)
        </div>
        <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={() =>
              applyPreset({
                amount: '580000',
                currency: 'INR',
                countryCode: 'IN',
                paymentStatus: 'received',
                customerComplete: false,
                documentAvailable: true,
                invoiceAmount: '580000',
                invoiceCurrency: 'INR',
                invoiceReference: 'INV-DEMO-580K',
              })
            }
            className="btn btn-secondary"
            style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}
          >
            🇮🇳 India · ₹5.80L Payment (Missing Customer Info)
          </button>

          <button
            type="button"
            onClick={() =>
              applyPreset({
                amount: '5000000000',
                currency: 'USD',
                countryCode: 'US',
                paymentStatus: 'received',
                customerComplete: false,
                documentAvailable: true,
                invoiceAmount: '5000000000',
                invoiceCurrency: 'USD',
                invoiceReference: 'INV-GLOBAL-5B',
              })
            }
            className="btn btn-secondary"
            style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem', borderColor: 'var(--purple)' }}
          >
            🇺🇸 United States · $5.00B Payment (Missing Customer Info)
          </button>

          <button
            type="button"
            onClick={() =>
              applyPreset({
                amount: '50000',
                currency: 'EUR',
                countryCode: 'DE',
                paymentStatus: 'captured',
                customerComplete: true,
                customerName: 'Hans Schmidt GmbH',
                customerEmail: 'finance@schmidt-gmbh.de',
                documentAvailable: true,
                invoiceAmount: '50000',
                invoiceCurrency: 'EUR',
                invoiceReference: 'INV-EUR-50K',
              })
            }
            className="btn btn-secondary"
            style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}
          >
            🇩🇪 Germany · €50,000 Payment (Complete Info)
          </button>

          <button
            type="button"
            onClick={() =>
              applyPreset({
                amount: '150',
                currency: 'USD',
                countryCode: 'US',
                paymentStatus: 'captured',
                customerComplete: true,
                customerName: 'Alice Smith',
                customerEmail: 'alice@example.com',
                documentAvailable: true,
                invoiceAmount: '150',
                invoiceCurrency: 'USD',
                invoiceReference: 'INV-SMALL-150',
              })
            }
            className="btn btn-secondary"
            style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}
          >
            💳 $150 Standard Payment (Low Risk)
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: '1rem 1.25rem', background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-md)', color: '#fca5a5', marginBottom: '1.5rem' }}>
          <strong>Notice:</strong> {error}
        </div>
      )}

      {/* Main Friendly Entry Form */}
      <div className="table-card" style={{ padding: '2rem' }}>
        <form onSubmit={handleSubmit}>
          {/* Section 1: Customer Country & Payment Amount */}
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#fff', marginBottom: '1.25rem' }}>
            1. Payment & Customer Origin
          </h2>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1.25rem', marginBottom: '1.5rem' }}>
            {/* Customer Country */}
            <div className="form-group">
              <label className="form-label">Customer Country *</label>
              <select
                value={countryCode}
                onChange={(e) => handleCountryChange(e.target.value)}
                className="form-select"
              >
                {COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.flag} {c.name} ({c.code})
                  </option>
                ))}
              </select>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem', display: 'block' }}>
                Suggests domestic currency: <strong>{selectedCountry.defaultCurrency}</strong>
              </span>
            </div>

            {/* Currency */}
            <div className="form-group">
              <label className="form-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>Payment Currency *</span>
                {hasManualCurrencyChange && (
                  <span style={{ fontSize: '0.7rem', color: 'var(--cyan)' }}>
                    Custom selection
                  </span>
                )}
              </label>
              <select
                value={currency}
                onChange={(e) => handleCurrencyChange(e.target.value)}
                className="form-select"
              >
                {CURRENCIES.map((cur) => (
                  <option key={cur.code} value={cur.code}>
                    {cur.name}
                  </option>
                ))}
              </select>

              {isCurrencyMismatch && (
                <div
                  style={{
                    marginTop: '0.45rem',
                    padding: '0.45rem 0.65rem',
                    background: 'rgba(56, 189, 248, 0.1)',
                    border: '1px solid rgba(56, 189, 248, 0.25)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.75rem',
                    color: 'var(--cyan)',
                    lineHeight: 1.4,
                  }}
                >
                  ℹ️ <strong>Customer country differs from transaction currency.</strong>
                  <div style={{ color: 'var(--text-secondary)', marginTop: '0.15rem' }}>
                    International currency: <strong>{currency}</strong> (Customer country: {selectedCountry.name})
                  </div>
                </div>
              )}
            </div>

            {/* Amount */}
            <div className="form-group">
              <label className="form-label">Payment Amount *</label>
              <input
                type="number"
                step="0.01"
                required
                min="0.01"
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value);
                  setInvoiceAmount(e.target.value);
                }}
                className="form-input"
                placeholder="e.g. 580000 or 5000000000"
              />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem', display: 'block' }}>
                Formatted: <strong>{formatCurrency(amount, currency, true)}</strong>
              </span>
            </div>

            {/* Payment Received Status */}
            <div className="form-group">
              <label className="form-label">Has the payment been received? *</label>
              <select
                value={paymentStatus}
                onChange={(e) => setPaymentStatus(e.target.value)}
                className="form-select"
              >
                <option value="received">✓ Yes (Payment received)</option>
                <option value="captured">✓ Yes (Payment captured)</option>
                <option value="pending">⏳ In processing / Pending</option>
                <option value="failed">⚠ Failed / Problematic hold</option>
              </select>
            </div>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '1.75rem 0' }} />

          {/* Section 2: Customer Information Status */}
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#fff', marginBottom: '1.25rem' }}>
            2. Customer Contact Details
          </h2>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1.25rem', marginBottom: '1.5rem' }}>
            <div className="form-group">
              <label className="form-label">Do you have the customer's required information? *</label>
              <select
                value={customerComplete ? 'complete' : 'incomplete'}
                onChange={(e) => setCustomerComplete(e.target.value === 'complete')}
                className="form-select"
              >
                <option value="incomplete">⚠ Missing information (Customer details incomplete)</option>
                <option value="complete">✓ Complete (Full name and email are on file)</option>
              </select>
            </div>

            {customerComplete && (
              <>
                <div className="form-group">
                  <label className="form-label">Customer Legal / Business Name</label>
                  <input
                    type="text"
                    value={customerName}
                    onChange={(e) => setCustomerName(e.target.value)}
                    className="form-input"
                    placeholder="e.g. Asha Sharma or Enterprise Corp"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Customer Email Address</label>
                  <input
                    type="email"
                    value={customerEmail}
                    onChange={(e) => setCustomerEmail(e.target.value)}
                    className="form-input"
                    placeholder="e.g. billing@enterprise.com"
                  />
                </div>
              </>
            )}
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '1.75rem 0' }} />

          {/* Section 3: Invoices & Supporting Documentation */}
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#fff', marginBottom: '1.25rem' }}>
            3. Invoices & Commercial Documentation
          </h2>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1.25rem', marginBottom: '1.5rem' }}>
            <div className="form-group">
              <label className="form-label">Is the invoice/supporting document available? *</label>
              <select
                value={documentAvailable ? 'available' : 'missing'}
                onChange={(e) => setDocumentAvailable(e.target.value === 'available')}
                className="form-select"
              >
                <option value="available">✓ Yes (Commercial invoice or receipt is available)</option>
                <option value="missing">⚠ Not yet (Document missing)</option>
              </select>
            </div>

            {documentAvailable && (
              <>
                <div className="form-group">
                  <label className="form-label">Invoice / Order Reference</label>
                  <input
                    type="text"
                    value={invoiceReference}
                    onChange={(e) => setInvoiceReference(e.target.value)}
                    className="form-input"
                    placeholder="e.g. INV-2026-001"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Invoice Amount</label>
                  <input
                    type="number"
                    step="0.01"
                    value={invoiceAmount}
                    onChange={(e) => setInvoiceAmount(e.target.value)}
                    className="form-input"
                    placeholder="Invoice amount"
                  />
                </div>
              </>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem', marginTop: '2rem' }}>
            <Link to="/dashboard" className="btn btn-secondary" style={{ padding: '0.75rem 1.5rem' }}>
              Cancel
            </Link>
            <button
              type="submit"
              disabled={submitting}
              className="btn btn-primary"
              style={{ padding: '0.75rem 2.25rem', fontSize: '0.95rem', fontWeight: 600 }}
            >
              {submitting ? 'Analyzing Payment...' : 'Analyze Payment →'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

