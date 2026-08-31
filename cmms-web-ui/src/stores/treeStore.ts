import { create } from 'zustand';

export interface AssetTreeNode {
  id: string;
  name: string;
  type: 'zone' | 'system' | 'node';
  status: 'operational' | 'warning' | 'critical' | 'offline' | 'maintenance';
  children?: AssetTreeNode[];
  hasChildren?: boolean;
  parentId?: string | null;
  expanded?: boolean;
  loading?: boolean;
}

interface TreeState {
  // Root nodes (Zones)
  roots: AssetTreeNode[];
  
  // Map for quick lookup by ID
  nodeMap: Record<string, AssetTreeNode>;
  
  // Currently selected node ID
  selectedNodeId: string | null;
  
  // Expanded node IDs set
  expandedIds: Set<string>;
  
  // Loading state for specific nodes
  loadingNodes: Set<string>;
  
  // Actions
  setRoots: (nodes: AssetTreeNode[]) => void;
  addNode: (parentId: string | null, node: AssetTreeNode) => void;
  updateNode: (id: string, updates: Partial<AssetTreeNode>) => void;
  removeNode: (id: string) => void;
  selectNode: (id: string | null) => void;
  toggleExpand: (id: string) => void;
  expandNode: (id: string) => void;
  collapseNode: (id: string) => void;
  setLoading: (id: string, loading: boolean) => void;
  clearTree: () => void;
}

const useTreeStore = create<TreeState>((set, get) => ({
  roots: [],
  nodeMap: {},
  selectedNodeId: null,
  expandedIds: new Set(),
  loadingNodes: new Set(),

  setRoots: (nodes) => {
    const nodeMap: Record<string, AssetTreeNode> = {};
    const buildMap = (nodeList: AssetTreeNode[], parentId: string | null = null) => {
      nodeList.forEach((node) => {
        node.parentId = parentId;
        nodeMap[node.id] = { ...node, expanded: false };
        if (node.children) {
          buildMap(node.children, node.id);
        }
      });
    };
    buildMap(nodes);
    
    set({ roots: nodes, nodeMap });
  },

  addNode: (parentId, node) => {
    const { nodeMap, roots } = get();
    const newNode = { ...node, expanded: false, parentId };
    
    if (parentId === null) {
      set({ roots: [...roots, newNode], nodeMap: { ...nodeMap, [node.id]: newNode } });
    } else {
      const parent = nodeMap[parentId];
      if (parent) {
        const updatedParent = {
          ...parent,
          children: [...(parent.children || []), newNode],
        };
        set({
          nodeMap: {
            ...nodeMap,
            [parentId]: updatedParent,
            [node.id]: newNode,
          },
        });
      }
    }
  },

  updateNode: (id, updates) => {
    const { nodeMap, roots } = get();
    const node = nodeMap[id];
    if (!node) return;

    const updatedNode = { ...node, ...updates };
    const newNodeMap = { ...nodeMap, [id]: updatedNode };

    // Update in roots if it's a root node
    const rootIndex = roots.findIndex((r) => r.id === id);
    if (rootIndex !== -1) {
      const newRoots = [...roots];
      newRoots[rootIndex] = updatedNode;
      set({ roots: newRoots, nodeMap: newNodeMap });
    } else {
      set({ nodeMap: newNodeMap });
    }
  },

  removeNode: (id) => {
    const { nodeMap, roots } = get();
    
    // Helper to collect all descendant IDs
    const collectDescendantIds = (nodeId: string): string[] => {
      const node = nodeMap[nodeId];
      if (!node || !node.children) return [];
      const ids: string[] = [nodeId];
      node.children.forEach((child) => {
        ids.push(...collectDescendantIds(child.id));
      });
      return ids;
    };

    const idsToRemove = collectDescendantIds(id);
    const newNodeMap = { ...nodeMap };
    idsToRemove.forEach((removeId) => {
      delete newNodeMap[removeId];
    });

    // Remove from roots if applicable
    const newRoots = roots.filter((r) => r.id !== id);
    
    // Remove from parent's children if not root
    const node = nodeMap[id];
    if (node && node.parentId) {
      const parent = nodeMap[node.parentId];
      if (parent && parent.children) {
        const updatedParent = {
          ...parent,
          children: parent.children.filter((c) => c.id !== id),
        };
        newNodeMap[node.parentId] = updatedParent;
      }
    }

    set({ roots: newRoots, nodeMap: newNodeMap });
    
    // Clear selection if removed node was selected
    if (get().selectedNodeId === id) {
      set({ selectedNodeId: null });
    }
  },

  selectNode: (id) => {
    set({ selectedNodeId: id });
  },

  toggleExpand: (id) => {
    const { expandedIds } = get();
    const newExpanded = new Set(expandedIds);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    set({ expandedIds: newExpanded });
  },

  expandNode: (id) => {
    const { expandedIds } = get();
    const newExpanded = new Set(expandedIds);
    newExpanded.add(id);
    set({ expandedIds: newExpanded });
  },

  collapseNode: (id) => {
    const { expandedIds } = get();
    const newExpanded = new Set(expandedIds);
    newExpanded.delete(id);
    set({ expandedIds: newExpanded });
  },

  setLoading: (id, loading) => {
    const { loadingNodes } = get();
    const newLoading = new Set(loadingNodes);
    if (loading) {
      newLoading.add(id);
    } else {
      newLoading.delete(id);
    }
    set({ loadingNodes: newLoading });
  },

  clearTree: () => {
    set({
      roots: [],
      nodeMap: {},
      selectedNodeId: null,
      expandedIds: new Set(),
      loadingNodes: new Set(),
    });
  },
}));

export default useTreeStore;
