/**
 * Currency-aware number and monetary formatting utility.
 */

export function formatCurrency(amount, currency = 'INR', exact = false) {
  const num = Number(amount) || 0;
  const curr = (currency || 'INR').toUpperCase().trim();

  if (exact) {
    if (curr === 'INR') return `₹${num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (curr === 'USD') return `$${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (curr === 'EUR') return `€${num.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (curr === 'GBP') return `£${num.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    return `${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${curr}`;
  }

  if (curr === 'INR') {
    if (num >= 10000000) return `₹${(num / 10000000).toFixed(2)}Cr`;
    if (num >= 100000) return `₹${(num / 100000).toFixed(2)}L`;
    return `₹${num.toLocaleString('en-IN')}`;
  }

  if (curr === 'USD') {
    if (num >= 1000000000) return `$${(num / 1000000000).toFixed(2)}B`;
    if (num >= 1000000) return `$${(num / 1000000).toFixed(2)}M`;
    if (num >= 10000) return `$${(num / 1000).toFixed(1)}K`;
    return `$${num.toLocaleString('en-US')}`;
  }

  if (curr === 'EUR') {
    if (num >= 1000000000) return `€${(num / 1000000000).toFixed(2)}B`;
    if (num >= 1000000) return `€${(num / 1000000).toFixed(2)}M`;
    if (num >= 10000) return `€${(num / 1000).toFixed(1)}K`;
    return `€${num.toLocaleString('de-DE')}`;
  }

  if (curr === 'GBP') {
    if (num >= 1000000000) return `£${(num / 1000000000).toFixed(2)}B`;
    if (num >= 1000000) return `£${(num / 1000000).toFixed(2)}M`;
    if (num >= 10000) return `£${(num / 1000).toFixed(1)}K`;
    return `£${num.toLocaleString('en-GB')}`;
  }

  if (num >= 1000000000) return `${(num / 1000000000).toFixed(2)}B ${curr}`;
  if (num >= 1000000) return `${(num / 1000000).toFixed(2)}M ${curr}`;
  return `${num.toLocaleString()} ${curr}`;
}

export function formatINR(val) {
  return formatCurrency(val, 'INR');
}
