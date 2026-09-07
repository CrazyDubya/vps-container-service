const fs = require('fs');
const os = require('os');
const path = require('path');
const bcrypt = require('bcrypt');

const Database = require('../lib/database');
const { createRateLimiter } = require('../lib/rate-limit');

function rawGet(db, sql, params = []) {
  return new Promise((resolve, reject) => {
    db.db.get(sql, params, (error, row) => (error ? reject(error) : resolve(row)));
  });
}

function rawRun(db, sql, params = []) {
  return new Promise((resolve, reject) => {
    db.db.run(sql, params, (error) => (error ? reject(error) : resolve()));
  });
}

function closeDb(db) {
  return new Promise((resolve, reject) => {
    db.db.close((error) => (error ? reject(error) : resolve()));
  });
}

describe('security primitives', () => {
  let tempDir;
  let db;

  beforeEach(() => {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'container-service-test-'));
    db = new Database(path.join(tempDir, 'users.sqlite3'));
  });

  afterEach(async () => {
    await closeDb(db);
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  test('new API keys are stored as deterministic SHA-256 digests and authenticate directly', async () => {
    const created = await db.createUser({
      username: 'alice',
      email: 'alice@example.test',
      password: 'correct horse battery staple',
    });

    expect(created.apiKey).toMatch(/^[0-9a-f]{64}$/);
    const stored = await rawGet(db, 'SELECT api_key FROM users WHERE id = ?', [created.id]);
    expect(stored.api_key).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(stored.api_key).not.toBe(created.apiKey);

    const authenticated = await db.getUserByApiKey(created.apiKey);
    expect(authenticated).not.toBeNull();
    expect(authenticated.id).toBe(created.id);
  });

  test('legacy plaintext API keys are upgraded after successful use', async () => {
    const created = await db.createUser({
      username: 'legacy',
      email: 'legacy@example.test',
      password: 'correct horse battery staple',
    });
    const legacyKey = 'legacy-key-that-is-long-enough-for-validation-1234567890';
    await rawRun(db, 'UPDATE users SET api_key = ? WHERE id = ?', [legacyKey, created.id]);

    const authenticated = await db.getUserByApiKey(legacyKey);
    expect(authenticated.id).toBe(created.id);

    const stored = await rawGet(db, 'SELECT api_key FROM users WHERE id = ?', [created.id]);
    expect(stored.api_key).toBe(db.hashApiKey(legacyKey));
  });

  test('legacy bcrypt API-key rows are not scanned on unauthenticated requests', async () => {
    const created = await db.createUser({
      username: 'bcrypt-legacy',
      email: 'bcrypt@example.test',
      password: 'correct horse battery staple',
    });
    const legacyKey = 'legacy-bcrypt-key-that-must-be-regenerated-1234567890';
    const bcryptHash = await bcrypt.hash(legacyKey, 10);
    await rawRun(db, 'UPDATE users SET api_key = ? WHERE id = ?', [bcryptHash, created.id]);

    await expect(db.getUserByApiKey(legacyKey)).resolves.toBeNull();
  });

  test('rate limiter returns 429 after the configured request budget', () => {
    const limiter = createRateLimiter({ windowMs: 60_000, max: 2 });
    const req = { ip: '127.0.0.1', socket: {} };
    const next = jest.fn();
    const res = {
      headers: {},
      statusCode: 200,
      set(name, value) {
        this.headers[name] = value;
        return this;
      },
      status(code) {
        this.statusCode = code;
        return this;
      },
      json(payload) {
        this.payload = payload;
        return this;
      },
    };

    limiter(req, res, next);
    limiter(req, res, next);
    limiter(req, res, next);

    expect(next).toHaveBeenCalledTimes(2);
    expect(res.statusCode).toBe(429);
    expect(res.headers['Retry-After']).toBeDefined();
  });
});
