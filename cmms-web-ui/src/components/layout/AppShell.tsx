import React, { ReactNode } from 'react';
import { Header } from './Header';
import { WorkspaceArea } from './WorkspaceArea';
import { useLayoutStore } from '@/store/layoutStore';

interface AppShellProps {
  children: ReactNode;
}

/**
 * AppShell Component
 * Main application layout shell containing:
 * - Header (with RTL toggle, notifications, user menu)
 * - Workspace Area (main content area with adaptive padding)
 * 
 * Manages the overall app layout and responds to sidebar state changes.
 */
export const AppShell: React.FC<AppShellProps> = ({ children }) => {
  const { toggleSidebar } = useLayoutStore();

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      {/* Header */}
      <Header onMenuClick={toggleSidebar} />

      {/* Main Content Area */}
      <div className="flex flex-1 overflow-hidden">
        <WorkspaceArea>
          {children}
        </WorkspaceArea>
      </div>
    </div>
  );
};
