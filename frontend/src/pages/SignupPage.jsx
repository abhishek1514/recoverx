import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../services/api';

export default function SignupPage({ onAuthenticated }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ business_name: '', full_name: '', email: '', password: '', confirm_password: '', country_code: 'IN', currency: 'INR' });
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const update = (event) => setForm((current) => ({ ...current, [event.target.name]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setError('');
    if (form.password !== form.confirm_password) { setError('Passwords do not match.'); return; }
    setSubmitting(true);
    try {
      await api.signup(form);
      onAuthenticated();
      navigate('/dashboard', { replace: true });
    } catch (requestError) {
      setError(requestError.message || 'Unable to create your account. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="login-page"><section className="login-card" aria-labelledby="signup-title"><div className="login-brand"><span>RX</span><div><strong>RecoverX</strong><small>Revenue recovery operations</small></div></div><h1 id="signup-title">Create your merchant account</h1><p className="login-intro">Set up your merchant workspace and start protecting revenue.</p>{error && <div className="login-error" role="alert">{error}</div>}<form onSubmit={submit}><label htmlFor="business_name">Business / Merchant Name</label><input id="business_name" name="business_name" value={form.business_name} onChange={update} required disabled={submitting} autoComplete="organization" /><label htmlFor="full_name">Full Name</label><input id="full_name" name="full_name" value={form.full_name} onChange={update} required disabled={submitting} autoComplete="name" /><label htmlFor="email">Email Address</label><input id="email" name="email" type="email" value={form.email} onChange={update} required disabled={submitting} autoComplete="email" /><label htmlFor="password">Password</label><input id="password" name="password" type="password" value={form.password} onChange={update} required minLength="8" disabled={submitting} autoComplete="new-password" /><label htmlFor="confirm_password">Confirm Password</label><input id="confirm_password" name="confirm_password" type="password" value={form.confirm_password} onChange={update} required minLength="8" disabled={submitting} autoComplete="new-password" /><button className="btn btn-primary login-submit" type="submit" disabled={submitting}>{submitting ? 'Creating account...' : 'Create account'}</button></form><p className="auth-switch">Already have an account? <Link to="/login">Sign in</Link></p></section></main>;
}