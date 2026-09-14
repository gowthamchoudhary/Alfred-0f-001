/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin for the API when the frontend is deployed separately. Empty = same-origin relative paths. */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
