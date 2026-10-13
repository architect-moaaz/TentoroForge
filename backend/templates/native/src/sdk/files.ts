// The app SDK (native) — stored files: a picture from the camera or library, a
// document, uploaded to the app's own `/api/files/upload`, which answers the
// stored file's id. An `image` or `file` field HOLDS THAT ID (not a URL), the
// same as on the web; `fileSource(value)` is how to show it.
//
//   const picked = await pickImage("camera");        // null when cancelled; throws a sentence if refused
//   const { id, error } = await uploadFile(picked);  // id goes into the workflow's input
//   <Image source={fileSource(row.photo)} />         // loads it, signed in
//
// `ImageField` / the form's `kind: "image" | "file"` do all of this for a form;
// a screen that wants a custom picker (search by picture: `useSimilar(…, { image: id })`)
// uses these.

import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import { apiFetch, appUrl, cookieHeaderFor } from "./api";
import { filePath } from "./format";

export interface PickedFile {
  uri: string;
  name: string;
  /** MIME type. */
  type: string;
}

export type UploadResult = { id: string; error: null } | { id: null; error: string };

/** A picture, from the camera or the photo library. `null` when the person
 *  cancelled. Throws a sentence when the permission was refused (shown as is). */
export async function pickImage(source: "camera" | "library"): Promise<PickedFile | null> {
  if (source === "camera") {
    const ask = await ImagePicker.requestCameraPermissionsAsync();
    if (!ask.granted) throw new Error("Camera access was declined. Allow the camera for this app in Settings to take a photo.");
  }
  const options: ImagePicker.ImagePickerOptions = { mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.8 };
  const res = source === "camera" ? await ImagePicker.launchCameraAsync(options) : await ImagePicker.launchImageLibraryAsync(options);
  const asset = res.canceled ? null : res.assets[0];
  if (!asset) return null;
  return { uri: asset.uri, name: asset.fileName || `photo-${Date.now()}.jpg`, type: asset.mimeType || "image/jpeg" };
}

/** Any document (a PDF, a spreadsheet). `null` when cancelled. */
export async function pickDocument(): Promise<PickedFile | null> {
  const res = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true });
  const asset = res.canceled ? null : res.assets[0];
  if (!asset) return null;
  return { uri: asset.uri, name: asset.name, type: asset.mimeType || "application/octet-stream" };
}

/** POST /api/files/upload (multipart, a `file` field). Never throws: the id, or the sentence why not. */
export async function uploadFile(file: PickedFile): Promise<UploadResult> {
  const body = new FormData();
  // React Native's FormData takes a { uri, name, type } descriptor in place of a Blob.
  body.append("file", { uri: file.uri, name: file.name, type: file.type } as unknown as Blob);
  try {
    const res = await apiFetch("/api/files/upload", { method: "POST", body });
    const reply = (await res.json().catch(() => null)) as { id?: unknown; error?: unknown } | null;
    if (res.ok && typeof reply?.id === "string" && reply.id) return { id: reply.id, error: null };
    return { id: null, error: typeof reply?.error === "string" && reply.error ? reply.error : "That file could not be uploaded." };
  } catch {
    return { id: null, error: "That file could not be uploaded — check the connection and try again." };
  }
}

/** What an `<Image source={…}>` needs to load a stored file: the app's preview
 *  address, and the session cookie (the platform's image loader has no jar of
 *  ours). A value that is already an outside URL is used as it is; empty is null. */
export function fileSource(value: string | null | undefined): { uri: string; headers?: Record<string, string> } | null {
  const path = filePath(value);
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return { uri: path };
  const uri = appUrl(path);
  const cookie = cookieHeaderFor(uri);
  return cookie ? { uri, headers: { Cookie: cookie } } : { uri };
}
