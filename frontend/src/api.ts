export const API_BASE = (import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "/api" : window.location.origin)).replace(/\/$/, "");

export type Instrument = {
  instrument_uid: string;
  name: string;
  name_ja: string;
  model_number: string | null;
  sample_image_url: string | null;
  category_path: string;
  category_levels: string[];
  status: string;
};

export type Session = {
  session_id: string;
  operator: string;
  location: string;
  lighting: string;
  camera_model: string;
  notes: string;
  started_at: string;
  closed_at: string | null;
};

export type DeclarationItem = {
  instrument_uid: string;
  instrument_name: string;
};

export type Declaration = {
  declaration_id: string;
  session_id: string;
  items: DeclarationItem[];
  instrument_type_count: number;
  confirmed: boolean;
  confirmed_at: string | null;
  arrangement_no: number;
  created_at: string;
  copied_from: string | null;
};

export type ImageRecord = {
  image_id: string;
  declaration_id: string;
  session_id: string;
  arrangement_no: number;
  width: number;
  height: number;
  content_type: string;
  sha256: string;
  captured_at: string;
  meta: Record<string, unknown>;
  tag_status: "untagged" | "tagged";
  tag_revision: number;
  tagged_at: string | null;
  tagged_by: string;
  camera_name: string;
  camera_status: string;
  location: string;
  relative_path: string;
  file_url: string;
};

export type Point = {
  x: number;
  y: number;
  status: "visible" | "estimated";
};

export type Hint = {
  instrument_uid: string;
  hint_source: "manual" | "auto_center" | "none";
  visible: boolean;
  center: Point | null;
  end_a: Point | null;
  end_b: Point | null;
  occluded: boolean;
  added_after_capture: boolean;
};

export type TagIssue = {
  code: string;
  message: string;
  instrument_uid?: string | null;
};

export type TagResult = {
  image_id: string;
  hints: Array<Hint & { instance_no: number; hint_quality: "full" | "center_only" | "none" }>;
  errors: TagIssue[];
  warnings: TagIssue[];
};

export type CameraStatus = {
  state: "closed" | "ready" | "error";
  error: string | null;
  camera_name: string;
};

export class ApiError extends Error {
  status: number;
  issues: TagIssue[];

  constructor(message: string, status: number, issues: TagIssue[] = []) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string; details?: { errors?: TagIssue[] } };
      message?: string;
    } | null;
    const detail = typeof body?.detail === "string" ? body.detail : body?.detail?.message;
    const issues = typeof body?.detail === "object" ? body.detail?.details?.errors ?? [] : [];
    throw new ApiError(detail ?? body?.message ?? `APIエラー (${response.status})`, response.status, issues);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function imageUrl(fileUrl: string): string {
  if (API_BASE.startsWith("/")) {
    return `${API_BASE}${fileUrl.startsWith("/") ? fileUrl : `/${fileUrl}`}`;
  }
  return new URL(fileUrl, `${API_BASE}/`).toString();
}