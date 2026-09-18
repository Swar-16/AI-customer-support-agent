// apps/web/src/features/chat/message-scroll-boundary.tsx
import { Component, createRef } from 'react';
import type { ReactNode } from 'react';

interface ScrollProps {
  readonly pageKey: string;
  readonly ready: boolean;
  readonly lastSequence: number | null;
  readonly layoutKey?: string;
  readonly startAtBottom?: boolean;
  readonly children: ReactNode;
}

interface ScrollState {
  readonly hasNewMessages: boolean;
}

interface ScrollSnapshot {
  readonly nearBottom: boolean;
  readonly scrollTop: number;
  readonly anchor: HTMLElement | null;
  readonly anchorTop: number;
  readonly hasIncomingMessages: boolean;
}

const NEAR_BOTTOM_PX = 96;

export class MessageScrollBoundary extends Component<
  ScrollProps,
  ScrollState,
  ScrollSnapshot | null
> {
  override state: ScrollState = {
    hasNewMessages: false,
  };

  private readonly host = createRef<HTMLDivElement>();
  private readingPane: HTMLElement | null = null;

  private awaitingPagePosition = true;
  private hiddenSnapshot: ScrollSnapshot | null = null;

  override componentDidMount() {
    this.readingPane =
      this.host.current?.closest<HTMLElement>('[data-chat-scroll], .chat-reading') ?? null;

    this.readingPane?.addEventListener('scroll', this.handleScroll, {
      passive: true,
    });

    this.positionPage();
  }

  override componentWillUnmount() {
    this.readingPane?.removeEventListener('scroll', this.handleScroll);
    this.readingPane = null;
    this.hiddenSnapshot = null;
  }

  override getSnapshotBeforeUpdate(previous: Readonly<ScrollProps>): ScrollSnapshot | null {
    const pane = this.readingPane;

    if (
      pane === null ||
      previous.pageKey !== this.props.pageKey ||
      !previous.ready ||
      !this.props.ready
    ) {
      return null;
    }

    const layoutChanged = previous.layoutKey !== this.props.layoutKey;

    const hasIncomingMessages =
      this.props.lastSequence !== null &&
      this.props.lastSequence > (previous.lastSequence ?? Number.NEGATIVE_INFINITY);

    if (!layoutChanged && !hasIncomingMessages) return null;

    // On narrow screens, opening support hides the message column.
    // Preserve its last visible position until the column returns.
    if (pane.clientHeight === 0 && this.hiddenSnapshot) {
      return {
        ...this.hiddenSnapshot,
        hasIncomingMessages: this.hiddenSnapshot.hasIncomingMessages || hasIncomingMessages,
      };
    }

    const paneTop = pane.getBoundingClientRect().top;
    const messages = this.host.current?.querySelectorAll<HTMLElement>('[data-chat-message]');

    let anchor: HTMLElement | null = null;

    if (messages) {
      for (const message of messages) {
        if (message.getBoundingClientRect().bottom > paneTop) {
          anchor = message;
          break;
        }
      }
    }

    return {
      nearBottom: this.isNearBottom(pane),
      scrollTop: pane.scrollTop,
      anchor,
      anchorTop: anchor === null ? 0 : anchor.getBoundingClientRect().top - paneTop,
      hasIncomingMessages,
    };
  }

  override componentDidUpdate(
    previous: Readonly<ScrollProps>,
    _previousState: Readonly<ScrollState>,
    snapshot: ScrollSnapshot | null,
  ) {
    if (previous.pageKey !== this.props.pageKey) {
      this.awaitingPagePosition = true;
      this.hiddenSnapshot = null;
      this.clearNotice();
    }

    if (this.positionPage()) return;

    const pane = this.readingPane;
    if (pane === null || snapshot === null) return;

    if (pane.clientHeight === 0) {
      this.hiddenSnapshot = snapshot;
      return;
    }

    this.hiddenSnapshot = null;

    if (snapshot.nearBottom) {
      pane.scrollTop = pane.scrollHeight;
      this.clearNotice();
      return;
    }

    const anchor = snapshot.anchor;

    if (anchor !== null && anchor.isConnected && this.host.current?.contains(anchor)) {
      const currentTop = anchor.getBoundingClientRect().top - pane.getBoundingClientRect().top;

      pane.scrollTop += currentTop - snapshot.anchorTop;
    } else {
      pane.scrollTop = snapshot.scrollTop;
    }

    if (snapshot.hasIncomingMessages && !this.state.hasNewMessages) {
      this.setState({ hasNewMessages: true });
    }
  }

  private positionPage(): boolean {
    const pane = this.readingPane;

    if (!this.awaitingPagePosition || !this.props.ready || pane === null) {
      return false;
    }

    if (!this.props.startAtBottom) {
      this.awaitingPagePosition = false;
      return false;
    }

    // Keep waiting if the mobile support panel currently hides messages.
    if (pane.clientHeight === 0) return false;

    pane.scrollTop = pane.scrollHeight;
    this.awaitingPagePosition = false;
    this.clearNotice();
    return true;
  }

  private clearNotice() {
    if (this.state.hasNewMessages) {
      this.setState({ hasNewMessages: false });
    }
  }

  private isNearBottom(pane: HTMLElement): boolean {
    return pane.scrollHeight - pane.clientHeight - pane.scrollTop <= NEAR_BOTTOM_PX;
  }

  private handleScroll = () => {
    const pane = this.readingPane;

    if (pane !== null && pane.clientHeight > 0 && this.isNearBottom(pane)) {
      this.clearNotice();
    }
  };

  private showNewMessages = () => {
    const pane = this.readingPane;
    const messages = this.host.current?.querySelectorAll<HTMLElement>('[data-chat-message]');
    const latest = messages?.item(messages.length - 1);

    if (pane === null || !latest) return;

    const top = Math.max(
      0,
      pane.scrollTop + latest.getBoundingClientRect().top - pane.getBoundingClientRect().top - 16,
    );

    const reduceMotion =
      typeof window.matchMedia !== 'function' ||
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    latest.focus({ preventScroll: true });
    this.clearNotice();

    pane.scrollTo({
      top,
      behavior: reduceMotion ? 'auto' : 'smooth',
    });
  };

  override render() {
    const showNotice = this.props.ready && this.state.hasNewMessages;

    return (
      <div ref={this.host} className="chat-scroll-boundary">
        <div className="chat-new-messages">
          <span
            className="chat-markdown__sr-only"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {showNotice ? 'New messages are available below.' : ''}
          </span>

          {showNotice && (
            <button type="button" onClick={this.showNewMessages}>
              New messages
            </button>
          )}
        </div>

        {this.props.children}
      </div>
    );
  }
}
