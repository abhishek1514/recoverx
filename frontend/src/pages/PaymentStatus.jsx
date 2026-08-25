import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency } from '../utils/format';
import { getActionLabel, getStatusInfo } from '../utils/status';

export default function PaymentStatus() {
  const { orderId } = useParams();
  const navigate = useNavigate();

  const [orderStatus, setOrderStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pollCount, setPollCount] = useState(0);

  const fetchStatus = async () => {
    try {
      setError(null);
      const data = await api.getRazorpayOrderStatus(orderId);
      setOrderStatus(data);
      return data;
    } catch (err) {
      setError(err.message || 'Failed to fetch payment status.');
      return null;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();

    // Poll every 1.5s until recovery case analysis is produced
    const interval = setInterval(async () => {
      setPollCount((prev) => prev + 1);
      const current = await fetchStatus();
      if (current && current.case_id) {
        clearInterval(interval);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [orderId]);

  if (loading && !orderStatus) {
    return (
      <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>⏳</div>
        <div>Loading payment status for {orderId}...</div>
      </div>
    );
  }

  const hasCase = Boolean(orderStatus?.case_id);
  const statusInfo = getStatusInfo(orderStatus?.status);
  const timeline = orderStatus?.timeline || [];

  return (
    <div className="payment-status-page" style={{ maxWidth: '840px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
          <Link to="/" style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            ← Back to Dashboard
          </Link>
          <span style={{ color: 'var(--border-light)' }}>/</span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Order {orderId}</span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff' }}>
              Payment Recovery Status
            </h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', marginTop: '0.2rem' }}>
              Real-time webhook ingestion and automated settlement risk evaluation.
            </p>
          </div>

          <span
            style={{
              padding: '0.35rem 0.95rem',
              borderRadius: '9999px',
              fontSize: '0.85rem',
              fontWeight: 600,
              background: `${statusInfo.color}15`,
              color: statusInfo.color,
              border: `1px solid ${statusInfo.color}35`,
            }}
          >
            {hasCase ? '✓ Recovery Analysis Complete' : 'Waiting for Razorpay Webhook...'}
          </span>
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

      {/* Dynamic Exposure Card */}
      {hasCase && (
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.12) 0%, rgba(15, 23, 42, 0.6) 100%)',
            border: '1px solid rgba(239, 68, 68, 0.35)',
            borderRadius: 'var(--radius-lg)',
            padding: '1.75rem',
            marginBottom: '2rem',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', marginBottom: '1rem' }}>
            <div>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
                Automated Settlement Evaluation
              </span>
              <h2 style={{ fontSize: '1.85rem', fontWeight: 800, color: 'var(--warning)', margin: '0.25rem 0 0 0' }}>
                {formatCurrency(orderStatus.revenue_at_risk, orderStatus.currency)} potentially at risk
              </h2>
            </div>

            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Payment Amount</div>
              <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>
                {formatCurrency(orderStatus.amount, orderStatus.currency, true)}
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginTop: '1.25rem', paddingTop: '1.25rem', borderTop: '1px solid rgba(255, 255, 255, 0.1)' }}>
            <div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Recovery Likelihood</div>
              <div style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--success)' }}>
                {((Number(orderStatus.recovery_probability) || 0) * 100).toFixed(0)}% Likelihood
              </div>
            </div>

            <div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Recommended Next Action</div>
              <div style={{ fontSize: '1.05rem', fontWeight: 600, color: '#fff' }}>
                {getActionLabel(orderStatus.next_best_action)}
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <Link to={`/cases/${orderStatus.case_id}`} className="btn btn-secondary" style={{ fontSize: '0.85rem' }}>
                View Analysis Details
              </Link>
              <Link to={`/cases/${orderStatus.case_id}/customer`} className="btn btn-primary" style={{ fontSize: '0.85rem', fontWeight: 600 }}>
                Start Recovery →
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Live Automation Timeline */}
      <div className="table-card" style={{ padding: '2rem' }}>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#fff', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>Automation Event Timeline</span>
          {!hasCase && (
            <span style={{ fontSize: '0.8rem', color: 'var(--accent-blue)', fontWeight: 400 }}>
              Live polling... ({pollCount}s)
            </span>
          )}
        </h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {timeline.map((step, idx) => {
            const isDone = step.status === 'completed';
            const isCurrent = step.status === 'in_progress';

            return (
              <div key={step.key || idx} style={{ display: 'flex', gap: '1.25rem', alignItems: 'flex-start' }}>
                {/* Status Dot */}
                <div
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.85rem',
                    fontWeight: 700,
                    flexShrink: 0,
                    background: isDone
                      ? 'rgba(16, 185, 129, 0.15)'
                      : isCurrent
                      ? 'rgba(59, 130, 246, 0.15)'
                      : 'rgba(255, 255, 255, 0.05)',
                    color: isDone ? 'var(--success)' : isCurrent ? 'var(--accent-blue)' : 'var(--text-muted)',
                    border: `1px solid ${
                      isDone
                        ? 'rgba(16, 185, 129, 0.35)'
                        : isCurrent
                        ? 'rgba(59, 130, 246, 0.35)'
                        : 'var(--border-color)'
                    }`,
                  }}
                >
                  {isDone ? '✓' : isCurrent ? '⏳' : idx + 1}
                </div>

                {/* Content */}
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ fontWeight: 600, color: isDone ? '#fff' : isCurrent ? '#93c5fd' : 'var(--text-muted)', fontSize: '0.95rem' }}>
                      {step.title}
                    </div>
                    {step.timestamp && (
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {new Date(step.timestamp).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                    {step.description}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

