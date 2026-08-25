import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency, formatINR } from '../utils/format';
import { getStatusInfo } from '../utils/status';

export default function MerchantReview() {
  const { caseId } = useParams();
  const navigate = useNavigate();

  const [caseData, setCaseData] = useState(null);
  const [resolutionDetails, setResolutionDetails] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [notes, setNotes] = useState('');
  const [decisionSuccess, setDecisionSuccess] = useState(null);

  const loadCase = async () => {
    try {
      setLoading(true);
      setError(null);
      const [data, resData, audit] = await Promise.all([
        api.getCase(caseId),
        api.getCaseResolution(caseId).catch(() => null),
        api.getCaseAudit(caseId).catch(() => []),
      ]);
      setCaseData(data);
      setResolutionDetails(resData);
      setAuditLogs(audit);
    } catch (err) {
      setError(err.message || 'Failed to load payment review portal.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCase();
  }, [caseId]);

  const handleDecision = async (decision) => {
    try {
      setSubmitting(true);
      setError(null);
      const res = await api.reviewCase(caseId, {
        decision: decision,
        notes: notes || `Merchant decision: ${decision}`,
      });
      setDecisionSuccess(res);
      await loadCase();
    } catch (err) {
      setError(err.message || 'Failed to record decision.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
        Loading payment review...
      </div>
    );
  }

  const tx = caseData?.transaction || {};
  const isRecovered = caseData?.case_status === 'recovered';
  const val = resolutionDetails?.latest_validation;
  const statusInfo = getStatusInfo(caseData?.case_status);

  return (
    <div className="merchant-review-page" style={{ maxWidth: '920px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Header Bar */}
      <div style={{ marginBottom: '1.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
          <Link to={`/cases/${caseId}`} style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            ← Back to Payment #{caseId}
          </Link>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <h1 style={{ fontSize: '1.65rem', fontWeight: 700, color: '#fff' }}>
            Review Payment
          </h1>
          <span
            style={{
              display: 'inline-block',
              padding: '0.3rem 0.85rem',
              borderRadius: '9999px',
              fontSize: '0.8rem',
              fontWeight: 600,
              background: `${statusInfo.color}15`,
              color: statusInfo.color,
              border: `1px solid ${statusInfo.color}35`,
            }}
          >
            {statusInfo.label}
          </span>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', marginTop: '0.25rem' }}>
          Review customer submission and decide whether to approve for settlement review or request further clarification.
        </p>
      </div>

      {decisionSuccess && (
        <div style={{ background: 'rgba(16, 185, 129, 0.12)', border: '1px solid rgba(16, 185, 129, 0.35)', borderRadius: 'var(--radius-md)', padding: '1.25rem 1.5rem', marginBottom: '1.75rem' }}>
          <h3 style={{ color: 'var(--success)', fontSize: '1.05rem', fontWeight: 700, marginBottom: '0.35rem' }}>
            ✓ Decision Recorded: {decisionSuccess.decision === 'APPROVE' ? 'Approved for Settlement Review' : decisionSuccess.decision}
          </h3>
          <p style={{ color: '#e2e8f0', fontSize: '0.875rem' }}>
            {decisionSuccess.decision === 'APPROVE'
              ? 'This payment has been verified and marked ready for settlement review. At-risk revenue has been protected.'
              : `Decision updated: ${decisionSuccess.case_status}.`}
          </p>
        </div>
      )}

      {error && (
        <div style={{ padding: '1rem', background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-md)', color: '#fca5a5', marginBottom: '1.5rem' }}>
          <strong>Notice:</strong> {error}
        </div>
      )}

      {/* Overview Grid */}
      <div className="detail-grid" style={{ marginBottom: '1.5rem' }}>
        <div className="detail-card">
          <h3>📊 Payment Overview</h3>
          <div className="detail-row">
            <span className="label">Payment Amount:</span>
            <span className="val" style={{ fontWeight: 700, color: '#fff' }}>
              {formatCurrency(tx.amount, tx.currency, true)}
            </span>
          </div>
          <div className="detail-row">
            <span className="label">Revenue At Risk:</span>
            <span className="val" style={{ color: 'var(--warning)', fontWeight: 700 }}>
              {formatCurrency(caseData?.revenue_at_risk, tx.currency)}
            </span>
          </div>
          <div className="detail-row">
            <span className="label">Origin Country:</span>
            <span className="val">{tx.country_code || 'IN'}</span>
          </div>
          <div className="detail-row">
            <span className="label">Current Status:</span>
            <span className="val" style={{ color: statusInfo.color, fontWeight: 600 }}>
              {statusInfo.label}
            </span>
          </div>
        </div>

        <div className="detail-card">
          <h3>👤 Customer & Documentation</h3>
          <div className="detail-row">
            <span className="label">Customer Submission:</span>
            <span className="val" style={{ color: resolutionDetails?.customer_submission ? 'var(--success)' : 'var(--warning)' }}>
              {resolutionDetails?.customer_submission ? 'Information Received' : 'Awaiting Details'}
            </span>
          </div>
          <div className="detail-row">
            <span className="label">Documents Uploaded:</span>
            <span className="val">{resolutionDetails?.documents?.length || 0} document(s)</span>
          </div>
          <div className="detail-row">
            <span className="label">Verification Check:</span>
            <span className="val" style={{ color: val?.status === 'PASS' ? 'var(--success)' : 'var(--warning)', fontWeight: 700 }}>
              {val?.status === 'PASS' ? '✓ Passed (Matching)' : val?.status || 'Pending'}
            </span>
          </div>
          <div className="detail-row">
            <span className="label">High-Value Tier:</span>
            <span className="val">{caseData?.is_high_value ? 'High-Value Payment' : 'Standard'}</span>
          </div>
        </div>
      </div>

      {/* Customer Submission Breakdown */}
      {resolutionDetails?.customer_submission && (
        <div className="table-card" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#fff', marginBottom: '1rem' }}>
            📋 Customer Submitted Details
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', fontSize: '0.85rem' }}>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Customer Name:</span>
              <div style={{ fontWeight: 600, color: '#fff' }}>{resolutionDetails.customer_submission.customer_name || 'N/A'}</div>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Customer Email:</span>
              <div style={{ fontWeight: 600, color: '#fff' }}>{resolutionDetails.customer_submission.customer_email || 'N/A'}</div>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Submitted Invoice Amount:</span>
              <div style={{ fontWeight: 600, color: '#fff' }}>
                {resolutionDetails.customer_submission.invoice_amount} {resolutionDetails.customer_submission.invoice_currency}
              </div>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Invoice Reference:</span>
              <div style={{ fontWeight: 600, color: '#fff' }}>{resolutionDetails.customer_submission.invoice_reference || 'N/A'}</div>
            </div>
          </div>
        </div>
      )}

      {/* Validation Result Detail */}
      {val && (
        <div className="table-card" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#fff', marginBottom: '0.5rem' }}>
            Validation Summary ({val.status})
          </h3>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
            {val.overall_reason}
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
            {(val.checks || []).map((chk, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.6rem',
                  fontSize: '0.85rem',
                  background: '#0d131f',
                  padding: '0.45rem 0.75rem',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-color)',
                }}
              >
                <span style={{ color: chk.status === 'PASS' ? 'var(--success)' : 'var(--danger)', fontWeight: 700 }}>
                  {chk.status === 'PASS' ? '✓' : '✕'}
                </span>
                <span style={{ color: '#e2e8f0' }}>{chk.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Merchant Decision Controls */}
      <div className="table-card" style={{ padding: '2rem', marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 600, color: '#fff', marginBottom: '1rem' }}>
          Merchant Decision
        </h2>

        <div className="form-group">
          <label className="form-label">Review Notes / Internal Comments</label>
          <textarea
            placeholder="e.g. Commercial invoice verified against purchase order. Customer confirmed."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="form-textarea"
          />
        </div>

        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '1.5rem' }}>
          <button
            onClick={() => handleDecision('APPROVE')}
            disabled={submitting}
            className="btn btn-success"
            style={{ padding: '0.75rem 1.75rem', fontSize: '0.9rem', fontWeight: 600 }}
          >
            ✓ Approve
          </button>

          <button
            onClick={() => handleDecision('REQUEST_MORE_INFORMATION')}
            disabled={submitting}
            className="btn btn-secondary"
            style={{ padding: '0.75rem 1.5rem', fontSize: '0.9rem' }}
          >
            Request More Information
          </button>

          <button
            onClick={() => handleDecision('REJECT')}
            disabled={submitting}
            className="btn btn-danger"
            style={{ padding: '0.75rem 1.5rem', fontSize: '0.9rem' }}
          >
            Reject
          </button>
        </div>

        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '1rem' }}>
          🔒 <strong>Human-in-the-loop:</strong> Financial recovery decisions require explicit merchant approval and are never auto-approved by AI.
        </p>
      </div>
    </div>
  );
}


