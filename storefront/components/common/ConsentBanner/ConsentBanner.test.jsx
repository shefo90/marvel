import { fireEvent, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it } from 'vitest';

import { renderAt } from '../../../test/render.jsx';
import ConsentBanner from './ConsentBanner.jsx';

beforeEach(() => {
  window.dataLayer = [];
  window.gtag = function gtag() {
    window.dataLayer.push(arguments);
  };
});
afterEach(() => {
  delete window.dataLayer;
  delete window.gtag;
  document.cookie = 'consent=; path=/; max-age=0';
});

it('asks for a choice when none has been stored', async () => {
  renderAt(<ConsentBanner />);

  expect(await screen.findByRole('button', { name: 'Accept' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
});

it('stays out of the page once a choice has been stored', () => {
  document.cookie = 'consent=granted; path=/';
  renderAt(<ConsentBanner />);

  expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument();
});

it('grants analytics consent and dismisses itself when the shopper accepts', async () => {
  renderAt(<ConsentBanner />);
  fireEvent.click(await screen.findByRole('button', { name: 'Accept' }));

  expect(document.cookie).toContain('consent=granted');
  expect(Array.from(window.dataLayer.at(-1))).toEqual([
    'consent',
    'update',
    {
      ad_storage: 'granted',
      ad_user_data: 'granted',
      ad_personalization: 'granted',
      analytics_storage: 'granted',
    },
  ]);
  expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument();
});

it('records a refusal without granting anything when the shopper rejects', async () => {
  renderAt(<ConsentBanner />);
  fireEvent.click(await screen.findByRole('button', { name: 'Reject' }));

  expect(document.cookie).toContain('consent=denied');
  expect(Array.from(window.dataLayer.at(-1))).toEqual([
    'consent',
    'update',
    {
      ad_storage: 'denied',
      ad_user_data: 'denied',
      ad_personalization: 'denied',
      analytics_storage: 'denied',
    },
  ]);
  expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument();
});

it('speaks Arabic when the page is Arabic', async () => {
  renderAt(<ConsentBanner />, { locale: 'ar', pathname: '/ar' });

  expect(await screen.findByRole('button', { name: 'أوافق' })).toBeInTheDocument();
});

it('points its privacy link at the current language', async () => {
  renderAt(<ConsentBanner />, { locale: 'ar', pathname: '/ar' });

  const link = await screen.findByRole('link', { name: 'الخصوصية' });
  expect(link).toHaveAttribute('href', '/ar/privacy');
});
