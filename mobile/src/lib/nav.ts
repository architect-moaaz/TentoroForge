import type { Feather } from '@expo/vector-icons';
import type { ComponentProps } from 'react';

export type IconName = ComponentProps<typeof Feather>['name'];

export interface NavItem {
  key: string;
  label: string;
  icon: IconName;
  /** Platform feature that can be switched off per organisation (shown locked). */
  feature?: string;
}

export interface NavGroup {
  label?: string;
  items: NavItem[];
}

// Same groups, order and labels as the web sidebar
// (frontend/src/app/org/[orgId]/layout.tsx).
export const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { key: 'portal', label: 'Portal', icon: 'globe', feature: 'portal' },
    ],
  },
  {
    label: 'Build',
    items: [
      { key: 'projects', label: 'Projects', icon: 'folder' },
      { key: 'drafts-room', label: 'Drafts Room', icon: 'edit-3', feature: 'drafts_room' },
      { key: 'discover', label: 'Discover', icon: 'star', feature: 'discover' },
      { key: 'templates', label: 'Templates', icon: 'layout', feature: 'templates' },
    ],
  },
  {
    label: 'Organization',
    items: [
      { key: 'people', label: 'People', icon: 'users' },
      { key: 'departments', label: 'Departments', icon: 'briefcase' },
      { key: 'teams', label: 'Teams', icon: 'user-check' },
      { key: 'org-chart', label: 'Org Chart', icon: 'git-merge' },
      { key: 'roles', label: 'Roles', icon: 'shield' },
      { key: 'groups', label: 'Groups', icon: 'users' },
    ],
  },
  {
    items: [
      { key: 'import', label: 'Import', icon: 'upload' },
      { key: 'settings', label: 'Settings', icon: 'settings' },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);
