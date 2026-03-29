import { test, expect, type Page } from '@playwright/test';

const EMAIL = process.env.HELIOS_LOGIN_EMAIL || 'ci-admin@example.com';
const PASSWORD = process.env.HELIOS_LOGIN_PASSWORD || 'CITestPass1!';
const SEEDED_VENDOR_NAME = process.env.HELIOS_SEEDED_VENDOR_NAME || 'CI SEEDED EXPORT CASE';
const SEEDED_VENDOR_PATTERN = new RegExp(SEEDED_VENDOR_NAME, 'i');

type AuthSession = {
  token: string;
  user: {
    email: string;
    name: string;
    role: string;
  };
};

let authSession: AuthSession;

async function installSession(page: Page) {
  await page.addInitScript((session: AuthSession) => {
    sessionStorage.setItem('helios_token', session.token);
    sessionStorage.setItem('helios_user', JSON.stringify(session.user));
  }, authSession);
}

test.describe('Helios E2E Smoke Tests', () => {
  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    try {
      const response = await page.request.post('/api/auth/login', {
        data: { email: EMAIL, password: PASSWORD },
      });

      expect(response.status()).toBe(200);
      const data = await response.json();
      authSession = {
        token: data.token,
        user: data.user,
      };
      expect(authSession.token).toBeTruthy();
      expect(authSession.user.email).toBe(EMAIL);
    } finally {
      await page.close();
    }
  });

  test('unauthenticated users land on the sign-in screen', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Vendor intelligence and assurance')).toBeVisible();
    await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
  });

  test.describe('authenticated shell', () => {
    test.beforeEach(async ({ page }) => {
      await installSession(page);
      await page.goto('/');
      await page.waitForLoadState('networkidle');
    });

    test('renders the operator shell and live connection state', async ({ page }) => {
      await expect(page.getByRole('button', { name: 'Dashboard' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Helios' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Portfolio' })).toBeVisible();
      await expect(page.getByText('System live')).toBeVisible();
    });

    test('shows the seeded case in portfolio view', async ({ page }) => {
      await page.getByRole('button', { name: 'Portfolio' }).click();
      await page.getByRole('button', { name: 'Export' }).click({ force: true });
      await expect(page.getByRole('heading', { name: 'Cases' })).toBeVisible();
      await expect(page.getByText(SEEDED_VENDOR_PATTERN)).toBeVisible();
    });

    test('opens the seeded case and exposes the export workflow', async ({ page }) => {
      await page.getByRole('button', { name: 'Portfolio' }).click();
      await page.getByRole('button', { name: 'Export' }).click({ force: true });
      const seededRow = page.locator('tr').filter({ hasText: SEEDED_VENDOR_PATTERN }).first();
      await expect(seededRow).toBeVisible();
      await seededRow.click();

      await expect(page.getByRole('button', { name: /Run Authorization/i }).first()).toBeVisible();
    });
  });
});
