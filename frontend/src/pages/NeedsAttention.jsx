import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency, formatINR } from '../utils/format';
import { getStatusInfo, getActionLabel, translateFrictionReason, translateActionRecommendation } from '../utils/status';

export default function NeedsAttention() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('ALL');
  const navigate = useNavigate();

  const loadCases = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getCases();
      // Filter to active cases needing attention
      setCases(data);
    } catch (err) {
      setError(err.message || 'Failed to load payments needing attention.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCases();
  }, []);

  const activeCases = cases.filter((c) => {
    if (filter === 'ACTION_REQUIRED') {
      return c.status === 'action_required' || c.status === 'open' || c.status === 'customer_responded';
    }
    if (filter === 'MERCHANT_REVIEW') {
      return c.status === 'merchant_review' || c.status === 'validation_failed';
    }
    if (filter === 'RECOVERED') {
      return c.status === 'recovered' || c.status === 'settlement_ready';
    }
    return true; // ALL
  });

  return (
    <div className="needs-attention-page" style={{ maxWidth: '1100px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.75rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff', marginBottom: '0.35rem' }}>
            Payments Needing Attention
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Active payment settlement risks requiring customer documentation or merchant review.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button onClick={loadCases} className="btn btn-secondary" style={{ padding: '0.55rem 1rem', fontSize: '0.85rem' }}>
            ↻ Refresh
          </button>
          <Link to="/pay" className="btn btn-primary" style={{ padding: '0.55rem 1.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
            🧪 Make Test Payment
          </Link>
        </div>
      </div>

      {/* Filter Tabs */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
        {[
          { id: 'ALL', label: `All Attention Cases (${cases.length})` },
          { id: 'ACTION_REQUIRED', label: 'Action Needed' },
          { id: 'MERCHANT_REVIEW', label: 'Needs Merchant Review' },
          { id: 'RECOVERED', label: 'Recovered / Ready' },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setFilter(tab.id)}
            style={{
              padding: '0.45rem 1rem',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.85rem',
              fontWeight: 600,
              background: filter === tab.id ? 'var(--accent-blue)' : 'rgba(255, 255, 255, 0.05)',
              color: filter === tab.id ? '#fff' : 'var(--text-secondary)',
              border: '1px solid var(--border-color)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
          Loading payments needing attention...
        </div>
      ) : error ? (
        <div style={{ padding: '1.5rem', background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-md)', color: '#fca5a5', marginBottom: '2rem' }}>
          <strong>Notice:</strong> {error}
        </div>
      ) : activeCases.length === 0 ? (
        <div className="table-card" style={{ padding: '3.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>🎉</div>
          <h3 style={{ fontSize: '1.2rem', color: '#fff', marginBottom: '0.5rem' }}>No Payments Currently Need Attention</h3>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto 1.5rem' }}>
            All payments are either cleared for settlement or successfully recovered. You can make a test payment to test the recovery flow.
          </p>
          <Link to="/pay" className="btn btn-primary" style={{ padding: '0.65rem 1.5rem', fontSize: '0.9rem' }}>
            Make a Test Payment
          </Link>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {activeCases.map((c) => {
            const statusInfo = getStatusInfo(c.status);
            const likelihood = Math.round(Number(c.recovery_probability || 0.8) * 100);
            const tx = c.transaction || {};
            const paymentAmount = tx.amount || c.amount_at_risk;
            const currency = tx.currency || 'INR';
            const isReview = c.status === 'merchant_review' || c.status === 'validation_failed';
            const isRecovered = c.status === 'recovered' || c.status === 'settlement_ready';

            // Friction reason & recommendation
            const reason = (c.risk_reasons && c.risk_reasons.length > 0)
              ? translateFrictionReason(c.risk_reasons[0])
              : 'Cross-border settlement documentation or KYC confirmation required.';
            const recommendation = translateActionRecommendation(c.next_best_action, c.missing_information);

            return (
              <div
                key={c.id}
                className="table-card"
                style={{
                  padding: '1.75rem 2rem',
                  borderLeft: `4px solid ${statusInfo.color}`,
                  background: isRecovered
                    ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.06) 0%, #161f30 100%)'
                    : 'linear-gradient(135deg, rgba(245, 158, 11, 0.06) 0%, #161f30 100%)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
                      <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>
                        {tx.country_code ? `${tx.country_code} International Payment` : `Payment #${c.id}`}
                      </h2>
                      <span
                        style={{
                          display: 'inline-block',
                          padding: '0.2rem 0.65rem',
                          borderRadius: '9999px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          background: `${statusInfo.color}15`,
                          color: statusInfo.color,
                          border: `1px solid ${statusInfo.color}35`,
                        }}
                      >
                        {statusInfo.label}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                      Total Payment Value: <strong style={{ color: '#fff' }}>{formatCurrency(paymentAmount, currency, true)}</strong> · Origin: <strong style={{ color: '#fff' }}>{tx.country_code || 'International'}</strong>
                    </div>
                  </div>

                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Revenue At Risk</div>
                    <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--warning)' }}>
                      {formatCurrency(c.amount_at_risk, currency, true)}
                    </div>
                  </div>
                </div>

                {/* 5 Clear Questions Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem', background: 'rgba(0,0,0,0.25)', padding: '1.25rem', borderRadius: 'var(--radius-md)', marginBottom: '1.25rem' }}>
                  <div>
                    <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
                      ⚠️ Why it needs attention
                    </div>
                    <p style={{ fontSize: '0.875rem', color: '#f1f5f9', lineHeight: 1.5 }}>
                      {reason}
                    </p>
                  </div>

                  <div>
                    <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--cyan)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
                      🎯 What RecoverX recommends
                    </div>
                    <p style={{ fontSize: '0.875rem', color: '#f1f5f9', lineHeight: 1.5 }}>
                      {recommendation}
                    </p>
                  </div>

                  <div>
                    <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--success)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
                      📈 Recovery Likelihood
                    </div>
                    <div style={{ fontSize: '1.25rem', fontWeight: 800, color: likelihood >= 70 ? 'var(--success)' : '#fbbf24' }}>
                      {likelihood}%
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Estimated resolution success
                    </div>
                  </div>
                </div>

                {/* Action CTA Bar */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', alignItems: 'center' }}>
                  <Link
                    to={`/cases/${c.id}`}
                    className="btn btn-secondary"
                    style={{ padding: '0.55rem 1.1rem', fontSize: '0.85rem' }}
                  >
                    View Details
                  </Link>

                  {isReview ? (
                    <Link
                      to={`/cases/${c.id}/review`}
                      className="btn btn-primary"
                      style={{ padding: '0.55rem 1.4rem', fontSize: '0.85rem', fontWeight: 600, background: 'var(--amber)' }}
                    >
                      Review Decision →
                    </Link>
                  ) : !isRecovered ? (
                    <Link
                      to={`/cases/${c.id}/customer`}
                      className="btn btn-primary"
                      style={{ padding: '0.55rem 1.4rem', fontSize: '0.85rem', fontWeight: 600 }}
                    >
                      Start Recovery →
                    </Link>
                  ) : (
                    <span style={{ fontSize: '0.85rem', color: 'var(--success)', fontWeight: 600 }}>
                      ✓ Revenue Cleared
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

