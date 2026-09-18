// apps/web/src/shared/navigation/navigation-protection.ts
import { createContext, useCallback, useContext, useId, useLayoutEffect } from 'react';

export function createNavigationProtection() {
  const owners = new Set<string>();
  const listeners = new Set<() => void>();

  function update(change: () => void) {
    const wasProtected = owners.size > 0;

    change();

    if (wasProtected !== owners.size > 0) {
      listeners.forEach((listener) => listener());
    }
  }

  return {
    getSnapshot: () => owners.size > 0,

    subscribe(listener: () => void) {
      listeners.add(listener);

      return () => {
        listeners.delete(listener);
      };
    },

    set(owner: string, active: boolean) {
      update(() => {
        if (active) {
          owners.add(owner);
        } else {
          owners.delete(owner);
        }
      });
    },

    remove(owner: string) {
      update(() => {
        owners.delete(owner);
      });
    },
  };
}

export type NavigationProtection = ReturnType<typeof createNavigationProtection>;

export const NavigationProtectionContext = createContext<NavigationProtection | null>(null);

/**
 * Register a mounted editor's navigation protection.
 *
 * The returned function releases protection synchronously before an
 * intentional navigation, such as opening a successfully saved conversation.
 */
export function useNavigationProtection(active: boolean): () => void {
  const protection = useContext(NavigationProtectionContext);
  const owner = useId();

  useLayoutEffect(() => {
    if (protection === null) return;

    protection.set(owner, active);

    return () => {
      protection.remove(owner);
    };
  }, [active, owner, protection]);

  return useCallback(() => {
    protection?.remove(owner);
  }, [owner, protection]);
}
