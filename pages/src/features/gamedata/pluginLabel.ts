// Plugin ids are directory names and stay the key everywhere; this is only what a person reads.
const LABELS: Record<string, string> = {
  CounterStrikeSharp: 'CounterStrikeSharp (mrc4tt fork)',
  'CounterStrikeSharp-roflmuffin': 'CounterStrikeSharp (original, roflmuffin)',
  matchzy: 'matchzy (mrc4tt fork)',
  'matchzy-original': 'matchzy (original, WD-)',
}

export function pluginLabel(plugin: string): string {
  return LABELS[plugin] ?? plugin
}
