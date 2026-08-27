/**
 * RecoverX Centralized Production API Client
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const ACCESS_TOKEN_KEY = 'recoverx_access_token';
const USER_KEY = 'recoverx_user';

function clearStoredAuthentication() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function notifyAuthenticationRequired() {
  clearStoredAuthentication();
  window.dispatchEvent(new Event('recoverx:authentication-required'));
}

async function verifyCurrentSession() {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  if (!token) {
    notifyAuthenticationRequired();
    return;
  }
  try {
    const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) notifyAuthenticationRequired();
  } catch (_) {
    // A transient network failure is not proof that the local JWT has expired.
  }
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;
  const defaultHeaders = {};

  if (!(options.body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  if (token) {
    defaultHeaders['Authorization'] = `Bearer ${token}`;
  }

  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  };

  try {
    const response = await fetch(url, config);
    if (!response.ok) {
      let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const errorData = await response.json();
        errorDetail = errorData.detail || errorDetail;
      } catch (_) {}
      const error = new Error(errorDetail);
      error.status = response.status;
      if (response.status === 401) {
        if (endpoint === '/api/auth/me') notifyAuthenticationRequired();
        else if (endpoint !== '/api/auth/login') void verifyCurrentSession();
      }
      throw error;
    }
    return await response.json();
  } catch (error) {
    console.error(`API Error on ${endpoint}:`, error);
    throw error;
  }
}

export const api = {
  // Authentication
  login: async (credentials) => {
    const data = await request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
    if (data.access_token) {
      localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    }
    return data;
  },

  getMe: () => request('/api/auth/me'),

  logout: () => {
    clearStoredAuthentication();
  },

  // Dashboard
  getDashboardSummary: () => request('/api/dashboard/summary'),

  // Unified Revenue Exceptions (Phase 5)
  getRevenueExceptions: (params = {}) => {
    const query = new URLSearchParams();
    if (params.type) query.append('type', params.type);
    if (params.status) query.append('status', params.status);
    if (params.priority) query.append('priority', params.priority);
    if (params.min_amount) query.append('min_amount', params.min_amount);
    if (params.deadline_status) query.append('deadline_status', params.deadline_status);
    const qs = query.toString();
    return request('/api/exceptions' + (qs ? `?${qs}` : ''));
  },
  getRevenueExceptionMetrics: () => request('/api/exceptions/metrics'),
  getRevenueExceptionDetail: (id) => request(`/api/exceptions/${id}`),

  // Cases
  getCases: () => request('/api/cases'),
  getCase: (caseId) => request(`/api/cases/${caseId}`),
  analyzeTransaction: (transactionId) =>
    request(`/api/cases/analyze/${transactionId}`, { method: 'POST' }),

  // Disputes & Chargebacks (Phase 3)
  getDisputes: (status) => request('/api/disputes' + (status ? `?status=${status}` : '')),
  getDispute: (id) => request(`/api/disputes/${id}`),
  getDisputeEvidence: (id) => request(`/api/disputes/${id}/evidence`),
  uploadDisputeEvidence: (id, formData) =>
    request(`/api/disputes/${id}/evidence`, { method: 'POST', body: formData }),
  prepareDisputeContest: (id, payload) =>
    request(`/api/disputes/${id}/prepare-contest`, {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  approveDisputeContest: (id, payload) =>
    request(`/api/disputes/${id}/approve-contest`, {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  getDisputeTimeline: (id) => request(`/api/disputes/${id}/timeline`),
  getDisputeMetrics: () => request('/api/disputes/metrics/summary'),

  // Settlements & Reconciliation (Phase 4)
  getSettlements: (status) => request('/api/settlements' + (status ? `?status=${status}` : '')),
  getSettlement: (id) => request(`/api/settlements/${id}`),
  getSettlementExceptions: () => request('/api/settlements/exceptions'),
  getReconciliationRecords: (status) => request('/api/settlements/reconciliation' + (status ? `?status=${status}` : '')),
  getSettlementMetrics: () => request('/api/settlements/metrics'),
  syncSettlement: (id) => request(`/api/settlements/${id}/sync`, { method: 'POST' }),
  syncAllSettlements: (lookbackHours) =>
    request('/api/settlements/sync-all' + (lookbackHours ? `?lookback_hours=${lookbackHours}` : ''), { method: 'POST' }),

  // Transactions & Interactive Test Mode
  getTransactions: () => request('/api/transactions'),
  createTestTransaction: (payload) =>
    request('/api/transactions/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Razorpay Test Mode Checkout
  createRazorpayOrder: (payload) =>
    request('/api/payments/create-order', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  verifyRazorpayPayment: (payload) =>
    request('/api/payments/verify', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getRazorpayOrderStatus: (orderId) =>
    request(`/api/payments/order/${orderId}/status`),

  // AI Explanation
  getCaseAiAnalysis: (caseId) =>
    request(`/api/cases/${caseId}/ai-analysis`, { method: 'POST' }),

  // Customer Resolution
  requestResolution: (caseId) =>
    request(`/api/cases/${caseId}/request-resolution`, { method: 'POST' }),
  
  resolveCase: (caseId, payload, isFormData = false) => {
    return request(`/api/customers/cases/${caseId}/resolve`, {
      method: 'POST',
      body: isFormData ? payload : JSON.stringify(payload),
    });
  },

  // Deterministic Validation & Review
  validateCase: (caseId) =>
    request(`/api/cases/${caseId}/validate`, { method: 'POST' }),
  
  reviewCase: (caseId, { decision, notes }) =>
    request(`/api/cases/${caseId}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, notes }),
    }),

  // Resolution Details & Audit
  getCaseResolution: (caseId) => request(`/api/cases/${caseId}/resolution`),
  getCaseAudit: (caseId) => request(`/api/cases/${caseId}/audit`),

  // Document Access
  getDocumentSignedUrl: (docId) => request(`/api/documents/${docId}/signed-url`),

  // Test Webhook trigger (Dev/Demo)
  triggerTestWebhook: (payload) =>
    request('/api/webhooks/razorpay/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Full Demo Workflow Orchestrator
  runDemoWorkflow: async (onProgress = () => {}) => {
    const timestamp = Date.now();
    const eventId = `evt_demo_${timestamp}`;
    const paymentId = `pay_demo_${timestamp}`;

    onProgress({ step: 1, text: 'Simulating High-Value International Payment (₹5,80,000 INR)...' });
    
    // 1. Send test webhook with 580,000 INR (amount in paise = 58000000)
    await api.triggerTestWebhook({
      event_id: eventId,
      event: 'payment.captured',
      payload: {
        payment: {
          entity: {
            id: paymentId,
            order_id: `order_demo_${timestamp}`,
            amount: 58000000,
            currency: 'INR',
            status: 'captured',
            method: 'upi',
            customer_id: `cust_demo_${timestamp}`,
            created_at: Math.floor(timestamp / 1000),
          },
        },
      },
    });

    // Small delay to ensure background worker normalizes and analyzes
    await new Promise((r) => setTimeout(r, 600));

    onProgress({ step: 2, text: 'Deterministic Intelligence: Detecting Settlement Risk & Revenue At Risk...' });
    const cases = await api.getCases();
    const currentCase = cases[0];

    if (!currentCase) {
      throw new Error('Could not find newly generated recovery case.');
    }

    onProgress({ step: 3, text: 'Triggering Customer Resolution (Requesting invoice & customer information)...' });
    await api.requestResolution(currentCase.id);

    await new Promise((r) => setTimeout(r, 600));

    onProgress({ step: 4, text: 'Customer Submitting Matching Commercial Invoice (₹5,80,000 INR)...' });
    
    const pdfBlob = new Blob(
      ['%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000118 00000 n \ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n180\n%%EOF'],
      { type: 'application/pdf' }
    );
    const invoiceFile = new File([pdfBlob], 'commercial_invoice_demo.pdf', { type: 'application/pdf' });

    const formData = new FormData();
    formData.append('customer_name', 'Asha Sharma');
    formData.append('customer_email', 'asha.sharma@enterprise.com');
    formData.append('country_code', 'IN');
    formData.append('invoice_amount', '580000');
    formData.append('invoice_currency', 'INR');
    formData.append('invoice_reference', `INV-DEMO-${timestamp.toString().slice(-6)}`);
    formData.append('invoice_date', new Date().toISOString().split('T')[0]);
    formData.append('notes', 'Commercial invoice uploaded for full settlement reconciliation.');
    formData.append('file', invoiceFile);

    const valResult = await api.resolveCase(currentCase.id, formData, true);

    await new Promise((r) => setTimeout(r, 600));

    onProgress({
      step: 5,
      text: `Deterministic Validation: ${valResult.status}. Reached Settlement Readiness...`,
    });
    
    onProgress({ step: 6, text: 'Merchant Review: Approving case for recovery completion...' });
    await api.reviewCase(currentCase.id, {
      decision: 'APPROVE',
      notes: 'Merchant verified commercial invoice and approved settlement readiness.',
    });

    onProgress({ step: 7, text: 'Success! ₹2,61,000 At-Risk Revenue Recovered/Unlocked.' });
    return currentCase.id;
  },

  // Webhook / Payment-State Recovery
  resyncWebhookPayment: (transactionId) =>
    request(`/api/webhooks/recovery/${transactionId}/sync`, { method: 'POST' }),

  triggerWebhookRecoveryDetect: () =>
    request('/api/webhooks/recovery/detect', { method: 'POST' }),

  getWebhookRecoveryMismatches: () =>
    request('/api/webhooks/recovery/mismatches'),
};
