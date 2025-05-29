const fetch = require('node-fetch'); // Using node-fetch@2 for CommonJS
const jwt = require('jsonwebtoken');
const jwkToPem = require('jwk-to-pem');

const CLOUDFLARE_TEAM_DOMAIN = process.env.CLOUDFLARE_TEAM_DOMAIN;
const CLOUDFLARE_AUDIENCE_TAG = process.env.CLOUDFLARE_AUDIENCE_TAG;

let cachedPublicKeys = null; // { kid1: pem1, kid2: pem2, ... }
let lastKeyFetchTime = 0;
const KEY_CACHE_DURATION_MS = 60 * 60 * 1000; // 1 hour

/**
 * Fetches Cloudflare's public keys (JWKs) for verifying JWTs.
 * Implements in-memory caching for the keys.
 * @returns {Promise<object|null>} A map of kids to PEM-formatted public keys, or null if fetching fails.
 */
async function fetchCloudflarePublicKeys() {
  const now = Date.now();
  if (cachedPublicKeys && (now - lastKeyFetchTime < KEY_CACHE_DURATION_MS)) {
    // console.log('Using cached Cloudflare public keys.');
    return cachedPublicKeys;
  }

  if (!CLOUDFLARE_TEAM_DOMAIN) {
    // console.warn('Cloudflare Team Domain not configured, cannot fetch public keys.');
    return null;
  }

  const certsUrl = `https://${CLOUDFLARE_TEAM_DOMAIN}/cdn-cgi/access/certs`;
  // console.log(`Fetching Cloudflare public keys from: ${certsUrl}`);

  try {
    const response = await fetch(certsUrl);
    if (!response.ok) {
      throw new Error(`Failed to fetch Cloudflare certs: ${response.status} ${response.statusText}`);
    }
    const jwks = await response.json();
    
    if (!jwks || !jwks.keys || !Array.isArray(jwks.keys)) {
      throw new Error('Invalid JWKS format received from Cloudflare.');
    }

    const pemKeys = {};
    for (const key of jwks.keys) {
      if (key.kid && key.kty === 'RSA' && key.alg === 'RS256') { // Ensure it's an RSA key for RS256
        pemKeys[key.kid] = jwkToPem(key);
      } else if (key.kid && key.kty === 'EC' && key.alg === 'ES256') { // Support for EC keys if used
         pemKeys[key.kid] = jwkToPem(key);
      }
    }
    
    if (Object.keys(pemKeys).length === 0) {
        throw new Error('No usable public keys found in JWKS response.');
    }

    cachedPublicKeys = pemKeys;
    lastKeyFetchTime = now;
    // console.log('Successfully fetched and cached Cloudflare public keys. Kids:', Object.keys(cachedPublicKeys));
    return cachedPublicKeys;
  } catch (error) {
    console.error('Error fetching or processing Cloudflare public keys:', error.message);
    // If fetching fails, don't immediately invalidate the old cache if it exists,
    // unless it's too old or never fetched.
    if (!cachedPublicKeys || (now - lastKeyFetchTime > KEY_CACHE_DURATION_MS * 2)) { // e.g. allow stale for 2x duration
        cachedPublicKeys = null; // Invalidate stale cache on repeated failures
    }
    return null; // Indicate failure to fetch/update
  }
}

/**
 * Verifies a Cloudflare Access JWT.
 * @param {string} token - The JWT from the CF-Access-Jwt-Assertion header.
 * @returns {Promise<object|null>} The decoded payload if valid, otherwise null.
 */
async function verifyCloudflareJWT(token) {
  if (!CLOUDFLARE_TEAM_DOMAIN || !CLOUDFLARE_AUDIENCE_TAG) {
    // console.log('Cloudflare Access authentication is not configured/disabled.');
    return null;
  }
  if (!token) {
    // console.log('No Cloudflare JWT provided.');
    return null;
  }

  try {
    const decodedHeader = jwt.decode(token, { complete: true });
    if (!decodedHeader || !decodedHeader.header || !decodedHeader.header.kid) {
      console.error('Invalid Cloudflare JWT: Missing kid in header.');
      return null;
    }
    const kid = decodedHeader.header.kid;

    let publicKeys = await fetchCloudflarePublicKeys();
    if (!publicKeys) {
        // Attempt a refetch if initial fetch might have failed but cache was cleared
        console.warn('Retrying fetch for Cloudflare public keys as initial attempt failed or cache was cleared.');
        publicKeys = await fetchCloudflarePublicKeys(); 
    }

    if (!publicKeys || !publicKeys[kid]) {
      console.error(`No matching public key found for kid: ${kid}. Keys may need refresh or token is invalid.`);
      // Force a refresh attempt if a key for a specific kid is missing
      cachedPublicKeys = null; // Invalidate cache
      publicKeys = await fetchCloudflarePublicKeys();
      if (!publicKeys || !publicKeys[kid]) {
          console.error(`Still no matching public key found for kid: ${kid} after refresh.`);
          return null;
      }
    }

    const pem = publicKeys[kid];
    const expectedIssuer = `https://${CLOUDFLARE_TEAM_DOMAIN}`;

    const decodedPayload = jwt.verify(token, pem, {
      audience: CLOUDFLARE_AUDIENCE_TAG,
      issuer: expectedIssuer,
      algorithms: ['RS256', 'ES256'], // Specify algorithms Cloudflare uses
    });

    // console.log('Cloudflare JWT verified successfully. Payload:', decodedPayload);
    return decodedPayload;

  } catch (error) {
    console.error('Cloudflare JWT verification failed:', error.message);
    if (error.name === 'JsonWebTokenError' && error.message.includes('kid')) {
        // Potentially a new kid was introduced, force refresh
        cachedPublicKeys = null;
    }
    return null;
  }
}

// Pre-fetch keys on module load, but don't block startup.
// This helps ensure keys are available for the first request.
if (CLOUDFLARE_TEAM_DOMAIN) {
  fetchCloudflarePublicKeys().catch(err => {
    console.error("Initial pre-fetch of Cloudflare public keys failed:", err.message);
  });
}

module.exports = {
  verifyCloudflareJWT,
  fetchCloudflarePublicKeys // Export for testing or manual refresh if needed
};
