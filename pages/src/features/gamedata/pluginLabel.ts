// Plugin ids are directory names and stay the key everywhere; this is only what a person reads.
const LABELS: Record<string, string> = {
  matchzy: 'matchzy (mrc4tt fork)',
}

export function pluginLabel(plugin: string): string {
  return LABELS[plugin] ?? plugin
}
