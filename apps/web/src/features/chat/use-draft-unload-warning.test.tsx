// apps/web/src/features/chat/use-draft-unload-warning.test.tsx
import { StrictMode, type ReactNode } from 'react';
import { cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { useDraftUnloadWarning } from './use-draft-unload-warning';

afterEach(cleanup);

function dispatchUnload(): Event {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event;
}

function StrictWrapper({ children }: { readonly children: ReactNode }) {
  return <StrictMode>{children}</StrictMode>;
}

describe('draft unload warning', () => {
  it('does not prevent unloading when protection is disabled', () => {
    renderHook(() => useDraftUnloadWarning(false));

    expect(dispatchUnload().defaultPrevented).toBe(false);
  });

  it('requests a warning while protection is enabled', () => {
    renderHook(() => useDraftUnloadWarning(true));

    expect(dispatchUnload().defaultPrevented).toBe(true);
  });

  it('removes protection when the submission becomes resolved', () => {
    const view = renderHook(({ enabled }) => useDraftUnloadWarning(enabled), {
      initialProps: { enabled: true },
    });

    expect(dispatchUnload().defaultPrevented).toBe(true);

    view.rerender({ enabled: false });

    expect(dispatchUnload().defaultPrevented).toBe(false);
  });

  it('removes protection when the draft unmounts', () => {
    const view = renderHook(() => useDraftUnloadWarning(true));

    view.unmount();

    expect(dispatchUnload().defaultPrevented).toBe(false);
  });

  it('works through Strict Mode setup and cleanup', () => {
    const view = renderHook(() => useDraftUnloadWarning(true), {
      wrapper: StrictWrapper,
    });

    expect(dispatchUnload().defaultPrevented).toBe(true);

    view.unmount();

    expect(dispatchUnload().defaultPrevented).toBe(false);
  });
});
