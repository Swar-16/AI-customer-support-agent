// apps/web/src/features/chat/use-draft-unload-warning.ts
import { useEffect } from 'react';

/**
 * Warn before unloading a page that contains unsent text or an unresolved
 * submission. Does not persist content or cancel backend processing.
 */
export function useDraftUnloadWarning(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;

    function handleBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();

      // Required by browsers that still use the legacy confirmation signal.
      // The browser supplies its own warning text.
      event.returnValue = '';
    }

    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [enabled]);
}
