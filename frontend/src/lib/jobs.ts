// MIT License -- see LICENSE-MIT
//
// Job types and API functions for the RenderTrust job system.
// Maps to backend endpoints: /api/v1/jobs/* and /api/v1/jobs/dispatch

import api from "./api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Job status values matching backend JobStatus enum. */
export type JobStatus =
  | "QUEUED"
  | "DISPATCHED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED";

/** Job type values supported by the scheduler. */
export type JobType = "render" | "inference" | "generic";

/** Priority levels for job submission. */
export type JobPriority = "low" | "normal" | "high";

/** Single job record from the backend. */
export interface Job {
  id: string;
  node_id: string;
  job_type: string;
  payload_ref: string;
  status: JobStatus;
  result_ref: string | null;
  error_message: string | null;
  retry_count: number;
  queued_at: string;
  dispatched_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Paginated job list response. */
export interface JobListResponse {
  jobs: Job[];
  count: number;
}

/** Job dispatch request body. */
export interface DispatchRequest {
  job_type: string;
  payload_ref: string;
}

/** Job dispatch response. */
export interface DispatchResponse {
  job_id: string;
  node_id: string;
  status: string;
}

/** Job result download response. */
export interface JobResultResponse {
  job_id: string;
  download_url: string;
  expires_in: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/** List jobs with optional status filter and pagination. */
export async function fetchJobs(params?: {
  status?: JobStatus;
  limit?: number;
  offset?: number;
}): Promise<JobListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.limit !== undefined)
    searchParams.set("limit", String(params.limit));
  if (params?.offset !== undefined)
    searchParams.set("offset", String(params.offset));

  const query = searchParams.toString();
  const path = `/api/v1/jobs${query ? `?${query}` : ""}`;
  return api.get<JobListResponse>(path);
}

/** Get a single job by ID. */
export async function fetchJob(jobId: string): Promise<Job> {
  return api.get<Job>(`/api/v1/jobs/${jobId}`);
}

/** Submit a new job for dispatch. */
export async function submitJob(
  data: DispatchRequest,
): Promise<DispatchResponse> {
  return api.post<DispatchResponse>("/api/v1/jobs/dispatch", data);
}

/** Cancel a queued or dispatched job. */
export async function cancelJob(jobId: string): Promise<Job> {
  return api.post<Job>(`/api/v1/jobs/${jobId}/cancel`);
}

/** Get a presigned download URL for a completed job's result. */
export async function fetchJobResult(
  jobId: string,
): Promise<JobResultResponse> {
  return api.get<JobResultResponse>(`/api/v1/jobs/${jobId}/result`);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns true if the job is in an active (non-terminal) state. */
export function isJobActive(status: JobStatus): boolean {
  return status === "QUEUED" || status === "DISPATCHED" || status === "RUNNING";
}

/** Returns true if the job can be cancelled. */
export function isJobCancellable(status: JobStatus): boolean {
  return status === "QUEUED" || status === "DISPATCHED";
}

/** Human-readable label for a job status. */
export function statusLabel(status: JobStatus): string {
  const labels: Record<JobStatus, string> = {
    QUEUED: "Queued",
    DISPATCHED: "Dispatched",
    RUNNING: "Running",
    COMPLETED: "Completed",
    FAILED: "Failed",
  };
  return labels[status] ?? status;
}

/** Tailwind CSS classes for a status badge. */
export function statusBadgeClasses(status: JobStatus): string {
  const base =
    "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium";
  const colors: Record<JobStatus, string> = {
    QUEUED: "bg-yellow-100 text-yellow-800",
    DISPATCHED: "bg-blue-100 text-blue-800",
    RUNNING: "bg-blue-100 text-blue-800",
    COMPLETED: "bg-green-100 text-green-800",
    FAILED: "bg-red-100 text-red-800",
  };
  return `${base} ${colors[status] ?? "bg-gray-100 text-gray-800"}`;
}
