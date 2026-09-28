/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_APP_NAME: string;
  readonly VITE_APP_VERSION: string;
  readonly VITE_ENABLE_AI: string;
  readonly VITE_ENABLE_AUDIT_LOG: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
