import { useColorScheme } from 'react-native';

import { useThemePref } from './theme-pref';

// Same look as the web app: Inter, navy primary, indigo accent, slate greys,
// white surfaces, 10px radius. Light values come from
// frontend/src/app/globals.css; dark follows its `.dark` block (near-black
// background, light primary).
export const lightColors = {
  primary: '#1B2A40',
  primaryText: '#ffffff',
  brand: '#6172f3',
  brandSoft: '#eef0fe',
  background: '#ffffff',
  surface: '#ffffff',
  surfaceSecondary: '#f9fafb',
  muted: '#f3f4f6',
  border: '#e5e7eb',
  text: '#111827',
  textSecondary: '#6b7280',
  textTertiary: '#9ca3af',
  slate700: '#334155',
  danger: '#b91c1c',
  dangerBg: '#fef2f2',
  dangerBorder: '#fecaca',
  success: '#15803d',
  successBg: '#dcfce7',
  info: '#1d4ed8',
  infoBg: '#dbeafe',
  violet: '#8b5cf6',
  purple: '#9333ea',
  statusBar: 'dark' as 'dark' | 'light',
};

export type Palette = typeof lightColors;

export const darkColors: Palette = {
  primary: '#e5e5e5',
  primaryText: '#171717',
  brand: '#8098f9',
  brandSoft: '#1e2142',
  background: '#0a0a0a',
  surface: '#171717',
  surfaceSecondary: '#111111',
  muted: '#262626',
  border: '#2e2e2e',
  text: '#fafafa',
  textSecondary: '#a3a3a3',
  textTertiary: '#737373',
  slate700: '#d4d4d8',
  danger: '#f87171',
  dangerBg: '#2a1212',
  dangerBorder: '#7f1d1d',
  success: '#4ade80',
  successBg: '#14532d',
  info: '#93c5fd',
  infoBg: '#1e3a8a',
  violet: '#8b5cf6',
  purple: '#9333ea',
  statusBar: 'light',
};

/** The palette for the person's choice: light, dark, or follow the phone. */
export function useColors(): Palette {
  const system = useColorScheme();
  const { pref } = useThemePref();
  const scheme = pref === 'system' ? system : pref;
  return scheme === 'dark' ? darkColors : lightColors;
}

export const radius = { sm: 6, md: 8, lg: 10, xl: 14, xxl: 20, pill: 999 };

/** Spacing steps. Use these instead of loose numbers so gaps line up everywhere. */
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 28, xxxl: 40 };

/** Icon sizes: small in badges and meta lines, medium in rows, large in empty states. */
export const icon = { sm: 14, md: 18, lg: 22, xl: 36 };

/** Text scale. Each entry is a ready style: spread it, then add a colour.
 *  Big titles use Plus Jakarta Sans for character; everything you read stays in Inter. */
export const type = {
  display: { fontFamily: 'PlusJakartaSans_700Bold', fontSize: 30, lineHeight: 36, letterSpacing: -0.8 },
  title: { fontFamily: 'PlusJakartaSans_700Bold', fontSize: 20, lineHeight: 26, letterSpacing: -0.4 },
  headline: { fontFamily: 'Inter_600SemiBold', fontSize: 16, lineHeight: 22, letterSpacing: -0.1 },
  body: { fontFamily: 'Inter_400Regular', fontSize: 15, lineHeight: 21 },
  callout: { fontFamily: 'Inter_400Regular', fontSize: 14, lineHeight: 20 },
  caption: { fontFamily: 'Inter_400Regular', fontSize: 13, lineHeight: 18 },
  label: { fontFamily: 'Inter_600SemiBold', fontSize: 11, lineHeight: 14, letterSpacing: 0.8 },
} as const;

/** Soft shadows. `card` for resting surfaces, `float` for sheets and floating buttons. */
export const shadow = {
  card: {
    shadowColor: '#0f172a',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  float: {
    shadowColor: '#0f172a',
    shadowOpacity: 0.12,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 8 },
    elevation: 6,
  },
};

/** Smallest comfortable touch size (Apple and Google both say about 44). */
export const touch = 44;

export const font = {
  regular: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semibold: 'Inter_600SemiBold',
  bold: 'Inter_700Bold',
  display: 'PlusJakartaSans_700Bold',
};

export function statusStyle(c: Palette, status: string): { bg: string; fg: string } {
  switch (status) {
    case 'generating':
    case 'pending':
    case 'brief_ready':
      return { bg: c.infoBg, fg: c.info };
    case 'ready':
    case 'active':
    case 'accepted':
    case 'converted':
    case 'agreed':
    case 'completed':
      return { bg: c.successBg, fg: c.success };
    case 'error':
    case 'abandoned':
    case 'escalated':
    case 'inactive':
      return { bg: c.dangerBg, fg: c.danger };
    default:
      return { bg: c.muted, fg: c.textSecondary };
  }
}
