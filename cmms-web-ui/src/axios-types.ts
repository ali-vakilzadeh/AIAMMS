// Type definitions for axios v1.6+
// Simplified type definitions that work with TypeScript bundler mode

export interface AxiosInstance {
  <T = any, R = AxiosResponse<T>, D = any>(config: AxiosRequestConfig<D>): Promise<R>;
  <T = any, R = AxiosResponse<T>, D = any>(url: string, config?: AxiosRequestConfig<D>): Promise<R>;
  create(config?: CreateAxiosDefaults): AxiosInstance;
  Cancel: any;
  CancelToken: any;
  Axios: any;
  AxiosError: any;
  HttpStatusCode: any;
  readonly VERSION: string;
  isCancel: any;
  all: any;
  spread: any;
  isAxiosError: any;
  toFormData: any;
  formToJSON: any;
  getAdapter: any;
  CanceledError: any;
  AxiosHeaders: any;
  mergeConfig: any;
  defaults: any;
  interceptors: any;
  uri: string;
  getUri(config?: AxiosRequestConfig): string;
  request<T = any, R = AxiosResponse<T>, D = any>(config: AxiosRequestConfig<D>): Promise<R>;
  get<T = any, R = AxiosResponse<T>, D = any>(url: string, config?: AxiosRequestConfig<D>): Promise<R>;
  delete<T = any, R = AxiosResponse<T>, D = any>(url: string, config?: AxiosRequestConfig<D>): Promise<R>;
  head<T = any, R = AxiosResponse<T>, D = any>(url: string, config?: AxiosRequestConfig<D>): Promise<R>;
  options<T = any, R = AxiosResponse<T>, D = any>(url: string, config?: AxiosRequestConfig<D>): Promise<R>;
  post<T = any, R = AxiosResponse<T>, D = any>(url: string, data?: D, config?: AxiosRequestConfig<D>): Promise<R>;
  put<T = any, R = AxiosResponse<T>, D = any>(url: string, data?: D, config?: AxiosRequestConfig<D>): Promise<R>;
  patch<T = any, R = AxiosResponse<T>, D = any>(url: string, data?: D, config?: AxiosRequestConfig<D>): Promise<R>;
  postForm<T = any, R = AxiosResponse<T>, D = any>(url: string, data?: D, config?: AxiosRequestConfig<D>): Promise<R>;
  putForm<T = any, R = AxiosResponse<T>, D = any>(url: string, data?: D, config?: AxiosRequestConfig<D>): Promise<R>;
  patchForm<T = any, R = AxiosResponse<T>, D = any>(url: string, data?: D, config?: AxiosRequestConfig<D>): Promise<R>;
}

export class AxiosError<T = unknown, D = any> extends Error {
  config?: InternalAxiosRequestConfig<D>;
  code?: string;
  request?: any;
  response?: AxiosResponse<T, D>;
  status?: number;
  isAxiosError: boolean = true;
  cause?: Error;
  toJSON(): object { return {}; }
}

export interface AxiosResponse<T = any, D = any> {
  data: T;
  status: number;
  statusText: string;
  headers: RawAxiosResponseHeaders | AxiosResponseHeaders;
  config: InternalAxiosRequestConfig<D>;
  request?: any;
}

export interface InternalAxiosRequestConfig<D = any> extends AxiosRequestConfig<D> {
  headers: AxiosRequestHeaders;
}

export interface AxiosRequestConfig<D = any> {
  url?: string;
  method?: string;
  baseURL?: string;
  transformRequest?: any;
  transformResponse?: any;
  headers?: RawAxiosRequestHeaders | AxiosRequestHeaders;
  params?: any;
  paramsSerializer?: any;
  data?: D;
  timeout?: number;
  timeoutErrorMessage?: string;
  withCredentials?: boolean;
  adapter?: any;
  auth?: any;
  responseType?: string;
  responseEncoding?: string;
  xsrfCookieName?: string;
  xsrfHeaderName?: string;
  onUploadProgress?: (progressEvent: any) => void;
  onDownloadProgress?: (progressEvent: any) => void;
  maxContentLength?: number;
  validateStatus?: ((status: number) => boolean) | null;
  maxBodyLength?: number;
  maxRedirects?: number;
  beforeRedirect?: (options: any, responseDetails: any) => void;
  socketPath?: string | null;
  httpAgent?: any;
  httpsAgent?: any;
  proxy?: any;
  cancelToken?: any;
  decompress?: boolean;
  transitional?: any;
  signal?: any;
  insecureHTTPParser?: boolean;
  env?: any;
  formDataEncoder?: any;
  family?: number;
  lookup?: any;
  paramsSerializerOptions?: any;
}

export type AxiosPromise<T = any> = Promise<AxiosResponse<T>>;

type RawAxiosRequestHeaders = Record<string, string>;
type RawAxiosResponseHeaders = Record<string, string>;
type AxiosRequestHeaders = RawAxiosRequestHeaders;
type AxiosResponseHeaders = RawAxiosResponseHeaders;

interface CreateAxiosDefaults<D = any> extends Omit<AxiosRequestConfig<D>, 'headers'> {
  headers?: RawAxiosRequestHeaders | { [Key in string]: string | number | boolean | undefined };
}

// Re-export default axios instance
export { default } from 'axios';
