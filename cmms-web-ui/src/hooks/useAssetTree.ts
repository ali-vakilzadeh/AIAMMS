import { useCallback } from 'react';
import useTreeStore, { AssetTreeNode } from '@/stores/treeStore';

// Mock API function to fetch children of a node
// In real implementation, this would call the backend API
const mockFetchChildren = async (parentId: string | null): Promise<AssetTreeNode[]> => {
  // Simulate network delay
  await new Promise((resolve) => setTimeout(resolve, 300));

  if (parentId === null) {
    // Return root zones
    return [
      {
        id: 'zone-1',
        name: 'Production Floor',
        type: 'zone',
        status: 'operational',
        hasChildren: true,
      },
      {
        id: 'zone-2',
        name: 'Warehouse',
        type: 'zone',
        status: 'warning',
        hasChildren: true,
      },
      {
        id: 'zone-3',
        name: 'Office Building',
        type: 'zone',
        status: 'operational',
        hasChildren: true,
      },
    ];
  }

  if (parentId.startsWith('zone-')) {
    // Return systems for a zone
    const systemCount = Math.floor(Math.random() * 3) + 2;
    return Array.from({ length: systemCount }, (_, i) => ({
      id: `system-${parentId}-${i}`,
      name: `System ${String.fromCharCode(65 + i)}`,
      type: 'system',
      status: i === 0 ? 'operational' : i === 1 ? 'warning' : 'maintenance',
      hasChildren: true,
      parentId,
    }));
  }

  if (parentId.startsWith('system-')) {
    // Return nodes for a system
    const nodeCount = Math.floor(Math.random() * 4) + 3;
    return Array.from({ length: nodeCount }, (_, i) => ({
      id: `node-${parentId}-${i}`,
      name: `Node ${i + 1}`,
      type: 'node',
      status: i % 5 === 0 ? 'critical' : i % 3 === 0 ? 'offline' : 'operational',
      hasChildren: false,
      parentId,
    }));
  }

  return [];
};

export const useAssetTree = () => {
  const {
    roots,
    nodeMap,
    selectedNodeId,
    expandedIds,
    loadingNodes,
    setRoots,
    addNode,
    updateNode,
    selectNode,
    toggleExpand,
    setLoading,
  } = useTreeStore();

  // Load root nodes on mount
  const loadRoots = useCallback(async () => {
    if (roots.length > 0) return; // Already loaded

    try {
      const data = await mockFetchChildren(null);
      setRoots(data);
    } catch (error) {
      console.error('Failed to load root nodes:', error);
    }
  }, [roots.length, setRoots]);

  // Load children for a specific node
  const loadChildren = useCallback(
    async (nodeId: string) => {
      const node = nodeMap[nodeId];
      if (!node || !node.hasChildren || node.children?.length) {
        return; // No children to load or already loaded
      }

      setLoading(nodeId, true);
      try {
        const children = await mockFetchChildren(nodeId);
        children.forEach((child) => {
          addNode(nodeId, child);
        });
      } catch (error) {
        console.error(`Failed to load children for node ${nodeId}:`, error);
      } finally {
        setLoading(nodeId, false);
      }
    },
    [nodeMap, addNode, setLoading]
  );

  // Handle node click (select and expand/collapse)
  const handleNodeClick = useCallback(
    async (nodeId: string) => {
      const node = nodeMap[nodeId];
      if (!node) return;

      // Toggle selection
      if (selectedNodeId === nodeId) {
        selectNode(null);
      } else {
        selectNode(nodeId);
      }

      // Toggle expansion and load children if needed
      if (node.hasChildren && !expandedIds.has(nodeId)) {
        toggleExpand(nodeId);
        await loadChildren(nodeId);
      } else if (expandedIds.has(nodeId)) {
        toggleExpand(nodeId);
      }
    },
    [nodeMap, selectedNodeId, expandedIds, selectNode, toggleExpand, loadChildren]
  );

  // Update node status (e.g., after an action)
  const updateNodeStatus = useCallback(
    (nodeId: string, status: AssetTreeNode['status']) => {
      updateNode(nodeId, { status });
    },
    [updateNode]
  );

  return {
    roots,
    nodeMap,
    selectedNodeId,
    expandedIds,
    loadingNodes,
    loadRoots,
    loadChildren,
    handleNodeClick,
    updateNodeStatus,
    selectNode,
    toggleExpand,
  };
};

export default useAssetTree;
