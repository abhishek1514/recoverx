import React from 'react';
import { Link, useLocation } from 'react-router-dom';

export default function Navbar() {
  const location = useLocation();

  return (
    <header className="navbar">
      <div className="nav-inner">
        <div className="brand-section">
          <Link to="/dashboard" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div className="brand-logo">RX</div>
            <div className="brand-title-wrap">
              <span className="brand-name">
                RecoverX
              </span>
              <span className="brand-subtitle">Protect revenue before settlement gets delayed.</span>
            </div>
          </Link>
        </div>

        <nav className="nav-links" style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          <Link
            to="/dashboard"
            className={`nav-link ${location.pathname === '/' || location.pathname === '/dashboard' ? 'active' : ''}`}
          >
            Dashboard
          </Link>
          <Link
            to="/cases"
            className={`nav-link ${location.pathname.startsWith('/cases') ? 'active' : ''}`}
          >
            Payments
          </Link>
          <Link
            to="/pay"
            className={`nav-link ${location.pathname === '/pay' || location.pathname.startsWith('/payments') ? 'active' : ''}`}
            style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}
          >
            <span style={{ fontSize: '0.9rem' }}>💳</span> Make Test Payment
          </Link>
          <Link
            to="/transactions/new"
            className="nav-link"
            style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginLeft: '0.5rem', opacity: 0.7 }}
            title="Developer & Test Simulation Tools"
          >
            ⚙️ Developer Tools
          </Link>
        </nav>
      </div>
    </header>
  );
}


