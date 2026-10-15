import React from 'react';
import { Sparkles, FolderGit2, Settings, Moon, Sun, Plus } from 'lucide-react';
import type { AppRoute, AppTheme } from '../../types';

export interface LeftNavRailProps {
  currentRoute: AppRoute;
  onRouteChange: (route: AppRoute) => void;
  onNewWorkflow: () => void;
  theme: AppTheme;
  onToggleTheme: () => void;
}

export const LeftNavRail: React.FC<LeftNavRailProps> = ({
  currentRoute,
  onRouteChange,
  onNewWorkflow,
  theme,
  onToggleTheme,
}) => {
  return (
    <aside
      className="left-nav-rail"
      aria-label="Application sections"
      style={{
        width: '56px',
        backgroundColor: 'var(--bg-surface)',
        borderRight: '1px solid var(--border-default)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 0',
        zIndex: 20,
        flexShrink: 0,
        height: '100%',
        userSelect: 'none',
      }}
    >
      {/* Top: Logo & Main Navigation Icons */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', width: '100%' }}>
        {/* Brand Icon Button */}
        <button
          type="button"
          onClick={() => onRouteChange('workspace')}
          title="n8n Workflow Studio"
          aria-label="n8n Workflow Studio Home"
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: '4px',
            borderRadius: 'var(--radius-sm)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg
            viewBox="0 0 32 32"
            width="28"
            height="28"
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
        </button>

        <div style={{ width: '32px', height: '1px', backgroundColor: 'var(--border-subtle)' }} />

        {/* Section Navigation Buttons */}
        <nav
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '8px',
            width: '100%',
          }}
          aria-label="Main navigation rail"
        >
          {/* Create / Workspace */}
          <button
            type="button"
            className={`rail-nav-btn ${currentRoute === 'workspace' ? 'active' : ''}`}
            onClick={() => onRouteChange('workspace')}
            title="Create Automation (Workspace)"
            aria-label="Create Automation"
            aria-current={currentRoute === 'workspace' ? 'page' : undefined}
            style={{
              width: '40px',
              height: '40px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              backgroundColor: currentRoute === 'workspace' ? 'var(--brand-primary-subtle)' : 'transparent',
              color: currentRoute === 'workspace' ? 'var(--brand-primary)' : 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              position: 'relative',
              transition: 'background-color 0.15s ease, color 0.15s ease',
            }}
          >
            <Sparkles size={18} />
          </button>

          {/* New Workflow Shortcut */}
          <button
            type="button"
            className="rail-nav-btn"
            onClick={onNewWorkflow}
            title="Start New Workflow Draft"
            aria-label="Start New Workflow Draft"
            style={{
              width: '40px',
              height: '40px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              backgroundColor: 'transparent',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background-color 0.15s ease, color 0.15s ease',
            }}
          >
            <Plus size={18} />
          </button>

          {/* My Workflows (Drafts) */}
          <button
            type="button"
            className={`rail-nav-btn ${currentRoute === 'drafts' ? 'active' : ''}`}
            onClick={() => onRouteChange('drafts')}
            title="My Workflows"
            aria-label="My Workflows"
            aria-current={currentRoute === 'drafts' ? 'page' : undefined}
            style={{
              width: '40px',
              height: '40px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              backgroundColor: currentRoute === 'drafts' ? 'var(--brand-primary-subtle)' : 'transparent',
              color: currentRoute === 'drafts' ? 'var(--brand-primary)' : 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background-color 0.15s ease, color 0.15s ease',
            }}
          >
            <FolderGit2 size={18} />
          </button>

          {/* Settings */}
          <button
            type="button"
            className={`rail-nav-btn ${currentRoute === 'settings' ? 'active' : ''}`}
            onClick={() => onRouteChange('settings')}
            title="Settings & Integrations"
            aria-label="Settings & Integrations"
            aria-current={currentRoute === 'settings' ? 'page' : undefined}
            style={{
              width: '40px',
              height: '40px',
              borderRadius: 'var(--radius-sm)',
              border: 'none',
              backgroundColor: currentRoute === 'settings' ? 'var(--brand-primary-subtle)' : 'transparent',
              color: currentRoute === 'settings' ? 'var(--brand-primary)' : 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background-color 0.15s ease, color 0.15s ease',
            }}
          >
            <Settings size={18} />
          </button>
        </nav>
      </div>

      {/* Bottom: Theme Toggle */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
          title={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
          style={{
            width: '36px',
            height: '36px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-default)',
            backgroundColor: 'var(--bg-surface-subtle)',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'background-color 0.15s ease, color 0.15s ease',
          }}
        >
          {theme === 'light' ? <Moon size={15} /> : <Sun size={15} />}
        </button>
      </div>
    </aside>
  );
};
