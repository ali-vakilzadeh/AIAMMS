import React from 'react';
import { ChevronRight, ChevronDown, Folder, Settings, Box, Loader2 } from 'lucide-react';
import useAssetTree from '@/hooks/useAssetTree';
import { cn } from '@/lib/cn';
import { getStatusColor } from '@/components/ui/Badge';

interface AssetTreeNodeProps {
  nodeId: string;
  depth: number;
}

const AssetTreeNode: React.FC<AssetTreeNodeProps> = ({ nodeId, depth }) => {
  const { nodeMap, expandedIds, loadingNodes, selectedNodeId, handleNodeClick } = useAssetTree();
  
  const node = nodeMap[nodeId];
  if (!node) return null;

  const isExpanded = expandedIds.has(nodeId);
  const isLoading = loadingNodes.has(nodeId);
  const isSelected = selectedNodeId === nodeId;
  const hasChildren = node.hasChildren || (node.children && node.children.length > 0);

  // Icon based on node type
  const Icon = node.type === 'zone' ? Folder : node.type === 'system' ? Settings : Box;

  return (
    <div className="select-none">
      {/* Node Row */}
      <div
        role="treeitem"
        aria-expanded={hasChildren ? isExpanded : undefined}
        aria-selected={isSelected}
        tabIndex={0}
        onClick={() => handleNodeClick(nodeId)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleNodeClick(nodeId);
          }
        }}
        className={cn(
          'flex items-center gap-1 px-2 py-1.5 cursor-pointer rounded-md transition-colors duration-150',
          'focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-1',
          isSelected
            ? 'bg-primary-100 text-primary-900 dark:bg-primary-900 dark:text-primary-100'
            : 'hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300'
        )}
        style={{ paddingInlineStart: depth * 12 + 8 }}
      >
        {/* Expand/Collapse Arrow */}
        <span className="w-4 h-4 flex items-center justify-center flex-shrink-0">
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5 text-gray-500" />
            )
          ) : null}
        </span>

        {/* Loading Indicator */}
        {isLoading && (
          <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin" />
        )}

        {/* Node Icon with Status Color */}
        <Icon
          className={cn(
            'w-4 h-4 flex-shrink-0',
            getStatusColor(node.status, 'text')
          )}
        />

        {/* Node Name */}
        <span className="text-sm font-medium truncate flex-1">
          {node.name}
        </span>

        {/* Status Badge Dot */}
        <span
          className={cn(
            'w-2 h-2 rounded-full flex-shrink-0',
            getStatusColor(node.status, 'bg')
          )}
          aria-label={`Status: ${node.status}`}
        />
      </div>

      {/* Children */}
      {isExpanded && node.children && (
        <div role="group" className="flex flex-col">
          {node.children.map((child) => (
            <AssetTreeNode key={child.id} nodeId={child.id} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

export default AssetTreeNode;
