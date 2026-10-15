import type React from 'react';
import { Sparkles, Sun, Moon, FolderGit2, Settings, Plus } from 'lucide-react';
import type { AppRoute, AppTheme } from '../../types';
import { Button } from '../ui/Button';

export interface HeaderProps {
  currentRoute: AppRoute;
  onRouteChange: (route: AppRoute) => void;
  onNewWorkflow: () => void;
  theme: AppTheme;
  onToggleTheme: () => void;
  hasActiveWorkflow?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  currentRoute,
  onRouteChange,
  onNewWorkflow,
  theme,
  onToggleTheme,
  hasActiveWorkflow = false,
}) => {
  return (
    <header className="app-header">
      <div style={{ display: 'flex', alignItems: 'center', gap: '28px' }}>
        <a
          href="#/"
          className="header-brand"
          onClick={(e) => {
            e.preventDefault();
            onRouteChange('workspace');
          }}
          title="n8n Workflow AI Home"
        >
          <div className="brand-icon">
            <svg
              viewBox="0 0 32 32"
              width="24"
              height="24"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <rect width="32" height="32" rx="6" fill="#0B0F17" />
              <circle cx="8" cy="16" r="3" fill="#EA580C" />
              <circle cx="24" cy="10" r="3" fill="#10B981" />
              <circle cx="24" cy="22" r="3" fill="#0284C7" />
              <path
                d="M11 16h6l4-6m-4 6l4 6"
                fill="none"
                stroke="#6B7280"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <span className="brand-title">n8n Workflow AI</span>
        </a>

        <nav className="header-nav" aria-label="Main navigation">
          <button
            type="button"
            className={`nav-link ${currentRoute === 'workspace' ? 'active' : ''}`}
            onClick={() => onRouteChange('workspace')}
            aria-current={currentRoute === 'workspace' ? 'page' : undefined}
          >
            <Sparkles size={15} />
            <span>Create</span>
          </button>
          <button
            type="button"
            className={`nav-link ${currentRoute === 'drafts' ? 'active' : ''}`}
            onClick={() => onRouteChange('drafts')}
            aria-current={currentRoute === 'drafts' ? 'page' : undefined}
          >
            <FolderGit2 size={15} />
            <span>My Workflows</span>
          </button>
          <button
            type="button"
            className={`nav-link ${currentRoute === 'settings' ? 'active' : ''}`}
            onClick={() => onRouteChange('settings')}
            aria-current={currentRoute === 'settings' ? 'page' : undefined}
          >
            <Settings size={15} />
            <span>Settings</span>
          </button>
        </nav>
      </div>

      <div className="header-actions">
        {hasActiveWorkflow && currentRoute === 'workspace' && (
          <Button
            variant="secondary"
            size="sm"
            onClick={onNewWorkflow}
            icon={<Plus size={14} />}
            title="Start a new automation"
          >
            <span>New automation</span>
          </Button>
        )}

        <Button
          variant="secondary"
          size="sm"
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
          title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
          icon={theme === 'light' ? <Moon size={14} /> : <Sun size={14} />}
        >
          <span>{theme === 'light' ? 'Dark' : 'Light'}</span>
        </Button>
      </div>
    </header>
  );
};
