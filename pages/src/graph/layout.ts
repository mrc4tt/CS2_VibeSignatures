import ELK from 'elkjs/lib/elk.bundled.js'
import type { VisualGraph } from './model'

export interface NodePosition {
  x: number
  y: number
}

const elk = new ELK()

export async function layoutGraph(graph: VisualGraph): Promise<Record<string, NodePosition>> {
  const result = await elk.layout({
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '36',
      'elk.layered.spacing.nodeNodeBetweenLayers': '80',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
    },
    children: graph.nodes.map((node) => ({ id: node.id, width: 220, height: 76 })),
    edges: graph.edges.filter((edge) => edge.layout).map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  })
  return Object.fromEntries((result.children || []).map((node) => [node.id, { x: node.x || 0, y: node.y || 0 }]))
}
