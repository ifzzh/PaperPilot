import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './cold-tests', workers: 1, timeout: 60000,
  use: {baseURL: 'http://127.0.0.3:7191', browserName: 'chromium'},
  webServer: {
    command: 'cd .. && exec env PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m tests.workbench_cold_server',
    url: 'http://127.0.0.3:7191/api/auth/session', timeout: 60000,
    gracefulShutdown: {signal: 'SIGTERM', timeout: 5000},
  },
});
