import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency, formatINR } from '../utils/format';
import { getStatusInfo, getActionLabel } from '../utils/status';

export default function Cases() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const navigate = useNavigate();

  const loadCases = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getCases();
      setCases(data);
    } catch (err) {
      setError(err.message || 'Failed to load payments.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCases();
  }, []);

  const filteredCases = cases.filter((c) => {
    const matchesSearch =
      search === '' ||
      c.id.toString().includes(search) ||
      (c.next_best_action || '').toLowerCase().includes(search.toLowerCase()) ||
      (c.status || '').toLowerCase().includes(search.toLowerCase());

    const matchesStatus =
      statusFilter === 'ALL' ||
      (statusFilter === 'RECOVERED' && c.status === 'recovered') ||
      (statusFilter === 'READY' && (c.status === 'settlement_ready' || c.status === 'ready')) ||
      (statusFilter === 'ACTION_REQUIRED' && (c.status === 'action_required' || c.status === 'open' || c.status === 'customer_responded')) ||
      (statusFilter === 'MERCHANT_REVIEW' && (c.status === 'merchant_review' || c.status === 'validation_failed'));

    return matchesSearch && matchesStatus;
  });

  return (
    <div className="cases-page" style={{ maxWidth: '1100px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.65rem', fontWeight: 700, color: '#fff', marginBottom: '0.35rem' }}>
            Payments Needing Attention
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Monitor at-risk payments and track recovery progress across international transactions.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button onClick={loadCases} className="btn btn-secondary" style={{ padding: '0.55rem 1rem', fontSize: '0.85rem' }}>
            ↻ Refresh
          </button>
          <Link to="/pay" className="btn btn-primary" style={{ padding: '0.55rem 1.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
            💳 Make Test Payment
          </Link>
        </div>
      </div>


      {/* Filters Bar */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
        <input
          type="text"
          placeholder="Search by Payment ID, action, or status..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="form-input"
          style={{ maxWidth: '380px' }}
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="form-select"
          style={{ maxWidth: '240px' }}
        >
          <option value="ALL">All Payments ({cases.length})</option>
          <option value="ACTION_REQUIRED">Action Needed</option>
          <option value="MERCHANT_REVIEW">Needs Your Review</option>
          <option value="READY">Ready for Settlement Review</option>
          <option value="RECOVERED">Recovered At-Risk Revenue</option>
        </select>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '3.5rem', color: 'var(--text-muted)' }}>
          Loading payments...
        </div>
      ) : error ? (
        <div style={{ padding: '1.5rem', background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-md)', color: '#fca5a5' }}>
          <strong>Error loading payments:</strong> {error}
        </div>
      ) : (
        <div className="table-card" style={{ padding: '1.5rem' }}>
          <div className="table-header" style={{ marginBottom: '1.25rem' }}>
            <h2 style={{ fontSize: '1.15rem', color: '#fff' }}>Active Payments Portfolio ({filteredCases.length})</h2>
          </div>

          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Payment</th>
                  <th>Amount</th>
                  <th>Revenue at Risk</th>
                  <th>Recovery Likelihood</th>
                  <th>What to Do</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredCases.length === 0 ? (
                  <tr>
                    <td colSpan="7" style={{ textAlign: 'center', padding: '2.5rem', color: 'var(--text-muted)' }}>
                      No payments match the selected filter.
                    </td>
                  </tr>
                ) : (
                  filteredCases.map((c) => {
                    const statusInfo = getStatusInfo(c.status);
                    const actionLabel = getActionLabel(c.next_best_action);
                    const likelihood = Math.round(Number(c.recovery_probability || 0.8) * 100);

                    return (
                      <tr key={c.id} onClick={() => navigate(`/cases/${c.id}`)}>
                        <td>
                          <div style={{ fontWeight: 600, color: '#fff' }}>
                            Payment #{c.id}
                          </div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            Ref: txn_{c.transaction_id || c.id}
                          </div>
                        </td>
                        <td style={{ fontWeight: 600 }}>
                          {formatCurrency(c.amount_at_risk, 'INR')}
                        </td>
                        <td style={{ color: 'var(--warning)', fontWeight: 600 }}>
                          {formatCurrency(c.amount_at_risk, 'INR')}
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <span style={{ fontWeight: 700, color: likelihood >= 70 ? 'var(--success)' : '#fbbf24' }}>
                              {likelihood}%
                            </span>
                          </div>
                        </td>
                        <td style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                          {actionLabel}
                        </td>
                        <td>
                          <span
                            style={{
                              display: 'inline-block',
                              padding: '0.25rem 0.65rem',
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
                        </td>
                        <td>
                          <Link to={`/cases/${c.id}`} className="btn btn-secondary" style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem' }}>
                            View →
                          </Link>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

