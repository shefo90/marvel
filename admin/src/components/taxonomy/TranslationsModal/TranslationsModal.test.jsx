import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';

import TranslationsModal from './TranslationsModal.jsx';

const TRANSLATIONS = [
  {
    locale: 'en',
    title: 'Sandals',
    slug: 'sandals',
    description: 'Open shoes',
    meta_description: 'Buy sandals',
    is_published: true,
  },
  {
    locale: 'ar',
    title: 'صنادل',
    slug: 'صنادل',
    description: 'حذاء مفتوح',
    meta_description: 'اشتر صنادل',
    is_published: false,
  },
];

function renderModal(props = {}) {
  return render(
    <TranslationsModal
      open
      name="Sandals"
      translations={TRANSLATIONS}
      onSave={vi.fn()}
      onClose={vi.fn()}
      {...props}
    />,
  );
}

it('opens on the first locale and shows what is already written', async () => {
  renderModal();

  expect(await screen.findByLabelText('Title')).toHaveValue('Sandals');
  expect(screen.getByLabelText('Slug')).toHaveValue('sandals');
});

it('swaps every field when the language changes', async () => {
  // The trap ContentTab already documents: leave the previous locale's values
  // in the form and saving writes English into Arabic.
  const user = userEvent.setup();
  renderModal();
  await screen.findByLabelText('Title');

  // The hidden input carries pointer-events: none; a person clicks the label.
  await user.click(screen.getByText('Arabic'));

  await waitFor(() => expect(screen.getByLabelText('Title')).toHaveValue('صنادل'));
  expect(screen.getByLabelText('Description')).toHaveValue('حذاء مفتوح');
});

it('renders Arabic right to left', async () => {
  const user = userEvent.setup();
  renderModal();
  await screen.findByLabelText('Title');

  // The hidden input carries pointer-events: none; a person clicks the label.
  await user.click(screen.getByText('Arabic'));

  await waitFor(() => expect(screen.getByLabelText('Title')).toHaveAttribute('dir', 'rtl'));
});

it('saves against the language that is showing', async () => {
  const onSave = vi.fn();
  const user = userEvent.setup();
  renderModal({ onSave });
  await screen.findByLabelText('Title');

  // The hidden input carries pointer-events: none; a person clicks the label.
  await user.click(screen.getByText('Arabic'));
  await waitFor(() => expect(screen.getByLabelText('Title')).toHaveValue('صنادل'));
  await user.click(screen.getByRole('button', { name: 'Save Arabic' }));

  await waitFor(() => expect(onSave).toHaveBeenCalled());
  const [locale, values] = onSave.mock.calls[0];
  expect(locale).toBe('ar');
  expect(values.title).toBe('صنادل');
});

it('names the language in the save button, never just Save', async () => {
  // Per-language publishing is the locked decision: English can be live while
  // Arabic is unfinished, so every action has to say which one it affects.
  renderModal();

  expect(await screen.findByRole('button', { name: 'Save English' })).toBeInTheDocument();
});

it('shows whether this language is live', async () => {
  const user = userEvent.setup();
  renderModal();

  expect(await screen.findByText('published')).toBeInTheDocument();

  // The hidden input carries pointer-events: none; a person clicks the label.
  await user.click(screen.getByText('Arabic'));
  expect(await screen.findByText('draft')).toBeInTheDocument();
});

it('says when a language has not been started', async () => {
  const user = userEvent.setup();
  renderModal({ translations: [TRANSLATIONS[0]] });
  await screen.findByLabelText('Title');

  // The hidden input carries pointer-events: none; a person clicks the label.
  await user.click(screen.getByText('Arabic'));

  expect(await screen.findByText('not started')).toBeInTheDocument();
  expect(screen.getByLabelText('Title')).toHaveValue('');
});

it('surfaces a save failure instead of closing', async () => {
  renderModal({ error: { message: 'slug is already taken' } });

  expect(await screen.findByText('slug is already taken')).toBeInTheDocument();
});
