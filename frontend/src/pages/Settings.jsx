import React from 'react';

export default function Settings() {
  return (
    <div className="settings-page" style={{ maxWidth: '800px', margin: '0 auto', paddingBottom: '3rem' }}>
      <div style={{ marginBottom: '1.75rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff', marginBottom: '0.35rem' }}>
          Settings & Preferences
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
          Configure RecoverX revenue recovery thresholds, settlement alerts, and Razorpay integration.
        </p>
      </div>

      <div className="table-card" style={{ padding: '2rem', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff', marginBottom: '1.25rem' }}>
          🛡️ Revenue Protection Thresholds
        </h2>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1.25rem' }}>
          <div className="form-group">
            <label className="form-label">High-Value Settlement Threshold (INR)</label>
            <input
              type="text"
              readOnly
              value="₹1,00,000"
              className="form-input"
              style={{ background: '#0a0f18', color: 'var(--cyan)' }}
            />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.3rem' }}>
              Transactions exceeding this amount trigger automatic KYC & invoice verification checks.
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Cross-Border Documentation Guard</label>
            <input
              type="text"
              readOnly
              value="Active (Automated)"
              className="form-input"
              style={{ background: '#0a0f18', color: 'var(--success)' }}
            />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.3rem' }}>
              Monitors currency & origin country discrepancies for settlement friction.
            </div>
          </div>
        </div>
      </div>

      <div className="table-card" style={{ padding: '2rem', marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff', marginBottom: '1.25rem' }}>
          ⚡ Razorpay Integration Status
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <div>
              <div style={{ fontWeight: 600, color: '#fff', fontSize: '0.9rem' }}>Razorpay Test Mode</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Standard Checkout modal & Orders API</div>
            </div>
            <span style={{ padding: '0.2rem 0.65rem', borderRadius: '9999px', fontSize: '0.75rem', fontWeight: 600, background: 'rgba(16, 185, 129, 0.15)', color: 'var(--success)', border: '1px solid rgba(16, 185, 129, 0.35)' }}>
              Connected
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <div>
              <div style={{ fontWeight: 600, color: '#fff', fontSize: '0.9rem' }}>Server-to-Server Webhook Ingestion</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>HMAC-SHA256 signature verification & idempotency</div>
            </div>
            <span style={{ padding: '0.2rem 0.65rem', borderRadius: '9999px', fontSize: '0.75rem', fontWeight: 600, background: 'rgba(16, 185, 129, 0.15)', color: 'var(--success)', border: '1px solid rgba(16, 185, 129, 0.35)' }}>
              Authoritative
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 0' }}>
            <div>
              <div style={{ fontWeight: 600, color: '#fff', fontSize: '0.9rem' }}>AI Explanation Layer</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Non-authoritative explanations with PII guardrails</div>
            </div>
            <span style={{ padding: '0.2rem 0.65rem', borderRadius: '9999px', fontSize: '0.75rem', fontWeight: 600, background: 'rgba(139, 92, 246, 0.15)', color: 'var(--purple)', border: '1px solid rgba(139, 92, 246, 0.35)' }}>
              Assisted
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

