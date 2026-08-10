import { expect, test, type Locator } from "@playwright/test";

async function renderedContrast(locator: Locator) {
  return locator.evaluate(element => {
    const parse = (value: string) => {
      const parts = value.match(/[\d.]+/g)?.map(Number) || [];
      return { r: parts[0] || 0, g: parts[1] || 0, b: parts[2] || 0, a: parts[3] ?? 1 };
    };
    const composite = (
      front: { r: number; g: number; b: number; a: number },
      back: { r: number; g: number; b: number; a: number },
    ) => {
      const a = front.a + back.a * (1 - front.a);
      if (!a) return { r: 0, g: 0, b: 0, a: 0 };
      return {
        r: (front.r * front.a + back.r * back.a * (1 - front.a)) / a,
        g: (front.g * front.a + back.g * back.a * (1 - front.a)) / a,
        b: (front.b * front.a + back.b * back.a * (1 - front.a)) / a,
        a,
      };
    };
    let background = { r: 0, g: 0, b: 0, a: 0 };
    let current: Element | null = element;
    let opacity = 1;
    while (current) {
      const style = getComputedStyle(current);
      background = composite(background, parse(style.backgroundColor));
      opacity *= Number(style.opacity || 1);
      current = current.parentElement;
    }
    background = composite(background, { r: 255, g: 255, b: 255, a: 1 });
    const text = parse(getComputedStyle(element).color);
    const foreground = composite({ ...text, a: text.a * opacity }, background);
    const luminance = (color: { r: number; g: number; b: number }) => {
      const channels = [color.r, color.g, color.b].map(channel => {
        const value = channel / 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const values = [luminance(foreground), luminance(background)].sort((left, right) => right - left);
    return (values[0] + 0.05) / (values[1] + 0.05);
  });
}

test.beforeEach(async ({ page }) => {
  await page.goto("/tests/e2e/fixtures/accessibility.html");
});

test("named status, ticker, and scroll areas use valid keyboard-accessible roles", async ({ page }) => {
  await expect(page.getByRole("heading", { level: 1, name: "Civic Observatory" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Live connection" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Live stock ticker" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Join", exact: true })).toHaveAttribute(
    "href", "/join/local-sandbox",
  );

  for (const name of [
    "Firms and exchange records",
    "Published news stories",
    "Stored conversations",
    "Simulation event spine",
  ]) {
    const region = page.getByRole("region", { name });
    await expect(region).toBeVisible();
    await expect(region).toHaveAttribute("tabindex", "0");
  }
});

test("small Observatory controls retain WCAG AA text contrast", async ({ page }) => {
  const targets: Array<[string, Locator]> = [
    ["partial-day warning", page.getByText(/partial day 2/i)],
    ["active product link", page.getByRole("link", { name: "Observatory", exact: true })],
    ["inactive product link", page.getByRole("link", { name: "World OS", exact: true })],
    ["active city count", page.getByRole("button", { name: /^All 2$/ }).locator("b")],
    ["inactive city count", page.getByRole("button", { name: /^Work 0$/ }).locator("b")],
    ["health agent initials", page.getByRole("button", { name: /^Dr\. Amara Osei,/ }).locator("span")],
    ["bank table heading", page.getByRole("columnheader", { name: "Bank" })],
  ];

  for (const [label, target] of targets) {
    await expect(target).toBeVisible();
    expect.soft(await renderedContrast(target), label).toBeGreaterThanOrEqual(4.5);
  }
});

test("print media hides application chrome but preserves semantic content headers", async ({ page }) => {
  await page.evaluate(() => {
    const shell = document.createElement("div");
    shell.className = "world-os-shell";
    shell.innerHTML = '<aside class="world-os-rail">Navigation</aside><header class="world-os-topbar">Toolbar</header>';
    document.body.appendChild(shell);
  });
  await page.emulateMedia({ media: "print" });

  await expect(page.locator(".civic-run-header")).toBeHidden();
  await expect(page.locator(".civic-city__mast")).toBeVisible();
  await expect(page.locator(".world-os-rail")).toBeHidden();
  await expect(page.locator(".world-os-shell")).toHaveCSS("display", "block");
});

test("native controls use the color scheme of their visual surface", async ({ page }) => {
  const schemes = await page.evaluate(() => {
    const shell = document.createElement("div");
    shell.className = "world-os-shell";
    const world = document.createElement("div");
    world.className = "civic-city civic-city--world-os";
    shell.appendChild(world);
    document.body.appendChild(shell);

    const result = {
      observatory: getComputedStyle(document.querySelector(".civic-observatory")!).colorScheme,
      shell: getComputedStyle(shell).colorScheme,
      world: getComputedStyle(world).colorScheme,
    };
    shell.remove();
    return result;
  });

  expect(schemes).toEqual({ observatory: "light", shell: "light", world: "dark" });
});
