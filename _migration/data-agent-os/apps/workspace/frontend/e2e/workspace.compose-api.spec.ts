import { test, expect } from '@playwright/test';

const composeE2e = process.env.COMPOSE_E2E === '1';
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

test.describe('Workspace compose live API', () => {
  test.skip(!composeE2e, 'Set COMPOSE_E2E=1 with API stack at NEXT_PUBLIC_API_URL');

  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      try {
        const response = await fetch(`${apiUrl}/health`);
        if (response.ok) {
          return;
        }
      } catch {
        // API stack still starting
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error(`API health check failed for ${apiUrl}`);
  });

  test('GMV preset returns evidence-backed result', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'GMV last week' }).click();

    await expect(page.getByRole('heading', { name: 'GMV metric contract' })).toBeVisible({
      timeout: 60_000,
    });
  });

  test('run report page loads trace and report from live API', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'GMV last week' }).click();
    await expect(page.getByRole('heading', { name: 'GMV metric contract' })).toBeVisible({
      timeout: 60_000,
    });

    await page.locator('aside a[href^="/runs/"]').first().click();
    await expect(page.getByRole('heading', { name: 'Run Report' })).toBeVisible();
    await expect(page.getByText('Execution Trace')).toBeVisible({
      timeout: 30_000,
    });
  });

  test('knowledge catalog loads from live API', async ({ page }) => {
    await page.goto('/knowledge');
    await expect(page.getByRole('heading', { name: 'Knowledge Assets' })).toBeVisible();
    await expect(page.getByText('Failed to load knowledge assets')).not.toBeVisible();
  });
});
