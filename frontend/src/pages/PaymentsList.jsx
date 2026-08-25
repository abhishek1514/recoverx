import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency } from '../utils/format';

export default function PaymentsList() {
  const [payments, setPayments] = useState([]);
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const navigate = useNavigate();

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [txList, caseList] = await Promise.all([
        api.getTransactions().catch(() => []),
        api.getCases().catch(() => []),
      ]);
      setPayments(txList);
      setCases(caseList);
    } catch (err) {
      setError(err.message || 'Failed to load payments.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Map transaction ID / order ID to case
  const txCaseMap = cases.reduce((acc, c) => {
    if (c.transaction_id) acc[c.transaction_id] = c;
    if (c.transaction?.order_id) acc[c.transaction.order_id] = c;
    if (c.transaction?.id) acc[c.transaction.id] = c;
    return acc;
  }, {});

  const filteredPayments = payments.filter((p) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      (p.order_id || '').toLowerCase().includes(s) ||
      (p.external_id || '').toLowerCase().includes(s) ||
      (p.currency || '').toLowerCase().includes(s) ||
      (p.status || '').toLowerCase().includes(s) ||
      (p.country_code || '').toLowerCase().includes(s) ||
      p.id.toString().includes(s)
    );
  });

  return (
    <div className="payments-page" style={{ maxWidth: '1100px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.75rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff', marginBottom: '0.35rem' }}>
            Payments
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            All ingested payment records, settlement status, and active recovery protections.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button onClick={loadData} className="btn btn-secondary" style={{ padding: '0.55rem 1rem', fontSize: '0.85rem' }}>
            ↻ Refresh
          </button>
          <Link to="/pay" className="btn btn-primary" style={{ padding: '0.55rem 1.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
            🧪 Make Test Payment
          </Link>
        </div>
      </div>

      {/* Search Bar */}
      <div style={{ marginBottom: '1.5rem' }}>
        <input
          type="text"
          placeholder="Search payments by currency, country, or status..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="form-input"
          style={{ maxWidth: '400px' }}
        />
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
          Loading payments...
        </div>
      ) : error ? (
        <div style={{ padding: '1.5rem', background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-md)', color: '#fca5a5', marginBottom: '2rem' }}>
          <strong>Notice:</strong> {error}
        </div>
      ) : filteredPayments.length === 0 ? (
        <div className="table-card" style={{ padding: '3.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>💳</div>
          <h3 style={{ fontSize: '1.2rem', color: '#fff', marginBottom: '0.5rem' }}>No Payments Found</h3>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto 1.5rem' }}>
            Complete a test payment in Razorpay Test Mode to see the automated recovery ingestion.
          </p>
          <Link to="/pay" className="btn btn-primary" style={{ padding: '0.65rem 1.5rem', fontSize: '0.9rem' }}>
            Make a Test Payment
          </Link>
        </div>
      ) : (
        <div className="table-card" style={{ padding: '1.5rem' }}>
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Payment</th>
                  <th>Amount</th>
                  <th>Currency</th>
                  <th>Status</th>
                  <th>Risk</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredPayments.map((p) => {
                  const matchedCase = txCaseMap[p.id] || (p.order_id ? txCaseMap[p.order_id] : null);
                  const isCaptured = p.status === 'captured' || p.status === 'payment_verified';
                  const isHighRisk = matchedCase && (matchedCase.status === 'action_required' || matchedCase.status === 'open');
                  const isRecovered = matchedCase && (matchedCase.status === 'recovered' || matchedCase.status === 'settlement_ready');

                  return (
                    <tr
                      key={p.id}
                      onClick={() => {
                        if (matchedCase) navigate(`/cases/${matchedCase.id}`);
                      }}
                      style={{ cursor: matchedCase ? 'pointer' : 'default' }}
                    >
                      <td>
                        <div style={{ fontWeight: 600, color: '#fff' }}>
                          {p.country_code ? `${p.country_code} Payment` : `Payment #${p.id}`}
                        </div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          {p.created_at ? new Date(p.created_at).toLocaleDateString() : 'Recent'}
                        </div>
                      </td>

                      <td style={{ fontWeight: 700 }}>
                        {formatCurrency(p.amount, p.currency, true)}
                      </td>

                      <td>
                        <span style={{ fontWeight: 600, color: '#93c5fd' }}>
                          {p.currency}
                        </span>
                      </td>

                      <td>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '0.2rem 0.65rem',
                            borderRadius: '9999px',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            background: isCaptured ? 'rgba(16, 185, 129, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                            color: isCaptured ? 'var(--success)' : 'var(--accent-blue)',
                            border: `1px solid ${isCaptured ? 'rgba(16, 185, 129, 0.35)' : 'rgba(59, 130, 246, 0.35)'}`,
                          }}
                        >
                          {p.status ? p.status.replace(/_/g, ' ') : 'Pending'}
                        </span>
                      </td>

                      <td>
                        {matchedCase ? (
                          isRecovered ? (
                            <span style={{ color: 'var(--success)', fontWeight: 600, fontSize: '0.85rem' }}>
                              ✓ Protected
                            </span>
                          ) : isHighRisk ? (
                            <span style={{ color: 'var(--warning)', fontWeight: 600, fontSize: '0.85rem' }}>
                              ⚠️ Needs Attention
                            </span>
                          ) : (
                            <span style={{ color: 'var(--cyan)', fontWeight: 600, fontSize: '0.85rem' }}>
                              In Review
                            </span>
                          )
                        ) : (
                          <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                            Standard
                          </span>
                        )}
                      </td>

                      <td>
                        {matchedCase ? (
                          <Link
                            to={`/cases/${matchedCase.id}`}
                            className="btn btn-secondary"
                            style={{ padding: '0.35rem 0.85rem', fontSize: '0.8rem' }}
                            onClick={(e) => e.stopPropagation()}
                          >
                            View Case →
                          </Link>
                        ) : (
                          <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                            —
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

