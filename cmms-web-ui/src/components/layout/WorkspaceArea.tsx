import React, { ReactNode } from 'react';
import { useLayoutStore } from '@/store/layoutStore';

interface WorkspaceAreaProps {
  children: ReactNode;
  className?: string;
}

/**
 * WorkspaceArea Component
 * Main content area that adapts to sidebar state and RTL/LTR direction.
 * Uses CSS logical properties for proper RTL support.
 */
export const WorkspaceArea: React.FC<WorkspaceAreaProps> = ({ 
  children, 
  className = '' 
}) => {
  const { sidebarOpen, direction, workspacePadding } = useLayoutStore();

  return (
    <main
      className={`flex-1 overflow-auto bg-muted/20 ${className}`}
      style={{
        padding: `${workspacePadding}px`,
        paddingInlineStart: sidebarOpen ? `calc(var(--asset-tree-width) + ${workspacePadding}px)` : `${workspacePadding}px`,
        transition: 'padding-inline-start 0.3s ease',
      }}
      dir={direction}
    >
      {children}
    </main>
  );
};
