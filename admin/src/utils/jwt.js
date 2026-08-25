/**
 * Read the claims out of a JWT without verifying it.
 *
 * Display only, and deliberately so: this decides whether to render the COGS
 * field, never whether the request is allowed. `routes/admin_deps.py` re-reads
 * the actor from the database on every request precisely because a claim minted
 * at login outlives a demotion. A forged token here changes what one browser
 * draws and nothing else.
 */
export function decodeClaims(token) {
  try {
    const payload = token.split('.')[1];
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json);
  } catch {
    return null;
  }
}
