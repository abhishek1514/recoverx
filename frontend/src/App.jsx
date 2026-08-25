import React, { useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/common/Sidebar';
import Dashboard from './pages/Dashboard';
import PaymentsList from './pages/PaymentsList';
import NeedsAttention from './pages/NeedsAttention';
import CaseDetails from './pages/CaseDetails';
import CustomerResolution from './pages/CustomerResolution';
import MerchantReview from './pages/MerchantReview';
import NewTransaction from './pages/NewTransaction';
import PaymentCheckout from './pages/PaymentCheckout';
import PaymentStatus from './pages/PaymentStatus';
import Settings from './pages/Settings';

export default function App() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className={`app-layout ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar collapsed={collapsed} setCollapsed={setCollapsed} />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/payments" element={<PaymentsList />} />
          <Route path="/needs-attention" element={<NeedsAttention />} />
          <Route path="/cases" element={<NeedsAttention />} />
          <Route path="/cases/:caseId" element={<CaseDetails />} />
          <Route path="/cases/:caseId/customer" element={<CustomerResolution />} />
          <Route path="/cases/:caseId/review" element={<MerchantReview />} />
          <Route path="/transactions/new" element={<NewTransaction />} />
          <Route path="/pay" element={<PaymentCheckout />} />
          <Route path="/payments/:orderId/status" element={<PaymentStatus />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}




