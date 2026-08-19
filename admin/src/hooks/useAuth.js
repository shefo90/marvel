import { useAuthContext } from '../context/AuthContext.jsx';
import { LEVEL_ADMIN } from '../utils/constants.js';

/**
 * The session, plus the two questions the UI actually asks of it.
 *
 * `canSetCost` gates rendering only. COGS feeds contribution_profit, so the API
 * requires admin (4) for it even though the route itself is open to catalog (2)
 * -- and it re-reads the actor from the database to decide, because a level
 * baked into a token at login outlives a demotion. Hiding the field is a
 * courtesy; the refusal is the API's.
 */
export function useAuth() {
  const { session, signIn, signOut } = useAuthContext();
  const accessLevel = session?.user?.access_level ?? 0;

  return {
    session,
    signIn,
    signOut,
    accessLevel,
    role: session?.user?.role ?? null,
    canSetCost: accessLevel >= LEVEL_ADMIN,
  };
}
