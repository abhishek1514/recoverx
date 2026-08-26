import React, { useState, useEffect } from 'react';
import { api } from '../services/api';

export default function Disputes() {
  const [disputes, setDisputes] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDispute, setSelectedDispute] = useState(null);
  const [evidenceData, setEvidenceData] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [draftData, setDraftData] = useState(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadCategory, setUploadCategory] = useState('proof_of_delivery');
  const [uploadFile, setUploadFile] = useState(null);
  const [extractedAmount, setExtractedAmount] = useState('');
  const [merchantNotes, setMerchantNotes] = useState('');
  const [approvedSummary, setApprovedSummary] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [actionSuccess, setActionSuccess] = useState('');
  const [actionError, setActionError] = useState('');

  const loadData = async () => {
    try {
      setLoading(true);
      const [dispList, metData] = await Promise.all([
        api.getDisputes(),
        api.getDisputeMetrics().catch(() => null),
      ]);
      setDisputes(dispList);
      setMetrics(metData);
      if (dispList.length > 0 && !selectedDispute) {
        selectDisputeDetail(dispList[0].id);
      }
    } catch (err) {
      console.error('Failed loading disputes:', err);
    } finally {
      setLoading(false);
    }
  };

  const selectDisputeDetail = async (id) => {
    try {
      const [d, ev, tl] = await Promise.all([
        api.getDispute(id),
        api.getDisputeEvidence(id),
        api.getDisputeTimeline(id).catch(() => []),
      ]);
      setSelectedDispute(d);
      setEvidenceData(ev);
      setTimeline(tl);
      setDraftData(null);
      setApprovedSummary(d.contest_summary || '');
      setActionSuccess('');
      setActionError('');
    } catch (err) {
      console.error('Error fetching dispute detail:', err);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleUploadEvidence = async (e) => {
    e.preventDefault();
    if (!uploadFile || !selectedDispute) return;

    try {
      setSubmitting(true);
      setActionError('');
      const formData = new FormData();
      formData.append('document_type', uploadCategory);
      formData.append('file', uploadFile);
      if (extractedAmount) {
        formData.append('extracted_amount', extractedAmount);
      }

      await api.uploadDisputeEvidence(selectedDispute.id, formData);
      setActionSuccess(`Successfully uploaded ${uploadCategory.replace('_', ' ')} evidence.`);
      setUploadModalOpen(false);
      setUploadFile(null);
      setExtractedAmount('');
      // Reload dispute details
      await selectDisputeDetail(selectedDispute.id);
      await loadData();
    } catch (err) {
      setActionError(err.message || 'Failed uploading evidence file.');
    } finally {
      setSubmitting(false);
    }
  };

  const handlePrepareContest = async () => {
    if (!selectedDispute) return;
    try {
      setSubmitting(true);
      setActionError('');
      const draft = await api.prepareDisputeContest(selectedDispute.id, {
        merchant_notes: merchantNotes,
      });
      setDraftData(draft);
      setApprovedSummary(draft.contest_summary);
      setActionSuccess('AI Contest draft prepared. Please review below and approve for submission.');
      // Refresh dispute
      const updated = await api.getDispute(selectedDispute.id);
      setSelectedDispute(updated);
    } catch (err) {
      setActionError(err.message || 'Failed generating contest draft.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleApproveAndSubmit = async () => {
    if (!selectedDispute) return;
    try {
      setSubmitting(true);
      setActionError('');
      const result = await api.approveDisputeContest(selectedDispute.id, {
        approved_summary: approvedSummary,
      });
      setSelectedDispute(result);
      setActionSuccess('Dispute contest approved and submitted to Razorpay!');
      await selectDisputeDetail(selectedDispute.id);
      await loadData();
    } catch (err) {
      setActionError(err.message || 'Failed submitting contest to Razorpay.');
    } finally {
      setSubmitting(false);
    }
  };

  const getDeadlineBadge = (dispute) => {
    if (dispute.deadline_status === 'deadline_critical') {
      return (
        <span className="badge badge-danger">
          ⚠️ {dispute.hours_remaining ? `${dispute.hours_remaining}h remaining (CRITICAL)` : 'Critical Deadline'}
        </span>
      );
    }
    if (dispute.deadline_status === 'deadline_approaching') {
      return (
        <span className="badge badge-warning">
          ⏳ {dispute.hours_remaining ? `${dispute.hours_remaining}h remaining` : 'Deadline Approaching'}
        </span>
      );
    }
    if (dispute.deadline_status === 'deadline_expired') {
      return <span className="badge badge-secondary">❌ Deadline Expired</span>;
    }
    return (
      <span className="badge badge-success">
        ✓ {dispute.hours_remaining ? `${dispute.hours_remaining}h safe` : 'Safe'}
      </span>
    );
  };

  return (
    <div className="page-container">
      {/* Header & Metrics */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Disputes & Chargebacks</h1>
          <p className="page-subtitle">
            Autonomous, evidence-backed revenue protection for disputed payments.
          </p>
        </div>
      </div>

      {metrics && (
        <div className="metrics-grid" style={{ marginBottom: '1.5rem' }}>
          <div className="metric-card">
            <span className="metric-label">Revenue at Risk</span>
            <span className="metric-value text-danger">₹{Number(metrics.amount_at_risk).toLocaleString()}</span>
            <span className="metric-subtext">{metrics.open_disputes} open dispute(s)</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">Critical Deadlines (&lt;24h)</span>
            <span className="metric-value text-warning">{metrics.deadline_critical_disputes}</span>
            <span className="metric-subtext">Requires immediate response</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">Evidence Complete</span>
            <span className="metric-value text-primary">{metrics.evidence_complete_rate}%</span>
            <span className="metric-subtext">Disputes ready to contest</span>
          </div>
          <div className="metric-card">
            <span className="metric-label">Contest Success</span>
            <span className="metric-value text-success">{metrics.contest_success_rate}%</span>
            <span className="metric-subtext">₹{Number(metrics.amount_recovered).toLocaleString()} recovered</span>
          </div>
        </div>
      )}

      {/* Main Two-Column Layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: '1.5rem', alignItems: 'start' }}>
        {/* Left Column: Dispute List */}
        <div className="card">
          <div className="card-header" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem' }}>
            <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Active Disputes</h3>
          </div>
          <div style={{ maxHeight: '680px', overflowY: 'auto' }}>
            {loading ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading disputes...</div>
            ) : disputes.length === 0 ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                No active disputes on file.
              </div>
            ) : (
              disputes.map((d) => (
                <div
                  key={d.id}
                  onClick={() => selectDisputeDetail(d.id)}
                  style={{
                    padding: '1rem',
                    borderBottom: '1px solid var(--border-color)',
                    cursor: 'pointer',
                    backgroundColor: selectedDispute?.id === d.id ? 'var(--bg-card-hover, rgba(59, 130, 246, 0.08))' : 'transparent',
                    borderLeft: selectedDispute?.id === d.id ? '4px solid var(--primary-color)' : '4px solid transparent',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                    <span style={{ fontWeight: 600 }}>₹{Number(d.amount).toLocaleString()} {d.currency}</span>
                    <span className={`badge badge-${d.status === 'won' ? 'success' : d.status === 'lost' ? 'danger' : 'warning'}`}>
                      {d.status.toUpperCase()}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                    {d.razorpay_dispute_id} • {d.reason_code || 'General Dispute'}
                  </div>
                  <div>{getDeadlineBadge(d)}</div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right Column: Dispute Resolution Workspace */}
        {selectedDispute ? (
          <div className="card" style={{ padding: '1.5rem' }}>
            {actionSuccess && (
              <div className="alert alert-success" style={{ marginBottom: '1rem' }}>
                ✓ {actionSuccess}
              </div>
            )}
            {actionError && (
              <div className="alert alert-danger" style={{ marginBottom: '1rem' }}>
                ⚠️ {actionError}
              </div>
            )}

            {/* Step 1: What Happened? */}
            <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '1.25rem', marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span style={{ fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-secondary)', fontWeight: 600 }}>
                    1. Dispute Overview
                  </span>
                  <h2 style={{ margin: '0.25rem 0', fontSize: '1.5rem' }}>
                    ₹{Number(selectedDispute.amount).toLocaleString()} {selectedDispute.currency} at Risk
                  </h2>
                </div>
                <div>{getDeadlineBadge(selectedDispute)}</div>
              </div>
              <p style={{ color: 'var(--text-secondary)', margin: '0.5rem 0 0 0' }}>
                Dispute <strong>{selectedDispute.razorpay_dispute_id}</strong> was raised for reason: <strong>{selectedDispute.reason_code || 'Customer dispute'}</strong>.
                Associated payment: <code>{selectedDispute.payment_id || 'On file'}</code>.
              </p>
            </div>

            {/* Step 2: Evidence Checklist */}
            <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '1.25rem', marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                <span style={{ fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-secondary)', fontWeight: 600 }}>
                  2. Evidence Completeness
                </span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setUploadModalOpen(true)}
                  disabled={selectedDispute.status === 'won' || selectedDispute.status === 'lost'}
                >
                  + Upload Evidence Document
                </button>
              </div>

              {evidenceData && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div style={{ background: 'var(--bg-secondary, #f8fafc)', padding: '1rem', borderRadius: '8px' }}>
                    <div style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: '0.5rem' }}>Required Evidence</div>
                    {evidenceData.required_evidence.map((req) => {
                      const isSubmitted = evidenceData.submitted_documents.some((d) => d.document_type === req);
                      return (
                        <div key={req} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem', fontSize: '0.9rem' }}>
                          <span style={{ color: isSubmitted ? '#10b981' : '#ef4444' }}>{isSubmitted ? '✓' : '✗'}</span>
                          <span style={{ textTransform: 'capitalize' }}>{req.replace(/_/g, ' ')}</span>
                        </div>
                      );
                    })}
                  </div>

                  <div style={{ background: 'var(--bg-secondary, #f8fafc)', padding: '1rem', borderRadius: '8px' }}>
                    <div style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: '0.5rem' }}>Attached Documents ({evidenceData.submitted_documents.length})</div>
                    {evidenceData.submitted_documents.length === 0 ? (
                      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>No documents attached yet.</div>
                    ) : (
                      evidenceData.submitted_documents.map((doc) => (
                        <div key={doc.id} style={{ fontSize: '0.85rem', marginBottom: '0.35rem', display: 'flex', justifyContent: 'space-between' }}>
                          <span>📄 {doc.file_name || doc.document_type}</span>
                          <span className="badge badge-success">Attached</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Step 3: Recommendation & AI Contest Draft */}
            <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '1.25rem', marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                <span style={{ fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-secondary)', fontWeight: 600 }}>
                  3. RecoverX Recommendation & Defense Letter
                </span>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handlePrepareContest}
                  disabled={submitting || selectedDispute.status === 'won' || selectedDispute.status === 'lost'}
                >
                  ⚡ Prepare AI Contest Draft
                </button>
              </div>

              <div style={{ background: 'var(--bg-secondary, #f8fafc)', padding: '1rem', borderRadius: '8px', marginBottom: '1rem' }}>
                <div style={{ fontWeight: 600, color: 'var(--primary-color)', marginBottom: '0.25rem' }}>
                  Recommendation: {selectedDispute.evidence_completeness === 'complete' ? 'CONTEST (Strong Defense)' : 'UPLOAD MISSING EVIDENCE THEN CONTEST'}
                </div>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                  {selectedDispute.validation_notes || 'Deterministic validation completed.'}
                </div>
              </div>

              {(draftData || selectedDispute.contest_summary) && (
                <div>
                  <label style={{ display: 'block', fontWeight: 600, fontSize: '0.9rem', marginBottom: '0.5rem' }}>
                    Contest Defense Summary (Editable by Merchant):
                  </label>
                  <textarea
                    rows={5}
                    className="form-control"
                    style={{ width: '100%', padding: '0.75rem', borderRadius: '6px', border: '1px solid var(--border-color)', fontSize: '0.9rem' }}
                    value={approvedSummary}
                    onChange={(e) => setApprovedSummary(e.target.value)}
                    placeholder="Contest explanation summary for Razorpay / issuing bank..."
                  />
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                    * AI-generated draft — requires merchant review before submission.
                  </div>
                </div>
              )}
            </div>

            {/* Step 4: Merchant Decision Action Bar */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  Contest Status: <strong>{selectedDispute.contest_status.toUpperCase()}</strong>
                </span>
              </div>
              <div style={{ display: 'flex', gap: '0.75rem' }}>
                {selectedDispute.status !== 'won' && selectedDispute.status !== 'lost' && (
                  <button
                    type="button"
                    className="btn btn-success"
                    onClick={handleApproveAndSubmit}
                    disabled={submitting || selectedDispute.contest_status === 'submitted' || selectedDispute.status === 'under_review'}
                  >
                    {submitting ? 'Submitting...' : selectedDispute.status === 'under_review' ? '✓ Already Submitted to Bank' : 'Approve & Submit to Razorpay'}
                  </button>
                )}
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* Upload Evidence Modal */}
      {uploadModalOpen && (
        <div className="modal-backdrop" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div className="modal-content card" style={{ width: '480px', padding: '1.5rem', background: 'var(--bg-card, #fff)' }}>
            <h3 style={{ margin: '0 0 1rem 0' }}>Upload Evidence Document</h3>
            <form onSubmit={handleUploadEvidence}>
              <div className="form-group" style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, fontSize: '0.9rem' }}>Evidence Category</label>
                <select
                  className="form-control"
                  style={{ width: '100%', padding: '0.5rem' }}
                  value={uploadCategory}
                  onChange={(e) => setUploadCategory(e.target.value)}
                >
                  <option value="proof_of_delivery">Proof of Delivery (POD) / Tracking</option>
                  <option value="invoice">Tax Invoice / Billing Receipt</option>
                  <option value="customer_communication">Customer Email / Chat Correspondence</option>
                  <option value="order_information">Order Confirmation</option>
                  <option value="terms_and_conditions">Terms & Conditions Agreement</option>
                  <option value="service_evidence">Proof of Service Rendered</option>
                </select>
              </div>

              <div className="form-group" style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, fontSize: '0.9rem' }}>Select File (PDF, PNG, JPG)</label>
                <input
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg"
                  className="form-control"
                  onChange={(e) => setUploadFile(e.target.files[0])}
                  required
                />
              </div>

              <div className="form-group" style={{ marginBottom: '1.5rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, fontSize: '0.9rem' }}>Invoice Amount (Optional for Validation)</label>
                <input
                  type="number"
                  step="0.01"
                  className="form-control"
                  placeholder="e.g. 50000.00"
                  value={extractedAmount}
                  onChange={(e) => setExtractedAmount(e.target.value)}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setUploadModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting || !uploadFile}>
                  {submitting ? 'Uploading...' : 'Upload & Attach'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

