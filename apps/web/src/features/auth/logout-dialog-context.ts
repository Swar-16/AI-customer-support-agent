// apps/web/src/features/auth/logout-dialog-context.ts
import { createContext, useContext } from 'react';

export const LogoutDialogContext = createContext<(() => void) | null>(null);

export function useLogoutDialog(): () => void {
  const requestLogout = useContext(LogoutDialogContext);

  if (requestLogout === null) {
    throw new Error('LogoutDialogProvider is required.');
  }

  return requestLogout;
}
