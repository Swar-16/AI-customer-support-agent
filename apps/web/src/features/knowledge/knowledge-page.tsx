// apps/web/src/features/knowledge/knowledge-page.tsx

import { WorkspaceEntry } from '../../shared/components/workspace-entry';

export default function KnowledgePage() {
  return (
    <WorkspaceEntry
      workspace="knowledge"
      description="Manage support documents and their publication lifecycle."
    />
  );
}
