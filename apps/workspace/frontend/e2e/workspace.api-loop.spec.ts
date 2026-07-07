import { test, expect } from '@playwright/test';
import {
  MOCK_APPROVAL_ID,
  MOCK_TRACE_ID,
  mockApprovalDetail,
  mockApprovalExecuteResponse,
  mockOutcomeResponse,
  mockRunResponse,
  mockTraceResponse,
} from './fixtures/api-loop-mocks';

test.describe('Workspace live API closed loop (mocked)', () => {
  const isApiRequest = (resourceType: string) =>
    resourceType === 'fetch' || resourceType === 'xhr';

  test.beforeEach(async ({ page }) => {
    await page.route(/\/runs$/, async (route) => {
      if (!isApiRequest(route.request().resourceType())) {
        await route.continue();
        return;
      }
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockRunResponse),
        });
        return;
      }
      await route.continue();
    });

    await page.route(new RegExp(`/approvals/${MOCK_APPROVAL_ID}/execute$`), async (route) => {
      if (!isApiRequest(route.request().resourceType())) {
        await route.continue();
        return;
      }
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockApprovalExecuteResponse),
        });
        return;
      }
      await route.continue();
    });

    await page.route(new RegExp(`/approvals/${MOCK_APPROVAL_ID}$`), async (route) => {
      if (!isApiRequest(route.request().resourceType())) {
        await route.continue();
        return;
      }
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockApprovalDetail),
        });
        return;
      }
      await route.continue();
    });

    await page.route(/\/outcomes$/, async (route) => {
      if (!isApiRequest(route.request().resourceType())) {
        await route.continue();
        return;
      }
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockOutcomeResponse),
        });
        return;
      }
      await route.continue();
    });

    await page.route(new RegExp(`/traces/${MOCK_TRACE_ID}$`), async (route) => {
      if (!isApiRequest(route.request().resourceType())) {
        await route.continue();
        return;
      }
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockTraceResponse),
        });
        return;
      }
      await route.continue();
    });
  });

  test('query → evidence → outcome feedback', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'GMV last week' }).click();

    await expect(page.getByText('GMV totaled 128,800 CNY')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Action Proposal' })).toBeVisible();
    await expect(page.getByText('awaiting_approval')).toBeVisible();

    await page.getByRole('button', { name: 'Useful' }).click();
    await page.getByRole('button', { name: 'Submit Feedback' }).click();
    await expect(page.getByText('Feedback submitted. Thank you.')).toBeVisible({
      timeout: 10_000,
    });
  });

  test('approvals detail → execute with operator key', async ({ page }) => {
    await page.goto(`/approvals/${MOCK_APPROVAL_ID}`);

    await expect(page.getByRole('heading', { name: 'Approval Detail' })).toBeVisible();
    await expect(page.getByText(MOCK_APPROVAL_ID)).toBeVisible();
    await expect(page.getByText('pending')).toBeVisible();

    await page.getByRole('button', { name: 'Execute' }).click();

    await expect(page.getByText(/Operation trace: op-trace-e2e-mock-001/)).toBeVisible({
      timeout: 10_000,
    });
  });

  test('trace link from run result navigates', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'GMV last week' }).click();
    await expect(page.getByRole('link', { name: /View full trace/i })).toBeVisible();
    await page.getByRole('link', { name: /View full trace/i }).click();
    await expect(page).toHaveURL(new RegExp(`/trace/${MOCK_TRACE_ID}`));
    await expect(page.getByRole('heading', { name: 'Trace Detail' })).toBeVisible();
  });
});
