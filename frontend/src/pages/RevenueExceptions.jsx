import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';

export default function RevenueExceptions() {
  const [exceptions, setExceptions] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [priorityFilter, setPriorityFilter] = useState('ALL');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [selectedException, setSelectedException] = useState(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [syncingId, setSyncingId] = useState(null);

  const loadData = async () => {
    try {
      setLoading(true);
      const [excList, metData] = await Promise.all([
        api.getRevenueExceptions(),
        api.getRevenueExceptionMetrics().catch(() => null),
      ]);
      setExceptions(excList);
      setMetrics(metData);
    } catch (err) {
      console.error('Failed loading revenue exceptions:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const openDetail = async (id) => {
    try {
      const detail = await api.getRevenueExceptionDetail(id);
      setSelectedException(detail);
      setDetailModalOpen(true);
    } catch (err) {
      console.error('Error fetching exception detail:', err);
    }
  };

  const handleResync = async (txId) => {
    try {
      setSyncingId(txId);
      await api.resyncWebhookPayment(txId);
      await loadData();
    } catch (err) {
      alert('Resync failed: ' + (err.message || 'Unknown error'));
    } finally {
      setSyncingId(null);
    }
  };

  const filteredExceptions = exceptions.filter((exc) => {
    if (priorityFilter !== 'ALL' && exc.priority !== priorityFilter) return false;
    if (typeFilter === 'DISPUTES' && exc.exception_type !== 'chargeback_dispute') return false;
    if (typeFilter === 'SETTLEMENTS' && !['settlement_failure', 'settlement_hold', 'settlement_risk'].includes(exc.exception_type)) return false;
    if (typeFilter === 'RECONCILIATION' && exc.exception_type !== 'reconciliation_variance') return false;
    if (typeFilter === 'PAYMENT_STATE' && exc.exception_type !== 'webhook_payment_state_exception') return false;
    return true;
  });

  const getPriorityBadgeClass = (priority) => {
    switch (priority) {
      case 'CRITICAL':
        return 'badge-danger';
      case 'HIGH':
        return 'badge-warning';
      case 'MEDIUM':
        return 'badge-primary';
      default:
        return 'badge-secondary';
    }
  };

  const getActionRoute = (exc) => {
    if (exc.exception_type === 'chargeback_dispute') return '/disputes';
    if (['settlement_failure', 'settlement_hold', 'reconciliation_variance'].includes(exc.exception_type)) return '/settlements';
    return `/cases/${exc.id}`;
  };

  return (
    <div className="page-container">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Revenue Exceptions</h1>
          <p className="page-subtitle">
            Autonomous unified detection, priority ranking, and AI-assisted resolution for revenue at risk.
          </p>
        </div>
      </div>

      {/* Top Metrics Grid */}
      {metrics && (
        <div className="metrics-grid" style={{ marginBottom: '1.5rem' }}>
          <div className="metric-card">
            <span className="metric-label">Total Revenue at Risk</span>
            <span className="metric-value text-danger">₹{Number(metrics.total_amount_at_risk).toLocaleString()}</span>
            <span className="metric-subtext">{metrics.action_required_count} exception(s) requiring action</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">Critical Exceptions</span>
            <span className="metric-value text-warning">{metrics.critical_count}</span>
            <span className="metric-subtext">Immediate action / deadline &lt; 24h</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">Protected / Recovered</span>
            <span className="metric-value text-success">₹{Number(metrics.amount_recovered).toLocaleString()}</span>
            <span className="metric-subtext">{metrics.total_exceptions} total cases tracked</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">Recovery Rate</span>
            <span className="metric-value text-primary">{(Number(metrics.recovery_rate) * 100).toFixed(0)}%</span>
            <span className="metric-subtext">Verified financial outcome</span>
          </div>
        </div>
      )}

      {/* Filters Bar */}
      <div className="card" style={{ padding: '1rem', marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        {/* Priority Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)' }}>PRIORITY:</span>
          {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((p) => (
            <button
              key={p}
              type="button"
              className={`btn btn-sm ${priorityFilter === p ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setPriorityFilter(p)}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Type Filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)' }}>CATEGORY:</span>
          {['ALL', 'DISPUTES', 'SETTLEMENTS', 'RECONCILIATION', 'PAYMENT_STATE'].map((t) => (
            <button
              key={t}
              type="button"
              className={`btn btn-sm ${typeFilter === t ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setTypeFilter(t)}
            >
              {t.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* Exceptions List */}
      {loading ? (
        <div className="card" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          Loading revenue exceptions...
        </div>
      ) : filteredExceptions.length === 0 ? (
        <div className="card" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-primary)' }}>✓ No Revenue Exceptions</h3>
          <p style={{ margin: 0 }}>All revenue streams are healthy and reconciled.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {filteredExceptions.map((exc) => (
            <div
              key={exc.id}
              className="card"
              style={{
                padding: '1.25rem 1.5rem',
                borderLeft: exc.priority === 'CRITICAL' ? '5px solid #ef4444' : exc.priority === 'HIGH' ? '5px solid #f59e0b' : '5px solid #3b82f6',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <span className={`badge ${getPriorityBadgeClass(exc.priority)}`}>
                    {exc.priority} PRIORITY
                  </span>
                  <span style={{ fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-secondary)', fontWeight: 600 }}>
                    {exc.exception_type.replace(/_/g, ' ')}
                  </span>
                  <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    • ID: <code>{exc.source_id}</code>
                  </span>
                </div>
                <div>
                  <span className={`badge badge-${exc.status === 'resolved' ? 'success' : exc.status === 'lost' ? 'danger' : 'warning'}`}>
                    {exc.status.toUpperCase()}
                  </span>
                </div>
              </div>

              {/* 5 Core Merchant Answers */}
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 3fr 2fr', gap: '1.5rem', alignItems: 'center' }}>
                {/* 1 & 2: What happened & Money Affected */}
                <div>
                  <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                    ₹{Number(exc.amount_at_risk).toLocaleString()} <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>{exc.currency}</span>
                  </div>
                  <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                    {exc.reason}
                  </div>
                </div>

                {/* 3 & 4: Urgency & Action */}
                <div style={{ background: 'var(--bg-secondary, #f8fafc)', padding: '0.75rem 1rem', borderRadius: '8px' }}>
                  <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
                    Recommended Next Action
                  </div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--primary-color)', marginTop: '0.2rem' }}>
                    👉 {exc.recommended_action.replace(/_/g, ' ')}
                  </div>
                  {exc.hours_remaining !== null && (
                    <div style={{ fontSize: '0.8rem', color: exc.hours_remaining < 24 ? '#ef4444' : 'var(--text-secondary)', marginTop: '0.2rem' }}>
                      ⏳ Response window: {exc.hours_remaining} hours remaining
                    </div>
                  )}
                </div>

                {/* 5: CTAs */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', alignItems: 'center' }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => openDetail(exc.id)}
                  >
                    View Details
                  </button>
                  {exc.exception_type === 'webhook_payment_state_exception' ? (
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={syncingId === (exc.source_id || exc.id) || exc.status === 'resolved'}
                      onClick={() => handleResync(exc.source_id || exc.id)}
                    >
                      {syncingId === (exc.source_id || exc.id) ? 'Syncing...' : exc.status === 'resolved' ? '✓ Recovered' : '🔄 Sync State'}
                    </button>
                  ) : (
                    <Link
                      to={getActionRoute(exc)}
                      className="btn btn-primary btn-sm"
                    >
                      Resolve →
                    </Link>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Exception Detail Modal */}
      {detailModalOpen && selectedException && (
        <div className="modal-backdrop" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div className="modal-content card" style={{ width: '640px', maxHeight: '85vh', overflowY: 'auto', padding: '1.5rem', background: 'var(--bg-card, #fff)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
              <div>
                <span className={`badge ${getPriorityBadgeClass(selectedException.priority)}`} style={{ marginBottom: '0.5rem' }}>
                  {selectedException.priority} PRIORITY
                </span>
                <h2 style={{ margin: '0.25rem 0', fontSize: '1.4rem' }}>
                  ₹{Number(selectedException.amount_at_risk).toLocaleString()} {selectedException.currency} at Risk
                </h2>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  Type: {selectedException.exception_type.replace(/_/g, ' ')} • Source: <code>{selectedException.source_id}</code>
                </div>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setDetailModalOpen(false)}
              >
                ✕ Close
              </button>
            </div>

            <div style={{ background: 'var(--bg-secondary, #f8fafc)', padding: '1rem', borderRadius: '8px', marginBottom: '1rem' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)' }}>EXPLANATION & ROOT CAUSE</div>
              <p style={{ margin: '0.35rem 0 0 0', fontSize: '0.95rem' }}>{selectedException.reason}</p>
            </div>

            <div style={{ background: 'var(--bg-secondary, #f8fafc)', padding: '1rem', borderRadius: '8px', marginBottom: '1.5rem' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)' }}>AI RECOVERY ADVICE</div>
              <p style={{ margin: '0.35rem 0 0 0', fontSize: '0.9rem', color: 'var(--primary-color)' }}>
                {selectedException.ai_explanation}
              </p>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                * AI output is advisory — deterministic validation and merchant approval govern recovery actions.
              </div>
            </div>

            {/* Audit Timeline */}
            <div style={{ marginBottom: '1.5rem' }}>
              <h4 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem' }}>Chronological Audit Trail</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {selectedException.timeline.map((evt, idx) => (
                  <div key={idx} style={{ padding: '0.5rem', borderLeft: '2px solid var(--primary-color)', fontSize: '0.85rem' }}>
                    <div style={{ fontWeight: 600 }}>{evt.event.replace(/_/g, ' ').toUpperCase()}</div>
                    <div style={{ color: 'var(--text-secondary)' }}>{evt.description}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{new Date(evt.timestamp).toLocaleString()}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setDetailModalOpen(false)}
              >
                Close
              </button>
              <Link
                to={getActionRoute(selectedException)}
                className="btn btn-primary"
              >
                Go to Resolution Workspace →
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

