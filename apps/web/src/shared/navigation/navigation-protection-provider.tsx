// apps/web/src/shared/navigation/navigation-protection-provider.tsx
import { useState } from 'react';
import type { ReactNode } from 'react';

import { createNavigationProtection, NavigationProtectionContext } from './navigation-protection';

export function NavigationProtectionProvider({ children }: { readonly children: ReactNode }) {
  const [protection] = useState(createNavigationProtection);

  return (
    <NavigationProtectionContext.Provider value={protection}>
      {children}
    </NavigationProtectionContext.Provider>
  );
}
