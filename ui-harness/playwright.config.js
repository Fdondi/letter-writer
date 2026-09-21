// @ts-check
const { defineConfig } = require("@playwright/test");

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3010";

module.exports = defineConfig({
  testDir: "./playwright",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  retries: 1,
  use: {
    baseURL,
    viewport: { width: 1280, height: 800 },
  },
});
