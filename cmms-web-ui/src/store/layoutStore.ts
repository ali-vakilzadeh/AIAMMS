import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Direction = 'ltr' | 'rtl';

interface LayoutState {
  // RTL/LTR State
  direction: Direction;
  setDirection: (dir: Direction) => void;
  toggleDirection: () => void;

  // Sidebar State
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;

  // Header State
  headerHeight: number;
  setHeaderHeight: (height: number) => void;

  // Workspace State
  workspacePadding: number;
  setWorkspacePadding: (padding: number) => void;
}

const HEADER_HEIGHT_DEFAULT = 56;
const WORKSPACE_PADDING_DEFAULT = 16;

export const useLayoutStore = create<LayoutState>()(
  persist(
    (set, get) => ({
      // RTL/LTR
      direction: 'ltr',
      setDirection: (dir) => {
        set({ direction: dir });
        document.documentElement.dir = dir;
        document.documentElement.lang = dir === 'rtl' ? 'ar' : 'en';
      },
      toggleDirection: () => {
        const newDir = get().direction === 'ltr' ? 'rtl' : 'ltr';
        get().setDirection(newDir);
      },

      // Sidebar
      sidebarOpen: true,
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),

      // Header
      headerHeight: HEADER_HEIGHT_DEFAULT,
      setHeaderHeight: (height) => set({ headerHeight: height }),

      // Workspace
      workspacePadding: WORKSPACE_PADDING_DEFAULT,
      setWorkspacePadding: (padding) => set({ workspacePadding: padding }),
    }),
    {
      name: 'cmms-layout-storage',
      partialize: (state) => ({
        direction: state.direction,
        sidebarOpen: state.sidebarOpen,
      }),
      onRehydrateStorage: () => (state) => {
        if (state?.direction) {
          document.documentElement.dir = state.direction;
          document.documentElement.lang = state.direction === 'rtl' ? 'ar' : 'en';
        }
      },
    }
  )
);
