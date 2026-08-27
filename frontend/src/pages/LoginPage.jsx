import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';

export default function LoginPage({ onAuthenticated }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const submit = async (event) => {
    event.preventDefault(); setError(''); setSubmitting(true);
    try { await api.login({ email: email.trim(), password }); onAuthenticated(); navigate('/dashboard', { replace: true }); }
    catch (requestError) { setError(requestError.message || 'Unable to sign in. Please try again.'); }
    finally { setSubmitting(false); }
  };
  return <main className="login-page"><section className="login-card" aria-labelledby="login-title"><div className="login-brand"><span>RX</span><div><strong>RecoverX</strong><small>Revenue recovery operations</small></div></div><h1 id="login-title">Sign in to RecoverX</h1><p className="login-intro">Use your merchant account to access recovery operations and Razorpay test checkout.</p>{error && <div className="login-error" role="alert">{error}</div>}<form onSubmit={submit}><label htmlFor="email">Email address</label><input id="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required minLength="3" disabled={submitting} /><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength="6" disabled={submitting} /><button className="btn btn-primary login-submit" type="submit" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}</button></form><p className="auth-switch">Don&apos;t have an account? <Link to="/signup">Create account</Link></p></section></main>;
}