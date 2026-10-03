import { randomUUID } from "node:crypto";

import { ChatShell } from "@/components/chat/chat-shell";

// Each rendered chat needs its own checkpoint lineage; static prerendering would
// otherwise bake one build-time thread ID into the page for every visitor.
export const dynamic = "force-dynamic";

export default function HomePage() {
  return <ChatShell initialThreadId={`web-${randomUUID()}`} />;
}
