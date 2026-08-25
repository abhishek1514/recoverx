import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency } from '../utils/format';

export default function CustomerResolution() {
  const { caseId } = useParams();
  const navigate = useNavigate();

  const [caseData, setCaseData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [validationResult, setValidationResult] = useState(null);

  // Form State
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [countryCode, setCountryCode] = useState('IN');
  const [invoiceAmount, setInvoiceAmount] = useState('');
  const [invoiceCurrency, setInvoiceCurrency] = useState('INR');
  const [invoiceReference, setInvoiceReference] = useState('');
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().split('T')[0]);
  const [notes, setNotes] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);

  const loadCase = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getCase(caseId);
      setCaseData(data);

      if (data.transaction) {
        setInvoiceAmount(data.transaction.amount || '');
        setInvoiceCurrency(data.transaction.currency || 'INR');
        setCountryCode(data.transaction.country_code || 'IN');
        setInvoiceReference(data.transaction.order_id || `INV-${caseId}`);
      }
    } catch (err) {
      setError(err.message || 'Failed to load details for customer resolution.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCase();
  }, [caseId]);

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      setError(null);
      setValidationResult(null);

      const formattedDate = invoiceDate ? new Date(invoiceDate).toISOString() : new Date().toISOString();

      let res;
      if (selectedFile) {
        const formData = new FormData();
        formData.append('customer_name', name);
        formData.append('customer_email', email);
        formData.append('country_code', countryCode);
        formData.append('invoice_amount', invoiceAmount);
        formData.append('invoice_currency', invoiceCurrency);
        formData.append('invoice_reference', invoiceReference);
        formData.append('invoice_date', formattedDate);
        formData.append('notes', notes);
        formData.append('file', selectedFile);

        res = await api.resolveCase(caseId, formData, true);
      } else {
        res = await api.resolveCase(caseId, {
          customer_name: name,
          customer_email: email,
          country_code: countryCode,
          invoice_amount: invoiceAmount ? Number(invoiceAmount) : null,
          invoice_currency: invoiceCurrency,
          invoice_reference: invoiceReference,
          invoice_date: formattedDate,
          notes: notes,
        });
      }


      setValidationResult(res);
      await loadCase();
    } catch (err) {
      setError(err.message || 'Submission failed.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
        Loading payment verification portal...
      </div>
    );
  }

  const tx = caseData?.transaction || {};

  return (
    <div className="customer-resolution-page" style={{ maxWidth: '820px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
          <Link to={`/cases/${caseId}`} style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            ← Back to Payment #{caseId}
          </Link>
        </div>
        <h1 style={{ fontSize: '1.65rem', fontWeight: 700, color: '#fff', marginBottom: '0.35rem' }}>
          Complete Payment Information
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
          We need a few details before this payment can move through settlement review.
        </p>
      </div>



      {/* Payment Summary Box */}
      <div
        style={{
          background: 'rgba(56, 189, 248, 0.08)',
          border: '1px solid rgba(56, 189, 248, 0.25)',
          borderRadius: 'var(--radius-md)',
          padding: '1.25rem 1.5rem',
          marginBottom: '1.75rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Payment Amount</div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>
            {formatCurrency(tx.amount, tx.currency, true)}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Reference ID</div>
          <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--cyan)' }}>
            {tx.payment_id || `pay_${tx.id}`}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Country of Origin</div>
          <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#fff' }}>
            {tx.country_code || 'IN'}
          </div>
        </div>
      </div>

      {/* Validation Result Box */}
      {validationResult && (
        <div
          style={{
            background:
              validationResult.status === 'PASS'
                ? 'rgba(16, 185, 129, 0.12)'
                : 'rgba(239, 68, 68, 0.12)',
            border: `1px solid ${
              validationResult.status === 'PASS' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)'
            }`,
            borderRadius: 'var(--radius-md)',
            padding: '1.5rem',
            marginBottom: '2rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '1.5rem' }}>
              {validationResult.status === 'PASS' ? '✓' : '⚠️'}
            </span>
            <h3 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#fff' }}>
              {validationResult.status === 'PASS'
                ? 'Information matches'
                : 'We found a mismatch'}
            </h3>
          </div>

          <p style={{ fontSize: '0.9rem', color: '#f8fafc', marginBottom: '1rem', lineHeight: 1.5 }}>
            {validationResult.status === 'PASS'
              ? 'Your submitted details match the transaction records and have been verified.'
              : 'One or more submitted values differ from our transaction records. A merchant review will be performed.'}
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginBottom: '1.25rem' }}>
            {(validationResult.checks || []).map((chk, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.6rem',
                  fontSize: '0.85rem',
                  background: 'rgba(0,0,0,0.3)',
                  padding: '0.45rem 0.75rem',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                <span style={{ color: chk.status === 'PASS' ? 'var(--success)' : 'var(--danger)', fontWeight: 700 }}>
                  {chk.status === 'PASS' ? '✓' : '✕'}
                </span>
                <span style={{ color: '#e2e8f0' }}>{chk.message}</span>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <Link to={`/cases/${caseId}`} className="btn btn-secondary" style={{ fontSize: '0.85rem' }}>
              ← Return to Payment Details
            </Link>
            <Link to={`/cases/${caseId}/review`} className="btn btn-primary" style={{ fontSize: '0.85rem' }}>
              {validationResult.status === 'PASS' ? 'Proceed to Merchant Review →' : 'View Merchant Review →'}
            </Link>
          </div>
        </div>
      )}

      {error && (
        <div style={{ padding: '1rem', background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-md)', color: '#fca5a5', marginBottom: '1.5rem' }}>
          <strong>Notice:</strong> {error}
        </div>
      )}

      {/* Main Friendly Form */}
      <div className="table-card" style={{ padding: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff', marginBottom: '1.25rem' }}>
          Please provide your details below
        </h2>

        <form onSubmit={handleSubmit}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1.25rem' }}>
            <div className="form-group">
              <label className="form-label">Full Legal / Business Name *</label>
              <input
                type="text"
                required
                placeholder="e.g. Asha Sharma"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label className="form-label">Email Address *</label>
              <input
                type="email"
                required
                placeholder="e.g. asha.sharma@enterprise.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label className="form-label">Country Code *</label>
              <input
                type="text"
                maxLength={2}
                required
                placeholder="IN"
                value={countryCode}
                onChange={(e) => setCountryCode(e.target.value.toUpperCase())}
                className="form-input"
              />
            </div>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '1.5rem 0' }} />

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1.25rem' }}>
            <div className="form-group">
              <label className="form-label">Invoice Amount *</label>
              <input
                type="number"
                step="0.01"
                required
                placeholder="580000"
                value={invoiceAmount}
                onChange={(e) => setInvoiceAmount(e.target.value)}
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label className="form-label">Invoice Currency *</label>
              <input
                type="text"
                maxLength={3}
                required
                placeholder="INR"
                value={invoiceCurrency}
                onChange={(e) => setInvoiceCurrency(e.target.value.toUpperCase())}
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label className="form-label">Invoice / Order Reference ID *</label>
              <input
                type="text"
                required
                placeholder="e.g. INV-2026-001"
                value={invoiceReference}
                onChange={(e) => setInvoiceReference(e.target.value)}
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label className="form-label">Invoice Date</label>
              <input
                type="date"
                value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)}
                className="form-input"
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Upload supporting document</label>
            <div className="file-dropzone" onClick={() => document.getElementById('file-input').click()}>
              <input
                id="file-input"
                type="file"
                accept=".pdf,.png,.jpg,.jpeg"
                onChange={handleFileChange}
                style={{ display: 'none' }}
              />
              <div className="dropzone-icon">📄</div>
              {selectedFile ? (
                <div>
                  <strong style={{ color: 'var(--success)' }}>Selected: {selectedFile.name}</strong>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    ({(selectedFile.size / 1024).toFixed(1)} KB) — Click to replace
                  </div>
                </div>
              ) : (
                <div>
                  <strong>Click to upload supporting document</strong>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                    Accepted formats: PDF, PNG, JPG (Max 5MB)
                  </div>
                </div>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem', marginTop: '1.75rem' }}>
            <Link to={`/cases/${caseId}`} className="btn btn-secondary">
              Cancel
            </Link>
            <button type="submit" disabled={submitting} className="btn btn-primary" style={{ padding: '0.75rem 2rem', fontWeight: 600 }}>
              {submitting ? 'Checking your information...' : 'Submit'}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
}

