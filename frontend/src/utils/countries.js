/**
 * Centralized Country and Currency registry for RecoverX.
 */

export const COUNTRIES = [
  { code: 'IN', name: 'India', defaultCurrency: 'INR', flag: '🇮🇳' },
  { code: 'US', name: 'United States', defaultCurrency: 'USD', flag: '🇺🇸' },
  { code: 'CA', name: 'Canada', defaultCurrency: 'CAD', flag: '🇨🇦' },
  { code: 'GB', name: 'United Kingdom', defaultCurrency: 'GBP', flag: '🇬🇧' },
  { code: 'DE', name: 'Germany', defaultCurrency: 'EUR', flag: '🇩🇪' },
  { code: 'FR', name: 'France', defaultCurrency: 'EUR', flag: '🇫🇷' },
  { code: 'IT', name: 'Italy', defaultCurrency: 'EUR', flag: '🇮🇹' },
  { code: 'ES', name: 'Spain', defaultCurrency: 'EUR', flag: '🇪🇸' },
  { code: 'NL', name: 'Netherlands', defaultCurrency: 'EUR', flag: '🇳🇱' },
  { code: 'JP', name: 'Japan', defaultCurrency: 'JPY', flag: '🇯🇵' },
  { code: 'CN', name: 'China', defaultCurrency: 'CNY', flag: '🇨🇳' },
  { code: 'SG', name: 'Singapore', defaultCurrency: 'SGD', flag: '🇸🇬' },
  { code: 'AU', name: 'Australia', defaultCurrency: 'AUD', flag: '🇦🇺' },
  { code: 'NZ', name: 'New Zealand', defaultCurrency: 'NZD', flag: '🇳🇿' },
  { code: 'CH', name: 'Switzerland', defaultCurrency: 'CHF', flag: '🇨🇭' },
  { code: 'AE', name: 'United Arab Emirates', defaultCurrency: 'AED', flag: '🇦🇪' },
  { code: 'SA', name: 'Saudi Arabia', defaultCurrency: 'SAR', flag: '🇸🇦' },
  { code: 'HK', name: 'Hong Kong', defaultCurrency: 'HKD', flag: '🇭🇰' },
];

export const CURRENCIES = [
  { code: 'INR', name: 'INR — Indian Rupee (₹)', symbol: '₹' },
  { code: 'USD', name: 'USD — US Dollar ($)', symbol: '$' },
  { code: 'EUR', name: 'EUR — Euro (€)', symbol: '€' },
  { code: 'GBP', name: 'GBP — British Pound (£)', symbol: '£' },
  { code: 'CAD', name: 'CAD — Canadian Dollar (C$)', symbol: 'C$' },
  { code: 'JPY', name: 'JPY — Japanese Yen (¥)', symbol: '¥' },
  { code: 'CNY', name: 'CNY — Chinese Yuan (¥)', symbol: '¥' },
  { code: 'SGD', name: 'SGD — Singapore Dollar (S$)', symbol: 'S$' },
  { code: 'AUD', name: 'AUD — Australian Dollar (A$)', symbol: 'A$' },
  { code: 'NZD', name: 'NZD — New Zealand Dollar (NZ$)', symbol: 'NZ$' },
  { code: 'CHF', name: 'CHF — Swiss Franc (CHF)', symbol: 'CHF' },
  { code: 'AED', name: 'AED — UAE Dirham (AED)', symbol: 'AED' },
  { code: 'SAR', name: 'SAR — Saudi Riyal (SAR)', symbol: 'SAR' },
  { code: 'HKD', name: 'HKD — Hong Kong Dollar (HK$)', symbol: 'HK$' },
];

export const COUNTRY_MAP = COUNTRIES.reduce((acc, item) => {
  acc[item.code] = item;
  return acc;
}, {});

export function getDefaultCurrencyForCountry(countryCode) {
  const c = COUNTRY_MAP[(countryCode || '').toUpperCase().trim()];
  return c ? c.defaultCurrency : 'USD';
}

export function getCountryDetails(countryCode) {
  return COUNTRY_MAP[(countryCode || '').toUpperCase().trim()] || null;
}
