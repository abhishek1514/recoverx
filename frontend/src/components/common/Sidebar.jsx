import React, { useState } from 'react';
import { NavLink, Link } from 'react-router-dom';

export default function Sidebar({ collapsed, setCollapsed }) {
  const [devToolsOpen, setDevToolsOpen] = useState(false);

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      {/* Brand & Toggle Header */}
      <div className="sidebar-header">
        <Link to="/exceptions" className="sidebar-brand">
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
          to="/exceptions"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Revenue Exceptions"
        >
          <span className="nav-icon">🚨</span>
          {!collapsed && <span className="nav-label">Revenue Exceptions</span>}
        </NavLink>

        <NavLink
          to="/dashboard"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Dashboard"
        >
          <span className="nav-icon">🏠</span>
          {!collapsed && <span className="nav-label">Dashboard</span>}
        </NavLink>

        <NavLink
          to="/disputes"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Disputes & Chargebacks"
        >
          <span className="nav-icon">⚖️</span>
          {!collapsed && <span className="nav-label">Disputes & Chargebacks</span>}
        </NavLink>

        <NavLink
          to="/settlements"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Settlements & Recon"
        >
          <span className="nav-icon">🏦</span>
          {!collapsed && <span className="nav-label">Settlements & Recon</span>}
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
          to="/transactions/new"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Simulate Transaction"
        >
          <span className="nav-icon">⚡</span>
          {!collapsed && <span className="nav-label">Simulate Transaction</span>}
        </NavLink>

        <NavLink
          to="/pay"
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          title="Razorpay Checkout"
        >
          <span className="nav-icon">🛒</span>
          {!collapsed && <span className="nav-label">Razorpay Checkout</span>}
        </NavLink>

        {/* Developer / Operations Tools Toggle */}
        <div className="nav-divider" />
        <div className="nav-section-label">{!collapsed && 'OPERATIONS'}</div>

        <button
          type="button"
          className="sidebar-link dev-tools-toggle"
          onClick={() => setDevToolsOpen(!devToolsOpen)}
          title="Operational Tools"
        >
          <span className="nav-icon">⚙️</span>
          {!collapsed && (
            <>
              <span className="nav-label">Operations Tools</span>
              <span className="toggle-chevron">{devToolsOpen ? '▾' : '▸'}</span>
            </>
          )}
        </button>

        {devToolsOpen && !collapsed && (
          <div className="dev-tools-submenu">
            <NavLink
              to="/settings"
              className={({ isActive }) => `submenu-link ${isActive ? 'active' : ''}`}
            >
              System Health & Diagnostics
            </NavLink>
          </div>
        )}
      </nav>

      {/* Footer Info */}
      <div className="sidebar-footer">
        {!collapsed ? (
          <div className="footer-status">
            <span className="status-indicator online" />
            <span className="status-text">Razorpay Test Mode Active</span>
          </div>
        ) : (
          <span className="status-indicator online dot-only" title="Online" />
        )}
      </div>
    </aside>
  );
}
