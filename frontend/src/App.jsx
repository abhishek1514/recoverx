import React, { useEffect, useState } from 'react';
import { Navigate, Outlet, Route, Routes } from 'react-router-dom';
import Sidebar from './components/common/Sidebar';
import { api } from './services/api';
import Dashboard from './pages/Dashboard';
import RevenueExceptions from './pages/RevenueExceptions';
import PaymentsList from './pages/PaymentsList';
import NeedsAttention from './pages/NeedsAttention';
import Disputes from './pages/Disputes';
import Settlements from './pages/Settlements';
import CaseDetails from './pages/CaseDetails';
import CustomerResolution from './pages/CustomerResolution';
import MerchantReview from './pages/MerchantReview';
import NewTransaction from './pages/NewTransaction';
import PaymentCheckout from './pages/PaymentCheckout';
import PaymentStatus from './pages/PaymentStatus';
import Settings from './pages/Settings';
import LoginPage from './pages/LoginPage';

const ACCESS_TOKEN_KEY = 'recoverx_access_token';

function ProtectedLayout({ authenticated, onLogout }) {
  const [collapsed, setCollapsed] = useState(false);
  if (!authenticated) return <Navigate to="/login" replace />;

  return (
    <div className={`app-layout ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar collapsed={collapsed} setCollapsed={setCollapsed} onLogout={onLogout} />
      <main className="main-content"><Outlet /></main>
    </div>
  );
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(localStorage.getItem(ACCESS_TOKEN_KEY)));
  const [checkingSession, setCheckingSession] = useState(Boolean(localStorage.getItem(ACCESS_TOKEN_KEY)));
  const logout = () => { api.logout(); setAuthenticated(false); };

  useEffect(() => {
    const handleAuthenticationRequired = () => setAuthenticated(false);
    window.addEventListener('recoverx:authentication-required', handleAuthenticationRequired);
    return () => window.removeEventListener('recoverx:authentication-required', handleAuthenticationRequired);
  }, []);

  useEffect(() => {
    if (!authenticated) { setCheckingSession(false); return; }
    let active = true;
    api.getMe()
      .then((user) => { if (active) localStorage.setItem('recoverx_user', JSON.stringify(user)); })
      .catch(() => { if (active) setAuthenticated(false); })
      .finally(() => { if (active) setCheckingSession(false); });
    return () => { active = false; };
  }, [authenticated]);

  if (checkingSession) return <div className="auth-loading">Checking your secure session…</div>;

  return (
    <Routes>
      <Route path="/login" element={authenticated ? <Navigate to="/dashboard" replace /> : <LoginPage onAuthenticated={() => setAuthenticated(true)} />} />
      <Route element={<ProtectedLayout authenticated={authenticated} onLogout={logout} />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/exceptions" element={<RevenueExceptions />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/payments" element={<PaymentsList />} />
        <Route path="/needs-attention" element={<NeedsAttention />} />
        <Route path="/disputes" element={<Disputes />} />
        <Route path="/settlements" element={<Settlements />} />
        <Route path="/cases" element={<NeedsAttention />} />
        <Route path="/cases/:caseId" element={<CaseDetails />} />
        <Route path="/cases/:caseId/customer" element={<CustomerResolution />} />
        <Route path="/cases/:caseId/review" element={<MerchantReview />} />
        <Route path="/transactions/new" element={<NewTransaction />} />
        <Route path="/pay" element={<PaymentCheckout />} />
        <Route path="/payments/:orderId/status" element={<PaymentStatus />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to={authenticated ? '/dashboard' : '/login'} replace />} />
    </Routes>
  );
}