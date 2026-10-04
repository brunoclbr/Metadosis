import { randomUUID } from "node:crypto";

import { MetadosisApp } from "@/components/apprentice/metadosis-app";

// Each visitor needs their own session lineage; static prerendering would
// otherwise bake one build-time ID into the page for everyone.
export const dynamic = "force-dynamic";

export default function HomePage() {
  return <MetadosisApp initialSessionId={`web-${randomUUID()}`} />;
}
