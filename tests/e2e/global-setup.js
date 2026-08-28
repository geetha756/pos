// Mints an authenticated storageState for the Playwright test run.
//
// The app only supports real Google OAuth (restricted to @sn15.ai accounts),
// which can't be driven headlessly. Instead we sign a Flask session cookie
// locally (mint_session_cookie.py, using the same SECRET_KEY + session
// interface the app itself uses) for the seeded local admin account, then
// hand Playwright a storageState with that cookie pre-set - equivalent to
// having logged in through the browser once.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const TEST_ADMIN_EMAIL = 'deepthi@sn15.ai';
const TEST_ADMIN_NAME = 'Deepthi kommuri';

module.exports = async function globalSetup() {
  // Self-cleanup: remove any fixture rows left behind by a previous
  // interrupted/failed run before this one creates its own. Scoped to the
  // suite's own synthetic naming pattern only (see db_helper.py) - never
  // touches real staff records.
  execFileSync('python', [path.join(__dirname, 'db_helper.py'), 'cleanup-fixtures'], {
    cwd: path.join(__dirname, '..', '..'),
    encoding: 'utf-8',
  });

  const scriptPath = path.join(__dirname, 'mint_session_cookie.py');
  const output = execFileSync('python', [scriptPath, TEST_ADMIN_EMAIL, TEST_ADMIN_NAME], {
    cwd: path.join(__dirname, '..', '..'),
    encoding: 'utf-8',
  }).trim();

  const [cookieName, cookieValue] = output.split('\t');
  if (!cookieName || !cookieValue) {
    throw new Error('Failed to mint session cookie: unexpected output from mint_session_cookie.py: ' + output);
  }

  const state = {
    cookies: [
      {
        name: cookieName,
        value: cookieValue,
        domain: 'localhost',
        path: '/',
        expires: Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60, // 30 days, matches PERMANENT_SESSION_LIFETIME
        httpOnly: true,
        secure: false,
        sameSite: 'Lax',
      },
    ],
    origins: [],
  };

  const authDir = path.join(__dirname, '.auth');
  if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
  fs.writeFileSync(path.join(authDir, 'admin-state.json'), JSON.stringify(state, null, 2));
};
