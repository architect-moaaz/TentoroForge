# Smith for mobile

An Expo (React Native) app for talking to Smith from a phone: sign in, chat, change a built app, and watch it live.
It uses the Forge backend's existing APIs; nothing here changes the backend.

## Run it

```bash
npm install
EXPO_PUBLIC_API_URL=http://<your computer's address>:6500 npx expo start
```

Open the QR code in Expo Go. Without `EXPO_PUBLIC_API_URL` the app uses `http://10.0.2.2:6500` on an Android emulator and `http://localhost:6500` elsewhere.

The backend must listen on an address the phone can reach (for example `0.0.0.0`). Android release builds block plain `http://`, so use https for a shared build.

## Layout

- `src/app` — screens (Expo Router): sign-in, menu, a project's Smith and Live app tabs, one screen per menu item.
- `src/components` — chat, preview, lists and the shared pieces.
- `src/lib` — the API client with login renewal, the live stream, the organisation and its locked features.
- `src/theme.ts`, `src/theme-pref.tsx` — colours and the System / Light / Dark choice.
