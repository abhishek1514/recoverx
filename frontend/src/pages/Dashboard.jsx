import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency, formatINR } from '../utils/format';
import { getStatusInfo, getActionLabel } from '../utils/status';

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [recentCases, setRecentCases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const navigate = useNavigate();

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [sumData, casesData] = await Promise.all([
        api.getDashboardSummary(),
        api.getCases(),
      ]);
      setSummary(sumData);
      setRecentCases(casesData.slice(0, 8));
    } catch (err) {
      setError(err.message || 'Failed to load recovery dashboard metrics.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const totalAtRisk = Number(summary?.total_revenue_at_risk || 0);
  const recoveredAtRisk = Number(summary?.recovered_revenue || 0);
  const remainingAtRisk = Math.max(0, totalAtRisk - recoveredAtRisk);
  const recoveredPercent = totalAtRisk > 0 ? Math.min(100, (recoveredAtRisk / totalAtRisk) * 100) : 0;
  const remainingPercent = totalAtRisk > 0 ? 100 - recoveredPercent : 0;

  return (
    <div className="dashboard-page">
      {/* Merchant Header Banner */}
      <div className="product-banner" style={{ padding: '2rem 2.25rem' }}>
        <div className="banner-text">
          <h1 style={{ fontSize: '1.65rem', fontWeight: 700, color: '#fff', marginBottom: '0.5rem' }}>
            Protect revenue before settlement gets delayed.
          </h1>
          <p style={{ fontSize: '0.95rem', color: 'var(--text-secondary)', maxWidth: '680px', lineHeight: 1.5 }}>
            RecoverX identifies payment issues early, guides resolution, and helps recover revenue before settlement friction becomes a larger problem.
          </p>
        </div>
        <div>
          <Link
            to="/pay"
            className="btn btn-primary"
            style={{ padding: '0.75rem 1.5rem', fontSize: '0.9rem', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
          >
            <span>💳</span>
            <span>Make Test Payment</span>
          </Link>
        </div>
      </div>

      {loading && !summary ? (
        <div style={{ textAlign: 'center', padding: '3.5rem', color: 'var(--text-muted)' }}>
          Loading recovery dashboard...
        </div>
      ) : error ? (
        <div style={{ padding: '1.5rem', background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-md)', color: '#fca5a5', marginBottom: '2rem' }}>
          <strong>Error loading metrics:</strong> {error}
          <button onClick={loadData} className="btn btn-secondary" style={{ marginLeft: '1rem', padding: '0.25rem 0.75rem', fontSize: '0.8rem' }}>
            Retry
          </button>
        </div>
      ) : (
        <>
          {/* 4 Primary Merchant KPIs */}
          <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <div className="kpi-card">
              <div className="kpi-label">Revenue At Risk</div>
              <div className="kpi-value highlight-amber">
                {formatINR(summary?.total_revenue_at_risk || 0)}
              </div>
              <div className="kpi-subtext">Potentially delayed settlement exposure</div>
            </div>

            <div className="kpi-card">
              <div className="kpi-label">Cases Needing Action</div>
              <div className="kpi-value highlight-blue">
                {(summary?.at_risk_transactions || summary?.cases_awaiting_customer || 0)}
              </div>
              <div className="kpi-subtext">Requires customer or merchant resolution</div>
            </div>

            <div className="kpi-card">
              <div className="kpi-label">Recovered Revenue</div>
              <div className="kpi-value highlight-green">
                {formatINR(summary?.recovered_revenue || 0)}
              </div>
              <div className="kpi-subtext">Successfully protected and cleared</div>
            </div>

            <div className="kpi-card">
              <div className="kpi-label">Recovery Likelihood</div>
              <div className="kpi-value highlight-green">
                {(Number(summary?.recovery_rate || summary?.average_recovery_probability || 0.82) * 100).toFixed(0)}%
              </div>
              <div className="kpi-subtext">Average resolution probability</div>
            </div>
          </div>

          {/* Revenue Resolution Progress Overview */}
          <div className="revenue-viz-card" style={{ marginTop: '1.5rem', marginBottom: '2rem' }}>
            <div className="revenue-viz-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#fff' }}>Revenue Protection Progress</h2>
              <span style={{ fontSize: '0.85rem', color: 'var(--success)', fontWeight: 600 }}>
                {recoveredPercent.toFixed(0)}% Protected & Cleared
              </span>
            </div>

            <div className="progress-bar-container" style={{ height: '10px', borderRadius: '5px' }}>
              <div
                className="progress-segment-recovered"
                style={{ width: `${recoveredPercent}%` }}
                title={`Recovered: ${formatINR(recoveredAtRisk)}`}
              />
              <div
                className="progress-segment-remaining"
                style={{ width: `${remainingPercent}%` }}
                title={`Remaining At Risk: ${formatINR(remainingAtRisk)}`}
              />
            </div>

            <div className="revenue-stats-row" style={{ marginTop: '1.25rem' }}>
              <div className="rev-stat-item">
                <div className="stat-indicator total" />
                <div>
                  <div className="stat-info-title">Total Revenue Monitored</div>
                  <div className="stat-info-val">{formatINR(totalAtRisk)}</div>
                </div>
              </div>

              <div className="rev-stat-item">
                <div className="stat-indicator recovered" />
                <div>
                  <div className="stat-info-title">Recovered Revenue</div>
                  <div className="stat-info-val" style={{ color: 'var(--success)' }}>
                    {formatINR(recoveredAtRisk)}
                  </div>
                </div>
              </div>

              <div className="rev-stat-item">
                <div className="stat-indicator remaining" />
                <div>
                  <div className="stat-info-title">Revenue At Risk</div>
                  <div className="stat-info-val" style={{ color: remainingAtRisk > 0 ? 'var(--warning)' : 'var(--text-muted)' }}>
                    {formatINR(remainingAtRisk)}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Payments Needing Attention */}
          <div className="table-card" style={{ padding: '1.75rem' }}>
            <div className="table-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
              <div>
                <h2 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff' }}>Payments Needing Attention</h2>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '0.2rem' }}>
                  Track active payment resolutions and required next steps.
                </p>
              </div>
              <Link to="/cases" className="btn btn-secondary" style={{ padding: '0.4rem 0.9rem', fontSize: '0.8rem' }}>
                View All Payments →
              </Link>
            </div>

            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Payment</th>
                    <th>Amount</th>
                    <th>Revenue At Risk</th>
                    <th>Recovery Likelihood</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {recentCases.length === 0 ? (
                    <tr>
                      <td colSpan="5" style={{ textAlign: 'center', padding: '2.5rem', color: 'var(--text-muted)' }}>
                        No payments needing attention.{' '}
                        <Link to="/pay" style={{ color: 'var(--cyan)', fontWeight: 600 }}>
                          Make a Test Payment
                        </Link>{' '}
                        to see RecoverX in action.
                      </td>
                    </tr>
                  ) : (
                    recentCases.map((c) => {
                      const likelihood = Math.round(Number(c.recovery_probability || 0.8) * 100);
                      const paymentAmount = c.transaction?.amount || c.amount_at_risk;
                      const currency = c.transaction?.currency || 'INR';

                      return (
                        <tr key={c.id} onClick={() => navigate(`/cases/${c.id}`)}>
                          <td>
                            <div style={{ fontWeight: 600, color: '#fff' }}>
                              Payment #{c.id}
                            </div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                              {c.transaction?.country_code ? `Origin: ${c.transaction.country_code}` : 'International Payment'}
                            </div>
                          </td>
                          <td style={{ fontWeight: 600 }}>
                            {formatCurrency(paymentAmount, currency, true)}
                          </td>
                          <td style={{ color: 'var(--warning)', fontWeight: 600 }}>
                            {formatCurrency(c.amount_at_risk, currency, true)}
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                              <span style={{ fontWeight: 700, color: likelihood >= 70 ? 'var(--success)' : '#fbbf24' }}>
                                {likelihood}%
                              </span>
                            </div>
                          </td>
                          <td>
                            <span style={{ color: 'var(--cyan)', fontSize: '0.85rem', fontWeight: 600 }}>
                              View →
                            </span>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}


