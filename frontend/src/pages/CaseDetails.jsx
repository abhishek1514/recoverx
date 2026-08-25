import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { formatCurrency } from '../utils/format';
import { getStatusInfo, getActionLabel, translateFrictionReason, translateActionRecommendation } from '../utils/status';

export default function CaseDetails() {
  const { caseId } = useParams();
  const navigate = useNavigate();

  const [caseData, setCaseData] = useState(null);
  const [resolutionDetails, setResolutionDetails] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [aiData, setAiData] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

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
      setError(err.message || 'Failed to load payment details.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCase();
  }, [caseId]);

  const handleFetchAi = async () => {
    try {
      setAiLoading(true);
      const aiRes = await api.getCaseAiAnalysis(caseId);
      setAiData(aiRes);
    } catch (err) {
      console.warn('AI analysis error or unavailable:', err);
      setAiData({ ai_status: 'unavailable', error: err.message });
    } finally {
      setAiLoading(false);
    }
  };

  const handleStartRecovery = async () => {
    try {
      setActionLoading(true);
      await api.requestResolution(caseId);
      await loadCase();
      navigate(`/cases/${caseId}/customer`);
    } catch (err) {
      alert(`Resolution request notice: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
        Loading payment analysis...
      </div>
    );
  }

  if (error || !caseData) {
    return (
      <div style={{ padding: '2rem', background: 'var(--danger-bg)', borderRadius: 'var(--radius-md)', color: '#fca5a5' }}>
        <strong>Notice:</strong> {error || 'Payment not found.'}
        <div style={{ marginTop: '1rem' }}>
          <Link to="/cases" className="btn btn-secondary">
            ← Back to Payments
          </Link>
        </div>
      </div>
    );
  }

  const tx = caseData.transaction || {};
  const isRecovered = caseData.case_status === 'recovered';
  const isReady = caseData.case_status === 'settlement_ready';
  const isMerchantReview = caseData.case_status === 'merchant_review' || caseData.case_status === 'validation_failed';
  const statusInfo = getStatusInfo(caseData.case_status);
  const likelihood = Math.round(Number(caseData.recovery_probability || 0.8) * 100);

  const frictionReasons = (caseData.risk_reasons || []).map(translateFrictionReason);
  const recommendedActionText = translateActionRecommendation(caseData.next_best_action, caseData.missing_information);

  return (
    <div className="case-details-page" style={{ maxWidth: '920px', margin: '0 auto', paddingBottom: '3rem' }}>
      {/* Navigation Breadcrumb */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Link to="/cases" style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            ← Payments Needing Attention
          </Link>
          <span style={{ color: 'var(--border-light)' }}>/</span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Payment #{caseId}</span>
        </div>
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

      {/* Main Status Headline Card */}
      <div
        className="table-card"
        style={{
          padding: '2rem 2.25rem',
          marginBottom: '1.5rem',
          background: isRecovered
            ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(15, 23, 42, 0.9) 100%)'
            : isReady
            ? 'linear-gradient(135deg, rgba(56, 189, 248, 0.12) 0%, rgba(15, 23, 42, 0.9) 100%)'
            : 'linear-gradient(135deg, rgba(245, 158, 11, 0.12) 0%, rgba(15, 23, 42, 0.9) 100%)',
          borderLeft: `4px solid ${statusInfo.color}`,
        }}
      >
        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '0.35rem' }}>
          {isRecovered ? 'Recovery Status' : isReady ? 'Readiness Status' : 'Attention Required'}
        </div>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#fff', marginBottom: '0.5rem' }}>
          {isRecovered
            ? '✓ Revenue Successfully Protected'
            : isReady
            ? 'Payment looks ready for settlement'
            : `${formatCurrency(caseData.revenue_at_risk, tx.currency, true)} potentially at risk`}
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', maxWidth: '680px' }}>
          Total Payment Value: <strong style={{ color: '#fff' }}>{formatCurrency(tx.amount, tx.currency, true)}</strong> · Origin Country: <strong style={{ color: '#fff' }}>{tx.country_code || 'IN'}</strong>
        </p>

        {/* Primary Action Button Bar */}
        <div style={{ display: 'flex', gap: '0.85rem', marginTop: '1.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
          {!isRecovered && !isReady && (
            <button
              onClick={handleStartRecovery}
              disabled={actionLoading}
              className="btn btn-primary"
              style={{ padding: '0.75rem 1.75rem', fontSize: '0.95rem', fontWeight: 600 }}
            >
              {actionLoading ? 'Initiating...' : 'Start Recovery'}
            </button>

          )}

          {isMerchantReview && (
            <Link
              to={`/cases/${caseId}/review`}
              className="btn btn-primary"
              style={{ padding: '0.75rem 1.75rem', fontSize: '0.95rem', fontWeight: 600, background: 'var(--amber)' }}
            >
              Review Payment Decision →
            </Link>
          )}

          <Link
            to={`/cases/${caseId}/customer`}
            className="btn btn-secondary"
            style={{ padding: '0.75rem 1.25rem', fontSize: '0.9rem' }}
          >
            Customer Resolution Portal
          </Link>
        </div>
      </div>

      {/* 3 Clear Merchant Sections */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.25rem', marginBottom: '1.5rem' }}>
        {/* Why is this payment at risk? */}
        <div className="table-card" style={{ padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#fff', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>⚠️</span>
            <span>Why is this payment at risk?</span>
          </h3>
          {frictionReasons.length === 0 ? (
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              No critical settlement friction identified.
            </p>
          ) : (
            <ul style={{ paddingLeft: '1.2rem', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.6 }}>
              {frictionReasons.map((r, i) => (
                <li key={i} style={{ marginBottom: '0.35rem' }}>{r}</li>
              ))}
            </ul>
          )}
        </div>

        {/* Recommended Action */}
        <div className="table-card" style={{ padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#fff', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>🎯</span>
            <span>Recommended Action</span>
          </h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.6, marginBottom: '0.75rem' }}>
            {recommendedActionText}
          </p>
          <div style={{ fontSize: '0.8rem', color: 'var(--cyan)', fontWeight: 600 }}>
            Next Best Action: {getActionLabel(caseData.next_best_action)}
          </div>
        </div>

        {/* Recovery Probability */}
        <div className="table-card" style={{ padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#fff', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>📈</span>
            <span>Recovery Probability</span>
          </h3>
          <div style={{ fontSize: '2rem', fontWeight: 700, color: likelihood >= 70 ? 'var(--success)' : '#fbbf24', marginBottom: '0.5rem' }}>
            {likelihood}%
          </div>
          <div className="progress-bar-container" style={{ height: '8px', borderRadius: '4px', background: 'rgba(255,255,255,0.08)' }}>
            <div
              style={{
                width: `${likelihood}%`,
                height: '100%',
                borderRadius: '4px',
                background: likelihood >= 70 ? 'var(--success)' : '#fbbf24',
              }}
            />
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '0.5rem' }}>
            Estimated recovery success probability upon customer resolution.
          </p>
        </div>
      </div>


      {/* Recovery Timeline */}
      <div className="table-card" style={{ padding: '1.75rem', marginBottom: '1.5rem' }}>
        <h3 style={{ fontSize: '1.05rem', fontWeight: 600, color: '#fff', marginBottom: '1.25rem' }}>
          Recovery Timeline
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          {[
            {
              title: 'Payment received',
              desc: `Transaction ${formatCurrency(tx.amount, tx.currency, true)} ingested`,
              done: true,
              active: false,
            },
            {
              title: 'Risk detected',
              desc: `${formatCurrency(caseData.revenue_at_risk, tx.currency, true)} flagged at risk`,
              done: true,
              active: false,
            },
            {
              title: 'Recovery requested',
              desc: 'Resolution workflow initiated with customer',
              done: caseData.case_status !== 'open' && caseData.case_status !== 'created' && caseData.case_status !== 'action_required',
              active: caseData.case_status === 'open' || caseData.case_status === 'action_required',
            },
            {
              title: 'Customer responded',
              desc: resolutionDetails?.customer_submission ? 'Customer submitted invoice details' : 'Awaiting customer response',
              done: Boolean(resolutionDetails?.customer_submission),
              active: caseData.case_status === 'resolution_requested' || caseData.case_status === 'awaiting_customer',
            },
            {
              title: 'Validation passed',
              desc: resolutionDetails?.latest_validation?.status === 'PASS' ? 'All documentation verified deterministically' : 'Deterministic check pending',
              done: resolutionDetails?.latest_validation?.status === 'PASS' || isRecovered || isReady,
              active: Boolean(resolutionDetails?.customer_submission) && !isRecovered && !isReady && resolutionDetails?.latest_validation?.status !== 'PASS',
            },
            {
              title: 'Merchant review',
              desc: isRecovered ? 'Approved by merchant' : 'Human-in-the-loop verification',
              done: isRecovered || isReady,
              active: isMerchantReview,
            },
            {
              title: 'Recovery completed',
              desc: isRecovered ? 'Revenue fully recovered & settlement unlocked' : 'Final recovery clearing',
              done: isRecovered,
              active: isReady && !isRecovered,
            },
          ].map((step, idx) => (
            <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.85rem' }}>
              <div
                style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  background: step.done
                    ? 'var(--success)'
                    : step.active
                    ? 'var(--accent-blue)'
                    : '#1e293b',
                  color: step.done || step.active ? '#fff' : 'var(--text-muted)',
                  border: step.active ? '2px solid #60a5fa' : 'none',
                  flexShrink: 0,
                  marginTop: '0.1rem',
                }}
              >
                {step.done ? '✓' : step.active ? '→' : '•'}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: step.done ? '#fff' : step.active ? 'var(--cyan)' : 'var(--text-muted)' }}>
                  {step.title}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.1rem' }}>
                  {step.desc}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>


      {/* Customer Submission & Verification Summary (if customer has responded) */}
      {resolutionDetails?.customer_submission && (
        <div className="table-card" style={{ padding: '1.5rem', marginBottom: '1.5rem', borderLeft: '4px solid var(--purple)' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: '#fff', marginBottom: '0.75rem' }}>
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
              <span style={{ color: 'var(--text-muted)' }}>Invoice Amount:</span>
              <div style={{ fontWeight: 600, color: '#fff' }}>
                {resolutionDetails.customer_submission.invoice_amount} {resolutionDetails.customer_submission.invoice_currency}
              </div>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>Invoice Ref:</span>
              <div style={{ fontWeight: 600, color: '#fff' }}>{resolutionDetails.customer_submission.invoice_reference || 'N/A'}</div>
            </div>
          </div>
        </div>
      )}

      {/* Collapsible Technical Details for Auditing */}
      <div className="table-card" style={{ padding: '1.25rem' }}>
        <button
          type="button"
          onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-secondary)',
            fontSize: '0.9rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            width: '100%',
            padding: '0.25rem 0',
          }}
        >
          <span>{showTechnicalDetails ? '▲ Hide technical details' : '▼ View technical details'}</span>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            {showTechnicalDetails ? 'Collapse' : 'Risk Score, AI explanation & Audit log'}
          </span>
        </button>

        {showTechnicalDetails && (
          <div style={{ marginTop: '1.25rem', paddingTop: '1.25rem', borderTop: '1px solid var(--border-color)' }}>
            {/* Technical Metadata Row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', marginBottom: '1.5rem', fontSize: '0.85rem' }}>
              <div style={{ background: '#0a0f18', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Settlement Risk Score</span>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff' }}>{caseData.risk_score} / 100</div>
              </div>
              <div style={{ background: '#0a0f18', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Internal Transaction ID</span>
                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--cyan)' }}>{tx.payment_id || `pay_${tx.id}`}</div>
              </div>
              <div style={{ background: '#0a0f18', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>High-Value Classification</span>
                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: caseData.is_high_value ? 'var(--cyan)' : '#fff' }}>
                  {caseData.is_high_value ? 'Yes (Exceeds Threshold)' : 'Standard'}
                </div>
              </div>
              <div style={{ background: '#0a0f18', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Deterministic Heuristic</span>
                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#fff' }}>{caseData.readiness_status}</div>
              </div>
            </div>

            {/* AI-Assisted Explanation Box */}
            <div style={{ background: '#0a0f18', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', marginBottom: '1.5rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                <div style={{ fontWeight: 600, color: '#fff', fontSize: '0.9rem' }}>
                  ✨ RecoverX Recommendation
                </div>
                {!aiData && (
                  <button
                    onClick={handleFetchAi}
                    disabled={aiLoading}
                    className="btn btn-secondary"
                    style={{ fontSize: '0.75rem', padding: '0.3rem 0.75rem' }}
                  >
                    {aiLoading ? 'Generating...' : 'Generate AI Explanation'}
                  </button>
                )}
              </div>

              {aiData ? (
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  {aiData.executive_summary && <p style={{ marginBottom: '0.5rem' }}>{aiData.executive_summary}</p>}
                  {aiData.root_cause && <p style={{ marginBottom: '0.5rem' }}><strong>Root Cause:</strong> {aiData.root_cause}</p>}
                  {aiData.recommended_action && <p><strong>Recommendation:</strong> {aiData.recommended_action}</p>}
                </div>
              ) : (
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Click above to generate a plain-English executive explanation.
                </p>
              )}
            </div>

            {/* Audit History Log */}
            <div>
              <h4 style={{ fontSize: '0.85rem', fontWeight: 600, color: '#fff', marginBottom: '0.75rem' }}>
                Audit Activity History
              </h4>
              {auditLogs.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No audit history recorded.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', fontSize: '0.8rem' }}>
                  {auditLogs.slice(0, 5).map((l, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', padding: '0.35rem 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                      <span>{l.event_type.replace(/_/g, ' ')}: {l.details}</span>
                      <span style={{ color: 'var(--text-muted)' }}>{new Date(l.created_at).toLocaleTimeString()}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

