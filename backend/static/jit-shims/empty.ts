// A module the JIT preview does not need (server-only): every export is a no-op.
const noop: any = new Proxy(() => undefined, { get: () => noop, apply: () => undefined });
export default noop;
export const auth = async () => null;
export const cookies = () => ({ get: () => undefined, getAll: () => [] });
export const headers = () => new Map();
