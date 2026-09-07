/**
 * The number this publish will carry (Form IR §9).
 *
 * A published version is immutable, and the server refuses the same number
 * with different content — rightly. The dialog promises "the next numbered
 * version", so this is where the number comes from: the document's own
 * `version` if nothing that high is published yet, otherwise one past the
 * highest published. The draft is told afterwards, so it carries the number
 * it became.
 */
export function nextVersion(draftVersion: number, published: number[]): number {
  const highest = published.reduce((a, b) => Math.max(a, b), 0);
  return draftVersion > highest ? draftVersion : highest + 1;
}
