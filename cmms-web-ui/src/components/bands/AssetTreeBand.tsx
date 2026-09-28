import React, { useEffect } from 'react';
import { Trees } from 'lucide-react';
import useAssetTree from '@/hooks/useAssetTree';
import AssetTreeNode from './AssetTreeNode';
import { cn } from '@/lib/cn';

interface AssetTreeBandProps {
  className?: string;
}

const AssetTreeBand: React.FC<AssetTreeBandProps> = ({ className }) => {
  const { roots, loadRoots, selectedNodeId, nodeMap } = useAssetTree();

  // Load root nodes on mount
  useEffect(() => {
    loadRoots();
  }, [loadRoots]);

  const selectedNode = selectedNodeId ? nodeMap[selectedNodeId] : null;

  return (
    <aside
      className={cn(
        'flex flex-col h-full bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800',
        'w-[--asset-tree-width] min-w-[--asset-tree-width] max-w-[--asset-tree-width]',
        'overflow-hidden',
        className
      )}
      role="navigation"
      aria-label="Asset tree navigation"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-gray-200 dark:border-gray-800">
        <Trees className="w-4 h-4 text-gray-500 dark:text-gray-400" />
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Assets
        </h2>
      </div>

      {/* Tree Content */}
      <div
        className="flex-1 overflow-y-auto overflow-x-hidden"
        role="tree"
        aria-label="Asset hierarchy"
      >
        {roots.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500 dark:text-gray-400">
            <p className="text-xs">Loading assets...</p>
          </div>
        ) : (
          <div className="py-2">
            {roots.map((root) => (
              <AssetTreeNode key={root.id} nodeId={root.id} depth={0} />
            ))}
          </div>
        )}
      </div>

      {/* Footer with Selected Node Info */}
      {selectedNode && (
        <div className="px-3 py-2 border-t border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
          <p className="text-xs text-gray-500 dark:text-gray-400">Selected:</p>
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
            {selectedNode.name}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 capitalize">
            {selectedNode.type} • {selectedNode.status}
          </p>
        </div>
      )}
    </aside>
  );
};

export default AssetTreeBand;
