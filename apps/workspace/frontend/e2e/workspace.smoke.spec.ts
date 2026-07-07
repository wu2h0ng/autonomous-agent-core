import { test, expect } from '@playwright/test';

test.describe('Workspace shell', () => {
  test('home page shows query workspace', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Data Agent OS')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Business Query' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Submit Query' })).toBeVisible();
  });

  test('primary navigation links are visible', async ({ page }) => {
    await page.goto('/');
    for (const label of ['Runs', 'Approvals', 'Knowledge', 'Outcomes']) {
      await expect(page.getByRole('link', { name: label })).toBeVisible();
    }
  });

  test('runs page loads', async ({ page }) => {
    await page.goto('/runs');
    await expect(page.getByRole('heading', { name: 'Recent Runs' })).toBeVisible();
  });

  test('approvals page loads', async ({ page }) => {
    await page.goto('/approvals');
    await expect(page.getByRole('heading', { name: /Approvals/i })).toBeVisible();
  });
});
