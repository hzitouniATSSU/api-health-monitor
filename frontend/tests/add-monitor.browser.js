// Open the local Vite URL with playwright-cli, then run-code --filename=frontend/tests/add-monitor.browser.js.
async (page) => {
  const baseUrl = new URL(page.url());
  if (!["127.0.0.1", "localhost"].includes(baseUrl.hostname)) {
    throw new Error("Run this check against the local frontend only.");
  }

  function check(condition, message) {
    if (!condition) throw new Error(message);
  }

  const initialMonitor = {
    id: 1,
    name: "Example API",
    url: "https://example.com/health",
    current_status: "UP",
    last_checked_at: null,
    created_at: "2026-11-11T12:00:00Z",
  };
  let monitors = [initialMonitor];
  let submissions = [];
  let failSubmission = false;
  let releaseSubmission;
  let pendingSubmission;
  const consoleErrors = [];
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  // Intercept every API request and block external traffic, including production.
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) {
      const response = { headers: { "Access-Control-Allow-Origin": "*" } };
      if (request.method() === "POST" && url.pathname === "/api/monitors") {
        submissions.push(request.postDataJSON());
        if (pendingSubmission) await pendingSubmission;
        if (failSubmission) {
          await route.fulfill({ ...response, status: 500, json: {} });
          return;
        }
        const monitor = { ...initialMonitor, id: 2, ...request.postDataJSON() };
        monitors = [...monitors, monitor];
        await route.fulfill({ ...response, status: 201, json: monitor });
        return;
      }
      check(request.method() === "GET", `Unexpected API method: ${request.method()}`);
      let json;
      if (url.pathname === "/api/monitors") json = monitors;
      else if (url.pathname.endsWith("/stats")) {
        json = {
          total_checks: 18, successful_checks: 18, failed_checks: 0,
          uptime_percentage: 100, average_response_time_ms: 355,
        };
      } else if (/\/(checks|incidents)$/.test(url.pathname)) json = [];
      else throw new Error(`Unexpected API URL: ${url.pathname}`);
      await route.fulfill({ ...response, json });
      return;
    }
    if (url.origin === baseUrl.origin) await route.continue();
    else await route.abort();
  });

  const results = [];
  for (const width of [320, 393, 768, 1440]) {
    monitors = [initialMonitor];
    submissions = [];
    await page.setViewportSize({ width, height: width === 320 ? 568 : width === 393 ? 852 : 900 });
    await page.goto(baseUrl.origin);
    await page.locator(".monitor-card").waitFor();

    // Compare all dashboard styles and geometry with and without the form CSS.
    const unchanged = await page.evaluate(() => {
      const style = [...document.querySelectorAll("style")].find((element) =>
        element.dataset.viteDevId?.replaceAll("\\", "/").endsWith("/src/App.css"),
      );
      if (!style?.sheet) throw new Error("Expected Vite's App.css stylesheet");
      const fullCss = style.textContent;
      const originalCss = [...style.sheet.cssRules]
        .filter((rule) => !rule.cssText.includes(".add-form"))
        .map((rule) => rule.cssText).join("\n");
      function snapshot() {
        return JSON.stringify([...document.querySelectorAll(".page, .page *")].map((element) => {
          const computed = getComputedStyle(element);
          const bounds = element.getBoundingClientRect();
          return {
            styles: [...computed].map((property) => [property, computed.getPropertyValue(property)]),
            bounds: [bounds.x, bounds.y, bounds.width, bounds.height],
          };
        }));
      }
      const after = snapshot();
      style.textContent = originalCss;
      const before = snapshot();
      style.textContent = fullCss;
      return before === after;
    });
    check(unchanged, `${width}px: dashboard styles or geometry changed`);

    const opener = page.locator(".header button");
    const form = page.getByRole("form", { name: "Add monitor" });
    await opener.focus();
    await page.keyboard.press("Enter");
    await form.waitFor();
    const close = form.getByRole("button", { name: "Close add monitor form" });
    const name = form.getByRole("textbox", { name: "Name", exact: true });
    const url = form.getByRole("textbox", { name: "URL", exact: true });
    const cancel = form.getByRole("button", { name: "Cancel" });
    const submit = form.locator('button[type="submit"]');

    for (const control of [close, name, url, cancel, submit]) {
      await page.keyboard.press("Tab");
      check(await control.evaluate((element) => element === document.activeElement), `${width}px: incorrect tab order`);
      check(await control.evaluate((element) => {
        const style = getComputedStyle(element);
        return element.matches(":focus-visible") && style.outlineStyle === "solid" && parseFloat(style.outlineWidth) >= 2;
      }), `${width}px: missing visible keyboard focus`);
    }
    await page.keyboard.press("Shift+Tab");
    check(await cancel.evaluate((element) => element === document.activeElement), `${width}px: reverse tab failed`);

    const layout = await form.evaluate((element) => {
      const controls = [...element.querySelectorAll("input, button")];
      const formBounds = element.getBoundingClientRect();
      return {
        noOverflow: document.documentElement.scrollWidth <= innerWidth &&
          element.scrollWidth <= element.clientWidth && formBounds.left >= 0 && formBounds.right <= innerWidth,
        controlsFit: controls.every((control) => {
          const bounds = control.getBoundingClientRect();
          return bounds.left >= formBounds.left && bounds.right <= formBounds.right && bounds.height >= 44;
        }),
        inputFontSizes: [...element.querySelectorAll("input")].map((input) => getComputedStyle(input).fontSize),
        columns: getComputedStyle(element.querySelector(".form-fields")).gridTemplateColumns.split(" ").length,
      };
    });
    check(layout.noOverflow && layout.controlsFit, `${width}px: overflow or undersized controls`);
    check(layout.inputFontSizes.every((size) => size === "16px"), `${width}px: input text too small`);
    check(layout.columns === (width <= 700 ? 1 : 2), `${width}px: incorrect responsive layout`);

    const contrast = await form.evaluate((element) => {
      function ratio(first, second) {
        function luminance(color) {
          const channels = color.match(/[\d.]+/g).slice(0, 3).map((channel) => {
            const value = Number(channel) / 255;
            return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
          });
          return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
        }
        const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
        return (values[0] + 0.05) / (values[1] + 0.05);
      }
      const surface = getComputedStyle(element).backgroundColor;
      const input = element.querySelector("input");
      const inputStyle = getComputedStyle(input);
      const textRatios = [...element.querySelectorAll("h2, p, label, input, button")].map((control) => {
        const style = getComputedStyle(control);
        const background = style.backgroundColor === "rgba(0, 0, 0, 0)" ? surface : style.backgroundColor;
        return ratio(style.color, background);
      });
      textRatios.push(ratio(getComputedStyle(input, "::placeholder").color, inputStyle.backgroundColor));
      return {
        minimumText: Math.min(...textRatios),
        inputBorder: Math.min(ratio(inputStyle.borderColor, surface), ratio(inputStyle.borderColor, inputStyle.backgroundColor)),
        focusRing: ratio(getComputedStyle(element.querySelector(".secondary-button")).outlineColor, surface),
      };
    });
    check(contrast.minimumText >= 4.5 && contrast.inputBorder >= 3 && contrast.focusRing >= 3, `${width}px: insufficient contrast`);

    await submit.click();
    check(await name.evaluate((element) => element.validity.valueMissing && element === document.activeElement), "Required name validation failed");
    await name.fill("X".repeat(100));
    await url.fill(`https://example.com/${"x".repeat(2028)}`);
    check(await form.evaluate((element) => document.documentElement.scrollWidth <= innerWidth && element.scrollWidth <= element.clientWidth), "Long values caused overflow");
    await name.fill("Payments API");
    await url.fill("");
    await submit.click();
    check(await url.evaluate((element) => element.validity.valueMissing && element === document.activeElement), "Required URL validation failed");
    await url.fill("invalid-url");
    await submit.click();
    check(await url.evaluate((element) => element.validity.typeMismatch), "URL validation failed");
    check(submissions.length === 0, "Invalid form reached the API");
    check(await name.getAttribute("maxlength") === "100" && await url.getAttribute("maxlength") === "2048", "Input length constraints changed");

    await cancel.click();
    await form.waitFor({ state: "detached" });
    await opener.click();
    check(await name.inputValue() === "Payments API", "Cancel changed draft retention");
    await close.click();
    await form.waitFor({ state: "detached" });
    await opener.click();
    await name.fill("  Portfolio API  ");
    await url.fill("https://example.com/status");

    if (width === 393) {
      failSubmission = true;
      await submit.click();
      await form.getByRole("alert").waitFor();
      check(await form.getByRole("alert").textContent() === "Failed to create monitor", "Submission error missing");
      check(await name.inputValue() === "  Portfolio API  ", "Error lost the draft");
      failSubmission = false;
    }

    pendingSubmission = new Promise((resolve) => { releaseSubmission = resolve; });
    await url.focus();
    await page.keyboard.press("Enter");
    await form.getByRole("button", { name: "Adding..." }).waitFor();
    check(await submit.isDisabled(), "Submit must be disabled while adding");
    releaseSubmission();
    pendingSubmission = undefined;
    await form.waitFor({ state: "detached" });
    await page.getByRole("heading", { name: "Portfolio API" }).waitFor();
    check(JSON.stringify(submissions.at(-1)) === JSON.stringify({ name: "Portfolio API", url: "https://example.com/status" }), "Submission payload changed");
    check(submissions.length === (width === 393 ? 2 : 1), "Unexpected or duplicate submissions");
    await opener.click();
    check(await name.inputValue() === "" && await url.inputValue() === "", "Successful submission must reset inputs");
    await close.focus();
    await page.keyboard.press("Enter");
    await form.waitFor({ state: "detached" });
    results.push({ width, dashboardUnchanged: unchanged, ...layout, contrast, interactions: "passed" });
  }
  check(consoleErrors.length === 0, `Browser errors: ${consoleErrors.join("; ")}`);
  return { results, browserErrors: consoleErrors, api: "intercepted; no backend writes" };
}
