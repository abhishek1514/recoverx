import React, { useState, useEffect } from 'react';
import { api } from '../services/api';

export default function Settlements() {
  const [activeTab, setActiveTab] = useState('exceptions'); // 'exceptions' | 'all' | 'reconciliation'
  const [exceptions, setExceptions] = useState([]);
  const [settlements, setSettlements] = useState([]);
  const [reconciliation, setReconciliation] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncingId, setSyncingId] = useState(null);
  const [syncingAll, setSyncingAll] = useState(false);
  const [actionSuccess, setActionSuccess] = useState('');
  const [actionError, setActionError] = useState('');

  const loadData = async () => {
    try {
      setLoading(true);
      const [excData, setlData, reconData, metData] = await Promise.all([
        api.getSettlementExceptions().catch(() => []),
        api.getSettlements().catch(() => []),
        api.getReconciliationRecords().catch(() => []),
        api.getSettlementMetrics().catch(() => null),
      ]);
      setExceptions(excData);
      setSettlements(setlData);
      setReconciliation(reconData);
      setMetrics(metData);
    } catch (err) {
      console.error('Failed loading settlements data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSyncSingle = async (settlementId) => {
    try {
      setSyncingId(settlementId);
      setActionSuccess('');
      setActionError('');
      const updated = await api.syncSettlement(settlementId);
      setActionSuccess(`Settlement ${updated.razorpay_settlement_id} re-synchronized. Current status: ${updated.status.toUpperCase()}`);
      await loadData();
    } catch (err) {
      setActionError(err.message || 'Failed synchronizing settlement status.');
    } finally {
      setSyncingId(null);
    }
  };

  const handleSyncAll = async () => {
    try {
      setSyncingAll(true);
      setActionSuccess('');
      setActionError('');
      const res = await api.syncAllSettlements();
      setActionSuccess(`Synchronized ${res.total_synced} settlements from Razorpay. Exceptions detected: ${res.exceptions_detected}`);
      await loadData();
    } catch (err) {
      setActionError(err.message || 'Failed executing settlement synchronization.');
    } finally {
      setSyncingAll(false);
    }
  };

  return (
    <div className="page-container">
      {/* Header */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="page-title">Settlement Exceptions & Reconciliation</h1>
          <p className="page-subtitle">
            Autonomous detection, financial quantification, and verified recovery of held or failed payouts.
          </p>
        </div>
        <div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSyncAll}
            disabled={syncingAll}
          >
            {syncingAll ? '🔄 Synchronizing...' : '🔄 Sync from Razorpay'}
          </button>
        </div>
      </div>

      {/* Metric Cards */}
      {metrics && (
        <div className="metrics-grid" style={{ marginBottom: '1.5rem' }}>
          <div className="metric-card">
            <span className="metric-label">Failed Settlements</span>
            <span className="metric-value text-danger">₹{Number(metrics.amount_failed).toLocaleString()}</span>
            <span className="metric-subtext">{metrics.failed_settlement_count} failed payout(s)</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">On Hold / Under Review</span>
            <span className="metric-value text-warning">₹{Number(metrics.amount_on_hold).toLocaleString()}</span>
            <span className="metric-subtext">{metrics.on_hold_settlement_count} held payout(s)</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">Unreconciled Variance</span>
            <span className="metric-value text-primary">₹{Number(metrics.unexplained_reconciliation_variance).toLocaleString()}</span>
            <span className="metric-subtext">{metrics.unexplained_reconciliation_count} unexplained variance(s)</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">Successfully Settled</span>
            <span className="metric-value text-success">₹{Number(metrics.total_settled_amount).toLocaleString()}</span>
            <span className="metric-subtext">{metrics.processed_settlement_count} processed</span>
          </div>
        </div>
      )}

      {/* Notifications */}
      {actionSuccess && <div className="alert alert-success" style={{ marginBottom: '1rem' }}>✓ {actionSuccess}</div>}
      {actionError && <div className="alert alert-danger" style={{ marginBottom: '1rem' }}>⚠️ {actionError}</div>}

      {/* Tab Navigation */}
      <div style={{ display: 'flex', gap: '1rem', borderBottom: '1px solid var(--border-color)', marginBottom: '1.5rem' }}>
        <button
          type="button"
          className={`btn ${activeTab === 'exceptions' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('exceptions')}
        >
          ⚠️ Settlement Exceptions ({exceptions.length})
        </button>
        <button
          type="button"
          className={`btn ${activeTab === 'reconciliation' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('reconciliation')}
        >
          📊 Reconciliation Discrepancies ({reconciliation.length})
        </button>
        <button
          type="button"
          className={`btn ${activeTab === 'all' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('all')}
        >
          📁 All Settlements ({settlements.length})
        </button>
      </div>

      {/* Tab 1: Settlement Exceptions */}
      {activeTab === 'exceptions' && (
        <div>
          {loading ? (
            <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
              Loading settlement exceptions...
            </div>
          ) : exceptions.length === 0 ? (
            <div className="card" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-primary)' }}>✓ All Settlements Healthy</h3>
              <p style={{ margin: 0 }}>No failed or held settlements detected from Razorpay.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {exceptions.map((exc) => (
                <div key={exc.id} className="card" style={{ padding: '1.5rem', borderLeft: '4px solid #ef4444' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                    <div>
                      <span className="badge badge-danger" style={{ marginBottom: '0.5rem' }}>
                        {exc.status.toUpperCase()}
                      </span>
                      <h2 style={{ margin: '0.25rem 0', fontSize: '1.4rem' }}>
                        ₹{Number(exc.amount).toLocaleString()} {exc.currency} Payout Affected
                      </h2>
                      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                        Razorpay Settlement ID: <code>{exc.razorpay_settlement_id}</code>
                      </div>
                    </div>
                    <div>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleSyncSingle(exc.id)}
                        disabled={syncingId === exc.id}
                      >
                        {syncingId === exc.id ? 'Checking...' : '🔄 Check Again'}
                      </button>
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', background: 'var(--bg-secondary, #f8fafc)', padding: '1rem', borderRadius: '8px' }}>
                    <div>
                      <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)' }}>ACTUAL REASON</div>
                      <div style={{ fontSize: '0.95rem', fontWeight: 500, color: '#dc2626', marginTop: '0.25rem' }}>
                        {exc.failure_reason || 'Reason not provided by Razorpay'}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)' }}>RECOMMENDED NEXT ACTION</div>
                      <div style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--primary-color)', marginTop: '0.25rem' }}>
                        👉 {exc.recommended_action.replace(/_/g, ' ')}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Reconciliation Discrepancies */}
      {activeTab === 'reconciliation' && (
        <div className="card">
          <div className="card-header" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
            <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Transaction Reconciliation Records</h3>
          </div>
          {loading ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading reconciliation records...</div>
          ) : reconciliation.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>No reconciliation records on file.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)', textAlign: 'left' }}>
                    <th style={{ padding: '0.75rem' }}>Type</th>
                    <th style={{ padding: '0.75rem' }}>Expected</th>
                    <th style={{ padding: '0.75rem' }}>Settled</th>
                    <th style={{ padding: '0.75rem' }}>Fees & Tax</th>
                    <th style={{ padding: '0.75rem' }}>Refunds/Adj</th>
                    <th style={{ padding: '0.75rem' }}>Unexplained Variance</th>
                    <th style={{ padding: '0.75rem' }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {reconciliation.map((rec) => (
                    <tr key={rec.id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '0.75rem', fontWeight: 500 }}>{rec.discrepancy_type}</td>
                      <td style={{ padding: '0.75rem' }}>₹{Number(rec.expected_amount).toLocaleString()}</td>
                      <td style={{ padding: '0.75rem' }}>₹{Number(rec.settled_amount).toLocaleString()}</td>
                      <td style={{ padding: '0.75rem' }}>₹{(Number(rec.fee_amount) + Number(rec.tax_amount)).toLocaleString()}</td>
                      <td style={{ padding: '0.75rem' }}>₹{(Number(rec.refund_amount) + Number(rec.adjustment_amount)).toLocaleString()}</td>
                      <td style={{ padding: '0.75rem', fontWeight: 600, color: rec.status === 'unexplained' ? '#dc2626' : '#10b981' }}>
                        ₹{Number(rec.discrepancy_amount).toLocaleString()}
                      </td>
                      <td style={{ padding: '0.75rem' }}>
                        <span className={`badge badge-${rec.status === 'explained' ? 'success' : 'danger'}`}>
                          {rec.status.toUpperCase()}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tab 3: All Settlements */}
      {activeTab === 'all' && (
        <div className="card">
          <div className="card-header" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
            <h3 style={{ margin: 0, fontSize: '1.1rem' }}>All Settlements</h3>
          </div>
          {loading ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading settlements...</div>
          ) : settlements.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>No settlements synchronized yet.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)', textAlign: 'left' }}>
                    <th style={{ padding: '0.75rem' }}>Settlement ID</th>
                    <th style={{ padding: '0.75rem' }}>Amount</th>
                    <th style={{ padding: '0.75rem' }}>UTR</th>
                    <th style={{ padding: '0.75rem' }}>Fees & Tax</th>
                    <th style={{ padding: '0.75rem' }}>Status</th>
                    <th style={{ padding: '0.75rem' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {settlements.map((s) => (
                    <tr key={s.id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '0.75rem' }}><code>{s.razorpay_settlement_id}</code></td>
                      <td style={{ padding: '0.75rem', fontWeight: 600 }}>₹{Number(s.amount).toLocaleString()} {s.currency}</td>
                      <td style={{ padding: '0.75rem', color: 'var(--text-secondary)' }}>{s.utr || '—'}</td>
                      <td style={{ padding: '0.75rem' }}>₹{(Number(s.fees) + Number(s.tax)).toLocaleString()}</td>
                      <td style={{ padding: '0.75rem' }}>
                        <span className={`badge badge-${s.status === 'processed' ? 'success' : s.status === 'failed' ? 'danger' : 'warning'}`}>
                          {s.status.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ padding: '0.75rem' }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleSyncSingle(s.id)}
                          disabled={syncingId === s.id}
                        >
                          {syncingId === s.id ? 'Checking...' : 'Check'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

