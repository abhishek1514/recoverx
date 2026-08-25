import React, { useState } from 'react';
import { NavLink, Link } from 'react-router-dom';

export default function Sidebar({ collapsed, setCollapsed }) {
  const [devToolsOpen, setDevToolsOpen] = useState(false);

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      {/* Brand & Toggle Header */}
      <div className="sidebar-header">
        <Link to="/dashboard" className="sidebar-brand">
          <div className="brand-logo">RX</div>
          {!collapsed && (
            <div className="brand-text">
              <span className="brand-name">RecoverX</span>
              <span className="brand-tag">AI Recovery</span>
            </div>
          )}
        </Link>
        <button
          type="button"
          className="sidebar-toggle"
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? '→' : '←'}
        </button>
      </div>

      {/* Main Navigation Menu */}
      <nav className="sidebar-nav">
        <div className="nav-section-label">{!collapsed && 'RECOVERY AGENT'}</div>

        <NavLink
          to="/dashboard"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Dashboard"
        >
          <span className="nav-icon">🏠</span>
          {!collapsed && <span className="nav-label">Dashboard</span>}
        </NavLink>

        <NavLink
          to="/payments"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Payments"
        >
          <span className="nav-icon">💳</span>
          {!collapsed && <span className="nav-label">Payments</span>}
        </NavLink>

        <NavLink
          to="/needs-attention"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Needs Attention"
        >
          <span className="nav-icon">🔴</span>
          {!collapsed && <span className="nav-label">Needs Attention</span>}
        </NavLink>

        <NavLink
          to="/pay"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Test Payment"
        >
          <span className="nav-icon">🧪</span>
          {!collapsed && <span className="nav-label">Test Payment</span>}
        </NavLink>

        <div className="sidebar-divider" />

        <div className="nav-section-label">{!collapsed && 'PREFERENCES'}</div>

        <NavLink
          to="/settings"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Settings"
        >
          <span className="nav-icon">⚙️</span>
          {!collapsed && <span className="nav-label">Settings</span>}
        </NavLink>
      </nav>

      {/* Bottom Developer Tools Box */}
      <div className="sidebar-footer">
        {!collapsed ? (
          <div className="dev-tools-box">
            <button
              type="button"
              className="dev-tools-toggle"
              onClick={() => setDevToolsOpen(!devToolsOpen)}
            >
              <span>🛠️ Developer / Test Tools</span>
              <span style={{ fontSize: '0.7rem' }}>{devToolsOpen ? '▲' : '▼'}</span>
            </button>
            {devToolsOpen && (
              <div className="dev-tools-content">
                <p className="dev-tools-desc">
                  Simulation tools for manual high-value & cross-border test scenarios.
                </p>
                <Link to="/transactions/new" className="dev-tools-link">
                  + Manual Test Analyzer
                </Link>
              </div>
            )}
          </div>
        ) : (
          <Link
            to="/transactions/new"
            className="sidebar-link dev-icon-link"
            title="Developer / Test Simulation Tools"
          >
            <span className="nav-icon">🛠️</span>
          </Link>
        )}
      </div>
    </aside>
  );
}

