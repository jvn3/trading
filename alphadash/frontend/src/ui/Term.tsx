import type { ReactNode } from "react";

import { GLOSSARY, type GlossaryKey } from "../lib/glossary";
import { DefinitionTooltip } from "./DefinitionTooltip";

// S3.3: glossary-backed DefinitionTooltip. `k` is type-checked against the glossary, so a term
// used anywhere in the app is guaranteed to have a definition.
export function Term({ k, children }: { k: GlossaryKey; children?: ReactNode }) {
  return (
    <DefinitionTooltip term={k} definition={GLOSSARY[k]}>
      {children ?? k}
    </DefinitionTooltip>
  );
}
