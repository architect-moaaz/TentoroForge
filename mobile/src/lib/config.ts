import { Platform } from 'react-native';

// The Android emulator reaches the computer at 10.0.2.2 ("localhost" there is
// the emulator itself). A real phone needs EXPO_PUBLIC_API_URL set to a public
// address, for example a tunnel to the Forge backend.
const fallback = Platform.OS === 'android' ? 'http://10.0.2.2:6500' : 'http://localhost:6500';

export const API_BASE = (process.env.EXPO_PUBLIC_API_URL ?? fallback).replace(/\/$/, '');
