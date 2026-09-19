import { test, expect } from '@playwright/test';

for (const width of [1280, 375]) {
  test(`frontier reveals only recorded discoveries and supports selection at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/tests/e2e/fixtures/frontier.html');
    const map = page.getByRole('group', { name: 'Surrounding map' });
    await expect(map.getByRole('button')).toHaveCount(9);
    await map.getByRole('button', { name: /Northstar/ }).click();
    await expect(page.getByRole('heading', { name: 'Northstar', exact: true })).toBeVisible();
    await expect(page.getByText('established infrastructure · Space for 1000 residents')).toBeVisible();
    const unknown = map.getByRole('button', { name: /Site 1 / });
    await unknown.focus();
    await page.keyboard.press('Enter');
    await expect(unknown).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('Terrain and resources will be revealed by a completed expedition.')).toBeVisible();
    await expect(page.getByText('established infrastructure · Space for 1000 residents')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({ path: `../tmp/frontier-${width}.png`, fullPage: true });
  });
}
