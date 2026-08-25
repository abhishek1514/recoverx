/**
 * Merchant-friendly status and action mapping utilities for RecoverX.
 */

export const STATUS_LABELS = {
  open: { label: 'Monitoring', badgeClass: 'badge-blue', color: '#60a5fa' },
  action_required: { label: 'Action Needed', badgeClass: 'badge-amber', color: '#fbbf24' },
  at_risk: { label: 'Action Needed', badgeClass: 'badge-amber', color: '#fbbf24' },
  customer_responded: { label: 'Information Received', badgeClass: 'badge-purple', color: '#c084fc' },
  validation_pending: { label: 'Checking Information', badgeClass: 'badge-blue', color: '#38bdf8' },
  validation_failed: { label: 'Information Mismatch', badgeClass: 'badge-red', color: '#f87171' },
  merchant_review: { label: 'Needs Your Review', badgeClass: 'badge-amber', color: '#fb923c' },
  settlement_ready: { label: 'Ready for Settlement Review', badgeClass: 'badge-green', color: '#4ade80' },
  ready: { label: 'Ready for Settlement Review', badgeClass: 'badge-green', color: '#4ade80' },
  recovered: { label: 'Recovered At-Risk Revenue', badgeClass: 'badge-green', color: '#34d399' },
  closed: { label: 'Closed', badgeClass: 'badge-blue', color: '#94a3b8' },
};

export const ACTION_LABELS = {
  REQUEST_INFORMATION: 'Request Missing Information',
  CUSTOMER_RESOLUTION_REQUESTED: 'Information Requested',
  NO_ACTION: 'No Action Needed',
  MERCHANT_REVIEW: 'Review Payment',
  REVIEW_PAYMENT: 'Review Payment',
  VERIFY_DOCUMENTS: 'Verify Commercial Documents',
};

export function getStatusInfo(statusKey) {
  if (!statusKey) return { label: 'Monitoring', badgeClass: 'badge-blue', color: '#94a3b8' };
  const key = String(statusKey).toLowerCase().trim();
  return STATUS_LABELS[key] || { label: 'Monitoring', badgeClass: 'badge-blue', color: '#94a3b8' };
}

export function getActionLabel(actionKey) {
  if (!actionKey) return 'Monitor Payment';
  const key = String(actionKey).toUpperCase().trim();
  return ACTION_LABELS[key] || key.replace(/_/g, ' ');
}

export function translateFrictionReason(reason) {
  if (!reason) return '';
  if (reason.includes('exceeds the configured high-value threshold')) {
    return 'High-value transaction exceeds standard automated clearing limits.';
  }
  if (reason.includes('No customer record') || reason.includes('Customer information is incomplete')) {
    return 'Customer contact information or billing profile is incomplete.';
  }
  if (reason.includes('No available invoice') || reason.includes('supporting document')) {
    return 'Commercial invoice or supporting document has not yet been uploaded.';
  }
  if (reason.includes('needs review') || reason.includes('Payment status')) {
    return 'Payment gateway status indicates settlement review is required.';
  }
  if (reason.includes('Payment method or transaction type is unavailable')) {
    return 'Payment routing and method details need verification.';
  }
  if (reason.includes('No previous transaction history')) {
    return 'First-time customer with no prior transaction history on file.';
  }
  return reason;
}

export function translateActionRecommendation(actionKey, missingInfo = []) {
  if (actionKey === 'REQUEST_INFORMATION') {
    return 'Request the missing customer contact and invoice details before settlement review.';
  }
  if (actionKey === 'MERCHANT_REVIEW' || actionKey === 'REVIEW_PAYMENT') {
    return 'Review customer submitted documentation to verify eligibility for settlement review.';
  }
  if (actionKey === 'NO_ACTION') {
    return 'Payment is complete and ready to clear settlement without additional intervention.';
  }
  return 'Review transaction documentation and confirm customer identity.';
}
