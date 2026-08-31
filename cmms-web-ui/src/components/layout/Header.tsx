import React from 'react';
import { Bell, Globe, Menu, User, LogOut, Settings, ChevronDown } from 'lucide-react';
import { useLayoutStore } from '@/store/layoutStore';
import { useAuth } from '@/auth/AuthProvider';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';

interface HeaderProps {
  onMenuClick?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onMenuClick }) => {
  const { direction, toggleDirection } = useLayoutStore();
  const { user, logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = React.useState(false);
  const notificationCount = 3; // Mock count - would come from real API in production

  const handleLogout = () => {
    logout();
    setShowUserMenu(false);
  };

  return (
    <header 
      className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60"
      style={{ height: 'var(--header-height)', '--header-height': '56px' } as React.CSSProperties}
    >
      <div className="flex h-full items-center justify-between px-4">
        {/* Left Section: Menu + Logo */}
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={onMenuClick}
            aria-label="Toggle sidebar"
          >
            <Menu className="h-5 w-5" />
          </Button>
          
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
              <span className="text-primary-foreground font-bold text-sm">CM</span>
            </div>
            <span className="font-semibold text-lg hidden sm:inline-block">CMMS Pro</span>
          </div>
        </div>

        {/* Right Section: Actions + User Menu */}
        <div className="flex items-center gap-2">
          {/* RTL/LTR Toggle */}
          <Button
            variant="ghost"
            size="sm"
            onClick={toggleDirection}
            aria-label={`Switch to ${direction === 'ltr' ? 'RTL' : 'LTR'} mode`}
            title={`Current: ${direction.toUpperCase()}`}
          >
            <Globe className="h-4 w-4" />
            <span className="text-xs font-medium ms-1">
              {direction === 'ltr' ? 'LTR' : 'RTL'}
            </span>
          </Button>

          {/* Notifications Bell */}
          <Button
            variant="ghost"
            size="sm"
            aria-label="Notifications"
            className="relative"
          >
            <Bell className="h-5 w-5" />
            {notificationCount > 0 && (
              <Badge 
                variant="destructive" 
                className="absolute -top-1 -right-1 h-5 w-5 flex items-center justify-center p-0 text-xs"
              >
                {notificationCount}
              </Badge>
            )}
          </Button>

          {/* User Menu */}
          <div className="relative">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowUserMenu(!showUserMenu)}
              className="flex items-center gap-2"
              aria-label="User menu"
              aria-expanded={showUserMenu}
            >
              <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
                <User className="h-4 w-4" />
              </div>
              <span className="hidden md:inline-block text-sm font-medium">
                {user?.firstName || user?.email?.split('@')[0]}
              </span>
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            </Button>

            {/* Dropdown Menu */}
            {showUserMenu && (
              <>
                <div 
                  className="fixed inset-0 z-40" 
                  onClick={() => setShowUserMenu(false)}
                />
                <div 
                  className="absolute end-0 mt-2 w-56 rounded-lg border bg-popover p-2 shadow-lg z-50"
                  role="menu"
                >
                  {/* User Info */}
                  <div className="border-b pb-3 mb-2">
                    <p className="text-sm font-medium">{user?.firstName} {user?.lastName}</p>
                    <p className="text-xs text-muted-foreground">{user?.email}</p>
                    <Badge variant="outline" className="mt-1 text-xs">
                      {user?.role}
                    </Badge>
                  </div>

                  {/* Menu Items */}
                  <nav className="space-y-1">
                    <button
                      className="w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
                      role="menuitem"
                    >
                      <User className="h-4 w-4" />
                      Profile
                    </button>
                    <button
                      className="w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
                      role="menuitem"
                    >
                      <Settings className="h-4 w-4" />
                      Settings
                    </button>
                    <div className="border-t my-2" />
                    <button
                      className="w-full flex items-center gap-2 rounded-md px-3 py-2 text-sm text-destructive hover:bg-destructive/10"
                      role="menuitem"
                      onClick={handleLogout}
                    >
                      <LogOut className="h-4 w-4" />
                      Logout
                    </button>
                  </nav>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
